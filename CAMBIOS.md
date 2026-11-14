# Cambios

## Versión 4 (cuentas, inglés, asistente por voz y estacas)

### Cómo correrla
```
pip install -r requirements.txt
python app.py            # abre http://127.0.0.1:5000
```
La primera vez se crea `rotacion.db` (base de datos) y `.secret_key` (llave de las sesiones). **Ninguno de los dos se debe subir a GitHub ni compartir.** Variables de entorno opcionales:

| Variable | Para qué |
|---|---|
| `ROTACION_SECRET` | Llave de sesiones en el servidor (si no, se usa `.secret_key`) |
| `ROTACION_HTTPS=1` | Cookie de sesión solo por HTTPS (actívala en producción) |
| `ROTACION_DB` | Ruta de la base de datos |
| `HOST`, `PORT`, `FLASK_DEBUG` | Servidor (por defecto 127.0.0.1:5000, sin modo depuración) |
| `DATOS_ABIERTOS_CLAVES` | Claves para la API de datos abiertos (encabezado `X-Api-Key`) |
| `EARTHDATA_USER`, `EARTHDATA_PASS` | AppEEARS (ECOSTRESS y SMAP) |
| `GEE_PROJECT` | Proyecto de Google Earth Engine (requiere `earthengine-api` y autenticarse) |
| `SOCRATA_DATASET`, `SOCRATA_COL_CIUDAD`, `SOCRATA_TOKEN` | Precios de datos.gov.co |

### Interfaz
- **Inicio de sesión y registro** (nombre, apellido, correo y contraseña de mínimo 8 caracteres) con la autorización de tratamiento de datos de la Ley 1581 de 2012. La configuración del lote se guarda en la cuenta y vuelve al entrar desde otro equipo.
- **Toda la app en inglés**: botón Español / English en el inicio y en Configuración. Los textos del motor (alertas, razones, plan de acción) también se traducen.
- **Asistente por voz**: botón de micrófono (abajo a la derecha en el celular, en la barra lateral en el computador). Se le habla o se le escribe y responde con voz: días de lluvia de un mes, evaporación, temperatura, días de calor o fríos, heladas, aguaceros, veranillo, cuándo empiezan las lluvias, salud del suelo, pH, nutrientes, humedad, la estaca, qué sembrar, cuándo sembrar, riesgos, agua ahorrada, luna, sol y navegación ("abre el clima").
- **Escuchar cada tarjeta**: todas tienen un botón de altavoz que la lee en voz alta.
- **Computador**: la barra de pestañas pasa a un lado; en el celular sigue abajo.
- **Configuración en la barra** (sexto botón) y ya no junto a la zona. Ahí también están el idioma, la cuenta (cerrar sesión), **Mis estacas** y el permiso para compartir datos.
- **Último cultivo con selección múltiple.**
- Letra más grande en toda la app, sobre todo en las tarjetas pequeñas y los textos secundarios.
- **Rotación:** se quitó "Cómo repartir tus lotes".
- **Clima:** la ventanita de la lluvia solo dice "Llueve unos X días" y si la tierra se seca más de lo que llueve. En "Últimos 6 meses" la temperatura une los puntos con líneas y la letra es más grande.
- **Mi lote:** usa la última lectura de la estaca y dice de cuál y hace cuánto. Nueva tarjeta "Suelo según mapas globales" (SoilGrids, NASA POWER y Earth Engine) con el botón "Usar pH y tipo de suelo".

### Servidor
- `db.py`: tablas de usuarios, estacas, lecturas y caché de datos externos. Las tablas de usuarios no se borran al actualizar el catálogo.
- Contraseñas cifradas con `werkzeug` (hash con sal). Bloqueo de 15 minutos tras 5 intentos fallidos con el mismo correo.
- `services/estacas.py` y `docs/ESTACA.md`: recepción de lecturas de las estacas con token propio, validación de rangos y API de datos abiertos anónimos (JSON o CSV).
- `services/orquestador.py`: versión corregida del orquestador que mandó el equipo (NASA POWER, SoilGrids, Earth Engine, AppEEARS y precios). Cambios importantes: ECOSTRESS pasa a `ECO_L2T_LSTE.002` y SMAP a `SPL4SMGP.008`, porque las versiones del borrador ya no están en AppEEARS; las capas se validan contra AppEEARS antes de pedir; las credenciales salen de variables de entorno; AppEEARS trabaja con tareas que tardan, así que se envía y se consulta después.
- El motor responde en el idioma de la app (encabezado `X-Idioma`).

### Estaca
- `firmware/estaca_esp32s3/`: programa para ESP32-S3 (sensor Modbus de pH, CE y NPK, sensor capacitivo, DS18B20, DHT22 opcional, batería, sueño profundo y memoria para cuando no hay WiFi). **No probado en placa real**; verificar los registros Modbus del sensor.
- `herramientas/simular_estaca.py`: envía lecturas inventadas para la demo.

### Pendiente o por verificar
- Texto de la política de tratamiento de datos (Ley 1581): la app pide la autorización, pero falta la política.
- Umbrales de N, P, K y salinidad del sensor: aproximados, ajustarlos con un agrónomo.
- El reconocimiento de voz depende del navegador: funciona en Chrome y Edge, necesita internet y la app abierta en HTTPS o en localhost. Si no está disponible, se puede escribir. La lectura en voz alta sí funciona sin internet en la mayoría de equipos.
- El asistente entiende preguntas con reglas (palabras clave), no con inteligencia artificial: responde con los datos de la app y no inventa, pero no entiende preguntas fuera de esos temas.
- Identificador del conjunto de precios en datos.gov.co sin verificar; el DANE publica SIPSA también por un servicio SOAP.
- Las fuentes externas (NASA POWER, SoilGrids, AppEEARS, Earth Engine) no se pudieron probar en vivo desde el entorno de desarrollo, que no tenía internet hacia esos servicios.

