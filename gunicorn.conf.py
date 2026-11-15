"""Configuración de gunicorn para Render (o cualquier servidor).   Uso:  gunicorn -c gunicorn.conf.py app:app

Por qué así:
  - UN solo proceso: la descarga automática de datos de la NASA y su estado viven en la memoria de ese proceso,
    y SQLite trabaja mejor con un solo escritor. Con varios procesos se descargaría todo varias veces.
  - VARIOS hilos (gthread): una petición lenta (un punto libre del mapa, la consulta de suelo de "Consultar mi
    punto") ya no frena a las demás. Con la configuración por defecto de gunicorn (1 hilo, 30 s) una de esas
    peticiones dejaba la app en blanco y gunicorn reiniciaba el proceso (WORKER TIMEOUT).
  - timeout 120: con hilos, el límite vigila que el proceso siga vivo, no cada petición.
Render agrega por su cuenta --preload y --bind=0.0.0.0:10000 (variable GUNICORN_CMD_ARGS); no estorban."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("AGROSTAKE_HILOS_WEB", "8"))
timeout = 120
graceful_timeout = 20
keepalive = 5
accesslog = "-"
