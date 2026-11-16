/*
 * AmpereWatch - Firmware ESP32 + ADS1115 -> MQTT sobre TLS (puerto 8883)
 *
 * Cumple docs/PROTOCOLO_MQTT.md:
 *   - industrial/amperewatch/rms       cada ~1 s   {"rms": 12.52}
 *   - industrial/amperewatch/waveform  cada ~1 s   {"fs":860,"samples":[...],"t_us":[...]}
 *   - Valida el broker con ca.crt, usuario "esp32", hora por NTP.
 *
 * Librerias (Gestor de librerias): PubSubClient (Nick O'Leary).
 * Placa: ESP32 Dev Module. Core ESP32 de Arduino 2.x o 3.x.
 *
 * Conexiones (ADS1115):
 *   VDD -> 3V3 | GND -> GND | SDA -> GPIO21 | SCL -> GPIO22 | ADDR -> GND (0x48)
 *   ALERT/RDY -> GPIO4 (con pull-up de 10k a 3V3) | A0 -> salida del sensor de corriente
 *
 * IMPORTANTE: al encender, el motor debe estar SIN corriente: el firmware mide el nivel de
 * reposo del sensor (offset) durante el arranque.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <time.h>
#include <math.h>
#include "esp_timer.h"

// =============================== CONFIGURACION ===============================
// ---- WiFi ----
const char* WIFI_SSID = "Red S";
const char* WIFI_PASS = "4ZR431123";

// ---- MQTT (la IP debe estar en el certificado: --ip al ejecutar setup_security.sh) ----
const char*    MQTT_HOST      = "10.247.83.158";
const uint16_t MQTT_PORT      = 8883;
const char*    MQTT_USER      = "esp32";
const char*    MQTT_PASS      = "d576aba35b0c3c09a6b0a69793410bb5";   // MQTT_DEVICE_PASSWORD del .env
const char*    MQTT_CLIENT_ID = "esp32-amperewatch";         // distinto al del simulador
const char*    TOPIC_RMS      = "industrial/amperewatch/rms";
const char*    TOPIC_WAVE     = "industrial/amperewatch/waveform";

// ---- NTP: primero el servidor (contenedor ntp), luego internet de respaldo ----
const char* NTP_1 = "10.247.83.158";
const char* NTP_2 = "pool.ntp.org";
const long  GMT_OFFSET_S = -5 * 3600;            // Colombia (no afecta al TLS, que usa UTC)
const time_t EPOCH_MIN = 1767225600;             // 2026-01-01: por debajo, la hora no es valida

// ---- Certificado de la CA: pega aqui el contenido de certs/ca.crt ----
const char* CA_CERT = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFTzCCAzegAwIBAgIUVt8WAQ595oVKsSVpd3eIS9QKa9YwDQYJKoZIhvcNAQEL
BQAwLzEXMBUGA1UEAwwOQW1wZXJlV2F0Y2ggQ0ExFDASBgNVBAoMC0FtcGVyZVdh
dGNoMB4XDTI2MTAzMTIzMTc0N1oXDTM2MTAyODIzMTc0N1owLzEXMBUGA1UEAwwO
QW1wZXJlV2F0Y2ggQ0ExFDASBgNVBAoMC0FtcGVyZVdhdGNoMIICIjANBgkqhkiG
9w0BAQEFAAOCAg8AMIICCgKCAgEA2wRGNArGwJFJyussivUeOr1lzhabZgh3TvuS
/CpzO2+eGlzzU25/5r5FJZJgBwOtuSlVxqs6cKjbWYRR+keiMRXramJ9Z5Bo+kHL
QuHJnLTzlcLvvvulUvZW590jWFmi45qFAYzeOjepudgUX0J3LNVIsgOzLS6viC0R
zrEaOTRWwILSe7WT/VCR6kv02Zwjf66oFPPDqoRYgjRn4TtRCFRfsiyOkNPWxIEw
34MItXFoGrLQJTbziS+69ESVQFJ/JpO8UXhVk1ofRLMNBRZ+Q0eulDDes6MqjkQt
H6LS1EXkiJfIGkqtewSC9xyiOq1jqXroxGiV/WWpRPFLtRgZKbZK53UMb/ZCDK9i
YA0Uh1cmockPlgb3SLYvK17sLLZcvQZ9V63VmfkC6IYiwIaUw282fLnVFjFr+F5G
NFPUPp+TvI+29Vhs8h23ORyupbIUcfiPHGprZY4mWrz1jTfqxuJaKgVpho0gpyw6
GGQPBqOaoZD0UzDyJ8nPAqpkOeL5qJgG22SmhOATvLDgBIDldk6TvUgEqW5ChuEq
+SDM2oSOmyobNNMEwe3zSPpauaRZvdKmVcY3MR6btrGMbk4ZyL8VDHo4zwpx00Ed
yPLnCneDUP4WdUhfQh/4b8p1EicCrXnQqK7W4dOZWRnkkqz2DkF6ECE++C2FoGe2
gJxN+yMCAwEAAaNjMGEwHQYDVR0OBBYEFOzktwsswe+vJCy5VHiiwspdDDQeMB8G
A1UdIwQYMBaAFOzktwsswe+vJCy5VHiiwspdDDQeMA8GA1UdEwEB/wQFMAMBAf8w
DgYDVR0PAQH/BAQDAgEGMA0GCSqGSIb3DQEBCwUAA4ICAQC9CMefM+oBWmJg6FBD
1PJe13lhlGvzJW7LOgV7ZrmlTxgfidP8nODQGcMyTIeKxtvtzRWDAiMq0YxiPmVr
J5Zrs2IUxR7ikHT+Xn3+zLqpmMALMJQ4akHUioULKJ4L3/CI6JjgSyqAqukqvfSL
RhYLWV3Ja09RZdXbt0LJ2hT5DbqmzYiSz4P55pjVsEPuKSX+XPkZcYxYacrC0Qx9
RElF5QkyEA6SG/Rh/CvMT27YDMX9c9bdFFOMDHOEwxZkQaDyKd+6+3N8NepxBwTB
LafHEBgfPxC30Wg05Z5c/KreeJwfWpXId3RdA6sY4nkW/OhkwWoNT5Q12rSuLP0+
dYOqG9oxM5hLJul+nK1povKWCRWX49YFP/QzWaXQzPodn6+72FsIcOJU3ZP9sLDZ
8fbI/MsIsjwp3FCfdu8zIHgyNKGtajpUN7TrWaGP+5O8lDEQPLWqkSqgWMD4XQBR
GwTzHRb7S1U2nfOVwIxvujpP5THaYGoZPMtu1LS4/hHgVKqziGHJSaVcnJ4aeN5e
Tn6FMv2EqU1e2D1mMe4iptxdPBOJabf8go4+B1KdTxIBOGEIbeMXjogLkGTxdvK1
DGEXpj2rCWsAWHkDA341pOlNk9izTG+1LpyH2KdjlHXZr5RM1ItyAuC7LF283t02
xWuW+GaWIqlH+t4u0ATZ+EyAsA==
-----END CERTIFICATE-----
)EOF";

// ---- ADS1115 ----
constexpr uint8_t  ADS_ADDR = 0x48;
constexpr int      PIN_SDA  = 21;
constexpr int      PIN_SCL  = 22;
constexpr int      PIN_RDY  = 19;                 // ALERT/RDY del ADS1115
constexpr uint16_t ADS_MUX  = 0x4;               // 100 = A0 contra GND (0x0 = A0-A1 diferencial)
constexpr uint16_t ADS_PGA  = 0x1;               // +-4.096 V
constexpr float    ADS_LSB_V = 4.096f / 32768.0f;
constexpr int      FS_NOMINAL = 860;             // SPS configurados (el real lo da t_us)

// ---- Sensor de corriente: AJUSTA a tu sensor ----
constexpr float SENS_V_POR_A = 0.100f;           // sensibilidad en voltios por amperio

// ---- Ventana de forma de onda ----
constexpr int N_VENTANA = 128;                   // ~9 ciclos a 60 Hz
constexpr int N_CALIB   = 512;                   // muestras para medir el offset
// =============================================================================

// Registros ADS1115
constexpr uint8_t REG_CONV = 0x00, REG_CONFIG = 0x01, REG_LO = 0x02, REG_HI = 0x03;

WiFiClientSecure net;
PubSubClient mqtt(net);

QueueHandle_t colaRdy;                           // marcas de tiempo (us) tomadas en la interrupcion
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

volatile double   sumaCuad = 0;                  // para el RMS de 1 s
volatile uint32_t cuenta = 0;
volatile uint32_t muestrasPerdidas = 0;
volatile uint32_t errI2C = 0;


float    vA[N_VENTANA];                          // ventana: amperios
uint32_t vT[N_VENTANA];                          // ventana: micros() de cada muestra
volatile int  nV = 0;
volatile bool pedirVentana = false, capturando = false, ventanaLista = false;

float offsetV = 0;                               // nivel de reposo del sensor (V)

// ------------------------------------------------------------------ ADS1115
void adsEscribir(uint8_t reg, uint16_t val) {
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(reg);
  Wire.write((uint8_t)(val >> 8));
  Wire.write((uint8_t)(val & 0xFF));
  Wire.endTransmission();
}

/*int16_t adsLeer() {                              // el puntero ya apunta a REG_CONV
  Wire.requestFrom(ADS_ADDR, (uint8_t)2);
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  return (int16_t)((hi << 8) | lo);
}*/
bool adsLeer(int16_t &raw) {
  if (Wire.requestFrom(ADS_ADDR, (uint8_t)2) != 2) { errI2C++; return false; }
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  raw = (int16_t)((hi << 8) | lo);
  return true;
}

