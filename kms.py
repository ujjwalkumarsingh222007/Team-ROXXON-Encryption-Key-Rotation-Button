"""
AWS KMS Manager — Encryption Key Rotation Button
================================================
Handles REAL AWS KMS operations via boto3 with safe simulated fallback.

Target AWS KMS Key Details:
  - Region: us-east-1
  - Key ID: 4f206dc3-dea4-4fcf-baee-8624627af374

Key design rules (matching real AWS KMS behavior):
  - KMS Key ID NEVER changes during a rotation.
  - On-demand rotation (kms:RotateKeyOnDemand) rotates the backing cryptographic
    key material inside AWS HSMs while keeping the same Key ID.
  - Private key material / secret credentials are NEVER returned or logged.
  - No rotation occurs on startup or status checks (DescribeKey / GetKeyRotationStatus only).
  - RotateKeyOnDemand is called ONLY when the user explicitly triggers REAL KMS mode.
"""

import os
import logging
import datetime

logger = logging.getLogger("kms_manager")

DEFAULT_KMS_KEY_ID = "4f206dc3-dea4-4fcf-baee-8624627af374"
DEFAULT_AWS_REGION = "us-east-1"

# ---------------------------------------------------------------------------
# Safe boto3 import — never crashes the app if library is absent
# ---------------------------------------------------------------------------
try:
    import boto3
    from botocore.exceptions import (
        ClientError,
        NoCredentialsError,
        PartialCredentialsError,
        EndpointResolutionError,
        EndpointConnectionError,
        ConnectTimeoutError,
        BotoCoreError,
    )
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    ClientError = Exception
    NoCredentialsError = Exception
    PartialCredentialsError = Exception
    EndpointResolutionError = Exception
    EndpointConnectionError = Exception
    ConnectTimeoutError = Exception
    BotoCoreError = Exception


