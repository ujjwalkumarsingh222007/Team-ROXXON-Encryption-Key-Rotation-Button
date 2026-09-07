# AWS EC2 Production Deployment Guide

This guide explains how to deploy the Encryption Key Rotation application on an **AWS EC2 Ubuntu instance** with **Gunicorn** and **Nginx**.

---

## 1. Launch an EC2 Instance
1. Go to AWS EC2 Console $\rightarrow$ **Launch instances**.
2. Name: `Key-Rotation-Server`.
3. AMI: **Ubuntu 24.04 LTS**.
4. Instance Type: `t2.micro` or `t3.micro` (Free tier eligible).
5. Key pair: Select or create a `.pem` key pair for SSH.
6. **Network Settings (Security Group)**:
   - Allow **SSH** (Port 22) from your IP.
   - Allow **HTTP** (Port 80) from Anywhere (`0.0.0.0/0`).
   - Allow **HTTPS** (Port 443) from Anywhere (`0.0.0.0/0`).
7. Click **Launch instance**.

---

## 2. Connect to EC2 via SSH
```bash
ssh -i "your-key.pem" ubuntu@YOUR_EC2_PUBLIC_IP
```

---

## 3. Install System Dependencies & Python
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx git
```

---

## 4. Clone or Upload the Code
```bash
mkdir -p /home/ubuntu/app
cd /home/ubuntu/app
# Upload your files or clone repo
```

---

## 5. Set up Virtual Environment & Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 6. Configure Environment Variables (`.env`)
```bash
cp .env.example .env
nano .env
```
Fill in your `AWS_REGION`, `KMS_KEY_ID`, and `IOT_ENDPOINT`. Save with `CTRL+O`, exit with `CTRL+X`.

---

## 7. Configure Gunicorn Systemd Service
Create service file:
```bash
sudo nano /etc/systemd/system/keyrotator.service
```
Paste:
```ini
[Unit]
Description=Gunicorn instance to serve Key Rotation Flask App
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/app
Environment="PATH=/home/ubuntu/app/venv/bin"
ExecStart=/home/ubuntu/app/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 app:app

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl start keyrotator
sudo systemctl enable keyrotator
```

---

## 8. Configure Nginx Reverse Proxy
```bash
sudo nano /etc/nginx/sites-available/keyrotator
```
Paste:
```nginx
server {
    listen 80;
    server_name YOUR_EC2_PUBLIC_IP;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Enable Nginx site and restart:
```bash
sudo ln -s /etc/nginx/sites-available/keyrotator /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## 9. Access Your Application
Open your web browser and navigate to:
```text
http://YOUR_EC2_PUBLIC_IP
```
Your production web app is now running with Gunicorn and Nginx!