void adsIniciar() {
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  Wire.setTimeOut(20);   // no esperar 50 ms por cada lectura fallida
  // Pin ALERT/RDY como "conversion lista": Hi_thresh MSB=1, Lo_thresh MSB=0, COMP_QUE=00
  adsEscribir(REG_LO, 0x0000);
  adsEscribir(REG_HI, 0x8000);
  // OS=0 | MUX | PGA | MODE=0 (continuo) | DR=111 (860 SPS) | COMP_QUE=00
  uint16_t cfg = (ADS_MUX << 12) | (ADS_PGA << 9) | (0 << 8) | (0x7 << 5) | 0x0;
  adsEscribir(REG_CONFIG, cfg);
  // Dejar el puntero en el registro de conversion
  Wire.beginTransmission(ADS_ADDR);
  Wire.write(REG_CONV);
  Wire.endTransmission();
}
void recuperarADS() {
  Serial.println("I2C: reiniciando bus y ADS1115...");
  Wire.end();
  delay(5);
  adsIniciar();
}
void IRAM_ATTR isrRdy() {
  uint32_t ts = (uint32_t)esp_timer_get_time();  // instante real de la muestra
  BaseType_t w = pdFALSE;
  xQueueSendFromISR(colaRdy, &ts, &w);
  if (w) portYIELD_FROM_ISR();
}

