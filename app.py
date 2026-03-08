"""
app_tailscale_v2.py — Salt Dispenser  (run on Laptop 1)
=========================================================
This is the final demo version of the app.
Laptop 1 (this file) can be on ANY network.
Laptop 2 (relay_v2.py) must be on the ESP's hotspot.
Both laptops must have Tailscale installed and running.

The only difference from app_tester.py:
  - ESP_IP   = Laptop 2's Tailscale IP  (run: tailscale ip -4 on Laptop 2)
  - ESP_PORT = 8080
  - lbl_conn shows "Connected via Tailscale"

Everything else — UI, Gemini, ElevenLabs, voice — is identical.

Pre-demo checklist:
  [ ] Tailscale installed on both laptops, signed into same account
  [ ] relay_v2.py running on Laptop 2
  [ ] Laptop 2's Tailscale IP entered below as ESP_IP
  [ ] Both API keys filled in below
  [ ] Laptop 1 deliberately on a DIFFERENT network to show remote access
"""

import tkinter as tk
from tkinter import font as tkfont
import threading
import requests
import time
import queue
from datetime import datetime

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

try:
    from google import genai
    GEMINI_OK = True
except ImportError:
    GEMINI_OK = False

# ── CONFIG — only things to change ───────────────────────────────────────────
ESP_IP           = "Laptop 2's Tailscale IP"              # ← Laptop 2's Tailscale IP
                                             #   run on Laptop 2: tailscale ip -4
ESP_PORT         = 8080                      # relay port — do not change
ESP_BASE         = f"http://{ESP_IP}:{ESP_PORT}"
POLL_MS          = 5000

ELEVENLABS_KEY   = "Your ElevenLabs API Key"    # ← paste ElevenLabs key here
ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"   # Rachel

GEMINI_KEY       = "Your Gemini API Key"         # ← paste Gemini key here
# ─────────────────────────────────────────────────────────────────────────────

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
MIC_GEMINI  = "#7c3aed"


# ══════════════════════════════════════════════════════════════════════════════
#  ESP CLIENT
#  Points to relay_v2.py on Laptop 2 via Tailscale.
#  The relay forwards everything to the ESP transparently.
# ══════════════════════════════════════════════════════════════════════════════
class ESPClient:
    def __init__(self, base):
        self.base = base

    def status(self):
        try:
            return requests.get(f"{self.base}/status", timeout=5).json()
        except Exception:
            return None

    def manual_dispense(self):
        try:
            return requests.post(f"{self.base}/update",
                                 json={"manualDispense": True}, timeout=5).json()
        except Exception as e:
            return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
#  GEMINI ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class GeminiEngine:
    def __init__(self, api_key: str):
        if GEMINI_OK and api_key != "YOUR_GEMINI_API_KEY":
            self.client = genai.Client(api_key=api_key)
            self.ready = True
            print("[GEMINI] Connected — Gemini 2.5 Flash ready")
        else:
            self.client = None
            self.ready = False
            print("[GEMINI] Not configured — falling back to basic responses")

    def ask(self, user_text: str, esp_data: dict) -> str:
        if not self.ready:
            return self._fallback(user_text, esp_data)

        if esp_data:
            dispensing  = esp_data.get("dispensing", False)
            condition   = esp_data.get("weatherCondition", "unknown")
            temp_c      = esp_data.get("temperature", 0)
            temp_f      = int(temp_c * 9 / 5 + 32)
            next_cond   = esp_data.get("nextCondition", "unknown")
            next_temp_c = esp_data.get("nextTemperature", 0)
            next_temp_f = int(next_temp_c * 9 / 5 + 32)
            healthy     = esp_data.get("systemHealthy", True)
            context = (
                f"Device status: {'dispensing salt' if dispensing else 'monitoring, not dispensing'}. "
                f"System healthy: {healthy}. "
                f"Current weather: {condition}, {temp_f}°F ({temp_c:.1f}°C). "
                f"Next hour forecast: {next_cond}, {next_temp_f}°F ({next_temp_c:.1f}°C). "
            )
        else:
            context = "The salt dispenser device is currently offline or unreachable."

        prompt = (
            "You are a friendly voice assistant built into a smart automatic salt dispenser. "
            "The device monitors weather and automatically disperses salt on walkways when "
            "conditions are icy or wet. Your users are elderly people who may not be tech-savvy. "
            "Always speak in plain, warm, reassuring language. "
            "Reply in 1 to 2 short conversational sentences only — no lists, no bullet points. "
            "Never mention technical details like IP addresses, JSON, or API. "
            f"Current device and weather context: {context}"
            f"The user asked or said: \"{user_text}\""
        )

        try:
            result = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            response = result.text.strip()
            print(f"[GEMINI] Response: {response}")
            return response
        except Exception as e:
            print(f"[GEMINI ERROR] {e}")
            return "I'm having trouble thinking right now. Please try asking again in a moment."

    def _fallback(self, text: str, esp_data: dict) -> str:
        text = text.lower()
        if not esp_data:
            return "The device is not connected right now."
        condition  = esp_data.get("weatherCondition", "unknown")
        temp_c     = esp_data.get("temperature", 0)
        temp_f     = int(temp_c * 9 / 5 + 32)
        dispensing = esp_data.get("dispensing", False)
        if any(w in text for w in ["weather", "outside", "condition"]):
            return f"It is currently {temp_f} degrees and {condition.lower()} outside."
        if any(w in text for w in ["dispensing", "salt", "walkway", "status"]):
            return "Salt is being dispensed right now." if dispensing \
                   else "Your walkway is being monitored and no salt is needed right now."
        if any(w in text for w in ["temperature", "temp", "degrees"]):
            return f"The temperature is {temp_f} degrees Fahrenheit."
        return "I'm not sure about that. Try asking about the weather or your walkway status."


