"""
relay_v3.py — Tailscale-to-ESP Bridge  (Laptop 2, DHCP version)
=================================================================
Works with Integrated_Test_v2.ino which uses DHCP instead of
a static IP. Before each demo, check Serial Monitor for the ESP's
current IP and paste it below as ESP_LOCAL_IP.

In practice the hotspot will give the ESP the same IP every time
via DHCP lease, so you likely only need to do this once.

Requirements:
  pip install flask requests

Startup order every demo:
  1. Power on ESP → wait for Serial Monitor to show IP
  2. Paste that IP into ESP_LOCAL_IP below
  3. Connect this laptop to the ESP's hotspot
  4. Run: python relay_v3.py
  5. Confirm at: http://localhost:8080/health
  6. Run: tailscale ip -4  → give that IP to Laptop 1
"""

from flask import Flask, request, Response
import requests
import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
ESP_LOCAL_IP = "x.x.x.x"          # ← paste ESP's IP from Serial Monitor here
                                   #   printed on boot as:
                                   #   [ESP]  IP Address: http://x.x.x.x
ESP_BASE     = f"http://{ESP_LOCAL_IP}"
RELAY_PORT   = 8080
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
request_count = 0


def log(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")


def forward(path, method, body=None):
    global request_count
    request_count += 1
    url = f"{ESP_BASE}/{path}"
    log(f"#{request_count}  {method} /{path}  →  {url}")

    try:
        if method == "GET":
            resp = requests.get(url, timeout=5)
        elif method == "POST":
            resp = requests.post(url, json=body, timeout=5)
        else:
            return Response('{"error":"Unsupported method"}', 405,
                            content_type="application/json")

        log(f"#{request_count}  ESP replied {resp.status_code}")
        return Response(
            resp.content,
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "application/json")
        )

    except requests.exceptions.ConnectionError:
        log(f"#{request_count}  ERROR — ESP not reachable at {ESP_BASE}")
        log("  Check: is this laptop on the ESP's hotspot?")
        log("  Check: is the ESP powered on?")
        log(f"  Check: is {ESP_LOCAL_IP} still the correct IP? (check Serial Monitor)")
        return Response(
            '{"error":"ESP not reachable — check power, hotspot, and IP in relay_v3.py"}',
            status=503,
            content_type="application/json"
        )
    except Exception as e:
        log(f"#{request_count}  ERROR — {e}")
        return Response(f'{{"error":"{str(e)}"}}', status=500,
                        content_type="application/json")


@app.route("/status", methods=["GET"])
def status():
    return forward("status", "GET")


@app.route("/update", methods=["POST"])
def update():
    body = request.get_json(silent=True) or {}
    return forward("update", "POST", body)


@app.route("/health", methods=["GET"])
def health():
    """
    Open in browser to confirm relay is alive before starting demo:
      http://localhost:8080/health
    or from Laptop 1 via Tailscale:
      http://<laptop2-tailscale-ip>:8080/health
    """
    return {
        "relay": "online",
        "esp_target": ESP_BASE,
        "requests_forwarded": request_count
    }, 200


if __name__ == "__main__":
    print()
    print("=" * 56)
    print("  Salt Dispenser — Tailscale Relay v3  (Laptop 2)")
    print("=" * 56)
    print(f"  Forwarding all requests to:  {ESP_BASE}")
    print(f"  Relay listening on port:     {RELAY_PORT}")
    print()

    if ESP_LOCAL_IP == "x.x.x.x":
        print("  ⚠️  WARNING: ESP_LOCAL_IP is not set!")
        print("  Open Serial Monitor, reboot ESP, copy the IP,")
        print("  paste it into relay_v3.py as ESP_LOCAL_IP, then re-run.")
        print()
    else:
        print("  Pre-demo checklist:")
        print("  [ ] ESP is powered and Serial Monitor confirmed IP")
        print(f"  [ ] ESP_LOCAL_IP is set to {ESP_LOCAL_IP}")
        print("  [ ] This laptop is on the ESP's hotspot")
        print("  [ ] Tailscale is running (green icon in system tray)")
        print()
        print("  Get this laptop's Tailscale IP for Laptop 1:")
        print("    tailscale ip -4")
        print()
        print("  Verify relay is working:")
        print(f"    http://localhost:{RELAY_PORT}/health")

    print("=" * 56)
    print()

    app.run(host="0.0.0.0", port=RELAY_PORT, debug=False)
