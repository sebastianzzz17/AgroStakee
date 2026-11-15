"""Municipios de Colombia: dónde quedan, qué se siembra en cada uno y en qué semestre (data/municipios.json, que
arma herramientas/preparar_municipios.py con la EVA 2019-2024 de la UPRA y las coordenadas de las cabeceras).

Se carga una sola vez (unos 430 KB en disco y pocos MB en memoria) y todas las búsquedas son en memoria."""
import json, math
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "data" / "municipios.json"
VECINOS_KM = 100          # un cultivo "se siembra cerca" si aparece en algún municipio a menos de esto
EXACTO_KM = 1.5           # a menos de esto, el punto es el municipio (se toca su marcador o su cabecera)
CERCA_KM = 40             # hasta aquí se nombra "Cerca de ..."
DATOS_KM = 40             # hasta aquí se usan los datos de siembra de ese municipio (los rurales son grandes)
_D = None

def _datos():
    global _D
    if _D is None:
        try: _D = json.loads(RUTA.read_text(encoding="utf-8"))
        except FileNotFoundError: _D = {"municipios": [], "departamentos": {}, "eva": {}, "fuente": {}, "anios": []}
        _D["por_zona"] = {m["zona"]: m for m in _D["municipios"] if m.get("zona")}
        _D["caribe_set"] = set(_D.get("caribe") or [])
        _D["con"] = {}            # cultivo -> municipios donde se siembra (para buscar vecinos)
        for m in _D["municipios"]:
            for k, v in m.get("nuestros", {}).items():
                if v.get("ha", 0) > 0: _D["con"].setdefault(k, []).append(m)
        _D["por_cod"] = {m["cod"]: m for m in _D["municipios"]}
    return _D

def km(a, b, c, d):
    r = math.radians
    h = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, h)))

def lista():
    """Para el mapa y el buscador: lo mínimo de cada municipio."""
    return [{"cod": m["cod"], "n": m["n"], "d": m["d"], "lat": m["lat"], "lon": m["lon"], "zona": m.get("zona")} for m in _datos()["municipios"]]

def fuente(): return _datos()["fuente"]
def eva(): return _datos().get("eva", {})
def fuente_anios():
    a = _datos().get("anios") or []
    return f"{a[0]}-{a[-1]}" if a else ""

def cercano(lat, lon):
    """(municipio, km) más cercano a esa cabecera, o (None, None) si no hay datos."""
    mejor, dm = None, None
    for m in _datos()["municipios"]:
        d = km(lat, lon, m["lat"], m["lon"])
        if dm is None or d < dm: mejor, dm = m, d
    return mejor, (round(dm, 1) if dm is not None else None)

def de_zona(z):
    """Municipio con datos de siembra para una zona piloto o un punto libre (dentro de DATOS_KM)."""
    D = _datos()
    if not z: return None, None
    if not z.get("punto"): return D["por_zona"].get(z["id"]), 0
    m, d = cercano(z["lat"], z["lon"])
    return (m, d) if m and d <= DATOS_KM else (None, None)

def presencia(m, cultivo):
    """0 a 1: qué tanto se siembra ese cultivo en el municipio frente al más sembrado de los nuestros.
    Si en el municipio no aparece, la mitad de lo que pesa en el departamento."""
    if not m: return None
    nu = m.get("nuestros", {})
    if nu:
        mx = max(v["ha"] for v in nu.values())
        if cultivo in nu: return math.sqrt(nu[cultivo]["ha"] / mx) if mx else 0
    dep = [x for x in _datos()["municipios"] if x["d"] == m["d"]]
    tot = {}
    for x in dep:
        for k, v in x.get("nuestros", {}).items(): tot[k] = tot.get(k, 0) + v["ha"]
    if not tot or cultivo not in tot: return 0
    return .5 * math.sqrt(tot[cultivo] / max(tot.values()))

def rendimiento(m, cultivo):
    """(t/ha por cosecha, de dónde sale) del municipio; si no hay, el del departamento."""
    if not m: return None, None
    v = m.get("nuestros", {}).get(cultivo)
    if v and v.get("rend"): return v["rend"], "municipio"
    r = _datos()["departamentos"].get(m["d"], {}).get(cultivo)
    return (r, "departamento") if r else (None, None)

