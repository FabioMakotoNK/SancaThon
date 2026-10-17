#include <Arduino.h>
#include <WiFi.h>
#include <Ultrasonic.h>
#include <NetworkClient.h>

const char *ssid = "YOUR_WIFI_NAME";
const char *password = "YOUR_WIFI_PASSWORD";
// This computer's current Wi-Fi IPv4 address. Update if it changes.
const char* serverIP = "10.253.177.32";
const uint16_t serverPort = 5000;

constexpr uint8_t TRIG_PIN = 4;
constexpr uint8_t ECHO_PIN = 5;
constexpr unsigned long ECHO_TIMEOUT_US = 30000UL;
constexpr unsigned long TCP_RETRY_MS = 5000UL;
constexpr float REFERENCE_DISTANCE_CM = 75.0f;
constexpr float FILTER_GAIN = 0.5f;

Ultrasonic sensor(TRIG_PIN, ECHO_PIN, ECHO_TIMEOUT_US);
NetworkClient client;

bool wifiWasConnected = false;
bool tcpWasConnected = false;
bool filterInitialized = false;
bool tcpAttempted = false;
unsigned long lastWifiReport = 0;
unsigned long lastMeasurement = 0;
unsigned long lastTcpAttempt = 0;
float filteredDistanceCm = 0;

void setup() {
  Serial0.begin(115200);
  delay(1000);
  Serial0.println("HC-SR04: TRIG=GPIO4, ECHO=GPIO5");
  Serial0.println("TCP CSV fields: distance_ratio,filtered_cm,raw_cm");
  Serial0.print("TCP server: ");
  Serial0.print(serverIP);
  Serial0.print(":");
  Serial0.println(serverPort);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid, password);
}

void loop() {
  unsigned long now = millis();
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

  if (!wifiConnected) {
    client.stop();
    tcpAttempted = false;
  } else if (!client.connected() &&
             (!tcpAttempted || now - lastTcpAttempt >= TCP_RETRY_MS)) {
    client.stop();
    tcpAttempted = true;
    Serial0.println("Connecting to Python TCP server...");
    // Each attempt can block for up to 1 second; sensor readings resume afterward.
    if (client.connect(serverIP, serverPort, 1000)) {
      Serial0.println("TCP connected");
    } else {
      Serial0.println("TCP failed: check server IP, port 5000 and firewall");
    }
    lastTcpAttempt = millis();
  }
  wifiWasConnected = wifiConnected;

  const bool tcpConnected = wifiConnected && client.connected();
  if (tcpWasConnected && !tcpConnected) {
    Serial0.println("TCP disconnected; will retry");
  }
  tcpWasConnected = tcpConnected;

  // Drain optional server replies to avoid filling the receive buffer.
  for (unsigned int i = 0; i < 128 && client.available(); ++i) {
    Serial0.write(client.read());
  }

  now = millis();
  if (now - lastMeasurement >= 500UL) {
    lastMeasurement = now;
    const unsigned int distanceCm = sensor.read(CM);
    // Reject zero readings and out-of-range/stuck-HIGH timeout readings.
    if (distanceCm < 2 || distanceCm > 400) {
      Serial0.println("No valid echo: check power, GND, TRIG=4, ECHO=5 and ECHO voltage");
    } else {
      if (!filterInitialized) {
        filteredDistanceCm = distanceCm;
        filterInitialized = true;
      } else {
        filteredDistanceCm += FILTER_GAIN * (distanceCm - filteredDistanceCm);
      }
      // Preserves the original distance / 75 calculation; this is not fill percent.
      const float distanceRatio = filteredDistanceCm / REFERENCE_DISTANCE_CM;
      Serial0.print("Raw cm: ");
      Serial0.print(distanceCm);
      Serial0.print(" | Filtered cm: ");
      Serial0.print(filteredDistanceCm, 2);
      Serial0.print(" | Distance ratio: ");
      Serial0.println(distanceRatio, 4);

      if (wifiConnected && client.connected()) {
        char message[96];
        const int length = snprintf(message, sizeof(message), "%.4f,%.2f,%u\n",
                                    distanceRatio, filteredDistanceCm, distanceCm);
        if (length > 0 && static_cast<size_t>(length) < sizeof(message)) {
          const size_t sent = client.write(reinterpret_cast<const uint8_t*>(message), length);
          if (sent != static_cast<size_t>(length)) {
            Serial0.println("TCP write incomplete; reconnecting on next retry");
            client.stop();
          }
        }
      }
    }
  }
  delay(1);
}