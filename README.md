# AutoSalt — Smart Salt Dispenser
> HackCanada 2026

AutoSalt is an IoT salt dispenser that automatically detects icy and wet weather conditions and dispenses salt to protect walkways — with a voice-assisted desktop app designed for elderly users.

---

## How It Works

An ESP32-S3 monitors local weather every 10 minutes using the [Open-Meteo](https://open-meteo.com/) free API. If the temperature is below freezing **and** dangerous precipitation is detected, the motor activates and disperses salt automatically. A desktop app provides a live status display, manual override, and a voice assistant so users with limited mobility or vision can interact hands-free.

```
Open-Meteo API
      ↓
   ESP32-S3  ←──── POST /update (manual dispense)
   (weather + motor + webserver)
      ↓
   GET /status (every 5s)
      ↓
   Desktop App (app.py)
      ↓
   Voice Assistant (ElevenLabs TTS + Google STT)
```

---

## Features

- **Auto-dispensing** — triggers when cold (< 0°C) and wet weather codes are detected
- **Manual override** — button in app or voice command instantly triggers a dispense cycle
- **Voice assistant** — press and hold to ask questions; spoken responses via ElevenLabs
- **Elder-friendly UI** — large text, high contrast, simple status messages, no technical jargon
- **Static IP** — ESP always claims the same address so the app never loses connection
- **Offline-safe** — app degrades gracefully when ESP is unreachable

---

## Hardware

| Component | Details |
|-----------|---------|
| Microcontroller | ESP32-S3 Dev Module |
| Motor | DC motor on GPIO 5, PWM via LEDC |
| Network | 2.4GHz WiFi hotspot |

---

## Project Structure

```
AutoSalt/
├── Integrated_Test.ino     # ESP32 firmware — weather + webserver + motor
├── app.py                  # Desktop app — UI + voice assistant
└── README.md
```

---

## ESP32 Setup

### 1. Install Arduino Libraries
In Arduino IDE go to **Sketch → Manage Libraries** and install:
- `ArduinoJson` by Benoit Blanchon (v6 or v7)

`WiFi`, `WebServer`, and `HTTPClient` are built into the ESP32 core.

### 2. Configure credentials
Open `Integrated_Test.ino` and fill in the top section:
```cpp
const char* WIFI_SSID     = "your_network_name";
const char* WIFI_PASSWORD = "your_password";

const float LATITUDE  = 43.4516;   // your coordinates
const float LONGITUDE = -80.4925;

IPAddress STATIC_IP(192, 168, x, x);   // desired static IP
IPAddress GATEWAY  (192, 168, x, x);   // your router/hotspot gateway
```

### 3. Flash and get the IP
Select **Tools → Board → ESP32S3 Dev Module**, select the correct COM port, and upload.

Open Serial Monitor at **115200 baud** and press the EN/RST button. You will see:
```
[WiFi] Connected!
[ESP]  IP Address: http://192.168.x.x   <- copy this
[HTTP] Server started
```

### 4. Verify
Open a browser and go to `http://192.168.x.x/status` — you should see live JSON.

---

## Desktop App Setup

### Requirements
```bash
pip install requests speechrecognition elevenlabs pygame
pip install pipwin
pipwin install pyaudio       # Windows only
```

### Configure
Open `app.py` and set:
```python
ESP_IP           = "192.168.x.x"           # IP from Serial Monitor
ELEVENLABS_KEY   = "your_api_key_here"      # from elevenlabs.io -> Profile -> API Key
ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel (free tier voice ID)
```

### Run
```bash
python app.py
```

### Build standalone .exe (Windows)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "Salt Dispenser" app.py
# Output: dist/Salt Dispenser.exe
```

---

## Voice Commands

| Say | Response |
|-----|----------|
| "What's the weather?" | Current condition and temperature |
| "What's the forecast?" | Next hour prediction |
| "How's my walkway?" | Full status summary |
| "Is salt dispensing?" | Yes or no |
| "Dispense salt" | Triggers a manual dispense cycle |
| "What's the temperature?" | Temp in F and C |
| "Is the device working?" | Connection and system health |
| "Help" | Lists all available commands |

---

## Auto-Dispense Logic

The ESP checks conditions after every weather fetch:

```
temperature < 0 degrees C
    AND
weatherCode in [48, 51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99]
    AND
current hour != last dispensed hour
        |
        v
    dispenseSalt()
```

Weather codes cover: icy fog, drizzle, rain, snow, showers, and thunderstorms.

---

## API Reference

The ESP hosts these endpoints on port 80:

### `GET /status`
Returns current device state.
```json
{
  "dispensing": false,
  "weatherCondition": "Heavy snow",
  "temperature": -3.2,
  "nextCondition": "Moderate snow",
  "nextTemperature": -4.1,
  "systemHealthy": true,
  "uptime_s": 3600,
  "wifi_rssi": -42,
  "esp_ip": "192.168.241.239",
  "last_dispense_hr": "14:00"
}
```

### `POST /update`
Trigger a manual dispense cycle.
```json
{ "manualDispense": true }
```
Response:
```json
{ "success": true }
```

---

## Switching Networks

When moving to a new WiFi network:

1. Update `WIFI_SSID` and `WIFI_PASSWORD` in the `.ino` file
2. Update `STATIC_IP` and `GATEWAY` to match the new network
3. Reflash the ESP
4. Copy the new IP from Serial Monitor into `app.py`

---

## Built With

- [ESP32 Arduino Core](https://github.com/espressif/arduino-esp32)
- [Open-Meteo](https://open-meteo.com/) — free weather API, no key required
- [ArduinoJson](https://arduinojson.org/)
- [ElevenLabs](https://elevenlabs.io/) — text-to-speech
- [SpeechRecognition](https://pypi.org/project/SpeechRecognition/) — Google STT
- [Tkinter](https://docs.python.org/3/library/tkinter.html) — desktop UI
- [pygame](https://www.pygame.org/) — audio playback

---

*HackCanada 2026*
