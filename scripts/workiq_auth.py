"""Device-code sign-in for Work IQ, one token cache per user label.

Gets a delegated token for api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask
with the public client in .env, cached in .token_cache_workiq_<label>.json.
MSAL only; the Work IQ CLI is not used (it fails with a WAM error here).
"""

import os
import sys
from pathlib import Path

import msal
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

WORKIQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"


def workiq_token(label: str) -> str:
    """Return a Work IQ access token for user `label`; the token is never printed."""
    cache_path = ROOT / f".token_cache_workiq_{label}.json"
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text())
    app = msal.PublicClientApplication(
        os.environ["CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}",
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent([WORKIQ_SCOPE], account=accounts[0])
    if not result:
        flow = app.initiate_device_flow(scopes=[WORKIQ_SCOPE])
        if "user_code" not in flow:
            sys.exit(f"Could not start device flow: {flow.get('error_description', flow)}")
        print(f"[user {label}] {flow['message']}", flush=True)
        result = app.acquire_token_by_device_flow(flow)

    if cache.has_state_changed:
        cache_path.write_text(cache.serialize())
    if "access_token" not in result:
        sys.exit(f"Sign-in failed: {result.get('error')}: {result.get('error_description')}")
    claims = result.get("id_token_claims") or {}
    user = claims.get("preferred_username") or (accounts[0]["username"] if accounts else "?")
    print(f"Work IQ token for {user}", flush=True)
    return result["access_token"]
