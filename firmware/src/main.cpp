// TV-IR ESP32 firmware
//
// Generic IR transmitter exposed over HTTP. The server tells this node what
// to send via JSON; this node only knows how to drive the IR LED.
//
// Endpoints:
//   GET  /          status JSON
//   GET  /health    200 if alive
//   POST /ir        body: parsed protocol or raw timings, see README

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <ArduinoOTA.h>
#include <ArduinoJson.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>
#include <time.h>

#include "secrets.h"

// ---- Pins ----
static constexpr uint8_t IR_LED_PIN     = 4;   // through 2N2222 → IR LED
static constexpr uint8_t STATUS_LED_PIN = 2;   // built-in LED on most dev boards

// ---- Globals ----
static IRsend     irsend(IR_LED_PIN);
static WebServer  http(80);
static char       hostname[24];   // tvir-XXXXXX

// ---- Helpers ----
static void blinkStatus(uint16_t on_ms = 30) {
  digitalWrite(STATUS_LED_PIN, HIGH);
  delay(on_ms);
  digitalWrite(STATUS_LED_PIN, LOW);
}

static void sendJsonError(int code, const char* message) {
  JsonDocument doc;
  doc["ok"] = false;
  doc["error"] = message;
  String body;
  serializeJson(doc, body);
  http.send(code, "application/json", body);
}

static void sendJsonOk() {
  http.send(200, "application/json", "{\"ok\":true}");
}

// Transmit a parsed protocol command. Returns true on success.
// The server is expected to send {protocol, address, command, [bits]}.
static bool transmitParsed(const JsonDocument& doc) {
  const char* protoRaw = doc["protocol"] | "";
  String proto = String(protoRaw);
  proto.toUpperCase();

  uint32_t address = doc["address"] | 0;
  uint32_t command = doc["command"] | 0;
  uint16_t bits    = doc["bits"]    | 0;

  if (proto == "NEC" || proto == "NECEXT") {
    uint64_t data = irsend.encodeNEC(address, command);
    irsend.sendNEC(data, bits ? bits : kNECBits);
    return true;
  }
  if (proto == "SAMSUNG" || proto == "SAMSUNG32") {
    uint64_t data = irsend.encodeSAMSUNG(address & 0xFF, command & 0xFF);
    irsend.sendSAMSUNG(data, bits ? bits : kSamsung32Bits);
    return true;
  }
  if (proto == "SONY" || proto == "SIRC") {
    // Bit length varies per remote: 12 (most), 15, or 20.
    uint16_t nbits = bits ? bits : 12;
    irsend.sendSony(irsend.encodeSony(nbits, command, address), nbits);
    return true;
  }
  if (proto == "RC5") {
    uint64_t data = irsend.encodeRC5(address, command);
    irsend.sendRC5(data, bits ? bits : kRC5Bits);
    return true;
  }
  if (proto == "RC5X") {
    uint64_t data = irsend.encodeRC5X(address, command, /*key_released=*/false);
    irsend.sendRC5(data, bits ? bits : kRC5XBits);
    return true;
  }
  if (proto == "RC6") {
    uint64_t data = irsend.encodeRC6(address, command);
    irsend.sendRC6(data, bits ? bits : kRC6Mode0Bits);
    return true;
  }
  if (proto == "PANASONIC") {
    // Flipper stores Panasonic as a 16-bit address + 32-bit command.
    // IRremoteESP8266 wants the full 48-bit frame.
    uint64_t data = ((uint64_t)address << 32) | (command & 0xFFFFFFFF);
    irsend.sendPanasonic64(data, bits ? bits : kPanasonicBits);
    return true;
  }
  if (proto == "LG" || proto == "LG2") {
    uint64_t data = ((uint64_t)(address & 0xFF) << 24)
                  | ((uint64_t)(address & 0xFF) << 16)
                  |  (command & 0xFFFF);
    if (proto == "LG2") {
      irsend.sendLG2(data, bits ? bits : kLgBits);
    } else {
      irsend.sendLG(data, bits ? bits : kLgBits);
    }
    return true;
  }
  if (proto == "SHARP") {
    irsend.sendSharp(address, command);
    return true;
  }
  if (proto == "JVC") {
    uint16_t data = ((address & 0xFF) << 8) | (command & 0xFF);
    irsend.sendJVC(data, bits ? bits : kJvcBits);
    return true;
  }
  return false;
}

