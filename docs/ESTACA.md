# Estaca Rotación Caribe (ESP32-S3)

La estaca mide el suelo del lote, guarda las lecturas aunque no haya WiFi y las envía al servidor. El servidor las une a la cuenta del agricultor y las usa en "Mi lote". Si el agricultor lo autoriza, las lecturas salen anónimas por la API de datos abiertos para la NASA, universidades u otras entidades.

> El firmware compila sin advertencias contra la biblioteca ArduinoJson 7 real y cabeceras simuladas del ESP32, y el servidor acepta el JSON exacto que arma. **Todavía no se ha probado en una placa real.** Los registros Modbus del sensor y la calibración del sensor capacitivo se deben verificar antes de confiar en los números.

## 1. Materiales

| Pieza | Para qué | Nota |
|---|---|---|
| ESP32-S3 DevKitC-1 | Cerebro, WiFi, sueño profundo | Placa "ESP32S3 Dev Module" en el Arduino IDE |
| Sensor de suelo RS485 Modbus "7 en 1" | Humedad, temperatura, CE, pH, N, P y K | La mayoría pide 12 a 24 V; revisa el tuyo |
| Módulo MAX485 (o RS485 automático) | Habla con el sensor Modbus | Los MAX485 son de 5 V: usa un módulo compatible con 3,3 V o un adaptador de nivel |
| Elevador de voltaje (por ejemplo MT3608) | Sube la batería a 12 V para el sensor Modbus | |
| MOSFET de canal N de nivel lógico (o relé) | Apaga los sensores mientras la estaca duerme | Ahorra mucha batería |
| Sensor capacitivo de humedad (opcional) | Respaldo si no hay sensor Modbus | Da un índice relativo si no se calibra con tu suelo |
| DS18B20 a prueba de agua (opcional) | Temperatura del suelo de respaldo | Resistencia de 4,7 kΩ entre datos y 3,3 V |
| DHT22 (opcional) | Temperatura y humedad del aire | Activa `USAR_DHT22` |
| Batería 18650 + panel solar + cargador (TP4056 o similar) | Energía | |
| Dos resistencias de 100 kΩ | Divisor para medir la batería | |
| Tubo PVC y caja IP65 | La estaca en sí | |

No tengo una fuente verificada del consumo exacto de este montaje; mídelo con un multímetro antes de escoger el tamaño de batería y panel.

## 2. Conexiones (valores por defecto del firmware)

| Señal | Pin ESP32-S3 |
|---|---|
| RS485 RX (RO del MAX485) | GPIO 17 |
| RS485 TX (DI del MAX485) | GPIO 18 |
| DE y RE del MAX485 (unidos) | GPIO 16 |
| Encendido de sensores (MOSFET) | GPIO 7 |
| Sensor capacitivo (salida analógica) | GPIO 4 |
| Divisor de batería (punto medio) | GPIO 5 |
| DS18B20 (datos) | GPIO 15 |
| DHT22 (datos) | GPIO 6 |

Los analógicos van en GPIO 1 a 10 (ADC1), porque el ADC2 no funciona con el WiFi encendido. Si un sensor no está conectado, pon su pin en `-1` en el `.ino`.

## 3. Puesta en marcha

1. En la app: **Configuración > Mis estacas > Agregar**. Copia el token (empieza por `est_`); solo se muestra una vez. Ahí mismo aparece la dirección del servidor.
2. En la carpeta `firmware/estaca_esp32s3/`, copia `secretos.ejemplo.h` como `secretos.h` y llena el WiFi, la dirección y el token. **No subas `secretos.h` a GitHub.**
3. Para HTTPS de verdad, pega en `CA_RAIZ` el certificado raíz del servidor. Si lo dejas vacío, la conexión va cifrada pero sin verificar el servidor; sirve para pruebas, no para producción.
4. Instala las bibliotecas: ArduinoJson (v7), ModbusMaster, OneWire, DallasTemperature y, si usas el DHT22, DHT sensor library.
5. Revisa en la hoja de datos de tu sensor: velocidad (`MB_BAUDIOS`), dirección (`MB_ESCLAVO`), función (`MB_FUNCION`), primer registro (`MB_REG_INICIO`), orden de los 7 valores y escala del pH (`MB_ESCALA_PH`). Los valores que trae el código son los de varios sensores "7 en 1" comunes, pero cambian según el fabricante.
6. Calibra el sensor capacitivo: anota los milivoltios al aire (`CAP_SECO_MV`) y en un vaso de agua (`CAP_MOJADO_MV`).
7. Sube el programa y abre el monitor serie a 115200 baudios. Debes ver la lectura y la respuesta del servidor (`201`).

## 4. Cómo trabaja

- Cada `INTERVALO_S` (30 minutos por defecto) se despierta, enciende los sensores, mide, los apaga y guarda la lectura en la memoria RTC (cabe un día de lecturas).
- Cuando hay al menos `ENVIAR_CADA` lecturas, se conecta al WiFi y las envía. Cada una lleva `edad_s` (segundos desde que se midió), así el servidor les pone la hora correcta aunque se hayan enviado tarde. El reloj es aproximado: se desvía un poco durante el sueño profundo.
- Si el servidor responde `201`, borra las enviadas. Si responde `400` (datos no válidos), las descarta para no reintentar algo que nunca va a pasar. Si responde `401` (token malo), las guarda y avisa por el monitor serie. Si no hay respuesta, las guarda y reintenta en el siguiente ciclo.
- Antes de enviar, descarta valores imposibles (por ejemplo un pH de 16), porque el servidor rechaza el envío completo si uno solo está fuera de rango.

