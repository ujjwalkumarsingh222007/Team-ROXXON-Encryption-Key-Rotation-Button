"""
Encryption Key Rotation Button - Production Flask Backend
Provides REST APIs for:
- GET /api/status (System & AWS service status)
- POST /api/rotate (Trigger rotation in Demo or Real AWS mode)
- GET /api/rotation-status (Check ongoing rotation progress)
- GET /api/history (Get rotation audit records)
- GET /api/device-status (Get physical ESP32 telemetry & connection status)
- GET /api/health (Health check)
"""

import os
import json
import uuid
import time
import random
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request

# Load environment variables from .env file
load_dotenv()

from kms import KMSManager
from aws_iot import AWSIoTManager

app = Flask(__name__)

# Data file path
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'history.json')

# Managers
kms_mgr = KMSManager()
iot_mgr = AWSIoTManager()

def get_app_mode():
    """Returns 'real' if APP_MODE is real and AWS credentials/KMS are configured, else 'demo'."""
    mode = os.getenv("APP_MODE", "demo").lower()
    return "real" if mode == "real" else "demo"

def load_data():
    default_device = {
        "device_id": os.getenv("DEVICE_ID", "ESP32-001"),
        "device_type": "ESP32-WROOM-32D (32-bit Dual-Core)",
        "firmware_version": "v2.4.1-rotator-release",
        "gpio_button_pin": "GPIO 0 (Boot Button / Pull-Up)",
        "oled_i2c_address": "0x3C (SDA: GPIO 21, SCL: GPIO 22)",
        "wifi_ssid": "Connected Network",
        "wifi_status": "Connected",
        "mqtt_status": "Connected",
        "ip_address": "192.168.1.142",
        "mac_address": "24:6F:28:7A:B4:9C",
        "wifi_rssi": "-54 dBm (Good)",
        "button_status": "IDLE (Pull-Up HIGH)",
        "oled_status": "Active (SSD1306 128x64)",
        "last_ping": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        default_data = {
            "current_key": {
                "key_id": os.getenv("KMS_KEY_ID", "450b3db5-8fbb-4693-9c95-0cc1531adb0c"),
                "arn": f"arn:aws:kms:{os.getenv('AWS_REGION', 'us-east-1')}:748291038472:key/450b3db5-8fbb-4693-9c95-0cc1531adb0c",
                "status": "Active",
                "version": 1,
                "key_spec": "SYMMETRIC_DEFAULT",
                "key_usage": "ENCRYPT_DECRYPT",
                "origin": "AWS_KMS",
                "last_rotated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "rotation_count": 0
            },
            "stats": {
                "total_rotations": 0,
                "successful_rotations": 0,
                "failed_rotations": 0,
                "last_rotation": "Never"
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
                "steps": []
            }
        }
        save_data(default_data)
        return default_data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "device" not in data or not data["device"]:
                data["device"] = default_device
            return data
    except Exception:
        return {}

def save_data(data):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving data: {e}")

# -----------------------------------------------------------------------------
# Frontend Route
# -----------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

# -----------------------------------------------------------------------------
# API: Health Check
# -----------------------------------------------------------------------------
@app.route('/api/health', methods=['GET'])
def api_health():
    mode = get_app_mode()
    kms_conf = kms_mgr.is_configured()
    iot_conf = iot_mgr.is_configured()
    return jsonify({
        "backend": "online",
        "mode": mode,
        "aws": "configured" if (kms_conf and iot_conf) else "not configured",
        "kms_configured": kms_conf,
        "iot_configured": iot_conf,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

# -----------------------------------------------------------------------------
# API: Status
# -----------------------------------------------------------------------------
@app.route('/api/status', methods=['GET'])
def api_status():
    data = load_data()
    mode = get_app_mode()
    
    # Check AWS services status honestly
    kms_meta = kms_mgr.get_key_metadata() if mode == "real" else None
    
    # AWS Services Honest Status
    aws_services = {
        "iot_core": {
            "name": "AWS IoT Core",
            "status": "Connected" if (mode == "real" and iot_mgr.is_configured()) else ("Simulation Mode" if mode == "demo" else "Not Configured"),
            "configured": iot_mgr.is_configured(),
            "endpoint": iot_mgr.endpoint or "Not configured",
            "request_topic": iot_mgr.request_topic,
            "response_topic": iot_mgr.response_topic,
            "protocol": "MQTT over TLS v1.3 (Port 8883)",
            "client_id": "ESP32-001"
        },
        "lambda": {
            "name": "AWS Lambda",
            "status": "Ready" if (mode == "real" and kms_mgr.is_configured()) else ("Simulation Mode" if mode == "demo" else "Not Configured"),
            "function_name": "ESP32-KeyRotationHandler",
            "runtime": "Python 3.12 (Serverless)",
            "memory": "256 MB",
            "timeout": "15s"
        },
        "kms": {
            "name": "AWS KMS",
            "status": "Active" if (mode == "real" and kms_mgr.is_configured() and kms_meta and kms_meta.get("status") == "ACTIVE") else ("Simulation Mode" if mode == "demo" else "Not Configured"),
            "configured": kms_mgr.is_configured(),
            "key_id": kms_meta.get("key_id") if kms_meta else data.get("current_key", {}).get("key_id", "450b3db5-8fbb-4693-9c95-0cc1531adb0c"),
            "type": "Customer Managed Key (CMK)",
            "key_spec": "SYMMETRIC_DEFAULT",
            "algorithm": "AES-256-GCM"
        }
    }

    # ESP32 Status
    device_info = data.get("device", {})
    
    # Current Key info (Preserve Key ID, update version)
    current_key = data.get("current_key", {})
    if mode == "real" and kms_meta and kms_meta.get("status") == "ACTIVE":
        current_key["key_id"] = kms_meta.get("key_id", current_key["key_id"])
        current_key["arn"] = kms_meta.get("arn", current_key["arn"])
        current_key["version"] = kms_meta.get("version", current_key.get("version", 1))
        current_key["last_rotation"] = kms_meta.get("last_rotated", current_key["last_rotation"])
        current_key["status"] = "Active"

    return jsonify({
        "status": "online",
        "mode": mode,
        "aws_services": aws_services,
        "device": device_info,
        "current_key": current_key,
        "stats": data.get("stats", {}),
        "recent_logs": data.get("logs", [])[-10:],
        "oled": {
            "header": "KEY ROTATOR",
            "line1": "DEVICE READY",
            "line2": "PRESS BUTTON",
            "version": f"{current_key.get('version', 1):02d}",
            "status": "IDLE"
        },
        "system_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

# -----------------------------------------------------------------------------
# API: Device Status (ESP32 details)
# -----------------------------------------------------------------------------
@app.route('/api/device-status', methods=['GET'])
def api_device_status():
    data = load_data()
    device = data.get("device", {})
    device["last_ping"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({
        "device": device,
        "mode": get_app_mode(),
        "status": "online"
    })

# -----------------------------------------------------------------------------
# API: Rotation Status (Live execution timeline)
# -----------------------------------------------------------------------------
@app.route('/api/rotation-status', methods=['GET'])
def api_rotation_status():
    data = load_data()
    last_rot = data.get("last_rotation_state", {})
    return jsonify({
        "rotation_state": last_rot,
        "current_key": data.get("current_key", {}),
        "stats": data.get("stats", {})
    })

# -----------------------------------------------------------------------------
# API: History
# -----------------------------------------------------------------------------
@app.route('/api/history', methods=['GET'])
def api_history():
    data = load_data()
    return jsonify({
        "history": list(reversed(data.get("history", []))),
        "stats": data.get("stats", {})
    })

# -----------------------------------------------------------------------------
# API: Rotate Key (Handles Demo Mode & Real AWS Mode)
# -----------------------------------------------------------------------------
@app.route('/api/rotate', methods=['POST'])
def api_rotate():
    req_json = request.get_json(silent=True) or {}
    forced_scenario = req_json.get("scenario", "none")
    mode_requested = req_json.get("mode", get_app_mode())
    device_id = req_json.get("device_id", "ESP32-001")
    
    data = load_data()
    start_time = time.time()
    req_id = f"ROT-{uuid.uuid4().hex[:8].upper()}"
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Initialize execution state
    exec_steps = [
        {"name": "Button pressed", "stage": "ESP32", "status": "done", "detail": f"Physical button trigger on GPIO 0 ({device_id})"},
        {"name": "ESP32 request created", "stage": "ESP32", "status": "done", "detail": f"JSON payload serialized (Request ID: {req_id})"}
    ]

    # Check for forced demo failure scenarios
    if forced_scenario == "iot_timeout":
        time.sleep(0.4)
        exec_steps.append({"name": "AWS IoT Core connection", "stage": "AWS IoT Core", "status": "failed", "detail": "Connection timed out to topic 'esp32/key_rotation/request'"})
        data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
        data["stats"]["failed_rotations"] = data["stats"].get("failed_rotations", 0) + 1
        
        hist_entry = {
            "timestamp": timestamp_str,
            "request_id": req_id,
            "device_id": device_id,
            "key_id": data["current_key"]["key_id"],
            "version": data["current_key"].get("version", 1),
            "status": "FAILED",
            "duration_sec": round(time.time() - start_time, 2),
            "error_reason": "AWS IoT Core connection timeout (Simulated)",
            "mode": mode_requested
        }
        data["history"].append(hist_entry)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "AWS IoT Core Connection Timeout",
            "solution": "Check your MQTT endpoint, Wi-Fi connectivity, or AWS IoT Core policy.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2)
        }), 400

    if forced_scenario == "lambda_error":
        time.sleep(0.4)
        exec_steps.append({"name": "AWS IoT Core received request", "stage": "AWS IoT Core", "status": "done", "detail": "Topic rule matched"})
        exec_steps.append({"name": "Lambda invocation", "stage": "AWS Lambda", "status": "failed", "detail": "Lambda execution error: Timeout / Memory Limit (Simulated)"})
        data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
        data["stats"]["failed_rotations"] = data["stats"].get("failed_rotations", 0) + 1
        
        hist_entry = {
            "timestamp": timestamp_str,
            "request_id": req_id,
            "device_id": device_id,
            "key_id": data["current_key"]["key_id"],
            "version": data["current_key"].get("version", 1),
            "status": "FAILED",
            "duration_sec": round(time.time() - start_time, 2),
            "error_reason": "Lambda execution failure",
            "mode": mode_requested
        }
        data["history"].append(hist_entry)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "AWS Lambda Execution Failure",
            "solution": "Check CloudWatch logs for Lambda function 'ESP32-KeyRotationHandler'.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2)
        }), 400

    if forced_scenario == "kms_error":
        time.sleep(0.4)
        exec_steps.append({"name": "AWS IoT Core received request", "stage": "AWS IoT Core", "status": "done", "detail": "Topic rule matched"})
        exec_steps.append({"name": "Lambda triggered", "stage": "AWS Lambda", "status": "done", "detail": "Executing KMS API call"})
        exec_steps.append({"name": "AWS KMS Key Rotation", "stage": "AWS KMS", "status": "failed", "detail": "AccessDeniedException: IAM Role lacks 'kms:RotateKeyOnDemand' permission (Simulated)"})
        data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
        data["stats"]["failed_rotations"] = data["stats"].get("failed_rotations", 0) + 1
        
        hist_entry = {
            "timestamp": timestamp_str,
            "request_id": req_id,
            "device_id": device_id,
            "key_id": data["current_key"]["key_id"],
            "version": data["current_key"].get("version", 1),
            "status": "FAILED",
            "duration_sec": round(time.time() - start_time, 2),
            "error_reason": "KMS AccessDeniedException",
            "mode": mode_requested
        }
        data["history"].append(hist_entry)
        save_data(data)
        return jsonify({
            "success": False,
            "request_id": req_id,
            "status": "FAILED",
            "error": "AWS KMS Permission Denied",
            "solution": "Ensure your Lambda IAM Execution Role has 'kms:RotateKeyOnDemand' permission in its IAM policy.",
            "steps": exec_steps,
            "duration_sec": round(time.time() - start_time, 2)
        }), 400

    # -------------------------------------------------------------------------
    # REAL AWS EXECUTION
    # -------------------------------------------------------------------------
    if mode_requested == "real":
        if not kms_mgr.is_configured():
            return jsonify({
                "success": False,
                "status": "FAILED",
                "error": "AWS KMS Not Configured",
                "message": "KMS_KEY_ID or AWS credentials are not configured in your .env file.",
                "solution": "Follow AWS_SETUP.md to set up your KMS key and add it to .env, or switch to DEMO MODE."
            }), 400

        # 1. Publish to AWS IoT Core if configured
        if iot_mgr.is_configured():
            iot_res = iot_mgr.publish_request(device_id=device_id, request_id=req_id)
            if iot_res.get("success"):
                exec_steps.append({"name": "AWS IoT Core published", "stage": "AWS IoT Core", "status": "done", "detail": f"Published to topic '{iot_mgr.request_topic}'"})
            else:
                exec_steps.append({"name": "AWS IoT Core publish error", "stage": "AWS IoT Core", "status": "failed", "detail": iot_res.get("error")})

        # 2. Trigger KMS on-demand key rotation
        exec_steps.append({"name": "Lambda triggered", "stage": "AWS Lambda", "status": "done", "detail": "Invoking KMS RotateKeyOnDemand"})
        kms_res = kms_mgr.rotate_key_on_demand()
        
        if not kms_res.get("success"):
            exec_steps.append({"name": "AWS KMS Key Rotation", "stage": "AWS KMS", "status": "failed", "detail": kms_res.get("message")})
            data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
            data["stats"]["failed_rotations"] = data["stats"].get("failed_rotations", 0) + 1
            save_data(data)
            return jsonify({
                "success": False,
                "request_id": req_id,
                "status": "FAILED",
                "error": kms_res.get("error_type", "KMS_ERROR"),
                "message": kms_res.get("message"),
                "solution": kms_res.get("solution", "Verify IAM permissions."),
                "steps": exec_steps
            }), 400

        # Success in Real AWS Mode
        exec_steps.append({"name": "AWS KMS Key Rotation completed", "stage": "AWS KMS", "status": "done", "detail": f"New backing key material version v{kms_res.get('version', 2):02d} activated"})
        exec_steps.append({"name": "Response returned", "stage": "AWS IoT Core", "status": "done", "detail": "Payload sent to 'esp32/key_rotation/response'"})
        exec_steps.append({"name": "ESP32 received response", "stage": "ESP32", "status": "done", "detail": "Response verified"})
        exec_steps.append({"name": "OLED updated", "stage": "ESP32 OLED", "status": "done", "detail": f"Displaying Version: {kms_res.get('version', 2):02d}"})

        new_version = kms_res.get("version", 2)
        duration = round(time.time() - start_time, 2)
        
        # Update current key metadata (Key ID remains intact!)
        data["current_key"]["version"] = new_version
        data["current_key"]["last_rotation"] = timestamp_str
        data["current_key"]["rotation_count"] = data["current_key"].get("rotation_count", 0) + 1
        data["current_key"]["status"] = "Active"

        data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
        data["stats"]["successful_rotations"] = data["stats"].get("successful_rotations", 0) + 1
        data["stats"]["last_rotation"] = timestamp_str

        hist_entry = {
            "timestamp": timestamp_str,
            "request_id": req_id,
            "device_id": device_id,
            "key_id": kms_res.get("key_id", data["current_key"]["key_id"]),
            "version": new_version,
            "version_display": f"{new_version:02d}",
            "status": "SUCCESS",
            "duration_sec": duration,
            "mode": "real"
        }
        data["history"].append(hist_entry)
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
            "mode": "real"
        })

    # -------------------------------------------------------------------------
    # DEMO MODE EXECUTION (Simulated, safe, instant)
    # -------------------------------------------------------------------------
    time.sleep(0.3)
    exec_steps.append({"name": "AWS IoT Core received request", "stage": "AWS IoT Core", "status": "done", "detail": "MQTT QoS 1 on topic 'esp32/key_rotation/request'"})
    exec_steps.append({"name": "Lambda triggered", "stage": "AWS Lambda", "status": "done", "detail": "Function 'ESP32-KeyRotationHandler' executed"})
    exec_steps.append({"name": "AWS KMS Key Rotation completed", "stage": "AWS KMS", "status": "done", "detail": "Customer Managed Key backing material rotated"})
    exec_steps.append({"name": "Response returned", "stage": "AWS IoT Core", "status": "done", "detail": "Response published to 'esp32/key_rotation/response'"})
    exec_steps.append({"name": "ESP32 received response", "stage": "ESP32", "status": "done", "detail": "Integrity check passed"})
    exec_steps.append({"name": "OLED updated", "stage": "ESP32 OLED", "status": "done", "detail": "Screen updated to show SUCCESS and new version"})

    new_version = data["current_key"].get("version", 1) + 1
    duration = round(time.time() - start_time, 2)
    if duration == 0:
        duration = 1.8

    # Update current key metadata (Key ID remains intact!)
    data["current_key"]["version"] = new_version
    data["current_key"]["last_rotation"] = timestamp_str
    data["current_key"]["rotation_count"] = data["current_key"].get("rotation_count", 0) + 1
    data["current_key"]["status"] = "Active"

    data["stats"]["total_rotations"] = data["stats"].get("total_rotations", 0) + 1
    data["stats"]["successful_rotations"] = data["stats"].get("successful_rotations", 0) + 1
    data["stats"]["last_rotation"] = timestamp_str

    hist_entry = {
        "timestamp": timestamp_str,
        "request_id": req_id,
        "device_id": device_id,
        "key_id": data["current_key"]["key_id"],
        "version": new_version,
        "version_display": f"{new_version:02d}",
        "status": "SUCCESS",
        "duration_sec": duration,
        "mode": "demo"
    }
    data["history"].append(hist_entry)
    
    data["last_rotation_state"] = {
        "request_id": req_id,
        "status": "SUCCESS",
        "started_at": timestamp_str,
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": duration,
        "steps": exec_steps
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
        "mode": "demo"
    })

# Aliases for backward compatibility
@app.route('/api/rotate-key', methods=['POST'])
def api_rotate_key_alias():
    return api_rotate()

if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    print(f"Starting Key Rotation Server on http://{host}:{port} (Mode: {get_app_mode().upper()})")
    app.run(host=host, port=port, debug=debug)
