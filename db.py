"""Capa de datos SQLite.

Dos grupos de tablas:
- Catálogo (cultivos, zonas, clima, perfiles): se vuelve a sembrar con datos DE EJEMPLO cuando cambia VERSION.
  Para cargar datos reales: python importar.py <cultivos|zonas|clima|perfiles|nasa> archivo
- Usuarios (usuarios, estacas, lecturas, externos): NUNCA se borran al actualizar la app."""
import json, os, sqlite3
from contextlib import closing

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ROTACION_DB", os.path.join(BASE, "rotacion.db"))
VERSION = 4
EJEMPLO = "dato de ejemplo (pendiente de validar)"
CULT = ["cultivo","nombre","nombre_en","icono","familia","tipo","ciclo_dias","agua_mm","ph_min","ph_max","tol_sequia",
        "tol_salinidad","fija_n","demanda_n","cobertura","ingreso_rel","forraje","materia_organica","mercado"]
ZON = ["id","nombre","lat","lon","suelo","riego"]
CATALOGO = ("cultivos", "zonas", "clima", "perfiles")
SCHEMA_CATALOGO = f"""
CREATE TABLE IF NOT EXISTS cultivos({','.join(CULT)}, fuente, verificado INTEGER DEFAULT 0, PRIMARY KEY(cultivo));
CREATE TABLE IF NOT EXISTS zonas({','.join(ZON)}, fuente, verificado INTEGER DEFAULT 0, PRIMARY KEY(id));
CREATE TABLE IF NOT EXISTS clima(zona_id TEXT PRIMARY KEY, datos TEXT, fuente, verificado INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS perfiles(id TEXT PRIMARY KEY, nombre TEXT, datos TEXT, fuente, verificado INTEGER DEFAULT 0);
"""
SCHEMA_USUARIOS = """
CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL, apellido TEXT NOT NULL, correo TEXT NOT NULL UNIQUE COLLATE NOCASE,
  clave_hash TEXT NOT NULL,
  acepta_datos_en TEXT NOT NULL,          -- fecha de la autorización de tratamiento de datos (Ley 1581 de 2012)
  compartir_datos INTEGER NOT NULL DEFAULT 0,  -- 1 = autoriza compartir lecturas anónimas de sus estacas
  perfil TEXT,                            -- configuración de la app en JSON (zona, riego, idioma, tema...)
  creado_en TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS estacas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  nombre TEXT NOT NULL, lote INTEGER NOT NULL DEFAULT 1,
  lat REAL, lon REAL,
  token_hash TEXT NOT NULL UNIQUE,        -- SHA-256 del token del dispositivo (el token solo se muestra una vez)
  creada_en TEXT NOT NULL DEFAULT (datetime('now')),
  ultima_vez TEXT);
CREATE TABLE IF NOT EXISTS lecturas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  estaca_id INTEGER NOT NULL REFERENCES estacas(id) ON DELETE CASCADE,
  fecha TEXT NOT NULL,                    -- UTC, ISO 8601
  ph REAL, humedad_pct REAL, temp_suelo_c REAL, ce_us_cm REAL,
  n_mg_kg REAL, p_mg_kg REAL, k_mg_kg REAL,
  temp_aire_c REAL, humedad_aire_pct REAL, bateria_v REAL, rssi_dbm REAL);
CREATE INDEX IF NOT EXISTS ix_lecturas_estaca_fecha ON lecturas(estaca_id, fecha);
CREATE TABLE IF NOT EXISTS externos(
  clave TEXT PRIMARY KEY, datos TEXT NOT NULL, creado_en TEXT NOT NULL DEFAULT (datetime('now')));
"""

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def consultar(sql, args=()):
    with closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def ejecutar(sql, args=()):
    """Escribe y devuelve el id de la fila nueva (si aplica)."""
    with closing(conn()) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid

def ejecutar_varios(sql, filas):
    with closing(conn()) as c:
        c.executemany(sql, filas)
        c.commit()

def guardar(tabla, fila, verificado, fuente):
    fila = dict(fila, fuente=fuente, verificado=verificado)
    cols = ",".join(fila)
    with closing(conn()) as c:
        c.execute(f"INSERT OR REPLACE INTO {tabla}({cols}) VALUES({','.join('?'*len(fila))})", list(fila.values()))
        c.commit()

def _leer(n):
    return json.load(open(os.path.join(BASE, "data", n), encoding="utf-8"))

def init(forzar=False):
    with closing(conn()) as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if forzar or version != VERSION:
            for t in CATALOGO: c.execute(f"DROP TABLE IF EXISTS {t}")   # solo el catálogo de ejemplo
        c.executescript(SCHEMA_CATALOGO + SCHEMA_USUARIOS)
        c.execute(f"PRAGMA user_version={VERSION}")
        c.commit()
        sembrar = c.execute("SELECT COUNT(*) FROM cultivos").fetchone()[0] == 0
    if sembrar:
        for r in _leer("cultivos.json"): guardar("cultivos", r, 0, EJEMPLO)
        for z in _leer("zonas.json"): guardar("zonas", dict(z, riego=int(z["riego"])), 0, EJEMPLO)
        for k, d in _leer("clima_ejemplo.json").items(): guardar("clima", dict(zona_id=k, datos=json.dumps(d)), 0, EJEMPLO)
        # Copia de datos reales de la NASA hecha por la propia app (services/sincronizar.py). Si viene con el código,
        # un servidor que arranca con el disco vacío (Render) empieza ya con datos reales.
        if os.path.exists(os.path.join(BASE, "data", "clima_real.json")):
            try:
                for k, d in _leer("clima_real.json").get("zonas", {}).items():
                    guardar("clima", dict(zona_id=k, datos=json.dumps(d)), 1, d.get("fuente") or "NASA POWER")
            except (ValueError, AttributeError, OSError):
                pass
        for p in _leer("perfiles_suelo.json"):
            guardar("perfiles", dict(id=p["id"], nombre=p["nombre"], datos=json.dumps(p)), 0, EJEMPLO)
