"""Prepara data/municipios.json: qué se siembra en cada municipio de Colombia, en qué semestre y dónde queda.

Fuentes:
  - Evaluaciones Agropecuarias Municipales (EVA), base agrícola 2019-2024 (UPRA / MinAgricultura), archivo
    20250617_BaseAgricola20192024.xlsx. Los dos últimos años pueden cambiar y la forma de medir los cultivos
    transitorios cambió desde 2022 (notas del propio archivo).
  - Coordenadas de las cabeceras municipales, una de dos:
      --divipola  CSV oficial del DANE "DIVIPOLA - Códigos municipios" (datos.gov.co, conjunto gdxc-w37w), el preferido.
      --sivel     datos-geo-col.sql del proyecto SIVeL (dominio público, armado con DIVIPOLA 2013, Divipolador y OSM).
                  Sirve mientras tanto, pero tiene errores (Mompox queda a 16,9 km de su cabecera).
    Si das los dos, se usa el del DANE y se imprime cuánto difiere cada municipio del de SIVeL.
  - Las 8 zonas piloto conservan sus propias coordenadas (data/zonas.json).

Uso (necesita pandas y openpyxl, solo en tu computador; el servidor no los usa):
  python herramientas/preparar_municipios.py --eva 20250617_BaseAgricola20192024.xlsx --sivel datos-geo-col.sql [--divipola DIVIPOLA.csv]
  Con --region caribe sale solo el Caribe (como en la versión 16).

Semestres: la EVA reporta los cultivos transitorios por semestre (A: siembras de enero a junio; B: de julio a
diciembre). La app los compara con sus temporadas: primeras lluvias ≈ semestre A, segundas lluvias ≈ semestre B.
"""
import argparse, csv, json, math, re, sys, unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARIBE = ["Atlántico", "Bolívar", "Cesar", "Córdoba", "La Guajira", "Magdalena", "Sucre"]
# Cultivo del catálogo → nombre en la EVA. Ojo: "Frijol" en la EVA junta todas las clases de fríjol; en el Caribe
# buena parte es caupí, pero la base no lo separa, así que es una aproximación.
EVA = {"name": "Ñame", "yuca": "Yuca", "maiz": "Maíz", "arroz": "Arroz", "frijol": "Frijol", "guandul": "Guandul", "ajonjoli": "Ajonjolí"}
PILOTO = {"monteria": 23001, "valledupar": 20001, "zona_bananera": 47980, "san_jacinto": 13654, "repelon": 8606, "mompox": 13468, "sincelejo": 70001, "riohacha": 44001}

def sin_tildes(s): return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
def km(a, b, c, d):
    r = math.radians
    h = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))

def leer_sivel(ruta):
    """Municipios del SQL de SIVeL: INSERT INTO municipio (id, nombre, id_departamento, latitud, longitud, fechacreacion,
    fechadeshabilitacion). El código DANE es id_departamento * 1000 + id. Se omiten los deshabilitados y los sin coordenadas."""
    txt = Path(ruta).read_text(encoding="utf-8", errors="replace")
    out = {}
    if ruta.endswith(".json"):          # copia ya procesada: {"mun": [{"cod", "nombre", "dep", "lat", "lon"}]}
        for m in json.loads(txt)["mun"]:
            if m.get("lat") is not None: out[int(m["cod"])] = (float(m["lat"]), float(m["lon"]))
        return out
    val = lambda v: None if v == "NULL" else v.strip("'").replace("''", "'") if v.startswith("'") else float(v)
    for m in re.finditer(r"INSERT INTO (?:public\.)?(?:msip_)?municipio \(([^)]*)\) VALUES \((.*?)\);\n", txt):
        f = dict(zip([c.strip() for c in m.group(1).split(",")], [val(v) for v in re.findall(r"'(?:[^']|'')*'|NULL|-?[\d.]+", m.group(2))]))
        if f.get("fechadeshabilitacion") or f.get("latitud") is None: continue
        out[int(f["id_departamento"]) * 1000 + int(f["id"])] = (float(f["latitud"]), float(f["longitud"]))
    return out