## 5. API del dispositivo

`POST /api/estaca/lecturas`

Encabezados: `Authorization: Bearer est_...` y `Content-Type: application/json`

```json
{"lecturas": [
  {"ph": 6.2, "humedad_pct": 24.5, "temp_suelo_c": 29.1, "ce_us_cm": 450,
   "n_mg_kg": 32, "p_mg_kg": 18, "k_mg_kg": 150, "temp_aire_c": 31.0,
   "humedad_aire_pct": 70, "bateria_v": 3.95, "rssi_dbm": -67, "edad_s": 1800}
]}
```

Todos los campos son opcionales menos uno con valor. También se puede enviar una sola lectura sin la lista.

| Campo | Rango aceptado |
|---|---|
| ph | 0 a 14 |
| humedad_pct | 0 a 100 |
| temp_suelo_c | -10 a 70 |
| ce_us_cm | 0 a 20.000 |
| n_mg_kg, p_mg_kg | 0 a 2.000 |
| k_mg_kg | 0 a 5.000 |
| temp_aire_c | -20 a 60 |
| humedad_aire_pct | 0 a 100 |
| bateria_v | 0 a 6 |
| rssi_dbm | -130 a 0 |
| edad_s | 0 a 604.800 (7 días) |

Respuestas: `201 {"guardadas": n, "estaca": id}`, `400` (JSON o valores no válidos, máximo 100 lecturas por envío), `401` (token no válido).

Seguridad: el token se guarda en la base de datos solo como huella SHA-256; si alguien copia la base no puede hacerse pasar por la estaca. Si se pierde un token, se quita la estaca en la app y se crea otra.

## 6. Cómo la app usa las lecturas

En "Mi lote" se toma la última lectura de la estaca del lote más bajo. El pH, la humedad y la temperatura pasan tal cual. N, P y K se pasan a bajo, medio o alto con umbrales **aproximados** (`UMBRAL_NPK` en `services/estacas.py`: N 20 y 40, P 10 y 30, K 100 y 200 mg/kg) y la salinidad con 4.000 µS/cm (`UMBRAL_SAL_US_CM`). Ese umbral de 4 dS/m es el clásico para extracto de saturación de laboratorio; un sensor de campo mide distinto. Estos umbrales los debe ajustar un agrónomo con el sensor que usen.

## 7. Simulador (demo sin hardware)

```
python herramientas/simular_estaca.py --token est_xxx --historial 48
python herramientas/simular_estaca.py --token est_xxx --cada 30
python herramientas/simular_estaca.py --token est_xxx --seco
```

Envía lecturas inventadas con ciclo de día y noche. Sirve para mostrar el flujo en el reto; no son mediciones reales.

## 8. Datos abiertos

Solo salen lecturas de usuarios que activaron **"Compartir mis datos para la ciencia"** en Configuración (se puede quitar en cualquier momento). Sin nombre ni correo, con un código de estaca seudónimo y la ubicación redondeada a 0,01° (unos 1,1 km). No se publican batería ni señal WiFi.

- `GET /api/datos_abiertos`: descripción, unidades y si pide clave.
- `GET /api/datos_abiertos/lecturas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD&formato=json|csv`: máximo 366 días por consulta.
- Si se define la variable de entorno `DATOS_ABIERTOS_CLAVES` (claves separadas por comas), cada consulta debe llevar el encabezado `X-Api-Key`. Así se puede dar acceso solo a entidades con convenio.

Columnas del CSV: `estaca, fecha_utc, lat, lon, ph, humedad_pct, temp_suelo_c, ce_us_cm, n_mg_kg, p_mg_kg, k_mg_kg, temp_aire_c, humedad_aire_pct`.

Ley 1581 de 2012: el registro pide la autorización de tratamiento de datos, pero **falta el texto de la política de tratamiento** (responsable, finalidades, derechos y canal de consultas). Debe redactarse y enlazarse antes de usar la app con agricultores reales.

## 9. ¿Cómo llegan los datos a la NASA?

No encontré una vía para que un sensor propio suba datos automáticamente a la NASA. Lo que sí existe:

- **GLOBE** (programa educativo y de ciencia ciudadana patrocinado por la NASA) recibe mediciones hechas siguiendo sus protocolos. Desde el 23 de diciembre de 2025 cualquier miembro puede registrar todos los protocolos desde la app GLOBE Observer, después de la capacitación (eTraining). En suelo están humedad gravimétrica, humedad con el patrón de bloques de SMAP y temperatura del suelo. Ojo: el protocolo de humedad **con sensor** fue desactivado en septiembre de 2023, así que las lecturas de la estaca no entran tal cual; servirían para escoger dónde y cuándo tomar las muestras del protocolo.
- La API de datos abiertos de esta app (punto 8) deja los datos listos para que la NASA, una universidad o una empresa los consulten o los pidan en CSV.

Antes de prometer en el pitch que los datos "van a la NASA", conviene confirmarlo con GLOBE Colombia o con los mentores del reto.

Fuentes:
- [All GLOBE Protocols Now Open to Citizen Scientists (GLOBE Observer)](https://observer.globe.gov/news-events-and-people/news/-/obsnewsdetail/19589576/all-globe-protocols-now-open-to-citizen-scientists)
- [Protocolo de estaciones automáticas de humedad y temperatura del suelo, con aviso de desactivación (GLOBE)](https://globe.gov/documents/352961/d554e0a1-9f32-41bd-a2fe-eda45c555aea)
- [GLOBE Data User Guide v3 (nov. 2025)](https://www.globe.gov/documents/d/guest/globe-data-user-guide_v3-nov-2025)
