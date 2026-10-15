"""List every SharePoint site, library and file the signed-in user can see.

Signs in with the device-code flow (public client), caches the token in
.token_cache.json (or .token_cache_<label>_graph.json with --user), prints a
file count per library and writes inventory.csv, including the DocType column.

    uv run scripts/list_sites.py
    uv run scripts/list_sites.py --user svc
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import httpx
import msal
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / ".token_cache.json"
CSV_PATH = ROOT / "inventory.csv"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Sites.Read.All", "Files.Read.All"]

CSV_FIELDS = [
    "site", "library", "folder", "name", "type", "size", "modified",
    "modified_by", "url", "drive_id", "item_id", "doctype",
]


def get_token(label: str | None = None) -> str:
    load_dotenv(ROOT / ".env")
    cache_path = ROOT / f".token_cache_{label}_graph.json" if label else CACHE_PATH
    tenant_id = os.environ["TENANT_ID"]
    client_id = os.environ["CLIENT_ID"]

    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text())

    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            sys.exit(f"Could not start device flow: {flow.get('error_description', flow)}")
        print(flow["message"], flush=True)
        result = app.acquire_token_by_device_flow(flow)

    if cache.has_state_changed:
        cache_path.write_text(cache.serialize())

    if "access_token" not in result:
        sys.exit(f"Sign-in failed: {result.get('error')}: {result.get('error_description')}")

    claims = result.get("id_token_claims") or {}
    user = claims.get("preferred_username") or (accounts[0]["username"] if accounts else "?")
    print(f"Signed in as {user}\n")
    return result["access_token"]


def get_paged(client: httpx.Client, url: str):
    """Yield every item from a Graph collection, following @odata.nextLink."""
    while url:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        yield from data.get("value", [])
        url = data.get("@odata.nextLink")


def walk_files(client: httpx.Client, drive_id: str, item_id: str = "root", folder: str = ""):
    """Yield (folder_path, item) for every file under a folder, recursively."""
    url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/children?$expand=listItem($expand=fields($select=DocType))"
    for item in get_paged(client, url):
        if "folder" in item:
            sub = f"{folder}/{item['name']}" if folder else item["name"]
            yield from walk_files(client, drive_id, item["id"], sub)
        elif "file" in item:
            yield folder, item


def file_type(name: str) -> str:
    return Path(name).suffix.lstrip(".").lower() or "(none)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", help="token cache label, e.g. svc (default: the original cache)")
    token = get_token(parser.parse_args().user)
    rows = []
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        sites = list(get_paged(client, f"{GRAPH}/sites?search=*"))
        print(f"{len(sites)} site(s)\n")
        for site in sorted(sites, key=lambda s: (s.get("displayName") or s.get("name") or "").lower()):
            site_name = site.get("displayName") or site.get("name")
            print(f"{site_name}  {site.get('webUrl')}")
            try:
                drives = list(get_paged(client, f"{GRAPH}/sites/{site['id']}/drives"))
            except httpx.HTTPStatusError as e:
                print(f"  (could not list libraries: HTTP {e.response.status_code})")
                continue
            if not drives:
                print("  (no libraries)")
            for drive in drives:
                count = 0
                for folder, item in walk_files(client, drive["id"]):
                    count += 1
                    rows.append({
                        "site": site_name,
                        "library": drive["name"],
                        "folder": folder,
                        "name": item["name"],
                        "type": file_type(item["name"]),
                        "size": item.get("size", 0),
                        "modified": item.get("lastModifiedDateTime", ""),
                        "modified_by": ((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", ""),
                        "url": item.get("webUrl", ""),
                        "drive_id": drive["id"],
                        "item_id": item["id"],
                        "doctype": (((item.get("listItem") or {}).get("fields")) or {}).get("DocType", ""),
                    })
                print(f"  {drive['name']}: {count} file(s)")

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n{len(rows)} file(s) written to {CSV_PATH.name}")


if __name__ == "__main__":
    main()
