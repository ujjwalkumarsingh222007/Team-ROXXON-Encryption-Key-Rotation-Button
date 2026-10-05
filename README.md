# Encryption Key Rotation System (ESP32 + AWS Cloud Security)

A hybrid university engineering prototype demonstrating cryptographic key rotation initiated from a physical or simulated ESP32 device, executed via AWS Key Management Service (AWS KMS), and visualized through an SSD1306 OLED interface and web dashboard.

---

## 1. 🏗️ Architecture Overview

In restricted university lab environments (such as AWS Academy or Learner Labs), creating custom IAM roles, Lambda execution roles, or IoT Core thing certificates is often restricted or blocked by SCP policies. 

To overcome these constraints, this project uses a **hybrid architecture**:

```
+-----------------------------------------------------------------------------------+
|                              HYBRID LAB PROTOTYPE                                 |
+-----------------------------------------------------------------------------------+
|  [ESP32 Button]  --->  [AWS IoT Core]  --->  [AWS Lambda]  --->  [ AWS KMS (REAL) ]|
|   (Simulated)           (Simulated)           (Simulated)         kms:RotateKey   |
|                                                                    OnDemand       |
|                                                                        |          |
|  [ESP32 OLED]    <---  [  Response  ]  <---  [  Backend ]  <-----------+          |
|   (Simulated)           (Simulated)             (Flask)                           |
+-----------------------------------------------------------------------------------+
```

---

## 2. 🛡️ Real vs. Simulated Components

| Component | Status | Implementation Details |
|---|---|---|
| **AWS KMS** | **REAL** | Directly calls `kms:RotateKeyOnDemand` and `kms:DescribeKey` using `boto3`. Operates on active Customer Managed Key (CMK) in `us-east-1`. |
| **AWS IoT Core** | **SIMULATED** | Simulated in software prototype to avoid X.509 cert upload and IoT Core policy restrictions in university lab. |
| **AWS Lambda** | **SIMULATED** | Serverless function execution simulated locally; backend invokes KMS directly without requiring IAM role creation. |
| **ESP32 Button** | **SIMULATED / HARDWARE** | Interactive virtual GPIO 0 button on web UI (with optional physical firmware in `esp32/` directory). |
| **SSD1306 OLED** | **SIMULATED / HARDWARE** | Real-time virtual 128×64 OLED screen visualizer showing current key version and status. |

---

## 3. 🔄 Dual Operational Modes

### Mode 1: DEMO MODE (Safe Simulation)
- **Safe default** (`APP_MODE=demo`).
- No AWS credentials or internet connection needed.
- Simulates complete pipeline: `ESP32 → IoT Core → Lambda → KMS → OLED`.
- Shows clear progression: `WAITING → PROCESSING → SUCCESS`.
- KMS stage explicitly indicates **"Simulated KMS"** — never falsely claims live AWS rotation occurred.
- Supports 4 failure injection scenarios for lab evaluation.

### Mode 2: REAL KMS MODE (Live AWS KMS)
- Enabled by selecting **REAL KMS** on the frontend or setting `APP_MODE=real` in `.env`.
- Invokes AWS KMS API `kms:RotateKeyOnDemand` on your Customer Managed Key:
  - Alias: `alias/encryption-key-rotation` (or direct Key ID UUID).
  - Region: `us-east-1`.
- Protected by a **Safety Confirmation Modal** before invoking live cloud operations.
- Key ID **remains constant** while backing key material rotates in AWS HSM.
- Returns only safe metadata (status, version, timestamp) — **zero cryptographic key material or credentials are ever exposed**.

---

## 4. 🔑 AWS KMS Key Rotation Mechanics

In AWS KMS, rotating a Customer Managed Key (CMK) works by generating new backing cryptographic key material inside AWS Hardware Security Modules (HSMs):
1. The **KMS Key ID and ARN do NOT change**.
2. Applications continue using the same Key ID for `Encrypt` / `Decrypt` operations.
3. Newly encrypted data uses the new key material version.
4. Older key material versions are preserved to decrypt previously encrypted ciphertext seamlessly.

---

## 5. ⚙️ Required Environment Variables

Create a `.env` file in the project root based on `.env.example`:

```bash
# Application Mode ('demo' or 'real')
APP_MODE=demo

# Flask Server Configuration
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=True

# AWS Authentication & Region (Required for REAL KMS MODE)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Optional: AWS Academy / Learner Lab Session Token
AWS_SESSION_TOKEN=

# AWS KMS Key Alias or UUID
KMS_KEY_ID=alias/encryption-key-rotation

# Simulated Device Identifier
DEVICE_ID=ESP32-001
```

---

