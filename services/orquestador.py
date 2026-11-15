"""Orquestador de datos externos para un punto (lote): versión revisada del código del equipo.

Fuentes (cada una es opcional; si falla o no está configurada, las demás siguen):
  1. NASA POWER        clima diario reciente (no pide cuenta)
  2. ISRIC SoilGrids   suelo 0 a 30 cm: pH, carbono orgánico, arcilla, arena, CIC. Primero la API REST; ISRIC la tiene
                       pausada (aviso en docs.isric.org, dic. 2025), así que si falla se intenta la copia de SoilGrids
                       que ISRIC publica en Google Earth Engine (projects/soilgrids-isric/...). Sin Earth Engine no hay dato.
  3. Google Earth Engine  pendiente (SRTM) y NDVI/NDWI (Landsat 9). Pide: pip install earthengine-api,
                       autenticación y GEE_PROJECT
  4. NASA AppEEARS     temperatura de superficie a 70 m (ECOSTRESS) y humedad del suelo (SMAP L4).
                       Pide EARTHDATA_USER y EARTHDATA_PASS. Es ASÍNCRONO: la tarea tarda de minutos a horas,
                       por eso aquí solo se envía y se consulta su estado; no bloquea la app.
  5. Precios (Socrata, datos.gov.co)  pide SOCRATA_DATASET con el ID del conjunto de datos.
  6. IDEAM             estaciones activas más cercanas (services/ideam.py), con copia local si no hay internet.
  7. NASA MODIS (ORNL DAAC) verdor (NDVI) reciente y 8. elevación SRTM para la pendiente (services/descargas.py).
     Ninguna de las dos pide cuenta; sirven aunque Earth Engine no esté configurado.

completar(): arma la lista final de variables del punto. Si una no llegó de los satélites o los mapas,
se llena con el promedio de la zona del piloto más cercana (estudios publicados y clima guardado) y, si
tampoco hay, con un valor típico de las tierras bajas del Caribe. Cada variable dice de dónde salió.

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
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, timedelta
import requests
from services import descargas, ideam

TIMEOUT = 30
APPEEARS = "https://appeears.earthdatacloud.nasa.gov/api"
CAPAS_APPEEARS = [("ECO_L2T_LSTE.002", "LST"), ("SPL4SMGP.008", "sm_surface"), ("SPL4SMGP.008", "sm_rootzone")]

# ------------------------------------------------------------------ 1. NASA POWER
def nasa_power(lat, lon, inicio, fin, timeout=TIMEOUT):
    """Fechas YYYYMMDD. Resumen del periodo."""
    r = requests.get("https://power.larc.nasa.gov/api/temporal/daily/point", timeout=timeout, params={
        "parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,GWETTOP,TS", "community": "AG", "latitude": lat, "longitude": lon,
        "start": inicio, "end": fin, "format": "JSON"})
    r.raise_for_status()
    p = r.json()["properties"]["parameter"]
    ok = lambda v: v is not None and v > -999
    tx = [v for v in p["T2M_MAX"].values() if ok(v)]
    tn = [v for v in p["T2M_MIN"].values() if ok(v)]
    ll = [v for v in p["PRECTOTCORR"].values() if ok(v)]
    ult = lambda k: [v for _, v in sorted(p.get(k, {}).items())[-30:] if ok(v)]     # últimos 30 días con dato
    gw, ts = ult("GWETTOP"), ult("TS")
    return {"humedad_sup_rel": round(sum(gw) / len(gw), 3) if gw else None,      # 0 a 1, fracción de saturación (GWETTOP)
            "temp_superficie_c": round(sum(ts) / len(ts), 1) if ts else None,
            "temp_max_prom_c": round(sum(tx) / len(tx), 1) if tx else None,
            "temp_min_prom_c": round(sum(tn) / len(tn), 1) if tn else None,
            "dias_helada": sum(1 for t in tn if t <= 0), "dias_calor": sum(1 for t in tx if t > 35),
            "lluvia_total_mm": round(sum(ll)) if ll else None, "dias_lluvia": sum(1 for v in ll if v >= 1),
            "dias_lluvia_extrema": sum(1 for v in ll if v >= 50), "dias_con_datos": len(ll)}

# ------------------------------------------------------------------ 2. ISRIC SoilGrids
PROPS = ("phh2o", "soc", "clay", "sand", "cec")

def _resumen_suelo(out, fuente):
    arc, are = out.get("clay"), out.get("sand")                           # en %
    textura = None
    if arc is not None and are is not None:   # aproximación a grupos gruesos de textura
        textura = "arcilloso" if arc >= 35 else "arenoso" if are >= 60 and arc < 15 else "franco"
    soc = out.get("soc")                                                  # g/kg
    return {"ph": out.get("phh2o"), "arcilla_pct": arc, "arena_pct": are, "cic_cmol_kg": out.get("cec"),
            "carbono_organico_g_kg": soc, "materia_organica_pct": round(soc / 10 * 1.724, 2) if soc is not None else None,
            "textura": textura, "fuente": fuente,
            "nota": "Estimaciones de mapas globales a unos 250 m; confírmalas con un análisis de laboratorio."}

def soilgrids_gee(lat, lon, radio_m=250):
    """SoilGrids 2.0 en Earth Engine. Cada imagen trae 6 bandas (una por profundidad); se usan las 3 primeras
    (0-5, 5-15 y 15-30 cm) pesadas por su grosor. Todas las propiedades usadas se dividen entre 10."""
    ee = _ee()
    img = ee.Image.cat(*[ee.Image(f"projects/soilgrids-isric/{p}_mean").select([0, 1, 2], [f"{p}_a", f"{p}_b", f"{p}_c"]) for p in PROPS])
    v = img.reduceRegion(ee.Reducer.mean(), ee.Geometry.Point([lon, lat]).buffer(radio_m), 250).getInfo()
    out = {}
    for p in PROPS:
        a, b, c = v.get(f"{p}_a"), v.get(f"{p}_b"), v.get(f"{p}_c")
        out[p] = round((a * 5 + b * 10 + c * 15) / 30 / 10, 2) if None not in (a, b, c) else None
    if all(x is None for x in out.values()): raise RuntimeError("SoilGrids en Earth Engine no tiene datos en este punto (agua o zona urbana)")
    return _resumen_suelo(out, "SoilGrids 2.0 en Google Earth Engine")

# Fuentes que fallaron hace poco: no se vuelven a esperar en cada consulta (ISRIC tiene pausada la API de SoilGrids)
_PAUSA = {}
def _pausada(f): return _PAUSA.get(f, 0) > time.time()
def _pausar(f, horas): _PAUSA[f] = time.time() + horas * 3600

def _ee_disponible():
    if _pausada("gee"): return False
    try:
        import ee  # noqa: F401
        return True
    except ImportError:
        _pausar("gee", 24); return False

def soilgrids(lat, lon, timeout=TIMEOUT):
    e_rest = "pausada (falló hace poco; se reintenta en unas horas)"
    if not _pausada("soilgrids_rest"):
        try:
            return soilgrids_rest(lat, lon, timeout)
        except Exception as e:
            e_rest = str(e)[:80]
            if not isinstance(e, RuntimeError): _pausar("soilgrids_rest", 6)     # sin respuesta: no esperarla otra vez por 6 horas
    if _ee_disponible():
        try:
            return soilgrids_gee(lat, lon)
        except Exception as e_gee:
            raise RuntimeError(f"La API de SoilGrids no respondió ({e_rest}); ISRIC anunció que la pausó. Earth Engine tampoco: {str(e_gee)[:120]}")
    raise RuntimeError(f"La API de SoilGrids no respondió ({e_rest}); ISRIC anunció que la pausó. Earth Engine no está configurado.")

def soilgrids_rest(lat, lon, timeout=TIMEOUT):
    params = [("lon", lon), ("lat", lat)] + [("property", x) for x in PROPS] + \
             [("depth", d) for d in ("0-5cm", "5-15cm", "15-30cm")] + [("value", "mean")]
    r = requests.get("https://rest.isric.org/soilgrids/v2.0/properties/query", params=params, timeout=timeout)
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
    if all(x is None for x in out.values()): raise RuntimeError("SoilGrids no tiene datos en este punto (agua o zona urbana)")
    return _resumen_suelo(out, "API REST de SoilGrids 2.0")

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
def perfil_lote(lat, lon, dias=365, ciudad="BARRANQUILLA", limite=8, local=None):
    """Consulta rápida de la tarjeta "Suelo según mapas globales". Antes tardaba mucho porque esperaba a la fuente
    más lenta aunque ya se hubiera pasado del tiempo, pedía cosas que la tarjeta no muestra (catálogo del IDEAM,
    precios) y probaba MODIS en tres satélites seguidos. Ahora:
      - lo que la descarga automática ya trajo para ese punto (NASA POWER, MODIS, pendiente) se usa sin internet;
      - el resto corre en paralelo con un límite total de `limite` segundos: lo que no llegue a tiempo se llena
        con el promedio de la zona (completar);
      - SoilGrids, si no responde, no se vuelve a esperar por unas horas."""
    local = local or {}
    fin = date.today() - timedelta(days=2)
    ini = fin - timedelta(days=dias)
    t = min(10, limite)
    tareas = {"soilgrids": lambda: soilgrids(lat, lon, t)}
    if _ee_disponible(): tareas["gee"] = lambda: gee(lat, lon, ini.isoformat(), fin.isoformat())
    if "nasa_power" not in local: tareas["nasa_power"] = lambda: nasa_power(lat, lon, ini.strftime("%Y%m%d"), fin.strftime("%Y%m%d"), t)
    if "modis" not in local: tareas["modis"] = lambda: descargas.ndvi_serie(lat, lon, n=4, timeout=t / 2, productos=("MOD13Q1", "VNP13A1"))
    if "elevacion" not in local: tareas["elevacion"] = lambda: descargas.pendiente(lat, lon, timeout=t / 2)
    res = {k: {"estado": "ok", "datos": v, "local": True} for k, v in local.items()}
    ex = ThreadPoolExecutor(max_workers=len(tareas))
    fut = {k: ex.submit(f) for k, f in tareas.items()}
    listos, _ = wait(list(fut.values()), timeout=limite)
    for k, f in fut.items():
        if f not in listos: res[k] = {"estado": "error", "detalle": f"tardó más de {limite} s"}; continue
        try: res[k] = {"estado": "ok", "datos": f.result()}
        except Exception as e: res[k] = {"estado": "error", "detalle": str(e)[:300]}
    ex.shutdown(wait=False, cancel_futures=True)        # no espera a las fuentes lentas: responde ya
    dato = lambda k: res[k]["datos"] if k in res and res[k]["estado"] == "ok" else {}
    return {"punto": {"lat": round(lat, 4), "lon": round(lon, 4)}, "periodo": {"inicio": ini.isoformat(), "fin": fin.isoformat()},
            "suelo": dato("soilgrids"), "terreno": {"pendiente_pct": dato("gee").get("pendiente_pct")},
            "vegetacion": {k: dato("gee").get(k) for k in ("ndvi", "ndwi")}, "clima_reciente": dato("nasa_power"),
            "modis": dato("modis"), "elevacion": dato("elevacion"),
            "fuentes": {k: v["estado"] if v["estado"] == "ok" else v["detalle"] for k, v in res.items()}}

def datos_guardados(lat, lon):
    """Lo que la descarga automática ya trajo para este punto (o para la zona del piloto en ese mismo lugar).
    Así la tarjeta responde al instante sin volver a pedirlo por internet."""
    from services import motor
    out = {}
    R = descargas.recientes(lat, lon, solo_cache=True) or {}
    d = R.get("diario") or {}
    ult = lambda k: [v for _, v in sorted((d.get(k) or {}).items())[-30:]]
    gw, ts = ult("GWETTOP"), ult("TS")
    if gw or ts:
        out["nasa_power"] = {"humedad_sup_rel": round(sum(gw) / len(gw), 3) if gw else None,
                             "temp_superficie_c": round(sum(ts) / len(ts), 1) if ts else None}
    if R.get("ndvi"): out["modis"] = {"producto": R.get("producto_ndvi", "MODIS"), "serie": R["ndvi"][-4:]}
    zid = next((z["id"] for z in motor.db.consultar("SELECT id, lat, lon FROM zonas")
                if abs(float(z["lat"]) - lat) < .006 and abs(float(z["lon"]) - lon) < .006), None) or motor.id_punto(lat, lon)
    f = motor.db.consultar("SELECT datos, verificado FROM clima WHERE zona_id=?", (zid,))
    if f and f[0]["verificado"]:
        import json as _json
        cl = _json.loads(f[0]["datos"])
        if cl.get("lluvia_mensual_mm") and "nasa_power" in out: out["nasa_power"]["lluvia_anual_normal_mm"] = round(sum(cl["lluvia_mensual_mm"]))
        if cl.get("pendiente_pct") is not None and "pendiente_pct" not in (cl.get("campos_ejemplo") or []):
            out["elevacion"] = {"pendiente_pct": cl["pendiente_pct"], "elevacion_m": cl.get("elevacion_m"), "fuente": "SRTM (ya descargado)"}
    return out

# ------------------------------------------------------------------ Relleno de lo que falte
POROSIDAD = {"arenoso": 0.40, "franco": 0.46, "arcilloso": 0.50}
TEXTURA_TIPICA = {"arenoso": (8, 75), "franco": (20, 40), "arcilloso": (45, 20)}   # (arcilla %, arena %) aproximados de cada clase
TIPICO = {"ph": 6.3, "textura": "franco", "materia_organica_pct": 2.0, "humedad_pct": 25, "temp_suelo_c": 29, "ndvi": .55, "pendiente_pct": 3}

def _primer_numero(txt):
    """Solo acepta un promedio ("3,18 ± 0,99"), un valor suelto o el inicio de un rango ("4,71 a 6,16").
    Textos como "40% de las muestras alto" NO son un promedio y devuelven None."""
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(±|a\s|\(|$)", str(txt or ""))
    return float(m.group(1).replace(",", ".")) if m else None

def completar(perfil, idioma="es"):
    """Lista ordenada de variables del punto con su valor y su origen: "satelite" (medido para el punto por la NASA
    o los mapas globales), "zona" (promedio de la zona del piloto más cercana) o "estimado" (valor típico)."""
    import json as _json
    from datetime import date as _date
    from services import motor
    en = idioma == "en"
    lat, lon = perfil["punto"]["lat"], perfil["punto"]["lon"]
    zc, km = motor.zona_cercana(lat, lon)
    nom = zc["nombre"].split(" (")[0]
    piloto = _json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "piloto.json"), encoding="utf-8"))
    pz = piloto["zonas"].get(zc["id"]) or {}
    cl, _ = motor.clima_de(zc["id"])
    mes = _date.today().month - 1
    s, cli, mod, ele, gee_ = perfil.get("suelo") or {}, perfil.get("clima_reciente") or {}, perfil.get("modis") or {}, perfil.get("elevacion") or {}, perfil.get("terreno") or {}
    f_zona = (f"promedio de {nom} (a {km} km)" if not en else f"{nom} average ({km} km away)")
    f_tip = "valor típico del Caribe" if not en else "typical Caribbean value"
    out = []
    def var(clave, nombre, unidad, candidatos, dec=1):
        for valor, origen, fuente in candidatos:
            if valor is not None:
                v = round(valor, dec) if isinstance(valor, (int, float)) and dec is not None else valor
                out.append({"clave": clave, "nombre": nombre, "valor": v, "unidad": unidad, "origen": origen, "fuente": fuente}); return v
        return None
    tex = var("textura", "Tipo de suelo" if not en else "Soil type", "", [
        (s.get("textura"), "satelite", s.get("fuente")), ((pz.get("suelo") or {}).get("textura"), "zona", f_zona), (TIPICO["textura"], "estimado", f_tip)], None)
    var("ph", "pH", "", [(s.get("ph"), "satelite", s.get("fuente")), ((pz.get("suelo") or {}).get("ph"), "zona", f_zona), (TIPICO["ph"], "estimado", f_tip)])
    mo_cands = [
        (s.get("materia_organica_pct"), "satelite", s.get("fuente")), (_primer_numero((pz.get("valores") or {}).get("materia_organica_pct")), "zona", f_zona),
        (TIPICO["materia_organica_pct"], "estimado", f_tip)]
    mo = var("materia_organica_pct", "Materia orgánica" if not en else "Organic matter", "%", mo_cands)
    mo_origen = next((x["origen"] for x in out if x["clave"] == "materia_organica_pct"), None)
    arc, are = TEXTURA_TIPICA.get(tex, TEXTURA_TIPICA["franco"])
    f_tex = "según el tipo de suelo" if not en else "from the soil type"
    var("arcilla_pct", "Arcilla" if not en else "Clay", "%", [(s.get("arcilla_pct"), "satelite", s.get("fuente")), (arc, "estimado", f_tex)], 0)
    var("arena_pct", "Arena" if not en else "Sand", "%", [(s.get("arena_pct"), "satelite", s.get("fuente")), (are, "estimado", f_tex)], 0)
    hum_sat = cli.get("humedad_sup_rel")
    hum_zona = (cl or {}).get("humedad_sup_mensual") and cl["humedad_sup_mensual"][mes]
    var("humedad_pct", "Humedad del suelo" if not en else "Soil moisture", "%", [
        (hum_sat * POROSIDAD.get(tex, .46) * 100 if hum_sat is not None else None, "satelite", "NASA POWER (GWETTOP), últimos 30 días" if not en else "NASA POWER (GWETTOP), last 30 days"),
        (hum_zona / 100 * POROSIDAD.get(tex, .46) * 100 if hum_zona else None, "zona", f_zona), (TIPICO["humedad_pct"], "estimado", f_tip)])
    var("temp_suelo_c", "Temperatura del suelo" if not en else "Soil temperature", "°C", [
        (cli.get("temp_superficie_c"), "satelite", "NASA POWER (TS), últimos 30 días" if not en else "NASA POWER (TS), last 30 days"),
        ((cl or {}).get("temp_mensual", [None] * 12)[mes] + 1.5 if cl else None, "zona", f_zona), (TIPICO["temp_suelo_c"], "estimado", f_tip)])
    nd = [x["ndvi"] for x in (mod.get("serie") or [])[-2:]]
    var("ndvi", "Verdor de las plantas (NDVI)" if not en else "Plant greenness (NDVI)", "", [
        (sum(nd) / len(nd) if nd else None, "satelite", f"NASA {mod.get('producto', 'MODIS')} (ORNL DAAC)"),
        ((perfil.get("vegetacion") or {}).get("ndvi"), "satelite", "Landsat 9 (Earth Engine)"),
        ((cl or {}).get("ndvi_mensual", [None] * 12)[mes] if cl else None, "zona", f_zona), (TIPICO["ndvi"], "estimado", f_tip)], 2)
    var("pendiente_pct", "Pendiente" if not en else "Slope", "%", [
        (ele.get("pendiente_pct"), "satelite", ele.get("fuente")), (gee_.get("pendiente_pct"), "satelite", "SRTM (Earth Engine)"),
        ((cl or {}).get("pendiente_pct"), "zona", f_zona), (TIPICO["pendiente_pct"], "estimado", f_tip)])
    var("lluvia_anual_mm", "Lluvia al año" if not en else "Rain per year", "mm", [
        (cli.get("lluvia_total_mm"), "satelite", "NASA POWER, último año" if not en else "NASA POWER, last year"),
        (cli.get("lluvia_anual_normal_mm"), "satelite", "NASA POWER, año normal" if not en else "NASA POWER, normal year"),
        ((cl or {}).get("lluvia_anual_mm"), "zona", f_zona)], 0)
    n_mo = "bajo" if mo is not None and mo < 2 else "medio" if mo is not None and mo < 4 else "alto" if mo is not None else None
    n = n_mo if mo_origen != "estimado" else ((pz.get("suelo") or {}).get("n") or n_mo)   # sin promedio de MO, el nivel que da el estudio
    return {"variables": out, "n_desde_mo": n, "zona_cercana": {"id": zc["id"], "nombre": nom, "km": km},
            "resumen": {o: sum(1 for x in out if x["origen"] == o) for o in ("satelite", "zona", "estimado")}}
