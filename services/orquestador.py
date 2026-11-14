"""Orquestador de datos externos para un punto (lote): versión revisada del código del equipo.

Fuentes (cada una es opcional; si falla o no está configurada, las demás siguen):
  1. NASA POWER        clima diario reciente (no pide cuenta)
  2. ISRIC SoilGrids   suelo 0 a 30 cm: pH, carbono orgánico, arcilla, arena, CIC (no pide cuenta; uso moderado)
  3. Google Earth Engine  pendiente (SRTM) y NDVI/NDWI (Landsat 9). Pide: pip install earthengine-api,
                       autenticación y GEE_PROJECT
  4. NASA AppEEARS     temperatura de superficie a 70 m (ECOSTRESS) y humedad del suelo (SMAP L4).
                       Pide EARTHDATA_USER y EARTHDATA_PASS. Es ASÍNCRONO: la tarea tarda de minutos a horas,
                       por eso aquí solo se envía y se consulta su estado; no bloquea la app.
  5. Precios (Socrata, datos.gov.co)  pide SOCRATA_DATASET con el ID del conjunto de datos.

Cambios frente al código original:
  - ECO2LSTE.001 fue retirado el 21 de mayo de 2025 y SPL4SMGP.007 salió de AppEEARS en junio de 2025:
    ahora se usan ECO_L2T_LSTE.002 y SPL4SMGP.008. Antes de enviar la tarea se consultan las capas que de
    verdad tiene cada producto en AppEEARS, y si un nombre no existe se avisa con la lista disponible.
  - El producto de evapotranspiración de ECOSTRESS v001 quedó fuera; la evaporación se calcula con NASA POWER.
  - SoilGrids: el promedio de 0 a 30 cm ahora pesa cada capa por su grosor (5, 10 y 15 cm) y usa el factor
    de conversión que devuelve la API.
  - Landsat 9: se enmascaran nubes y sombras con QA_PIXEL (bits 1, 3 y 4), no solo con CLOUD_COVER.
  - La pendiente se entrega también en porcentaje, que es lo que usa el motor.
  - Las credenciales salen de variables de entorno, nunca del código.
  - El texto de la ciudad para la consulta de precios se limpia para evitar inyección en la consulta.
  - Earth Engine se importa solo si se usa, para que la app arranque aunque no esté instalado.
"""
import math, os, re, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import requests

TIMEOUT = 30
APPEEARS = "https://appeears.earthdatacloud.nasa.gov/api"
CAPAS_APPEEARS = [("ECO_L2T_LSTE.002", "LST"), ("SPL4SMGP.008", "sm_surface"), ("SPL4SMGP.008", "sm_rootzone")]

# ------------------------------------------------------------------ 1. NASA POWER
def nasa_power(lat, lon, inicio, fin):
    """Fechas YYYYMMDD. Resumen del periodo."""
    r = requests.get("https://power.larc.nasa.gov/api/temporal/daily/point", timeout=TIMEOUT, params={
        "parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR", "community": "AG", "latitude": lat, "longitude": lon,
        "start": inicio, "end": fin, "format": "JSON"})
    r.raise_for_status()
    p = r.json()["properties"]["parameter"]
    ok = lambda v: v is not None and v > -999
    tx = [v for v in p["T2M_MAX"].values() if ok(v)]
    tn = [v for v in p["T2M_MIN"].values() if ok(v)]
    ll = [v for v in p["PRECTOTCORR"].values() if ok(v)]
    return {"temp_max_prom_c": round(sum(tx) / len(tx), 1) if tx else None,
            "temp_min_prom_c": round(sum(tn) / len(tn), 1) if tn else None,
            "dias_helada": sum(1 for t in tn if t <= 0), "dias_calor": sum(1 for t in tx if t > 35),
            "lluvia_total_mm": round(sum(ll)) if ll else None, "dias_lluvia": sum(1 for v in ll if v >= 1),
            "dias_lluvia_extrema": sum(1 for v in ll if v >= 50), "dias_con_datos": len(ll)}

