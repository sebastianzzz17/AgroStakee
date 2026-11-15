"""AgroStake: servidor Flask.

Al arrancar descarga SOLA, en segundo plano, los datos reales de la NASA de las 8 zonas (services/sincronizar.py).
Para apagarlo: AGROSTAKE_SIN_DESCARGA=1.

Variables de entorno (todas opcionales):
  ROTACION_SECRET        clave para firmar las sesiones (si no está, se crea .secret_key junto a la app)
  ROTACION_HTTPS=1       marca la cookie de sesión como segura (úsalo detrás de HTTPS)
  DATOS_ABIERTOS_CLAVES  claves separadas por coma para la API de datos abiertos; si está vacía, la API es pública
  EARTHDATA_USER/PASS, GEE_PROJECT, SOCRATA_DATASET, SOCRATA_COL_CIUDAD, SOCRATA_TOKEN: ver services/orquestador.py
  AGROSTAKE_SIN_DESCARGA=1  apaga la descarga automática de datos de la NASA (services/sincronizar.py)
"""
import gzip, hashlib, json, os, re, secrets, time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from flask import Flask, Response, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from services import codigos, mensajeria, municipios, estacas, historico, ideam, motor, sincronizar
import db

PILOTO = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "piloto.json"), encoding="utf-8"))

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
    sincronizar.iniciar()          # descarga automática de datos reales (una sola vez, en segundo plano)

def _zona_valida(zid):
    """Zona guardada o punto libre del mapa ("p:lat,lon"). Devuelve la fila o None."""
    try: return motor.zona(zid)
    except (KeyError, ValueError): return None

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
    f = db.consultar("SELECT id,nombre,apellido,correo,compartir_datos,perfil,celular,celular_ok FROM usuarios WHERE id=?", (uid,))
    return f[0] if f else None

def _publico(u):
    return {"id": u["id"], "nombre": u["nombre"], "apellido": u["apellido"], "correo": u["correo"],
            "compartir_datos": bool(u["compartir_datos"]), "perfil": json.loads(u["perfil"]) if u.get("perfil") else None,
            "celular": u.get("celular"), "celular_ok": bool(u.get("celular_ok"))}

def requiere_login(fn):
    @wraps(fn)
    def envuelta(*a, **k):
        g.usuario = _usuario_actual()
        if not g.usuario: return _error("Inicia sesión para continuar.", "Please sign in to continue.", 401)
        return fn(*a, **k)
    return envuelta

# Verificación por código: el correo sale por Brevo/Resend (Render gratis bloquea SMTP) y el SMS por Twilio.
# Ver services/mensajeria.py (configuración) y services/codigos.py (seguridad de los códigos).
def _host(): return (request.host or "").split(":")[0]

# Límite por conexión: como máximo AGROSTAKE_CODIGOS_POR_IP envíos de código por hora (20 por defecto) desde una
# misma dirección IP, para que nadie agote el cupo gratis de correos (Brevo: 300 al día) ni haga gastar SMS. No es
# más bajo porque en una universidad o una feria mucha gente sale a internet con la misma IP.
# En Render todo pasa por Cloudflare: la IP real viene en CF-Connecting-IP (la pone Cloudflare). En X-Forwarded-For
# el último valor es de Cloudflare y los primeros los puede inventar el visitante, así que solo se usa de respaldo.
_envios_ip = {}
def _ip():
    if os.environ.get("RENDER") or os.environ.get("AGROSTAKE_DETRAS_DE_PROXY") == "1":
        for h in ("CF-Connecting-IP", "True-Client-IP"):
            v = (request.headers.get(h) or "").strip()
            if v: return v
        xf = [x.strip() for x in (request.headers.get("X-Forwarded-For") or "").split(",") if x.strip()]
        if xf: return xf[-2] if len(xf) >= 2 else xf[-1]
    return request.remote_addr or "?"
def _limite_ip():
    ahora, ip, tope = time.time(), _ip(), int(os.environ.get("AGROSTAKE_CODIGOS_POR_IP") or 20)
    marcas = [t for t in _envios_ip.get(ip, []) if ahora - t < 3600]
    if len(marcas) >= tope:
        return _error("Se pidieron demasiados códigos desde esta conexión. Espera una hora e intenta de nuevo.",
                      "Too many codes were requested from this connection. Wait an hour and try again.", 429)
    _envios_ip[ip] = marcas + [ahora]
    if len(_envios_ip) > 5000: _envios_ip.clear()          # que la memoria no crezca sin fin
    return None

