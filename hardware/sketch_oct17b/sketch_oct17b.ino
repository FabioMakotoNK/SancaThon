#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Ultrasonic.h>
#include <WiFiClient.h>
#include <time.h>
#include <cstring>

#include "secrets.h"
#include "sensor_pipeline.h"

// Preserve the working HC-SR04 reader and wiring from the pulled sketch.
// Level-shift ECHO to 3.3 V before connecting it to the ESP32.
constexpr uint8_t TRIG_PIN = 4;
constexpr uint8_t ECHO_PIN = 5;
constexpr unsigned long ECHO_TIMEOUT_US = 30000UL;
constexpr unsigned long SAMPLE_INTERVAL_MS = 500UL;
constexpr unsigned long WIFI_WAIT_MS = 12000UL;
constexpr float REFERENCE_DISTANCE_CM = 75.0f;
constexpr int HTTP_ATTEMPTS = 3;
constexpr int HTTP_TIMEOUT_MS = 5000;

Ultrasonic sensor(TRIG_PIN, ECHO_PIN, ECHO_TIMEOUT_US);
ciclorota::MeasurementPipeline pipeline;
bool configurationReady = false;
bool wifiWasConnected = false;
unsigned long lastWifiReport = 0;
unsigned long lastMeasurement = 0;

bool isSafeIdentifier(const char* value, size_t maxLength) {
  const size_t length = strlen(value);
  if (length == 0 || length > maxLength) return false;
  for (size_t i = 0; i < length; ++i) {
    const char c = value[i];
    const bool allowed = (c >= 97 && c <= 122) || (c >= 65 && c <= 90) ||
                         (c >= 48 && c <= 57) || c == 95 || c == 45 || c == 46;
    if (!allowed) return false;
  }
  return true;
}

bool configurationIsReady() {
  const bool configured = strcmp(CICLOROTA_WIFI_SSID, "replace-with-wifi-name") != 0 &&
      strcmp(CICLOROTA_WIFI_PASSWORD, "replace-with-wifi-password") != 0 &&
      strcmp(CICLOROTA_ENDPOINT, "http://192.168.1.10:8000/api/measurements") != 0;
  if (!configured) {
    Serial0.println("Set Wi-Fi and CICLOROTA_ENDPOINT in secrets.h before uploading");
    return false;
  }
  if (!isSafeIdentifier(CICLOROTA_DUMPSTER_ID, 64) ||
      !isSafeIdentifier(CICLOROTA_DEVICE_ID, 60)) {
    Serial0.println("IDs may contain letters, digits, dot, underscore or hyphen only");
    return false;
  }
  return true;
}

bool ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial0.println("Wi-Fi disconnected; reconnecting");
  WiFi.disconnect();
  WiFi.begin(CICLOROTA_WIFI_SSID, CICLOROTA_WIFI_PASSWORD);
  const unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < WIFI_WAIT_MS) {
    delay(250);
    Serial0.print(".");
  }
  Serial0.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial0.println("Wi-Fi reconnect timed out; next reading will retry");
    return false;
  }
  Serial0.print("Wi-Fi connected. ESP32 IP: ");
  Serial0.println(WiFi.localIP());
  return true;
}

bool timestampUtc(char* output, size_t outputSize) {
  const time_t now = time(nullptr);
  if (now < 1700000000) return false;
  struct tm utc {};
  gmtime_r(&now, &utc);
  return strftime(output, outputSize, "%Y-%m-%dT%H:%M:%SZ", &utc) > 0;
}

void makeMeasurementId(char* output, size_t outputSize) {
  snprintf(output, outputSize, "%s-%08lx%08lx", CICLOROTA_DEVICE_ID,
           static_cast<unsigned long>(esp_random()),
           static_cast<unsigned long>(esp_random()));
}

