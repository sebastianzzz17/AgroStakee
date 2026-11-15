"""Estaciones del IDEAM más cercanas a un punto.

Fuente oficial: Catálogo Nacional de Estaciones (CNE) en datos abiertos, conjunto hp9r-jxuu
(https://www.datos.gov.co/resource/hp9r-jxuu.json). Campos que se usan: codigo, nombre, categoria, tecnologia,
estado, departamento, municipio, latitud, longitud, altitud, entidad.

Cómo trabaja:
  1. Si hay una copia descargada hace menos de 30 días (data/cache/cne_ideam.json), usa esa.
  2. Si se pide con red=True, intenta bajar el catálogo completo y lo guarda en la caché.
  3. Si no hay red ni caché, usa la copia regional incluida en la app (data/cne_caribe.json, febrero de 2022).

Cambios frente al código del equipo (fetch_nearest_ideam_station):
  - El conjunto hpwx-a3qe no se pudo verificar; el catálogo de estaciones del IDEAM es hp9r-jxuu
    (es el que usa, por ejemplo, la librería colombia-hydrodata).
  - Ya no se filtra por departamento con LIKE: los nombres traen tildes y mayúsculas distintas ("Atlantico",
    "Bolívar") y la estación más cercana puede quedar en el departamento vecino. Se calcula la distancia a todas.
  - Se descartan estaciones suspendidas, de otras entidades y las que solo miden ríos (limnimétricas, etc.).
  - Sin $limit=100: Socrata devuelve 1000 filas por defecto y el catálogo tiene unas 4.500.
  - El texto del usuario ya no se mete dentro de la consulta SoQL (evita inyección).
"""
import json, math, os, re, time
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://www.datos.gov.co/resource/hp9r-jxuu.json"
CACHE = os.path.join(BASE, "data", "cache", "cne_ideam.json")
COPIA = os.path.join(BASE, "data", "cne_caribe.json")
DIAS_CACHE = 30
CLIMA = {"Climática Principal", "Climática Ordinaria", "Sinóptica Principal", "Sinóptica Secundaria",
         "Agrometeorológica", "Meteorológica Especial"}
LLUVIA = {"Pluviométrica", "Pluviográfica"}
TIPOS = {"clima": CLIMA, "lluvia": CLIMA | LLUVIA}

def _hav(a, b, c, d):
    r = math.radians
    x = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))

def _num(v):
    try: return float(str(v).replace(",", "."))
    except (TypeError, ValueError): return None

def _normalizar(filas):
    out = []
    for f in filas:
        lat, lon = _num(f.get("latitud")), _num(f.get("longitud"))
        if lat is None or lon is None: continue
        if str(f.get("estado", "")).strip().lower() != "activa": continue
        if "HIDROLOGIA METEOROLOGIA" not in str(f.get("entidad", "")).upper(): continue
        cat = str(f.get("categoria", "")).strip()
        if cat not in CLIMA | LLUVIA: continue
        alt = _num(f.get("altitud"))
        nombre = re.sub(r"\s*-\s*(AUT)?\s*$", "", str(f.get("nombre", "")).split(" [")[0].strip())
        out.append({"codigo": str(f.get("codigo", "")).strip(), "nombre": re.sub(r"\s+", " ", nombre),
                    "categoria": cat, "tecnologia": str(f.get("tecnologia", "")).strip(),
                    "municipio": f.get("municipio"), "departamento": f.get("departamento"),
                    "lat": lat, "lon": lon, "altitud_m": int(alt) if alt is not None else None})
    return out

def descargar(timeout=60):
    """Baja el catálogo oficial y lo guarda en la caché. Devuelve cuántas estaciones útiles quedaron."""
    r = requests.get(URL, params={"$limit": 20000}, timeout=timeout)
    r.raise_for_status()
    est = _normalizar(r.json())
    if not est: raise RuntimeError("el catálogo llegó vacío o con columnas distintas a las esperadas")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        f.write(json.dumps({"fuente": f"Catálogo Nacional de Estaciones del IDEAM ({URL})", "fecha_copia": time.strftime("%Y-%m-%d"),
                            "estaciones": est}, ensure_ascii=False))
    return len(est)

_MEM = {}
def _leer(ruta):
    """El catálogo completo pesa varios cientos de KB: se lee una vez y se guarda en memoria hasta que cambie el archivo."""
    m = os.path.getmtime(ruta)
    if _MEM.get(ruta, (None,))[0] != m: _MEM[ruta] = (m, json.load(open(ruta, encoding="utf-8")))
    return _MEM[ruta][1]

def catalogo(red=False):
    if os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < DIAS_CACHE * 86400:
        return _leer(CACHE) | {"origen": "copia descargada"}
    if red:
        try:
            descargar()
            return _leer(CACHE) | {"origen": "catálogo oficial"}
        except Exception:
            pass
    if os.path.exists(CACHE):   # vieja, pero mejor que nada
        return _leer(CACHE) | {"origen": "copia descargada (más de 30 días)"}
    return _leer(COPIA) | {"origen": "copia incluida en la app"}

def cercanas(lat, lon, n=3, tipo="lluvia", km_max=80, red=False):
    """Estaciones activas del IDEAM más cercanas. tipo: 'clima' (miden temperatura y lluvia) o 'lluvia'."""
    cat = catalogo(red)
    if cat.get("origen") == "copia incluida en la app":   # la copia guarda los nombres tal cual del catálogo
        cat["estaciones"] = [dict(e, nombre=re.sub(r"\s+", " ", re.sub(r"\s*-\s*(AUT)?\s*$", "", e["nombre"]))) for e in cat["estaciones"]]
    cats = TIPOS.get(tipo, TIPOS["lluvia"])
    est = [dict(e, distancia_km=round(_hav(lat, lon, e["lat"], e["lon"]), 1)) for e in cat["estaciones"] if e["categoria"] in cats]
    est = sorted((e for e in est if e["distancia_km"] <= km_max), key=lambda e: e["distancia_km"])[:n]
    return {"fuente": cat["fuente"], "fecha_copia": cat.get("fecha_copia"), "origen": cat["origen"], "estaciones": est,
            "datos": "Las series de cada estación se descargan en DHIME (http://dhime.ideam.gov.co/atencionciudadano/) con el código."}
