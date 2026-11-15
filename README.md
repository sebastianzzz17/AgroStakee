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

### Que las cuentas no se pierdan

Crea una base Postgres y pon su dirección en la variable **`DATABASE_URL`** (Render → tu servicio → Environment).
Con eso, las cuentas, las estacas y sus lecturas se guardan allá y sobreviven a los reinicios; el clima y el catálogo
se siguen guardando en el disco del servidor porque la app los vuelve a crear sola. Sin `DATABASE_URL` todo funciona
igual que antes, con SQLite.

- **Neon** (neon.tech) o **Supabase**: tienen plan gratis permanente. Copia la "connection string" que empieza por
  `postgresql://` (con `sslmode=require` al final).
- **Postgres de Render**: se conecta en dos clics ("Internal Database URL"), pero el gratis vence a los 30 días.

Para comprobarlo: `/api/estado_datos` debe decir `"cuentas": "postgres"`.

### Códigos por correo y por mensaje de texto (versión 16)

Al crear la cuenta se manda un código de 6 números al correo, y la contraseña se recupera con un código por correo
o por mensaje de texto (SMS) al celular que la persona confirmó. **Mientras no pongas estas variables, todo sigue
como antes:** la cuenta se crea sin código y la pantalla dice que la recuperación no está activa.

Render gratis **bloquea el correo por SMTP** (puertos 25, 465 y 587), por eso el correo sale por una API web:

| Para | Variables (Render → tu servicio → Environment) | Notas |
|---|---|---|
| Correo con **Brevo** (recomendado) | `BREVO_API_KEY`, `CORREO_REMITENTE` | Plan gratis de 300 correos al día. En Brevo, verifica el correo remitente ("Senders") y crea la clave en "SMTP & API" → "API Keys". |
| Correo con **Resend** | `RESEND_API_KEY`, `CORREO_REMITENTE` | Exige un dominio propio verificado. |
| Correo por SMTP (solo en tu computador o en un plan pago) | `SMTP_HOST`, `SMTP_PUERTO`, `SMTP_USUARIO`, `SMTP_CLAVE`, `CORREO_REMITENTE` | |
| SMS con **Twilio** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` y `TWILIO_FROM` (o `TWILIO_MESSAGING_SID`) | Cada SMS cuesta. Con la cuenta de prueba de Twilio solo llegan a números que verifiques en Twilio. |
| Nombre que ve quien recibe | `CORREO_NOMBRE` | Por defecto "AgroStake". |

- **El código se pone solo:** el SMS termina en `@tu-dominio #123456`. Chrome en Android lo lee apenas llega y lo
  escribe (WebOTP); en el iPhone el teclado lo ofrece encima. En los demás casos se copia del mensaje.
- **Seguridad:** se guarda solo un HMAC del código (nunca el código), vence a los 10 minutos, admite 5 intentos,
  hay que esperar 60 s para pedir otro, máximo 5 por hora a un mismo correo o celular y 20 por hora desde una
  misma conexión (`AGROSTAKE_CODIGOS_POR_IP`; no es más bajo porque en una universidad mucha gente comparte la
  misma IP). En Render la IP del visitante se toma de `CF-Connecting-IP`, que pone Cloudflare. "¿Olvidaste tu contraseña?" responde igual exista o no la cuenta.
- Para probar sin enviar nada: `AGROSTAKE_MENSAJES_CONSOLA=1` escribe los mensajes en la consola del servidor.

### Municipios del Caribe (versión 16)

El mapa muestra los 194 municipios de Atlántico, Bolívar, Cesar, Córdoba, La Guajira, Magdalena y Sucre, con un
buscador. Para cada uno, la app sabe qué se siembra y cuánto se cosecha por hectárea (Evaluaciones Agropecuarias
Municipales, EVA 2019-2024). El archivo `data/municipios_caribe.json` (78 KB) lo arma
`herramientas/preparar_municipios.py` en tu computador (necesita `pandas` y `openpyxl`; el servidor no los usa):

    python herramientas/preparar_municipios.py --eva 20250617_BaseAgricola20192024.xlsx --divipola DIVIPOLA.csv --sivel datos-geo-col.sql

- **Coordenadas:** las de esta versión son las de SIVeL (dominio público, armadas con DIVIPOLA 2013, Divipolador
  y OpenStreetMap). Tienen errores: la de Mompox queda a 16,9 km. Las 8 zonas piloto conservan las suyas.
  Cuando tengas el CSV oficial del DANE "DIVIPOLA - Códigos municipios" (datos.gov.co), pásalo con `--divipola`:
  se usa ese y se imprime cuánto difiere de SIVeL. No pude abrir datos.gov.co desde aquí, así que el lector busca
  las columnas por nombre (código, latitud, longitud) y avisa si no las encuentra.

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
| Pasto (braquiaria) | Tropical Forages y ficha de semilla (ver `docs/PILOTO.md`) | No |
| Qué se siembra y cuánto se cosecha en cada municipio | Evaluaciones Agropecuarias Municipales (EVA) 2019-2024, UPRA y MinAgricultura | No (archivo incluido) |
| Ubicación de las cabeceras municipales | SIVeL (provisional); DIVIPOLA del DANE cuando se agregue | No |

Las que piden cuenta se activan solas si están las variables de entorno (ver `app.py` y `services/orquestador.py`).
Las credenciales nunca van en el código.

Más detalle: `CAMBIOS.md`, `docs/PILOTO.md` y `docs/ESTACA.md`.
