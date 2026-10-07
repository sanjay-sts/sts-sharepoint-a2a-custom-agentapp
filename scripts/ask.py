"""Ask the A2A agent a question as a test user and print the streamed answer.

MCP server and A2A server must be running.
    uv run scripts/ask.py --user a "What sites can you see?"
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

sys.path.insert(0, str(Path(__file__).resolve().parent))
from signin import sign_in  # noqa: E402

A2A_URL = "http://127.0.0.1:8002"


def _text(parts) -> str:
    return "".join(p.text for p in parts if p.HasField("text"))


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", default="a", help="user label; selects .token_cache_<label>.json")
    p.add_argument("question")
    args = p.parse_args()
    token = sign_in(args.user)

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=300) as http:
        client = await create_client(A2A_URL, client_config=ClientConfig(streaming=True, httpx_client=http))
        request = SendMessageRequest(message=new_text_message(args.question, role=Role.ROLE_USER))
        failed = False
        async for ev in client.send_message(request):
            if ev.HasField("artifact_update"):
                print(_text(ev.artifact_update.artifact.parts), end="", flush=True)
            elif ev.HasField("status_update"):
                st = ev.status_update.status
                msg = _text(st.message.parts) if st.HasField("message") else ""
                if st.state == TaskState.TASK_STATE_FAILED:
                    failed = True
                    print(f"\n[failed] {msg}", file=sys.stderr)
                elif msg.startswith("Calling "):
                    print(f"\n[{msg.rstrip('.')}]", file=sys.stderr, flush=True)
            elif ev.HasField("message"):
                print(_text(ev.message.parts), end="", flush=True)
        await client.close()
    print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
