"""Capa de datos SQLite.

Dos grupos de tablas:
- Catálogo (cultivos, zonas, clima, perfiles): se vuelve a sembrar con datos DE EJEMPLO cuando cambia VERSION.
  Para cargar datos reales: python importar.py <cultivos|zonas|clima|perfiles|nasa> archivo
- Usuarios (usuarios, estacas, lecturas, externos): NUNCA se borran al actualizar la app.

Cuentas que no se pierden: si existe la variable de entorno DATABASE_URL (una base Postgres, por ejemplo de Neon o
de Render), las tablas usuarios, estacas y lecturas viven allá. Así sobreviven a los reinicios de un servidor que borra
su disco (Render gratis). El catálogo, el clima y las cachés siguen en SQLite: se vuelven a crear o descargar solos."""
import json, os, re, sqlite3, threading
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
CREATE TABLE IF NOT EXISTS codigos(       -- códigos de verificación (solo su HMAC; ver services/codigos.py)
  destino TEXT NOT NULL, proposito TEXT NOT NULL, codigo_hash TEXT NOT NULL, expira REAL NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0, enviado_en REAL NOT NULL, enviados INTEGER NOT NULL DEFAULT 1, ventana REAL NOT NULL,
  datos TEXT, PRIMARY KEY(destino, proposito));
