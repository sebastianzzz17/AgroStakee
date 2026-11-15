"""Envío de correos y SMS (códigos de verificación).

Render gratis bloquea los puertos SMTP (25, 465 y 587), así que el correo sale por una API web (HTTPS):
  - Brevo:  BREVO_API_KEY  y CORREO_REMITENTE (el correo que verificaste en Brevo como remitente)
  - Resend: RESEND_API_KEY y CORREO_REMITENTE (Resend exige un dominio propio verificado)
  - SMTP, solo en tu computador o en un plan pago: SMTP_HOST, SMTP_PUERTO, SMTP_USUARIO, SMTP_CLAVE y CORREO_REMITENTE
SMS (cada mensaje tiene costo):
  - Twilio: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN y TWILIO_FROM (número de Twilio) o TWILIO_MESSAGING_SID
Nombre del remitente: CORREO_NOMBRE (por defecto "AgroStake").
Para pruebas: AGROSTAKE_MENSAJES_CONSOLA=1 escribe los mensajes en la consola del servidor en vez de enviarlos.
Las claves van solo en variables de entorno, nunca en el código."""
import os, re, smtplib, ssl
from email.message import EmailMessage
import requests

ULTIMOS = []                       # en modo consola: los últimos mensajes (para las pruebas automáticas)

def _env(k): return (os.environ.get(k) or "").strip()
def _consola(): return _env("AGROSTAKE_MENSAJES_CONSOLA") == "1"

def proveedor_correo():
    if _env("BREVO_API_KEY") and _env("CORREO_REMITENTE"): return "brevo"
    if _env("RESEND_API_KEY") and _env("CORREO_REMITENTE"): return "resend"
    if _env("SMTP_HOST") and _env("CORREO_REMITENTE"): return "smtp"
    return "consola" if _consola() else None

def proveedor_sms():
    if _env("TWILIO_ACCOUNT_SID") and _env("TWILIO_AUTH_TOKEN") and (_env("TWILIO_FROM") or _env("TWILIO_MESSAGING_SID")): return "twilio"
    return "consola" if _consola() else None

def _consola_guardar(tipo, destino, asunto, texto):
    ULTIMOS.append({"tipo": tipo, "destino": destino, "asunto": asunto, "texto": texto})
    del ULTIMOS[:-50]
    print(f"[mensaje de prueba · {tipo} → {destino}] {asunto or ''}\n{texto}\n", flush=True)

def enviar_correo(destino, asunto, texto, html):
    p, nombre, remitente = proveedor_correo(), _env("CORREO_NOMBRE") or "AgroStake", _env("CORREO_REMITENTE")
    if p == "brevo":
        r = requests.post("https://api.brevo.com/v3/smtp/email", timeout=20,
                          headers={"api-key": _env("BREVO_API_KEY"), "accept": "application/json", "content-type": "application/json"},
                          json={"sender": {"name": nombre, "email": remitente}, "to": [{"email": destino}],
                                "subject": asunto, "htmlContent": html, "textContent": texto})
        if r.status_code >= 300: raise RuntimeError(f"Brevo respondió {r.status_code}: {r.text[:200]}")
    elif p == "resend":
        r = requests.post("https://api.resend.com/emails", timeout=20, headers={"Authorization": f"Bearer {_env('RESEND_API_KEY')}"},
                          json={"from": f"{nombre} <{remitente}>", "to": [destino], "subject": asunto, "html": html, "text": texto})
        if r.status_code >= 300: raise RuntimeError(f"Resend respondió {r.status_code}: {r.text[:200]}")
    elif p == "smtp":
        m = EmailMessage(); m["From"] = f"{nombre} <{remitente}>"; m["To"] = destino; m["Subject"] = asunto
        m.set_content(texto); m.add_alternative(html, subtype="html")
        puerto = int(_env("SMTP_PUERTO") or 587)
        if puerto == 465:
            with smtplib.SMTP_SSL(_env("SMTP_HOST"), puerto, context=ssl.create_default_context(), timeout=20) as s:
                s.login(_env("SMTP_USUARIO"), _env("SMTP_CLAVE")); s.send_message(m)
        else:
            with smtplib.SMTP(_env("SMTP_HOST"), puerto, timeout=20) as s:
                s.starttls(context=ssl.create_default_context()); s.login(_env("SMTP_USUARIO"), _env("SMTP_CLAVE")); s.send_message(m)
    elif p == "consola":
        _consola_guardar("correo", destino, asunto, texto)
    else:
        raise RuntimeError("No hay servicio de correo configurado")

def enviar_sms(numero, texto):
    p = proveedor_sms()
    if p == "twilio":
        sid = _env("TWILIO_ACCOUNT_SID")
        datos = {"To": numero, "Body": texto}
        if _env("TWILIO_MESSAGING_SID"): datos["MessagingServiceSid"] = _env("TWILIO_MESSAGING_SID")
        else: datos["From"] = _env("TWILIO_FROM")
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=datos,
                          auth=(sid, _env("TWILIO_AUTH_TOKEN")), timeout=20)
        if r.status_code >= 300: raise RuntimeError(f"Twilio respondió {r.status_code}: {r.text[:200]}")
    elif p == "consola":
        _consola_guardar("sms", numero, None, texto)
    else:
        raise RuntimeError("No hay servicio de SMS configurado")

def normalizar_celular(s):
    """Celular colombiano en formato internacional (+57 y 10 dígitos que empiezan por 3). Acepta espacios, guiones,
    paréntesis y el 57 adelante. Un número de otro país se acepta si viene con + y de 8 a 15 dígitos."""
    s = (s or "").strip()
    if not s: return None
    mas = s.startswith("+")
    d = re.sub(r"\D", "", s)
    if not mas and len(d) == 10 and d.startswith("3"): return "+57" + d
    if d.startswith("57") and len(d) == 12 and d[2] == "3": return "+" + d
    if mas and 8 <= len(d) <= 15 and not d.startswith("57"): return "+" + d
    return None

def tapar(destino):
    """Para mostrar a dónde se envió el código sin revelarlo entero: j***@gmail.com · +57 300 *** **67."""
    if "@" in destino:
        u, d = destino.split("@", 1)
        return f"{u[:1]}***@{d}"
    if destino.startswith("+57") and len(destino) == 13: return f"+57 {destino[3:6]} *** **{destino[-2:]}"
    return destino[:4] + " *** **" + destino[-2:]