def _enviar_codigo(via, destino, codigo, motivo):
    if via == "sms":
        # La última línea "@dominio #código" deja que Android (WebOTP) y el iPhone llenen el código solos.
        txt = _t(f"AgroStake: tu código es {codigo}. Vence en 10 minutos. No lo compartas con nadie.",
                 f"AgroStake: your code is {codigo}. It expires in 10 minutes. Do not share it.")
        mensajeria.enviar_sms(destino, f"{txt}\n\n@{_host()} #{codigo}")
        return
    para = {"registro": _t("para crear tu cuenta", "to create your account"), "clave": _t("para recuperar tu contraseña", "to reset your password")}[motivo]
    asunto = _t(f"Tu código de AgroStake: {codigo}", f"Your AgroStake code: {codigo}")
    intro = _t(f"Este es tu código {para}:", f"This is your code {para}:")
    pie = _t("Vence en 10 minutos. Si no lo pediste, ignora este correo.", "It expires in 10 minutes. If you did not request it, ignore this email.")
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px;color:#111">
      <h2 style="margin:0 0 12px">AgroStake</h2><p style="font-size:16px">{intro}</p>
      <p style="font-size:34px;font-weight:700;letter-spacing:8px;background:#f2f2f7;border-radius:12px;padding:14px 0;text-align:center;margin:12px 0">{codigo}</p>
      <p style="color:#555;font-size:14px">{pie}</p></div>"""
    mensajeria.enviar_correo(destino, asunto, f"{intro} {codigo}\n\n{pie}", html)

def _celular_de(texto):
    texto = (texto or "").strip()
    return mensajeria.normalizar_celular(texto) if texto else None

@app.get("/api/acceso/config")
def acceso_config():
    """Qué puede hacer la pantalla de entrada en este servidor (según los servicios configurados)."""
    return jsonify(verificar_correo=bool(mensajeria.proveedor_correo()), sms=bool(mensajeria.proveedor_sms()))

@app.post("/api/registro")
def registro():
    d = request.get_json(force=True)
    nombre, apellido = (d.get("nombre") or "").strip()[:60], (d.get("apellido") or "").strip()[:60]
    correo, clave = (d.get("correo") or "").strip().lower()[:120], d.get("clave") or ""
    if not nombre or not apellido: return _error("Escribe tu nombre y tu apellido.", "Please enter your first and last name.")
    if not CORREO.match(correo): return _error("El correo no parece válido.", "That email does not look valid.")
    if not 8 <= len(clave) <= 128: return _error("La contraseña debe tener al menos 8 caracteres.", "The password must have at least 8 characters.")
    celular = _celular_de(d.get("celular"))
    if (d.get("celular") or "").strip() and not celular:
        return _error("Ese celular no parece válido. Escríbelo así: 300 123 4567.", "That mobile number does not look valid. Write it like 300 123 4567.")
    if not d.get("acepta_datos"): return _error("Debes aceptar el tratamiento de tus datos personales para crear la cuenta.",
                                                "You must accept the processing of your personal data to create an account.")
    if db.consultar("SELECT 1 FROM usuarios WHERE correo=?", (correo,)):
        return _error("Ya existe una cuenta con ese correo. Inicia sesión.", "An account with that email already exists. Please sign in.", 409)
    datos = {"nombre": nombre, "apellido": apellido, "clave_hash": generate_password_hash(clave),
             "acepta_datos_en": datetime.now(timezone.utc).isoformat(), "celular": celular}
    if not mensajeria.proveedor_correo():        # sin servicio de correo configurado: la cuenta se crea de una vez
        return _crear_cuenta(correo, datos)
    lim = _limite_ip()
    if lim: return lim
    codigo, err = codigos.crear(app.config["SECRET_KEY"], correo, "registro", datos)
    if err: return _error(err[0], err[1], 429)
    try: _enviar_codigo("correo", correo, codigo, "registro")
    except Exception as e:
        app.logger.error("No se pudo enviar el código de registro: %s", e)
        return _error("No pudimos enviarte el correo. Revisa la dirección o intenta más tarde.", "We could not send you the email. Check the address or try later.", 502)
    return jsonify(verificar=True, correo=correo, destino=mensajeria.tapar(correo)), 202

def _crear_cuenta(correo, datos):
    if db.consultar("SELECT 1 FROM usuarios WHERE correo=?", (correo,)):
        return _error("Ya existe una cuenta con ese correo. Inicia sesión.", "An account with that email already exists. Please sign in.", 409)
    uid = db.ejecutar("INSERT INTO usuarios(nombre,apellido,correo,clave_hash,acepta_datos_en,celular) VALUES(?,?,?,?,?,?)",
                      (datos["nombre"], datos["apellido"], correo, datos["clave_hash"], datos["acepta_datos_en"], datos.get("celular")))
    session.clear(); session.permanent = True; session["uid"] = uid
    res = {"usuario": _publico(_usuario_actual())}
    if datos.get("celular") and mensajeria.proveedor_sms():          # de una vez se confirma el celular (el código llega por SMS)
        res["verificar_celular"] = _codigo_celular(uid, datos["celular"])
        if res["verificar_celular"]: res["destino_celular"] = mensajeria.tapar(datos["celular"])
    return jsonify(res), 201

def _codigo_celular(uid, celular):
    if _limite_ip(): return False
    codigo, err = codigos.crear(app.config["SECRET_KEY"], celular, "celular", {"uid": uid})
    if err: return False
    try: _enviar_codigo("sms", celular, codigo, "celular"); return True
    except Exception as e:
        app.logger.error("No se pudo enviar el SMS de confirmación: %s", e); return False

@app.post("/api/registro/verificar")
def registro_verificar():
    d = request.get_json(force=True)
    correo = (d.get("correo") or "").strip().lower()
    ok, r = codigos.verificar(app.config["SECRET_KEY"], correo, "registro", d.get("codigo"))
    if not ok: return _error(r[0], r[1])
    return _crear_cuenta(correo, r)

@app.post("/api/registro/reenviar")
def registro_reenviar():
    d = request.get_json(force=True)
    correo = (d.get("correo") or "").strip().lower()
    datos = codigos.pendiente(correo, "registro")
    if datos is None: return _error("Tu registro venció. Vuelve a llenar el formulario.", "Your sign-up expired. Fill in the form again.", 410)
    lim = _limite_ip()
    if lim: return lim
    codigo, err = codigos.crear(app.config["SECRET_KEY"], correo, "registro", datos)
    if err: return _error(err[0], err[1], 429)
    try: _enviar_codigo("correo", correo, codigo, "registro")
    except Exception as e:
        app.logger.error("No se pudo reenviar el código: %s", e)
        return _error("No pudimos enviarte el correo. Intenta más tarde.", "We could not send you the email. Try later.", 502)
    return jsonify(ok=True)

def _destino_clave(d):
    """(via, destino normalizado) para recuperar la contraseña; destino None si no es válido."""
    via = "sms" if d.get("via") == "sms" else "correo"
    if via == "sms": return via, _celular_de(d.get("destino"))
    correo = (d.get("destino") or "").strip().lower()
    return via, correo if CORREO.match(correo) else None

@app.post("/api/clave/olvido")
def clave_olvido():
    d = request.get_json(force=True)
    via, destino = _destino_clave(d)
    if not (mensajeria.proveedor_sms() if via == "sms" else mensajeria.proveedor_correo()):
        return _error("Esa forma de recuperar la cuenta no está activa en este servidor.", "That recovery method is not active on this server.", 503)
    if not destino:
        return _error("Ese celular no parece válido. Escríbelo así: 300 123 4567." if via == "sms" else "El correo no parece válido.",
                      "That mobile number does not look valid." if via == "sms" else "That email does not look valid.")
    lim = _limite_ip()                      # cuenta aunque no haya cuenta con ese dato (misma respuesta para todos)
    if lim: return lim
    f = db.consultar("SELECT id FROM usuarios WHERE celular=? AND celular_ok=1" if via == "sms" else "SELECT id FROM usuarios WHERE correo=?", (destino,))
    if f:           # si no hay cuenta, la respuesta es la misma (así no se puede averiguar quién está registrado)
        codigo, err = codigos.crear(app.config["SECRET_KEY"], destino, "clave", {"uid": f[0]["id"]})
        if err: return _error(err[0], err[1], 429)
        try: _enviar_codigo(via, destino, codigo, "clave")
        except Exception as e:
            app.logger.error("No se pudo enviar el código para recuperar la clave: %s", e)
            return _error("No pudimos enviar el código. Intenta más tarde.", "We could not send the code. Try later.", 502)
    return jsonify(ok=True, destino=mensajeria.tapar(destino))

@app.post("/api/clave/verificar")
def clave_verificar():
    d = request.get_json(force=True)
    via, destino = _destino_clave(d)
    ok, r = codigos.verificar(app.config["SECRET_KEY"], destino or "", "clave", d.get("codigo"), consumir=False)
    return jsonify(ok=True) if ok else _error(r[0], r[1])

@app.post("/api/clave/restablecer")
def clave_restablecer():
    d = request.get_json(force=True)
    clave = d.get("clave") or ""
    if not 8 <= len(clave) <= 128: return _error("La contraseña debe tener al menos 8 caracteres.", "The password must have at least 8 characters.")
    via, destino = _destino_clave(d)
    ok, r = codigos.verificar(app.config["SECRET_KEY"], destino or "", "clave", d.get("codigo"))
    if not ok: return _error(r[0], r[1])
    db.ejecutar("UPDATE usuarios SET clave_hash=? WHERE id=?", (generate_password_hash(clave), r["uid"]))
    session.clear(); session.permanent = True; session["uid"] = r["uid"]
    return jsonify(usuario=_publico(_usuario_actual()))

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

@app.post("/api/celular")
@requiere_login
def celular_guardar():
    """Guarda el celular para recuperar la cuenta y, si hay SMS, le manda un código para confirmarlo."""
    d = request.get_json(force=True)
    cel = _celular_de(d.get("celular"))
    if not cel: return _error("Ese celular no parece válido. Escríbelo así: 300 123 4567.", "That mobile number does not look valid. Write it like 300 123 4567.")
    if cel != g.usuario.get("celular"): db.ejecutar("UPDATE usuarios SET celular=?, celular_ok=0 WHERE id=?", (cel, g.usuario["id"]))
    verificar = bool(mensajeria.proveedor_sms()) and _codigo_celular(g.usuario["id"], cel)
    return jsonify(usuario=_publico(_usuario_actual()), verificar=verificar, destino=mensajeria.tapar(cel))

@app.post("/api/celular/verificar")
@requiere_login
def celular_verificar():
    d = request.get_json(force=True)
    cel = g.usuario.get("celular")
    if not cel: return _error("Primero escribe tu celular.", "Enter your mobile number first.")
    ok, r = codigos.verificar(app.config["SECRET_KEY"], cel, "celular", d.get("codigo"))
    if not ok: return _error(r[0], r[1])
    if r.get("uid") != g.usuario["id"]: return _error("Ese código no es de tu cuenta.", "That code is not for your account.")
    db.ejecutar("UPDATE usuarios SET celular_ok=0 WHERE celular=? AND id<>?", (cel, g.usuario["id"]))   # un celular, una cuenta
    db.ejecutar("UPDATE usuarios SET celular_ok=1 WHERE id=?", (g.usuario["id"],))
    return jsonify(usuario=_publico(_usuario_actual()))

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
    # Respuesta guardada: 7 días si llegaron todas las fuentes del punto, 1 día si faltó alguna (para reintentarla)
    f = db.consultar("SELECT datos, creado_en >= datetime('now','-1 day') AS reciente FROM externos WHERE clave=? AND creado_en >= datetime('now','-7 days')", (clave,))
    idioma = "en" if motor._en() else "es"
    if f and (json.loads(f[0]["datos"]).get("completo") or f[0]["reciente"]):
        res = json.loads(f[0]["datos"])
        return jsonify(dict(res, cache=True, **orquestador.completar(res, idioma)))
    res = orquestador.perfil_lote(lat, lon, local=orquestador.datos_guardados(lat, lon))
    del_punto = [k for k in ("nasa_power", "modis", "elevacion", "soilgrids") if res["fuentes"].get(k) == "ok"]
    res["completo"] = len(del_punto) == 4
    if del_punto:
        db.ejecutar("INSERT OR REPLACE INTO externos(clave, datos, creado_en) VALUES(?,?,datetime('now'))", (clave, json.dumps(res)))
    return jsonify(dict(res, cache=False, **orquestador.completar(res, idioma)))

# ------------------------------------------------------------------ Catálogo y motor
_PAGINA = {}
@app.route("/")
def index():
    """La página (unos 220 KB) va comprimida si el navegador lo acepta: carga mucho más rápido con señal débil."""
    ruta = os.path.join(app.root_path, "templates", "index.html")
    m = os.path.getmtime(ruta)
    if _PAGINA.get("m") != m:
        crudo = open(ruta, "rb").read()
        _PAGINA.update(m=m, crudo=crudo, gz=gzip.compress(crudo, 6), etag=hashlib.md5(crudo).hexdigest())
    gz = "gzip" in request.headers.get("Accept-Encoding", "")
    r = app.response_class(_PAGINA["gz"] if gz else _PAGINA["crudo"], mimetype="text/html")
    r.headers.update({"X-App": "AgroStake", "Cache-Control": "no-cache", "Vary": "Accept-Encoding"})
    if gz: r.headers["Content-Encoding"] = "gzip"
    r.set_etag(_PAGINA["etag"] + ("-gz" if gz else ""))
    return r.make_conditional(request)

@app.get("/salud")
def salud():
    """Para revisar que el servidor está vivo (Render la usa como chequeo y sirve para mantenerlo despierto)."""
    return "ok", 200, {"Content-Type": "text/plain", "Cache-Control": "no-store"}

@app.get("/sw.js")
def service_worker():
    """Uso sin señal (ver static/sw.js). Se sirve desde la raíz para que pueda guardar toda la app."""
    r = send_from_directory("static", "sw.js", mimetype="application/javascript")
    r.headers.update({"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
    return r

@app.get("/manifest.webmanifest")
def manifiesto():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")

# ------------------------------------------------------------------ Relleno histórico del suelo (sin estaca)
@app.get("/api/suelo_historico")
def suelo_historico():
    zid = request.args.get("zona", "")
    if zid not in PILOTO["zonas"] and not (motor.es_punto(zid) and _zona_valida(zid)): return _error("Zona no válida.", "Invalid area.")
    try: mes = int(request.args.get("mes") or datetime.now().month)
    except ValueError: mes = 0
    if not 1 <= mes <= 12: return _error("Mes no válido.", "Invalid month.")
    return jsonify(historico.suelo(zid, mes))

# ------------------------------------------------------------------ Datos de referencia del piloto (sin estaca)
@app.get("/api/referencia")
def referencia():
    """Suelo publicado para la zona y estaciones del IDEAM más cercanas al punto. No usa internet:
    las estaciones salen de la copia descargada o de la copia regional incluida (ver services/ideam.py)."""
    zid = request.args.get("zona", "")
    if motor.es_punto(zid) and _zona_valida(zid): zid = motor.zona(zid)["cercana"]
    z = PILOTO["zonas"].get(zid)
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError
    except (KeyError, ValueError):
        return _error("Coordenadas no válidas.", "Invalid coordinates.")
    clima, lluvia = ideam.cercanas(lat, lon, n=2, tipo="clima"), ideam.cercanas(lat, lon, n=3, tipo="lluvia")
    vistos, est = set(), []
    for e in clima["estaciones"] + lluvia["estaciones"]:
        if e["codigo"] not in vistos: vistos.add(e["codigo"]); est.append(e)
    return jsonify({"zona": zid, "suelo": z, "fuentes": {k: PILOTO["fuentes"][k] for k in (z or {}).get("fuentes", [])},
                    "interpretacion": PILOTO["interpretacion"], "nota": PILOTO["nota"],
                    "ideam": {"estaciones": sorted(est, key=lambda e: e["distancia_km"])[:4], "fuente": clima["fuente"],
                              "fecha_copia": clima["fecha_copia"], "origen": clima["origen"], "datos": clima["datos"]}})

@app.get("/api/estado_datos")
def estado_datos():
    """Avance de la descarga automática y cuántas zonas ya tienen datos reales de la NASA."""
    return jsonify(sincronizar.estado() | {"cuentas": db.modo_cuentas()})   # "postgres": las cuentas no se pierden

@app.post("/api/punto")
def punto():
    """Punto libre del mapa: descarga el clima de la NASA para esa latitud y longitud (10 años) y lo guarda.
    Si no hay internet, responde con la zona igual y la app usa el clima de la zona más cercana (lo dice)."""
    d = request.get_json(force=True) or {}
    try:
        lat, lon = float(d["lat"]), float(d["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError
    except (KeyError, TypeError, ValueError):
        return _error("Coordenadas no válidas.", "Invalid coordinates.")
    zid = motor.id_punto(lat, lon)
    z = dict(motor.zona(zid)); z["riego"] = bool(z["riego"])
    # La descarga va en un hilo aparte: si tarda más de unos segundos, la app sigue con el clima de la zona más
    # cercana y avisa cuando llegue (antes esta petición podía tardar minutos y frenar todo el servidor).
    listo = sincronizar.descargar_punto(zid, *motor.punto_coords(zid), espera=3)
    cl, real = motor.clima_de(zid)
    if not listo: return jsonify(zona=z, clima_real=False, pendiente=True, aviso=None)
    return jsonify(zona=z, clima_real=real, pendiente=False,
                   aviso=None if real else _t(f"No se pudo descargar el clima de la NASA para este punto; mientras tanto se usa el de {z['cercana_nombre']} (a {z['km_cercana']} km).",
                                              f"NASA weather for this point could not be downloaded; meanwhile the data from {z['cercana_nombre']} ({z['km_cercana']} km away) is used."))

@app.get("/api/zonas")
def zonas():
    out = []
    for z in db.consultar("SELECT * FROM zonas"):
        z["clima"], z["clima_verificado"] = motor.clima_de(z["id"])
        z["riego"] = bool(z["riego"])
        out.append(z)
    return jsonify(out)

@app.get("/api/municipios")
def lista_municipios():
    """Los 194 municipios del Caribe para el mapa y el buscador (cambia solo cuando se actualiza el archivo)."""
    r = jsonify(municipios=municipios.lista(), fuente=municipios.fuente())
    r.headers["Cache-Control"] = "public, max-age=86400"
    return r

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
    if not _zona_valida(request.args.get("zona_id", "")): return _error("Zona no válida.", "Invalid area.")
    return jsonify(motor.diario(request.args["zona_id"], int(request.args["mes"]), int(request.args.get("anio", date.today().year))))

@app.post("/api/panel")
def panel():
    d = request.get_json(force=True)
    if not _zona_valida(d.get("zona_id", "")): return _error("Zona no válida.", "Invalid area.")
    sincronizar.priorizar(d["zona_id"])              # si se están descargando los datos de la NASA, esta zona va primero
    return jsonify(motor.panel(d["zona_id"], _suelo(d["suelo"]), d.get("textura"), d.get("riego")))

@app.post("/api/recomendar")
def recomendar():
    d = request.get_json(force=True)
    if not _zona_valida(d.get("zona_id", "")): return _error("Zona no válida.", "Invalid area.")
    return jsonify(motor.recomendar(d["zona_id"], _suelo(d["suelo"]), d.get("prioridades"), _ultimos(d), d.get("riego"), d.get("textura")))

@app.post("/api/simular")
def simular():
    d = request.get_json(force=True)
    if not _zona_valida(d.get("zona_id", "")): return _error("Zona no válida.", "Invalid area.")
    return jsonify(motor.simular(d["zona_id"], _suelo(d["suelo"]), d.get("textura"), d.get("riego"), d["secuencia"], _ultimos(d),
                                 max(.1, float(d.get("ha", 5))), max(1, min(10, int(d.get("anios", 5))))))

if __name__ == "__main__":
    sincronizar.iniciar()
    print("AgroStake: abre http://127.0.0.1:%s  (los datos de la NASA se descargan solos en segundo plano)" % os.environ.get("PORT", 5000))
    # En un servidor (Render pone PORT) escucha en todas las interfaces; en tu computador, solo en el tuyo.
    host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host=host, port=int(os.environ.get("PORT", 5000)), threaded=True)