# ------------------------------------------------------------------ 2. ISRIC SoilGrids
def soilgrids(lat, lon):
    params = [("lon", lon), ("lat", lat)] + [("property", x) for x in ("phh2o", "soc", "clay", "sand", "cec")] + \
             [("depth", d) for d in ("0-5cm", "5-15cm", "15-30cm")] + [("value", "mean")]
    r = requests.get("https://rest.isric.org/soilgrids/v2.0/properties/query", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    out = {}
    for capa in r.json()["properties"]["layers"]:
        factor = (capa.get("unit_measure") or {}).get("d_factor") or 10
        suma = peso = 0.0
        for d in capa["depths"]:
            v = d["values"].get("mean")
            if v is None: continue
            rg = d.get("range") or {}
            if "bottom_depth" in rg: g = rg["bottom_depth"] - rg["top_depth"]   # grosor de la capa en cm
            else: a_, b_ = re.findall(r"\d+", d.get("label", "0-1cm"))[:2]; g = int(b_) - int(a_)
            suma += v / factor * g; peso += g
        out[capa["name"]] = round(suma / peso, 2) if peso else None
    arc, are = out.get("clay"), out.get("sand")                           # en %
    textura = None
    if arc is not None and are is not None:   # aproximación a grupos gruesos de textura
        textura = "arcilloso" if arc >= 35 else "arenoso" if are >= 60 and arc < 15 else "franco"
    soc = out.get("soc")                                                  # g/kg
    return {"ph": out.get("phh2o"), "arcilla_pct": arc, "arena_pct": are, "cic_cmol_kg": out.get("cec"),
            "carbono_organico_g_kg": soc, "materia_organica_pct": round(soc / 10 * 1.724, 2) if soc is not None else None,
            "textura": textura, "nota": "Estimaciones de mapas globales a unos 250 m; confírmalas con un análisis de laboratorio."}

# ------------------------------------------------------------------ 3. Google Earth Engine
_ee_listo = False
def _ee():
    global _ee_listo
    import ee                                     # pip install earthengine-api
    if not _ee_listo:
        proyecto = os.environ.get("GEE_PROJECT")
        ee.Initialize(project=proyecto) if proyecto else ee.Initialize()
        _ee_listo = True
    return ee

def gee(lat, lon, inicio, fin, radio_m=150):
    """Fechas YYYY-MM-DD. Pendiente media (SRTM 30 m) y NDVI/NDWI medios de Landsat 9 sin nubes."""
    ee = _ee()
    zona = ee.Geometry.Point([lon, lat]).buffer(radio_m)
    pend = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003")).reduceRegion(ee.Reducer.mean(), zona, 30).getInfo().get("slope")

    def preparar(img):
        qa = img.select("QA_PIXEL")
        limpio = qa.bitwiseAnd(1 << 1).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0)).And(qa.bitwiseAnd(1 << 4).eq(0))
        sr = img.select(["SR_B4", "SR_B5", "SR_B6"]).multiply(0.0000275).add(-0.2)
        ndvi = sr.normalizedDifference(["SR_B5", "SR_B4"]).rename("NDVI")
        ndwi = sr.normalizedDifference(["SR_B5", "SR_B6"]).rename("NDWI")   # NDWI de Gao: agua en la vegetación
        return ndvi.addBands(ndwi).updateMask(limpio)

    col = ee.ImageCollection("LANDSAT/LC09/C02/T1_L2").filterBounds(zona).filterDate(inicio, fin).map(preparar)
    n = col.size().getInfo()
    idx = col.mean().reduceRegion(ee.Reducer.mean(), zona, 30).getInfo() if n else {}
    return {"pendiente_grados": round(pend, 2) if pend is not None else None,
            "pendiente_pct": round(math.tan(math.radians(pend)) * 100, 1) if pend is not None else None,
            "ndvi": round(idx["NDVI"], 3) if idx.get("NDVI") is not None else None,
            "ndwi": round(idx["NDWI"], 3) if idx.get("NDWI") is not None else None, "imagenes": n}

# ------------------------------------------------------------------ 4. NASA AppEEARS (asíncrono)
_token = {"valor": None, "vence": 0}
def _appeears_token():
    if _token["valor"] and time.time() < _token["vence"]: return _token["valor"]
    u, p = os.environ.get("EARTHDATA_USER"), os.environ.get("EARTHDATA_PASS")
    if not (u and p): raise RuntimeError("faltan EARTHDATA_USER y EARTHDATA_PASS")
    r = requests.post(f"{APPEEARS}/login", auth=(u, p), timeout=TIMEOUT)
    r.raise_for_status()
    _token.update(valor=r.json()["token"], vence=time.time() + 40 * 3600)
    return _token["valor"]

def appeears_capas(producto):
    r = requests.get(f"{APPEEARS}/product/{producto}", timeout=TIMEOUT)
    r.raise_for_status()
    return list(r.json().keys())

