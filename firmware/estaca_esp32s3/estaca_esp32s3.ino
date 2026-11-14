/*
  Estaca Rotación Caribe · ESP32-S3
  ---------------------------------
  Mide el suelo cada cierto tiempo, guarda las lecturas en la memoria RTC (sobrevive al sueño profundo)
  y las envía al servidor por WiFi con el token de la estaca. Si no hay WiFi, las guarda y las manda después
  con su "edad" (edad_s), para que el servidor sepa cuándo se tomaron.

  Sensores (todos opcionales; lo que no esté conectado se omite):
   - Sensor de suelo RS485 Modbus "7 en 1": humedad, temperatura, conductividad (CE), pH, N, P y K.
     Va con un módulo MAX485 (o uno con control automático de dirección). Casi todos piden 12 a 24 V:
     usa un elevador de voltaje y córtale la energía mientras la estaca duerme (PIN_ENERGIA_SENSORES).
   - Sensor capacitivo de humedad (analógico), de respaldo si no hay sensor Modbus.
   - DS18B20 (temperatura del suelo), de respaldo.
   - DHT22 (temperatura y humedad del aire), opcional.
   - Divisor de voltaje para la batería.

  Bibliotecas (Gestor de bibliotecas del Arduino IDE):
   - ArduinoJson (versión 7) de Benoit Blanchon
   - ModbusMaster de Doc Walker
   - OneWire y DallasTemperature
   - DHT sensor library de Adafruit (solo si USAR_DHT22 = 1)
  Placa: "ESP32S3 Dev Module" (paquete esp32 de Espressif).

  IMPORTANTE: los registros Modbus cambian según el fabricante del sensor. Los de abajo son los de varios
  sensores "7 en 1" comunes, pero hay que VERIFICARLOS en la hoja de datos de tu sensor antes de confiar en los números.
  Este código no se ha probado todavía en una placa real.
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ModbusMaster.h>
#include <esp_sleep.h>
#include <math.h>
#include "secretos.h"   // copia secretos.ejemplo.h como secretos.h y llénalo

// ---------------------------------------------------------------- Configuración general
#define INTERVALO_S          1800   // mide cada 30 minutos
#define ENVIAR_CADA          2      // intenta enviar cuando haya al menos 2 lecturas guardadas (ahorra batería)
#define MAX_BUF              48     // lecturas que caben en la memoria RTC (unas 24 horas con 30 min)
#define MAX_POR_ENVIO        50     // el servidor acepta hasta 100 por envío
#define MAX_EDAD_S           (7UL * 86400UL)  // el servidor no acepta lecturas de más de 7 días
#define WIFI_ESPERA_MS       15000
#define ESPERA_SENSORES_MS   2000   // tiempo para que los sensores se estabilicen tras darles energía

// ---------------------------------------------------------------- Pines (ESP32-S3 DevKitC-1)
// Analógicos solo en ADC1 (GPIO 1 a 10): el ADC2 no funciona con el WiFi encendido.
#define PIN_ENERGIA_SENSORES 7      // MOSFET o relé que enciende los sensores; -1 si siempre tienen energía
#define PIN_HUMEDAD_CAP      4      // sensor capacitivo; -1 si no lo tienes
#define PIN_BATERIA          5      // divisor de voltaje; -1 si no lo tienes
#define DIVISOR_BATERIA      2.0f   // 2.0 para dos resistencias iguales (por ejemplo 100k y 100k)
#define PIN_DS18B20          15     // -1 si no lo tienes
#define PIN_RS485_RX         17
#define PIN_RS485_TX         18
#define PIN_RS485_DE_RE      16     // DE y RE del MAX485 unidos; -1 si tu módulo es automático
#define USAR_MODBUS          1
#define USAR_DHT22           0
#define PIN_DHT              6

// ---------------------------------------------------------------- Sensor Modbus (VERIFICAR EN LA HOJA DE DATOS)
#define MB_BAUDIOS           4800
#define MB_ESCLAVO           1
#define MB_FUNCION           3      // 3 = holding registers, 4 = input registers
#define MB_REG_INICIO        0x0000 // se leen 7 registros seguidos desde aquí:
// orden esperado: 0 humedad (x0,1 %), 1 temperatura (x0,1 °C, con signo), 2 CE (µS/cm), 3 pH (x0,1), 4 N, 5 P, 6 K (mg/kg)
#define MB_ESCALA_PH         0.1f   // algunos sensores usan 0,01

// ---------------------------------------------------------------- Calibración del sensor capacitivo
// Mide el voltaje con el sensor al aire (seco) y dentro de un vaso de agua (mojado) y pon esos valores.
// Sin calibrar con tu suelo, el resultado es un índice relativo de 0 a 100, no la humedad volumétrica exacta.
#define CAP_SECO_MV          2600
#define CAP_MOJADO_MV        1100

#if USAR_DHT22
#include <DHT.h>
DHT dht(PIN_DHT, DHT22);
#endif

// ---------------------------------------------------------------- Memoria que sobrevive al sueño profundo
struct Lectura {
  uint32_t t;   // segundos (aproximados) desde el primer arranque, para calcular edad_s
  float ph, humedad, temp_suelo, ce, n, p, k, temp_aire, humedad_aire, bateria;
};
RTC_DATA_ATTR Lectura buf[MAX_BUF];
RTC_DATA_ATTR uint16_t nbuf = 0;
RTC_DATA_ATTR uint32_t reloj_s = 0;
RTC_DATA_ATTR bool token_rechazado = false;

HardwareSerial RS485(1);
ModbusMaster nodo;
OneWire unCable(PIN_DS18B20 >= 0 ? PIN_DS18B20 : 0);
DallasTemperature ds18b20(&unCable);

static uint32_t ahora_s() { return reloj_s + millis() / 1000; }
static float enRango(float v, float a, float b) { return (isnan(v) || v < a || v > b) ? NAN : v; }

void antesDeTransmitir() { if (PIN_RS485_DE_RE >= 0) digitalWrite(PIN_RS485_DE_RE, HIGH); }
void despuesDeTransmitir() { if (PIN_RS485_DE_RE >= 0) digitalWrite(PIN_RS485_DE_RE, LOW); }

// ---------------------------------------------------------------- Medición
static bool leerModbus(Lectura &l) {
#if USAR_MODBUS
  if (PIN_RS485_DE_RE >= 0) { pinMode(PIN_RS485_DE_RE, OUTPUT); digitalWrite(PIN_RS485_DE_RE, LOW); }
  RS485.begin(MB_BAUDIOS, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);
  nodo.begin(MB_ESCLAVO, RS485);
  nodo.preTransmission(antesDeTransmitir);
  nodo.postTransmission(despuesDeTransmitir);
  for (int intento = 0; intento < 3; intento++) {
    uint8_t r = (MB_FUNCION == 4) ? nodo.readInputRegisters(MB_REG_INICIO, 7) : nodo.readHoldingRegisters(MB_REG_INICIO, 7);
    if (r == ModbusMaster::ku8MBSuccess) {
      l.humedad    = nodo.getResponseBuffer(0) * 0.1f;
      l.temp_suelo = (int16_t)nodo.getResponseBuffer(1) * 0.1f;
      l.ce         = nodo.getResponseBuffer(2);
      l.ph         = nodo.getResponseBuffer(3) * MB_ESCALA_PH;
      l.n          = nodo.getResponseBuffer(4);
      l.p          = nodo.getResponseBuffer(5);
      l.k          = nodo.getResponseBuffer(6);
      RS485.end();
      return true;
    }
    Serial.printf("Modbus: error 0x%02X (intento %d)\n", r, intento + 1);
    delay(300);
  }
  RS485.end();
#endif
  return false;
}

static float leerCapacitivo() {
  if (PIN_HUMEDAD_CAP < 0) return NAN;
  uint32_t suma = 0;
  for (int i = 0; i < 8; i++) { suma += analogReadMilliVolts(PIN_HUMEDAD_CAP); delay(10); }
  float mv = suma / 8.0f;
  float h = (CAP_SECO_MV - mv) / (float)(CAP_SECO_MV - CAP_MOJADO_MV) * 100.0f;
  return constrain(h, 0.0f, 100.0f);
}

static float leerDS18B20() {
  if (PIN_DS18B20 < 0) return NAN;
  ds18b20.begin();
  ds18b20.requestTemperatures();
  float t = ds18b20.getTempCByIndex(0);
  return (t == DEVICE_DISCONNECTED_C) ? NAN : t;
}

static float leerBateria() {
  if (PIN_BATERIA < 0) return NAN;
  uint32_t suma = 0;
  for (int i = 0; i < 8; i++) { suma += analogReadMilliVolts(PIN_BATERIA); delay(5); }
  return suma / 8.0f / 1000.0f * DIVISOR_BATERIA;
}

static Lectura medir() {
  Lectura l;
  l.t = ahora_s();
  l.ph = l.humedad = l.temp_suelo = l.ce = l.n = l.p = l.k = l.temp_aire = l.humedad_aire = l.bateria = NAN;

  if (PIN_ENERGIA_SENSORES >= 0) { pinMode(PIN_ENERGIA_SENSORES, OUTPUT); digitalWrite(PIN_ENERGIA_SENSORES, HIGH); }
  delay(ESPERA_SENSORES_MS);

  if (!leerModbus(l)) Serial.println("Modbus: sin respuesta, se usan los sensores de respaldo");
  if (isnan(l.humedad)) l.humedad = leerCapacitivo();
  if (isnan(l.temp_suelo)) l.temp_suelo = leerDS18B20();
#if USAR_DHT22
  dht.begin();
  delay(2000);
  l.temp_aire = dht.readTemperature();
  l.humedad_aire = dht.readHumidity();
#endif
  if (PIN_ENERGIA_SENSORES >= 0) digitalWrite(PIN_ENERGIA_SENSORES, LOW);
  l.bateria = leerBateria();

  // Los mismos rangos que valida el servidor: un valor imposible se descarta aquí,
  // porque si llega al servidor rechaza todo el envío.
  l.ph = enRango(l.ph, 0, 14);
  l.humedad = enRango(l.humedad, 0, 100);
  l.temp_suelo = enRango(l.temp_suelo, -10, 70);
  l.ce = enRango(l.ce, 0, 20000);
  l.n = enRango(l.n, 0, 2000);
  l.p = enRango(l.p, 0, 2000);
  l.k = enRango(l.k, 0, 5000);
  l.temp_aire = enRango(l.temp_aire, -20, 60);
  l.humedad_aire = enRango(l.humedad_aire, 0, 100);
  l.bateria = enRango(l.bateria, 0, 6);

  Serial.printf("Lectura: pH %.1f · humedad %.1f %% · suelo %.1f °C · CE %.0f · N %.0f P %.0f K %.0f · bateria %.2f V\n",
                l.ph, l.humedad, l.temp_suelo, l.ce, l.n, l.p, l.k, l.bateria);
  return l;
}

static void guardar(const Lectura &l) {
  if (nbuf >= MAX_BUF) {           // memoria llena: se descarta la más vieja
    memmove(buf, buf + 1, sizeof(Lectura) * (MAX_BUF - 1));
    nbuf = MAX_BUF - 1;
  }
  buf[nbuf++] = l;
}

static void quitarPrimeras(uint16_t cuantas) {
  if (cuantas >= nbuf) { nbuf = 0; return; }
  memmove(buf, buf + cuantas, sizeof(Lectura) * (nbuf - cuantas));
  nbuf -= cuantas;
}

// ---------------------------------------------------------------- Envío
static void poner(JsonObject o, const char *clave, float v, int decimales) {
  if (!isnan(v)) o[clave] = roundf(v * powf(10, decimales)) / powf(10, decimales);
}

static bool conectarWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_CLAVE);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_ESPERA_MS) delay(250);
  if (WiFi.status() != WL_CONNECTED) { Serial.println("WiFi: sin conexión, las lecturas quedan guardadas"); return false; }
  Serial.printf("WiFi: conectado, señal %d dBm\n", WiFi.RSSI());
  return true;
}

static void enviar() {
  uint32_t ahora = ahora_s();
  // Lecturas demasiado viejas: el servidor las rechazaría, se descartan.
  uint16_t viejas = 0;
  while (viejas < nbuf && ahora - buf[viejas].t > MAX_EDAD_S) viejas++;
  if (viejas) quitarPrimeras(viejas);
  if (!nbuf || !conectarWifi()) return;

  int rssi = WiFi.RSSI();
  while (nbuf) {
    uint16_t cuantas = nbuf < MAX_POR_ENVIO ? nbuf : MAX_POR_ENVIO;
    JsonDocument doc;
    JsonArray arr = doc["lecturas"].to<JsonArray>();
    for (uint16_t i = 0; i < cuantas; i++) {
      const Lectura &l = buf[i];
      JsonObject o = arr.add<JsonObject>();
      poner(o, "ph", l.ph, 2);
      poner(o, "humedad_pct", l.humedad, 1);
      poner(o, "temp_suelo_c", l.temp_suelo, 1);
      poner(o, "ce_us_cm", l.ce, 0);
      poner(o, "n_mg_kg", l.n, 0);
      poner(o, "p_mg_kg", l.p, 0);
      poner(o, "k_mg_kg", l.k, 0);
      poner(o, "temp_aire_c", l.temp_aire, 1);
      poner(o, "humedad_aire_pct", l.humedad_aire, 1);
      poner(o, "bateria_v", l.bateria, 2);
      if (i == cuantas - 1) o["rssi_dbm"] = rssi;
      o["edad_s"] = ahora - l.t;
    }
    String cuerpo;
    serializeJson(doc, cuerpo);

    HTTPClient http;
    WiFiClient plano;
    WiFiClientSecure seguro;
    bool https = strncmp(SERVIDOR_URL, "https", 5) == 0;
    if (https) {
      if (strlen(CA_RAIZ) > 0) seguro.setCACert(CA_RAIZ);
      else seguro.setInsecure();   // solo para pruebas: cifra pero no verifica el servidor
    }
    bool ok = https ? http.begin(seguro, SERVIDOR_URL) : http.begin(plano, SERVIDOR_URL);
    if (!ok) { Serial.println("HTTP: dirección no válida"); return; }
    http.setTimeout(15000);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + ESTACA_TOKEN);
    int codigo = http.POST(cuerpo);
    String resp = http.getString();
    http.end();
    Serial.printf("Servidor: %d %s\n", codigo, resp.c_str());

    if (codigo == 201) { quitarPrimeras(cuantas); token_rechazado = false; }
    else if (codigo == 400) { quitarPrimeras(cuantas); }   // datos que el servidor no acepta: no se reintentan
    else if (codigo == 401) { token_rechazado = true; return; }  // token malo: se guardan y se reintenta en el próximo ciclo
    else return;   // sin respuesta o error del servidor: se reintenta en el próximo ciclo
  }
}

// ---------------------------------------------------------------- Ciclo: despertar, medir, enviar, dormir
void setup() {
  Serial.begin(115200);
  delay(200);
  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER) reloj_s += INTERVALO_S;
  if (token_rechazado) Serial.println("Aviso: el servidor rechazó el token. Revisa ESTACA_TOKEN en secretos.h");

  guardar(medir());
  if (nbuf >= ENVIAR_CADA || token_rechazado) enviar();

  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  reloj_s += millis() / 1000;
  Serial.printf("Durmiendo %d s con %d lecturas guardadas\n", INTERVALO_S, nbuf);
  Serial.flush();
  esp_sleep_enable_timer_wakeup((uint64_t)INTERVALO_S * 1000000ULL);
  esp_deep_sleep_start();
}

void loop() {}
