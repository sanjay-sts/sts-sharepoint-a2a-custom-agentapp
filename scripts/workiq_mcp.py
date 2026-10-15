"""Call the Work IQ remote MCP server (Streamable HTTP) as a test user.

    uv run scripts/workiq_mcp.py tools --user svc     # tool names, retrieve input schema
    uv run scripts/workiq_mcp.py probe --user svc --name p1 "question"
        # retrieve (grounding, OneDriveAndSharePoint), raw structuredContent to
        # workiq_raw_<name>.json, plus the same query through Graph Search

Stops on an HTTP error from the server (prints status and body; a 403 may be a
tenant MCP policy), an empty tools/list, or any Communication site hit.
"""

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from pathlib import Path

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
from list_sites import get_token  # noqa: E402
from workiq_auth import workiq_token  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MCP_URL = "https://workiq.svc.cloud.microsoft/mcp"
GRAPH = "https://graph.microsoft.com/v1.0"

# Communication site is the tenant root: its URLs have no /sites/ or /teams/
# segment, unlike every other site on the tenant.
ROOT_SITE_URL = re.compile(r"https://2tdgcb\.sharepoint\.com/(?!sites/|teams/)[^\s\"']*", re.I)

http_errors: list[tuple[int, str]] = []


async def _record_errors(response: httpx2.Response):
    if response.status_code >= 400:
        await response.aread()
        http_errors.append((response.status_code, response.text[:2000]))


def stop_on_http_error():
    if http_errors:
        for status, body in http_errors:
            print(f"STOP: HTTP {status} from Work IQ MCP\n{body}")
        sys.exit(1)


async def with_session(token: str, fn):
    client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx2.Timeout(30, read=300),
        event_hooks={"response": [_record_errors]},
    )
    try:
        async with client, streamable_http_client(MCP_URL, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                print(f"Server: {init.server_info.name} {init.server_info.version}, "
                      f"protocol {init.protocol_version}")
                return await fn(session)
    except Exception as e:
        stop_on_http_error()
        raise SystemExit(f"MCP call failed: {type(e).__name__}: {e}")
    finally:
        stop_on_http_error()


async def cmd_tools(session: ClientSession):
    tools = (await session.list_tools()).tools
    if not tools:
        sys.exit("STOP: tools/list is empty")
    print(f"\n{len(tools)} tool(s):")
    for t in tools:
        print(f"  {t.name}: {(t.description or '').splitlines()[0][:120] if t.description else ''}")
    for t in tools:
        if "retrieve" in t.name.lower():
            print(f"\n{t.name} description:\n{t.description}\n")
            print(f"{t.name} inputSchema:\n{json.dumps(t.input_schema, indent=2)}")
            if t.output_schema:
                print(f"\n{t.name} outputSchema:\n{json.dumps(t.output_schema, indent=2)}")


def communication_drive_ids() -> set[str]:
    path = ROOT / "seed_manifest.csv"
    if not path.exists():
        return set()
    return {r["drive_id"] for r in csv.DictReader(path.open(encoding="utf-8"))
            if r["site"] == "Communication site"}


def stop_on_communication(raw: str, where: str):
    hits = sorted(set(ROOT_SITE_URL.findall(raw)))
    hits += [d for d in communication_drive_ids() if d in raw]
    if hits:
        print(f"STOP: {where} references Communication site:")
        for h in hits[:20]:
            print(f"  {h}")
        sys.exit(1)


def seed_names() -> dict[str, str]:
    path = ROOT / "seed_manifest.csv"
    return {r["filename"]: r["seed_id"] for r in csv.DictReader(path.open(encoding="utf-8"))}


async def retrieve(session: ClientSession, query: str, capabilities: list[dict]) -> tuple[dict, float]:
    start = time.perf_counter()
    result = await session.call_tool("retrieve", {
        "query": query, "strategy": "grounding", "capabilities": capabilities,
    })
    elapsed = time.perf_counter() - start
    stop_on_http_error()
    if getattr(result, "is_error", False):
        text = " ".join(getattr(c, "text", "") for c in result.content)
        sys.exit(f"STOP: retrieve returned an error: {text[:2000]}")
    return result.model_dump(by_alias=True, exclude_none=True), elapsed


def graph_search(query: str) -> list[dict]:
    with httpx.Client(headers={"Authorization": f"Bearer {get_token('svc')}"}, timeout=60) as client:
        body = {"requests": [{"entityTypes": ["driveItem"], "query": {"queryString": query}, "size": 25}]}
        resp = client.post(f"{GRAPH}/search/query", json=body)
        resp.raise_for_status()
        containers = resp.json()["value"][0]["hitsContainers"]
        return [h["resource"] for c in containers for h in c.get("hits", [])]


def cmd_probe(token: str, name: str, query: str):
    async def run(session):
        return await retrieve(session, query, [{"name": "OneDriveAndSharePoint"}])

    raw, elapsed = asyncio.run(with_session(token, run))
    out = ROOT / f"workiq_raw_{name}.json"
    text = json.dumps(raw, indent=2, ensure_ascii=False)
    out.write_text(text, encoding="utf-8")
    print(f"\nretrieve: {elapsed:.1f}s, raw result saved to {out.name}")
    stop_on_communication(text, "Work IQ retrieve")

    names = seed_names()
    hits = graph_search(query)
    stop_on_communication(json.dumps(hits), "Graph Search")
    print(f"\nGraph Search control, {len(hits)} hit(s):")
    for h in hits:
        print(f"  {names.get(h.get('name'), '   ')} {h.get('name')}  {h.get('webUrl', '')[:90]}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tools")
    p.add_argument("--user", default="svc")
    p = sub.add_parser("probe")
    p.add_argument("--user", default="svc")
    p.add_argument("--name", required=True, help="suffix for workiq_raw_<name>.json")
    p.add_argument("query")
    args = parser.parse_args()

    token = workiq_token(args.user)
    if args.cmd == "tools":
        asyncio.run(with_session(token, cmd_tools))
    elif args.cmd == "probe":
        cmd_probe(token, args.name, args.query)


if __name__ == "__main__":
    main()
