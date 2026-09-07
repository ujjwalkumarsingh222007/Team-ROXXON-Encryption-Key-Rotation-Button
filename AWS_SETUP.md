# AWS Setup Guide (Step-by-Step for Complete Beginners)

Follow this guide to connect your real AWS services. Take it **one step at a time**.

---

## 📋 Overview of AWS Components
1. **AWS KMS** $\rightarrow$ Customer Managed Symmetric Key with on-demand key rotation.
2. **AWS IAM** $\rightarrow$ Permissions role for the Lambda function.
3. **AWS Lambda** $\rightarrow$ Serverless function that executes key rotation logic.
4. **AWS IoT Core** $\rightarrow$ MQTT broker, device certificate (X.509), and topic routing rule.

---

## STEP 1: Create the AWS KMS Key

1. Log in to the [AWS Management Console](https://console.aws.amazon.com/).
2. In the top search bar, type `KMS` and click **Key Management Service**.
3. In the left navigation bar, click **Customer managed keys**.
4. Click the orange **Create key** button.
5. In **Step 1 (Configure key)**:
   - Key type: select **Symmetric**.
   - Key usage: select **Encrypt and decrypt**.
   - Advanced options: Leave **KMS** (default).
   - Click **Next**.
6. In **Step 2 (Add labels)**:
   - Alias: Enter `ESP32-Master-Encryption-Key`
   - Description: `Symmetric key for ESP32 IoT project`
   - Click **Next**.
7. In **Step 3 (Define key administrative permissions)**:
   - Select your IAM User or Admin role so you can administer the key.
   - Click **Next**.
8. In **Step 4 (Define key usage permissions)**:
   - Click **Next**.
9. In **Step 5 (Review)**:
   - Click **Finish**.
10. Click on your newly created key (`ESP32-Master-Encryption-Key`).

📌 **COPY THIS VALUE:**
- Under **General configuration**, copy the **Key ID** (e.g., `12345678-1234-1234-1234-123456789012`).

📌 **PASTE IT HERE:**
- In your project's `.env` file:
  ```ini
  KMS_KEY_ID=paste-your-key-id-here
  ```

---

## STEP 2: Create the Lambda IAM Execution Role

1. Search for `IAM` in the AWS search bar and click **IAM**.
2. In the left sidebar, click **Roles**, then click **Create role**.
3. Under **Trusted entity type**, select **AWS service**.
4. Under **Use case**, select **Lambda**, then click **Next**.
5. In **Add permissions**, click **Create policy** (opens in a new tab):
   - Click the **JSON** tab.
   - Paste the contents from `lambda/iam_policy.json`.
   - Click **Next**.
   - Policy name: `ESP32-KeyRotator-Policy`.
   - Click **Create policy**.
6. Return to the Role creation tab, click the refresh icon, search for `ESP32-KeyRotator-Policy`, and check the box next to it.
7. Click **Next**.
8. Role name: `ESP32-KeyRotator-ExecutionRole`.
9. Click **Create role**.

---

## STEP 3: Create the AWS Lambda Function

1. Search for `Lambda` in the AWS search bar and click **Lambda**.
2. Click **Create function**.
3. Select **Author from scratch**.
4. Function name: `ESP32-KeyRotationHandler`.
5. Runtime: **Python 3.12** (or Python 3.11).
6. Under **Permissions**, expand *Change default execution role*:
   - Select **Use an existing role**.
   - Existing role: Select `ESP32-KeyRotator-ExecutionRole`.
7. Click **Create function**.
8. In the **Code source** editor:
   - Open `lambda_function.py`.
   - Delete any default code and paste the exact code from `lambda/lambda_function.py`.
   - Click the orange **Deploy** button.
9. Go to the **Configuration** tab $\rightarrow$ **Environment variables** $\rightarrow$ **Edit**:
   - Add Key: `KMS_KEY_ID`, Value: (Your KMS Key ID from Step 1).
   - Add Key: `RESPONSE_TOPIC`, Value: `esp32/key_rotation/response`.
   - Click **Save**.

---

## STEP 4: Create the AWS IoT Thing & X.509 Certificates

1. Search for `IoT Core` and click **AWS IoT Core**.
2. In the left menu, click **Manage** $\rightarrow$ **All devices** $\rightarrow$ **Things**.
3. Click **Create things** $\rightarrow$ select **Create single thing** $\rightarrow$ click **Next**.
4. Thing name: `ESP32-001`. Click **Next**.
5. Under **Device Certificate**, select **Auto-generate a new certificate (recommended)** $\rightarrow$ click **Next**.
6. Under **Policies**, click **Create policy** (or skip to Step 5 first).

---

## STEP 5: Create the IoT Core Policy

1. In AWS IoT Core, in the left menu, click **Security** $\rightarrow$ **Policies** $\rightarrow$ **Create policy**.
2. Policy Name: `ESP32-IoT-Policy`.
3. Click the **JSON** tab and paste the exact contents of `lambda/iot_policy.json`.
4. Click **Create**.
5. Attach this policy to your downloaded Device Certificate.

---

## STEP 6: Download Certificates & Find IoT Endpoint

1. When generating certificates in IoT Core, download:
   - **Device certificate** (`...-certificate.pem.crt`)
   - **Private key** (`...-private.pem.key`)
   - **Amazon Root CA 1**
2. In the left menu of IoT Core, scroll down to **Settings**.

📌 **COPY THIS VALUE:**
- Copy the **Device data endpoint** (e.g., `a1234567890abc-ats.iot.us-east-1.amazonaws.com`).

📌 **PASTE IT HERE:**
- In your `.env` file:
  ```ini
  IOT_ENDPOINT=paste-your-endpoint-here
  ```
- In `esp32/secrets.h`:
  ```cpp
  const char* AWS_IOT_ENDPOINT = "paste-your-endpoint-here";
  ```

---

## STEP 7: Create the IoT Topic Rule

1. In AWS IoT Core, click **Message routing** $\rightarrow$ **Rules**.
2. Click **Create rule**.
3. Rule name: `RotateKeyRule`. Click **Next**.
4. SQL statement:
   ```sql
   SELECT * FROM 'esp32/key_rotation/request'
   ```
5. Click **Next**.
6. Under **Rule actions**, select **Lambda**.
7. Select Lambda function: `ESP32-KeyRotationHandler`.
8. Click **Next** $\rightarrow$ click **Create**.

---

## STEP 8: Flash ESP32 & Run

1. Open `esp32/key_rotator.ino` in Arduino IDE.
2. Fill in `esp32/secrets.h` with your Wi-Fi credentials and downloaded certificates.
3. Upload to ESP32.
4. Press the physical button on GPIO 0 to watch real-time rotation!
