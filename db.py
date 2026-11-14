"""Capa de datos SQLite. Todo lo sembrado al inicio es DE EJEMPLO (verificado=0).
Para cargar datos reales: python importar.py <cultivos|zonas|clima|perfiles> archivo"""
import json, os, sqlite3
from contextlib import closing

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "rotacion.db")
VERSION = 3
EJEMPLO = "dato de ejemplo (pendiente de validar)"
CULT = ["cultivo","nombre","icono","familia","tipo","ciclo_dias","agua_mm","ph_min","ph_max","tol_sequia",
        "tol_salinidad","fija_n","demanda_n","cobertura","ingreso_rel","forraje","materia_organica","mercado"]
ZON = ["id","nombre","lat","lon","suelo","riego"]
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS cultivos({','.join(CULT)}, fuente, verificado INTEGER DEFAULT 0, PRIMARY KEY(cultivo));
CREATE TABLE IF NOT EXISTS zonas({','.join(ZON)}, fuente, verificado INTEGER DEFAULT 0, PRIMARY KEY(id));
CREATE TABLE IF NOT EXISTS clima(zona_id TEXT PRIMARY KEY, datos TEXT, fuente, verificado INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS perfiles(id TEXT PRIMARY KEY, nombre TEXT, datos TEXT, fuente, verificado INTEGER DEFAULT 0);
"""

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def consultar(sql, args=()):
    with closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def guardar(tabla, fila, verificado, fuente):
    fila = dict(fila, fuente=fuente, verificado=verificado)
    cols = ",".join(fila)
    with closing(conn()) as c:
        c.execute(f"INSERT OR REPLACE INTO {tabla}({cols}) VALUES({','.join('?'*len(fila))})", list(fila.values()))
        c.commit()

def _leer(n):
    return json.load(open(os.path.join(BASE, "data", n), encoding="utf-8"))

def _version():
    with closing(sqlite3.connect(DB)) as c:
        return c.execute("PRAGMA user_version").fetchone()[0]

def init(forzar=False):
    if os.path.exists(DB) and (forzar or _version() != VERSION):
        os.remove(DB)   # esquema nuevo: se vuelve a sembrar con datos de ejemplo
    with closing(conn()) as c:
        c.executescript(SCHEMA)
        c.execute(f"PRAGMA user_version={VERSION}")
        c.commit()
        vacio = lambda t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
        sembrar = vacio("cultivos")
    if sembrar:
        for r in _leer("cultivos.json"): guardar("cultivos", r, 0, EJEMPLO)
        for z in _leer("zonas.json"): guardar("zonas", dict(z, riego=int(z["riego"])), 0, EJEMPLO)
        for k, d in _leer("clima_ejemplo.json").items(): guardar("clima", dict(zona_id=k, datos=json.dumps(d)), 0, EJEMPLO)
        for p in _leer("perfiles_suelo.json"):
            guardar("perfiles", dict(id=p["id"], nombre=p["nombre"], datos=json.dumps(p)), 0, EJEMPLO)