class KMSManager:
    """
    Manages AWS KMS operations for the Encryption Key Rotation project.

    Uses boto3 to interact directly with AWS KMS in us-east-1.
    """

    def __init__(self, key_id: str = None, region: str = None):
        self.key_id = (key_id or os.getenv("KMS_KEY_ID", DEFAULT_KMS_KEY_ID)).strip()
        self.region = (region or os.getenv("AWS_REGION", DEFAULT_AWS_REGION)).strip()
        self.client = None
        self._init_client()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_client(self):
        if not BOTO3_AVAILABLE:
            logger.warning("boto3 is not installed — KMS calls will not work.")
            return
        try:
            # Uses environment AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN)
            # or ~/.aws/credentials / IAM role
            self.client = boto3.client("kms", region_name=self.region)
            logger.info(f"KMS client initialised for region {self.region} with Key ID {self.key_id}")
        except Exception as exc:
            logger.warning(f"Could not create boto3 KMS client: {exc}")
            self.client = None

    def is_configured(self) -> bool:
        """True when boto3 is available and a Key ID is set."""
        return bool(BOTO3_AVAILABLE and self.key_id and self.client)

    # ------------------------------------------------------------------
    # Status & Metadata Check (Read-Only: DescribeKey + GetKeyRotationStatus)
    # Does NOT rotate the key! Safe for page refreshes and health polling.
    # ------------------------------------------------------------------

    def get_kms_status(self) -> dict:
        """
        Fetch current status and metadata from AWS KMS.
        Calls DescribeKey and GetKeyRotationStatus.
        NEVER calls RotateKeyOnDemand.
        NEVER returns key material, credentials, or secret data.
        """
        # Re-read env var in case it changed at runtime
        self.key_id = os.getenv("KMS_KEY_ID", self.key_id or DEFAULT_KMS_KEY_ID).strip()
        self.region = os.getenv("AWS_REGION", self.region or DEFAULT_AWS_REGION).strip()

        if not self.is_configured():
            return {
                "configured": False,
                "key_id": self.key_id,
                "region": self.region,
                "status": "NOT_CONFIGURED",
                "error": "boto3 not installed or AWS KMS credentials not available in environment.",
                "reason": "AWS credentials or boto3 not configured.",
            }

        try:
            # 1. Call DescribeKey for key metadata
            desc = self.client.describe_key(KeyId=self.key_id)
            meta = desc.get("KeyMetadata", {})
            actual_key_id = meta.get("KeyId", self.key_id)

            # 2. Call GetKeyRotationStatus for annual rotation status
            rotation_enabled = False
            try:
                rot = self.client.get_key_rotation_status(KeyId=actual_key_id)
                rotation_enabled = rot.get("KeyRotationEnabled", False)
            except Exception as e:
                logger.debug(f"GetKeyRotationStatus optional check: {e}")

            # 3. Optional: check list_key_rotations for on-demand rotation count
            rotation_count = 1
            last_rotated = "Never"
            try:
                rot_list = self.client.list_key_rotations(KeyId=actual_key_id)
                rotations = rot_list.get("Rotations", [])
                rotation_count = max(len(rotations) + 1, 1)
                if rotations:
                    latest = rotations[-1].get("RotationDate")
                    if latest:
                        last_rotated = latest.strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                creation = meta.get("CreationDate")
                if creation:
                    last_rotated = creation.strftime("%Y-%m-%d %H:%M:%S UTC")

            return {
                "configured": True,
                "key_id": actual_key_id,  # Same KMS Key ID: 4f206dc3-dea4-4fcf-baee-8624627af374
                "arn": meta.get("Arn", f"arn:aws:kms:{self.region}:...:key/{actual_key_id}"),
                "region": self.region,
                "status": "Active" if meta.get("Enabled") else "Disabled",
                "key_state": meta.get("KeyState", "Enabled"),
                "key_spec": meta.get("KeySpec", "SYMMETRIC_DEFAULT"),
                "key_usage": meta.get("KeyUsage", "ENCRYPT_DECRYPT"),
                "origin": meta.get("Origin", "AWS_KMS"),
                "multi_region": meta.get("MultiRegion", False),
                "rotation_status": "Ready",
                "last_rotated": "Not available",
                "rotation_auto_enabled": rotation_enabled,
                "error": None,
                "mode": "REAL",
            }

        except Exception as exc:
            safe_error, error_code = _parse_aws_exception(exc, self.key_id, self.region)
            logger.error(f"KMS DescribeKey failed: {exc}")
            return {
                "configured": False,
                "key_id": self.key_id,
                "region": self.region,
                "status": "ERROR",
                "rotation_status": "Not available",
                "last_rotated": "Not available",
                "error_code": error_code,
                "error": safe_error,
                "mode": "REAL",
            }

    # ------------------------------------------------------------------
    # On-Demand Key Rotation (Mutating: RotateKeyOnDemand)
    # Triggered ONLY upon explicit POST /api/rotate with mode="real".
    # ------------------------------------------------------------------

    def rotate_key_on_demand(self) -> dict:
        """
        Trigger an on-demand KMS key rotation on AWS KMS.
        Called ONLY when the user explicitly triggers REAL KMS mode.

        Returns safe metadata showing the SAME Key ID and successful rotation.
        NEVER returns private key material or AWS credentials.
        """
        self.key_id = os.getenv("KMS_KEY_ID", self.key_id or DEFAULT_KMS_KEY_ID).strip()
        self.region = os.getenv("AWS_REGION", self.region or DEFAULT_AWS_REGION).strip()

        if not self.is_configured():
            return {
                "success": False,
                "error_type": "NOT_CONFIGURED",
                "message": "AWS KMS is not configured. Set KMS_KEY_ID and AWS credentials in .env.",
                "solution": "Provide AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and KMS_KEY_ID in .env",
            }

        try:
            # 1. Execute on-demand rotation (ONLY called here)
            response = self.client.rotate_key_on_demand(KeyId=self.key_id)
            returned_key_id = response.get("KeyId", self.key_id)
            rot_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            return {
                "success": True,
                "key_id": returned_key_id or self.key_id,  # Guaranteed SAME KMS Key ID
                "status": "Active",
                "rotation_status": "Key material rotated",
                "last_rotated": rot_time,
                "timestamp": rot_time,
                "message": "Key material rotated successfully in Real AWS KMS on-demand.",
                "kms_mode": "REAL",
            }

        except Exception as exc:
            safe_error, error_code = _parse_aws_exception(exc, self.key_id, self.region)
            solution = _get_error_solution(error_code, self.key_id, self.region)
            logger.error(f"KMS RotateKeyOnDemand failed: {exc}")
            return {
                "success": False,
                "error_type": error_code,
                "error": safe_error,
                "message": f"KMS Rotation Failed: {safe_error}",
                "solution": solution,
                "kms_mode": "REAL",
            }