bool postMeasurement(const char* measurementId, float rawCm, float filteredCm,
                     const char* measuredAt) {
  if (!ensureWifi()) return false;
  char payload[512];
  const int payloadLength = snprintf(
      payload, sizeof(payload),
      "{\"measurement_id\":\"%s\",\"dumpster_id\":\"%s\","
      "\"device_id\":\"%s\",\"raw_distance_cm\":%.2f,"
      "\"distance_cm\":%.2f,\"measured_at\":\"%s\"}",
      measurementId, CICLOROTA_DUMPSTER_ID, CICLOROTA_DEVICE_ID,
      rawCm, filteredCm, measuredAt);
  if (payloadLength <= 0 || static_cast<size_t>(payloadLength) >= sizeof(payload)) {
    Serial0.println("Measurement payload exceeded its buffer; upload skipped");
    return false;
  }

  for (int attempt = 1; attempt <= HTTP_ATTEMPTS; ++attempt) {
    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    WiFiClient client;
    if (!http.begin(client, CICLOROTA_ENDPOINT)) {
      Serial0.println("HTTP client initialization failed; check CICLOROTA_ENDPOINT");
      return false;
    }
    http.addHeader("Content-Type", "application/json");
    const int status = http.POST(reinterpret_cast<uint8_t*>(payload), payloadLength);
    const String response = status > 0 ? http.getString() : String();
    http.end();
    if (status >= 200 && status < 300) {
      Serial0.printf("Measurement accepted: HTTP %d, %s\n", status, response.c_str());
      return true;
    }
    Serial0.printf("Measurement upload failed: HTTP %d, attempt %d/%d\n",
                    status, attempt, HTTP_ATTEMPTS);
    const bool transient = status < 0 || status >= 500 || status == 408 || status == 429;
    if (!transient || attempt == HTTP_ATTEMPTS) {
      if (response.length()) Serial0.println(response);
      return false;
    }
    delay(500 * attempt);
  }
  return false;
}

void sampleAndUpload() {
  // Keep the pulled Ultrasonic.read(CM) acquisition path intact.
  const unsigned int rawCm = sensor.read(CM);
  if (rawCm < ciclorota::MeasurementPipeline::kMinDistanceCm ||
      rawCm > ciclorota::MeasurementPipeline::kMaxDistanceCm) {
    Serial0.println("No valid echo; check power, GND, TRIG=4, ECHO=5 and ECHO voltage");
    return;
  }

  float filteredCm = 0.0f;
  bool discontinuityReset = false;
  if (!pipeline.update(static_cast<float>(rawCm), filteredCm, discontinuityReset)) {
    Serial0.printf("Distance rejected or awaiting step confirmation: %u cm\n", rawCm);
    return;
  }
  if (discontinuityReset) Serial0.println("Persistent step confirmed; Kalman estimate reset");

  // The original distance ratio is diagnostic only; it is not fill percent.
  const float distanceRatio = filteredCm / REFERENCE_DISTANCE_CM;
  Serial0.printf("Raw cm: %u | Kalman filtered cm: %.2f | Distance ratio: %.4f\n",
                 rawCm, filteredCm, distanceRatio);

  char measuredAt[32];
  if (!timestampUtc(measuredAt, sizeof(measuredAt))) {
    Serial0.println("NTP time not synchronized; measurement upload skipped");
    return;
  }
  char measurementId[80];
  makeMeasurementId(measurementId, sizeof(measurementId));
  postMeasurement(measurementId, static_cast<float>(rawCm), filteredCm, measuredAt);
}

void setup() {
  Serial0.begin(115200);
  delay(1000);
  Serial0.println("HC-SR04: TRIG=GPIO4, ECHO=GPIO5");
  Serial0.println("POST /api/measurements JSON: distance fields in centimeters");
  configurationReady = configurationIsReady();
  if (!configurationReady) return;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  WiFi.begin(CICLOROTA_WIFI_SSID, CICLOROTA_WIFI_PASSWORD);
}

void loop() {
  if (!configurationReady) {
    delay(1000);
    return;
  }
  const unsigned long now = millis();
  const bool wifiConnected = WiFi.status() == WL_CONNECTED;
  if (wifiConnected != wifiWasConnected || now - lastWifiReport >= 10000UL) {
    lastWifiReport = now;
    if (wifiConnected) {
      Serial0.print("Wi-Fi connected. ESP32 IP: ");
      Serial0.println(WiFi.localIP());
    } else {
      Serial0.print("Wi-Fi unavailable. Status: ");
      Serial0.println(static_cast<int>(WiFi.status()));
    }
  }
  wifiWasConnected = wifiConnected;

  if (now - lastMeasurement >= SAMPLE_INTERVAL_MS) {
    lastMeasurement = now;
    sampleAndUpload();
  }
  delay(1);
}