# ══════════════════════════════════════════════════════════════════════════════
#  DISPENSE COMMAND DETECTOR
# ══════════════════════════════════════════════════════════════════════════════
DISPENSE_KEYWORDS = [
    "dispense", "dispense salt", "add salt", "start dispensing",
    "release salt", "spread salt", "activate"
]

def is_dispense_command(text: str) -> bool:
    return any(kw in text.lower() for kw in DISPENSE_KEYWORDS)


# ══════════════════════════════════════════════════════════════════════════════
#  VOICE ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class VoiceEngine:
    def __init__(self, api_key: str, voice: str):
        self.voice    = voice
        self.speaking = False
        self._tts_queue = queue.Queue()

        if ELEVENLABS_OK and api_key != "YOUR_ELEVENLABS_API_KEY":
            self.client = ElevenLabs(api_key=api_key)
            self.tts_ready = True
            print("[VOICE] ElevenLabs TTS ready")
        else:
            self.client    = None
            self.tts_ready = False
            print("[VOICE] ElevenLabs not configured — TTS disabled")

        if SR_OK:
            self.recognizer = sr.Recognizer()
            self.mic        = sr.Microphone()
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
                import tempfile, os, pygame
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    for chunk in audio:
                        f.write(chunk)
                    tmp_path = f.name
                pygame.mixer.init()
                pygame.mixer.music.load(tmp_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                pygame.mixer.quit()
                os.unlink(tmp_path)
            else:
                print(f"[TTS FALLBACK] {text}")
        except Exception as e:
            print(f"[TTS ERROR] {e}")
        finally:
            self.speaking = False

    def listen(self) -> str:
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
        self.esp    = ESPClient(ESP_BASE)
        self.voice  = VoiceEngine(ELEVENLABS_KEY, ELEVENLABS_VOICE)
        self.gemini = GeminiEngine(GEMINI_KEY)
        self.esp_data    = {}
        self._mic_held   = False
        self._mic_thread = None

        self.title("Salt Dispenser")
        self.geometry("700x700")
        self.resizable(False, False)
        self.configure(bg=BG)

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
        self.after(1500, self._greet)

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

        # Status card
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

        # Voice section
        voice_frame = tk.Frame(self, bg=SURFACE,
                               highlightbackground=GREY_LIGHT,
                               highlightthickness=1)
        voice_frame.pack(fill="x", padx=24, pady=(0, 8))
        self.lbl_voice_status = tk.Label(voice_frame,
                                         text="🎙️  Press and hold to speak",
                                         font=self.f_med, bg=SURFACE, fg=TEXT_MED)
        self.lbl_voice_status.pack(pady=(12, 6))
        self.btn_mic = tk.Button(
            voice_frame, text="🎤  Hold to Talk",
            font=self.f_mic, bg=MIC_IDLE, fg=WHITE,
            activebackground=MIC_LISTEN, activeforeground=WHITE,
            relief="flat", bd=0, padx=30, pady=12, cursor="hand2"
        )
        self.btn_mic.pack(pady=(0, 6))
        self.btn_mic.bind("<ButtonPress-1>",   self._mic_press)
        self.btn_mic.bind("<ButtonRelease-1>", self._mic_release)
        self.lbl_heard = tk.Label(voice_frame, text="",
                                  font=self.f_tiny, bg=SURFACE, fg=TEXT_LIGHT,
                                  wraplength=600, justify="center")
        self.lbl_heard.pack(pady=(0, 10))

        self.lbl_footer = tk.Label(self, text="Last updated: —",
                                   font=self.f_tiny, bg=BG, fg=TEXT_LIGHT)
        self.lbl_footer.pack(pady=(4, 6))

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
        f._temp  = tk.Label(f, text="—", font=self.f_small, bg=SURFACE, fg=TEXT_MED)
        f._temp.pack(pady=(2, 12))
        return f

    def _update_tile(self, tile, emoji, condition, temp_c):
        tile._emoji.config(text=emoji)
        tile._cond.config(text=condition)
        tile._temp.config(
            text=fmt_temp(temp_c) if isinstance(temp_c, (int, float)) else "—")

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
                             "Make sure the salt dispenser is plugged in and the relay is running.\n"
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
        # shows judges this is running over Tailscale
        self.lbl_conn.config(text="● Connected via Tailscale", fg="#a8d4f5")
        self.lbl_footer.config(text=f"Last updated: {now_str()}")

    def _set_status(self, bg, fg, icon, main, sub):
        self.status_card.config(bg=bg)
        self.lbl_icon.config(text=icon, bg=bg)
        self.lbl_main.config(text=main, bg=bg, fg=fg)
        self.lbl_sub.config(text=sub,   bg=bg, fg=TEXT_MED)

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

    def _greet(self):
        data = self.esp_data
        if data:
            condition  = data.get("weatherCondition", "unknown conditions")
            temp_c     = data.get("temperature", 0)
            temp_f     = int(temp_c * 9/5 + 32)
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
                f"Press and hold the Talk button at any time to ask me anything."
            )
        else:
            greeting = (
                "Hello! Welcome to your Salt Dispenser app. "
                "I'm trying to connect to your device. "
                "Please make sure the salt dispenser is plugged in and nearby. "
                "Press and hold the Talk button at any time to ask me anything."
            )
        self.voice.speak(greeting)

    def _mic_press(self, event):
        if self._mic_held:
            return
        self._mic_held = True
        self.btn_mic.config(bg=MIC_LISTEN, text="🔴  Listening…")
        self.lbl_voice_status.config(text="🎙️  Listening — release when done speaking")
        self.lbl_heard.config(text="")
        self._mic_thread = threading.Thread(target=self._record, daemon=True)
        self._mic_thread.start()

    def _mic_release(self, event):
        self._mic_held = False
        self.btn_mic.config(bg=MIC_THINK, text="⏳  Processing…")
        self.lbl_voice_status.config(text="⏳  Processing your request…")

    def _record(self):
        text = self.voice.listen()
        self.after(0, self._handle_command, text)

    def _handle_command(self, text: str):
        self.btn_mic.config(bg=MIC_IDLE, text="🎤  Hold to Talk")

        if not text:
            self.lbl_voice_status.config(text="🎙️  Didn't catch that — try again")
            self.lbl_heard.config(text="")
            self.voice.speak("Sorry, I didn't catch that. Please try again.")
            return

        self.lbl_heard.config(text=f'You said: "{text}"')

        if is_dispense_command(text):
            self.lbl_voice_status.config(text="💧  Dispensing salt now…")
            self.voice.speak("Okay, dispensing salt now.")
            self.after(100, self._manual_dispense)
            self.lbl_voice_status.config(text="🎙️  Press and hold to speak")
            return

        self.btn_mic.config(bg=MIC_GEMINI, text="✨  Thinking…")
        self.lbl_voice_status.config(text="✨  Asking assistant…")

        def _ask_gemini():
            response = self.gemini.ask(text, self.esp_data)
            def _respond():
                self.btn_mic.config(bg=MIC_IDLE, text="🎤  Hold to Talk")
                self.lbl_voice_status.config(text="🎙️  Press and hold to speak")
                self.voice.speak(response)
            self.after(0, _respond)

        threading.Thread(target=_ask_gemini, daemon=True).start()


# ── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    SaltDispenserApp().mainloop()