/*bool calibrarOffset() {
  double suma = 0;
  int n = 0;
  uint32_t ts;
  for (int i = 0; i < N_CALIB + 20; i++) {
    if (xQueueReceive(colaRdy, &ts, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    int16_t raw = adsLeer();
    if (i < 20) continue;                        // descarta el transitorio inicial
    suma += raw;
    n++;
  }
  offsetV = (float)(suma / n) * ADS_LSB_V;
  return true;
}*/
bool calibrarOffset() {
  double suma = 0;
  int n = 0;
  uint32_t ts;
  int16_t raw;
  for (int i = 0; i < N_CALIB + 20; i++) {
    if (xQueueReceive(colaRdy, &ts, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    if (!adsLeer(raw)) return false;
    if (i < 20) continue;
    suma += raw;
    n++;
  }
  offsetV = (float)(suma / n) * ADS_LSB_V;
  return true;
}

// Tarea de muestreo (nucleo 1, prioridad alta): una muestra por cada pulso RDY
/*void tareaMuestreo(void*) {
  uint32_t ts, ts2;
  for (;;) {
    if (xQueueReceive(colaRdy, &ts, portMAX_DELAY) != pdTRUE) continue;
    // Si nos atrasamos, la lectura corresponde a la conversion mas reciente: usar su marca
    while (xQueueReceive(colaRdy, &ts2, 0) == pdTRUE) { ts = ts2; muestrasPerdidas++; }

    float amps = ((float)adsLeer() * ADS_LSB_V - offsetV) / SENS_V_POR_A;

    portENTER_CRITICAL(&mux);
    sumaCuad += (double)amps * amps;
    cuenta++;
    portEXIT_CRITICAL(&mux);

    if (pedirVentana && !capturando && !ventanaLista) {
      capturando = true;
      nV = 0;
      pedirVentana = false;
    }
    if (capturando) {
      vA[nV] = amps;
      vT[nV] = ts;
      if (++nV >= N_VENTANA) {
        capturando = false;
        ventanaLista = true;
      }
    }
  }
}*/
void tareaMuestreo(void*) {
  uint32_t ts, ts2;
  uint8_t fallos = 0;
  for (;;) {
    if (xQueueReceive(colaRdy, &ts, pdMS_TO_TICKS(500)) != pdTRUE) {
      Serial.println("Sin pulsos RDY en 500 ms");
      recuperarADS();
      xQueueReset(colaRdy);
      continue;
    }
    while (xQueueReceive(colaRdy, &ts2, 0) == pdTRUE) { ts = ts2; muestrasPerdidas++; }

    int16_t raw;
    if (!adsLeer(raw)) {
      if (++fallos >= 5) { fallos = 0; recuperarADS(); xQueueReset(colaRdy); }
      continue;
    }
    fallos = 0;
    float amps = ((float)raw * ADS_LSB_V - offsetV) / SENS_V_POR_A;

    portENTER_CRITICAL(&mux);
    sumaCuad += (double)amps * amps;
    cuenta++;
    portEXIT_CRITICAL(&mux);

    if (pedirVentana && !capturando && !ventanaLista) {
      capturando = true;
      nV = 0;
      pedirVentana = false;
    }
    if (capturando) {
      vA[nV] = amps;
      vT[nV] = ts;
      if (++nV >= N_VENTANA) {
        capturando = false;
        ventanaLista = true;
      }
    }
  }
}

// ------------------------------------------------------------ Red, hora, MQTT
void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
}
/*void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(200);

  Serial.println("Redes que ve la ESP32 (solo 2.4 GHz):");
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++)
    Serial.printf("  %s | canal %d | %d dBm\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));

  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t0 > 20000) {
      Serial.printf("\nNo conecta, status=%d. Reintentando...\n", WiFi.status());
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      t0 = millis();
    }
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
}*/

void sincronizarHora() {
  configTime(GMT_OFFSET_S, 0, NTP_1, NTP_2);
  Serial.print("NTP");
  uint32_t t0 = millis();
  while (time(nullptr) < EPOCH_MIN) {
    if (millis() - t0 > 30000) {
      Serial.println("\nSin hora NTP: sin ella el TLS falla. Reiniciando...");
      delay(1000);
      ESP.restart();
    }
    delay(300);
    Serial.print(".");
  }
  Serial.printf("\nHora OK (epoch %ld)\n", (long)time(nullptr));
}

void asegurarMQTT() {
  static uint32_t ultimoIntento = 0;
  if (mqtt.connected()) return;
  if (millis() - ultimoIntento < 3000 && ultimoIntento != 0) return;
  ultimoIntento = millis();
  Serial.print("MQTT TLS... ");
  if (mqtt.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASS)) {
    Serial.println("conectado");
  } else {
    char err[100] = {0};
    net.lastError(err, sizeof(err));
    Serial.printf("fallo rc=%d | TLS: %s\n", mqtt.state(), err);
  }
}

