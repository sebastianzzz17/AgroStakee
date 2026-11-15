# Cambios

## Versión 12 (cuentas que no se pierden, plan de acción por meses)

- **Cuentas guardadas aparte:** con la variable `DATABASE_URL` (una base Postgres: Neon, Supabase o Render), las
  cuentas, las estacas y sus lecturas se guardan allá y sobreviven a los reinicios de Render, que borra su disco.
  El clima y el catálogo siguen en el disco porque la app los vuelve a crear sola. Sin la variable, todo sigue con
  SQLite como antes. Probado con un Postgres 16: cuenta, perfil, estaca y lecturas siguen ahí con el disco borrado;
  la app se reconecta sola si la base corta la conexión; 8 registros a la vez bajo gunicorn sin errores.
  `/api/estado_datos` dice `"cuentas": "postgres"` cuando está activo.
- **Plan de acción por meses:** en vez de la tira con iniciales, una agenda: cada fila es un mes con su hojita de
  calendario (mes y año, del color de la etapa), el nombre del mes en palabras, la etapa y las tareas. Los meses
  seguidos sin tareas se juntan ("Mayo a julio de 2027: Guandul sigue en el lote").
- **Suelo según mapas globales:** al tocar "Usar estos datos" sale el aviso "Datos aplicados" y la tarjeta lo marca;
  "Consultar de nuevo" vuelve a mostrar la animación de carga.
- **Fuentes de datos** al final de Resumen, Rotación y Proyección (el mismo texto de Mi lote).
- **Mi lote:** "Valores ajustados a mano" cambia por "Aquí están los datos de tu lote", en letra más grande.
- **Sales en el suelo** sin emojis. **Fósforo alto:** "Ayuda a raíces y flores", y la voz dice "Fósforo alto. Ayuda a
  raíces y flores." "Follaje" cambia por "hojas" en toda la app.
- **Proyección:** el botón "Realizar proyección" sin emoji y sin el recuadro "Comparado con".

## Versión 11 (Render: lentitud y Clima en blanco)

- **Clima en blanco (corregido):** al escoger un punto libre del mapa, la pestaña Clima fallaba
  (`Cannot read properties of undefined (reading 'campos_ejemplo')`) porque un punto no trae el clima dentro de la
  zona. Ahora esos datos salen de la respuesta del panel. Pasaba en cualquier servidor, no solo en Render.
- **El servidor ya no se bloquea con un punto libre:** `/api/punto` descargaba 10 años de NASA y el verdor MODIS
  mientras el agricultor esperaba. Con el gunicorn que trae Render por defecto (1 hilo, 30 s) eso frenaba todas las
  demás peticiones y gunicorn reiniciaba el proceso (`WORKER TIMEOUT`), llevándose la descarga de fondo.
  Ahora la descarga del punto va en un hilo aparte; la app muestra el clima de la zona más cercana y avisa cuando
  llega el del punto.
- **Ya no se queda en blanco si el servidor falla o tarda:**
  - Si el panel o las recomendaciones fallan (un 502, el servidor despertando), la app reintenta sola y lo dice
    ("El servidor no respondió; reintentando solo…"). Antes se quedaba con los esqueletos para siempre.
  - Si tardan más de 7 s, avisa que el servidor puede estar despertando (hasta un minuto en Render gratis).
  - Una respuesta que no es JSON (una página de error o de espera) cuenta como error y nunca se guarda como dato.
  - El estado de la descarga se sigue consultando aunque una consulta falle.
- **Render:** `gunicorn.conf.py` (1 proceso, 8 hilos), `render.yaml`, `gunicorn` en requirements, ruta `/salud`, y
  `python app.py` escucha en `0.0.0.0` cuando hay `PORT`.
- **Menos CPU:** los archivos grandes se escriben con el codificador JSON en C, 2 zonas a la vez en vez de 3 y el
  catálogo del IDEAM se lee una vez y queda en memoria. En la réplica de Render (0,1 de CPU) la peor demora del
  panel durante la descarga bajó de 3,6 s a 0,5 s.
- **Página comprimida:** 228 KB → 72 KB con gzip, y el navegador revalida sin volver a bajarla.
- **Copia de datos reales:** al terminar la descarga se guarda `data/clima_real.json`; si se sube con el código,
  un servidor con el disco vacío (Render) arranca ya con datos reales.
- **Al abrir la app, tu zona primero:** la zona que estás mirando se descarga de primera y la pantalla se
  actualiza sola apenas llegan sus datos reales.

## Versión 10 (barras de carga)

