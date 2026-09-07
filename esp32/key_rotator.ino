/*
 * =========================================================================================
 * ESP32 AWS IoT Core & KMS Key Rotation Button
 * =========================================================================================
 * Description:
 *   ESP32 firmware that connects to AWS IoT Core over TLS using X.509 certificates,
 *   listens for a physical push button press on GPIO 0, publishes a rotation request,
 *   receives the updated key version from AWS Lambda, and displays live status on an OLED.
 *
 * Hardware:
 *   - ESP32 NodeMCU / DevKit V1
 *   - Push Button: GPIO 0 (or GPIO 4 with internal pull-up)
 *   - SSD1306 0.96" I2C OLED Display (SDA: GPIO 21, SCL: GPIO 22)
 *
 * Libraries required (Install via Arduino Library Manager):
 *   1. PubSubClient by Nick O'Leary
 *   2. ArduinoJson by Benoit Blanchon (v6 or v7)
 *   3. Adafruit SSD1306 and Adafruit GFX Library
 * =========================================================================================
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "secrets.h"

// OLED Display Configuration
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SCREEN_ADDRESS 0x3C

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// Hardware Pin Configuration
#define BUTTON_PIN 0          // Boot button on most ESP32 boards (active LOW)
#define DEBOUNCE_DELAY_MS 350 // Button debounce time

// MQTT Topics
const char* AWS_IOT_REQUEST_TOPIC = "esp32/key_rotation/request";
const char* AWS_IOT_RESPONSE_TOPIC = "esp32/key_rotation/response";

// WiFi and MQTT Clients
WiFiClientSecure netClient;
PubSubClient mqttClient(netClient);

// State tracking
enum DeviceState {
  STATE_IDLE,
  STATE_ROTATING,
  STATE_SUCCESS,
  STATE_FAILURE
};

DeviceState currentState = STATE_IDLE;
unsigned long lastButtonPress = 0;
unsigned long stateChangeTime = 0;
String lastKeyVersion = "01";
String lastErrorMessage = "";

// -----------------------------------------------------------------------------
// OLED Display Helpers
// -----------------------------------------------------------------------------
void drawOledHeader() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(F("  KEY ROTATOR"));
  display.println(F("---------------------"));
}

void showOledIdle() {
  drawOledHeader();
  display.setCursor(0, 22);
  display.setTextSize(1);
  display.println(F("STATUS: READY"));
  display.setCursor(0, 36);
  display.setTextSize(2);
  display.println(F("PRESS BTN"));
  display.setTextSize(1);
  display.setCursor(0, 56);
  display.print(F("Current Ver: v"));
  display.println(lastKeyVersion);
  display.display();
}

void showOledRotating() {
  drawOledHeader();
  display.setCursor(0, 22);
  display.setTextSize(1);
  display.println(F("STATUS: IN PROGRESS"));
  display.setCursor(0, 36);
  display.setTextSize(2);
  display.println(F("ROTATING."));
  display.setTextSize(1);
  display.setCursor(0, 56);
  display.println(F("PLEASE WAIT..."));
  display.display();
}

void showOledSuccess(String versionStr) {
  drawOledHeader();
  display.setCursor(0, 20);
  display.setTextSize(1);
  display.println(F("AWS KMS ROTATED OK"));
  display.setCursor(0, 34);
  display.setTextSize(2);
  display.print(F("VER: "));
  display.println(versionStr);
  display.setTextSize(1);
  display.setCursor(0, 54);
  display.println(F("KEY UPDATED!"));
  display.display();
}

void showOledFailure(String reason) {
  drawOledHeader();
  display.setCursor(0, 20);
  display.setTextSize(1);
  display.println(F("ROTATION FAILED"));
  display.setCursor(0, 34);
  display.setTextSize(1);
  display.println(reason);
  display.setCursor(0, 52);
  display.println(F("PRESS TO RETRY"));
  display.display();
}

// -----------------------------------------------------------------------------
// MQTT Message Callback (Incoming Response from AWS Lambda)
// -----------------------------------------------------------------------------
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Message arrived on topic: ");
  Serial.println(topic);

  // Parse JSON response
  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, payload, length);

  if (error) {
    Serial.print(F("JSON Deserialization failed: "));
    Serial.println(error.f_str());
    currentState = STATE_FAILURE;
    lastErrorMessage = "JSON ERROR";
    showOledFailure("PARSE ERROR");
    stateChangeTime = millis();
    return;
  }

  const char* status = doc["status"];
  const char* versionDisplay = doc["version_display"] | "02";
  const char* message = doc["message"] | "";

  Serial.print("Status: ");
  Serial.println(status);

  if (status && strcmp(status, "SUCCESS") == 0) {
    currentState = STATE_SUCCESS;
    lastKeyVersion = String(versionDisplay);
    showOledSuccess(lastKeyVersion);
    stateChangeTime = millis();
  } else {
    currentState = STATE_FAILURE;
    const char* errCode = doc["error_code"] | "FAILED";
    lastErrorMessage = String(errCode);
    showOledFailure(lastErrorMessage);
    stateChangeTime = millis();
  }
}

// -----------------------------------------------------------------------------
// Connect to Wi-Fi
// -----------------------------------------------------------------------------
void connectWiFi() {
  Serial.print("Connecting to Wi-Fi: ");
  Serial.println(WIFI_SSID);

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 10);
  display.println(F("CONNECTING WIFI..."));
  display.setCursor(0, 26);
  display.println(WIFI_SSID);
  display.display();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi connected! IP address: ");
  Serial.println(WiFi.localIP());
}

// -----------------------------------------------------------------------------
// Connect to AWS IoT Core (MQTT over TLS with X.509 Certificates)
// -----------------------------------------------------------------------------
void connectAWS() {
  // Configure TLS certificates from secrets.h
  netClient.setCACert(AWS_CERT_CA);
  netClient.setCertificate(AWS_CERT_CRT);
  netClient.setPrivateKey(AWS_CERT_PRIVATE);

  mqttClient.setServer(AWS_IOT_ENDPOINT, 8883);
  mqttClient.setCallback(mqttCallback);

  Serial.println("Connecting to AWS IoT Core...");

  while (!mqttClient.connected()) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 10);
    display.println(F("AWS IOT CONNECTING"));
    display.setCursor(0, 28);
    display.println(F("TLS 1.3 Handshake..."));
    display.display();

    if (mqttClient.connect(AWS_DEVICE_ID)) {
      Serial.println("Connected to AWS IoT Core!");
      // Subscribe to the response topic
      mqttClient.subscribe(AWS_IOT_RESPONSE_TOPIC);
      Serial.print("Subscribed to: ");
      Serial.println(AWS_IOT_RESPONSE_TOPIC);
      showOledIdle();
    } else {
      Serial.print("Failed to connect, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" Retrying in 4 seconds...");
      delay(4000);
    }
  }
}

// -----------------------------------------------------------------------------
// Trigger Key Rotation
// -----------------------------------------------------------------------------
void triggerRotation() {
  Serial.println("Triggering Key Rotation via AWS IoT Core...");
  currentState = STATE_ROTATING;
  showOledRotating();
  stateChangeTime = millis();

  // Create JSON request payload
  StaticJsonDocument<256> doc;
  doc["device_id"] = AWS_DEVICE_ID;
  doc["action"] = "ROTATE_KEY";
  char reqId[20];
  snprintf(reqId, sizeof(reqId), "REQ-%lu", millis());
  doc["request_id"] = reqId;

  char jsonBuffer[256];
  serializeJson(doc, jsonBuffer);

  // Publish to request topic
  if (mqttClient.publish(AWS_IOT_REQUEST_TOPIC, jsonBuffer)) {
    Serial.print("Published request: ");
    Serial.println(jsonBuffer);
  } else {
    Serial.println("Failed to publish MQTT message!");
    currentState = STATE_FAILURE;
    showOledFailure("PUB ERROR");
  }
}

// -----------------------------------------------------------------------------
// Setup
// -----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // Initialize OLED
  if (!display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDRESS)) {
    Serial.println(F("SSD1306 allocation failed"));
    for (;;); // Don't proceed, loop forever
  }
  display.clearDisplay();
  display.display();

  connectWiFi();
  connectAWS();
}

// -----------------------------------------------------------------------------
// Main Loop
// -----------------------------------------------------------------------------
void loop() {
  // Ensure MQTT connection is active
  if (!mqttClient.connected()) {
    connectAWS();
  }
  mqttClient.loop();

  // Check physical push button (Active LOW)
  int buttonState = digitalRead(BUTTON_PIN);
  if (buttonState == LOW && (millis() - lastButtonPress > DEBOUNCE_DELAY_MS)) {
    lastButtonPress = millis();
    if (currentState != STATE_ROTATING) {
      triggerRotation();
    }
  }

  // Reset to IDLE screen after 8 seconds of showing SUCCESS or FAILURE
  if ((currentState == STATE_SUCCESS || currentState == STATE_FAILURE) && (millis() - stateChangeTime > 8000)) {
    currentState = STATE_IDLE;
    showOledIdle();
  }

  // Timeout safety: If in ROTATING state for > 15s without AWS response
  if (currentState == STATE_ROTATING && (millis() - stateChangeTime > 15000)) {
    currentState = STATE_FAILURE;
    showOledFailure("TIMEOUT");
    stateChangeTime = millis();
  }
}