// ---------------------------------------------------------------- Publicacion
void publicarRms() {
  double suma;
  uint32_t c;
  portENTER_CRITICAL(&mux);
  suma = sumaCuad; c = cuenta;
  sumaCuad = 0; cuenta = 0;
  portEXIT_CRITICAL(&mux);
  Serial.printf("[estado] mqtt=%d muestras/s=%u i2cErr=%u perdidas=%u heap=%u\n",
              mqtt.connected(), c, errI2C, muestrasPerdidas, ESP.getFreeHeap());
  if (c < 100) return;                           // muy pocas muestras: no publicar

  float rms = (float)sqrt(suma / c);             // RMS sobre ~1 s de muestras continuas
  if (!(rms >= 0.0f && rms <= 1000.0f)) return;  // el backend descarta fuera de rango

  char buf[48];
  snprintf(buf, sizeof(buf), "{\"rms\": %.2f}", rms);
  bool ok = mqtt.publish(TOPIC_RMS, buf);
  Serial.printf("RMS %.2f A | muestras %u | perdidas %u | publish %s\n",
                rms, c, muestrasPerdidas, ok ? "ok" : "FALLO");
}

void publicarVentana() {
  static char json[4096];
  int n = snprintf(json, sizeof(json), "{\"fs\":%d,\"samples\":[", FS_NOMINAL);
  for (int i = 0; i < N_VENTANA && n < (int)sizeof(json) - 16; i++)
    n += snprintf(json + n, sizeof(json) - n, i ? ",%.3f" : "%.3f", vA[i]);
  n += snprintf(json + n, sizeof(json) - n, "],\"t_us\":[");

  uint32_t prev = 0;
  for (int i = 0; i < N_VENTANA && n < (int)sizeof(json) - 16; i++) {
    uint32_t t = vT[i] - vT[0];                  // relativo al primer dato (tolera el desbordamiento)
    if (i > 0 && t <= prev) t = prev + 1;        // estrictamente creciente
    prev = t;
    n += snprintf(json + n, sizeof(json) - n, i ? ",%u" : "%u", t);
  }
  n += snprintf(json + n, sizeof(json) - n, "]}");

  if (n >= (int)sizeof(json)) { Serial.println("Ventana demasiado grande, descartada"); return; }
  bool ok = mqtt.publish(TOPIC_WAVE, (const uint8_t*)json, n);
  if (!ok) Serial.printf("Waveform: publish FALLO (%d bytes)\n", n);
}

