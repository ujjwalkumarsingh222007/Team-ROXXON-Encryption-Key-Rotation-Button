# ESP32 Firmware Guide & Wiring

This directory contains the complete Arduino firmware for the physical **Encryption Key Rotation Button**.

---

## 1. Hardware Required
1. **ESP32 Development Board** (NodeMCU-32S, ESP32-WROOM-32D, or DevKit V1)
2. **SSD1306 0.96" OLED Display** (128x64 pixels, I2C Interface)
3. **Physical Push Button** (Tactile switch)
4. **Jumper Wires & Breadboard**
5. **Micro-USB Cable**

---

## 2. Pin Connections (Wiring Diagram)

| ESP32 Pin | Component | Component Pin | Description |
| :--- | :--- | :--- | :--- |
| **3V3** | OLED Screen | **VCC** | 3.3V Power |
| **GND** | OLED Screen | **GND** | Ground |
| **GPIO 21** | OLED Screen | **SDA** | I2C Data Line |
| **GPIO 22** | OLED Screen | **SCL** | I2C Clock Line |
| **GPIO 0** | Push Button | **Leg 1** | Boot button pin (Active LOW, internal pull-up) |
| **GND** | Push Button | **Leg 2** | Connected to Ground |

*(Note: If using the onboard `BOOT` button on your ESP32 board, no extra wiring is required for the button as it is already wired to GPIO 0!)*

---

## 3. Arduino IDE Setup

1. Open **Arduino IDE**.
2. Go to **File -> Preferences**.
3. In *Additional Board Manager URLs*, paste:
   ```text
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Go to **Tools -> Board -> Boards Manager**, search for `esp32` by *Espressif Systems*, and click **Install**.
5. Go to **Sketch -> Include Library -> Manage Libraries...** and install:
   - `PubSubClient` by Nick O'Leary
   - `ArduinoJson` by Benoit Blanchon (version 6.x or 7.x)
   - `Adafruit SSD1306` by Adafruit
   - `Adafruit GFX Library` by Adafruit

---

## 4. Flashing Firmware

1. Copy `secrets.h.example` to `secrets.h` inside the `esp32/` directory.
2. In `secrets.h`, update:
   - `WIFI_SSID` and `WIFI_PASSWORD`
   - `AWS_IOT_ENDPOINT` (from AWS IoT Core Settings)
   - `AWS_CERT_CRT` (Device Certificate)
   - `AWS_CERT_PRIVATE` (Device Private Key)
3. Connect ESP32 to your computer via USB.
4. Select board: `DOIT ESP32 DEVKIT V1` (or your ESP32 variant) and select the correct COM port.
5. Click **Upload** (Arrow icon).
