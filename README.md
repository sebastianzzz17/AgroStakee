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

### Cuentas con celular (versión 18)

- **Crear cuenta:** nombre, apellido, número de celular y contraseña (y la autorización de datos de la Ley 1581).
  Si hay SMS configurado (Twilio, abajo), llega un código por mensaje de texto y la cuenta se crea al escribirlo;
  si no, la cuenta se crea de una vez.
- **Iniciar sesión:** celular y contraseña. Las cuentas viejas creadas con correo (versión 16) siguen entrando: se
  escribe el correo en el mismo campo.
- **¿Olvidaste tu contraseña?:** se escribe el celular, llega un código por SMS (en Android se pone solo), y luego
  la contraseña nueva. Las cuentas viejas con correo tienen el enlace "Mi cuenta es con correo".
- En la base, la columna `correo` es obligatoria y única, así que las cuentas de celular guardan ahí un relleno fijo
  por número (`cel573001234567@agrostake.invalid`; el dominio `.invalid` está reservado y nunca recibe correo).
  Eso también impide dos cuentas con el mismo celular. La app nunca muestra ese relleno.
- Las cuentas "solo con el nombre" de la versión 17, si alguien alcanzó a crear alguna, siguen funcionando mientras
  no se cierre la sesión en ese equipo; ya no se pueden crear nuevas. La sesión dura un año desde la última visita.

### Rotaciones guardadas (versión 18)

En cada rotación hay un botón "Guardar". Las guardadas quedan en la cuenta (tabla `rotaciones`, en Postgres si
está `DATABASE_URL`) y aparecen en Rotación, en "Mis rotaciones guardadas", cada vez que se inicia sesión. Se
guarda el plan tal como estaba ese día (con su plan de acción) y se puede ver o borrar. Antes de generar rotaciones
nuevas, la tarjeta "Mejor rotación" de Resumen muestra la última guardada. Máximo 30 por cuenta.

### Códigos por mensaje de texto y por correo (versiones 16 y 18)

Los códigos para crear la cuenta y para recuperar la contraseña van por mensaje de texto (SMS) al celular. El
correo solo se usa para recuperar las cuentas viejas creadas con correo. **Mientras no pongas estas variables:** la
cuenta se crea sin código y la pantalla dice que la recuperación no está activa.

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

### Municipios de Colombia y la EVA (versiones 16 y 17)

El mapa muestra los 1.101 municipios de Colombia que tienen datos en la EVA, con un buscador y el botón "Usar mi
ubicación". Para cada uno, la app sabe qué se siembra, en qué semestre y cuánto se cosecha por hectárea
(Evaluaciones Agropecuarias Municipales, EVA 2019-2024). El archivo `data/municipios.json` pesa 434 KB (85 KB
comprimido) y se carga una vez. Lo arma `herramientas/preparar_municipios.py` en tu computador (necesita `pandas`
y `openpyxl`; el servidor no los usa):

    python herramientas/preparar_municipios.py --eva 20250617_BaseAgricola20192024.xlsx --divipola DIVIPOLA.csv --sivel datos-geo-col.sql

- **En las rotaciones** la EVA hace estas cosas:
  1. Un cultivo solo se recomienda si se siembra en el propio municipio con al menos 10 ha al año y el 1,5 % del
     área del cultivo más sembrado allí: si no, es señal de que el clima, el suelo o el mercado no le sirven. Por eso
     la app no recomienda ñame ni arroz en Tunja, ni guandul en Sahagún.
  2. Donde hay datos de la EVA no se recomienda abono verde (casi no se siembra en las fincas). Si en una temporada
     de lluvias no encaja ningún cultivo de la zona, la rotación deja el lote descansando con rastrojo, penalizado.
  3. Indicador "Se siembra en tu zona" (pesa el triple que los demás): compara cada siembra con lo que se siembra
     en el municipio en ese mismo semestre. Primeras lluvias ≈ semestre A; segundas lluvias ≈ semestre B.
  4. La mitad del puntaje de mercado sale de cuánto se siembra cada cultivo en el municipio.
  5. En Proyección, "Mejor cultivo a largo plazo" escoge el cultivo de la rotación que más se siembra en el
     municipio (con un empujón a los que mejoran el suelo) y da su cosecha promedio por hectárea.
- **Fuera del Caribe** la app avisa que es una guía en prueba: se armó para la tierra caliente del Caribe.
  El caupí solo se recomienda donde hay fríjol registrado en el Caribe a menos de 100 km (en el resto del país, el
  "Frijol" de la EVA puede ser fríjol común). La braquiaria no se recomienda con menos de 19 °C de temperatura
  media (Tropical Forages: crece mejor por encima de 19 °C).
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
| Ubicación del lote con el GPS del equipo | El navegador (pide permiso; solo con https o en tu computador) | No |

Las que piden cuenta se activan solas si están las variables de entorno (ver `app.py` y `services/orquestador.py`).
Las credenciales nunca van en el código.

Más detalle: `CAMBIOS.md`, `docs/PILOTO.md` y `docs/ESTACA.md`.
