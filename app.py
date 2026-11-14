"""Rotación Caribe: servidor Flask.

Variables de entorno (todas opcionales):
  ROTACION_SECRET        clave para firmar las sesiones (si no está, se crea .secret_key junto a la app)
  ROTACION_HTTPS=1       marca la cookie de sesión como segura (úsalo detrás de HTTPS)
  DATOS_ABIERTOS_CLAVES  claves separadas por coma para la API de datos abiertos; si está vacía, la API es pública
  EARTHDATA_USER/PASS, GEE_PROJECT, SOCRATA_DATASET, SOCRATA_COL_CIUDAD, SOCRATA_TOKEN: ver services/orquestador.py
"""
import hashlib, json, os, re, secrets, time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from flask import Flask, Response, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from services import estacas, motor
import db

app = Flask(__name__)

def _secreto():
    if os.environ.get("ROTACION_SECRET"): return os.environ["ROTACION_SECRET"]
    ruta = os.path.join(db.BASE, ".secret_key")
    if not os.path.exists(ruta):
        with open(ruta, "w") as f: f.write(secrets.token_hex(32))
    return open(ruta).read().strip()

app.config.update(SECRET_KEY=_secreto(), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("ROTACION_HTTPS") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30), MAX_CONTENT_LENGTH=256 * 1024)
SAL_DATOS = hashlib.sha256((app.config["SECRET_KEY"] + ":datos").encode()).hexdigest()
db.init()

@app.before_request
def _idioma():
    motor.IDIOMA.set("en" if (request.headers.get("X-Idioma") or request.args.get("idioma")) == "en" else "es")

def _t(es, en): return motor.tr(es, en)
def _error(es, en, codigo=400): return jsonify(error=_t(es, en)), codigo

def _suelo(s):
    return {"ph": float(s["ph"]), "n": s.get("n", "medio"), "p": s.get("p", "medio"), "k": s.get("k", "medio"),
            "humedad_pct": float(s.get("humedad_pct", 25)), "temp_suelo_c": float(s.get("temp_suelo_c", 29)),
            "salinidad": s.get("salinidad", "normal")}

def _ultimos(d):
    u = d.get("ultimos")
    if u is None: u = d.get("ultimo_cultivo")
    return u or []

# ------------------------------------------------------------------ Cuentas de usuario
CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_fallos = {}   # correo -> [marcas de tiempo de intentos fallidos]

def _usuario_actual():
    uid = session.get("uid")
    if not uid: return None
    f = db.consultar("SELECT id,nombre,apellido,correo,compartir_datos,perfil FROM usuarios WHERE id=?", (uid,))
    return f[0] if f else None

def _publico(u):
    return {"id": u["id"], "nombre": u["nombre"], "apellido": u["apellido"], "correo": u["correo"],
            "compartir_datos": bool(u["compartir_datos"]), "perfil": json.loads(u["perfil"]) if u.get("perfil") else None}

def requiere_login(fn):
    @wraps(fn)
    def envuelta(*a, **k):
        g.usuario = _usuario_actual()
        if not g.usuario: return _error("Inicia sesión para continuar.", "Please sign in to continue.", 401)
        return fn(*a, **k)
    return envuelta

@app.post("/api/registro")
def registro():
    d = request.get_json(force=True)
    nombre, apellido = (d.get("nombre") or "").strip()[:60], (d.get("apellido") or "").strip()[:60]
    correo, clave = (d.get("correo") or "").strip().lower()[:120], d.get("clave") or ""
    if not nombre or not apellido: return _error("Escribe tu nombre y tu apellido.", "Please enter your first and last name.")
    if not CORREO.match(correo): return _error("El correo no parece válido.", "That email does not look valid.")
    if not 8 <= len(clave) <= 128: return _error("La contraseña debe tener al menos 8 caracteres.", "The password must have at least 8 characters.")
    if not d.get("acepta_datos"): return _error("Debes aceptar el tratamiento de tus datos personales para crear la cuenta.",
                                                "You must accept the processing of your personal data to create an account.")
    if db.consultar("SELECT 1 FROM usuarios WHERE correo=?", (correo,)):
        return _error("Ya existe una cuenta con ese correo. Inicia sesión.", "An account with that email already exists. Please sign in.", 409)
    uid = db.ejecutar("INSERT INTO usuarios(nombre,apellido,correo,clave_hash,acepta_datos_en) VALUES(?,?,?,?,?)",
                      (nombre, apellido, correo, generate_password_hash(clave), datetime.now(timezone.utc).isoformat()))
    session.clear(); session.permanent = True; session["uid"] = uid
    return jsonify(usuario=_publico(_usuario_actual())), 201

