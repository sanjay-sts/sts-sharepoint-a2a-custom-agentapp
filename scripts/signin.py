"""Device-code sign-in for test scripts, one token cache per user label.

Gets a token for our API (api://<client-id>/access_as_user), cached in
.token_cache_<label>.json and reused silently on later runs.
"""

import os
import sys
from pathlib import Path

import msal
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def sign_in(label: str) -> str:
    """Return an access token for api://<client-id>/access_as_user as user `label`."""
    client_id = os.environ["CLIENT_ID"]
    scopes = [f"api://{client_id}/access_as_user"]
    cache_path = ROOT / f".token_cache_{label}.json"

    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text())
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}",
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            sys.exit(f"Could not start device flow: {flow.get('error_description', flow)}")
        print(f"[user {label}] {flow['message']}", flush=True)
        result = app.acquire_token_by_device_flow(flow)

    if cache.has_state_changed:
        cache_path.write_text(cache.serialize())
    if "access_token" not in result:
        sys.exit(f"Sign-in failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]
