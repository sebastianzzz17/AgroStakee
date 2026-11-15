# AgroStake

Rotación de cultivos para el Caribe colombiano con datos de la NASA y de una estaca de sensores (ESP32-S3).
NASA Space Apps Challenge 2026, Barranquilla.

## Cómo correrla (para el jurado)

```
pip install -r requirements.txt
python app.py
```

Abre http://127.0.0.1:5000 en el navegador. No hace falta ningún comando más ni ninguna cuenta:
**al arrancar, la app descarga sola, en segundo plano, los datos reales de la NASA** de las 8 zonas del piloto
(clima de 20 años, humedad y temperatura del suelo de NASA POWER, verdor MODIS y pendiente SRTM) y los últimos
meses. Mientras descarga, la app muestra el avance; si no hay internet, sigue con los datos guardados y lo dice.

- Funciona en celular: abre la misma dirección desde el teléfono (con `HOST=0.0.0.0`) o instálala como app.
- Sin señal: la app guarda las últimas respuestas y las muestra con un aviso. El modo sin señal completo
  (la app abre aunque no haya conexión) necesita https o localhost, que es una regla de los navegadores.

## Publicarla en Render

- **Comando de inicio** (Settings → Start Command): `gunicorn -c gunicorn.conf.py app:app`
  (un proceso con 8 hilos: una consulta lenta ya no frena a las demás). Con `render.yaml` se configura solo.
- **Plan gratis** (según la documentación de Render): 0,1 de CPU y 512 MB; el servicio se duerme tras 15 minutos
  sin visitas y tarda cerca de un minuto en despertar; y **cada vez que se duerme, reinicia o se vuelve a
  desplegar, se borra el disco**: las cuentas creadas, las lecturas de estacas y los datos descargados.
  La app vuelve a descargar los datos de la NASA sola, pero las cuentas no vuelven.
- **Para que arranque con datos reales:** corre la app una vez en tu computador con internet; al terminar la
  descarga se crea `data/clima_real.json`. Súbelo al repositorio junto con el código y Render arrancará ya con
  los datos de la NASA de las 8 zonas (y solo bajará lo de los últimos meses).
- `GET /salud` responde `ok`: sirve como chequeo de Render y para un "ping" que lo mantenga despierto.

## Fuentes de datos

| Dato | Fuente | ¿Pide cuenta? |
|---|---|---|
| Clima, humedad y temperatura del suelo | NASA POWER | No |
| Verdor de las plantas (NDVI) | NASA MODIS / VIIRS por la API de ORNL DAAC | No |
| Pendiente | SRTM (Open-Elevation) o Copernicus DEM (Open-Meteo) | No |
| Capas del mapa | NASA GIBS (VIIRS, SMAP, MODIS, GPM IMERG) | No |
| Suelo del piloto | Estudios publicados (ver `docs/PILOTO.md`) | No |
| Suelo de cualquier punto | ISRIC SoilGrids (su API está pausada por ISRIC; se intenta igual) | No |
| Estaciones | Catálogo del IDEAM (datos.gov.co), con copia incluida | No |
| Temperatura de superficie a 70 m y humedad SMAP L4 | NASA AppEEARS | Sí (Earthdata) |
| Pendiente y NDVI de Landsat, SoilGrids en la nube | Google Earth Engine | Sí |
| Humedad y temperatura del suelo ERA5-Land | Copernicus CDS | Sí |
| Características de cultivos | USDA PLANTS | No |

Las que piden cuenta se activan solas si están las variables de entorno (ver `app.py` y `services/orquestador.py`).
Las credenciales nunca van en el código.

Más detalle: `CAMBIOS.md`, `docs/PILOTO.md` y `docs/ESTACA.md`.
