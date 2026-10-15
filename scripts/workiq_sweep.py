"""Discovery sweep over the Work IQ remote MCP server's retrieve tool.

Pass 1: one retrieve call per topic in topics.txt, scoped to
OneDriveAndSharePoint. Pass 2: one call per readable site, scoped with
items_by_url, using a combined HR-topics query. Strategy "grounding" throughout.

Writes, all git-ignored, with the run id in each name (default run1):
  workiq_calls_<run>.csv       one row per call: pass, scope, query, seconds, counts
  workiq_candidates_<run>.csv  one row per hit per call, joined to inventory.csv and
                               seed_manifest.csv on driveId + itemId
  workiq_raw_sweep_<run>_NN.json  {"elapsed": seconds, "result": raw tool result} per call

Communication site hits are flagged in comm_site, not stopped on (recall test;
the isolation test comes later). An HTTP error or isError result stops the run.
Each call gets its own MCP session and one retry on a connection failure; CSVs
are rewritten after every call. --resume reuses calls already saved.
--rerun <id> repeats the same topics.txt plan under a new run id, so runs
compare call for call.

    uv run scripts/workiq_sweep.py --user a                    # run1
    uv run scripts/workiq_sweep.py --user svc --rerun run2-svc
    uv run scripts/workiq_sweep.py --user a --rerun run2 --resume
"""

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workiq_mcp as w  # noqa: E402
from seed_docs import SITE_PATHS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULT_KEY = "application/vnd.ms-workiq.retrieval"
SITE_QUERY = ("HR and company policy documents about leave, conduct, benefits, onboarding, "
              "safety, expenses, travel and remote work")
TENANT = "https://2tdgcb.sharepoint.com"

CALL_FIELDS = ["run_id", "user", "call", "pass", "topic", "scope", "query", "seconds", "result_count", "hits",
               "stopped_reason", "search_terms", "total_results"]
CANDIDATE_FIELDS = ["run_id", "user", "call", "pass", "topic", "scope", "query", "rank", "driveId", "itemId", "webUrl",
                    "title", "relevanceScore", "sensitivityLabel", "file_type", "seed_id", "route",
                    "site", "in_inventory", "comm_site"]


def load_topics() -> list[tuple[str, str]]:
    lines = (ROOT / "topics.txt").read_text(encoding="utf-8").splitlines()
    return [tuple(line.split("\t", 1)) for line in lines if line.strip()]


def plan_calls() -> list[dict]:
    calls = [{"pass": 1, "topic": topic, "scope": "OneDriveAndSharePoint", "query": q,
              "capabilities": [{"name": "OneDriveAndSharePoint"}]} for topic, q in load_topics()]
    for site, path in SITE_PATHS.items():
        if site == "Communication site":
            continue
        calls.append({"pass": 2, "topic": "all", "scope": site, "query": SITE_QUERY,
                      "capabilities": [{"name": "OneDriveAndSharePoint",
                                        "items_by_url": [{"url": TENANT + path}]}]})
    return calls


