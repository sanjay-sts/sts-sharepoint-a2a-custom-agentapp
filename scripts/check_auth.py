"""Step 2 check: user token -> validate -> on-behalf-of -> list sites as that user.

    uv run scripts/check_auth.py [label]     (label defaults to "a")
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sp_graph  # noqa: E402
from signin import sign_in  # noqa: E402


async def main(label: str):
    token = sign_in(label)

    claims = sp_graph.validate_token(token)
    print(f"Validated: user={claims.get('preferred_username') or claims.get('upn')} "
          f"oid={claims['oid']} aud={claims['aud']} ver={claims.get('ver')} scp={claims['scp']}")

    graph_token = sp_graph.graph_token_for(token, claims)
    again = sp_graph.graph_token_for(token, claims)
    print(f"On-behalf-of exchange OK (second call served from per-user cache: {again is graph_token})")

    sites = [s async for s in sp_graph.get_paged(graph_token, "sites?search=*")]
    print(f"\n{len(sites)} site(s) visible to this user:")
    for s in sorted(sites, key=lambda s: (s.get("displayName") or "").lower()):
        print(f"  {s.get('displayName')}  {s.get('webUrl')}")

    try:
        sp_graph.validate_token(token[:-4] + "AAAA")
        print("\nFAIL: tampered token was accepted")
    except sp_graph.AuthError as e:
        print(f"\nTampered token rejected: {e}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "a"))
