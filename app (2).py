"""
app.py — Salt Dispenser Home Display with Voice Assistant
==========================================================
Elder-friendly desktop app with:
  - ElevenLabs text-to-speech voice output
  - Press-and-hold voice input (speech_recognition)
  - Greeting on open that reads current status aloud
  - Preset voice commands (no ESP changes needed)
  - Weather tiles, status card, manual dispense button

Install dependencies:
  pip install requests speechrecognition pyaudio elevenlabs

Build exe:
  pip install pyinstaller
  pyinstaller --onefile --windowed --name "Salt Dispenser" app.py

NOTE: pyaudio on Windows may need:
  pip install pipwin
  pipwin install pyaudio
"""

import tkinter as tk
from tkinter import font as tkfont
import threading
import requests
import time
import queue
from datetime import datetime

# ElevenLabs + speech recognition
try:
    from elevenlabs.client import ElevenLabs
    ELEVENLABS_OK = True
except ImportError:
    ELEVENLABS_OK = False

try:
    import speech_recognition as sr
    SR_OK = True
except ImportError:
    SR_OK = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
ESP_IP            = "192.168.241.239"
ESP_BASE          = f"http://{ESP_IP}"
POLL_MS           = 5000

ELEVENLABS_KEY    = "sk_c9ae5ff6b89f09bfc47e876400e3a803f6a5a99b94e4899b"   # ← paste your key here
ELEVENLABS_VOICE  = "21m00Tcm4TlvDq8ikWAM"                     # ElevenLabs voice name

# ── PALETTE ───────────────────────────────────────────────────────────────────
BG          = "#f0f4f8"
SURFACE     = "#ffffff"
BLUE        = "#2c6fad"
BLUE_LIGHT  = "#ddeeff"
GREEN       = "#1e7e4a"
GREEN_LIGHT = "#d4f0e0"
AMBER       = "#b45309"
AMBER_LIGHT = "#fef3c7"
RED         = "#b91c1c"
RED_LIGHT   = "#fee2e2"
GREY_LIGHT  = "#cbd5e1"
TEXT        = "#1e293b"
TEXT_MED    = "#475569"
TEXT_LIGHT  = "#94a3b8"
WHITE       = "#ffffff"
MIC_IDLE    = "#2c6fad"
MIC_LISTEN  = "#e84040"
MIC_THINK   = "#b45309"


# ══════════════════════════════════════════════════════════════════════════════
#  ESP CLIENT
# ══════════════════════════════════════════════════════════════════════════════
class ESPClient:
    def __init__(self, base):
        self.base = base

    def status(self):
        try:
            return requests.get(f"{self.base}/status", timeout=3).json()
        except Exception:
            return None

    def manual_dispense(self):
        try:
            return requests.post(f"{self.base}/update",
                                 json={"manualDispense": True}, timeout=3).json()
        except Exception as e:
            return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  VOICE ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class VoiceEngine:
    """Handles ElevenLabs TTS output and speech_recognition STT input."""

    def __init__(self, api_key: str, voice: str):
        self.voice    = voice
        self.speaking = False
        self._tts_queue = queue.Queue()

        if ELEVENLABS_OK and api_key != "YOUR_ELEVENLABS_API_KEY":
            self.client = ElevenLabs(api_key=api_key)
            self.tts_ready = True
        else:
            self.client    = None
            self.tts_ready = False
            print("[VOICE] ElevenLabs not configured — TTS disabled")

        if SR_OK:
            self.recognizer = sr.Recognizer()
            self.mic        = sr.Microphone()
            # Calibrate mic noise level once at startup
            threading.Thread(target=self._calibrate, daemon=True).start()
            self.stt_ready = True
        else:
            self.stt_ready = False
            print("[VOICE] speech_recognition not installed — STT disabled")

    def _calibrate(self):
        try:
            with self.mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            print("[VOICE] Microphone calibrated")
        except Exception as e:
            print(f"[VOICE] Mic calibration failed: {e}")

    def speak(self, text: str):
        """Speak text via ElevenLabs on a background thread."""
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def _speak_worker(self, text: str):
        self.speaking = True
        print(f"[TTS] {text}")
        try:
            if self.tts_ready:
                audio = self.client.text_to_speech.convert(
                    text=text,
                    voice_id=self.voice,
                    model_id="eleven_flash_v2_5",
                )
                import tempfile, os
                import pygame

                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    for chunk in audio:
                        f.write(chunk)
                    tmp_path = f.name

                pygame.mixer.init()
                pygame.mixer.music.load(tmp_path)
                pygame.mixer.music.play()

                # Wait for playback to finish before cleaning up
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)

                pygame.mixer.quit()
                os.unlink(tmp_path)  # delete the temp file after playing
            else:
                # Fallback: just print if ElevenLabs not configured
                print(f"[TTS FALLBACK] {text}")
        except Exception as e:
            print(f"[TTS ERROR] {e}")
        finally:
            self.speaking = False

    def listen(self) -> str:
        """Record audio while called, return recognised text or empty string."""
        if not self.stt_ready:
            return ""
        try:
            with self.mic as source:
                print("[STT] Listening...")
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=6)
            text = self.recognizer.recognize_google(audio).lower()
            print(f"[STT] Heard: {text}")
            return text
        except sr.WaitTimeoutError:
            return ""
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            print(f"[STT ERROR] {e}")
            return ""