- Una sola barra de progreso para todas las cargas: pantalla de inicio, "Consultar mi punto", "Cargando recomendaciones", "Guardando información" y "Realizando proyección".
  - Avanza sola y frena si el servidor tarda.
  - Cuando llegan los datos sube hasta el 100% y se queda llena un instante antes de cerrar.
  - Antes, la de "Consultar mi punto" solo barría de lado a lado y nunca se llenaba, y las otras se cerraban justo al llegar al final.
  - Comprobado cuadro por cuadro: todas llegan al 100% y nunca retroceden, aunque la página se redibuje durante la carga.

## Versión 9 (plan de acción, leyenda del mapa, estado de la estaca)

- **Nutrientes:** la voz lee exactamente el nivel marcado en la pantalla y lo que causa, nunca los otros niveles de la escala. Al tocar un nivel lo dice enseguida, solo para ese nutriente.
- **Ver detalle:** queda solo el plan de acción, rediseñado:
  - una franja de colores con los meses desde hoy y una leyenda de etapas;
  - una línea de tiempo por etapas (preparar el lote y cada cultivo), con sus fechas, su duración y las tareas de cada mes;
  - letra más grande.
- **Últimos 6 meses:** sin el enunciado.
- **Mapa:** leyenda para cada capa (verdor, calor, humedad y lluvia), con los colores de los colormaps oficiales de NASA GIBS, los valores, los extremos en palabras ("Seco", "Muy húmedo"…) y qué significa donde no hay color.
- **Estaca:** "Estaca conectada: Sin conexión" en rojo, o "Estaca conectada: Conectada" en verde cuando hay lecturas de las últimas 24 horas.
- **Animación de "Consultar mi punto":** ya no se reinicia cuando la página se redibuja (eso la hacía ver trabada); dura unos 3,4 s como mínimo.
- **Pantallas de carga de 4,5 s** con mensajes que van cambiando: "Cargando recomendaciones", "Guardando información" y la nueva "Realizando proyección" al tocar "Realizar proyección".

## Versión 8 (ajustes finales)

- **Suelo según mapas globales:**
  - Texto más corto.
  - Ya no muestra la línea de "variables medidas" ni la lista de fuentes con ✓ y ✗.
  - Al tocar "Consultar mi punto" aparece una animación breve: un satélite gira sobre el pin y van pasando las fuentes.
- **Consulta del punto mucho más rápida.** Antes podía tardar minutos porque:
  - el servidor esperaba a la fuente más lenta aunque ya se le hubiera acabado el tiempo;
  - pedía el catálogo completo del IDEAM y los precios, que la tarjeta no muestra;
  - probaba MODIS en tres satélites seguidos;
  - esperaba 30 s a SoilGrids (pausada) en cada consulta.

  Ahora:
  - Usa lo que la descarga automática ya trajo para ese lugar, sin internet.
  - El resto corre en paralelo con un límite total de 8 s; lo que no llegue se completa con el promedio de la zona.
  - SoilGrids no se vuelve a esperar por 6 horas si no respondió.
  - La respuesta se guarda (7 días si llegó completa, 1 día si faltó algo).

  En pruebas con APIs lentas simuladas: 8 s el peor caso la primera vez, y al instante si el punto ya se consultó o la zona ya se descargó.
- **Proyección:** ya no calcula nada al entrar. El usuario escribe las hectáreas (se pueden teclear, con coma o punto) y elige los años, y toca "Realizar proyección". Si después cambia algo, el resultado anterior se atenúa hasta volver a tocar el botón.
- **"Estaca no conectada"** en lugar de "Sin estaca".

## Versión 7 (AgroStake: datos reales automáticos, puntos libres, proyección corregida, sin señal)

- **Nuevo nombre: AgroStake.**
- **Datos reales de la NASA sin comandos** (`services/sincronizar.py`): al arrancar, la app descarga sola y en segundo plano, para las 8 zonas:
  - el clima de 20 años de NASA POWER, con humedad (GWETTOP) y temperatura de la superficie (TS);
  - el verdor normal de cada mes (NDVI de MODIS por la API de ORNL DAAC, con respaldo en Aqua y VIIRS);
  - la pendiente (elevación SRTM con Open-Elevation, o Copernicus DEM con Open-Meteo).

  También descarga los últimos ~7 meses (lluvia y temperatura diarias, NDVI reciente). Repite el clima cada 30 días y lo reciente cada día. Si no hay internet, vuelve a intentar cada 30 minutos. Luego actualiza IDEAM y USDA, y Copernicus si hay credenciales. Se apaga con `AGROSTAKE_SIN_DESCARGA=1`. Avance en `GET /api/estado_datos` y en la app.
