"""
AWS KMS Manager
Handles real AWS KMS operations via boto3 with simulated fallback.
Follows real AWS KMS architecture:
- KMS Key ID remains constant during key rotations.
- Key material version increments and rotation metadata updates.
- Cryptographic plaintext secrets are NEVER returned or exposed.
"""

import os
import datetime
import logging

logger = logging.getLogger("kms_manager")

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    ClientError = Exception
    NoCredentialsError = Exception

class KMSManager:
    def __init__(self, key_id=None, region="us-east-1"):
        self.key_id = key_id or os.getenv("KMS_KEY_ID", "").strip()
        self.region = region or os.getenv("AWS_REGION", "us-east-1").strip()
        self.client = None
        self._init_client()

    def _init_client(self):
        if not BOTO3_AVAILABLE:
            return
        try:
            self.client = boto3.client("kms", region_name=self.region)
        except Exception as e:
            logger.warning(f"Could not initialize AWS KMS client: {e}")
            self.client = None

    def is_configured(self):
        """Check if KMS Key ID and AWS client credentials are provided."""
        return bool(BOTO3_AVAILABLE and self.key_id and self.client)

    def get_key_metadata(self):
        """
        Fetch actual KMS Key metadata from AWS KMS.
        """
        if not self.is_configured():
            return {
                "status": "NOT_CONFIGURED",
                "key_id": self.key_id or "Not configured",
                "arn": "Not configured",
                "key_state": "Not Configured",
                "key_spec": "SYMMETRIC_DEFAULT",
                "key_usage": "ENCRYPT_DECRYPT",
                "origin": "AWS_KMS",
                "multi_region": False,
                "rotation_enabled": False,
                "version": 1,
                "last_rotated": "Never",
                "error": "boto3 library or KMS_KEY_ID not configured in .env"
            }

        try:
            desc = self.client.describe_key(KeyId=self.key_id)
            meta = desc.get("KeyMetadata", {})

            rot_status = False
            try:
                rot = self.client.get_key_rotation_status(KeyId=self.key_id)
                rot_status = rot.get("KeyRotationEnabled", False)
            except Exception:
                pass

            rotations = []
            try:
                rot_list = self.client.list_key_rotations(KeyId=self.key_id)
                rotations = rot_list.get("Rotations", [])
            except Exception:
                pass

            version = len(rotations) + 1 if rotations else 1
            last_rot = "Never"
            if rotations:
                latest_rot = rotations[-1].get("RotationDate")
                if latest_rot:
                    last_rot = latest_rot.strftime("%Y-%m-%d %H:%M:%S UTC")
            elif meta.get("CreationDate"):
                last_rot = meta.get("CreationDate").strftime("%Y-%m-%d %H:%M:%S UTC")

            return {
                "status": "ACTIVE" if meta.get("Enabled") else "DISABLED",
                "key_id": meta.get("KeyId", self.key_id),
                "arn": meta.get("Arn", f"arn:aws:kms:{self.region}:...:key/{self.key_id}"),
                "key_state": meta.get("KeyState", "Enabled"),
                "key_spec": meta.get("KeySpec", "SYMMETRIC_DEFAULT"),
                "key_usage": meta.get("KeyUsage", "ENCRYPT_DECRYPT"),
                "origin": meta.get("Origin", "AWS_KMS"),
                "multi_region": meta.get("MultiRegion", False),
                "rotation_enabled": rot_status,
                "version": version,
                "last_rotated": last_rot,
                "error": None
            }

        except Exception as ce:
            logger.error(f"KMS DescribeKey error: {ce}")
            return {
                "status": "ERROR",
                "key_id": self.key_id,
                "arn": "Error fetching ARN",
                "key_state": "Error",
                "key_spec": "SYMMETRIC_DEFAULT",
                "key_usage": "ENCRYPT_DECRYPT",
                "origin": "AWS_KMS",
                "multi_region": False,
                "rotation_enabled": False,
                "version": 1,
                "last_rotated": "Unknown",
                "error": str(ce)
            }

    def rotate_key_on_demand(self):
        """
        Trigger an on-demand key rotation in AWS KMS.
        """
        if not self.is_configured():
            return {
                "success": False,
                "error_type": "NOT_CONFIGURED",
                "message": "KMS Key ID or AWS credentials not configured. Please check your .env file.",
                "solution": "Set KMS_KEY_ID, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY in .env"
            }

        try:
            response = self.client.rotate_key_on_demand(KeyId=self.key_id)
            new_key_id = response.get("KeyId", self.key_id)
            
            meta = self.get_key_metadata()
            new_version = meta.get("version", 2)

            return {
                "success": True,
                "key_id": new_key_id,
                "arn": meta.get("arn"),
                "version": new_version,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "message": "AWS KMS key material rotated successfully on-demand."
            }

        except Exception as ce:
            msg = str(ce)
            logger.error(f"KMS RotateKeyOnDemand error: {msg}")

            friendly_solution = "Verify your AWS IAM permissions."
            if "AccessDeniedException" in msg:
                friendly_solution = "Your IAM user or role lacks 'kms:RotateKeyOnDemand' permission for this key."
            elif "NotFoundException" in msg:
                friendly_solution = "The specified KMS Key ID was not found in region " + self.region
            elif "LimitExceededException" in msg:
                friendly_solution = "AWS KMS on-demand rotation limit reached (max 10 on-demand rotations per key per year)."
            elif "DisabledException" in msg:
                friendly_solution = "The KMS key is currently Disabled. Enable it in the AWS KMS Console."

            return {
                "success": False,
                "error_type": "KMSError",
                "message": f"KMS Rotation Failed: {msg}",
                "solution": friendly_solution
            }
