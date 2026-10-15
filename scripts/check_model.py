"""Step 4 check: send one short prompt to Claude on Bedrock and print the reply.

    uv run scripts/check_model.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.model import credential_problem, make_model  # noqa: E402

try:
    reply = make_model().invoke("Reply with one short sentence confirming you are reachable.")
except Exception as e:
    problem = credential_problem(e)
    sys.exit(problem or f"Model call failed: {type(e).__name__}: {e}")
print(reply.content if isinstance(reply.content, str) else reply.text)
