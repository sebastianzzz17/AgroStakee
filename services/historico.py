"""Relleno del suelo cuando el lote no tiene estaca: datos históricos de la zona.

Orden de preferencia para cada valor:
  pH, nitrógeno, fósforo, potasio, sales y textura:
      estudios de suelos publicados para la zona (data/piloto.json, ver docs/PILOTO.md).
  Humedad del suelo del mes:
      1. Copernicus ERA5-Land, capa de 0 a 7 cm (data/historico_suelo.json, python importar.py cds)
      2. NASA POWER GWETTOP (humedad relativa de la superficie) por la porosidad aproximada de la textura
      3. Estimación con el balance del mes: agua útil entre punto de marchitez y capacidad de campo según la textura
         (valores medios aproximados de FAO-56, tabla 19), en proporción a lluvia / evaporación.
  Temperatura del suelo del mes:
      1. ERA5-Land  2. NASA POWER TS (superficie)  3. Temperatura media del aire del mes + 1,5 °C (aproximación).
Los pasos 3 son estimaciones para que la app funcione sin datos; se reemplazan solos al importar las fuentes."""
import json, os
from services import motor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOTO = json.load(open(os.path.join(BASE, "data", "piloto.json"), encoding="utf-8"))
ERA5 = os.path.join(BASE, "data", "historico_suelo.json")
AGUA = {"arenoso": (0.12, 0.045), "franco": (0.29, 0.12), "arcilloso": (0.36, 0.22)}   # (capacidad de campo, marchitez)
POROSIDAD = {"arenoso": 0.40, "franco": 0.46, "arcilloso": 0.50}
TIPICO = {"ph": 6.3, "textura": "franco", "n": "medio", "p": "medio", "k": "medio", "salinidad": "normal"}

def _era5(zona_id):
    try: return json.load(open(ERA5, encoding="utf-8")).get(zona_id)
    except (OSError, ValueError): return None

def suelo(zona_id, mes):
    """mes: 1 a 12. Devuelve los valores del suelo y de dónde salió cada uno."""
    punto = motor.es_punto(zona_id)
    zp = motor.zona(zona_id) if punto else None
    ref_id = zp["cercana"] if punto else zona_id          # un punto libre usa los estudios de la zona más cercana
    ref = PILOTO["zonas"].get(ref_id)
    base = dict(ref["suelo"] if ref else TIPICO)
    tex = base.pop("textura")
    cl, _ = motor.clima_de(zona_id)
    era, i = (None if punto else _era5(zona_id)), mes - 1
    origen = {"suelo": (f"estudios de suelos de la zona más cercana ({zp['cercana_nombre']}, a {zp['km_cercana']} km)" if punto
                        else "estudios de suelos de la zona") if ref else "valores típicos del Caribe"}

    h = era["humedad_pct"][i] if era and era.get("humedad_pct") else None
    if h is not None: origen["humedad"] = era["fuente"]
    elif cl and cl.get("humedad_sup_mensual") and cl["humedad_sup_mensual"][i] is not None:
        h, origen["humedad"] = cl["humedad_sup_mensual"][i] / 100 * POROSIDAD[tex] * 100, "NASA POWER (GWETTOP)"
    elif cl:
        cc, pm = AGUA[tex]
        f = max(.05, min(1.1, cl["lluvia_mensual_mm"][i] / max(1, cl["evap_mensual_mm"][i])))
        h, origen["humedad"] = (pm + (cc - pm) * f) * 100, "estimada con la lluvia y el secado de la tierra del mes"

    t = era["temp_suelo_c"][i] if era and era.get("temp_suelo_c") else None
    if t is not None: origen["temperatura"] = era["fuente"]
    elif cl and cl.get("temp_suelo_mensual") and cl["temp_suelo_mensual"][i] is not None:
        t, origen["temperatura"] = cl["temp_suelo_mensual"][i], "NASA POWER (TS)"
    elif cl:
        t, origen["temperatura"] = cl["temp_mensual"][i] + 1.5, "estimada con la temperatura del aire del mes"

    if h is not None: base["humedad_pct"] = round(max(5, min(50, h)), 1)
    if t is not None: base["temp_suelo_c"] = round(max(20, min(40, t)), 1)
    return {"zona": zona_id, "mes": mes, "suelo": base, "textura": tex, "origen": origen}