# ══════════════════════════════════════════════════════════════════════════════
#  VOICE COMMAND MATCHER
# ══════════════════════════════════════════════════════════════════════════════
class CommandMatcher:
    """
    Maps spoken phrases to actions using keyword matching.
    No Gemini / NLP needed — just a word bank.
    """

    # Each entry: (keywords_that_trigger_it, command_key)
    COMMANDS = [
        (["weather", "outside", "condition", "raining", "snowing"],  "weather"),
        (["forecast", "next hour", "later", "coming up"],            "forecast"),
        (["walkway", "status", "happening", "going on", "okay"],     "status"),
        (["dispensing", "salt dispensing", "is salt"],               "dispensing"),
        (["dispense", "start dispensing", "add salt", "release"],    "dispense_now"),
        (["device", "working", "connected", "online", "system"],     "health"),
        (["temperature", "temp", "degrees", "how cold", "how warm"], "temperature"),
        (["help", "commands", "what can", "options", "what do"],     "help"),
    ]

    @classmethod
    def match(cls, text: str) -> str | None:
        text = text.lower()
        for keywords, cmd in cls.COMMANDS:
            for kw in keywords:
                if kw in text:
                    return cmd
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def fmt_temp(c):
    return f"{c * 9/5 + 32:.0f}°F  ({c:.1f}°C)"

def weather_emoji(condition):
    c = condition.lower()
    if "snow" in c:                     return "❄️"
    if "drizzle" in c or "rain" in c:  return "🌧️"
    if "thunder" in c:                  return "⛈️"
    if "fog" in c:                      return "🌫️"
    if "cloud" in c or "overcast" in c: return "☁️"
    if "clear" in c or "sunny" in c:    return "☀️"
    if "shower" in c:                   return "🌦️"
    return "🌡️"

