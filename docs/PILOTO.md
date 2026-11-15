# Datos de la prueba piloto (8 zonas, sin estaca)

Mientras no hay estaca en el lote, "Mi lote" usa **datos de referencia publicados** para cada zona y muestra las **estaciones del IDEAM más cercanas**. Todo está en la app y funciona sin internet. En cuanto llega una lectura de la estaca, la estaca manda; si el agricultor cambia un valor a mano, se respeta y puede volver a los de referencia con un botón.

## Por qué "mapas globales" no daba datos

- **SoilGrids:** ISRIC pausó temporalmente su API REST y no dio fecha para restablecerla (aviso en docs.isric.org, actualizado el 18 de diciembre de 2025). No era un error del código.
- La tarjeta vieja solo mostraba suelo, así que aunque NASA POWER respondiera, todo salía en "—". Ahora también muestra la lluvia y las temperaturas de NASA POWER del último año.
- Ahora, si la API REST falla, se intenta la copia de SoilGrids que ISRIC publica en Google Earth Engine (`projects/soilgrids-isric/<propiedad>_mean`). Eso exige `pip install earthengine-api`, autenticarse y la variable `GEE_PROJECT`. **No se pudo probar en vivo** desde el entorno de desarrollo.

## Suelo de referencia por zona (`data/piloto.json`)

| Zona | pH | Textura | N / P / K | Fuente principal | Confianza |
|---|---|---|---|---|---|
| Montería (Valle del Sinú) | 6,26 ± 0,58 | arcilloso | medio / medio / alto | Promedio de Córdoba en Contreras-Santos y otros (2021); suelo Vertic Endoaquept del Sinú | media |
| Valledupar | 6,30 ± 0,84 | franco | bajo / medio / medio | Promedio del Cesar (2021) | media |
| Zona Bananera | 4,64 a 8,03 | franco | medio / alto / medio | Estudio de 25 puntos en la Zona Bananera; estudio FAO de suelos con sales | media |
| Montes de María (San Jacinto) | 6,54 ± 0,49 | franco | medio / alto / alto | Promedio de Bolívar (incluye El Carmen de Bolívar y San Juan Nepomuceno) | media |
| Repelón | 6,34 ± 0,62 | franco | medio / medio / alto | Promedio del Atlántico (incluye Repelón) y estudio del distrito de riego de Repelón (CUC, 2017) | media |
| Depresión Momposina | 6,54 ± 0,49 | arcilloso | medio / alto / alto | Promedio de Bolívar (incluye Magangué); no hay estudio propio de Mompox | baja |
| Sincelejo | 6,16 ± 0,53 | franco | medio / medio / alto | Promedio de Sucre (incluye Sincelejo, Corozal y Sampués) | media |
| Riohacha | 5,92 a 7,95 | arenoso | bajo / medio / medio | 5 análisis del IGAC en Uribia (Alta Guajira), no en Riohacha | baja |

Advertencias importantes:

- Los promedios de Contreras-Santos y otros (2021) son de **fincas ganaderas** (0 a 30 cm, abril y mayo de 2016), no de lotes agrícolas. Sirven como punto de partida, no como medición del lote.
- Las clases bajo, medio y alto son una **interpretación aproximada** (umbrales en `data/piloto.json > interpretacion`). Un agrónomo debe revisarlas.
- Los números se extrajeron de los PDF con una herramienta automática; antes de citarlos en la presentación, confírmalos en la tabla 4 del artículo. En la fila del Cesar, el calcio más el magnesio (6,01 + 7,49) suman más que la CICE (7,56), lo que no cuadra; puede ser un error del artículo o de la extracción.
- La humedad y la temperatura del suelo **no** tienen dato de referencia: cambian día a día y solo las mide la estaca.

## Estaciones del IDEAM

