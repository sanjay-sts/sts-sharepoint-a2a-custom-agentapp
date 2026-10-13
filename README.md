# sts-sharepoint-a2a-custom-agentapp

Proof of concept: a SharePoint web part that asks a discovery agent about the user's own sites and files. The web part gets an Entra token, calls an A2A server, which runs a LangGraph agent on Claude (Bedrock). The agent's tools live on a FastMCP server that calls Microsoft Graph as the signed-in user (on-behalf-of), so each user only sees what they can open.

Build spec and step list: `mvp_prd_codeinstruction.md`. Design record for the remaining steps: `docs/superpowers/specs/2026-10-13-steps-7-12-design.md`.

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node 22 (for the SPFx web part)
- AWS CLI with SSO access to Bedrock in `us-east-1`
- An Entra app registration (`sp-agent-poc`) exposing `api://<client-id>/access_as_user`

## Versions

| Component | Version |
|---|---|
| Python | 3.12 |
| fastmcp | 4.0.11 |
| mcp | 2.3.0 |
| langchain | 1.4.3 |
| langchain-aws | 1.8.1 |
| langgraph | 1.2.14 |
| a2a-sdk | 1.2.2 |
| msal | 1.39.0 |
| httpx | 0.28.1 |
| Bedrock model | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Node | 22.17 |
| SPFx | see `webpart/package.json` once scaffolded |

## Configuration

Copy `.env.example` to `.env` in the repo root and fill in the values. `.env` is gitignored; every module loads it from the project root.

```
cp .env.example .env
uv sync
uv run main.py   # prints "Config: OK" once the required Entra values are set
```

Keys: `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, `AWS_REGION`, `BEDROCK_MODEL_ID`, `SHAREPOINT_ORIGIN`; optional `AWS_PROFILE`, `AWS_BEARER_TOKEN_BEDROCK`, `MCP_URL`.

## Running

Two servers, each in its own terminal:

```
uv run python -m mcp_server.server      # MCP server on 127.0.0.1:8001/mcp
uv run python -m agent.a2a_server       # A2A server on 127.0.0.1:8002
```

Ask a question as a test user (device-code sign-in on first run, cached per label):

```
uv run scripts/ask.py --user a "What sites can you see?"
uv run scripts/ask.py --user b "What sites can you see?"
```

Sign user B in from a private window or a separate browser profile, otherwise the browser reuses user A's session.

## Check scripts

| Script | Checks | Needs |
|---|---|---|
| `uv run scripts/list_sites.py` | Graph listing; writes `inventory.csv` | device-code sign-in |
| `uv run scripts/check_auth.py [label]` | token validation and on-behalf-of exchange | `.env` |
| `uv run scripts/check_mcp.py [label]` | every MCP tool, and 401 without a token | MCP server running |
| `uv run scripts/check_model.py` | one Bedrock prompt | AWS credentials |
| `uv run scripts/check_agent.py [--user a] "question"` | the agent without A2A | MCP server running |

## Web part

Scaffolded at step 8 into `webpart/` with the SPFx Yeoman generator on the Heft toolchain. Build commands are filled in once the package exists:

```
cd webpart
npm install
heft start                              # hosted workbench
heft build --production
heft package-solution --production      # produces sharepoint/solution/*.sppkg
```

## Refreshing credentials

| Credential | When it expires | Refresh |
|---|---|---|
| AWS SSO session (Bedrock) | hours | `aws sso login` (add `--profile <name>` and set `AWS_PROFILE` in `.env` if not the default profile), then restart the A2A server |
| Bedrock API key (alternative) | per key policy | create a new key, update `AWS_BEARER_TOKEN_BEDROCK`, restart the A2A server |
| Test-user tokens | about an hour, refreshed silently | delete `.token_cache_<label>.json` to force a new device-code sign-in |
| Client secret | per portal setting | create a new secret on `sp-agent-poc`, update `CLIENT_SECRET` in `.env`, restart both servers |

When the agent fails with a message starting `ERROR_AWS_CREDENTIALS:`, the AWS session has expired; run the SSO login and retry.
