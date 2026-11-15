"""Descarga AUTOMÁTICA de datos reales: arranca sola con la app, en segundo plano, sin comandos ni cuentas.

Para cada una de las 8 zonas del piloto (y para los puntos libres que alguien haya escogido en el mapa):
  1. Clima de 20 años de NASA POWER (lluvia, temperaturas, humedad del suelo, temperatura de la superficie),
     verdor normal de cada mes (NDVI de MODIS por la API de ORNL DAAC) y pendiente (elevación SRTM).
     Se vuelve a descargar cada 30 días.
  2. Últimos ~7 meses de NASA POWER y NDVI reciente, para "Últimos 6 meses" y la lluvia día por día (cada día).
Luego, si hace falta: catálogo de estaciones del IDEAM (cada 30 días), USDA PLANTS (una vez) y Copernicus CDS
(solo si hay credenciales en ~/.cdsapirc o en CDSAPI_URL y CDSAPI_KEY, y está instalado cdsapi).

Si no hay internet, la app sigue con los datos guardados (o los de ejemplo) y vuelve a intentar cada 30 minutos.
Para apagar la descarga automática: variable de entorno AGROSTAKE_SIN_DESCARGA=1."""
import json, os, threading, time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import db
from services import descargas

DIAS_CLIMA = 30
HILOS = int(os.environ.get("AGROSTAKE_HILOS", "2"))   # zonas que se descargan a la vez (Render gratis: 0,1 de CPU)
_cola, _prioridad = deque(), set()
CADA_HORAS = 6
REINTENTO_MIN = 30
POR_DEFECTO = {"ndvi_mensual": [.55] * 12, "pendiente_pct": 3, "humedad_suelo_pct": 30}   # último recurso, típico de tierras bajas

ESTADO = {"activo": False, "fase": "esperando", "hechas": 0, "total": 0, "errores": [], "sin_internet": None,
          "ultima": None, "apagado": False, "listas": [], "en_curso": [], "puntos": {}}
_lock = threading.Lock()
_hilo = None
_hilos_punto = {}

def _desactivado(): return os.environ.get("AGROSTAKE_SIN_DESCARGA") == "1"

def _fase(texto, **kw):
    with _lock: ESTADO.update(fase=texto, **kw)

def _error(donde, e):
    with _lock:
        ESTADO["errores"] = (ESTADO["errores"] + [{"donde": donde, "error": str(e)[:200], "hora": datetime.now().strftime("%H:%M")}])[-12:]

def _clima_guardado(zid):
    f = db.consultar("SELECT datos, verificado FROM clima WHERE zona_id=?", (zid,))
    return (json.loads(f[0]["datos"]), bool(f[0]["verificado"])) if f else (None, False)

def _fresco(d, dias):
    try: return d and (date.today() - date.fromisoformat(d.get("descargado", "2000-01-01"))).days < dias
    except ValueError: return False

def clima_completo(lat, lon, anios=20, respaldo=None):
    """Clima real de NASA para el punto. Lo que no se pueda descargar se toma del respaldo (la zona más cercana
    o el ejemplo) y queda listado en campos_ejemplo, para que la app lo diga."""
    from services import nasa                       # importa el motor; se carga solo cuando hace falta
    d = nasa.construir(lat, lon, anios)
    fuentes, faltan = [d["fuente"]], []
    try:
        n = descargas.ndvi_mensual(lat, lon)
        d["ndvi_mensual"] = n["ndvi_mensual"]; fuentes.append(f"NDVI de {n['producto']} (NASA, ORNL DAAC)")
    except Exception as e:
        faltan.append("ndvi_mensual"); _error("NDVI MODIS", e)
    try:
        p = descargas.pendiente(lat, lon, timeout=12)      # Open-Elevation a veces se cuelga: no esperarla 40 s
        d["pendiente_pct"], d["elevacion_m"] = p["pendiente_pct"], p["elevacion_m"]; fuentes.append(f"pendiente: {p['fuente']}")
    except Exception as e:
        faltan.append("pendiente_pct"); _error("Elevación", e)
    if d.get("humedad_suelo_pct") is None: faltan.append("humedad_suelo_pct")
    resp = respaldo or {}
    for k in faltan: d[k] = resp.get(k) if resp.get(k) is not None else POR_DEFECTO[k]
    d.update(campos_ejemplo=faltan, fuente="; ".join(fuentes), descargado=date.today().isoformat())
    return d

