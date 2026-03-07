/*
 * Integrated_Test.ino
 * ESP32-S2/S3 — Salt Dispenser: Weather + Web Server combined
 * ============================================================
 * What this does:
 *   1. Connects to WiFi
 *   2. Syncs time via NTP
 *   3. Fetches weather from Open-Meteo every FETCH_INTERVAL_MS
 *   4. Automatically dispenses salt if cold + wet conditions detected
 *   5. Hosts an HTTP server so the desktop app can:
 *        GET  /status  → read weather, dispensing state, system health
 *        POST /update  → trigger manual dispense from the app
 *
 * Libraries needed (Sketch → Manage Libraries):
 *   - ArduinoJson by Benoit Blanchon (v6 or v7)
 *   WiFi, WebServer, HTTPClient are all built-in for ESP32.
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// =============================================================================
// USER CONFIG — fill these in
// =============================================================================
const char* WIFI_SSID     = "I will hack u";
const char* WIFI_PASSWORD = "Alfrsmhmmd!2598";

// Coordinates for weather lookup (hardcoded as per design)
const float LATITUDE  = 43.4516;
const float LONGITUDE = -80.4925;

// NTP timezone offset in seconds.
// -18000 = UTC-5 (Eastern Standard Time)
// -14400 = UTC-4 (Eastern Daylight Time — use this in summer)
const long  TZ_OFFSET_SEC = -18000;

// How often to fetch weather (ms). 10 min = 600000. 10s for testing = 10000.
const unsigned long FETCH_INTERVAL_MS = 600000;

// Motor pin for salt dispenser (PWM-capable GPIO)
#define MOTOR_PIN       5
#define LEDC_FREQ_HZ    5000
#define LEDC_RESOLUTION 8     // 8-bit → 0–255
#define MOTOR_SPEED     200   // PWM speed while dispensing (0–255)
#define DISPENSE_MS     3000  // How long to run motor per dispense cycle (ms)

IPAddress STATIC_IP(192, 168, 241, 239);  // ESP always claims this
IPAddress GATEWAY  (192, 168, 241, 178);    // your hotspot gateway
IPAddress SUBNET   (255, 255, 255, 0);
IPAddress DNS      (8,   8,   8,   8);

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

// The weather codes that count as "dangerous" (icy/wet/snowy)
int dangerousWeatherCodes[] = {48, 51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99};
const int DANGEROUS_CODES_LEN = sizeof(dangerousWeatherCodes) / sizeof(int);

// =============================================================================
// DISPENSER STATE
// =============================================================================
bool   isSaltDispensing = false;   // true while motor is running
String timeLastUsed     = "";      // tracks which hour was last dispensed
unsigned long dispenseStartMs = 0; // when the current dispense cycle started
unsigned long lastFetchTime   = 0; // when weather was last fetched
bool   weatherReady     = false;   // false until first fetch completes

// =============================================================================
// WEB SERVER
// =============================================================================
WebServer server(80);


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
// MOTOR / DISPENSER
// =============================================================================
void dispenseSalt() {
  // Guard: don't start a new cycle if already running
  if (isSaltDispensing) return;

  Serial.println("[DISPENSE] Starting salt dispense cycle");
  isSaltDispensing  = true;
  dispenseStartMs   = millis();

  // Store which hour triggered this so we don't repeat it
  timeLastUsed = currentHour.time.substring(11, 16); // "HH:MM" portion

  // Start motor via LEDC (v3 API)
  ledcWrite(MOTOR_PIN, MOTOR_SPEED);
}

void stopMotor() {
  ledcWrite(MOTOR_PIN, 0);
  isSaltDispensing = false;
  Serial.println("[DISPENSE] Dispense cycle complete — motor stopped");
}


// =============================================================================
// WEATHER CHECK — called after every fetch
// =============================================================================
bool checkHour(HourlyWeather hour) {
  bool cold = hour.temperature < 0.0;
  bool wet  = false;

  // Extract just the "HH:MM" part of the timestamp for dedup check
  String hourKey = hour.time.substring(11, 16);

  for (int i = 0; i < DANGEROUS_CODES_LEN; i++) {
    if (hour.weatherCode == dangerousWeatherCodes[i]) {
      wet = true;
      break;
    }
  }

  Serial.printf("[CHECK] cold=%d  wet=%d  hourKey=%s  lastUsed=%s\n",
                cold, wet, hourKey.c_str(), timeLastUsed.c_str());

  // Dispense if cold + wet + haven't already dispensed this hour
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

  // Auto-check after every fetch
  checkHour(currentHour);
}


// =============================================================================
// ROUTE: GET /status
// Desktop app calls this every 5 seconds to refresh its UI
// =============================================================================
void handleGetStatus() {
  // Add CORS header so browser-based tools can also call this
  server.sendHeader("Access-Control-Allow-Origin", "*");

  StaticJsonDocument<512> doc;

  // Fields the desktop app reads
  doc["dispensing"]       = isSaltDispensing;
  doc["weatherCondition"] = weatherReady ? decodeWeatherCode(currentHour.weatherCode) : "Loading...";
  doc["temperature"]      = weatherReady ? currentHour.temperature : 0.0;
  doc["nextCondition"]    = weatherReady ? decodeWeatherCode(nextHour.weatherCode)    : "Loading...";
  doc["nextTemperature"]  = weatherReady ? nextHour.temperature    : 0.0;
  doc["systemHealthy"]    = (WiFi.status() == WL_CONNECTED) && weatherReady;

  // Diagnostic fields (useful during testing)
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


// =============================================================================
// ROUTE: POST /update
// Desktop app sends { "manualDispense": true } to trigger manual cycle
// =============================================================================
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


// =============================================================================
// ROUTE: OPTIONS preflight (needed for browser-based tools / curl)
// =============================================================================
void handleOptions() {
  server.sendHeader("Access-Control-Allow-Origin",  "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.send(200);
}


// =============================================================================
// ROUTE: 404 fallback
// =============================================================================
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
  Serial.println("  Salt Dispenser — Integrated Test");
  Serial.println("====================================");

  // Motor init (ESP32 core v3 API)
  ledcAttach(MOTOR_PIN, LEDC_FREQ_HZ, LEDC_RESOLUTION);
  ledcWrite(MOTOR_PIN, 0);   // motor off at boot

  // Apply static IP before connecting — ESP will always claim this address
  if (!WiFi.config(STATIC_IP, GATEWAY, SUBNET, DNS)) {
    Serial.println("[WiFi] WARNING: Static IP config failed — will use DHCP instead");
  }

  // WiFi — STA mode so ESP connects to network AND can host a server
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
    Serial.println("\n[WiFi] FAILED — restarting in 5 s");
    delay(5000);
    ESP.restart();
  }

  Serial.println();
  Serial.printf("[WiFi] Connected!\n");
  Serial.printf("[ESP]  IP Address: http://%s\n", WiFi.localIP().toString().c_str());
  Serial.println("[ESP]  Put this IP in app.py  →  ESP_IP = \"x.x.x.x\"");
  Serial.println("====================================");

  // NTP time sync — required for hour-matching in fetchWeather()
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
    Serial.println("\n[NTP]  WARNING — time sync failed. Weather hour-matching may not work.");
  }

  // First weather fetch
  fetchWeather();
  lastFetchTime = millis();

  // Register HTTP routes
  server.on("/status",  HTTP_GET,     handleGetStatus);
  server.on("/update",  HTTP_POST,    handlePostUpdate);
  server.on("/status",  HTTP_OPTIONS, handleOptions);
  server.on("/update",  HTTP_OPTIONS, handleOptions);
  server.onNotFound(handleNotFound);

  server.begin();
  Serial.println("[HTTP] Server started");
  Serial.println("  GET  /status → read weather + dispense state");
  Serial.println("  POST /update → manual dispense trigger");
  Serial.println("====================================");
}


// =============================================================================
// LOOP
// =============================================================================
void loop() {
  // Handle any incoming HTTP requests from the desktop app
  server.handleClient();

  // Stop motor after DISPENSE_MS if it's been running long enough
  if (isSaltDispensing && (millis() - dispenseStartMs >= DISPENSE_MS)) {
    stopMotor();
  }

  // Fetch new weather data on schedule
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
