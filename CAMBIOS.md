# Cambios de esta versión

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
