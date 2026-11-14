"""Estacas (ESP32-S3 con sensores): registro, lecturas, conversión a datos de suelo y datos abiertos.

Cada estaca pertenece a un usuario y tiene un token propio. El token solo se muestra una vez al crearla;
en la base de datos se guarda su huella SHA-256, así que si alguien copia la base no puede hacerse pasar por la estaca.

Datos abiertos: solo salen lecturas de usuarios que autorizaron compartir (compartir_datos = 1), sin nombre ni correo,
con un código de estaca seudónimo y la ubicación redondeada a 0,01° (unos 1,1 km)."""
import csv, hashlib, io, secrets
from datetime import datetime, timedelta, timezone
import db

CAMPOS = ("ph", "humedad_pct", "temp_suelo_c", "ce_us_cm", "n_mg_kg", "p_mg_kg", "k_mg_kg",
          "temp_aire_c", "humedad_aire_pct", "bateria_v", "rssi_dbm")
RANGOS = {"ph": (0, 14), "humedad_pct": (0, 100), "temp_suelo_c": (-10, 70), "ce_us_cm": (0, 20000),
          "n_mg_kg": (0, 2000), "p_mg_kg": (0, 2000), "k_mg_kg": (0, 5000), "temp_aire_c": (-20, 60),
          "humedad_aire_pct": (0, 100), "bateria_v": (0, 6), "rssi_dbm": (-130, 0)}
# Umbrales APROXIMADOS para pasar mg/kg a bajo/medio/alto. Dependen del método de análisis y del sensor:
# ajústalos con un agrónomo o con la hoja de datos de tu sensor.
UMBRAL_NPK = {"n": (20, 40), "p": (10, 30), "k": (100, 200)}
# 4 dS/m (4000 µS/cm) es el umbral clásico de suelo salino, medido en extracto de saturación.
# Los sensores de campo miden la conductividad del suelo tal cual, que suele dar valores más bajos: calíbralo.
UMBRAL_SAL_US_CM = 4000
MAX_LOTE = 100          # lecturas por envío
MAX_EDAD_S = 7 * 86400  # una lectura guardada en la estaca puede tener hasta 7 días

def _hash(t): return hashlib.sha256(t.encode()).hexdigest()
def _ahora(): return datetime.now(timezone.utc).replace(microsecond=0)

def crear(usuario_id, nombre, lote=1, lat=None, lon=None):
    token = "est_" + secrets.token_urlsafe(24)
    eid = db.ejecutar("INSERT INTO estacas(usuario_id,nombre,lote,lat,lon,token_hash) VALUES(?,?,?,?,?,?)",
                      (usuario_id, nombre.strip()[:60] or "Estaca", int(lote), lat, lon, _hash(token)))
    return eid, token

def borrar(usuario_id, estaca_id):
    return db.ejecutar("DELETE FROM estacas WHERE id=? AND usuario_id=?", (estaca_id, usuario_id))

def por_token(token):
    f = db.consultar("SELECT * FROM estacas WHERE token_hash=?", (_hash(token or ""),))
    return f[0] if f else None

def _limpiar(l):
    out = {}
    for k in CAMPOS:
        v = l.get(k)
        if v is None or v == "": continue
        v = float(v)
        a, b = RANGOS[k]
        if not a <= v <= b: raise ValueError(f"{k}={v} fuera de rango ({a} a {b})")
        out[k] = round(v, 3)
    if not out: raise ValueError("la lectura no trae ningún valor")
    edad = int(l.get("edad_s", 0) or 0)
    if not 0 <= edad <= MAX_EDAD_S: raise ValueError("edad_s fuera de rango")
    out["fecha"] = (_ahora() - timedelta(seconds=edad)).isoformat()
    return out

def guardar_lecturas(estaca, lecturas):
    """lecturas: lista de dicts con los CAMPOS y opcionalmente edad_s (segundos desde que se midió)."""
    if not isinstance(lecturas, list) or not lecturas: raise ValueError("se esperaba una lista de lecturas")
    if len(lecturas) > MAX_LOTE: raise ValueError(f"máximo {MAX_LOTE} lecturas por envío")
    filas = [_limpiar(l) for l in lecturas]
    cols = ("fecha",) + CAMPOS
    db.ejecutar_varios(f"INSERT INTO lecturas(estaca_id,{','.join(cols)}) VALUES(?,{','.join('?' * len(cols))})",
                       [(estaca["id"],) + tuple(f.get(c) for c in cols) for f in filas])
    db.ejecutar("UPDATE estacas SET ultima_vez=? WHERE id=?", (_ahora().isoformat(), estaca["id"]))
    return len(filas)

def ultima(estaca_id):
    f = db.consultar("SELECT * FROM lecturas WHERE estaca_id=? ORDER BY fecha DESC LIMIT 1", (estaca_id,))
    return f[0] if f else None

def listar(usuario_id):
    out = []
    for e in db.consultar("SELECT id,nombre,lote,lat,lon,creada_en,ultima_vez FROM estacas WHERE usuario_id=? ORDER BY lote,id", (usuario_id,)):
        u = ultima(e["id"])
        out.append(dict(e, ultima=u, suelo=a_suelo(u) if u else None))
    return out

def lecturas(usuario_id, estaca_id, dias=30):
    if not db.consultar("SELECT 1 FROM estacas WHERE id=? AND usuario_id=?", (estaca_id, usuario_id)): return None
    desde = (_ahora() - timedelta(days=max(1, min(365, dias)))).isoformat()
    return db.consultar("SELECT * FROM lecturas WHERE estaca_id=? AND fecha>=? ORDER BY fecha", (estaca_id, desde))

def _clase(v, umbrales):
    a, b = umbrales
    return "bajo" if v < a else "medio" if v < b else "alto"

def a_suelo(l):
    """Convierte una lectura de la estaca en los datos de suelo que usa el motor (solo los que vengan)."""
    s = {}
    for k in ("ph", "humedad_pct", "temp_suelo_c"):
        if l.get(k) is not None: s[k] = round(l[k], 1)
    for k in ("n", "p", "k"):
        if l.get(f"{k}_mg_kg") is not None: s[k] = _clase(l[f"{k}_mg_kg"], UMBRAL_NPK[k])
    if l.get("ce_us_cm") is not None: s["salinidad"] = "alta" if l["ce_us_cm"] >= UMBRAL_SAL_US_CM else "normal"
    return s

def datos_abiertos(sal, desde, hasta, limite=50000):
    """Lecturas anónimas de usuarios que autorizaron compartir."""
    filas = db.consultar(f"""SELECT l.*, e.lat, e.lon FROM lecturas l JOIN estacas e ON e.id = l.estaca_id
                             JOIN usuarios u ON u.id = e.usuario_id
                             WHERE u.compartir_datos = 1 AND l.fecha >= ? AND l.fecha < ? ORDER BY l.fecha LIMIT ?""",
                         (desde, hasta, limite))
    out = []
    for f in filas:
        out.append({"estaca": hashlib.sha256(f"{sal}:{f['estaca_id']}".encode()).hexdigest()[:12],
                    "fecha_utc": f["fecha"], "lat": round(f["lat"], 2) if f["lat"] is not None else None,
                    "lon": round(f["lon"], 2) if f["lon"] is not None else None, **{k: f[k] for k in CAMPOS if k not in ("bateria_v", "rssi_dbm")}})
    return out

def a_csv(filas):
    cols = ["estaca", "fecha_utc", "lat", "lon"] + [k for k in CAMPOS if k not in ("bateria_v", "rssi_dbm")]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader(); w.writerows(filas)
    return buf.getvalue()
