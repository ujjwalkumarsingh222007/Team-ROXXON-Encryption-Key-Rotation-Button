"""
Encryption Key Rotation Button — Flask Backend
===============================================
REST API for a hybrid university prototype:

  REAL:       AWS KMS (RotateKeyOnDemand)
  SIMULATED:  AWS IoT Core, AWS Lambda, ESP32 button, OLED display

Endpoints
---------
  GET  /                      → Serve frontend (index.html)
  GET  /api/health             → Server health check
  GET  /api/status             → Full system status (AWS service states)
  GET  /api/kms/status         → Safe KMS key metadata (real or simulated)
  POST /api/rotate             → Trigger rotation (demo or real KMS)
  POST /api/rotate-key         → Alias for /api/rotate (backward compat)
  GET  /api/rotation-status    → Last rotation state
  GET  /api/history            → Audit log of all rotations
  GET  /api/device-status      → Simulated ESP32 telemetry

Security notes
--------------
  - AWS credentials are NEVER returned to the frontend.
  - Key material / private cryptographic data is NEVER returned.
  - Demo mode is the safe default (APP_MODE=demo in .env).
  - Real KMS mode only fires kms:RotateKeyOnDemand — no IAM creation.
"""

import os
import json
import uuid
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request

# Load .env before importing managers so env vars are available
load_dotenv()

from kms import KMSManager
from aws_iot import AWSIoTManager

app = Flask(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "history.json")

# ---------------------------------------------------------------------------
# Service managers (safe to construct even without credentials)
# ---------------------------------------------------------------------------
kms_mgr = KMSManager()
iot_mgr = AWSIoTManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_app_mode() -> str:
    """Returns 'real' only when APP_MODE=real is set in .env, else 'demo'."""
    return "real" if os.getenv("APP_MODE", "demo").lower() == "real" else "demo"