@app.post("/api/login")
def login():
    d = request.get_json(force=True)
    correo, clave = (d.get("correo") or "").strip().lower(), d.get("clave") or ""
    ahora = time.time()
    intentos = [t for t in _fallos.get(correo, []) if ahora - t < 900]
    if len(intentos) >= 5: return _error("Demasiados intentos. Espera 15 minutos.", "Too many attempts. Wait 15 minutes.", 429)
    f = db.consultar("SELECT id, clave_hash FROM usuarios WHERE correo=?", (correo,))
    if not f or not check_password_hash(f[0]["clave_hash"], clave):
        _fallos[correo] = intentos + [ahora]
        return _error("Correo o contraseña incorrectos.", "Wrong email or password.", 401)
    _fallos.pop(correo, None)
    session.clear(); session.permanent = True; session["uid"] = f[0]["id"]
    return jsonify(usuario=_publico(_usuario_actual()))

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/yo")
@requiere_login
def yo():
    return jsonify(usuario=_publico(g.usuario))

@app.put("/api/perfil")
@requiere_login
def perfil():
    d = request.get_json(force=True)
    if "perfil" in d:
        texto = json.dumps(d["perfil"])
        if len(texto) > 20000: return _error("Perfil demasiado grande.", "Profile too large.")
        db.ejecutar("UPDATE usuarios SET perfil=? WHERE id=?", (texto, g.usuario["id"]))
    if "compartir_datos" in d:
        db.ejecutar("UPDATE usuarios SET compartir_datos=? WHERE id=?", (1 if d["compartir_datos"] else 0, g.usuario["id"]))
    return jsonify(ok=True)

# ------------------------------------------------------------------ Estacas (ESP32-S3)
@app.get("/api/estacas")
@requiere_login
def estacas_listar():
    return jsonify(estacas.listar(g.usuario["id"]))

@app.post("/api/estacas")
@requiere_login
def estacas_crear():
    d = request.get_json(force=True)
    lat, lon = d.get("lat"), d.get("lon")
    eid, token = estacas.crear(g.usuario["id"], d.get("nombre") or "Estaca", int(d.get("lote") or 1),
                               float(lat) if lat is not None else None, float(lon) if lon is not None else None)
    return jsonify(id=eid, token=token, aviso=_t("Copia este token en la estaca. No se vuelve a mostrar.",
                                                  "Copy this token into the stake. It will not be shown again.")), 201

@app.delete("/api/estacas/<int:eid>")
@requiere_login
def estacas_borrar(eid):
    estacas.borrar(g.usuario["id"], eid)
    return jsonify(ok=True)

@app.get("/api/estacas/<int:eid>/lecturas")
@requiere_login
def estacas_lecturas(eid):
    filas = estacas.lecturas(g.usuario["id"], eid, int(request.args.get("dias", 30)))
    if filas is None: return _error("Esa estaca no es tuya.", "That stake is not yours.", 404)
    return jsonify(filas)

@app.post("/api/estaca/lecturas")
def estaca_enviar():
    """Lo llama la estaca: Authorization: Bearer <token>. Cuerpo: {"lecturas": [...]} o una sola lectura."""
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    e = estacas.por_token(token)
    if not e: return jsonify(error="token no válido"), 401
    d = request.get_json(force=True, silent=True)
    if d is None: return jsonify(error="JSON no válido"), 400
    try: n = estacas.guardar_lecturas(e, d.get("lecturas") if isinstance(d, dict) and "lecturas" in d else [d])
    except (ValueError, TypeError) as ex: return jsonify(error=str(ex)), 400
    return jsonify(guardadas=n, estaca=e["id"]), 201

# ------------------------------------------------------------------ Datos abiertos (para la NASA, universidades u otras entidades)
@app.get("/api/datos_abiertos")
def datos_abiertos_info():
    return jsonify({"descripcion": "Lecturas de suelo de las estacas de Rotación Caribe, solo de usuarios que autorizaron compartirlas.",
                    "privacidad": "Sin nombres ni correos; código de estaca seudónimo; ubicación redondeada a 0,01° (unos 1,1 km).",
                    "uso": "/api/datos_abiertos/lecturas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD&formato=json|csv",
                    "unidades": {"ph": "pH", "humedad_pct": "% volumétrico (según calibración del sensor)", "temp_suelo_c": "°C",
                                 "ce_us_cm": "µS/cm", "n_mg_kg": "mg/kg", "p_mg_kg": "mg/kg", "k_mg_kg": "mg/kg",
                                 "temp_aire_c": "°C", "humedad_aire_pct": "%"},
                    "requiere_clave": bool(os.environ.get("DATOS_ABIERTOS_CLAVES"))})

