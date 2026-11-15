"""receptor_agrostake.py
Recibe en el servidor Python los datos locales que envía el ESP32 de AgroStake.

Instalación:  py -m pip install paho-mqtt   (y agregar paho-mqtt a requirements.txt)

Uso:
    from receptor_agrostake import iniciar_receptor, obtener_datos
    iniciar_receptor()      # una sola vez, al arrancar el servidor
    obtener_datos()         # devuelve lo último recibido, en cualquier momento
"""
import json
import threading
import time
import uuid

import paho.mqtt.client as mqtt

BROKER = "broker.emqx.io"
PORT = 1883
TOPIC_LOCAL = "miproyecto-8472/agrostake/local"
SIN_DATOS_SEG = 5          # si pasan más de 5 s sin mensajes, se avisa

_ultimo = {}               # último mensaje de cada grupo (hoy solo "suelo")
_ultima_llegada = 0.0
_lock = threading.Lock()


def _al_conectar(client, userdata, flags, reason_code, properties=None):
    client.subscribe(TOPIC_LOCAL)


def _al_recibir(client, userdata, msg):
    global _ultima_llegada
    try:
        datos = json.loads(msg.payload.decode("utf-8"))
    except ValueError:
        return
    if not isinstance(datos, dict) or not datos.get("grupo"):
        return
    datos["recibido"] = time.time()
    with _lock:
        _ultimo[datos["grupo"]] = datos
        _ultima_llegada = time.time()


def iniciar_receptor():
    """Conecta al broker en un hilo aparte. Se reconecta solo si se cae."""
    cliente = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="agrostake-web-" + uuid.uuid4().hex[:8],
    )
    cliente.on_connect = _al_conectar
    cliente.on_message = _al_recibir
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    cliente.connect_async(BROKER, PORT, keepalive=60)
    cliente.loop_start()
    return cliente


def obtener_datos():
    """Devuelve {"grupos": {...}, "sin_datos": bool, "segundos_desde_ultimo": float|None}."""
    with _lock:
        grupos = {g: dict(d) for g, d in _ultimo.items()}
        llegada = _ultima_llegada
    segundos = (time.time() - llegada) if llegada else None
    return {
        "grupos": grupos,
        "sin_datos": segundos is None or segundos > SIN_DATOS_SEG,
        "segundos_desde_ultimo": segundos,
    }