def search_metadata(markdown: str) -> dict:
    """The grounding markdown ends with a '## SearchMetadata' JSON line."""
    if "## SearchMetadata" not in markdown:
        return {}
    tail = markdown.split("## SearchMetadata", 1)[1].strip()
    try:
        return json.loads(tail.splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return {}


def keyed(path: str, key_fields=("drive_id", "item_id")) -> dict:
    rows = csv.DictReader((ROOT / path).open(encoding="utf-8"))
    return {(r[key_fields[0]], r[key_fields[1]]): r for r in rows}


def unwrap(e: BaseException) -> str:
    """Innermost messages of an exception group, for a readable failure line."""
    subs = getattr(e, "exceptions", None)
    if subs:
        return "; ".join(unwrap(x) for x in subs)
    return f"{type(e).__name__}: {e}"


async def call_once(token: str, c: dict) -> tuple[dict, float]:
    async def one(session):
        return await w.retrieve(session, c["query"], c["capabilities"])
    for attempt in (1, 2):
        try:
            return await w.with_session(token, one)
        except SystemExit:
            raise
        except BaseException as e:  # noqa: BLE001 - transport errors arrive as exception groups
            print(f"   connection failure (attempt {attempt}): {unwrap(e)[:500]}", flush=True)
            if attempt == 2:
                raise SystemExit("STOP: call failed twice")
    raise AssertionError


def write_csvs(run_id: str, call_rows: list[dict], cand_rows: list[dict]):
    for name, fields, rows in [(f"workiq_calls_{run_id}.csv", CALL_FIELDS, call_rows),
                               (f"workiq_candidates_{run_id}.csv", CANDIDATE_FIELDS, cand_rows)]:
        with (ROOT / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="a")
    parser.add_argument("--resume", action="store_true", help="reuse calls already saved")
    parser.add_argument("--rerun", metavar="RUN_ID", default="run1",
                        help="run id appended to every output file (default run1)")
    args = parser.parse_args()

    seeds = keyed("seed_manifest.csv")
    inventory = keyed("inventory.csv")
    comm_drives = w.communication_drive_ids()
    calls = plan_calls()
    token = w.workiq_token(args.user)

    async def run():
        call_rows, cand_rows = [], []
        for n, c in enumerate(calls, start=1):
            raw_path = ROOT / f"workiq_raw_sweep_{args.rerun}_{n:02d}.json"
            saved = json.loads(raw_path.read_text(encoding="utf-8")) if args.resume and raw_path.exists() else {}
            if "elapsed" in saved:
                raw, elapsed = saved["result"], saved["elapsed"]
            else:
                raw, elapsed = await call_once(token, c)
                raw_path.write_text(json.dumps({"elapsed": round(elapsed, 1), "result": raw},
                                               indent=2, ensure_ascii=False), encoding="utf-8")
            r = raw.get("structuredContent", {}).get(RESULT_KEY, {})
            hits = r.get("retrievalHits", [])
            meta = search_metadata(r.get("markdown", ""))
            base = {"run_id": args.rerun, "user": args.user, "call": n, "pass": c["pass"], "topic": c["topic"], "scope": c["scope"], "query": c["query"]}
            call_rows.append({**base, "seconds": f"{elapsed:.1f}", "result_count": r.get("resultCount", ""),
                              "hits": len(hits), "stopped_reason": r.get("stoppedReason", ""),
                              "search_terms": " ".join(meta.get("searchTerms", [])),
                              "total_results": meta.get("totalResults", "")})
            comm = 0
            for rank, h in enumerate(hits, start=1):
                key = (h.get("driveId", ""), h.get("itemId", ""))
                seed, inv = seeds.get(key, {}), inventory.get(key, {})
                is_comm = key[0] in comm_drives or bool(w.ROOT_SITE_URL.match(h.get("webUrl", "")))
                comm += is_comm
                cand_rows.append({
                    **base, "rank": rank, "driveId": key[0], "itemId": key[1], "webUrl": h.get("webUrl", ""),
                    "title": ((h.get("resourceMetadata") or {}).get("document") or {}).get("title", ""),
                    "relevanceScore": h.get("relevanceScore", ""), "sensitivityLabel": h.get("sensitivityLabel", ""),
                    "file_type": inv.get("type", ""), "seed_id": seed.get("seed_id", ""),
                    "route": seed.get("route", ""), "site": inv.get("site", seed.get("site", "")),
                    "in_inventory": "yes" if inv else "no", "comm_site": "yes" if is_comm else "",
                })
            seeds_hit = [row["seed_id"] or "-" for row in cand_rows if row["call"] == n]
            print(f"{n:2d} p{c['pass']} {c['topic'][:11]:11} {c['scope'][:21]:21} {elapsed:5.1f}s "
                  f"hits {len(hits):2d}  {' '.join(seeds_hit)}{'  [Communication site hit]' if comm else ''}"
                  f"{'  (saved)' if 'elapsed' in saved else ''}", flush=True)
            write_csvs(args.rerun, call_rows, cand_rows)
        return call_rows, cand_rows

    call_rows, cand_rows = asyncio.run(run())
    print(f"\n{len(call_rows)} call(s) -> workiq_calls_{args.rerun}.csv, "
          f"{len(cand_rows)} hit row(s) -> workiq_candidates_{args.rerun}.csv")


if __name__ == "__main__":
    main()