@app.get("/api/datos_abiertos/lecturas")
def datos_abiertos():
    claves = [c.strip() for c in os.environ.get("DATOS_ABIERTOS_CLAVES", "").split(",") if c.strip()]
    if claves and request.headers.get("X-Api-Key") not in claves: return jsonify(error="clave de API no válida"), 401
    try:
        hasta = date.fromisoformat(request.args["hasta"]) if request.args.get("hasta") else date.today() + timedelta(days=1)
        desde = date.fromisoformat(request.args["desde"]) if request.args.get("desde") else hasta - timedelta(days=31)
    except ValueError: return jsonify(error="fechas en formato AAAA-MM-DD"), 400
    if (hasta - desde).days > 366: return jsonify(error="máximo 366 días por consulta"), 400
    filas = estacas.datos_abiertos(SAL_DATOS, desde.isoformat(), hasta.isoformat())
    if request.args.get("formato") == "csv":
        return Response(estacas.a_csv(filas), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=estacas_{desde}_{hasta}.csv"})
    return jsonify(desde=desde.isoformat(), hasta=hasta.isoformat(), total=len(filas), lecturas=filas)

# ------------------------------------------------------------------ Datos externos del punto (SoilGrids, NASA, Earth Engine)
@app.post("/api/datos_lote")
def datos_lote():
    from services import orquestador
    d = request.get_json(force=True)
    lat, lon = float(d["lat"]), float(d["lon"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180): return _error("Coordenadas no válidas.", "Invalid coordinates.")
    clave = f"{round(lat, 3)},{round(lon, 3)}"
    f = db.consultar("SELECT datos, creado_en FROM externos WHERE clave=? AND creado_en >= datetime('now','-7 days')", (clave,))
    if f: return jsonify(dict(json.loads(f[0]["datos"]), cache=True))
    res = orquestador.perfil_lote(lat, lon)
    if any(v == "ok" for v in res["fuentes"].values()):
        db.ejecutar("INSERT OR REPLACE INTO externos(clave, datos, creado_en) VALUES(?,?,datetime('now'))", (clave, json.dumps(res)))
    return jsonify(dict(res, cache=False))

# ------------------------------------------------------------------ Catálogo y motor
@app.route("/")
def index():
    return send_from_directory("templates", "index.html")

@app.get("/api/zonas")
def zonas():
    out = []
    for z in db.consultar("SELECT * FROM zonas"):
        z["clima"], z["clima_verificado"] = motor.clima_de(z["id"])
        z["riego"] = bool(z["riego"])
        out.append(z)
    return jsonify(out)

@app.get("/api/perfiles")
def perfiles():
    return jsonify([json.loads(p["datos"]) for p in db.consultar("SELECT datos FROM perfiles")])

@app.get("/api/cultivos")
def cultivos():
    return jsonify(db.consultar("SELECT * FROM cultivos"))

@app.get("/api/estado")
def estado():
    n = lambda t: db.consultar(f"SELECT COUNT(*) n FROM {t} WHERE verificado=0")[0]["n"]
    return jsonify({t: n(t) for t in db.CATALOGO})

@app.get("/api/clima_diario")
def clima_diario():
    return jsonify(motor.diario(request.args["zona_id"], int(request.args["mes"]), int(request.args.get("anio", date.today().year))))

@app.post("/api/panel")
def panel():
    d = request.get_json(force=True)
    return jsonify(motor.panel(d["zona_id"], _suelo(d["suelo"]), d.get("textura"), d.get("riego")))

@app.post("/api/recomendar")
def recomendar():
    d = request.get_json(force=True)
    return jsonify(motor.recomendar(d["zona_id"], _suelo(d["suelo"]), d.get("prioridades"), _ultimos(d), d.get("riego"), d.get("textura")))

@app.post("/api/simular")
def simular():
    d = request.get_json(force=True)
    return jsonify(motor.simular(d["zona_id"], _suelo(d["suelo"]), d.get("textura"), d.get("riego"), d["secuencia"], _ultimos(d),
                                 max(.1, float(d.get("ha", 5))), max(1, min(10, int(d.get("anios", 5))))))

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