def _respaldo(zid, lat, lon):
    try:
        ej = db._leer("clima_ejemplo.json")
        if zid in ej: return ej[zid]
    except Exception:
        pass
    from services import motor
    zc, _ = motor.zona_cercana(lat, lon)
    return _clima_guardado(zc["id"])[0] or {}

def actualizar(zid, lat, lon, anios=20, forzar=False):
    """Descarga (si hace falta) el clima completo y los datos recientes de una zona o punto. Devuelve el estado."""
    d, ok = _clima_guardado(zid)
    hecho = {"zona": zid, "clima": "guardado"}
    if forzar or not ok or not _fresco(d, DIAS_CLIMA):
        nuevo = clima_completo(lat, lon, anios, respaldo=_respaldo(zid, lat, lon))
        db.guardar("clima", {"zona_id": zid, "datos": json.dumps(nuevo)}, 1, nuevo["fuente"])
        hecho.update(clima="descargado", faltan=nuevo["campos_ejemplo"])
    try:
        descargas.recientes(lat, lon)
        hecho["recientes"] = "ok"
    except Exception as e:
        hecho["recientes"] = "error"; _error(f"recientes {zid}", e)
    return hecho

COPIA_REAL = os.path.join(db.BASE, "data", "clima_real.json")
def _copia_real():
    """Guarda en data/clima_real.json los datos reales ya descargados de las zonas. Si ese archivo se sube junto con
    el código (por ejemplo a Render, que borra el disco cada vez que el servicio se duerme o reinicia), la app arranca
    con datos reales desde el primer segundo y solo baja lo reciente."""
    filas = db.consultar("SELECT zona_id, datos FROM clima WHERE verificado=1 AND zona_id NOT LIKE 'p:%'")
    if not filas: return
    datos = {"nota": "Copia automática de los datos reales de la NASA (la crea services/sincronizar.py).",
             "fecha": date.today().isoformat(), "zonas": {f["zona_id"]: json.loads(f["datos"]) for f in filas}}
    tmp = COPIA_REAL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(json.dumps(datos, ensure_ascii=False))
    os.replace(tmp, COPIA_REAL)

def _extras():
    from services import ideam, usda, copernicus
    if not os.path.exists(ideam.CACHE) or time.time() - os.path.getmtime(ideam.CACHE) > DIAS_CLIMA * 86400:
        _fase("Estaciones del IDEAM")
        try: ideam.descargar()
        except Exception as e: _error("IDEAM", e)
    if not os.path.exists(usda.SALIDA):
        _fase("USDA PLANTS")
        try: usda.importar(db)
        except Exception as e: _error("USDA", e)
    cds = os.path.exists(os.path.expanduser("~/.cdsapirc")) or (os.environ.get("CDSAPI_URL") and os.environ.get("CDSAPI_KEY"))
    if cds and (not os.path.exists(copernicus.SALIDA) or time.time() - os.path.getmtime(copernicus.SALIDA) > 90 * 86400):
        try:
            import cdsapi  # noqa: F401
            _fase("Copernicus CDS (ERA5-Land)")
            copernicus.importar([dict(r) for r in db.consultar("SELECT id, lat, lon FROM zonas")], 10)
        except Exception as e:
            _error("Copernicus", e)

def priorizar(zid):
    """La zona que el agricultor está mirando (llamado desde /api/panel): si la descarga está en curso y esa zona
    todavía no empieza, arranca YA en su propio hilo; si la descarga no ha empezado, irá de primera."""
    z = None
    with _lock:
        _prioridad.add(zid)
        for i, x in enumerate(_cola):
            if x["id"] == zid: z = x; del _cola[i]; break
    if z: threading.Thread(target=_procesar, args=(z,), name=f"agrostake-{zid}", daemon=True).start()

def descargar_punto(zid, lat, lon, espera=6):
    """Punto libre del mapa: descarga su clima (10 años) en un hilo aparte. Espera como mucho `espera` segundos
    para no frenar al servidor; si no alcanza, sigue sola y al terminar queda en ESTADO["puntos"] ("listo" o "error"),
    que la app consulta en /api/estado_datos. Devuelve True si ya terminó."""
    with _lock:
        h = _hilos_punto.get(zid)
        if not (h and h.is_alive()):
            ESTADO["puntos"].pop(zid, None)
            ESTADO["en_curso"] = sorted(set(ESTADO.get("en_curso", [])) | {zid})
            h = threading.Thread(target=_punto, args=(zid, lat, lon), name=f"agrostake-{zid}", daemon=True)
            _hilos_punto[zid] = h; h.start()
    h.join(espera)
    return not h.is_alive()