def load_data() -> dict:
    """Load persistent data from JSON file, creating defaults on first run."""
    default_device = {
        "device_id": os.getenv("DEVICE_ID", "ESP32-001"),
        "device_type": "ESP32-WROOM-32D (32-bit Dual-Core)",
        "firmware_version": "v2.4.1-rotator-release",
        "gpio_button_pin": "GPIO 0 (Boot Button / Pull-Up)",
        "oled_i2c_address": "0x3C (SDA: GPIO 21, SCL: GPIO 22)",
        "wifi_ssid": "Connected Network",
        "wifi_status": "Connected",
        "mqtt_status": "Connected (Simulated)",
        "ip_address": "192.168.1.142",
        "mac_address": "24:6F:28:7A:B4:9C",
        "wifi_rssi": "-54 dBm (Good)",
        "button_status": "IDLE (Pull-Up HIGH)",
        "oled_status": "Active (SSD1306 128×64)",
        "last_ping": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        default_data = {
            "current_key": {
                "key_id": os.getenv("KMS_KEY_ID", "4f206dc3-dea4-4fcf-baee-8624627af374"),
                "arn": (
                    f"arn:aws:kms:{os.getenv('AWS_REGION','us-east-1')}"
                    ":748291038472:key/4f206dc3-dea4-4fcf-baee-8624627af374"
                ),
                "status": "Active",
                "version": 1,
                "rotation_count": 0,
                "key_spec": "SYMMETRIC_DEFAULT",
                "key_usage": "ENCRYPT_DECRYPT",
                "origin": "AWS_KMS",
                "last_rotation": "Never",
            },
            "stats": {
                "total_rotations": 0,
                "successful_rotations": 0,
                "failed_rotations": 0,
                "last_rotation": "Never",
            },
            "history": [],
            "logs": [],
            "device": default_device,
            "last_rotation_state": {
                "request_id": None,
                "status": "IDLE",
                "started_at": None,
                "completed_at": None,
                "duration_sec": 0,
                "steps": [],
            },
        }
        save_data(default_data)
        return default_data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "device" not in data or not data["device"]:
            data["device"] = default_device
        return data
    except Exception:
        return {}


def save_data(data: dict):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        print(f"[WARN] Could not save data: {exc}")


# ---------------------------------------------------------------------------
# Routes — Frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — Health
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def api_health():
    mode = get_app_mode()
    kms_conf = kms_mgr.is_configured()
    iot_conf = iot_mgr.is_configured()
    return jsonify({
        "backend": "online",
        "mode": mode,
        "kms_configured": kms_conf,
        "iot_configured": iot_conf,
        "aws": "configured" if kms_conf else "not configured",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Routes — Status
# ---------------------------------------------------------------------------

@app.route("/api/status", methods=["GET"])
def api_status():
    data = load_data()
    mode = get_app_mode()

    # Only fetch live KMS metadata in real mode to avoid unnecessary API calls
    kms_meta = None
    if mode == "real" and kms_mgr.is_configured():
        kms_meta = kms_mgr.get_kms_status()

    def _svc_status(configured, real_status):
        if mode == "real" and configured:
            return real_status or "Connected"
        if mode == "demo":
            return "Simulation Mode"
        return "Not Configured"

    aws_services = {
        "iot_core": {
            "name": "AWS IoT Core",
            "status": _svc_status(iot_mgr.is_configured(), "Connected"),
            "configured": iot_mgr.is_configured(),
            "note": "Simulated in university lab prototype",
            "protocol": "MQTT over TLS v1.3 (Port 8883)",
        },
        "lambda": {
            "name": "AWS Lambda",
            "status": _svc_status(False, "Ready"),
            "configured": False,
            "note": "Simulated — IAM role creation restricted in university lab",
            "function_name": "ESP32-KeyRotationHandler",
            "runtime": "Python 3.12",
        },
        "kms": {
            "name": "AWS KMS",
            "status": (
                (kms_meta.get("status") if kms_meta else None)
                or ("Simulation Mode" if mode == "demo" else "Not Configured")
            ),
            "configured": kms_mgr.is_configured(),
            "key_id": (
                kms_meta.get("key_id") if kms_meta else data.get("current_key", {}).get("key_id", "")
            ),
            "key_ref": kms_mgr.key_id or "4f206dc3-dea4-4fcf-baee-8624627af374",
            "note": "REAL AWS KMS — only service called directly in this prototype",
        },
    }

    current_key = dict(data.get("current_key", {}))

    if mode == "real":
        current_key["key_id"] = (kms_meta.get("key_id") if (kms_meta and kms_meta.get("configured")) else current_key.get("key_id", "4f206dc3-dea4-4fcf-baee-8624627af374"))
        current_key["status"] = (kms_meta.get("status") if (kms_meta and kms_meta.get("configured")) else "Active")
        current_key["rotation_status"] = (kms_meta.get("rotation_status") if (kms_meta and kms_meta.get("configured")) else "Ready")
        current_key["last_rotation"] = (kms_meta.get("last_rotated") if (kms_meta and kms_meta.get("configured")) else "Not available")
        current_key["origin"] = "AWS_KMS (Real)"
    else:
        current_key["status"] = "Active (Simulated)"
        current_key["rotation_status"] = f"v{current_key.get('version', 1):02d} (Simulated)"
        current_key["origin"] = "AWS_KMS (Simulated)"

    return jsonify({
        "status": "online",
        "mode": mode,
        "aws_services": aws_services,
        "device": data.get("device", {}),
        "current_key": current_key,
        "stats": data.get("stats", {}),
        "recent_logs": data.get("logs", [])[-10:],
        "oled": {
            "header": "KEY ROTATOR",
            "line1": "DEVICE READY",
            "line2": "PRESS BUTTON",
            "version": f"{current_key.get('version', 1):02d}",
            "status": "IDLE",
        },
        "system_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ---------------------------------------------------------------------------
# Routes — KMS Status (dedicated endpoint)
# ---------------------------------------------------------------------------

@app.route("/api/kms/status", methods=["GET"])
def api_kms_status():
    """
    Return safe KMS key metadata.
    - In demo mode: returns simulated data clearly marked as simulated.
    - In real mode: calls AWS KMS DescribeKey and returns safe fields only.
    NEVER returns key material, credentials, or secret data.
    """
    mode = get_app_mode()

    if mode == "demo" or not kms_mgr.is_configured():
        data = load_data()
        current_key = data.get("current_key", {})
        return jsonify({
            "mode": "demo",
            "configured": kms_mgr.is_configured(),
            "simulated": True,
            "key_ref": kms_mgr.key_id or "4f206dc3-dea4-4fcf-baee-8624627af374",
            "key_id": current_key.get("key_id", "4f206dc3-dea4-4fcf-baee-8624627af374"),
            "status": "Simulation Mode",
            "note": (
                "Demo mode: all KMS operations are simulated locally. "
                "No real AWS API calls are made."
                if not kms_mgr.is_configured()
                else "Set APP_MODE=real in .env to use real AWS KMS."
            ),
        })

    # Real mode — call AWS KMS
    meta = kms_mgr.get_kms_status()
    return jsonify({
        "mode": "real",
        "configured": True,
        "simulated": False,
        **meta,
    })


# ---------------------------------------------------------------------------
# Routes — Device Status
# ---------------------------------------------------------------------------

@app.route("/api/device-status", methods=["GET"])
def api_device_status():
    data = load_data()
    device = data.get("device", {})
    device["last_ping"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"device": device, "mode": get_app_mode(), "status": "online"})


# ---------------------------------------------------------------------------
# Routes — Rotation Status
# ---------------------------------------------------------------------------

@app.route("/api/rotation-status", methods=["GET"])
def api_rotation_status():
    data = load_data()
    return jsonify({
        "rotation_state": data.get("last_rotation_state", {}),
        "current_key": data.get("current_key", {}),
        "stats": data.get("stats", {}),
    })


# ---------------------------------------------------------------------------
# Routes — History
# ---------------------------------------------------------------------------

@app.route("/api/history", methods=["GET"])
def api_history():
    data = load_data()
    return jsonify({
        "history": list(reversed(data.get("history", []))),
        "stats": data.get("stats", {}),
    })


# ---------------------------------------------------------------------------
# Routes — Rotate Key  (Main Logic)
# ---------------------------------------------------------------------------

@app.route("/api/rotate", methods=["POST"])
def api_rotate():
    """
    Handle a key rotation request.

    Request body:
        { "mode": "demo" | "real", "scenario": "none" | "iot_timeout" |
          "lambda_error" | "kms_error" | "oled_error" }

    Modes:
        demo — fully simulated, no AWS calls. KMS stage is labelled
               "Simulated KMS" so the result is never misleading.
        real — calls kms:RotateKeyOnDemand only. IoT/Lambda/OLED remain
               simulated. Requires KMS_KEY_ID and AWS credentials in .env.

    Security:
        - No credentials are returned to the frontend.
        - No key material is returned.
        - Demo failure scenarios NEVER affect the real AWS KMS operation.
    """
    req_json = request.get_json(silent=True) or {}
    mode_requested = req_json.get("mode", get_app_mode())
    forced_scenario = req_json.get("scenario", "none")
    device_id = req_json.get("device_id", "ESP32-001")

    # Failure scenarios are only valid in demo mode — never in real mode
    if mode_requested == "real":
        forced_scenario = "none"

    data = load_data()
    start_time = time.time()
    req_id = f"ROT-{uuid.uuid4().hex[:8].upper()}"
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    exec_steps = [
        {
            "name": "Button pressed",
            "stage": "ESP32",
            "status": "done",
            "detail": f"Virtual button trigger ({device_id}) — Simulated",
        },
        {
            "name": "ESP32 request serialized",
            "stage": "ESP32",
            "status": "done",
            "detail": f"JSON payload created (Request ID: {req_id})",
        },
    ]

    # -----------------------------------------------------------------------
    # DEMO FAILURE SCENARIOS
    # -----------------------------------------------------------------------

    if forced_scenario == "iot_timeout":
        time.sleep(0.4)
        exec_steps.append({
            "name": "AWS IoT Core connection",
            "stage": "AWS IoT Core",
            "status": "failed",
            "detail": "SIMULATED: Connection timed out on topic esp32/key_rotation/request",
        })
        _record_failure(data, req_id, device_id, timestamp_str, start_time,
                        "AWS IoT Core connection timeout (Simulated)", mode_requested)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "AWS IoT Core Connection Timeout",
            "message": "Simulated IoT Core connection failure.",
            "solution": "In production: check Wi-Fi, MQTT endpoint, and IoT Core policy.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2),
            "kms_mode": "simulated",
        }), 400

    if forced_scenario == "lambda_error":
        time.sleep(0.4)
        exec_steps.append({
            "name": "AWS IoT Core received request",
            "stage": "AWS IoT Core",
            "status": "done",
            "detail": "SIMULATED: MQTT QoS 1 message received on topic rule",
        })
        exec_steps.append({
            "name": "Lambda invocation",
            "stage": "AWS Lambda",
            "status": "failed",
            "detail": "SIMULATED: Lambda execution error — Timeout after 15 s",
        })
        _record_failure(data, req_id, device_id, timestamp_str, start_time,
                        "Lambda execution failure (Simulated)", mode_requested)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "AWS Lambda Execution Failure",
            "message": "Simulated Lambda timeout failure.",
            "solution": "In production: check CloudWatch logs for ESP32-KeyRotationHandler.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2),
            "kms_mode": "simulated",
        }), 400

    if forced_scenario == "kms_error":
        time.sleep(0.4)
        exec_steps.append({
            "name": "AWS IoT Core received request",
            "stage": "AWS IoT Core",
            "status": "done",
            "detail": "SIMULATED: MQTT topic rule matched",
        })
        exec_steps.append({
            "name": "Lambda triggered",
            "stage": "AWS Lambda",
            "status": "done",
            "detail": "SIMULATED: Function invoked",
        })
        exec_steps.append({
            "name": "AWS KMS Key Rotation",
            "stage": "AWS KMS",
            "status": "failed",
            "detail": "SIMULATED: AccessDeniedException — kms:RotateKeyOnDemand not permitted",
        })
        _record_failure(data, req_id, device_id, timestamp_str, start_time,
                        "KMS AccessDeniedException (Simulated)", mode_requested)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "AWS KMS Permission Denied",
            "message": "Simulated KMS permission failure.",
            "solution": "In production: add kms:RotateKeyOnDemand to the Lambda IAM execution role.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2),
            "kms_mode": "simulated",
        }), 400

    if forced_scenario == "oled_error":
        time.sleep(0.4)
        exec_steps.append({
            "name": "AWS IoT Core received request",
            "stage": "AWS IoT Core",
            "status": "done",
            "detail": "SIMULATED: MQTT topic rule matched",
        })
        exec_steps.append({
            "name": "Lambda triggered",
            "stage": "AWS Lambda",
            "status": "done",
            "detail": "SIMULATED: Function invoked",
        })
        exec_steps.append({
            "name": "AWS KMS Key Rotation",
            "stage": "AWS KMS",
            "status": "done",
            "detail": "SIMULATED: Key material rotated (Simulated KMS)",
        })
        exec_steps.append({
            "name": "Response returned to ESP32",
            "stage": "AWS IoT Core",
            "status": "done",
            "detail": "SIMULATED: Response published to esp32/key_rotation/response",
        })
        exec_steps.append({
            "name": "OLED display update",
            "stage": "ESP32 OLED",
            "status": "failed",
            "detail": "SIMULATED: I2C bus error — SSD1306 not responding at 0x3C",
        })
        _record_failure(data, req_id, device_id, timestamp_str, start_time,
                        "OLED I2C failure (Simulated)", mode_requested)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "OLED Display I2C Error",
            "message": "Simulated OLED display failure (key WAS rotated, display failed).",
            "solution": "In production: check SDA/SCL wiring (GPIO 21/22) and I2C address 0x3C.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2),
            "kms_mode": "simulated",
        }), 400

    # -----------------------------------------------------------------------
    # REAL KMS MODE
    # -----------------------------------------------------------------------

    if mode_requested == "real":
        if not kms_mgr.is_configured():
            return jsonify({
                "success": False,
                "status": "FAILED",
                "error": "AWS KMS Not Configured",
                "message": (
                    "KMS_KEY_ID is not set or AWS credentials are not available. "
                    "Check your .env file."
                ),
                "solution": (
                    "Set KMS_KEY_ID=4f206dc3-dea4-4fcf-baee-8624627af374 and ensure "
                    "AWS credentials are available in .env, ~/.aws/credentials, "
                    "or environment variables."
                ),
                "kms_mode": "real",
            }), 400

        # Stages 1-3 are simulated even in real mode (no IoT/Lambda in lab)
        exec_steps.append({
            "name": "AWS IoT Core (Simulated)",
            "stage": "AWS IoT Core",
            "status": "done",
            "detail": "Simulated: MQTT request routed to backend (IoT Core not configured in lab)",
        })
        exec_steps.append({
            "name": "AWS Lambda (Simulated)",
            "stage": "AWS Lambda",
            "status": "done",
            "detail": "Simulated: Backend calls KMS directly (Lambda not configured in lab)",
        })

        # Stage 4 — REAL KMS call
        kms_res = kms_mgr.rotate_key_on_demand()

        if not kms_res.get("success"):
            exec_steps.append({
                "name": "AWS KMS Key Rotation",
                "stage": "AWS KMS",
                "status": "failed",
                "detail": kms_res.get("message", "KMS error"),
            })
            _record_failure(data, req_id, device_id, timestamp_str, start_time,
                            kms_res.get("message", "KMS error"), mode_requested)
            save_data(data)
            return jsonify({
                "success": False,
                "request_id": req_id,
                "status": "FAILED",
                "error": kms_res.get("error_type", "KMS_ERROR"),
                "message": kms_res.get("message"),
                "solution": kms_res.get("solution"),
                "steps": exec_steps,
                "duration_sec": round(time.time() - start_time, 2),
                "kms_mode": "real",
            }), 400

        # Real KMS success
        rotation_count = kms_res.get("rotation_count", 1)
        exec_steps.append({
            "name": "AWS KMS Key Rotation",
            "stage": "AWS KMS",
            "status": "done",
            "detail": (
                f"REAL AWS KMS: key material rotated on-demand. "
                f"Key ID unchanged. Rotation #{rotation_count}."
            ),
        })
        exec_steps.append({
            "name": "Response to ESP32 (Simulated)",
            "stage": "AWS IoT Core",
            "status": "done",
            "detail": "Simulated: Response would be published to esp32/key_rotation/response",
        })
        exec_steps.append({
            "name": "OLED Updated (Simulated)",
            "stage": "ESP32 OLED",
            "status": "done",
            "detail": "Simulated: SSD1306 display would show ROTATION SUCCESS",
        })

        duration = round(time.time() - start_time, 2)

        # Update persistent store — key ID stays the same
        key_id = kms_res.get("key_id", data["current_key"]["key_id"])
        data["current_key"]["key_id"] = key_id
        data["current_key"]["version"] = rotation_count
        data["current_key"]["last_rotation"] = timestamp_str
        data["current_key"]["rotation_count"] = rotation_count
        data["current_key"]["status"] = "Active"
        _record_success_stats(data, timestamp_str)

        hist_entry = {
            "timestamp": timestamp_str,
            "request_id": req_id,
            "device_id": device_id,
            "key_id": key_id,
            "version": rotation_count,
            "version_display": f"{rotation_count:02d}",
            "status": "SUCCESS",
            "duration_sec": duration,
            "mode": "real",
            "kms_mode": "REAL",
        }
        data["history"].append(hist_entry)
        save_data(data)

        return jsonify({
            "success": True,
            "request_id": req_id,
            "status": "SUCCESS",
            "key_id": key_id,                      # same UUID — key material changed, ID did not
            "rotation_count": rotation_count,
            "version": rotation_count,
            "version_display": f"{rotation_count:02d}",
            "steps": exec_steps,
            "duration_sec": duration,
            "timestamp": timestamp_str,
            "mode": "real",
            "kms_mode": "REAL",
            "kms_note": (
                "Real AWS KMS RotateKeyOnDemand was called. "
                "The Key ID is unchanged. Only the backing key material was rotated."
            ),
        })

    # -----------------------------------------------------------------------
    # DEMO MODE (fully simulated — no AWS calls)
    # -----------------------------------------------------------------------

    time.sleep(0.3)
    exec_steps.append({
        "name": "AWS IoT Core (Simulated)",
        "stage": "AWS IoT Core",
        "status": "done",
        "detail": "SIMULATED: MQTT QoS 1 received on esp32/key_rotation/request",
    })
    exec_steps.append({
        "name": "AWS Lambda (Simulated)",
        "stage": "AWS Lambda",
        "status": "done",
        "detail": "SIMULATED: Function ESP32-KeyRotationHandler executed",
    })

    new_version = data["current_key"].get("version", 1) + 1
    exec_steps.append({
        "name": "AWS KMS Key Rotation (Simulated)",
        "stage": "AWS KMS",
        "status": "done",
        "detail": (
            f"SIMULATED KMS: key material rotation simulated locally. "
            f"No real AWS API call. Rotation #{new_version}."
        ),
    })
    exec_steps.append({
        "name": "Response to ESP32 (Simulated)",
        "stage": "AWS IoT Core",
        "status": "done",
        "detail": "SIMULATED: Response published to esp32/key_rotation/response",
    })
    exec_steps.append({
        "name": "ESP32 received response (Simulated)",
        "stage": "ESP32",
        "status": "done",
        "detail": "SIMULATED: Integrity check passed",
    })
    exec_steps.append({
        "name": "OLED Updated (Simulated)",
        "stage": "ESP32 OLED",
        "status": "done",
        "detail": "SIMULATED: SSD1306 display shows ROTATION SUCCESS",
    })

    duration = round(time.time() - start_time, 2) or 1.8

    data["current_key"]["version"] = new_version
    data["current_key"]["last_rotation"] = timestamp_str
    data["current_key"]["rotation_count"] = data["current_key"].get("rotation_count", 0) + 1
    data["current_key"]["status"] = "Active"
    _record_success_stats(data, timestamp_str)

    hist_entry = {
        "timestamp": timestamp_str,
        "request_id": req_id,
        "device_id": device_id,
        "key_id": data["current_key"]["key_id"],
        "version": new_version,
        "version_display": f"{new_version:02d}",
        "status": "SUCCESS",
        "duration_sec": duration,
        "mode": "demo",
        "kms_mode": "SIMULATED",
    }
    data["history"].append(hist_entry)

    data["last_rotation_state"] = {
        "request_id": req_id,
        "status": "SUCCESS",
        "started_at": timestamp_str,
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": duration,
        "steps": exec_steps,
    }
    save_data(data)

    return jsonify({
        "success": True,
        "request_id": req_id,
        "status": "SUCCESS",
        "key_id": data["current_key"]["key_id"],
        "version": new_version,
        "version_display": f"{new_version:02d}",
        "steps": exec_steps,
        "duration_sec": duration,
        "timestamp": timestamp_str,
        "mode": "demo",
        "kms_mode": "SIMULATED",
        "kms_note": (
            "Demo mode: KMS rotation is fully simulated. "
            "No real AWS API call was made. Safe for demonstration."
        ),
    })


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------

