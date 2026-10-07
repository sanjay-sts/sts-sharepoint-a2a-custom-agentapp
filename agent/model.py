"""Claude on Bedrock via langchain-aws.

Credentials come only from boto3's default resolution: AWS_PROFILE (SSO /
temporary credentials) or AWS_BEARER_TOKEN_BEDROCK (Bedrock API key).
Nothing credential-related is passed here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def make_model() -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model_id=os.environ["BEDROCK_MODEL_ID"],
        region_name=os.environ["AWS_REGION"],
        temperature=0,
    )


_CREDENTIAL_ERRORS = (
    "NoCredentialsError", "ExpiredToken", "ExpiredTokenException", "TokenRetrievalError",
    "UnauthorizedSSOTokenError", "SSOTokenLoadError", "UnrecognizedClientException",
    "InvalidSignatureException", "security token included in the request is expired",
    "Unable to locate credentials", "Error when retrieving token from sso",
)


def credential_problem(exc: BaseException) -> str | None:
    """If exc is an expired/missing AWS credential error, return a plain message saying how to refresh."""
    text = f"{type(exc).__name__}: {exc}"
    if not any(marker in text for marker in _CREDENTIAL_ERRORS):
        return None
    if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        return ("AWS credentials for Bedrock are missing or expired. "
                "Generate a new Bedrock API key and update AWS_BEARER_TOKEN_BEDROCK, then restart the agent.")
    profile = os.environ.get("AWS_PROFILE")
    login = f"aws sso login --profile {profile}" if profile else "aws sso login"
    return f"AWS credentials for Bedrock are missing or expired. Run: {login}  then retry."