def _punto(zid, lat, lon):
    try: actualizar(zid, lat, lon, anios=10); res = "listo"
    except Exception as e: _error(zid, e); res = "error"
    with _lock:
        ESTADO["en_curso"] = [x for x in ESTADO.get("en_curso", []) if x != zid]
        ESTADO["puntos"][zid] = res
        if len(ESTADO["puntos"]) > 50: ESTADO["puntos"].pop(next(iter(ESTADO["puntos"])))

def _siguiente():
    with _lock:
        return _cola.popleft() if _cola else None

def _procesar(z):
    with _lock: ESTADO["en_curso"] = sorted(set(ESTADO.get("en_curso", [])) | {z["id"]})
    try: actualizar(z["id"], float(z["lat"]), float(z["lon"]))
    except Exception as e: _error(z["id"], e)
    with _lock:
        ESTADO["hechas"] += 1; ESTADO["en_curso"] = [x for x in ESTADO.get("en_curso", []) if x != z["id"]]
        ESTADO["listas"] = sorted(set(ESTADO.get("listas", [])) | {z["id"]})
        ESTADO["fase"] = f"Datos de la NASA: {ESTADO['hechas']} de {ESTADO['total']} zonas"

def _trabajador():
    while True:
        z = _siguiente()
        if not z: return
        _procesar(z)

def ciclo_una_vez():
    if not descargas.hay_internet():
        _fase("Sin internet: se usan los datos guardados", sin_internet=True, activo=False)
        return False
    zonas = db.consultar("SELECT id, lat, lon FROM zonas")
    puntos = [r["zona_id"] for r in db.consultar("SELECT zona_id FROM clima WHERE zona_id LIKE 'p:%' LIMIT 20")]
    with _lock:
        primero = [z for z in zonas if z["id"] in _prioridad]          # las que alguien está mirando van primero
        _cola.clear(); _cola.extend(primero + [z for z in zonas if z["id"] not in _prioridad])
        ESTADO.update(activo=True, sin_internet=False, hechas=0, total=len(zonas), errores=[], en_curso=[], listas=[],
                      fase=f"Datos de la NASA: 0 de {len(zonas)} zonas")
    with ThreadPoolExecutor(max_workers=HILOS) as ex:                  # varias zonas a la vez
        for _ in range(HILOS): ex.submit(_trabajador)
    while True:                                                         # espera a las zonas que arrancaron aparte (prioridad)
        with _lock:
            if ESTADO["hechas"] >= ESTADO["total"] or not ESTADO.get("en_curso"): break
        time.sleep(.5)
    from services import motor
    for pid in puntos:
        try:
            lat, lon = motor.punto_coords(pid)
            actualizar(pid, lat, lon, anios=10)
        except Exception as e:
            _error(pid, e)
    try: _copia_real()
    except Exception as e: _error("copia de datos reales", e)
    _extras()
    with _lock: ESTADO.update(activo=False, fase="Datos al día", ultima=datetime.now().isoformat(timespec="minutes"))
    return True

def _bucle():
    time.sleep(2)
    while True:
        try: ok = ciclo_una_vez()
        except Exception as e:
            _error("ciclo", e); ok = False
            with _lock: ESTADO["activo"] = False
        time.sleep(CADA_HORAS * 3600 if ok else REINTENTO_MIN * 60)

def iniciar():
    """Arranca el hilo una sola vez (es seguro llamarla en cada petición)."""
    global _hilo
    if _desactivado():
        ESTADO.update(apagado=True, fase="Descarga automática apagada (AGROSTAKE_SIN_DESCARGA=1)")
        return
    with _lock:
        if _hilo and _hilo.is_alive(): return
        _hilo = threading.Thread(target=_bucle, name="agrostake-descargas", daemon=True)
        _hilo.start()

def estado():
    with _lock: e = json.loads(json.dumps(ESTADO))
    filas = db.consultar("SELECT zona_id, verificado, datos FROM clima WHERE zona_id NOT LIKE 'p:%'")
    reales = 0
    for f in filas:
        try: reales += bool(f["verificado"]) and not json.loads(f["datos"]).get("campos_ejemplo")
        except ValueError: pass
    e.update(zonas_reales=sum(1 for f in filas if f["verificado"]), zonas_completas=reales, zonas=len(filas))
    return e
