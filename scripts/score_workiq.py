"""Score the Work IQ sweep against the seeded documents and the Graph controls.

For each row of seed_manifest.csv:
  found_workiq        cited in any retrieve call (either pass)
  found_workiq_topic  cited in pass 1 (topic questions, no site scope)
  found_keyword       Graph Search for "policy"
  found_topic_search  Graph Search for any of the ten topic words (union)
  found_name          inventory.csv file name contains "polic"
  found_walk          name filter OR DocType = Policy in inventory.csv
Writes workiq_scores_<run>.csv and prints recall by route, precision by rank,
latency, and what Work IQ adds over keyword search plus the walk.

Retrieve hits carry no relevance score, so precision is measured by rank
(hits come back ordered): all hits, and hits at rank 3 or better.

    uv run scripts/score_workiq.py                       # run1, Graph controls as user A
    uv run scripts/score_workiq.py --run run2-svc --user svc
"""

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from list_sites import get_token  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.microsoft.com/v1.0"
ROUTES = ["keyword", "metadata", "semantic", "distractor"]
RANK_CUTOFF = 3
SCORE_FIELDS = ["seed_id", "route", "site", "filename", "format", "doctype", "found_workiq",
                "found_workiq_topic", "found_keyword", "found_topic_search", "found_name", "found_walk"]


def read(name: str) -> list[dict]:
    return list(csv.DictReader((ROOT / name).open(encoding="utf-8")))


def search_ids(client: httpx.Client, query: str) -> set[tuple[str, str]]:
    """(driveId, itemId) of every driveItem Graph Search returns for a query."""
    found, start = set(), 0
    while True:
        body = {"requests": [{"entityTypes": ["driveItem"], "query": {"queryString": query},
                              "from": start, "size": 50}]}
        resp = client.post(f"{GRAPH}/search/query", json=body)
        resp.raise_for_status()
        containers = resp.json()["value"][0]["hitsContainers"]
        page = [h["resource"] for c in containers for h in c.get("hits", [])]
        found |= {((r.get("parentReference") or {}).get("driveId", ""), r.get("id", "")) for r in page}
        if not page or not any(c.get("moreResultsAvailable") for c in containers):
            return found
        start += len(page)


def yn(flag: bool) -> str:
    return "yes" if flag else "no"


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=None, help="Graph token label for the controls (default user A)")
    parser.add_argument("--run", default="run1", help="sweep run id to score")
    args = parser.parse_args()

    seeds = read("seed_manifest.csv")
    inventory = {(r["drive_id"], r["item_id"]): r for r in read("inventory.csv")}
    candidates = read(f"workiq_candidates_{args.run}.csv")
    calls = read(f"workiq_calls_{args.run}.csv")
    topics = [line.split("\t", 1)[0] for line in (ROOT / "topics.txt").read_text(encoding="utf-8").splitlines()
              if line.strip()]

    cited = {(c["driveId"], c["itemId"]) for c in candidates}
    cited_topic = {(c["driveId"], c["itemId"]) for c in candidates if c["pass"] == "1"}

    with httpx.Client(headers={"Authorization": f"Bearer {get_token(args.user)}"}, timeout=60) as client:
        keyword = search_ids(client, "policy")
        topic_search = set().union(*(search_ids(client, t) for t in topics))

    rows = []
    for s in seeds:
        key = (s["drive_id"], s["item_id"])
        inv = inventory.get(key, {})
        name_hit = "polic" in inv.get("name", "").lower()
        rows.append({
            **{f: s[f] for f in ["seed_id", "route", "site", "filename", "format", "doctype"]},
            "found_workiq": yn(key in cited), "found_workiq_topic": yn(key in cited_topic),
            "found_keyword": yn(key in keyword), "found_topic_search": yn(key in topic_search),
            "found_name": yn(name_hit), "found_walk": yn(name_hit or inv.get("doctype") == "Policy"),
        })
    with (ROOT / f"workiq_scores_{args.run}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    methods = [("Work IQ (both passes)", "found_workiq"), ("Work IQ (topic pass only)", "found_workiq_topic"),
               ("Graph Search 'policy'", "found_keyword"), ("Graph Search, 10 topic words", "found_topic_search"),
               ("Name filter 'polic'", "found_name"), ("Walk: name or DocType", "found_walk")]
    by_route = defaultdict(list)
    for r in rows:
        by_route[r["route"]].append(r)

    print(f"Run {args.run}: {calls[0].get('user', '?')} for Work IQ, Graph controls as {args.user or 'user A'}\n")
    print("Recall by route (distractor column = false positives)\n")
    print(f"{'Method':30}" + "".join(f"{r:>16}" for r in ROUTES))
    for label, col in methods:
        cells = [pct(sum(x[col] == "yes" for x in by_route[r]), len(by_route[r])) for r in ROUTES]
        print(f"{label:30}" + "".join(f"{c:>16}" for c in cells))

    # What Work IQ adds over keyword search plus the walk.
    relevant = [r for r in rows if r["route"] != "distractor"]
    baseline = {r["seed_id"] for r in relevant
                if "yes" in (r["found_keyword"], r["found_topic_search"], r["found_walk"])}
    workiq = {r["seed_id"] for r in relevant if r["found_workiq"] == "yes"}
    print(f"\nRelevant seeds: {len(relevant)}")
    print(f"Keyword search + topic search + walk: {len(baseline)}")
    print(f"Work IQ: {len(workiq)}")
    print(f"Work IQ only (adds recall): {sorted(workiq - baseline) or 'none'}")
    print(f"Baseline only (Work IQ missed): {sorted(baseline - workiq)}")
    print(f"Missed by everything: {sorted({r['seed_id'] for r in relevant} - baseline - workiq) or 'none'}")

    # Precision by rank over every hit row.
    seed_route = {(s["drive_id"], s["item_id"]): s["route"] for s in seeds}
    def precision(rows_):
        good = sum(seed_route.get((c["driveId"], c["itemId"]), "") in ("keyword", "metadata", "semantic")
                   for c in rows_)
        return pct(good, len(rows_))
    top = [c for c in candidates if int(c["rank"]) <= RANK_CUTOFF]
    print(f"\nPrecision (relevant seed hits / all hit rows; non-seed pages count as not relevant)")
    print(f"  all ranks: {precision(candidates)}   rank <= {RANK_CUTOFF}: {precision(top)}")
    distinct = {(c["driveId"], c["itemId"]) for c in candidates}
    print(f"  distinct files cited: {len(distinct)}, of which seeds: {len(distinct & set(seed_route))}")

    comm = [c for c in candidates if c["comm_site"] == "yes"]
    print(f"\nCommunication site hit rows: {len(comm)} {sorted({c['seed_id'] or c['title'] for c in comm})}")

    secs = [float(c["seconds"]) for c in calls]
    print(f"\nLatency over {len(secs)} calls: median {statistics.median(secs):.1f}s, "
          f"min {min(secs):.1f}s, max {max(secs):.1f}s, total {sum(secs):.0f}s")
    print(f"Calls with zero hits: {sum(c['hits'] == '0' for c in calls)}/{len(calls)}")


if __name__ == "__main__":
    main()
