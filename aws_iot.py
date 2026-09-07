"""
AWS IoT Core Integration
Handles communication with AWS IoT Core via MQTT/HTTPS endpoint.
Can publish rotation requests to 'esp32/key_rotation/request'
and subscribe/receive rotation responses from 'esp32/key_rotation/response'.
"""

import os
import json
import logging
import uuid
import datetime

logger = logging.getLogger("aws_iot")

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

class AWSIoTManager:
    def __init__(self, endpoint=None, region="us-east-1"):
        self.endpoint = endpoint or os.getenv("IOT_ENDPOINT", "").strip()
        self.region = region or os.getenv("AWS_REGION", "us-east-1").strip()
        self.request_topic = os.getenv("REQUEST_TOPIC", "esp32/key_rotation/request").strip()
        self.response_topic = os.getenv("RESPONSE_TOPIC", "esp32/key_rotation/response").strip()
        self.client = None
        self._init_client()

    def _init_client(self):
        if not BOTO3_AVAILABLE:
            return
        try:
            if self.endpoint:
                self.client = boto3.client("iot-data", endpoint_url=f"https://{self.endpoint}", region_name=self.region)
            else:
                self.client = boto3.client("iot", region_name=self.region)
        except Exception as e:
            logger.warning(f"Could not initialize AWS IoT client: {e}")
            self.client = None

    def is_configured(self):
        return bool(BOTO3_AVAILABLE and self.endpoint and self.client)

    def get_status(self):
        if not self.is_configured():
            return {
                "status": "NOT_CONFIGURED",
                "endpoint": self.endpoint or "Not configured",
                "region": self.region,
                "request_topic": self.request_topic,
                "response_topic": self.response_topic,
                "protocol": "MQTT over TLS v1.3 (Port 8883)",
                "qos": 1,
                "message": "Set IOT_ENDPOINT in .env to connect to live AWS IoT Core."
            }

        return {
            "status": "CONFIGURED",
            "endpoint": self.endpoint,
            "region": self.region,
            "request_topic": self.request_topic,
            "response_topic": self.response_topic,
            "protocol": "MQTT over TLS v1.3 (Port 8883)",
            "qos": 1,
            "message": "AWS IoT Core endpoint ready."
        }

    def publish_request(self, device_id="ESP32-001", request_id=None):
        if not request_id:
            request_id = f"ROT-{uuid.uuid4().hex[:8].upper()}"

        payload = {
            "device_id": device_id,
            "action": "ROTATE_KEY",
            "request_id": request_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "FLASK_WEB_APP"
        }

        if not self.is_configured():
            return {
                "success": False,
                "error": "IOT_ENDPOINT_NOT_CONFIGURED",
                "message": "AWS IoT Core endpoint is not configured in .env",
                "payload": payload
            }

        try:
            iot_data = boto3.client("iot-data", endpoint_url=f"https://{self.endpoint}", region_name=self.region)
            iot_data.publish(
                topic=self.request_topic,
                qos=1,
                payload=json.dumps(payload)
            )
            return {
                "success": True,
                "request_id": request_id,
                "payload": payload,
                "topic": self.request_topic
            }
        except Exception as e:
            logger.error(f"Error publishing to AWS IoT Core: {e}")
            return {
                "success": False,
                "error": str(e),
                "payload": payload
            }