## 6. 🚀 How to Run Locally

### Step 1: Install Python Dependencies
```bash
pip install Flask python-dotenv boto3
```
*(Note: `boto3` is only needed for Real KMS Mode. Demo mode runs with standard library + Flask).*

### Step 2: Start the Application
```bash
python app.py
```

### Step 3: Access the Web Interface
Open your web browser and go to:
```
http://127.0.0.1:5000
```

---

## 7. 🧪 Testing Guide

### A. Testing Demo Mode
1. Ensure the top-right toggle is set to **DEMO MODE**.
2. Click **ROTATE ENCRYPTION KEY**.
3. Watch the 5 stages illuminate sequentially:
   `ESP32 (Sent) → IoT Core (Routed) → Lambda (Complete) → Simulated KMS (Rotated) → OLED (Success)`.
4. To test failure simulations:
   - Go to the **DASHBOARD** tab.
   - Select a failure scenario from the **Demo Scenario** dropdown:
     - **IoT Connection Failure** → Stage 2 fails (IoT timeout).
     - **Lambda Execution Failure** → Stage 3 fails (Lambda timeout).
     - **KMS Permission Denied** → Stage 4 fails (AccessDenied).
     - **OLED Display I2C Error** → Stage 5 fails (SSD1306 I2C bus error; key was rotated).
   - Click **ROTATE ENCRYPTION KEY** to observe the exact failure isolation.

### B. Testing Real KMS Mode
1. In your AWS Account (`us-east-1`), create a Symmetric KMS Key:
   - Alias: `alias/encryption-key-rotation`
   - Key Spec: `SYMMETRIC_DEFAULT`
   - Key Usage: `ENCRYPT_DECRYPT`
2. Add your AWS credentials and key alias to `.env`.
3. Switch the top-right toggle to **REAL KMS**.
4. Click **ROTATE ENCRYPTION KEY**.
5. Confirm the action in the safety dialog.
6. The backend executes `kms:RotateKeyOnDemand` against AWS KMS and displays the verified rotation version.

### C. Running Automated Unit Tests
Run the 9-test test suite:
```bash
python test_app.py
```

---

## 8. 🔒 Security & Privacy Considerations

1. **No Frontend Secrets**: AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, session tokens) are stored only in server-side `.env` files and are never sent to browser JavaScript.
2. **No Plaintext Key Material Exposure**: Real AWS KMS never outputs raw symmetric key material. The backend and frontend handle only Key IDs and version metadata.
3. **Safety Confirmation Modal**: Real AWS KMS invocations require deliberate confirmation to prevent accidental AWS API calls.
4. **Git Protection**: `.env` and `data/history.json` are excluded via `.gitignore` to prevent leaking credentials or private history.

---

## 9. 🔌 REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/health` | GET | System health & AWS configuration status |
| `GET /api/status` | GET | Comprehensive system status and service metrics |
| `GET /api/kms/status` | GET | Safe KMS key metadata (real or simulated) |
| `POST /api/rotate` | POST | Execute key rotation (`{"mode": "demo"\|"real", "scenario": "none"\|...}`) |
| `POST /api/rotate-key` | POST | Backward-compatible alias for `/api/rotate` |
| `GET /api/rotation-status` | GET | Last rotation state and execution step timeline |
| `GET /api/history` | GET | Complete audit record of all past rotations |
| `GET /api/device-status` | GET | Simulated ESP32 telemetry, pinout, and MAC address |

---

## 10. 📁 Project Structure

```text
Team-ROXXON-Encryption-Key-Rotation-Button/
├── app.py                     # Flask REST API backend
├── kms.py                     # AWS KMS boto3 integration & on-demand rotation
├── aws_iot.py                 # AWS IoT Core helper (simulated fallback)
├── requirements.txt           # Python dependencies
├── test_app.py                # Unit test suite (9 tests)
├── .env.example               # Environment variables template
├── .gitignore                 # Secrets & temp file exclusions
│
├── templates/
│   └── index.html             # 5-page frontend application
├── static/
│   ├── css/style.css          # Design system stylesheet
│   └── js/script.js           # Frontend controller & pipeline visualizer
│
├── esp32/                     # Physical hardware firmware (optional)
│   ├── key_rotator.ino        # Arduino C++ sketch
│   ├── secrets.h.example      # Wi-Fi & certs template
│   └── README.md              # Wiring pinout guide
│
├── lambda/                    # Production serverless definitions (reference)
│   ├── lambda_function.py     # Lambda handler
│   ├── iam_policy.json        # IAM policy template
│   └── iot_rule.json          # IoT SQL topic rule
│
└── README.md                  # Project documentation
```
