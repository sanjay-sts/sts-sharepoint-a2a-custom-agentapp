"""Microsoft token handling and Graph helpers shared by the MCP server.

- validate_token: check an incoming bearer token was issued for our API.
- graph_token_for: exchange that user token for a Graph token (on-behalf-of),
  cached in memory per user (keyed by the token's oid claim).
- get_paged / walk_files: Graph reads; both take the Graph token explicitly.

Tokens are never logged. Callers log claims["preferred_username"] or ["oid"].
"""

import os
import threading
import time
from pathlib import Path

import httpx
import jwt
import msal
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
API_SCOPE = f"api://{CLIENT_ID}/access_as_user"
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["https://graph.microsoft.com/Sites.Read.All", "https://graph.microsoft.com/Files.Read.All"]

_AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
_AUDIENCES = [f"api://{CLIENT_ID}", CLIENT_ID]
_ISSUERS = [f"https://sts.windows.net/{TENANT_ID}/", f"{_AUTHORITY}/v2.0"]
_jwks = jwt.PyJWKClient(f"{_AUTHORITY}/discovery/v2.0/keys", cache_keys=True)


class AuthError(Exception):
    """The incoming token is missing or invalid. Message is safe to return to the caller."""


def validate_token(token: str) -> dict:
    """Return the token's claims, or raise AuthError."""
    if not token:
        raise AuthError("missing bearer token")
    try:
        key = _jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=_AUDIENCES,
            issuer=_ISSUERS,
            options={"require": ["exp", "iat", "aud", "iss", "oid"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("token expired") from None
    except (jwt.PyJWTError, jwt.PyJWKClientError) as e:
        raise AuthError(f"invalid token: {type(e).__name__}") from None
    if claims.get("tid") != TENANT_ID:
        raise AuthError("invalid token: wrong tenant")
    if "access_as_user" not in claims.get("scp", "").split():
        raise AuthError("invalid token: missing access_as_user scope")
    return claims


_cca = None
_cca_lock = threading.Lock()
_graph_cache: dict[str, tuple[str, float]] = {}  # oid -> (graph token, expires at)
_graph_cache_lock = threading.Lock()


def _confidential_client() -> msal.ConfidentialClientApplication:
    global _cca
    with _cca_lock:
        if _cca is None:
            _cca = msal.ConfidentialClientApplication(
                CLIENT_ID,
                authority=_AUTHORITY,
                client_credential=os.environ["CLIENT_SECRET"],
            )
        return _cca


def graph_token_for(token: str, claims: dict) -> str:
    """Exchange a validated user token for a Graph token for that same user.

    `claims` must come from validate_token(token). The cache key is the user's
    oid, so one user's Graph token can never answer another user's request.
    """
    oid = claims["oid"]
    with _graph_cache_lock:
        cached = _graph_cache.get(oid)
        if cached and cached[1] - 60 > time.time():
            return cached[0]

    result = _confidential_client().acquire_token_on_behalf_of(token, GRAPH_SCOPES)
    if "access_token" not in result:
        # error_description never contains the token itself
        raise AuthError(f"on-behalf-of failed: {result.get('error')}: {result.get('error_description', '').splitlines()[0] if result.get('error_description') else ''}")

    with _graph_cache_lock:
        _graph_cache[oid] = (result["access_token"], time.time() + int(result.get("expires_in", 0)))
    return result["access_token"]


async def get_paged(graph_token: str, url: str):
    """Yield every item of a Graph collection, following @odata.nextLink."""
    if not url.startswith("https://"):
        url = f"{GRAPH}/{url.lstrip('/')}"
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {graph_token}"}, timeout=30) as client:
        while url:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("value", []):
                yield item
            url = data.get("@odata.nextLink")


async def get_json(graph_token: str, url: str) -> dict:
    """GET a single Graph resource."""
    if not url.startswith("https://"):
        url = f"{GRAPH}/{url.lstrip('/')}"
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {graph_token}"}, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def walk_files(graph_token: str, drive_id: str, item_id: str = "root", folder: str = ""):
    """Yield (folder_path, driveItem) for every file under a drive folder, recursively."""
    async for item in get_paged(graph_token, f"drives/{drive_id}/items/{item_id}/children"):
        if "folder" in item:
            sub = f"{folder}/{item['name']}" if folder else item["name"]
            async for pair in walk_files(graph_token, drive_id, item["id"], sub):
                yield pair
        elif "file" in item:
            yield folder, item