- **"Últimos 6 meses" y la lluvia día por día ahora son reales** cuando ya se descargaron (antes eran de ejemplo). Si falta algún mes, se avisa.
- **Punto libre del mapa:** si tocas un lugar que no es una de las 8 zonas, la app busca el clima de la NASA para esa latitud y longitud (`POST /api/punto`, zona `p:lat,lon`). El suelo sale de los estudios de la zona más cercana. Sin internet, usa el clima de la zona más cercana y lo dice.
- **Suelo según mapas globales**, ahora debajo de la salud del suelo:
  - Abre con el enunciado de qué datos de la NASA usa.
  - Suma NASA POWER (humedad y temperatura del suelo de los últimos 30 días), MODIS (NDVI) y SRTM (pendiente), que no piden cuenta.
  - Toda variable que falte se llena con el promedio de la zona más cercana y, si tampoco hay, con un valor típico. Cada valor dice de dónde salió (satélite o mapa, promedio de la zona o estimado).
  - "Usar estos datos" también pasa la humedad y la temperatura.
- **Proyección corregida.** Antes salían números negativos para planes buenos porque:
  - (1) el abono verde y el rastrojo contaban como riego;
  - (2) "sin rotar" dejaba el verano vacío;
  - (3) se comparaba con repetir el último cultivo, aunque fuera frijol o yuca.

  Ahora "sin rotar" siembra el cereal de referencia (maíz, o arroz si eso sembraba el agricultor) en las mismas temporadas productivas del plan, y las coberturas no se riegan. El nitrógeno cambia de forma gradual, en vez de saltar a 0% o 100%. La app dice contra qué compara, y explica cuando un plan pide más agua (por ejemplo, porque incluye arroz) o es un solo cultivo de todo el año. Se revisaron 4.032 combinaciones: ningún plan con 70% o más sale peor en más de un indicador.
- **Mapa:** las capas de calor y humedad usaban imágenes de un solo día, que salen vacías con nubes. Ahora:
  - Usan el servicio WMS de GIBS (la imagen más reciente disponible) con composiciones de 8 días: VIIRS para calor y verdor, SMAP L4 para humedad.
  - Si una capa sale vacía o falla, se prueba sola la siguiente fuente.
  - MODIS queda de último porque NASA anunció que Terra y Aqua empiezan a apagarse entre finales de 2026 e inicios de 2027.
- **Uso sin señal:**
  - La app guarda las últimas respuestas (panel, recomendaciones, proyección, suelo) y las muestra con un aviso de cuándo son.
  - El service worker (`static/sw.js`) guarda la app y las teselas del mapa ya vistas.
  - Se puede instalar como app (`manifest.webmanifest`).
- **Etiqueta de la estaca:** dice "Datos recolectados por nuestra estaca" solo si hay estaca; si no, "Sin estaca: datos históricos de tu zona".
- **Revisión en celular (360 a 412 px):**
  - En Proyección, los tres botones "Recomendación 1, 2, 3" eran más anchos que la pantalla; en Android eso ensanchaba toda la vista y dejaba iconos corridos y la ✕ de las hojas por fuera. Ahora dicen "Opción 1, 2, 3" en pantallas angostas.
  - Títulos que se partían ("Proyecció n").
  - Meses de la gráfica de lluvia que se montaban.
  - "Proyección" cortado en la barra.
  - "Cerrar sesión" que se salía de la tarjeta.
- Se corrigió la lectura de los estudios del piloto: "40% de las muestras alto" ya no se toma como 40% de materia orgánica.
- `python importar.py nasa` hace lo mismo que la descarga automática, pero de una vez.

## Versión 6 (relleno histórico, carga animada, avisos, recorrido hablado)

- **Sin estaca, los datos se llenan con el historial de la zona** (`services/historico.py`, `GET /api/suelo_historico?zona=&mes=`):
  - pH, nitrógeno, fósforo, potasio y sales: estudios de suelos publicados para cada zona (`data/piloto.json`).
  - Humedad del suelo, en este orden: ERA5-Land de Copernicus (si se importó), NASA POWER (GWETTOP por la porosidad de la textura) o, sin ninguno, una estimación con la lluvia y el secado del mes entre el punto de marchitez y la capacidad de campo (valores aproximados de FAO-56).
  - Temperatura del suelo: ERA5-Land, NASA POWER (TS) o la temperatura media del mes + 1,5 °C.
  - La línea de estado de "Mi lote" dice de dónde salió cada dato.
