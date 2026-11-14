/*
 * 🌊 ایستگاه پایش تراز آب — بندر نوشهر
 * ESP32 + سنسور اولتراسونیک ضدآب JSN-SR04T + سنسور دما DS18B20
 *
 * سازوکار:
 *   سنسور فاصله خود تا سطح آب را می‌سنجد (mm)
 *   با دمای هوا تصحیح می‌کند (سرعت صوت وابسته به دماست)
 *   هر READ_INTERVAL ثانیه بسته JSON روی UDP می‌فرستد:
 *   {"id":"STN-NOSHR-1","dist_mm":3000.0,"temp_c":18.2}
 *
 * سیم‌کشی:
 *   JSN-SR04T:  VCC→5V( Vin )  GND→GND  TRIG→GPIO5  ECHO→GPIO18
 *   ⚠️ خروجی ECHO سنسور 5V است — با مقسم مقاومتی به ESP32 بدهید:
 *      ECHO ──[1kΩ]──●── GPIO18
 *                    │
 *                 [2kΩ]
 *                    │
 *                   GND
 *   DS18B20:  VCC→3.3V  GND→GND  DATA→GPIO4 (+ مقاومت 4.7kΩ بین DATA و 3.3V)
 *
 * کتابخانه‌های لازم (Arduino IDE → Library Manager):
 *   OneWire ، DallasTemperature
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ─────────────── تنظیمات (این‌ها را پر کنید) ───────────────
const char* WIFI_SSID   = "YOUR-WIFI-NAME";
const char* WIFI_PASS   = "YOUR-WIFI-PASSWORD";
const char* SERVER_IP   = "192.168.1.10";   // آی‌پی دستگاهی که ربات رویش اجراست
const uint16_t SERVER_PORT = 10111;
const char* DEVICE_ID   = "STN-NOSHR-1";
// ارتفاع سطح سنسور از مبنای هیدروگرافی (mm) — بعد از نقشه‌برداری تنظیم شود
const float DATUM_MM    = 5000.0;
const unsigned long READ_INTERVAL_MS = 5UL * 60UL * 1000UL;  // هر ۵ دقیقه

// ─────────────── پین‌ها ───────────────
#define TRIG_PIN 5
#define ECHO_PIN 18
#define TEMP_PIN 4

OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);
WiFiUDP udp;

float readDistanceMM() {
  // میانهٔ ۱۵ نمونه — مقاوم به نویز و قطرات
  const int N = 15;
  float v[N];
  for (int i = 0; i < N; i++) {
    digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(4);
    digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(20);
    digitalWrite(TRIG_PIN, LOW);
    unsigned long us = pulseIn(ECHO_PIN, HIGH, 30000UL);  // حداکثر ~۵ متر
    v[i] = (us == 0) ? NAN : (us / 2.0f) * 0.343f;        // mm (سرعت فرضی ۳۴۳ m/s)
    delay(60);
  }
  // میانه از نمونه‌های معتبر
  float valid[N]; int n = 0;
  for (int i = 0; i < N; i++) if (!isnan(v[i])) valid[n++] = v[i];
  if (n < N / 2) return NAN;               // بیش از نصف نمونه‌ها خراب → بده
  for (int i = 1; i < n; i++) {            // insertion sort
    float k = valid[i]; int j = i - 1;
    while (j >= 0 && valid[j] > k) { valid[j + 1] = valid[j]; j--; }
    valid[j + 1] = k;
  }
  return valid[n / 2];
}

float readAirTempC() {
  tempSensor.requestTemperatures();
  float t = tempSensor.getTempCByIndex(0);
  return (t > -50 && t < 80) ? t : NAN;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT); digitalWrite(TRIG_PIN, LOW);
  tempSensor.begin();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected ✅" : " FAILED ❌");
}

void loop() {
  static unsigned long last = 0;
  if (millis() - last < READ_INTERVAL_MS) { delay(1000); return; }
  last = millis();

  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); delay(2000); }

  float distRaw = readDistanceMM();
  float tempC   = readAirTempC();

  if (isnan(distRaw)) {
    Serial.println("سنسور فاصله پاسخ نداد — چک سیم‌کشی/مانع");
    return;
  }

  // تصحیح سرعت صوت با دمای هوا: v = 331.3 + 0.606*T  (m/s)
  float distMM = distRaw;
  if (!isnan(tempC)) {
    float v = 331.3f + 0.606f * tempC;
    distMM = distRaw * (v / 343.0f);
  }

  // JSON دستی — بدون کتابخانه اضافه
  char pkt[200];
  if (isnan(tempC))
    snprintf(pkt, sizeof(pkt), "{\"id\":\"%s\",\"dist_mm\":%.1f,\"datum_mm\":%.1f}",
             DEVICE_ID, distMM, DATUM_MM);
  else
    snprintf(pkt, sizeof(pkt),
             "{\"id\":\"%s\",\"dist_mm\":%.1f,\"temp_c\":%.1f,\"datum_mm\":%.1f}",
             DEVICE_ID, distMM, tempC, DATUM_MM);

  udp.beginPacket(SERVER_IP, SERVER_PORT);
  udp.write((const uint8_t*)pkt, strlen(pkt));
  udp.endPacket();

  float level = DATUM_MM - distMM;
  Serial.printf("dist=%.1fmm temp=%.1fC level=%.1fmm → %s:%u  [%s]\n",
                distMM, tempC, level, SERVER_IP, SERVER_PORT, pkt);
}