CREATE TABLE IF NOT EXISTS rotaciones(     -- versión 18: rotaciones que la persona guardó
  id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  zona_id TEXT, zona TEXT, clave TEXT NOT NULL, datos TEXT NOT NULL, creada_en TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS ix_rotaciones_usuario ON rotaciones(usuario_id);
"""

PG_URL = os.environ.get("DATABASE_URL", "").strip()
_EN_PG = re.compile(r"\b(?:usuarios|estacas|lecturas|codigos|rotaciones)\b")
_INSERTA_PG = re.compile(r"\s*INSERT\s+INTO\s+(?:usuarios|estacas|lecturas|rotaciones)\b", re.I)
_AHORA_PG = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"   # mismo formato que datetime('now') de SQLite
SCHEMA_PG = [f"""CREATE TABLE IF NOT EXISTS usuarios(
  id BIGSERIAL PRIMARY KEY,
  nombre TEXT NOT NULL, apellido TEXT NOT NULL, correo TEXT NOT NULL UNIQUE,   -- la app guarda el correo en minúsculas
  clave_hash TEXT NOT NULL, acepta_datos_en TEXT NOT NULL, compartir_datos INTEGER NOT NULL DEFAULT 0,
  perfil TEXT, creado_en TEXT NOT NULL DEFAULT ({_AHORA_PG}))""",
 f"""CREATE TABLE IF NOT EXISTS estacas(
  id BIGSERIAL PRIMARY KEY, usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  nombre TEXT NOT NULL, lote INTEGER NOT NULL DEFAULT 1, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
  token_hash TEXT NOT NULL UNIQUE, creada_en TEXT NOT NULL DEFAULT ({_AHORA_PG}), ultima_vez TEXT)""",
 """CREATE TABLE IF NOT EXISTS lecturas(
  id BIGSERIAL PRIMARY KEY, estaca_id BIGINT NOT NULL REFERENCES estacas(id) ON DELETE CASCADE,
  fecha TEXT NOT NULL,
  ph DOUBLE PRECISION, humedad_pct DOUBLE PRECISION, temp_suelo_c DOUBLE PRECISION, ce_us_cm DOUBLE PRECISION,
  n_mg_kg DOUBLE PRECISION, p_mg_kg DOUBLE PRECISION, k_mg_kg DOUBLE PRECISION,
  temp_aire_c DOUBLE PRECISION, humedad_aire_pct DOUBLE PRECISION, bateria_v DOUBLE PRECISION, rssi_dbm DOUBLE PRECISION)""",
 "CREATE INDEX IF NOT EXISTS ix_lecturas_estaca_fecha ON lecturas(estaca_id, fecha)",
 """CREATE TABLE IF NOT EXISTS codigos(
  destino TEXT NOT NULL, proposito TEXT NOT NULL, codigo_hash TEXT NOT NULL, expira DOUBLE PRECISION NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0, enviado_en DOUBLE PRECISION NOT NULL, enviados INTEGER NOT NULL DEFAULT 1,
  ventana DOUBLE PRECISION NOT NULL, datos TEXT, PRIMARY KEY(destino, proposito))""",
 "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS celular TEXT",                    # versión 16: recuperar la cuenta por SMS
 "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS celular_ok INTEGER NOT NULL DEFAULT 0",
 "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS invitado INTEGER NOT NULL DEFAULT 0",
 f"""CREATE TABLE IF NOT EXISTS rotaciones(
  id BIGSERIAL PRIMARY KEY, usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  zona_id TEXT, zona TEXT, clave TEXT NOT NULL, datos TEXT NOT NULL, creada_en TEXT NOT NULL DEFAULT ({_AHORA_PG}))""",   # versión 18
 "CREATE INDEX IF NOT EXISTS ix_rotaciones_usuario ON rotaciones(usuario_id)"]     # versión 17: entrar solo con el nombre
_pg_local = threading.local()

def modo_cuentas():
    return "postgres" if PG_URL else "sqlite"

def _usa_pg(sql):
    return bool(PG_URL) and bool(_EN_PG.search(sql))

def _pg_nueva():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(PG_URL, autocommit=True, row_factory=dict_row, connect_timeout=15)

def _pg_conn():
    """Una conexión por hilo y por proceso (gunicorn --preload crea el proceso hijo después de importar la app)."""
    c = getattr(_pg_local, "c", None)
    if c is None or c.closed or getattr(_pg_local, "pid", None) != os.getpid():
        _pg_local.c, _pg_local.pid = _pg_nueva(), os.getpid()
    return _pg_local.c

def _pg_hacer(fn):
    """Ejecuta fn(conexión). Si la conexión se cayó (los Postgres en la nube cierran las inactivas), reconecta una vez."""
    import psycopg
    for intento in (1, 2):
        try:
            return fn(_pg_conn())
        except psycopg.OperationalError:
            try: _pg_local.c.close()
            except Exception: pass
            _pg_local.c = None
            if intento == 2: raise

def _pg_sql(sql, con_args):
    """Del dialecto de la app (SQLite, con ?) al de psycopg (%s)."""
    return (sql.replace("%", "%%") if con_args else sql).replace("?", "%s")

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def consultar(sql, args=()):
    if _usa_pg(sql):
        return _pg_hacer(lambda c: [dict(r) for r in c.execute(_pg_sql(sql, bool(args)), tuple(args) if args else None).fetchall()])
    with closing(conn()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def ejecutar(sql, args=()):
    """Escribe y devuelve el id de la fila nueva (si aplica)."""
    if _usa_pg(sql):
        ins = bool(_INSERTA_PG.match(sql)); q = _pg_sql(sql, bool(args)) + (" RETURNING id" if ins else "")
        def hacer(c):
            cur = c.execute(q, tuple(args) if args else None)
            return cur.fetchone()["id"] if ins else cur.rowcount
        return _pg_hacer(hacer)
    with closing(conn()) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid if sql.lstrip()[:6].upper() == "INSERT" else cur.rowcount   # igual que en Postgres

def ejecutar_varios(sql, filas):
    if _usa_pg(sql):
        def hacer(c):
            with c.transaction(), c.cursor() as cur:
                cur.executemany(_pg_sql(sql, True), [tuple(f) for f in filas])
        return _pg_hacer(hacer)
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
        cols = {r[1] for r in c.execute("PRAGMA table_info(usuarios)")}      # versión 16: celular para recuperar la cuenta
        if "celular" not in cols: c.execute("ALTER TABLE usuarios ADD COLUMN celular TEXT")
        if "celular_ok" not in cols: c.execute("ALTER TABLE usuarios ADD COLUMN celular_ok INTEGER NOT NULL DEFAULT 0")
        if "invitado" not in cols: c.execute("ALTER TABLE usuarios ADD COLUMN invitado INTEGER NOT NULL DEFAULT 0")   # versión 17
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
    # Cultivos nuevos del catálogo (por ejemplo, el pasto) en bases que ya existían: se agregan sin tocar los demás
    with closing(conn()) as c:
        hay = {r[0] for r in c.execute("SELECT cultivo FROM cultivos")}
    for r in _leer("cultivos.json"):
        if r["cultivo"] not in hay: guardar("cultivos", r, 0, EJEMPLO)
    if PG_URL: _init_pg()

def _init_pg():
    """Crea las tablas de cuentas en Postgres si no existen (nunca borra nada). Conexión propia y cerrada al final,
    para que el proceso hijo de gunicorn no herede un socket abierto."""
    import time
    for intento in range(3):
        try:
            with closing(_pg_nueva()) as c:
                for q in SCHEMA_PG: c.execute(q)
            return
        except Exception as e:
            if intento == 2:
                raise RuntimeError(f"No se pudo conectar a la base de cuentas (DATABASE_URL): {e}") from e
            time.sleep(3)
