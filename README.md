# Encryption Key Rotation System (ESP32 + AWS IoT Core + Lambda + KMS)

A complete IoT and Cloud Security system that triggers on-demand AWS KMS Customer Managed Key (CMK) rotations from a physical or simulated ESP32 push button, updates backing key materials securely in AWS HSMs, and renders the live state and key version on an SSD1306 OLED display.

---

## 🚀 Key Features

- **Real AWS KMS On-Demand Key Rotation**: Cryptographically accurate implementation where the AWS KMS Key ID remains constant, while key backing material version increments. Secret keys are never exposed or transmitted to the device.
- **Full 5-Page Web Application**:
  1. **CONTROL**: Live 5-stage pipeline (`ESP32 → AWS IoT Core → Lambda → KMS → OLED`), tactile trigger button, SSD1306 OLED visualizer, honest system statuses, and active KMS Key card.
  2. **DASHBOARD**: Real-time execution metrics, vertical audit timeline, live activity feed, and demo failure injector.
  3. **HISTORY**: Complete historical audit log table with timestamps, key versions, and duration.
  4. **DEVICE**: Hardware pinout details, MAC address, Wi-Fi signal (RSSI), and connection state.
  5. **ABOUT**: Clear, beginner-friendly architecture explanation.
- **Dual Mode System**:
  - **DEMO MODE**: 100% functional local simulation without AWS charges or credentials.
  - **REAL AWS MODE**: Live API calls (`kms:RotateKeyOnDemand`, AWS IoT Core MQTT) with a safety confirmation modal.
- **ESP32 Hardware Firmware**: Complete Arduino/C++ sketch (`esp32/key_rotator.ino`) featuring TLS 1.3 X.509 mutual authentication, MQTT pub/sub, button debounce on GPIO 0, and SSD1306 OLED rendering.
- **Serverless AWS Lambda**: Production-ready Python 3.12 function with validation, KMS execution, and least-privilege IAM policies.

---

## 📁 Project Directory Structure

```text
CC_project/
├── app.py                     # Production Flask backend (REST APIs)
├── kms.py                     # AWS KMS manager (boto3 + on-demand rotation)
├── aws_iot.py                 # AWS IoT Core MQTT/HTTPS integration
├── requirements.txt           # Python dependencies
├── test_app.py                # Automated unit tests (unittest)
├── .env.example               # Configuration template
├── .gitignore                 # Git ignore rules
│
├── lambda/                    # AWS Lambda & IAM definitions
│   ├── lambda_function.py     # Lambda handler (Python 3.12)
│   ├── iam_policy.json        # Least-privilege IAM policy
│   ├── iot_rule.json          # IoT SQL topic rule
│   └── iot_policy.json        # IoT Thing policy
│
├── esp32/                     # Physical ESP32 firmware
│   ├── key_rotator.ino        # Arduino C++ sketch (TLS + MQTT + OLED)
│   ├── secrets.h.example      # Wi-Fi & X.509 certs template
│   └── README.md              # Wiring diagrams and flashing guide
│
├── templates/
│   └── index.html             # 5-Page frontend application
│
├── static/
│   ├── css/style.css          # Warm modern engineering design system
│   └── js/script.js           # Interactive controller & pipeline visualizer
│
├── AWS_SETUP.md               # Step-by-step AWS Console guide for beginners
├── DEPLOYMENT.md              # EC2 / Ubuntu / Gunicorn / Nginx guide
└── README.md                  # Project overview
```

---

## ⚡ Quick Start (Local Demo Mode)

You can run and test the complete system right away on your machine without configuring AWS:

1. **Install dependencies**:
   ```bash
   pip install Flask python-dotenv
   ```
2. **Start the Flask server**:
   ```bash
   python app.py
   ```
3. **Open in browser**:
   Navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000).

4. **Run Unit Tests**:
   ```bash
   python test_app.py
   ```

---

## ☁️ Connecting Real AWS

When you are ready to connect real AWS services:
1. Follow the step-by-step guide in [AWS_SETUP.md](file:///d:/Study%20material/CC_project/AWS_SETUP.md).
2. Copy `.env.example` to `.env` and fill in your AWS credentials, `KMS_KEY_ID`, and `IOT_ENDPOINT`.
3. In the web interface, switch from **DEMO MODE** to **REAL AWS**.
