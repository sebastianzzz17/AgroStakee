"""Descargas de datos reales SIN cuenta ni llave, para cualquier punto (lat, lon). Todas usan caché en disco.

  NASA POWER (diario)         lluvia, temperatura, humedad del suelo (GWETTOP) y temperatura de la superficie (TS)
                              de los últimos ~7 meses: "Últimos 6 meses" y la lluvia día por día.
  NASA MODIS (ORNL DAAC)      verdor de las plantas (NDVI) con la API REST de subconjuntos de MODIS:
                              https://modis.ornl.gov/rst/api/v1/{producto}/subset  (máximo 10 fechas por petición).
                              Se prueba MOD13Q1 (Terra), MYD13Q1 (Aqua) y VNP13A1 (VIIRS), porque NASA anunció que
                              Terra y Aqua empiezan a apagarse entre finales de 2026 e inicios de 2027.
  Elevación (SRTM)            pendiente del terreno con Open-Elevation (SRTM de la NASA); si no responde, con la API de
                              elevación de Open-Meteo (Copernicus DEM, 90 m). Es una pendiente aproximada del
                              terreno alrededor del punto (unos 550 m), no de cada surco.

Nada de esto pide credenciales. Si no hay internet, las funciones lanzan una excepción y quien las llama
sigue con lo que tenga guardado."""
import json, math, os, time
from datetime import date, timedelta
import requests

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
ORNL = "https://modis.ornl.gov/rst/api/v1"
PRODUCTOS_NDVI = ("MOD13Q1", "MYD13Q1", "VNP13A1")
TIMEOUT = 40
FALTA = -999
UA = {"User-Agent": "AgroStake/7 (NASA Space Apps 2026)"}

def _ruta(nombre):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, nombre)

def _leer(ruta):
    try: return json.load(open(ruta, encoding="utf-8"))
    except (OSError, ValueError): return None