def leer_divipola(ruta):
    """CSV del DANE. Se buscan las columnas por nombre (código de municipio, latitud y longitud) para no depender
    del orden exacto, que no pude confirmar porque datos.gov.co no se pudo abrir desde aquí."""
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";" if f.readline().count(";") > 2 else ","))
    if not filas: return {}
    cols = {sin_tildes(c): c for c in filas[0]}
    def col(*nombres):
        for n in nombres:
            for k, c in cols.items():
                if n in k: return c
        sys.exit(f"No encontré la columna {nombres} en {ruta}. Columnas: {list(filas[0])}")
    c_cod, c_lat, c_lon = col("cod_mpio", "codigo_municipio", "cod_municipio", "codigo"), col("latitud", "lat"), col("longitud", "lon")
    out = {}
    for r in filas:
        try: out[int(re.sub(r"\D", "", r[c_cod]))] = (float(r[c_lat].replace(",", ".")), float(r[c_lon].replace(",", ".")))
        except ValueError: pass
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eva", required=True); ap.add_argument("--sivel"); ap.add_argument("--divipola")
    ap.add_argument("--salida", default=str(RAIZ / "data" / "municipios.json"))
    ap.add_argument("--region", choices=["colombia", "caribe"], default="colombia")
    a = ap.parse_args()
    if not (a.sivel or a.divipola): sys.exit("Falta --divipola o --sivel (coordenadas).")
    import pandas as pd
    df = pd.read_pickle(a.eva) if a.eva.endswith(".pkl") else pd.read_excel(a.eva, header=7)
    if a.region == "caribe": df = df[df["Departamento"].isin(CARIBE)]
    df = df.copy()
    df["Municipio"] = df["Municipio"].astype(str).str.replace("*", "", regex=False).str.strip()
    anios = sorted(int(x) for x in df["Año"].dropna().unique())

    sivel = leer_sivel(a.sivel) if a.sivel else {}
    dane = leer_divipola(a.divipola) if a.divipola else {}
    coords, geo = (dane, "DANE DIVIPOLA") if dane else (sivel, "SIVeL (provisional)")
    zonas = {z["id"]: z for z in json.loads((RAIZ / "data" / "zonas.json").read_text(encoding="utf-8"))}
    zona_de = {cod: zid for zid, cod in PILOTO.items()}

    if dane and sivel:
        dif = sorted(((km(*dane[c], *sivel[c]), c) for c in dane if c in sivel), reverse=True)
        print(f"DANE frente a SIVeL ({len(dif)} municipios): más de 5 km en {sum(d > 5 for d, _ in dif)}")
        for d, c in dif[:10]: print(f"   {c}: {d:.1f} km")

    # Área sembrada al año (suma de los semestres A y B) y rendimiento por cosecha (producción / área cosechada).
    anual = df.groupby(["Código Dane municipio", "Cultivo", "Año"], as_index=False).agg(
        area=("Área sembrada (ha)", "sum"), cos=("Área cosechada (ha)", "sum"), prod=("Producción (t)", "sum"))
    por = anual.groupby(["Código Dane municipio", "Cultivo"]).agg(area=("area", "mean"), cos=("cos", "sum"), prod=("prod", "sum"), anios=("Año", "nunique")).reset_index()
    per = df["Periodo"].astype(str)
    df["sem"] = per.str[-1].where(per.str[-1].isin(["A", "B"]), "")
    sem = df[df["sem"] != ""].groupby(["Código Dane municipio", "Cultivo", "sem"])["Área sembrada (ha)"].sum()
    dep_rend = {}
    for (dep, cul), g in df.groupby(["Departamento", "Cultivo"]):
        cos, prod = g["Área cosechada (ha)"].sum(), g["Producción (t)"].sum()
        if cos > 0 and prod > 0: dep_rend[(dep, cul)] = prod / cos

    nombres = df.drop_duplicates("Código Dane municipio").set_index("Código Dane municipio")[["Municipio", "Departamento"]]
    municipios, sin_coord, raros = [], [], []
    for cod, fila in nombres.sort_index().iterrows():
        cod = int(cod); zid = zona_de.get(cod)
        if zid: lat, lon, fuente_geo = zonas[zid]["lat"], zonas[zid]["lon"], "zona piloto"
        elif cod in coords: (lat, lon), fuente_geo = coords[cod], geo
        else: sin_coord.append(f"{cod} {fila['Municipio']}"); continue
        p = por[por["Código Dane municipio"] == cod]
        nuestros = {}
        for cid, nom in EVA.items():
            r = p[p["Cultivo"] == nom]
            if r.empty or r["area"].iloc[0] <= 0: continue
            r = r.iloc[0]
            rend = r["prod"] / r["cos"] if r["cos"] > 0 and r["prod"] > 0 else None
            ref = dep_rend.get((fila["Departamento"], nom))
            if rend and ref and not (ref / 3 <= rend <= ref * 3):      # muy lejos de lo del departamento: se usa el del departamento
                raros.append(f"{fila['Municipio']} {nom}: {rend:.1f} t/ha (dpto {ref:.1f})"); rend = None
            n_ = int(r["anios"])
            sa, sb = (float(sem.get((cod, nom, x), 0)) / n_ for x in "AB")
            nuestros[cid] = {"ha": round(float(r["area"]), 1), "a": round(sa, 1), "b": round(sb, 1),
                             "rend": round(float(rend), 2) if rend else None, "anios": n_}
        top = p.sort_values("area", ascending=False).head(6)
        municipios.append({"cod": cod, "n": fila["Municipio"], "d": fila["Departamento"], "lat": round(lat, 5), "lon": round(lon, 5),
                           "zona": zid, "geo": fuente_geo, "nuestros": nuestros,
                           "top": [[c, round(float(x))] for c, x in zip(top["Cultivo"], top["area"]) if x >= 1]})
    deps = {d: {cid: round(dep_rend[(d, nom)], 2) for cid, nom in EVA.items() if (d, nom) in dep_rend} for d in sorted(df["Departamento"].unique())}
    out = {"fuente": {"cultivos": f"Evaluaciones Agropecuarias Municipales (EVA) {anios[0]}-{anios[-1]}, UPRA y Ministerio de Agricultura",
                      "coordenadas": geo, "nota": "Los dos últimos años de la EVA pueden cambiar y la forma de medir los cultivos transitorios cambió desde 2022. "
                      "«Frijol» en la EVA junta todas las clases de fríjol."},
           "anios": [anios[0], anios[-1]], "eva": EVA, "caribe": CARIBE, "departamentos": deps, "municipios": municipios}
    Path(a.salida).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    vieja = RAIZ / "data" / "municipios_caribe.json"
    if a.salida.endswith("municipios.json") and vieja.exists(): vieja.unlink()          # la versión 16 usaba ese nombre
    print(f"{len(municipios)} municipios → {a.salida} ({Path(a.salida).stat().st_size / 1024:.0f} KB) · coordenadas: {geo}")
    if sin_coord: print("Sin coordenadas (quedan por fuera):", ", ".join(sin_coord))
    if raros: print(f"Rendimientos muy lejos del departamento (se usa el del departamento): {len(raros)}"); [print("  ", x) for x in raros[:12]]

if __name__ == "__main__": main()
