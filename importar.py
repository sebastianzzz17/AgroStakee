"""Carga datos REALES (upsert, quedan verificado=1 y desaparece el aviso de 'datos de ejemplo').
  python importar.py cultivos  datos.csv    (columnas de db.CULT + fuente opcional)
  python importar.py zonas     datos.csv    (id,nombre,lat,lon,suelo,riego + fuente opcional)
  python importar.py clima     datos.json   ({"zona_id": {...mismos campos que data/clima_ejemplo.json...}})
  python importar.py perfiles  datos.json   (lista como data/perfiles_suelo.json)
  python importar.py nasa      [años]       (descarga el clima real de cada zona desde NASA POWER; por defecto 20 años)
  python importar.py ideam                  (actualiza el catálogo de estaciones del IDEAM desde datos.gov.co)
  python importar.py piloto    [años]       (las dos anteriores: clima NASA de las 8 zonas y estaciones IDEAM)
  python importar.py cds       [años]       (humedad y temperatura del suelo de ERA5-Land, Copernicus CDS; pide cuenta)
  python importar.py usda                   (características de los cultivos desde USDA PLANTS)"""
import csv, json, sys
import db

NUM = {"ciclo_dias","agua_mm","ph_min","ph_max","tol_sequia","fija_n","demanda_n","cobertura","ingreso_rel","forraje","materia_organica","mercado","lat","lon"}

def main(tabla, ruta):
    db.init()
    if tabla in ("cultivos", "zonas"):
        for r in csv.DictReader(open(ruta, encoding="utf-8-sig")):
            f = r.pop("fuente", None) or "dato real (sin fuente indicada)"
            r = {k: (float(v) if k in NUM else v) for k, v in r.items()}
            if tabla == "zonas": r["riego"] = 1 if str(r["riego"]).lower() in ("1", "true", "si", "sí") else 0
            db.guardar(tabla, r, 1, f)
    elif tabla == "ideam":
        from services import ideam
        print("Estaciones activas del IDEAM guardadas:", ideam.descargar())
    elif tabla == "cds":
        from services import copernicus
        zonas = [dict(r) for r in db.consultar("SELECT id, lat, lon FROM zonas")]
        copernicus.importar(zonas, int(ruta) if ruta else 10)
    elif tabla == "usda":
        from services import usda
        usda.importar(db)
    elif tabla == "piloto":
        main("ideam", None)
        return main("nasa", ruta)
    elif tabla == "nasa":
        from services import nasa
        ejemplo = db._leer("clima_ejemplo.json")
        for z in db.consultar("SELECT * FROM zonas"):
            try:
                d = nasa.construir(float(z["lat"]), float(z["lon"]), int(ruta or 20))
            except Exception as e:
                print("No se pudo descargar", z["id"], "->", e); continue
            previo = ejemplo.get(z["id"], {})
            faltan = [k for k in ("ndvi_mensual", "pendiente_pct", "humedad_suelo_pct") if d.get(k) is None]
            for k in faltan: d[k] = previo.get(k)
            d["campos_ejemplo"] = faltan
            db.guardar("clima", dict(zona_id=z["id"], datos=json.dumps(d)), 1, d["fuente"])
            print("Listo", z["id"], d["periodo"], "· de ejemplo todavía:", ", ".join(faltan) or "nada")
    elif tabla == "clima":
        for zid, d in json.load(open(ruta, encoding="utf-8")).items():
            db.guardar("clima", dict(zona_id=zid, datos=json.dumps(d)), 1, d.pop("fuente", "NASA"))
    else:
        for p in json.load(open(ruta, encoding="utf-8")):
            db.guardar("perfiles", dict(id=p["id"], nombre=p["nombre"], datos=json.dumps(p)), 1, p.get("fuente", "laboratorio"))
    print("Listo:", tabla)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