## Versión 3 (ajustes del equipo)
- **Configuración de lote** después del tutorial: riego, número de lotes, hectáreas, último cultivo (con buscador y sin emojis), ver fase lunar, ver salida del sol y modo oscuro o claro (se aplica al instante). Se abre en cualquier momento con el botón de engranaje junto a la zona, que también permite **cambiar la ubicación**.
- **Modo claro** completo (colores de texto y gráficas ajustados para fondo blanco). El modo, la luna y el sol se recuerdan en el navegador.
- **Resumen:** sin medalla; tarjetas de **fase lunar** (aproximada, ciclo medio de 29,53 días) y **salida del sol** (ecuaciones de NOAA, hora de Colombia UTC-5).
- **Clima:** texto nuevo en "Lluvia y evaporación"; al pasar el cursor o tocar un mes se ven los días de lluvia y el agua en litros por metro cuadrado (y en baldes de 20 litros). Se quitó la gráfica por días. "Días de calor" (> 35 °C) y "Días fríos" (< 18 °C) ahora son del mes. "Temperatura del mes" muestra máxima, media y mínima. Se quitaron "Verdor de las plantas" y "Estrés de las plantas". "Últimos 6 meses": lo normal en barras grises (no línea punteada), temperatura en puntos y números al pasar el cursor; botones más grandes.
- **Mi lote:** "Datos recolectados por nuestra estaca"; sin ejemplos ni botón "Ver mis rotaciones"; el cuadro de la finca pasó a la configuración.
- **Rotación:** "La más recomendada", "Recomendación 2" y "Recomendación 3"; sin el calendario de la rotación. "Ver detalle" muestra solo "Temporada por temporada" y el **Plan de acción**: calendario grande que empieza en el mes de hoy.
- **Proyección** (antes Impacto): "Rotación a evaluar" con los cultivos en grande; se quitaron "Frente a sembrar lo mismo", "En resumen" y "Nitrógeno del suelo"; números al pasar el cursor en "Agua ahorrada acumulada".
- Motor: días de lluvia, de calor y fríos por mes (`dias_lluvia_mensual`, `dias_calor_mensual`, `dias_frio_mensual`); con NASA POWER se cuentan de los datos diarios. Umbrales en `services/motor.py`: `UMBRAL_CALOR = 35`, `UMBRAL_FRIO = 18`.

## Versión 2

## Interfaz nueva (estilo app Fitness)
- Fondo negro, tarjetas redondeadas, números grandes de colores y barra de pestañas flotante abajo.
- Cinco secciones: **Resumen**, **Clima**, **Mi lote**, **Rotación** e **Impacto**.
- Resumen con tres anillos: **Suelo** (salud del suelo), **Agua** (cuánto de la evaporación cubre la lluvia de los próximos 2 meses) y **Clima** (100 menos el mayor riesgo).
- Pensada para campesinos: íconos, semáforo, botones grandes, menos texto y botón **Escuchar** (lee el resumen en voz alta con la voz del celular).
- Funciona en celular y en computador (2 columnas en celular, 4 en pantallas anchas).

## Variables de clima agregadas al motor (`services/motor.py`)
| Variable | Cómo se calcula |
|---|---|
| Evaporación | Hargreaves-Samani (FAO-56) con temperatura máxima, mínima y media y la latitud de la zona |
| Balance de agua | Lluvia menos evaporación, mes a mes; meses con déficit |
| Estrés térmico | Días al año con máxima > 35 °C |
| Riesgo de heladas | Días con mínima <= 0 °C y la mínima más baja registrada |
| Lluvias extremas | Días al año con >= 50 mm y el aguacero más grande |
| Estrés vegetal | Verdor (NDVI) del último mes frente a lo normal |
| Tendencia hídrica | Cambio de la lluvia y la temperatura en unos 20 años y lluvia en un año seco |

El agua que pide cada cultivo ahora se ajusta por la evaporación de la zona (referencia: 5 mm por día).

## Prioridades del agricultor
Antes: suelo, agua, ingreso. Ahora (hasta 3): **agua, forraje, nitrógeno, erosión, materia orgánica y mercado**.
Cada opción muestra 7 indicadores (los 6 anteriores más el aguante en años secos). Cada indicador pesa 1 y cada prioridad elegida suma 3.
Las prioridades viejas siguen funcionando en la API: `suelo` pasa a `nitrogeno` e `ingreso` a `mercado`.

Nuevos campos en `data/cultivos.json`: `forraje`, `materia_organica`, `mercado` (0 a 1). **Son valores de ejemplo** y deben validarse con un agrónomo o con datos de la zona.

## Datos reales de NASA POWER
```
python importar.py nasa        # 20 años, hasta el año pasado
python importar.py nasa 10     # otro número de años
```
Descarga T2M, T2M_MAX, T2M_MIN, PRECTOTCORR y GWETROOT para cada zona y calcula todos los campos de clima.
Quedan de ejemplo hasta conectar su fuente: el NDVI mensual (MODIS) y la pendiente (NASADEM). La app avisa cuáles faltan.
Nota: GWETROOT es humedad relativa a la saturación del suelo (0 a 1), no humedad volumétrica.

## Otros
- La base de datos subió a la versión 3: al arrancar se vuelve a crear con los datos de ejemplo.
- Se corrigió el formato de miles en el mensaje de ahorro de agua.
