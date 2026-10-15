"""Step 3 check: call every MCP tool as a user, and confirm 401 without a valid token.

Start the server first:  uv run python -m mcp_server.server
Then:                    uv run scripts/check_mcp.py [label]
"""

import asyncio
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import httpx
from fastmcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parent))
from signin import ROOT, sign_in  # noqa: E402

URL = "http://127.0.0.1:8001/mcp"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "check", "version": "0"}}}
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def show(title, value, limit=8):
    print(f"\n== {title}")
    if isinstance(value, list):
        for v in value[:limit]:
            print("  ", json.dumps(v, default=str)[:220])
        if len(value) > limit:
            print(f"   ... {len(value) - limit} more ({len(value)} total)")
    else:
        print("  ", json.dumps(value, default=str, indent=1)[:2500])


async def main(label: str):
    async with httpx.AsyncClient() as h:
        r = await h.post(URL, json=INIT, headers=HEADERS)
        print(f"No token        -> HTTP {r.status_code}")
        r = await h.post(URL, json=INIT, headers={**HEADERS, "Authorization": "Bearer not-a-real-token"})
        print(f"Bad token       -> HTTP {r.status_code}")

    token = sign_in(label)
    async with Client(URL, auth=token) as c:
        data = lambda res: res.structured_content.get("result", res.structured_content) \
            if res.structured_content is not None else res.data

        sites = data(await c.call_tool("list_sites", {}))
        show("list_sites", sites, limit=30)

        sts = next(s for s in sites if s["name"] == "sts it services")
        libs = data(await c.call_tool("list_libraries", {"site_id": sts["site_id"]}))
        show("list_libraries (sts it services)", libs)

        docs = next(l for l in libs if l["name"] == "Documents")
        files = data(await c.call_tool("list_files", {"drive_id": docs["drive_id"]}))
        show("list_files (sts it services / Documents)", files, limit=3)
        sub = data(await c.call_tool("list_files", {"drive_id": docs["drive_id"], "folder_path": "competitor reports"}))
        print(f"   folder_path='competitor reports' -> {len(sub)} file(s)")

        found = data(await c.call_tool("search_files", {"name_contains": "yara", "file_type": "pdf"}))
        show("search_files name~yara type=pdf", found)
        recent = data(await c.call_tool("search_files", {"modified_after": "2025-07-01"}))
        show("search_files modified_after=2025-07-01", recent)
        none = data(await c.call_tool("search_files", {"name_contains": "quarterly-unicorn-plan"}))
        print(f"   made-up name -> {len(none)} result(s)")

        meta = data(await c.call_tool("get_file_metadata", {"drive_id": files[0]["drive_id"], "item_id": files[0]["item_id"]}))
        show("get_file_metadata", meta)

        summary = data(await c.call_tool("inventory_summary", {}))
        show("inventory_summary", {k: summary[k] for k in ("total_files", "total_bytes", "by_site", "by_type")})

    rows = list(csv.DictReader((ROOT / "inventory.csv").open(encoding="utf-8")))
    csv_by_site = Counter(r["site"] for r in rows)
    mcp_by_site = {s: v["files"] for s, v in summary["by_site"].items()}
    print("\n== inventory_summary vs inventory.csv")
    print(f"   total: mcp={summary['total_files']} csv={len(rows)}")
    print(f"   per site match: {dict(csv_by_site) == mcp_by_site}")
    print(f"   per type match: {dict(Counter(r['type'] for r in rows)) == {t: v['files'] for t, v in summary['by_type'].items()}}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "a"))