def _escribir(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(datos, f, ensure_ascii=False)
    os.replace(tmp, ruta)

def hay_internet():
    """Prueba rápida: ¿responde NASA POWER?"""
    try:
        requests.get("https://power.larc.nasa.gov/", timeout=8, headers=UA)
        return True
    except requests.RequestException:
        return False

# ------------------------------------------------------------------ NASA POWER, últimos meses
def power_diario(lat, lon, inicio, fin, parametros=("T2M", "PRECTOTCORR", "GWETTOP", "TS")):
    r = requests.get(POWER, timeout=90, headers=UA, params={
        "parameters": ",".join(parametros), "community": "AG", "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start": inicio.strftime("%Y%m%d"), "end": fin.strftime("%Y%m%d"), "format": "JSON"})
    r.raise_for_status()
    p = r.json()["properties"]["parameter"]
    return {k: {d: v for d, v in serie.items() if v is not None and v > FALTA} for k, serie in p.items()}

# ------------------------------------------------------------------ NASA MODIS / VIIRS (ORNL DAAC)
def _ornl(ruta, _timeout=TIMEOUT, **params):
    r = requests.get(f"{ORNL}/{ruta}", params=params, timeout=_timeout, headers=dict(UA, Accept="application/json"))
    r.raise_for_status()
    return r.json()

def _banda_ndvi(producto, timeout=TIMEOUT):
    if producto in ("MOD13Q1", "MYD13Q1"): return "250m_16_days_NDVI"
    bandas = _ornl(f"{producto}/bands", _timeout=timeout).get("bands", [])
    for b in bandas:
        n = b.get("band", "")
        if "NDVI" in n.upper() and "QUALITY" not in n.upper() and "RELIAB" not in n.upper(): return n
    raise RuntimeError(f"{producto} no tiene banda de NDVI")

def _valor_ndvi(item, escala):
    """Promedio de los píxeles válidos del recuadro (rango válido de NDVI en MODIS: -2000 a 10000)."""
    vals = [v for v in item.get("data", []) if isinstance(v, (int, float)) and -2000 <= v <= 10000]
    return round(sum(vals) / len(vals) * escala, 3) if vals else None

def ndvi_serie(lat, lon, n=14, timeout=TIMEOUT, productos=PRODUCTOS_NDVI):
    """Últimas n fechas de NDVI (cada 16 días) en un recuadro de unos 2 x 2 km alrededor del punto."""
    errores = []
    for prod in productos:
        try:
            banda = _banda_ndvi(prod, timeout)
            fechas = _ornl(f"{prod}/dates", _timeout=timeout, latitude=lat, longitude=lon).get("dates", [])
            if not fechas: raise RuntimeError("sin fechas")
            fechas = fechas[-n:]
            serie = []
            for i in range(0, len(fechas), 10):                # la API acepta hasta 10 fechas por petición
                bloque = fechas[i:i + 10]
                j = _ornl(f"{prod}/subset", _timeout=timeout, latitude=lat, longitude=lon, band=banda,
                          startDate=bloque[0]["modis_date"], endDate=bloque[-1]["modis_date"], kmAboveBelow=1, kmLeftRight=1)
                try: escala = float(j.get("scale") or 0.0001)
                except (TypeError, ValueError): escala = 0.0001
                for it in j.get("subset", []):
                    if it.get("band", banda) != banda: continue
                    v = _valor_ndvi(it, escala)
                    if v is not None: serie.append({"fecha": it.get("calendar_date"), "ndvi": v})
                time.sleep(.3)
            if serie: return {"producto": prod, "serie": serie}
            errores.append(f"{prod}: sin valores válidos")
        except Exception as e:
            errores.append(f"{prod}: {str(e)[:90]}")
    raise RuntimeError("; ".join(errores))

def ndvi_mensual(lat, lon):
    """NDVI normal de cada mes con los últimos 2 años (46 fechas)."""
    d = ndvi_serie(lat, lon, n=46)
    por_mes = {m: [] for m in range(1, 13)}
    for x in d["serie"]:
        try: por_mes[int(x["fecha"][5:7])].append(x["ndvi"])
        except (TypeError, ValueError, KeyError): pass
    meses = [round(sum(v) / len(v), 2) if v else None for m, v in sorted(por_mes.items())]
    if all(v is None for v in meses): raise RuntimeError("MODIS no devolvió NDVI para este punto")
    for i in range(12):                                     # rellena meses vacíos con el promedio de los vecinos
        if meses[i] is None:
            vec = [meses[(i + k) % 12] for k in (-1, 1, -2, 2) if meses[(i + k) % 12] is not None]
            meses[i] = round(sum(vec[:2]) / len(vec[:2]), 2) if vec else round(sum(v for v in meses if v is not None) / sum(1 for v in meses if v is not None), 2)
    return {"ndvi_mensual": meses, "producto": d["producto"], "fechas": len(d["serie"])}

# ------------------------------------------------------------------ Elevación y pendiente
def elevaciones(puntos, timeout=TIMEOUT):
    """puntos: lista de (lat, lon). Devuelve (lista de metros, fuente)."""
    try:
        r = requests.post("https://api.open-elevation.com/api/v1/lookup", timeout=timeout, headers=dict(UA, Accept="application/json"),
                          json={"locations": [{"latitude": a, "longitude": b} for a, b in puntos]})
        r.raise_for_status()
        res = r.json()["results"]
        z = [float(x["elevation"]) for x in res]
        if len(z) == len(puntos): return z, "Open-Elevation (SRTM, NASA)"
    except Exception:
        pass
    r = requests.get("https://api.open-meteo.com/v1/elevation", timeout=timeout, headers=UA, params={
        "latitude": ",".join(f"{a:.5f}" for a, _ in puntos), "longitude": ",".join(f"{b:.5f}" for _, b in puntos)})
    r.raise_for_status()
    z = [float(x) for x in r.json()["elevation"]]
    if len(z) != len(puntos): raise RuntimeError("respuesta de elevación incompleta")
    return z, "Open-Meteo (Copernicus DEM 90 m)"

def pendiente(lat, lon, delta=.0025, timeout=TIMEOUT):
    """Pendiente media aproximada con diferencias centradas (norte-sur y este-oeste, unos 275 m a cada lado)."""
    pts = [(lat, lon), (lat + delta, lon), (lat - delta, lon), (lat, lon + delta), (lat, lon - delta)]
    z, fuente = elevaciones(pts, timeout)
    dy = 2 * delta * 110540
    dx = 2 * delta * 111320 * math.cos(math.radians(lat))
    gx, gy = (z[3] - z[4]) / dx, (z[1] - z[2]) / dy
    return {"pendiente_pct": round(math.hypot(gx, gy) * 100, 1), "elevacion_m": round(z[0]), "fuente": fuente}

# ------------------------------------------------------------------ Paquete "reciente" de un punto (con caché diaria)
def _clave(lat, lon): return f"{lat:.2f}_{lon:.2f}"

def recientes(lat, lon, solo_cache=False, hoy=None):
    """Lluvia y temperatura diarias de NASA POWER de los últimos ~7 meses + NDVI reciente de MODIS.
    Con solo_cache=True no usa internet. Se descarga como mucho una vez al día."""
    hoy = hoy or date.today()
    ruta = _ruta(f"reciente_{_clave(lat, lon)}.json")
    previo = _leer(ruta)
    if solo_cache or (previo and previo.get("descargado") == hoy.isoformat()): return previo
    out = dict(previo or {}, lat=lat, lon=lon)
    errores = {}
    try:
        ini = (hoy.replace(day=1) - timedelta(days=200)).replace(day=1)
        out["diario"] = power_diario(lat, lon, ini, hoy - timedelta(days=1))
        out["fuente_clima"] = "NASA POWER (diario)"
    except Exception as e:
        errores["power"] = str(e)[:160]
    try:
        n = ndvi_serie(lat, lon, n=14)
        out["ndvi"], out["producto_ndvi"] = n["serie"], n["producto"]
    except Exception as e:
        errores["ndvi"] = str(e)[:160]
    if "power" in errores and "ndvi" in errores:
        if previo: return previo
        raise RuntimeError("; ".join(errores.values()))
    out.update(descargado=hoy.isoformat(), errores=errores)
    _escribir(ruta, out)
    return out