- El catálogo oficial está en datos abiertos como **`hp9r-jxuu`** (`https://www.datos.gov.co/resource/hp9r-jxuu.json`). El código del equipo usaba `hpwx-a3qe`, que no pude verificar.
- Sin internet, la app usa `data/cne_caribe.json`: 583 estaciones activas del IDEAM que miden lluvia o clima en el Caribe, tomadas del archivo oficial `CNE_IDEAM.xls` del **13 de febrero de 2022** (copia guardada en el repositorio público rcfdtools/R.HydroTools). Alguna estación pudo cambiar de estado desde entonces.
- Con internet: `python importar.py ideam` baja el catálogo actual y lo guarda por 30 días.
- Estaciones más cercanas (copia de 2022): Repelón (estación automática a 0,8 km), Valledupar (Fedearroz a 0,7 km y aeropuerto a 3,8 km), Riohacha (aeropuerto a 1,4 km), Sincelejo (Puerta Roja a 2,3 km), Montería (dos agrometeorológicas a 3,7 y 5,3 km), Zona Bananera (Padelma a 7,7 km), Mompox (pluviométrica a 2,6 km; la climática más cercana a 18,6 km), San Jacinto (pluviométrica a 11,6 km y El Carmen de Bolívar a 12,3 km).
- El catálogo solo dice dónde está cada estación. Las series (lluvia diaria, temperaturas) se descargan en DHIME con el código de la estación; la app todavía no las baja sola.

## Cambios al código del equipo (orquestador con IDEAM)

| En el código original | Problema | Cómo quedó |
|---|---|---|
| Conjunto `hpwx-a3qe` | No verificado; el catálogo del IDEAM es `hp9r-jxuu` | `services/ideam.py` usa `hp9r-jxuu` |
| `upper(departamento) like '%ATLANTICO%'` | En el catálogo hay tildes ("Bolívar", "Córdoba") y la estación más cercana puede estar en el departamento vecino | Se mide la distancia a todas las estaciones |
| `$limit: 100` | Deja estaciones por fuera | Se baja el catálogo completo una vez y se guarda |
| Sin filtro de estado ni categoría | Puede escoger estaciones suspendidas o que solo miden ríos | Solo activas del IDEAM que miden lluvia o clima |
| Texto del departamento dentro de la consulta | Riesgo de inyección en SoQL | Ya no se arma la consulta con texto del usuario |
| SoilGrids: promedio simple de capas y todo entre 10 | Las capas tienen grosores distintos (5, 10 y 15 cm) | Promedio pesado por grosor y factor de la API |
| `ee.Initialize()` al crear la clase | Si Earth Engine no está, la app no arranca | Earth Engine se carga solo cuando se usa |

## Clima de las 8 zonas

El clima de la app sigue siendo **de ejemplo** hasta que se corra, en un computador con internet:

```
python importar.py piloto        # estaciones del IDEAM + 20 años de NASA POWER para las 8 zonas
```

