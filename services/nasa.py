"""Clima real de una zona desde NASA POWER (API diaria, comunidad AG), con caché en disco.

Variables de POWER: T2M, T2M_MAX, T2M_MIN, PRECTOTCORR y GWETROOT.
Con ellas se calculan todos los campos que usa el motor: lluvia y temperatura por mes, evaporación (Hargreaves,
FAO-56), días de estrés térmico (> 35 °C), heladas (<= 0 °C), lluvias extremas (>= 50 mm en un día), veranillo,
humedad del suelo, año seco y tendencias de largo plazo.

No vienen de POWER y se conservan del archivo de ejemplo hasta conectar su fuente:
ndvi_mensual (MODIS, por ejemplo con AppEEARS) y pendiente_pct (NASADEM).

Uso: python importar.py nasa [años]   (por defecto 20 años completos hasta el año pasado)."""
import json, os
from collections import defaultdict
from datetime import date
import requests
from services.motor import et0, MC

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
VARS = ("T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "GWETROOT")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache")
FALTA = -999

def _fetch(lat, lon, ini, fin):
    params = {"parameters": ",".join(VARS), "community": "AG", "latitude": lat, "longitude": lon,
              "start": f"{ini}0101", "end": f"{fin}1231", "format": "JSON"}
    r = requests.get(URL, params=params, timeout=180)
    r.raise_for_status()
    return r.json()["properties"]["parameter"]

def construir(lat, lon, anios=20, hoy=None):
    hoy = hoy or date.today()
    fin = hoy.year - 1
    ini = fin - anios + 1
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, f"power_{round(lat, 2)}_{round(lon, 2)}_{ini}_{fin}.json")
    if os.path.exists(ruta):
        p = json.load(open(ruta, encoding="utf-8"))
    else:
        p = _fetch(lat, lon, ini, fin)
        json.dump(p, open(ruta, "w", encoding="utf-8"))
    return calcular(p, lat, ini, fin)

def _ok(v): return v is not None and v > FALTA

def _pendiente(xs, ys):
    n = len(xs); mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0

def calcular(p, lat, ini, fin):
    """Convierte la serie diaria de POWER en el diccionario de clima que usa el motor."""
    dias = []
    for k in sorted(p["PRECTOTCORR"]):
        t, tx, tn, pr = (p[v].get(k) for v in ("T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR"))
        if all(_ok(x) for x in (t, tx, tn, pr)):
            dias.append({"a": int(k[:4]), "m": int(k[4:6]), "t": t, "tx": tx, "tn": tn, "pr": pr, "gw": p["GWETROOT"].get(k)})
    if not dias: raise ValueError("NASA POWER no devolvió datos válidos para este punto")
    anios = sorted({d["a"] for d in dias}); na = len(anios)
    por_mes, anios_mes = defaultdict(list), defaultdict(set)
    lluvia_anio, temp_anio = defaultdict(float), defaultdict(list)
    for d in dias:
        por_mes[d["m"]].append(d); anios_mes[d["m"]].add(d["a"])
        lluvia_anio[d["a"]] += d["pr"]; temp_anio[d["a"]].append(d["t"])
    med = lambda xs: sum(xs) / len(xs)
    ll, tm, tx, tn, ev = [], [], [], [], []
    for m in range(1, 13):
        ds, ya = por_mes[m], max(1, len(anios_mes[m]))
        ll.append(round(sum(d["pr"] for d in ds) / ya))
        tm.append(round(med([d["t"] for d in ds]), 1)); tx.append(round(med([d["tx"] for d in ds]), 1)); tn.append(round(med([d["tn"] for d in ds]), 1))
        ev.append(round(sum(et0(d["t"], d["tx"], d["tn"], lat, m) for d in ds) / ya))
    # Inicio de lluvias: el mes en que la lluvia sube y pasa el umbral (el mayor salto)
    umbral = max(80, sum(ll) / 12)
    saltos = [(ll[m] - ll[m - 1], m) for m in range(12) if ll[m - 1] < umbral <= ll[m]] or [(ll[m] - ll[m - 1], m) for m in range(12)]
    inicio = max(saltos)[1] + 1
    temporada = {(inicio - 1 + i) % 12 + 1 for i in range(8)}
    # Veranillo: racha más larga de días secos (< 1 mm) dentro de la temporada de lluvias, promedio de los años
    rachas = []
    for a in anios:
        mejor = act = 0
        for d in dias:
            if d["a"] != a or d["m"] not in temporada: continue
            act = act + 1 if d["pr"] < 1 else 0
            mejor = max(mejor, act)
        rachas.append(mejor)
    veranillo = round(med(rachas))
    totales = [lluvia_anio[a] for a in anios]
    media_ll = med(totales)
    tend_ll = _pendiente(anios, totales) * (na - 1) / media_ll * 100 if na > 2 else 0
    tend_t = _pendiente(anios, [med(temp_anio[a]) for a in anios]) * (na - 1) if na > 2 else 0
    gw = [d["gw"] for d in dias if _ok(d["gw"])]
    return {"lluvia_mensual_mm": ll, "temp_mensual": tm, "tmax_mensual": tx, "tmin_mensual": tn, "evap_mensual_mm": ev,
            "temp_media": round(med([d["t"] for d in dias]), 1), "tmax_media": round(med([d["tx"] for d in dias]), 1),
            "tmin_media": round(med([d["tn"] for d in dias]), 1), "tmin_absoluta": round(min(d["tn"] for d in dias), 1),
            "dias_estres_termico": round(sum(1 for d in dias if d["tx"] > 35) / na),
            "dias_helada": round(sum(1 for d in dias if d["tn"] <= 0) / na, 1),
            "dias_lluvia_extrema": round(sum(1 for d in dias if d["pr"] >= 50) / na, 1),
            "lluvia_max_dia_mm": round(max(d["pr"] for d in dias)),
            "humedad_suelo_pct": round(med(gw) * 100) if gw else None,
            "inicio_lluvias_mes": inicio, "dias_veranillo": veranillo,
            "riesgo_veranillo": "bajo" if veranillo < 15 else "medio" if veranillo < 30 else "alto",
            "tendencia_lluvia_pct": round(tend_ll), "tendencia_temp_c": round(tend_t, 1),
            "factor_ano_seco": round(min(totales) / media_ll, 2),
            "periodo": f"{ini}-{fin}", "fuente": f"NASA POWER (MERRA-2), datos diarios {ini}-{fin}",
            "mes_inicio_nombre": MC[inicio - 1]}