- **Se quitó la tarjeta "Datos de referencia de tu zona"** y volvió la de "Suelo según mapas globales" con su botón "Usar estos datos".
- **Botón "Guardar datos"** al final de "Mi lote": pantalla de carga con una planta que crece y "Cargando recomendaciones…" (unos 3 segundos) y luego pasa a Rotación. "Ver proyección" muestra "Guardando información…" y abre la proyección.
- **Proyección:** cambiar hectáreas o años ya no recalcula solo; los resultados se ven atenuados hasta tocar "Realizar proyección", que muestra la carga y vuelve a animar.
- **Notificaciones** (campana con contador en la cabecera): regar o no según la humedad del suelo, días que faltan para sembrar y cosechar según el plan, alertas del clima y estaca sin datos o con batería baja. Se marcan como leídas al abrir la campana y se reinician cada día. Con permiso del navegador también salen como aviso del equipo, **solo mientras la app está abierta** (no hay servidor de avisos push).
- **Recorrido guiado y hablado** la primera vez (y con el botón "Ayuda"/"¿Cómo funciona?"): resalta cada parte, la explica en voz alta, tiene "Callar", "Atrás", "Siguiente" y "Saltar", y termina señalando el asistente.
- **Tutorial inicial:** dos pantallas nuevas con animación: primero se clava la estaca, después los datos llegan solos a la app.
- **El asistente saluda en voz alta al abrirse** y la primera vez explica qué sabe hacer y termina con "Presiona el botón verde para hacerme una pregunta".
- **Porcentajes en lugar de "de 100"** en Resumen, Rotación, Proyección, informe y asistente.
- **Lectura en voz por tarjeta:** humedad dice el valor y su rango; lluvia dice "mes lluvioso", "mes seco", etc.; la gráfica de lluvia lee solo el mes tocado (o el enunciado, el mes actual y los 3 datos); "Últimos 6 meses" lee solo la barra o punto tocado; tipo de suelo, pH, temperatura, nutrientes (nivel elegido y su efecto) y sales leen solo lo seleccionado; "¿Qué es lo más importante para ti?" ya se puede escuchar.
- **Textos:** "Evaporación" pasa a "Secado de la tierra" (también en las alertas y en el informe); pH "ideal para cultivo" / "no es ideal para cultivo"; nuevo subtítulo de nutrientes; se quitó "estás viendo datos de ejemplo" y la frase del anillo de riesgos; letra más grande en las tarjetas del clima.
- **Iconos interactivos:** tubo de ensayo para el pH (cambia de color) y termómetro para la temperatura.
- **Animaciones al volver a cada sección:** anillos que se llenan, barras que suben y líneas que se dibujan otra vez.
- **Fuentes:** nota al pie en Mi lote y Clima, incluida la aclaración de que las gráficas y animaciones se generaron con inteligencia artificial.
- **Integraciones nuevas:** `python importar.py cds [años]` (ERA5-Land de Copernicus CDS: humedad y temperatura del suelo; pide cuenta, licencia y `pip install cdsapi`) y `python importar.py usda` (características de cultivos de USDA PLANTS; actualiza el pH mínimo y máximo cuando PLANTS los tiene). NASA POWER ahora también trae GWETTOP y TS.
- El mapa y las capas de la NASA no se tocaron.

## Versión 5 (prueba piloto sin estaca, inicio en Mi lote y animaciones)

- **Datos de referencia para las 8 zonas** (`data/piloto.json`, detalle en `docs/PILOTO.md`): pH, textura, nitrógeno, fósforo, potasio y sales tomados de estudios de suelos publicados, con su fuente y nivel de confianza. Sin estaca, "Mi lote" los aplica solo; si el agricultor ajusta algo a mano se respeta, y puede volver a ellos con "Usar estos valores".
- **Estaciones del IDEAM más cercanas** a cada lote (`services/ideam.py`), con el catálogo oficial `hp9r-jxuu` cuando hay internet y una copia regional de 2022 incluida en la app cuando no.
- **SoilGrids:** ISRIC pausó su API REST. Si falla, ahora se intenta SoilGrids en Google Earth Engine; el mensaje de error lo explica en vez de mostrar "—". La tarjeta también muestra la lluvia y las temperaturas de NASA POWER.
- `python importar.py ideam` y `python importar.py piloto` (estaciones del IDEAM + clima NASA POWER de las 8 zonas). Nuevo endpoint `GET /api/referencia?zona=&lat=&lon=`.
- **La app abre en "Mi lote"** al entrar y al escoger la zona.
- **Animaciones:** transición lateral entre pestañas, indicador que se desliza en la barra, números que suben desde cero, planta que crece según la salud del suelo (más sana, más alta, más hojas y flor), nivel de agua con olas en la humedad, iconos de cultivos que brotan y se mecen, tarjetas que se levantan al pasar el cursor, selecciones con rebote y tarjetas "esqueleto" mientras cargan. Se apagan si el equipo pide reducir el movimiento.
- El asistente responde de dónde salen los datos y cuál es la estación del IDEAM más cercana.

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
