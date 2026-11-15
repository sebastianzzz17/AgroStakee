"""Códigos de verificación de 6 dígitos (crear cuenta, recuperar la contraseña, confirmar el celular).

- Se guarda solo un HMAC del código (con la clave secreta del servidor), nunca el código.
- Vence a los 10 minutos y admite 5 intentos; después hay que pedir otro.
- Entre un envío y otro hay que esperar 60 s, y como máximo van 5 códigos por hora a un mismo destino."""
import hashlib, hmac, json, secrets, time
import db

VIGENCIA = 10 * 60
INTENTOS = 5
ESPERA = 60
POR_HORA = 5

def _hmac(secreto, destino, proposito, codigo):
    return hmac.new(secreto.encode(), f"{proposito}|{destino}|{codigo}".encode(), hashlib.sha256).hexdigest()

def _fila(destino, proposito):
    f = db.consultar("SELECT * FROM codigos WHERE destino=? AND proposito=?", (destino, proposito))
    return f[0] if f else None

def crear(secreto, destino, proposito, datos=None, ahora=None):
    """Devuelve (codigo, None) o (None, (mensaje_es, mensaje_en, segundos_de_espera))."""
    ahora = ahora or time.time()
    f = _fila(destino, proposito)
    ventana, enviados = (f["ventana"], f["enviados"]) if f else (ahora, 0)
    if ahora - ventana > 3600: ventana, enviados = ahora, 0
    if f and ahora - f["enviado_en"] < ESPERA:
        s = int(ESPERA - (ahora - f["enviado_en"])) + 1
        return None, (f"Espera {s} segundos para pedir otro código.", f"Wait {s} seconds to request another code.", s)
    if enviados >= POR_HORA:
        return None, ("Pediste demasiados códigos. Espera una hora e intenta de nuevo.", "Too many codes requested. Wait an hour and try again.", 3600)
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    db.ejecutar("DELETE FROM codigos WHERE destino=? AND proposito=?", (destino, proposito))
    db.ejecutar("INSERT INTO codigos(destino,proposito,codigo_hash,expira,intentos,enviado_en,enviados,ventana,datos) VALUES(?,?,?,?,?,?,?,?,?)",
                (destino, proposito, _hmac(secreto, destino, proposito, codigo), ahora + VIGENCIA, 0, ahora, enviados + 1, ventana,
                 json.dumps(datos) if datos is not None else None))
    return codigo, None

def pendiente(destino, proposito):
    """Datos guardados con el código vigente (por ejemplo, el registro que espera confirmación)."""
    f = _fila(destino, proposito)                                   # sirve para reenviar hasta un día después
    if not f or time.time() > f["expira"] + 86400: return None
    return json.loads(f["datos"]) if f["datos"] else {}

def verificar(secreto, destino, proposito, codigo, consumir=True):
    """Devuelve (True, datos) o (False, (mensaje_es, mensaje_en))."""
    f = _fila(destino, proposito)
    if not f: return False, ("Ese código ya no sirve. Pide uno nuevo.", "That code is no longer valid. Request a new one.")
    if time.time() > f["expira"]: return False, ("El código venció. Pide uno nuevo.", "The code expired. Request a new one.")
    if f["intentos"] >= INTENTOS: return False, ("Demasiados intentos con ese código. Pide uno nuevo.", "Too many attempts with that code. Request a new one.")
    codigo = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if not hmac.compare_digest(f["codigo_hash"], _hmac(secreto, destino, proposito, codigo)):
        db.ejecutar("UPDATE codigos SET intentos=intentos+1 WHERE destino=? AND proposito=?", (destino, proposito))
        quedan = INTENTOS - f["intentos"] - 1
        return False, (f"Código incorrecto. Te quedan {quedan} intentos." if quedan else "Código incorrecto. Pide uno nuevo.",
                       f"Wrong code. {quedan} attempts left." if quedan else "Wrong code. Request a new one.")
    if consumir: db.ejecutar("DELETE FROM codigos WHERE destino=? AND proposito=?", (destino, proposito))
    return True, json.loads(f["datos"]) if f["datos"] else {}
