"""
AWS KMS Manager — Encryption Key Rotation Button
================================================
Handles REAL AWS KMS operations via boto3 with safe simulated fallback.

Supports AWS authentication via:
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_SESSION_TOKEN (for temporary credentials, e.g. AWS VocLabs / Academy / Learner Lab)
  - AWS_REGION (default: us-east-1)
  - KMS_KEY_ID (default: 4f206dc3-dea4-4fcf-baee-8624627af374)

Key design rules (matching real AWS KMS behavior):
  - KMS Key ID NEVER changes during a rotation.
  - On-demand rotation (kms:RotateKeyOnDemand) rotates the backing cryptographic
    key material inside AWS HSMs while keeping the exact same Key ID.
  - Private key material, secret keys, or session tokens are NEVER returned, logged, or exposed.
  - Read-only methods (DescribeKey / GetKeyRotationStatus) NEVER mutate KMS state.
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
    # Internal helpers & dynamic client management
    # ------------------------------------------------------------------

    def is_boto3_available(self) -> bool:
        return BOTO3_AVAILABLE

    def has_credentials(self) -> bool:
        """Check whether basic AWS access keys are present in the environment."""
        access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
        return bool(access_key and secret_key)

    def has_session_token(self) -> bool:
        """Check whether temporary AWS session token is present."""
        return bool(os.getenv("AWS_SESSION_TOKEN", "").strip())

    def _init_client(self):
        """Initialize or refresh boto3 client with current environment variables."""
        if not BOTO3_AVAILABLE:
            logger.warning("boto3 is not installed — KMS calls will not work.")
            self.client = None
            return

        try:
            self.region = os.getenv("AWS_REGION", self.region or DEFAULT_AWS_REGION).strip()
            self.key_id = os.getenv("KMS_KEY_ID", self.key_id or DEFAULT_KMS_KEY_ID).strip()

            access_key = os.getenv("AWS_ACCESS_KEY_ID", "").strip() or None
            secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip() or None
            session_token = os.getenv("AWS_SESSION_TOKEN", "").strip() or None

            client_kwargs = {"region_name": self.region}
            if access_key and secret_key:
                client_kwargs["aws_access_key_id"] = access_key
                client_kwargs["aws_secret_access_key"] = secret_key
                if session_token:
                    client_kwargs["aws_session_token"] = session_token

            self.client = boto3.client("kms", **client_kwargs)
            logger.info(f"KMS client initialized for region {self.region}")
        except Exception as exc:
            logger.warning(f"Could not create boto3 KMS client: {exc}")
            self.client = None

    def is_configured(self) -> bool:
        """True when boto3 is available, key ID is set, and credentials are configured."""
        self._init_client()
        return bool(BOTO3_AVAILABLE and self.key_id and self.has_credentials() and self.client)

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
        self._init_client()

        if not self.is_configured():
            if not self.has_credentials():
                reason = "AWS credentials are not configured. Add temporary AWS credentials to .env or use Demo Mode."
            else:
                reason = "boto3 library or KMS Key ID not configured."

            return {
                "configured": False,
                "key_id": self.key_id,
                "region": self.region,
                "status": "NOT_CONFIGURED",
                "rotation_status": "Not available",
                "last_rotated": "Not available",
                "error": reason,
                "reason": reason,
                "mode": "REAL",
            }

        try:
            # 1. Call DescribeKey for key metadata (Read-Only)
            desc = self.client.describe_key(KeyId=self.key_id)
            meta = desc.get("KeyMetadata", {})
            actual_key_id = meta.get("KeyId", self.key_id)

            # 2. Call GetKeyRotationStatus for annual rotation status (Read-Only)
            rotation_enabled = False
            try:
                rot = self.client.get_key_rotation_status(KeyId=actual_key_id)
                rotation_enabled = rot.get("KeyRotationEnabled", False)
            except Exception as e:
                logger.debug(f"GetKeyRotationStatus optional check: {e}")

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
        self._init_client()

        if not self.has_credentials():
            return {
                "success": False,
                "error_type": "NO_CREDENTIALS",
                "error": "AWS credentials are not configured. Add temporary AWS credentials to .env or use Demo Mode.",
                "message": "AWS credentials are not configured. Add temporary AWS credentials to .env or use Demo Mode.",
                "solution": "Add AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN to your .env file or use Demo Mode.",
                "kms_mode": "REAL",
            }

        if not self.is_configured():
            return {
                "success": False,
                "error_type": "NOT_CONFIGURED",
                "error": "AWS KMS is not configured. Set KMS_KEY_ID and AWS credentials in .env.",
                "message": "AWS KMS is not configured. Set KMS_KEY_ID and AWS credentials in .env.",
                "solution": "Provide AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and KMS_KEY_ID in .env",
                "kms_mode": "REAL",
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
        return ("AWS credentials are not configured. Add temporary AWS credentials to .env or use Demo Mode.", "NO_CREDENTIALS")

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
            return ("AWS credentials have expired. Refresh your AWS VocLabs credentials and restart Flask.", "EXPIRED_TOKEN")

        if code in ("UnrecognizedClientException", "InvalidClientTokenId", "AuthFailure"):
            return ("AWS credentials are invalid or unrecognized. Refresh your AWS VocLabs credentials in .env.", "INVALID_CREDENTIALS")

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
    for sensitive in ("Credential", "credential", "Secret", "secret", "Token", "token", "AccessKey"):
        if sensitive in msg:
            return ("AWS authentication error. Check credentials in .env.", "AUTH_ERROR")

    return (msg, "UNKNOWN_ERROR")


def _get_error_solution(error_code: str, key_id: str, region: str) -> str:
    """Return user-friendly remediation advice for each error code."""
    solutions = {
        "NO_CREDENTIALS": "Add AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN to your .env file or use Demo Mode.",
        "EXPIRED_TOKEN": "AWS credentials / session token have expired. Refresh your AWS VocLabs credentials from your lab session into .env and restart Flask.",
        "INVALID_CREDENTIALS": "Check AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN in .env.",
        "PARTIAL_CREDENTIALS": "Ensure AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN are all provided in .env.",
        "ACCESS_DENIED": "Ensure your AWS IAM user/role has 'kms:DescribeKey', 'kms:GetKeyRotationStatus', and 'kms:RotateKeyOnDemand' permissions.",
        "KEY_NOT_FOUND": f"Ensure Key ID '{key_id}' exists in region '{region}'.",
        "LIMIT_EXCEEDED": "AWS allows up to 10 on-demand rotations per key per year. Test with Demo Mode or create a new test key.",
        "KEY_DISABLED": "Go to AWS KMS Console -> Customer managed keys -> Key actions -> Enable key.",
        "ENDPOINT_ERROR": f"Check your internet connection and verify AWS_REGION='{region}'.",
    }
    return solutions.get(error_code, "Check your AWS configuration and KMS permissions.")
