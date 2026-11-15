"""Características de los cultivos desde USDA PLANTS (API pública que usa la página oficial, sin clave).

  GET https://plantsservices.sc.egov.usda.gov/api/PlantSearch?searchText=<nombre científico>
  GET https://plantsservices.sc.egov.usda.gov/api/PlantProfile?symbol=<símbolo>        -> Id
  GET https://plantsservices.sc.egov.usda.gov/api/PlantCharacteristics/<Id>              -> lista de características

La API no está documentada oficialmente; las claves que se leen (Plant, Symbol, ScientificName, Id,
PlantCharacteristicName, PlantCharacteristicValue) son las que usan otras herramientas públicas.
Muchos cultivos tropicales no tienen características en PLANTS (la base es de plantas de EE. UU.).
Se guardan en data/usda_plants.json; si traen pH mínimo y máximo, se actualizan esos valores del cultivo.

Uso: python importar.py usda"""
import json, os
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(BASE, "data", "usda_plants.json")
API = "https://plantsservices.sc.egov.usda.gov/api"
CIENTIFICO = {"maiz": "Zea mays", "arroz": "Oryza sativa", "yuca": "Manihot esculenta", "frijol": "Vigna unguiculata",
              "guandul": "Cajanus cajan", "ajonjoli": "Sesamum indicum", "name": "Dioscorea alata"}
INTERES = ("ph, minimum", "ph, maximum", "drought tolerance", "salinity tolerance", "nitrogen fixation",
           "precipitation, minimum", "precipitation, maximum", "root depth, minimum", "anaerobic tolerance")

def _get(ruta, **params):
    r = requests.get(f"{API}/{ruta}", params=params or None, headers={"Accept": "application/json"}, timeout=40)
    r.raise_for_status()
    return r.json()

def _simbolo(nombre):
    for item in _get("PlantSearch", searchText=nombre) or []:
        p = item.get("Plant") if isinstance(item, dict) else None
        if p and str(p.get("ScientificName", "")).lower().startswith(nombre.lower()):
            return p.get("AcceptedSymbol") or p.get("Symbol")
    return None

def caracteristicas(nombre):
    sim = _simbolo(nombre)
    if not sim: return {"nombre": nombre, "error": "no encontrado en PLANTS"}
    perfil = _get("PlantProfile", symbol=sim)
    pid = perfil.get("Id") if isinstance(perfil, dict) else None
    if not pid: return {"nombre": nombre, "simbolo": sim, "error": "sin perfil"}
    car = {}
    for c in _get(f"PlantCharacteristics/{pid}") or []:
        if isinstance(c, dict) and str(c.get("PlantCharacteristicName", "")).strip().lower() in INTERES:
            car[c["PlantCharacteristicName"].strip()] = c.get("PlantCharacteristicValue")
    return {"nombre": nombre, "simbolo": sim, "id": pid, "caracteristicas": car,
            "url": f"https://plants.usda.gov/home/plantProfile?symbol={sim}"}

def _num(v):
    try: return float(str(v).replace(",", "."))
    except (TypeError, ValueError): return None

def importar(db):
    previo = json.load(open(SALIDA, encoding="utf-8")) if os.path.exists(SALIDA) else {}
    datos, bien = {}, 0
    for cultivo, nombre in CIENTIFICO.items():
        try:
            d = caracteristicas(nombre)
        except Exception as e:
            d = {"nombre": nombre, "error": str(e)[:160]}
        if d.get("error") and previo.get(cultivo) and not previo[cultivo].get("error"):
            d = previo[cultivo]   # si falla, se conserva lo último que sí se descargó
        else:
            bien += not d.get("error")
        datos[cultivo] = d
        car = d.get("caracteristicas") or {}
        lo, hi = _num(car.get("pH, Minimum")), _num(car.get("pH, Maximum"))
        if lo and hi and 3 < lo < hi < 10:
            db.ejecutar("UPDATE cultivos SET ph_min=?, ph_max=? WHERE cultivo=?", (lo, hi, cultivo))
        print(f"  USDA {cultivo}: {d.get('simbolo', '-')} {len(car)} características" + (f" ({d['error']})" if d.get("error") else ""))
    if bien or previo:
        json.dump(datos, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"USDA PLANTS: {bien} de {len(CIENTIFICO)} cultivos descargados ahora.")
    return datos
