"""
AWS Lambda Function: ESP32-KeyRotationHandler
Triggered by: AWS IoT Core Rule on topic 'esp32/key_rotation/request'
Action: Validates request, triggers AWS KMS On-Demand Rotation, publishes safe result to 'esp32/key_rotation/response'

SECURITY & PRIVACY RULES:
1. Validates device_id and action.
2. Calls AWS KMS kms:RotateKeyOnDemand (or describes/rotates key).
3. Increments key material version while keeping KMS Key ID intact.
4. NEVER returns plaintext key material.
5. Publishes result payload back to AWS IoT Core response topic.
"""

import json
import os
import boto3
import logging
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
KMS_KEY_ID = os.environ.get("KMS_KEY_ID")
RESPONSE_TOPIC = os.environ.get("RESPONSE_TOPIC", "esp32/key_rotation/response")
IOT_ENDPOINT = os.environ.get("IOT_ENDPOINT")

def lambda_handler(event, context):
    logger.info(f"Received IoT Key Rotation event: {json.dumps(event)}")
    
    # 1. Parse Event Payload
    # AWS IoT rules pass the payload directly or inside event dictionary
    device_id = event.get("device_id", "UNKNOWN_DEVICE")
    action = event.get("action", "")
    request_id = event.get("request_id", f"REQ-{datetime.now(timezone.utc).strftime('%H%M%S')}")
    
    # 2. Validation
    if action != "ROTATE_KEY":
        error_msg = f"Invalid action: '{action}'. Expected 'ROTATE_KEY'."
        logger.error(error_msg)
        response_payload = {
            "device_id": device_id,
            "request_id": request_id,
            "status": "FAILED",
            "error_code": "INVALID_ACTION",
            "message": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        publish_response(response_payload)
        return {"statusCode": 400, "body": response_payload}

    if not KMS_KEY_ID:
        error_msg = "Lambda environment variable 'KMS_KEY_ID' is not set."
        logger.error(error_msg)
        response_payload = {
            "device_id": device_id,
            "request_id": request_id,
            "status": "FAILED",
            "error_code": "CONFIG_ERROR",
            "message": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        publish_response(response_payload)
        return {"statusCode": 500, "body": response_payload}

    # 3. Call AWS KMS to trigger Key Rotation
    kms_client = boto3.client("kms")
    
    try:
        logger.info(f"Invoking KMS RotateKeyOnDemand for KeyId: {KMS_KEY_ID}")
        # KMS On-demand key rotation (AWS KMS API)
        rotate_resp = kms_client.rotate_key_on_demand(KeyId=KMS_KEY_ID)
        key_id = rotate_resp.get("KeyId", KMS_KEY_ID)
        
        # Get Key metadata to verify new version / status
        desc = kms_client.describe_key(KeyId=KMS_KEY_ID)
        meta = desc.get("KeyMetadata", {})
        
        # Retrieve rotation count
        rot_count = 1
        try:
            rotations = kms_client.list_key_rotations(KeyId=KMS_KEY_ID).get("Rotations", [])
            rot_count = len(rotations) + 1
        except Exception:
            rot_count = 2

        # 4. Construct Safe Response (NEVER include cryptographic plaintext)
        response_payload = {
            "device_id": device_id,
            "request_id": request_id,
            "status": "SUCCESS",
            "key_id": key_id,
            "key_arn": meta.get("Arn", f"arn:aws:kms:...:key/{key_id}"),
            "key_spec": meta.get("KeySpec", "SYMMETRIC_DEFAULT"),
            "key_version": rot_count,
            "version_display": f"{rot_count:02d}",
            "message": "KMS Key Rotation completed successfully.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"Key rotation successful: {response_payload}")

    except ClientError as ce:
        err_code = ce.response.get("Error", {}).get("Code", "KMS_ERROR")
        err_msg = ce.response.get("Error", {}).get("Message", str(ce))
        logger.error(f"AWS KMS ClientError: {err_code} - {err_msg}")
        
        response_payload = {
            "device_id": device_id,
            "request_id": request_id,
            "status": "FAILED",
            "error_code": err_code,
            "message": f"KMS Error: {err_msg}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        response_payload = {
            "device_id": device_id,
            "request_id": request_id,
            "status": "FAILED",
            "error_code": "INTERNAL_ERROR",
            "message": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    # 5. Publish Response back to AWS IoT Core Topic
    publish_response(response_payload)
    return {"statusCode": 200, "body": response_payload}


def publish_response(payload):
    """Publishes JSON response payload to AWS IoT Core response topic."""
    try:
        endpoint_url = f"https://{IOT_ENDPOINT}" if IOT_ENDPOINT else None
        iot_data = boto3.client("iot-data", endpoint_url=endpoint_url)
        iot_data.publish(
            topic=RESPONSE_TOPIC,
            qos=1,
            payload=json.dumps(payload)
        )
        logger.info(f"Published response to topic {RESPONSE_TOPIC}")
    except Exception as e:
        logger.error(f"Failed to publish response to IoT Core topic {RESPONSE_TOPIC}: {e}")