// ------------------------------------------------------------------ Arduino
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n== AmpereWatch ESP32 ==");

  colaRdy = xQueueCreate(16, sizeof(uint32_t));
  adsIniciar();
  pinMode(PIN_RDY, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_RDY), isrRdy, FALLING);

  Serial.println("Midiendo offset del sensor (motor SIN corriente)...");
  if (!calibrarOffset()) {
    Serial.println("No llegan pulsos RDY del ADS1115. Revisa ALERT/RDY->GPIO4, pull-up y direccion I2C.");
    delay(3000);
    ESP.restart();
  }
  Serial.printf("Offset = %.4f V\n", offsetV);
  xTaskCreatePinnedToCore(tareaMuestreo, "muestreo", 4096, nullptr, 3, nullptr, 1);

  conectarWiFi();
  sincronizarHora();

  net.setCACert(CA_CERT);                        // valida el broker con la CA de AmpereWatch
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(6144);                      // la ventana waveform ocupa ~2.5 KB
  mqtt.setKeepAlive(30);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) { delay(500); return; }
  asegurarMQTT();
  mqtt.loop();
  if (!mqtt.connected()) return;

  static uint32_t tUltimo = 0;
  if (millis() - tUltimo >= 1000) {
    tUltimo = millis();
    publicarRms();
    pedirVentana = true;                         // la tarea captura una ventana nueva
  }
  if (ventanaLista) {
    publicarVentana();
    ventanaLista = false;
  }
}
