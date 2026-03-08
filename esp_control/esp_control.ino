/*
 * Integrated_Test_v3.ino
 * ESP32-S3 — Salt Dispenser: Weather + Web Server + Servo + DC Motor
 * ===================================================================
 * Dispense sequence:
 *   1. DC motor ON (full speed)
 *   2. Wait 1 second for motor to reach speed
 *   3. Servo opens 0° → 30°
 *   4. Wait 1 second for salt to pour
 *   5. Servo closes 30° → 0°
 *   6. DC motor OFF
 *
 * Wiring:
 *   Servo Signal  --> GPIO 38
 *   DC Motor      --> GPIO 40 (via motor driver e.g. L298N or L9110)
 *
 * Libraries needed (Sketch → Manage Libraries):
 *   - ArduinoJson by Benoit Blanchon (v6 or v7)
 *   - ESP32Servo by Kevin Harrington
 *   WiFi, WebServer, HTTPClient are built-in for ESP32.
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

// =============================================================================
// USER CONFIG
// =============================================================================
const char* WIFI_SSID     = "include hotspot name ESP and relay will use.";
const char* WIFI_PASSWORD = "hotspot password";

const float LATITUDE      = 43.4516;
const float LONGITUDE     = -80.4925;

// -18000 = UTC-5 Eastern Standard Time
// -14400 = UTC-4 Eastern Daylight Time (summer)
const long  TZ_OFFSET_SEC = -18000;

// 600000 = 10 min normal operation. 10000 = 10s for testing.
const unsigned long FETCH_INTERVAL_MS = 600000;

// ---------- DC Motor ----------
#define DC_MOTOR_PIN  40      // GPIO to motor driver

// ---------- Servo ----------
#define SERVO_PIN     38      // GPIO to servo signal
#define SERVO_CLOSED  0       // degrees — lid closed
#define SERVO_OPEN    50     // degrees — lid open
#define SERVO_STEP_MS 15      // ms per 1° step (smooth sweep speed)

// ---------- Dispense Timing ----------
#define MOTOR_RAMP_MS   200  // ms to wait after motor on before opening servo
#define POUR_WAIT_MS    5000  // ms to hold servo open while salt pours
// Total dispense duration = MOTOR_RAMP_MS + sweep time + POUR_WAIT_MS + sweep time
// This replaces the old DISPENSE_MS since timing is now handled step by step


// =============================================================================
// WEATHER STATE
// =============================================================================
struct HourlyWeather {
  float  temperature = 0.0;
  int    weatherCode = 0;
  String time        = "";
};

HourlyWeather currentHour;
HourlyWeather nextHour;

int dangerousWeatherCodes[] = {48, 51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99};
const int DANGEROUS_CODES_LEN = sizeof(dangerousWeatherCodes) / sizeof(int);


// =============================================================================
// DISPENSER STATE
// =============================================================================
bool          isSaltDispensing = false;
String        timeLastUsed     = "";
unsigned long lastFetchTime    = 0;
bool          weatherReady     = false;


// =============================================================================
// HARDWARE OBJECTS
// =============================================================================
WebServer server(80);
Servo     dispenserServo;


// =============================================================================
// WEATHER CODE DECODER
// =============================================================================
String decodeWeatherCode(int code) {
  switch (code) {
    case 0:  return "Clear sky";
    case 1:  return "Mainly clear";
    case 2:  return "Partly cloudy";
    case 3:  return "Overcast";
    case 45: return "Foggy";
    case 48: return "Icy fog";
    case 51: return "Light drizzle";
    case 53: return "Moderate drizzle";
    case 55: return "Dense drizzle";
    case 61: return "Slight rain";
    case 63: return "Moderate rain";
    case 65: return "Heavy rain";
    case 71: return "Slight snow";
    case 73: return "Moderate snow";
    case 75: return "Heavy snow";
    case 80: return "Slight showers";
    case 81: return "Moderate showers";
    case 82: return "Violent showers";
    case 95: return "Thunderstorm";
    case 96: return "Thunderstorm w/ hail";
    case 99: return "Thunderstorm w/ heavy hail";
    default: return "Unknown (" + String(code) + ")";
  }
}


// =============================================================================
// SERVO HELPER — smooth sweep
// =============================================================================
void moveServo(int fromAngle, int toAngle) {
  fromAngle = constrain(fromAngle, 0, 180);
  toAngle   = constrain(toAngle,   0, 180);
  Serial.printf("[SERVO] %d° → %d°\n", fromAngle, toAngle);

  if (fromAngle < toAngle) {
    for (int pos = fromAngle; pos <= toAngle; pos++) {
      dispenserServo.write(pos);
      delay(SERVO_STEP_MS);
    }
  } else {
    for (int pos = fromAngle; pos >= toAngle; pos--) {
      dispenserServo.write(pos);
      delay(SERVO_STEP_MS);
    }
  }
  Serial.println("[SERVO] Move complete");
}


// =============================================================================
// DISPENSE SEQUENCE
// Runs fully blocking — takes ~2.9 seconds total:
//   1s ramp + ~0.45s open sweep + 1s pour + ~0.45s close sweep
// =============================================================================
void dispenseSalt() {
  if (isSaltDispensing) return;
  isSaltDispensing = true;
  timeLastUsed = currentHour.time.substring(11, 16);

  // Step 1 — DC motor ON full speed
  Serial.println("[DISPENSE] Step 1: DC motor ON");
  digitalWrite(DC_MOTOR_PIN, LOW);
  delay(MOTOR_RAMP_MS);

  // Step 2 — Servo opens lid 0° → 30°
  Serial.println("[DISPENSE] Step 2: Opening lid");
  moveServo(SERVO_CLOSED, SERVO_OPEN);

  // Step 3 — Hold open, salt pours out
  Serial.println("[DISPENSE] Step 3: Pouring...");
  delay(POUR_WAIT_MS);

  // Step 4 — Servo closes lid 30° → 0°
  Serial.println("[DISPENSE] Step 4: Closing lid");
  moveServo(SERVO_OPEN, SERVO_CLOSED);

  // Step 5 — DC motor OFF
  Serial.println("[DISPENSE] Step 5: DC motor OFF");
  digitalWrite(DC_MOTOR_PIN, HIGH);

  isSaltDispensing = false;
  Serial.println("[DISPENSE] Cycle complete");
}


// =============================================================================
// WEATHER CHECK
// =============================================================================
bool checkHour(HourlyWeather hour) {
  bool cold    = hour.temperature < 0.0;
  bool wet     = false;
  String hourKey = hour.time.substring(11, 16);

  for (int i = 0; i < DANGEROUS_CODES_LEN; i++) {
    if (hour.weatherCode == dangerousWeatherCodes[i]) {
      wet = true;
      break;
    }
  }

  Serial.printf("[CHECK] cold=%d  wet=%d  hourKey=%s  lastUsed=%s\n",
                cold, wet, hourKey.c_str(), timeLastUsed.c_str());

  if (cold && wet && hourKey != timeLastUsed) {
    dispenseSalt();
    return true;
  }
  return false;
}


// =============================================================================
// WEATHER FETCH
// =============================================================================
void fetchWeather() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WEATHER] WiFi not connected — skipping fetch");
    return;
  }

  String url = "https://api.open-meteo.com/v1/forecast"
               "?latitude="  + String(LATITUDE, 4) +
               "&longitude=" + String(LONGITUDE, 4) +
               "&hourly=temperature_2m,weathercode"
               "&windspeed_unit=kmh"
               "&timezone=auto"
               "&forecast_days=1";

  HTTPClient http;
  http.begin(url);
  int code = http.GET();

  if (code != 200) {
    Serial.printf("[WEATHER] HTTP error: %d\n", code);
    http.end();
    return;
  }

  String payload = http.getString();
  http.end();

  DynamicJsonDocument doc(2048);
  if (deserializeJson(doc, payload)) {
    Serial.println("[WEATHER] JSON parse failed");
    return;
  }

  JsonArray times        = doc["hourly"]["time"].as<JsonArray>();
  JsonArray temperatures = doc["hourly"]["temperature_2m"].as<JsonArray>();
  JsonArray weatherCodes = doc["hourly"]["weathercode"].as<JsonArray>();

  struct tm timeInfo;
  if (!getLocalTime(&timeInfo)) {
    Serial.println("[WEATHER] NTP time not ready — skipping parse");
    return;
  }

  char targetTime[17];
  strftime(targetTime, sizeof(targetTime), "%Y-%m-%dT%H:00", &timeInfo);

  int currentIndex = -1;
  for (int i = 0; i < (int)times.size(); i++) {
    if (times[i].as<String>() == String(targetTime)) {
      currentIndex = i;
      break;
    }
  }

  if (currentIndex == -1) {
    Serial.printf("[WEATHER] Hour not found in forecast. Looking for: %s\n", targetTime);
    return;
  }

  int nextIndex = min(currentIndex + 1, (int)times.size() - 1);

  currentHour.temperature = temperatures[currentIndex].as<float>();
  currentHour.weatherCode = weatherCodes[currentIndex].as<int>();
  currentHour.time        = times[currentIndex].as<String>();

  nextHour.temperature = temperatures[nextIndex].as<float>();
  nextHour.weatherCode = weatherCodes[nextIndex].as<int>();
  nextHour.time        = times[nextIndex].as<String>();

  weatherReady = true;

  Serial.println("========== CURRENT HOUR ==========");
  Serial.printf("Time:        %s\n", currentHour.time.c_str());
  Serial.printf("Weather:     %s\n", decodeWeatherCode(currentHour.weatherCode).c_str());
  Serial.printf("Temperature: %.1f °C\n", currentHour.temperature);
  Serial.println("=========== NEXT HOUR ============");
  Serial.printf("Time:        %s\n", nextHour.time.c_str());
  Serial.printf("Weather:     %s\n", decodeWeatherCode(nextHour.weatherCode).c_str());
  Serial.printf("Temperature: %.1f °C\n", nextHour.temperature);
  Serial.println("==================================");

  checkHour(currentHour);
}


// =============================================================================
// ROUTES
// =============================================================================
void handleGetStatus() {
  server.sendHeader("Access-Control-Allow-Origin", "*");

  StaticJsonDocument<512> doc;
  doc["dispensing"]       = isSaltDispensing;
  doc["weatherCondition"] = weatherReady ? decodeWeatherCode(currentHour.weatherCode) : "Loading...";
  doc["temperature"]      = weatherReady ? currentHour.temperature : 0.0;
  doc["nextCondition"]    = weatherReady ? decodeWeatherCode(nextHour.weatherCode)    : "Loading...";
  doc["nextTemperature"]  = weatherReady ? nextHour.temperature    : 0.0;
  doc["systemHealthy"]    = (WiFi.status() == WL_CONNECTED) && weatherReady;
  doc["uptime_s"]         = millis() / 1000;
  doc["free_heap"]        = ESP.getFreeHeap();
  doc["wifi_rssi"]        = WiFi.RSSI();
  doc["esp_ip"]           = WiFi.localIP().toString();
  doc["weather_ready"]    = weatherReady;
  doc["last_dispense_hr"] = timeLastUsed;

  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
  Serial.println("[HTTP] GET /status served");
}

void handlePostUpdate() {
  server.sendHeader("Access-Control-Allow-Origin", "*");

  if (!server.hasArg("plain")) {
    server.send(400, "application/json", "{\"error\":\"No body\"}");
    return;
  }

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, server.arg("plain"))) {
    server.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
    return;
  }

  if (doc.containsKey("manualDispense") && doc["manualDispense"]) {
    Serial.println("[HTTP] Manual dispense triggered from desktop app");
    dispenseSalt();
  }

  server.send(200, "application/json", "{\"success\":true}");
}

void handleOptions() {
  server.sendHeader("Access-Control-Allow-Origin",  "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.send(200);
}

void handleNotFound() {
  server.send(404, "application/json", "{\"error\":\"Route not found\"}");
}


// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n====================================");
  Serial.println("  Salt Dispenser v3 — Servo + Motor");
  Serial.println("====================================");

  // --- DC Motor setup (simple digital on/off) ---
  pinMode(DC_MOTOR_PIN, OUTPUT);
  digitalWrite(DC_MOTOR_PIN, HIGH);
  Serial.println("[MOTOR] DC motor initialised — OFF");

  // --- Servo setup ---
  ESP32PWM::allocateTimer(0);
  dispenserServo.setPeriodHertz(50);
  dispenserServo.attach(SERVO_PIN, 500, 2500);
  dispenserServo.write(SERVO_CLOSED);
  delay(500);
  Serial.println("[SERVO] Servo initialised — lid closed");

  // --- WiFi ---
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[WiFi] Connecting");

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 40) {
    delay(500);
    Serial.print(".");
    tries++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WiFi] FAILED — restarting in 5s");
    delay(5000);
    ESP.restart();
  }

  Serial.println();
  Serial.println("[WiFi] Connected!");
  Serial.println("====================================");
  Serial.printf("  [ESP]  IP Address: http://%s\n", WiFi.localIP().toString().c_str());
  Serial.println("  Paste this IP into relay_v3.py");
  Serial.println("  ESP_LOCAL_IP = \"" + WiFi.localIP().toString() + "\"");
  Serial.println("====================================");

  configTime(TZ_OFFSET_SEC, 0, "pool.ntp.org");
  Serial.print("[NTP]  Syncing time");
  struct tm timeInfo;
  int ntpTries = 0;
  while (!getLocalTime(&timeInfo) && ntpTries < 20) {
    delay(500);
    Serial.print(".");
    ntpTries++;
  }
  if (getLocalTime(&timeInfo)) {
    char buf[32];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &timeInfo);
    Serial.printf("\n[NTP]  Time synced: %s\n", buf);
  } else {
    Serial.println("\n[NTP]  WARNING — time sync failed.");
  }

  fetchWeather();
  lastFetchTime = millis();

  server.on("/status",  HTTP_GET,     handleGetStatus);
  server.on("/update",  HTTP_POST,    handlePostUpdate);
  server.on("/status",  HTTP_OPTIONS, handleOptions);
  server.on("/update",  HTTP_OPTIONS, handleOptions);
  server.onNotFound(handleNotFound);

  server.begin();
  Serial.println("[HTTP] Server started");
  Serial.println("====================================");
}


// =============================================================================
// LOOP
// =============================================================================
void loop() {
  server.handleClient();

  if (millis() - lastFetchTime >= FETCH_INTERVAL_MS) {
    lastFetchTime = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi] Lost — reconnecting...");
      WiFi.reconnect();
      delay(2000);
    }
    fetchWeather();
  }
}