@app.route("/api/rotate-key", methods=["POST"])
def api_rotate_key_alias():
    return api_rotate()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _record_failure(data, req_id, device_id, timestamp_str, start_time, reason, mode):
    data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
    data["stats"]["failed_rotations"] = data["stats"].get("failed_rotations", 0) + 1
    data["history"].append({
        "timestamp": timestamp_str,
        "request_id": req_id,
        "device_id": device_id,
        "key_id": data["current_key"]["key_id"],
        "version": data["current_key"].get("version", 1),
        "status": "FAILED",
        "duration_sec": round(time.time() - start_time, 2),
        "error_reason": reason,
        "mode": mode,
        "kms_mode": "simulated",
    })


def _record_success_stats(data, timestamp_str):
    data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
    data["stats"]["successful_rotations"] = data["stats"].get("successful_rotations", 0) + 1
    data["stats"]["last_rotation"] = timestamp_str


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    mode = get_app_mode()
    kms_ok = kms_mgr.is_configured()

    print(f"\n{'='*55}")
    print(f"  Encryption Key Rotation Button — Flask Server")
    print(f"  URL  : http://{host}:{port}")
    print(f"  Mode : {mode.upper()}")
    print(f"  KMS  : {'REAL (boto3 ready)' if kms_ok else 'SIMULATED (no credentials)'}")
    print(f"{'='*55}\n")

    app.run(host=host, port=port, debug=debug)