Fuentes:
- [SoilGrids: aviso de la pausa de la API REST (ISRIC)](https://docs.isric.org/globaldata/soilgrids/)
- [SoilGrids en Google Earth Engine (ISRIC)](https://docs.isric.org/globaldata/soilgrids/access_on_gee.html)
- [Contreras-Santos y otros (2021), Agronomía Costarricense 45(2)](https://dialnet.unirioja.es/descarga/articulo/8018402.pdf)
- [Suelos de la Zona Bananera (Revista de Investigación Agraria y Ambiental 13(2))](https://dialnet.unirioja.es/descarga/articulo/8479099.pdf)
- [Suelos afectados por sales en la Zona Bananera (FAO, GSAS21)](https://fao.org/fileadmin/user_upload/GSP/GSAS21/069.pdf)
- [Distrito de riego de Repelón (Universidad de la Costa)](https://repositorio.cuc.edu.co/handle/11323/339)
- [Análisis de suelos en Uribia, La Guajira (IGAC, 2019)](https://cendar-repositorio.metabiblioteca.org/bitstream/001/8200/6/INST-D%202019.%20199.%205.pdf)
- [Salinización de suelos en la región Caribe (INGE CUC, 2022)](https://www.redalyc.org/pdf/4977/497779341014.pdf)
- [Catálogo de estaciones en la librería colombia-hydrodata (usa hp9r-jxuu)](https://github.com/sebnarvaez19/colombia-hydrodata)
- [Copia de CNE_IDEAM.xls de febrero de 2022 (rcfdtools/R.HydroTools)](https://github.com/rcfdtools/R.HydroTools)

## Relleno histórico cuando no hay estaca (versión 6)

`GET /api/suelo_historico?zona=<id>&mes=<1-12>` arma un suelo completo para la zona y el mes. Cada dato dice de dónde salió (`origen`):

| Dato | Primera opción | Si no hay | Último recurso |
|---|---|---|---|
| pH, N, P, K, sales | Estudios de `data/piloto.json` | | |
| Humedad del suelo | ERA5-Land (`data/historico_suelo.json`) | NASA POWER GWETTOP × porosidad (arenoso 0,40; franco 0,46; arcilloso 0,50) | Estimación: punto de marchitez + (capacidad de campo − punto de marchitez) × lluvia/secado del mes |
| Temperatura del suelo | ERA5-Land | NASA POWER TS | Temperatura media del mes + 1,5 °C |

Los valores de capacidad de campo y punto de marchitez son aproximados (FAO-56, tabla 19) y conviene verificarlos con un análisis de laboratorio. La estimación del último recurso **no es una medición**: es un valor razonable para que las recomendaciones funcionen mientras llega la estaca.

### Cargar datos reales (requiere internet)

```
pip install cdsapi                 # solo para Copernicus
python importar.py nasa            # clima, GWETTOP y TS de NASA POWER
python importar.py cds 10          # ERA5-Land: crea data/historico_suelo.json
python importar.py usda            # USDA PLANTS: crea data/usda_plants.json
```

Para `cds` hace falta una cuenta en el Climate Data Store de Copernicus, aceptar la licencia de ERA5-Land en la página del conjunto y guardar el token en `~/.cdsapirc` (o en `CDSAPI_URL` y `CDSAPI_KEY`). **Nunca subas ese archivo ni el token a GitHub.** Estas dos importaciones no se pudieron probar en vivo desde el entorno donde se programaron; si el formato de respuesta cambió, el programa avisa y la app sigue con la estimación.

## Descarga automática (versión 7)

Ya no hace falta correr `importar.py`: al arrancar, `services/sincronizar.py` descarga en segundo plano el clima de
NASA POWER (20 años), el NDVI de MODIS (ORNL DAAC) y la pendiente (SRTM) de las 8 zonas, y los datos de los
últimos meses. Si un dato no se puede descargar, se conserva el anterior y la zona queda marcada con los campos que
siguen siendo de ejemplo (`campos_ejemplo`). El avance se ve en la app y en `GET /api/estado_datos`.


## Pasto (versión 13)

El cultivo "Pasto" toma como referencia la braquiaria (*Urochloa decumbens*, antes *Brachiaria decumbens*), una de las
gramíneas mejoradas más sembradas en el trópico bajo de Colombia. En la app ocupa un año entero (como la yuca y el ñame).

| Dato | Valor | De dónde sale |
|---|---|---|
| pH | 4,0 a 8,0 | Tropical Forages: se adapta a suelos con pH desde 3,5; la ficha no da límite alto, así que el 8,0 se toma de *U. brizantha* (pH 4 a 8). La app no deja bajar de 4. |
| Agua | 1.000 mm al año; aguante a sequía medio | Tropical Forages: crece con lluvias desde 700 mm, sobre todo con 1.200 a 2.500 mm y hasta 5 meses secos; sigue verde en el verano, pero produce mucho menos. |
| Salinidad | Baja | La ficha no trae el dato; se asume baja por precaución. |
| Nitrógeno | No lo fija; demanda media-baja | Tropical Forages: aguanta suelos pobres, pero responde mucho al N y al P. |
| Cobertura | Alta (0,9) | Tropical Forages: se extiende y cubre rápido el suelo; buena para controlar la erosión en laderas. |
| Siembra | Al voleo, 2 a 4 kg de semilla por hectárea | Tropical Forages. |
| Primer pastoreo y descanso | 70 a 120 días; potreros con 25 a 40 días de descanso | Ficha de semilla de *B. decumbens* cv. Basilisk (proveedor comercial). Varía con el suelo y la lluvia. |
| Materia orgánica, mercado e ingreso | 0,7 · 0,3 · 0,5 | Estimados del equipo: el pasto no se vende, su valor llega por el ganado. Pendientes de validar. |

Fuentes: Tropical Forages, fichas de *Urochloa decumbens* y *U. brizantha* (tropicalforages.info); ficha técnica de
*Brachiaria decumbens* cv. Basilisk de un proveedor de semillas. Si el pasto de tu finca es otro (colosoana, angleton,
guinea), sus valores cambian.