# ---------------------------------------------------------------------------
# Exception parsing and safety helpers
# ---------------------------------------------------------------------------

def _parse_aws_exception(exc: Exception, key_id: str, region: str) -> tuple[str, str]:
    """
    Parse AWS/botocore exceptions into a safe message and error code.
    Ensures credentials, secret tokens, or internal stack traces are never leaked.
    """
    if isinstance(exc, NoCredentialsError):
        return ("AWS credentials not found. Configure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env.", "NO_CREDENTIALS")

    if isinstance(exc, PartialCredentialsError):
        return ("Incomplete AWS credentials. Both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required.", "PARTIAL_CREDENTIALS")

    if isinstance(exc, (EndpointConnectionError, ConnectTimeoutError, EndpointResolutionError)):
        return (f"Unable to connect to AWS KMS endpoint in region '{region}'. Check network connectivity and AWS_REGION.", "ENDPOINT_ERROR")

    # Boto3 ClientError structured exceptions
    if hasattr(exc, "response") and isinstance(exc.response, dict):
        err_obj = exc.response.get("Error", {})
        code = err_obj.get("Code", "ClientError")
        raw_msg = err_obj.get("Message", str(exc))

        if code in ("ExpiredToken", "ExpiredTokenException"):
            return ("AWS temporary credentials / session token have expired. Please update AWS_SESSION_TOKEN / credentials in .env.", "EXPIRED_TOKEN")

        if code in ("UnrecognizedClientException", "InvalidClientTokenId", "AuthFailure"):
            return ("AWS credentials are invalid or unrecognized by AWS.", "INVALID_CREDENTIALS")

        if code == "AccessDeniedException":
            return (f"Access Denied: IAM role lacks required permissions on KMS key '{key_id}'.", "ACCESS_DENIED")

        if code == "NotFoundException":
            return (f"KMS Key '{key_id}' was not found in AWS region '{region}'. Verify KMS_KEY_ID.", "KEY_NOT_FOUND")

        if code == "LimitExceededException":
            return ("AWS KMS on-demand rotation limit exceeded (maximum 10 on-demand rotations per year per key).", "LIMIT_EXCEEDED")

        if code == "DisabledException":
            return (f"KMS Key '{key_id}' is currently disabled in AWS KMS. Enable it in the AWS Console.", "KEY_DISABLED")

        if code in ("InvalidArnException", "ValidationException"):
            return (f"Invalid KMS Key ID format: '{key_id}'. Use the standard UUID format.", "INVALID_KEY_ID")

        return (f"{code}: {raw_msg}", code)

    # General / fallback exception
    msg = str(exc)
    for sensitive in ("Credential", "credential", "Secret", "secret", "Token", "token"):
        if sensitive in msg:
            return ("AWS authentication error. Check credentials in .env.", "AUTH_ERROR")

    return (msg, "UNKNOWN_ERROR")


def _get_error_solution(error_code: str, key_id: str, region: str) -> str:
    """Return user-friendly remediation advice for each error code."""
    solutions = {
        "EXPIRED_TOKEN": "Your AWS lab session token expired. Copy fresh credentials from AWS CloudShell / Lab details into .env.",
        "INVALID_CREDENTIALS": "Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in your .env file.",
        "NO_CREDENTIALS": "Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION in your .env file.",
        "ACCESS_DENIED": "Ensure your AWS IAM user/role has 'kms:DescribeKey', 'kms:GetKeyRotationStatus', and 'kms:RotateKeyOnDemand' permissions.",
        "KEY_NOT_FOUND": f"Ensure Key ID '{key_id}' exists in region '{region}'.",
        "LIMIT_EXCEEDED": "AWS allows up to 10 on-demand rotations per key per year. Test with Demo Mode or create a new test key.",
        "KEY_DISABLED": "Go to AWS KMS Console -> Customer managed keys -> Key actions -> Enable key.",
        "ENDPOINT_ERROR": f"Check your internet connection and verify AWS_REGION='{region}'.",
    }
    return solutions.get(error_code, "Check your AWS configuration and KMS permissions.")
