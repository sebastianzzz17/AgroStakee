"""Humedad y temperatura históricas del suelo desde Copernicus CDS (ERA5-Land, serie de tiempo por punto).

Conjunto: reanalysis-era5-land-timeseries (horario, 0,1°, CSV). Variables:
  - volumetric_soil_water_layer_1  (m³/m³, capa de 0 a 7 cm)  -> humedad del suelo en %
  - soil_temperature_level_1       (K, capa de 0 a 7 cm)       -> temperatura del suelo en °C
Se promedia por mes del año (climatología) y se guarda en data/historico_suelo.json para cada zona.

Requisitos: pip install cdsapi, cuenta en https://cds.climate.copernicus.eu, aceptar la licencia de ERA5-Land en la
página del conjunto y el token en ~/.cdsapirc (o en las variables CDSAPI_URL y CDSAPI_KEY).
No se pudo probar en vivo desde el entorno de desarrollo: los nombres de las columnas del CSV se buscan de forma flexible.

Uso: python importar.py cds [años]   (por defecto 10 años completos hasta el año pasado)"""
import csv, io, json, os, tempfile, zipfile
from collections import defaultdict
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(BASE, "data", "historico_suelo.json")
DATASET = "reanalysis-era5-land-timeseries"
VARIABLES = ["volumetric_soil_water_layer_1", "soil_temperature_level_1"]

def _csv_de(ruta):
    """El CDS puede entregar un CSV o un ZIP con uno o varios CSV."""
    if zipfile.is_zipfile(ruta):
        with zipfile.ZipFile(ruta) as z:
            for n in z.namelist():
                if n.lower().endswith(".csv"):
                    yield list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8")))
    else:
        with open(ruta, encoding="utf-8") as f:
            yield list(csv.DictReader(f))

def _col(fila, *claves):
    for k in fila:
        kl = k.lower()
        if any(c in kl for c in claves): return k
    return None

def descargar_punto(lat, lon, anios=10, hoy=None):
    import cdsapi   # solo se necesita para este comando
    hoy = hoy or date.today()
    fin, ini = hoy.year - 1, hoy.year - anios
    req = {"variable": VARIABLES, "location": {"latitude": round(lat, 2), "longitude": round(lon, 2)},
           "date": [f"{ini}-01-01/{fin}-12-31"], "data_format": "csv"}
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "era5land")
        cdsapi.Client().retrieve(DATASET, req).download(ruta)
        hum, tem = defaultdict(list), defaultdict(list)
        for filas in _csv_de(ruta):
            if not filas: continue
            ct, ch, cs = _col(filas[0], "time", "date"), _col(filas[0], "swvl1", "soil_water"), _col(filas[0], "stl1", "soil_temperature")
            if not ct: continue
            for f in filas:
                try: mes = int(str(f[ct])[5:7])
                except (ValueError, TypeError): continue
                if ch and f.get(ch) not in (None, ""): hum[mes].append(float(f[ch]))
                if cs and f.get(cs) not in (None, ""): tem[mes].append(float(f[cs]))
    if not hum and not tem: raise RuntimeError("El CSV de ERA5-Land no traía las columnas esperadas")
    med = lambda xs: sum(xs) / len(xs) if xs else None
    return {"humedad_pct": [round(med(hum[m]) * 100, 1) if hum[m] else None for m in range(1, 13)],
            "temp_suelo_c": [round(med(tem[m]) - 273.15, 1) if tem[m] else None for m in range(1, 13)],
            "periodo": f"{ini}-{fin}", "fuente": "Copernicus CDS, ERA5-Land (capa de 0 a 7 cm)"}

def importar(zonas, anios=10):
    datos = json.load(open(SALIDA, encoding="utf-8")) if os.path.exists(SALIDA) else {}
    bien = 0
    for z in zonas:
        try:
            datos[z["id"]] = descargar_punto(float(z["lat"]), float(z["lon"]), anios)
            bien += 1; print("  ERA5-Land", z["id"], "ok")
        except Exception as e:
            print("  ERA5-Land", z["id"], "falló (se conserva lo anterior, si había):", str(e)[:160])
    if bien:
        json.dump(datos, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"ERA5-Land: {bien} de {len(zonas)} zonas descargadas ahora.")
    return datos