# Nombres en inglés de los cultivos que aparecen entre los más sembrados del Caribe (para la app en inglés).
INGLES = {"Aguacate": "Avocado", "Ahuyama": "Squash", "Ajonjolí": "Sesame", "Ají": "Chili pepper", "Algodón": "Cotton", "Arroz": "Rice",
          "Banano": "Banana", "Batata": "Sweet potato", "Berenjena": "Eggplant", "Cacao": "Cocoa", "Café": "Coffee", "Caña": "Sugarcane",
          "Cebolla de bulbo": "Onion", "Cebolla de rama": "Spring onion", "Cilantro": "Coriander", "Ciruela": "Plum", "Coco": "Coconut",
          "Fique": "Fique", "Frijol": "Beans", "Guandul": "Pigeon pea", "Guayaba": "Guava", "Limón": "Lime", "Malanga, achín, yota, papa china, bore": "Taro",
          "Mango": "Mango", "Maracuyá": "Passion fruit", "Marañón": "Cashew", "Maíz": "Maize", "Melón": "Melon", "Millo": "Millet",
          "Naranja": "Orange", "Níspero": "Sapodilla", "Otras hortalizas": "Other vegetables", "Otros cultivos tropicales tradicionales": "Other traditional tropical crops",
          "Otros cítricos": "Other citrus", "Palma de aceite": "Oil palm", "Papaya": "Papaya", "Patilla": "Watermelon", "Pepino Cohombro": "Cucumber",
          "Piña": "Pineapple", "Plátano": "Plantain", "Sorgo": "Sorghum", "Soya": "Soybean", "Tabaco": "Tobacco", "Tomate": "Tomato", "Yuca": "Cassava", "Zapote": "Sapote", "Ñame": "Yam"}
def nombre(eva_nombre, ingles=False):
    if eva_nombre.startswith("Malanga"): return "Taro" if ingles else "Malanga"
    return INGLES.get(eva_nombre, eva_nombre) if ingles else eva_nombre

def minimo_local(m):
    """Hectáreas al año desde las que un cultivo cuenta como "se siembra aquí": 10 ha y al menos el 1,5 % del más
    sembrado de los nuestros en el municipio (así unas pocas hectáreas sueltas no bastan)."""
    nu = (m or {}).get("nuestros", {})
    return max(10.0, .015 * max((v.get("ha", 0) for v in nu.values()), default=0))

def es_caribe(m): return bool(m) and m["d"] in _datos()["caribe_set"]

def cerca(m, cultivo, solo_caribe=False):
    """(municipio vecino más cercano donde se siembra el cultivo, km) dentro de VECINOS_KM, o (None, None)."""
    mejor, dm = None, None
    for x in _datos()["con"].get(cultivo, []):
        if solo_caribe and x["d"] not in _datos()["caribe_set"]: continue
        d = km(m["lat"], m["lon"], x["lat"], x["lon"])
        if d <= VECINOS_KM and (dm is None or d < dm): mejor, dm = x, d
    return mejor, (round(dm) if dm is not None else None)

def semestre(m, cultivo, sem):
    """0 a 1: qué tanto se siembra el cultivo en ese semestre ("a" o "b") en el municipio, frente al más sembrado de
    los nuestros en ese mismo semestre. None si el municipio no tiene datos por semestre."""
    nu = (m or {}).get("nuestros", {})
    mx = max((v.get(sem, 0) for v in nu.values()), default=0)
    if not mx: return None
    return math.sqrt(nu.get(cultivo, {}).get(sem, 0) / mx)

def resumen(m, d_km=None):
    """Bloque «Qué se siembra en tu municipio» para la app."""
    if not m: return None
    D = _datos()
    return {"cod": m["cod"], "nombre": m["n"], "departamento": m["d"], "km": d_km, "top": m.get("top", []),
            "nuestros": m.get("nuestros", {}), "anios": D.get("anios"), "fuente": D["fuente"].get("cultivos"),
            "nota": D["fuente"].get("nota")}
