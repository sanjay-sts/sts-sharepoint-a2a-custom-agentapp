"""Ask Work IQ a question over A2A (fallback to the MCP retrieve sweep).

POSTs an A2A 1.0 JSON-RPC SendMessage to the Work IQ endpoint with the
caller's delegated token (scope WorkIQAgent.Ask, device code per user label).
--raw prints the HTTP status and response body as received and saves it to
workiq_raw_a2a_<user>.json. Otherwise prints the answer text, the cited and
considered references, the sensitivity label, elapsed seconds and the contextId.

Response shape (verified 2026-10-15): result.task.artifacts[].parts holds
  {"text": answer markdown with [n](url#refid) citations}
  {"mediaType": "application/vnd.ms-workiq-reference",
   "data": {refid: {"targetLink": url, "isCitedInResponse": bool}}}
  {"mediaType": "application/vnd.ms-workiq.sensitivity-label", "data": {...}}

    uv run scripts/workiq_ask.py --user a --raw "List the HR policy documents you can find"
    uv run scripts/workiq_ask.py --user a --context <id> "Which of those was modified most recently?"
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workiq_auth import workiq_token  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
A2A_URL = "https://workiq.svc.cloud.microsoft/a2a/"
REFERENCE_TYPE = "application/vnd.ms-workiq-reference"
LABEL_TYPE = "application/vnd.ms-workiq.sensitivity-label"


def parse_task(task: dict) -> dict:
    """Answer text, references (cited first) and sensitivity label from a task."""
    answer, refs, label = [], [], None
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if isinstance(part.get("text"), str):
                answer.append(part["text"])
            elif part.get("mediaType") == REFERENCE_TYPE:
                refs += [{"id": k, "url": v.get("targetLink", ""), "cited": bool(v.get("isCitedInResponse"))}
                         for k, v in (part.get("data") or {}).items()]
            elif part.get("mediaType") == LABEL_TYPE:
                label = part.get("data")
    refs.sort(key=lambda r: not r["cited"])
    return {"answer": "\n".join(answer), "references": refs, "label": label,
            "state": (task.get("status") or {}).get("state"), "contextId": task.get("contextId")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="a")
    parser.add_argument("--context", help="contextId from a previous answer")
    parser.add_argument("--raw", action="store_true", help="print and save the raw response")
    parser.add_argument("question")
    args = parser.parse_args()

    message = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": args.question}]}
    if args.context:
        message["contextId"] = args.context
    body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "SendMessage", "params": {"message": message}}
    headers = {"Authorization": f"Bearer {workiq_token(args.user)}", "A2A-Version": "1.0",
               "Content-Type": "application/json", "Accept": "application/json"}

    start = time.perf_counter()
    resp = httpx.post(A2A_URL, json=body, headers=headers, timeout=300)
    elapsed = time.perf_counter() - start

    if args.raw:
        print(f"HTTP {resp.status_code}  {resp.headers.get('content-type', '')}  {elapsed:.1f}s")
        try:
            data = resp.json()
            text = json.dumps(data, indent=2, ensure_ascii=False)
        except ValueError:
            text = resp.text
        (ROOT / f"workiq_raw_a2a_{args.user}.json").write_text(text, encoding="utf-8")
        print(text[:20000])
        return

    if resp.status_code != 200:
        sys.exit(f"HTTP {resp.status_code}: {resp.text[:2000]}")
    data = resp.json()
    if "error" in data:
        sys.exit(f"A2A error: {json.dumps(data['error'])[:2000]}")
    task = (data.get("result") or {}).get("task")
    if not task:
        sys.exit(f"No task in the response: {json.dumps(data)[:2000]}")
    parsed = parse_task(task)
    print(parsed["answer"] or "(no answer text)")
    cited = [r for r in parsed["references"] if r["cited"]]
    print(f"\n{len(cited)} cited, {len(parsed['references']) - len(cited)} considered but not cited:")
    for r in parsed["references"]:
        print(f"  {'cited' if r['cited'] else '     '}  {r['url']}")
    label = parsed["label"] or {}
    print(f"\nsensitivity label: {label.get('displayName') or '(none)'}")
    print(f"{elapsed:.1f}s, state {parsed['state']}, contextId {parsed['contextId']}")


if __name__ == "__main__":
    main()