// Transmit a raw timing array.
static bool transmitRaw(const JsonDocument& doc) {
  uint16_t freq = doc["freq"] | 38000;
  JsonArrayConst arr = doc["raw"].as<JsonArrayConst>();
  if (arr.isNull() || arr.size() == 0) return false;

  size_t len = arr.size();
  if (len > 1024) return false;  // sanity cap

  std::unique_ptr<uint16_t[]> buf(new uint16_t[len]);
  size_t i = 0;
  for (JsonVariantConst v : arr) {
    buf[i++] = v.as<uint16_t>();
  }
  irsend.sendRaw(buf.get(), len, freq);
  return true;
}

// ---- HTTP handlers ----
static void handleStatus() {
  JsonDocument doc;
  doc["ok"] = true;
  doc["hostname"] = hostname;
  doc["ip"] = WiFi.localIP().toString();
  doc["mac"] = WiFi.macAddress();
  doc["rssi"] = WiFi.RSSI();
  doc["uptime_s"] = (uint32_t)(millis() / 1000);
  doc["heap_free"] = (uint32_t)ESP.getFreeHeap();
  String body;
  serializeJsonPretty(doc, body);
  http.send(200, "application/json", body);
}

static void handleHealth() {
  http.send(200, "text/plain", "ok");
}

static void handleIr() {
  if (http.method() != HTTP_POST) {
    sendJsonError(405, "method_not_allowed");
    return;
  }
  String body = http.arg("plain");
  if (body.isEmpty()) {
    sendJsonError(400, "empty_body");
    return;
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    sendJsonError(400, "bad_json");
    return;
  }

  bool ok = false;
  if (doc["raw"].is<JsonArrayConst>()) {
    ok = transmitRaw(doc);
  } else if (doc["protocol"].is<const char*>()) {
    ok = transmitParsed(doc);
  } else {
    sendJsonError(400, "missing_protocol_or_raw");
    return;
  }

  if (!ok) {
    sendJsonError(400, "unsupported_or_invalid");
    return;
  }

  blinkStatus();
  sendJsonOk();
}

// ---- Setup helpers ----
static void buildHostname() {
  uint64_t mac = ESP.getEfuseMac();
  uint32_t low = (uint32_t)(mac & 0xFFFFFF);
  snprintf(hostname, sizeof(hostname), "tvir-%06x", low);
}

static void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("[wifi] connecting to %s as %s\n", WIFI_SSID, hostname);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN));
    delay(250);
    if (millis() - start > 30000) {
      Serial.println("[wifi] timeout, restarting");
      ESP.restart();
    }
  }
  digitalWrite(STATUS_LED_PIN, LOW);
  Serial.printf("[wifi] connected: %s\n", WiFi.localIP().toString().c_str());
}

static void startMdns() {
  if (!MDNS.begin(hostname)) {
    Serial.println("[mdns] failed");
    return;
  }
  MDNS.addService("http", "tcp", 80);
  MDNS.addService("tvir", "tcp", 80);
  Serial.printf("[mdns] %s.local\n", hostname);
}

static void syncTime() {
  configTzTime(TIMEZONE, NTP_SERVER);
  Serial.printf("[ntp] using %s\n", NTP_SERVER);
}

static void startOta() {
  ArduinoOTA.setHostname(hostname);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { Serial.println("[ota] start"); });
  ArduinoOTA.onEnd([]() { Serial.println("[ota] done"); });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("[ota] error %u\n", e); });
  ArduinoOTA.begin();
}

static void startHttp() {
  http.on("/",       HTTP_GET,  handleStatus);
  http.on("/health", HTTP_GET,  handleHealth);
  http.on("/ir",     HTTP_POST, handleIr);
  http.onNotFound([]() { sendJsonError(404, "not_found"); });
  http.begin();
}

// ---- Arduino entry points ----
void setup() {
  Serial.begin(115200);
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  irsend.begin();
  buildHostname();
  connectWiFi();
  startMdns();
  syncTime();
  startOta();
  startHttp();

  Serial.println("[boot] ready");
}

void loop() {
  ArduinoOTA.handle();
  http.handleClient();
  delay(1);
}
