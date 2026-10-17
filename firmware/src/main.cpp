#include <Arduino.h>
#include <cstring>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <time.h>

#include "secrets.h"
#include "sensor_pipeline.h"

#ifndef HC_SR04_TRIG_PIN
#define HC_SR04_TRIG_PIN 4
#endif
#ifndef HC_SR04_ECHO_PIN
#define HC_SR04_ECHO_PIN 5
#endif
#ifndef MEASUREMENT_INTERVAL_MS
#define MEASUREMENT_INTERVAL_MS 60000UL
#endif

static constexpr uint32_t kEchoTimeoutUs = 30000UL;
static constexpr int kBurstSamples = 5;
static constexpr int kHttpAttempts = 3;
static constexpr int kWifiWaitMs = 12000;
static constexpr int kReadIntervalMs = 70;

ciclorota::MeasurementPipeline pipeline;
unsigned long lastMeasurementMs = 0;

float measureDistanceCm() {
  digitalWrite(HC_SR04_TRIG_PIN, LOW);
  delayMicroseconds(3);
  digitalWrite(HC_SR04_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(HC_SR04_TRIG_PIN, LOW);
  const unsigned long echo_us = pulseIn(HC_SR04_ECHO_PIN, HIGH, kEchoTimeoutUs);
  if (echo_us == 0) return -1.0f;
  return static_cast<float>(echo_us) / 58.0f;
}

bool ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial.println("Wi-Fi disconnected; reconnecting");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < kWifiWaitMs) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi reconnect timed out; measurement will be retried next interval");
    return false;
  }
  Serial.print("Wi-Fi connected, IP ");
  Serial.println(WiFi.localIP());
  return true;
}

bool timestampUtc(char* output, size_t output_size) {
  const time_t now = time(nullptr);
  if (now < 1700000000) return false;
  struct tm utc {};
  gmtime_r(&now, &utc);
  return strftime(output, output_size, "%Y-%m-%dT%H:%M:%SZ", &utc) > 0;
}

String makeMeasurementId() {
  char id[40];
  snprintf(id, sizeof(id), "%s-%08lx%08lx", DEVICE_ID,
           static_cast<unsigned long>(esp_random()),
           static_cast<unsigned long>(esp_random()));
  return String(id);
}

bool postMeasurement(float raw_cm, float filtered_cm) {
  if (!ensureWifi()) return false;
  char measured_at[32];
  if (!timestampUtc(measured_at, sizeof(measured_at))) {
    Serial.println("NTP time not synchronized; skipping timestamped upload");
    return false;
  }
  const String measurement_id = makeMeasurementId();
  char payload[512];
  snprintf(payload, sizeof(payload),
           "{\"measurement_id\":\"%s\",\"dumpster_id\":\"%s\","
           "\"device_id\":\"%s\",\"raw_distance_cm\":%.2f,"
           "\"distance_cm\":%.2f,\"measured_at\":\"%s\"}",
           measurement_id.c_str(), DUMPSTER_ID, DEVICE_ID, raw_cm, filtered_cm,
           measured_at);

  for (int attempt = 1; attempt <= kHttpAttempts; ++attempt) {
    HTTPClient http;
    http.setTimeout(5000);
    WiFiClient client;
    if (!http.begin(client, CICLOROTA_ENDPOINT)) {
      Serial.println("HTTP client initialization failed");
      return false;
    }
    http.addHeader("Content-Type", "application/json");
    const int status = http.POST(reinterpret_cast<uint8_t*>(payload), strlen(payload));
    const String response = status > 0 ? http.getString() : String();
    http.end();
    if (status >= 200 && status < 300) {
      Serial.printf("Measurement accepted: HTTP %d, %s\n", status, response.c_str());
      return true;
    }
    Serial.printf("Measurement upload failed: HTTP %d, attempt %d/%d\n",
                  status, attempt, kHttpAttempts);
    if (attempt < kHttpAttempts) delay(500 * attempt);
  }
  return false;
}

void sampleAndUpload() {
  bool accepted = false;
  float last_raw_cm = -1.0f;
  float last_filtered_cm = -1.0f;
  bool reset = false;
  for (int i = 0; i < kBurstSamples; ++i) {
    const float raw_cm = measureDistanceCm();
    if (raw_cm < 0.0f) {
      Serial.println("HC-SR04 timeout/no echo; reading rejected");
    } else {
      float filtered_cm = 0.0f;
      if (pipeline.update(raw_cm, filtered_cm, reset)) {
        last_raw_cm = raw_cm;
        last_filtered_cm = filtered_cm;
        accepted = true;
        if (reset) Serial.println("Persistent distance step confirmed; Kalman estimate reset");
      } else {
        Serial.printf("Distance reading rejected or awaiting step confirmation: %.2f cm\n", raw_cm);
      }
    }
    delay(kReadIntervalMs);
  }
  if (!accepted) {
    Serial.println("No valid filtered sample in burst; nothing uploaded");
    return;
  }
  const float fill = ciclorota::MeasurementPipeline::fillPercent(
      last_filtered_cm, EMPTY_DISTANCE_CM, FULL_DISTANCE_CM);
  if (fill < 0.0f) {
    Serial.println("Invalid dumpster calibration; refusing to upload");
    return;
  }
  Serial.printf("Raw %.2f cm, filtered %.2f cm, estimated fill %.1f%%\n",
                last_raw_cm, last_filtered_cm, fill);
  postMeasurement(last_raw_cm, last_filtered_cm);
}

void setup() {
  Serial.begin(115200);
  pinMode(HC_SR04_TRIG_PIN, OUTPUT);
  pinMode(HC_SR04_ECHO_PIN, INPUT);
  digitalWrite(HC_SR04_TRIG_PIN, LOW);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  ensureWifi();
  Serial.printf("CicloRota device %s for dumpster %s\n", DEVICE_ID, DUMPSTER_ID);
}

void loop() {
  const unsigned long now = millis();
  if (lastMeasurementMs == 0 || now - lastMeasurementMs >= MEASUREMENT_INTERVAL_MS) {
    lastMeasurementMs = now;
    sampleAndUpload();
  }
  delay(100);
}
