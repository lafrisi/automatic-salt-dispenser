# AutoThaw

An IoT-based automatic salt dispenser for residential walkways. The device monitors local weather conditions in real time and disperses salt when temperatures drop below freezing and precipitation is detected, with full remote monitoring and manual control from anywhere in the world.

---

## Overview

The system is made up of three parts working together. The ESP32-S3 microcontroller sits inside the dispenser unit, connects to a local hotspot, and fetches hourly weather forecasts. When conditions are dangerous it automatically runs the dispense cycle. A relay script runs on a second laptop connected to the same hotspot, bridging the ESP to the outside world. The desktop app runs on any laptop, on any network, and connects back to the relay over an encrypted Tailscale tunnel, giving the user live status, manual control, and a voice assistant no matter where they are.

---

## How It Works

The ESP polls the Open-Meteo weather API every 10 minutes using the device's GPS coordinates. If the current hour is both below 0°C and matches a dangerous weather code such as freezing drizzle, snow, ice fog, rain, or thunderstorms, it triggers the dispense cycle automatically. The cycle spins a DC motor to full speed, sweeps a servo from 0 to 30 degrees to open the lid, holds it open for one second while salt pours out, then closes the lid and shuts the motor off.

The desktop app polls the device every 5 seconds and displays the current weather condition, temperature, next-hour forecast, and system health. The voice assistant accepts natural language questions spoken aloud by holding a button, passes them to Gemini 2.5 Flash with the live device context, and speaks the response back using ElevenLabs text-to-speech.

The remote access works through Tailscale, which creates an encrypted peer-to-peer tunnel between the two laptops. The ESP never needs a public IP address or port forwarding. The app on Laptop 1 simply targets Laptop 2's Tailscale IP, and Tailscale handles the rest regardless of what network either machine is on.

---

## Hardware

| Component | Role |
|---|---|
| ESP32-S3 | Microcontroller, WiFi, web server, motor and servo control |
| MG996R Servo | Opens and closes the dispenser lid |
| DC Motor and Driver | Agitates and pushes salt through the opening |
| Salt container with hinged lid | Stores and releases salt onto the walkway |

Wiring connections to the ESP32-S3:

- Servo signal wire to GPIO 38
- DC motor driver input to GPIO 40

The enclosure can be 3D printed or hand-built. The servo controls a hinged lid over the salt opening, and the DC motor sits inside the container to move salt toward the exit during a dispense cycle.

---

## File Structure

| File | Description |
|---|---|
| `app.py` | Desktop app, runs on Laptop 1, works on any network |
| `relay_v3.py` | Relay bridge, runs on Laptop 2, must be on the ESP's hotspot |
| `esp_control.ino` | ESP32-S3 firmware |

---

## Requirements

Python dependencies for both laptops:

```
flask
requests
elevenlabs
speechrecognition
google-genai
pygame
```

Arduino libraries, installable via Sketch > Manage Libraries:

- ArduinoJson by Benoit Blanchon
- ESP32Servo by Kevin Harrington
- WiFi, WebServer, and HTTPClient are built into the ESP32 board package

Tailscale must be installed on both laptops and both signed into the same account. Download at tailscale.com/download.

---

## Configuration

**API keys** - open `app.py` and fill in:

```python
ELEVENLABS_KEY = "your_key"    # from elevenlabs.io under Profile > API Keys
GEMINI_KEY     = "your_key"    # from aistudio.google.com under Get API Key
```

**Hotspot credentials** - open `esp_control.ino` and set:

```cpp
const char* WIFI_SSID     = "your_hotspot_name";
const char* WIFI_PASSWORD = "your_hotspot_password";
```

**Location** - coordinates default to Waterloo, Ontario. To change them:

```cpp
const float LATITUDE  = 43.4516;
const float LONGITUDE = -80.4925;
```

---

## Running the System

**1. Flash the ESP**

Disconnect the motor driver power before flashing to prevent the motor from briefly spinning during boot. Open `esp_control.ino` in Arduino IDE, set your hotspot credentials, and upload to the ESP32-S3. Reconnect the motor driver, then open Serial Monitor at 115200 baud. The device will print its assigned IP address on boot, copy it.

**2. Start the relay on Laptop 2**

Connect Laptop 2 to the ESP's hotspot. Paste the ESP's IP into `relay_v3.py` as `ESP_LOCAL_IP`, then run:

```
python relay_v3.py
```

Open `http://localhost:8080/health` in a browser to confirm the relay is running. Then run `tailscale ip -4` to get Laptop 2's Tailscale IP and pass it to whoever is running the app.

**3. Start the app on Laptop 1**

Paste Laptop 2's Tailscale IP into `app.py` as `ESP_IP`, then run:

```
python app.py
```

The connection indicator in the top bar will show Connected via Tailscale once the device is reachable.

---

## Voice Assistant

Hold the Talk button and speak naturally. The assistant understands questions about current weather, walkway status, and temperature, and accepts voice commands to manually trigger a dispense cycle. All responses are spoken aloud. Example prompts:

- "What is the weather like outside?"
- "Is the walkway being monitored right now?"
- "Dispense salt now"

---

## Remote Access

Laptop 1 can be on an entirely different network from the device, whether that is a different WiFi, cellular, or another city entirely, and the app will still connect, display live data, and accept manual commands. The Tailscale tunnel encrypts all traffic between the two laptops and requires no router configuration on either end.