def appeears_enviar(id_lote, lat, lon, inicio, fin, capas=None):
    """Fechas MM-DD-YYYY. Devuelve el task_id para consultarlo después."""
    capas = capas or CAPAS_APPEEARS
    validas = []
    for prod, capa in capas:
        disp = appeears_capas(prod)
        if capa not in disp:
            raise ValueError(f"La capa {capa} no existe en {prod}. Capas disponibles: {', '.join(disp)}")
        validas.append({"product": prod, "layer": capa})
    cuerpo = {"task_type": "point", "task_name": f"rotacion_{id_lote}_{int(time.time())}",
              "params": {"dates": [{"startDate": inicio, "endDate": fin}], "layers": validas,
                         "coordinates": [{"id": str(id_lote), "latitude": lat, "longitude": lon}]}}
    r = requests.post(f"{APPEEARS}/task", json=cuerpo, headers={"Authorization": f"Bearer {_appeears_token()}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return {"estado": "enviada", "task_id": r.json()["task_id"]}

def appeears_estado(task_id):
    r = requests.get(f"{APPEEARS}/task/{task_id}", headers={"Authorization": f"Bearer {_appeears_token()}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def appeears_archivos(task_id):
    """Cuando el estado sea 'done': lista de archivos del resultado (los CSV traen los valores del punto)."""
    r = requests.get(f"{APPEEARS}/bundle/{task_id}", headers={"Authorization": f"Bearer {_appeears_token()}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("files", [])

# ------------------------------------------------------------------ 5. Precios (Socrata)
def precios(ciudad="BARRANQUILLA", limite=15):
    """Configura SOCRATA_DATASET con el ID del conjunto de precios mayoristas que vayas a usar en datos.gov.co,
    y SOCRATA_COL_CIUDAD con el nombre de la columna de ciudad de ese conjunto."""
    ds = os.environ.get("SOCRATA_DATASET")
    if not ds: raise RuntimeError("falta SOCRATA_DATASET (ID del conjunto de datos en datos.gov.co)")
    col = re.sub(r"[^a-z0-9_]", "", os.environ.get("SOCRATA_COL_CIUDAD", "ciudad").lower())
    ciudad = re.sub(r"[^A-ZÁÉÍÓÚÑ ]", "", ciudad.upper())[:40]
    h = {"X-App-Token": os.environ["SOCRATA_TOKEN"]} if os.environ.get("SOCRATA_TOKEN") else {}
    r = requests.get(f"https://www.datos.gov.co/resource/{ds}.json", headers=h, timeout=TIMEOUT,
                     params={"$limit": limite, "$where": f"upper({col}) like '%{ciudad}%'"})
    r.raise_for_status()
    return {"ciudad": ciudad, "registros": r.json()}

# ------------------------------------------------------------------ Orquestación
def perfil_lote(lat, lon, dias=365, ciudad="BARRANQUILLA"):
    """Corre en paralelo las fuentes rápidas y devuelve un resumen normalizado + el estado de cada fuente."""
    fin = date.today() - timedelta(days=2)
    ini = fin - timedelta(days=dias)
    tareas = {"nasa_power": lambda: nasa_power(lat, lon, ini.strftime("%Y%m%d"), fin.strftime("%Y%m%d")),
              "soilgrids": lambda: soilgrids(lat, lon),
              "gee": lambda: gee(lat, lon, ini.isoformat(), fin.isoformat()),
              "precios": lambda: precios(ciudad)}
    res = {}
    with ThreadPoolExecutor(max_workers=len(tareas)) as ex:
        fut = {k: ex.submit(f) for k, f in tareas.items()}
        for k, f in fut.items():
            try: res[k] = {"estado": "ok", "datos": f.result(timeout=TIMEOUT + 15)}
            except Exception as e: res[k] = {"estado": "error", "detalle": str(e)[:300]}
    dato = lambda k: res[k]["datos"] if res[k]["estado"] == "ok" else {}
    return {"punto": {"lat": round(lat, 4), "lon": round(lon, 4)}, "periodo": {"inicio": ini.isoformat(), "fin": fin.isoformat()},
            "suelo": dato("soilgrids"), "terreno": {"pendiente_pct": dato("gee").get("pendiente_pct")},
            "vegetacion": {k: dato("gee").get(k) for k in ("ndvi", "ndwi")}, "clima_reciente": dato("nasa_power"),
            "mercado": dato("precios"), "fuentes": {k: v["estado"] if v["estado"] == "ok" else v["detalle"] for k, v in res.items()}}
