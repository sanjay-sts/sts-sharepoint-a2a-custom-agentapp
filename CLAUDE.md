# CLAUDE.md

Proof of concept: a SharePoint discovery agent. A SharePoint web part asks questions, an A2A server runs a LangGraph agent on Claude (Bedrock), the agent calls a FastMCP server with read-only SharePoint tools, and every Graph call runs as the signed-in user via on-behalf-of. The full build spec is `mvp_prd_codeinstruction.md`; read it before changing scope.

## Layout

- `sp_graph/` shared auth and Graph module (token validation, per-user OBO cache)
- `mcp_server/` FastMCP 4 server, `127.0.0.1:8001`, endpoint `/mcp`
- `agent/` Bedrock model, LangGraph agent, A2A server on `127.0.0.1:8002`
- `scripts/` device-code sign-in, per-step check scripts, `ask.py` A2A client
- `webpart/` SPFx React web part (Heft toolchain)
- `docs/superpowers/specs/` design records

## Commands

```
uv sync
uv run python -m mcp_server.server
uv run python -m agent.a2a_server
uv run scripts/ask.py --user a "What sites can you see?"
uv run scripts/check_model.py          # Bedrock reachable
uv run scripts/list_sites.py           # regenerate inventory.csv (device code, user A)
```

Python goes through `uv add` and `uv run`. The web part uses npm and Heft (`npx heft start --nobrowser`, `npx heft build --production`, `npx heft package-solution --production`), not gulp.

Web part development notes:
- Before `heft start`, check nothing else holds port 4321 (`netstat -ano | findstr :4321`); an orphan serves a stale bundle and the workbench shows "Something went wrong".
- The dev server reads manifests at startup only; restart it after editing `*.manifest.json`. Property defaults are also hard-coded in `AgentChatWebPart.ts` as a fallback.
- Heft colours its log; grep for `compiled` and `Encountered`, not `compiled successfully`.
- SPFx downlevels classes: never rely on `instanceof` for `Error` subclasses in the web part; use `isChatError`.
- Status so far is recorded in `docs/step7-results.md` and `docs/next-steps.md`.

## Fixed decisions, do not revisit

- FastMCP 4.0.11 with `langchain.mcp.MCPAdapter`. `langchain-mcp-adapters` is incompatible with mcp 2.x.
- The agent sees every site user A can see, not a fixed list.
- User A is `stsadmin@2tdgcb.onmicrosoft.com`; tenant host `2tdgcb.sharepoint.com`.
- Bedrock model `us.anthropic.claude-sonnet-4-5-20250929-v1:0` in `us-east-1`, default AWS credential chain (SSO profile or `AWS_BEARER_TOKEN_BEDROCK`). Never pass credentials in code.
- `.env` keys: `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, `AWS_REGION`, `BEDROCK_MODEL_ID`, `SHAREPOINT_ORIGIN`, optional `AWS_PROFILE`, `MCP_URL`. Template in `.env.example`.
- The A2A server speaks a2a-sdk 1.2 JSON-RPC: method `SendStreamingMessage`, proto-JSON params (`role: ROLE_USER`, `parts: [{text}]`), `A2A-Version: 1.0` header required. SSE `data:` lines carry `result.task | statusUpdate | artifactUpdate`. Verified with curl on 2026-10-13.
- Localhost from the hosted workbench works; Chrome/Edge show a one-time local-network Allow prompt. No dev tunnel or AWS hosting needed.
- User B for tests is `AdeleV@2tdgcb.onmicrosoft.com` (member of Test site 1 only among private sites). Public group sites are visible to every tenant user regardless of membership.

## Gates

Steps 1, 7 and 10 of the spec are gates. Show the pass check and stop until the owner confirms. If user B ever sees a site or file B cannot open, stop and report it; do not continue.

## Secrets

- Never print, log, commit or paste `CLIENT_SECRET`, AWS keys, bearer tokens, `.env`, token caches or `~/.aws` contents. Do not read `~/.aws`.
- Log the caller (`preferred_username` or `oid`) and the tool name, never the token.
- Graph tokens from the OBO exchange stay in memory, keyed per user. One user's token must never serve another user's request.

## Working rules

- Commit after each passing step with a short message.
- Library APIs change fast (a2a-sdk, FastMCP, LangGraph, SPFx). Check current docs or the installed source before writing against them.
- Owner does all Entra and SharePoint portal tasks; give exact values and wait.
- User B signs in from a private window or separate browser profile, otherwise A's session is reused.