def now_str():
    return datetime.now().strftime("%I:%M %p")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class SaltDispenserApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.esp      = ESPClient(ESP_BASE)
        self.voice    = VoiceEngine(ELEVENLABS_KEY, ELEVENLABS_VOICE)
        self.esp_data = {}
        self._mic_held     = False
        self._mic_thread   = None

        self.title("Salt Dispenser")
        self.geometry("700x700")
        self.resizable(False, False)
        self.configure(bg=BG)

        # Fonts
        self.f_huge  = tkfont.Font(family="Georgia", size=30, weight="bold")
        self.f_large = tkfont.Font(family="Georgia", size=20, weight="bold")
        self.f_med   = tkfont.Font(family="Georgia", size=14)
        self.f_med_b = tkfont.Font(family="Georgia", size=14, weight="bold")
        self.f_small = tkfont.Font(family="Georgia", size=12)
        self.f_tiny  = tkfont.Font(family="Georgia", size=10)
        self.f_btn   = tkfont.Font(family="Georgia", size=14, weight="bold")
        self.f_mic   = tkfont.Font(family="Georgia", size=13, weight="bold")

        self._build()
        self._start_poll()

        # Greet after 1.5 s so window is fully visible first
        self.after(1500, self._greet)

    # ── BUILD UI ──────────────────────────────────────────────────────────────
    def _build(self):
        # Top bar
        top = tk.Frame(self, bg=BLUE, height=64)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="🧂  Salt Dispenser",
                 font=self.f_large, bg=BLUE, fg=WHITE
                 ).pack(side="left", padx=24, pady=14)
        self.lbl_time = tk.Label(top, text=now_str(),
                                 font=self.f_small, bg=BLUE, fg="#bcd8f5")
        self.lbl_time.pack(side="right", padx=24)
        self.lbl_conn = tk.Label(top, text="Connecting…",
                                 font=self.f_tiny, bg=BLUE, fg="#bcd8f5")
        self.lbl_conn.pack(side="right", padx=4)

        # Main status card
        self.status_card = tk.Frame(self, bg=SURFACE,
                                    highlightbackground=GREY_LIGHT,
                                    highlightthickness=1)
        self.status_card.pack(fill="x", padx=24, pady=(16, 8))

        self.lbl_icon = tk.Label(self.status_card, text="⏳",
                                 font=tkfont.Font(size=42), bg=SURFACE)
        self.lbl_icon.pack(pady=(20, 4))

        self.lbl_main = tk.Label(self.status_card,
                                 text="Checking your walkway…",
                                 font=self.f_huge, bg=SURFACE, fg=TEXT,
                                 wraplength=620, justify="center")
        self.lbl_main.pack(pady=(0, 4))

        self.lbl_sub = tk.Label(self.status_card,
                                text="Please wait while we connect.",
                                font=self.f_med, bg=SURFACE, fg=TEXT_MED,
                                wraplength=580, justify="center")
        self.lbl_sub.pack(pady=(0, 20))

        # Weather tiles
        wx_row = tk.Frame(self, bg=BG)
        wx_row.pack(fill="x", padx=24, pady=(0, 8))
        self.tile_now  = self._tile(wx_row, "Right Now")
        self.tile_now.pack(side="left", expand=True, fill="both", padx=(0, 8))
        self.tile_next = self._tile(wx_row, "Next Hour")
        self.tile_next.pack(side="left", expand=True, fill="both")

        # Dispense button
        self.btn_dispense = tk.Button(
            self, text="  💧  Dispense Salt Now  ",
            font=self.f_btn, bg=BLUE, fg=WHITE,
            activebackground="#1a4f8a", activeforeground=WHITE,
            relief="flat", bd=0, padx=20, pady=12,
            cursor="hand2", command=self._manual_dispense)
        self.btn_dispense.pack(fill="x", padx=24, pady=(0, 8))

        # ── VOICE SECTION ──
        voice_frame = tk.Frame(self, bg=SURFACE,
                               highlightbackground=GREY_LIGHT,
                               highlightthickness=1)
        voice_frame.pack(fill="x", padx=24, pady=(0, 8))

        # Voice status label
        self.lbl_voice_status = tk.Label(voice_frame,
                                         text="🎙️  Press and hold to speak",
                                         font=self.f_med, bg=SURFACE, fg=TEXT_MED)
        self.lbl_voice_status.pack(pady=(12, 6))

        # Mic button — press and hold
        self.btn_mic = tk.Button(
            voice_frame,
            text="🎤  Hold to Talk",
            font=self.f_mic,
            bg=MIC_IDLE, fg=WHITE,
            activebackground=MIC_LISTEN,
            activeforeground=WHITE,
            relief="flat", bd=0,
            padx=30, pady=12,
            cursor="hand2"
        )
        self.btn_mic.pack(pady=(0, 12))

        # Bind press and release
        self.btn_mic.bind("<ButtonPress-1>",   self._mic_press)
        self.btn_mic.bind("<ButtonRelease-1>", self._mic_release)

        # Last heard label
        self.lbl_heard = tk.Label(voice_frame,
                                  text="",
                                  font=self.f_tiny, bg=SURFACE, fg=TEXT_LIGHT,
                                  wraplength=600, justify="center")
        self.lbl_heard.pack(pady=(0, 10))

        # Footer
        self.lbl_footer = tk.Label(self, text="Last updated: —",
                                   font=self.f_tiny, bg=BG, fg=TEXT_LIGHT)
        self.lbl_footer.pack(pady=(4, 6))

    # ── TILE WIDGET ───────────────────────────────────────────────────────────
    def _tile(self, parent, title):
        f = tk.Frame(parent, bg=SURFACE,
                     highlightbackground=GREY_LIGHT, highlightthickness=1)
        tk.Label(f, text=title, font=self.f_tiny,
                 bg=SURFACE, fg=TEXT_LIGHT).pack(pady=(12, 2))
        f._emoji = tk.Label(f, text="—", font=tkfont.Font(size=28), bg=SURFACE)
        f._emoji.pack()
        f._cond  = tk.Label(f, text="—", font=self.f_med_b,
                            bg=SURFACE, fg=TEXT, wraplength=260, justify="center")
        f._cond.pack(pady=(2, 0))
        f._temp  = tk.Label(f, text="—", font=self.f_small,
                            bg=SURFACE, fg=TEXT_MED)
        f._temp.pack(pady=(2, 12))
        return f

    def _update_tile(self, tile, emoji, condition, temp_c):
        tile._emoji.config(text=emoji)
        tile._cond.config(text=condition)
        tile._temp.config(
            text=fmt_temp(temp_c) if isinstance(temp_c, (int, float)) else "—")

    # ── POLLING ───────────────────────────────────────────────────────────────
    def _start_poll(self):
        self._tick_clock()
        def loop():
            while True:
                data = self.esp.status()
                self.after(0, self._refresh, data)
                time.sleep(POLL_MS / 1000)
        threading.Thread(target=loop, daemon=True).start()

    def _tick_clock(self):
        self.lbl_time.config(text=now_str())
        self.after(30000, self._tick_clock)

    def _refresh(self, data):
        if data is None:
            self._set_status(AMBER_LIGHT, AMBER, "📡",
                             "Device not reachable",
                             "Make sure the salt dispenser is plugged in and your Wi-Fi is working.\n"
                             "The app will keep trying automatically.")
            self.lbl_conn.config(text="● Offline", fg="#fbbf24")
            self._update_tile(self.tile_now,  "—", "No data", "—")
            self._update_tile(self.tile_next, "—", "No data", "—")
            return

        self.esp_data = data
        dispensing = data.get("dispensing",       False)
        healthy    = data.get("systemHealthy",    True)
        wx_now     = data.get("weatherCondition", "Unknown")
        temp_now   = data.get("temperature",      0)
        wx_next    = data.get("nextCondition",    "Unknown")
        temp_next  = data.get("nextTemperature",  0)

        if not healthy:
            self._set_status(RED_LIGHT, RED, "⚠️",
                             "Device needs attention",
                             "The salt dispenser may not be working correctly.\n"
                             "Please check the unit or contact support.")
        elif dispensing:
            self._set_status(GREEN_LIGHT, GREEN, "✅",
                             "Your walkway is protected",
                             "Salt is being dispensed automatically right now.")
        else:
            self._set_status(BLUE_LIGHT, BLUE, "🏠",
                             "Walkway is being monitored",
                             "No salt needed right now. The system will activate\n"
                             "automatically if conditions change.")

        self._update_tile(self.tile_now,  weather_emoji(wx_now),  wx_now,  temp_now)
        self._update_tile(self.tile_next, weather_emoji(wx_next), wx_next, temp_next)
        self.lbl_conn.config(text="● Connected", fg="#a8d4f5")
        self.lbl_footer.config(text=f"Last updated: {now_str()}")

    def _set_status(self, bg, fg, icon, main, sub):
        self.status_card.config(bg=bg)
        self.lbl_icon.config(text=icon, bg=bg)
        self.lbl_main.config(text=main, bg=bg, fg=fg)
        self.lbl_sub.config(text=sub,   bg=bg, fg=TEXT_MED)

    # ── MANUAL DISPENSE ───────────────────────────────────────────────────────
    def _manual_dispense(self):
        self.btn_dispense.config(state="disabled", text="  Sending…  ")
        def _do():
            result = self.esp.manual_dispense()
            ok = "error" not in result
            def _done():
                if ok:
                    self.btn_dispense.config(text="  ✓  Request Sent!  ", bg=GREEN)
                    self.after(3000, self._reset_dispense_btn)
                else:
                    self.btn_dispense.config(
                        text="  Could not reach device — try again  ",
                        bg=AMBER, state="normal")
                    self.after(3000, self._reset_dispense_btn)
            self.after(0, _done)
        threading.Thread(target=_do, daemon=True).start()

    def _reset_dispense_btn(self):
        self.btn_dispense.config(text="  💧  Dispense Salt Now  ",
                                 bg=BLUE, state="normal")

    # ── GREETING ──────────────────────────────────────────────────────────────
    def _greet(self):
        """Spoken greeting on app open using current ESP data."""
        data = self.esp_data
        if data:
            condition = data.get("weatherCondition", "unknown conditions")
            temp_c    = data.get("temperature", 0)
            temp_f    = int(temp_c * 9/5 + 32)
            dispensing = data.get("dispensing", False)
            healthy    = data.get("systemHealthy", True)

            if not healthy:
                status_line = "However, the device may need attention."
            elif dispensing:
                status_line = "Salt is currently being dispensed to protect your walkway."
            else:
                status_line = "Your walkway is being monitored and no salt is needed right now."

            greeting = (
                f"Hello! Welcome to your Salt Dispenser app. "
                f"Your device is connected and working. "
                f"Outside right now it is {temp_f} degrees and {condition.lower()}. "
                f"{status_line} "
                f"Press and hold the Talk button at any time to ask me a question."
            )
        else:
            greeting = (
                "Hello! Welcome to your Salt Dispenser app. "
                "I'm trying to connect to your device. "
                "Please make sure the salt dispenser is plugged in and nearby. "
                "Press and hold the Talk button at any time to ask me a question."
            )

        self.voice.speak(greeting)

    # ── MIC BUTTON ────────────────────────────────────────────────────────────
    def _mic_press(self, event):
        if self._mic_held:
            return
        self._mic_held = True
        self.btn_mic.config(bg=MIC_LISTEN, text="🔴  Listening…")
        self.lbl_voice_status.config(text="🎙️  Listening — release when done speaking")
        self.lbl_heard.config(text="")

        # Start recording on background thread
        self._mic_thread = threading.Thread(target=self._record, daemon=True)
        self._mic_thread.start()

    def _mic_release(self, event):
        # Signal the recognizer to stop (it will naturally stop on phrase_time_limit)
        # The _record thread handles the full cycle
        self._mic_held = False
        self.btn_mic.config(bg=MIC_THINK, text="⏳  Processing…")
        self.lbl_voice_status.config(text="⏳  Processing your request…")

    def _record(self):
        """Runs on background thread — listens then processes command."""
        text = self.voice.listen()
        self.after(0, self._handle_command, text)

    def _handle_command(self, text: str):
        """Back on main thread — match command and respond."""
        self.btn_mic.config(bg=MIC_IDLE, text="🎤  Hold to Talk")

        if not text:
            self.lbl_voice_status.config(text="🎙️  Didn't catch that — try again")
            self.lbl_heard.config(text="")
            self.voice.speak("Sorry, I didn't catch that. Please try again.")
            return

        self.lbl_heard.config(text=f'You said: "{text}"')
        cmd = CommandMatcher.match(text)
        data = self.esp_data

        if cmd is None:
            self.lbl_voice_status.config(text="🎙️  Press and hold to speak")
            self.voice.speak(
                "I'm not sure what you meant. "
                "Try saying things like: what's the weather, "
                "is salt dispensing, or help."
            )
            return

        # ── Build response based on matched command ──
        response = ""

        if cmd == "weather":
            if data:
                cond   = data.get("weatherCondition", "unknown")
                temp_c = data.get("temperature", 0)
                temp_f = int(temp_c * 9/5 + 32)
                response = f"Right now outside it is {temp_f} degrees Fahrenheit, {temp_c:.1f} Celsius, and {cond.lower()}."
            else:
                response = "I can't get weather data right now. The device may be offline."

        elif cmd == "forecast":
            if data:
                cond   = data.get("nextCondition", "unknown")
                temp_c = data.get("nextTemperature", 0)
                temp_f = int(temp_c * 9/5 + 32)
                response = f"Next hour it will be {temp_f} degrees Fahrenheit and {cond.lower()}."
            else:
                response = "Forecast data isn't available right now."

        elif cmd == "status":
            if data:
                dispensing = data.get("dispensing", False)
                cond       = data.get("weatherCondition", "unknown")
                temp_c     = data.get("temperature", 0)
                temp_f     = int(temp_c * 9/5 + 32)
                if dispensing:
                    response = f"Your walkway is being protected. Salt is dispensing right now. It is {temp_f} degrees and {cond.lower()} outside."
                else:
                    response = f"Your walkway is being monitored. No salt needed right now. It is {temp_f} degrees and {cond.lower()} outside."
            else:
                response = "The device is not connected right now."

        elif cmd == "dispensing":
            if data:
                dispensing = data.get("dispensing", False)
                response = "Yes, salt is being dispensed right now." if dispensing \
                           else "No, salt is not dispensing right now. The system will activate automatically when needed."
            else:
                response = "I can't check dispensing status — the device appears offline."

        elif cmd == "dispense_now":
            response = "Okay, I'll dispense salt now."
            self.after(100, self._manual_dispense)

        elif cmd == "health":
            if data:
                healthy = data.get("systemHealthy", False)
                rssi    = data.get("wifi_rssi", 0)
                response = f"The device is connected and working normally. Wi-Fi signal strength is {rssi} decibels." \
                           if healthy else "The device may need attention. Please check that it is plugged in."
            else:
                response = "The device is not reachable right now. Please check it is plugged in."

        elif cmd == "temperature":
            if data:
                temp_c = data.get("temperature", 0)
                temp_f = int(temp_c * 9/5 + 32)
                response = f"The current temperature outside is {temp_f} degrees Fahrenheit, or {temp_c:.1f} degrees Celsius."
            else:
                response = "Temperature data isn't available right now."

        elif cmd == "help":
            response = (
                "Here are things you can ask me. "
                "Say: what's the weather, "
                "what's the forecast, "
                "how's my walkway, "
                "is salt dispensing, "
                "dispense salt, "
                "is the device working, "
                "or what's the temperature."
            )

        self.lbl_voice_status.config(text="🎙️  Press and hold to speak")
        if response:
            self.voice.speak(response)


# ── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    SaltDispenserApp().mainloop()
