"""
AWS KMS Manager — Encryption Key Rotation Button
================================================
Handles REAL AWS KMS operations via boto3 with safe simulated fallback.

Key design rules (matching real AWS KMS behaviour):
  - KMS Key ID NEVER changes during a rotation.
  - On-demand rotation changes the backing *key material* while keeping the same Key ID.
  - Private key material / secret values are NEVER returned or logged.
  - All errors are surfaced with a safe human-readable message only.

Supported key reference formats:
  - Key ID:   "450b3db5-8fbb-4693-9c95-0cc1531adb0c"
  - Key ARN:  "arn:aws:kms:us-east-1:123456789012:key/450b3db5-..."
  - Alias:    "alias/encryption-key-rotation"
"""

import os
import logging
import datetime

logger = logging.getLogger("kms_manager")

# ---------------------------------------------------------------------------
# Safe boto3 import — never crashes the app if library is absent
# ---------------------------------------------------------------------------
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError, EndpointResolutionError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    ClientError = Exception
    NoCredentialsError = Exception
    EndpointResolutionError = Exception


class KMSManager:
    """
    Manages AWS KMS operations for the Encryption Key Rotation Button project.

    University lab restriction note:
      IAM role creation and Lambda/IoT setup are out of scope.
      Only AWS KMS RotateKeyOnDemand is called directly from this backend.
    """

    def __init__(self, key_id: str = None, region: str = None):
        # Accept Key ID, ARN, or Alias (e.g. "alias/encryption-key-rotation")
        self.key_id = (key_id or os.getenv("KMS_KEY_ID", "")).strip()
        self.region = (region or os.getenv("AWS_REGION", "us-east-1")).strip()
        self.client = None
        self._resolved_key_id = None   # canonical UUID key ID resolved from alias
        self._init_client()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_client(self):
        if not BOTO3_AVAILABLE:
            logger.warning("boto3 is not installed — KMS calls will not work.")
            return
        try:
            self.client = boto3.client("kms", region_name=self.region)
            logger.info(f"KMS client initialised for region {self.region}")
        except Exception as exc:
            logger.warning(f"Could not create boto3 KMS client: {exc}")
            self.client = None

    def _safe_key_ref(self) -> str:
        """Return alias or key id for display — never the actual key material."""
        return self.key_id or "Not configured"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """True only when boto3 is available AND a Key ID / alias is set."""
        return bool(BOTO3_AVAILABLE and self.key_id and self.client)

    def get_kms_status(self) -> dict:
        """
        Return safe metadata about the configured KMS key.
        Called by GET /api/kms/status.
        Never returns key material, credentials, or secret data.
        """
        if not self.is_configured():
            return {
                "configured": False,
                "key_ref": self._safe_key_ref(),
                "region": self.region,
                "status": "NOT_CONFIGURED",
                "reason": "boto3 not installed or KMS_KEY_ID not set in environment.",
            }

        try:
            desc = self.client.describe_key(KeyId=self.key_id)
            meta = desc.get("KeyMetadata", {})
            actual_key_id = meta.get("KeyId", self.key_id)
            self._resolved_key_id = actual_key_id

            # Rotation status (may not be available on all key types)
            rotation_enabled = False
            try:
                rot = self.client.get_key_rotation_status(KeyId=actual_key_id)
                rotation_enabled = rot.get("KeyRotationEnabled", False)
            except Exception:
                pass

            # Count on-demand rotations performed (list_key_rotations — may not exist in all SDK versions)
            rotation_count = 0
            last_rotated = "Never"
            try:
                rot_list = self.client.list_key_rotations(KeyId=actual_key_id)
                rotations = rot_list.get("Rotations", [])
                rotation_count = len(rotations)
                if rotations:
                    latest = rotations[-1].get("RotationDate")
                    if latest:
                        last_rotated = latest.strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                # list_key_rotations not available in this SDK version — use creation date
                creation = meta.get("CreationDate")
                if creation:
                    last_rotated = creation.strftime("%Y-%m-%d %H:%M:%S UTC")

            return {
                "configured": True,
                "key_ref": self._safe_key_ref(),
                "key_id": actual_key_id,                    # safe — this is the UUID, not key material
                "arn": meta.get("Arn", ""),
                "region": self.region,
                "status": "ACTIVE" if meta.get("Enabled") else "DISABLED",
                "key_state": meta.get("KeyState", "Unknown"),
                "key_spec": meta.get("KeySpec", "SYMMETRIC_DEFAULT"),
                "key_usage": meta.get("KeyUsage", "ENCRYPT_DECRYPT"),
                "origin": meta.get("Origin", "AWS_KMS"),
                "multi_region": meta.get("MultiRegion", False),
                "rotation_auto_enabled": rotation_enabled,
                "rotation_count": rotation_count,
                "last_rotated": last_rotated,
                "error": None,
            }

        except Exception as exc:
            safe_msg = _safe_error_message(exc)
            logger.error(f"KMS DescribeKey failed: {exc}")
            return {
                "configured": True,       # credentials exist but the call failed
                "key_ref": self._safe_key_ref(),
                "region": self.region,
                "status": "ERROR",
                "error": safe_msg,
            }

    def rotate_key_on_demand(self) -> dict:
        """
        Trigger an on-demand KMS key rotation.
        Called only when the user explicitly selects REAL KMS MODE and confirms.

        Returns a safe result dict — NEVER includes key material or credentials.
        """
        if not self.is_configured():
            return {
                "success": False,
                "error_type": "NOT_CONFIGURED",
                "message": "KMS Key ID or AWS credentials not configured.",
                "solution": (
                    "Set KMS_KEY_ID and AWS credentials in your .env file, "
                    "then restart the server."
                ),
            }

        try:
            response = self.client.rotate_key_on_demand(KeyId=self.key_id)
            # response contains only KeyId — safe to use
            actual_key_id = response.get("KeyId", self.key_id)

            # Fetch fresh metadata to get updated rotation count
            meta = self.get_kms_status()
            rotation_count = meta.get("rotation_count", 1)

            return {
                "success": True,
                "key_id": actual_key_id,             # same ID — key material changed, not the ID
                "rotation_count": rotation_count,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
                "message": "AWS KMS key material rotated successfully via on-demand rotation.",
                "kms_mode": "REAL",
            }

        except Exception as exc:
            safe_msg = _safe_error_message(exc)
            solution = _rotation_solution(str(exc))
            logger.error(f"KMS RotateKeyOnDemand failed: {exc}")
            return {
                "success": False,
                "error_type": "KMSError",
                "message": f"KMS Rotation Failed: {safe_msg}",
                "solution": solution,
            }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_error_message(exc: Exception) -> str:
    """Extract a human-readable, safe error string — no credentials leak."""
    msg = str(exc)
    # Strip any token/credential-looking substrings just in case
    for sensitive in ("Credential", "credential", "AccessKey", "SecretKey", "Token", "token"):
        if sensitive in msg:
            return "AWS authentication error. Check your credentials in .env."
    return msg


def _rotation_solution(msg: str) -> str:
    if "AccessDeniedException" in msg:
        return (
            "Your AWS user/role lacks 'kms:RotateKeyOnDemand' permission on this key. "
            "Add this permission in the AWS Console → IAM."
        )
    if "NotFoundException" in msg:
        return "The KMS Key ID or alias was not found. Check KMS_KEY_ID in .env."
    if "LimitExceededException" in msg:
        return (
            "AWS KMS on-demand rotation limit reached (max 10 per key per year). "
            "Wait or use a different key."
        )
    if "DisabledException" in msg:
        return "The KMS key is disabled. Enable it in the AWS Console → KMS."
    if "InvalidArnException" in msg or "InvalidKeyId" in msg:
        return "KMS_KEY_ID value is invalid. Use a UUID Key ID or alias/your-alias-name."
    return "Verify your AWS IAM permissions and KMS key configuration."
