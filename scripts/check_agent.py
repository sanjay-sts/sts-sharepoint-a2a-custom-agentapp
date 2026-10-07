"""Step 5 check: ask the agent a question directly (no A2A) as a user.

MCP server must be running.  uv run scripts/check_agent.py [--user a] "question"
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.graph import stream_answer  # noqa: E402
from agent.model import credential_problem  # noqa: E402
from signin import sign_in  # noqa: E402


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", default="a")
    p.add_argument("question")
    args = p.parse_args()
    token = sign_in(args.user)
    try:
        async for ev in stream_answer(args.question, token):
            if ev["type"] == "tool":
                print(f"\n[tool: {ev['name']}]", flush=True)
            else:
                print(ev["text"], end="", flush=True)
    except Exception as e:
        sys.exit("\n" + (credential_problem(e) or f"Agent failed: {type(e).__name__}: {e}"))
    print()


if __name__ == "__main__":
    asyncio.run(main())
