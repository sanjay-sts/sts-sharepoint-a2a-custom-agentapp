# Handoff: SharePoint discovery agent (web part + A2A + MCP proof)

You are picking up a small proof of concept partway through. Read this whole file before changing anything.

## What we are proving

A React web part on a SharePoint page sends a question over the A2A protocol to a LangGraph agent. The agent calls a custom MCP server, and the MCP server lists SharePoint files through Microsoft Graph **as the signed-in user**. Two users with different SharePoint access ask the same question and get different, correct answers.

That chain, with per-user results, is the whole point. The owner is an experienced AI architect who wants to see it work before investing in anything larger. The tools only list and describe files; nothing reads file content. Prefer the smallest thing that demonstrates the chain over anything more general.

```
SharePoint page (browser)
  SPFx React web part ──A2A + user token──> A2A agent (LangGraph) ──MCP + user token──> MCP server (FastMCP)
        │                                          │                                        │
   Entra ID: token for                      Claude on Bedrock                    Entra ID: on-behalf-of exchange
   the signed-in user                 (AWS profile or Bedrock API key)                      │
                                                                                  Microsoft Graph (as that user)
```

Everything except SharePoint, Entra and Bedrock runs on the owner's Windows machine on localhost. Both test users use that machine, in separate browser profiles.

## Current state

| Item | State |
|---|---|
| Repo | `sts-sharepoint-a2a-custom-agentapp`, created with `uv init`, Python >= 3.12, Windows |
| Dependencies so far | `dotenv` (a wrapper that installs `python-dotenv`); `msal` and `httpx` may or may not be added yet |
| `.env` | Exists with `TENANT_ID` and `CLIENT_ID` |
| Entra app | `sp-agent-poc`, single tenant, public client flows enabled, delegated Graph scopes `Sites.Read.All` and `Files.Read.All` with admin consent. No client secret and no exposed API yet |
| Tenant | Microsoft 365 Developer E5 sandbox, three SharePoint sites, under 30 documents in total |
| `scripts/list_sites.py` | Written, may not have been run. Signs in by device code, caches the token in `.token_cache.json`, walks every site and library, writes `inventory.csv` |

Start by inspecting the repo and confirming each row. If `scripts/list_sites.py` is missing, ask the owner for it instead of rewriting it from this description.

## Stack

| Layer | Choice | Version guidance |
|---|---|---|
| Web part | SharePoint Framework (SPFx), React, TypeScript | Latest SPFx; Node version from the SPFx compatibility matrix |
| A2A in the browser | Official A2A JavaScript SDK if it runs in a browser; otherwise a small fetch-based client | Latest stable |
| Agent | LangGraph | Latest stable |
| MCP tools in the agent | `langchain-mcp-adapters` | Latest stable |
| Model client | `langchain-aws` (Bedrock Converse) | Latest stable |
| A2A server and Python client | `a2a-sdk` | Latest stable |
| MCP server | FastMCP 4 | See the note below |
| Microsoft tokens | `msal` | Latest stable |

**FastMCP 4 note.** When this file was written, PyPI listed FastMCP 4 as an alpha (`4.0.0a2`). Check PyPI first. If a stable 4.x exists, use it. If 4 is still pre-release, tell the owner and let him choose between the pre-release and the latest stable 3.x before you install either; a pre-release needs `uv add --prerelease allow`.

## Decisions already made

These were chosen deliberately to keep the proof small. Do not change them without asking.

| Decision | Reason |
|---|---|
| Two users, each identified by their own Entra token on every hop | Per-user results are what is being proven |
| The MCP server exchanges the user's token for a Graph token (on-behalf-of) | Graph then applies that user's SharePoint permissions; no permission logic in our code |
| One Entra app registration for the web part's API, the agent and the MCP server | The agent can forward the user's token unchanged. Production would split these |
| Listing tools only, read-only | No file content, no vector index, consent stays at two delegated read scopes |
| Backend on localhost | Both users test from the owner's machine, so no cloud hosting is needed |
| LangGraph for the agent | Owner's choice. If it blocks you, stop and ask before switching framework |
| Claude on Amazon Bedrock, called directly | No gateway in this proof |
| AWS credentials come from the environment, never from code | See the AWS section |

## What the owner does in Microsoft portals

You cannot do these. Give him the exact values he needs at the step where each is required, and wait.

| When | Portal task | Check |
|---|---|---|
| Before step 2 | On `sp-agent-poc`: **Expose an API**, accept the Application ID URI `api://<client-id>`, add scope `access_as_user` (admins and users can consent) | Scope listed |
| Before step 2 | On `sp-agent-poc`: create a client secret; put it in `.env` as `CLIENT_SECRET` | Secret not in the repo |
| Before step 7 | Under **Expose an API**, add the app's own client ID as an authorized client application for `access_as_user`, so the test script can get a token | Listed as authorized |
| Before step 7 | Create a second user (user B) with an E5 licence. Make user A a member of all three sites and user B a member of only some, so their results must differ | B gets access denied on at least one site in the browser |
| Before step 9 | Under **Expose an API**, add **SharePoint Online Client Extensibility Web Application Principal** as an authorized client application for `access_as_user` (he looks up its client ID under Enterprise applications) | Listed as authorized |
| Before step 11 | Create the tenant app catalog if the tenant has none | App catalog site opens |
| During step 11 | Upload the package you build to the app catalog, approve the pending request under **API access** in the SharePoint admin centre, and add the web part to a page | Web part appears on the page |

## AWS credentials for the model

The owner will supply short-lived AWS access in one of two ways. The code must work with either without modification, which it will if the Bedrock client is created with boto3's default credential resolution and nothing is passed explicitly.

| Option | What the owner sets | Notes |
|---|---|---|
| AWS profile (temporary credentials, usually SSO) | `AWS_PROFILE` and `AWS_REGION` | He refreshes with `aws sso login --profile <name>` when they expire |
| Bedrock API key | `AWS_BEARER_TOKEN_BEDROCK` and `AWS_REGION` | Recent boto3 picks this up on its own; confirm the installed version supports it |

- Read `AWS_REGION` and `BEDROCK_MODEL_ID` from `.env`. Ask the owner for the model or inference profile ID; do not guess one.
- When a model call fails with an expired or missing credential error, say so plainly and tell the owner which refresh to run. Do not retry in a loop or try another credential source.

## Secrets and tokens

This proof now handles a client secret and other people's access tokens. Treat them carefully.

- `CLIENT_SECRET`, AWS keys and any bearer token must never appear in code, logs, commits, error messages or your replies. Do not read `~/.aws` files.
- Log who called (the token's `preferred_username` or `oid` claim) and which tool ran, never the token.
- Keep Graph tokens from the on-behalf-of exchange in memory only, keyed per user. Never let one user's Graph token serve another user's request; this is the one bug that would invalidate the proof.

## Verify APIs before you write against them

All of these libraries change quickly, and nothing in this file about their APIs has been checked against current documentation. Before writing code that depends on them, look up the current docs (a Context7 MCP server is available on this machine) for:

- FastMCP 4: defining tools, serving over Streamable HTTP, and reading the incoming request's `Authorization` header inside a tool
- `langchain-mcp-adapters`: loading tools from a remote Streamable HTTP MCP server with per-request headers
- LangGraph: the current recommended way to build a tool-calling agent (the prebuilt constructor has been renamed and moved between releases), and passing per-request values through config
- `langchain-aws`: the Bedrock Converse chat model and how it resolves credentials
- `a2a-sdk` (Python): server components (agent card, request handler, agent executor, task store), how the executor reads request headers, streaming, and the client. The SDK had breaking changes around its 1.0 release, so ignore tutorials written for 0.2 or 0.3
- A2A JavaScript SDK: whether its client runs in a browser with a custom `Authorization` header and streaming
- `msal` Python: `acquire_token_on_behalf_of` on a confidential client
- SPFx: current generator and build toolchain, `webApiPermissionRequests`, and `AadTokenProvider`

The open-source LangGraph library has no built-in A2A server, so write a thin agent executor that runs the graph and maps its output to A2A events, and let `a2a-sdk` handle everything else. Do not hand-roll the protocol on the server.

## Work to do

Do these in order. Each step has a pass check; run it and show the owner the result before moving on. Steps 1, 7 and 10 are gates.

### Backend

**1. Confirm Graph listing (gate).** Add `msal` and `httpx` if missing, then have the owner run `uv run scripts/list_sites.py` and sign in as user A with the device code it prints.

Pass: his three sites are listed (extra system sites are fine), per-library file counts match SharePoint, and `inventory.csv` has one row per file. If a site is missing, fall back to a `SITE_URLS` list in `.env` resolved with `GET /sites/{hostname}:/{path}`.

**2. Shared auth and Graph module.** One importable module that holds all Microsoft token handling:

- Validate an incoming bearer token: signature against the tenant's signing keys, issuer, audience (`api://<client-id>` or the client ID), expiry, and the `access_as_user` scope.
- Exchange a validated user token for a Graph token with on-behalf-of, cached in memory per user.
- A paged GET helper that follows `@odata.nextLink`, and a file walker that yields every file under a drive with its folder path. Both take the Graph token as an argument.
- The device-code flow stays in `scripts/` only.

Pass: a short script signs in by device code for the scope `api://<client-id>/access_as_user`, runs the token through validate and exchange, and lists sites with the resulting Graph token.

**3. MCP server.** FastMCP, Streamable HTTP on `127.0.0.1:8001`. Every tool call requires a bearer token, validates it, exchanges it and calls Graph as that user. No token or a bad token returns 401.

| Tool | Input | Returns |
|---|---|---|
| `list_sites` | none | Site id, name and URL for each site the user can see |
| `list_libraries` | site id | Library (drive) id and name |
| `list_files` | drive id, optional folder path | Files with name, folder, type, size, modified, modified by, URL |
| `search_files` | optional name text, file type, modified-after date, site id | Matching files in the same shape |
| `get_file_metadata` | drive id, item id | Full metadata for one file |
| `inventory_summary` | optional site id | File count and total size grouped by site, library and file type |

- `inventory_summary` must do the counting in Python and return the totals. Models miscount long listings.
- `search_files` filters the walked listing by name, type, date and site; with under 30 documents that is fast and exact. No content search.
- Every file result includes its SharePoint URL so the agent can cite it.
- Write tool descriptions for a model to read: what each tool is for and when to prefer it.
- Log each tool call with the caller's identity and arguments.

Pass: with user A's token, each tool returns correct results from MCP Inspector or a short client script; with no token the server returns 401.

**4. Model check.** Add `langchain-aws`, write `scripts/check_model.py` that sends one short prompt and prints the reply, and run it with the owner's credentials in place.

Pass: a one-line reply prints.

**5. Agent.** A LangGraph tool-calling agent whose only tools are the MCP server's, using the Bedrock model. The user's bearer token arrives per request and must be sent as the `Authorization` header on that request's MCP calls. Build the MCP connection per request, or otherwise guarantee that concurrent requests from two users cannot share a token.

The system prompt should say that the agent answers questions about what files exist in the user's SharePoint sites, that every factual claim must come from a tool result, that counts come from `inventory_summary`, that it cites file URLs, and that it says plainly when nothing was found instead of guessing.

Pass: a short script calling the graph with user A's token answers "what files are in <site>" correctly, and the MCP log shows user A as the caller.

**6. A2A server.** Expose the agent with `a2a-sdk` on `127.0.0.1:8002`:

- Agent card describing the discovery skill, declaring streaming and bearer authentication. The card itself is readable without a token.
- Validate the bearer token on every message request (401 otherwise) and hand it to the graph.
- CORS for `https://<tenant>.sharepoint.com` only, allowing the `Authorization` and `Content-Type` headers and the methods A2A uses. Ask the owner for the tenant host name.

Pass: the agent card loads in a browser; a message request with no token returns 401.

**7. Two-user test from a script (gate).** `scripts/ask.py --user a "question"` signs in by device code for `api://<client-id>/access_as_user` (one token cache file per user label, both git-ignored), calls the A2A server with the `a2a-sdk` client and prints the streamed answer.

| # | Question | As user A | As user B |
|---|---|---|---|
| 1 | What sites can you see? | All three sites | Only the sites B is a member of |
| 2 | How many files are in each site, by type? | Matches `inventory.csv` | Counts only for B's sites |
| 3 | List the PDFs in <site> modified in the last 30 days | Same as filtering `inventory.csv` | Same if B has the site; otherwise nothing found |
| 4 | Find <a real file name in a site B cannot open> and say who last modified it | Correct file, author and date | Not found |
| 5 | Is there a file called <a made-up name>? | Says nothing was found | Says nothing was found |

Pass: every cell matches, and the MCP log shows the right caller on each request. The backend is complete at this point. If user B ever sees a file or site name B cannot open, stop and report it; do not continue to the web part.

### Web part

**8. Scaffold.** Create an SPFx React web part in `webpart/` with the current generator. Check the SPFx compatibility matrix for the Node version before installing, and tell the owner if his installed Node does not fit.

Pass: the empty web part renders in the hosted workbench (`https://<tenant>.sharepoint.com/_layouts/15/workbench.aspx`).

**9. Token and A2A client.** Add a `webApiPermissionRequests` entry for resource `sp-agent-poc`, scope `access_as_user`. In the web part, get the user's token with `AadTokenProvider` and call the A2A server with it, with streaming. The backend URL is a web part property defaulting to `http://127.0.0.1:8002`.

Pass: in the hosted workbench, the browser's network tab shows a 200 from the A2A server with a bearer header.

A browser may ask for permission before letting a SharePoint page call an address on the local machine, or block it. If the call is blocked, show the owner the console error and ask him before adding a dev tunnel or HTTPS on localhost.

**10. Chat UI (gate).** A minimal chat: message list, input box, streamed answer text, file links that open in a new tab, and a visible error state for 401, network failure and expired AWS credentials on the backend. Use Fluent UI components that ship with SPFx. No history, settings or styling work beyond readable.

Pass: a full question and answer round trip in the hosted workbench as user A.

**11. Package and deploy.** Build the production package and give the owner the `.sppkg` path. He uploads it, approves the API access request and adds the web part to a page.

Pass: the web part answers a question on the real page.

**12. Final check.** The owner runs the five questions from step 7 on the page as user A, then as user B in a separate browser profile.

Pass: results match step 7 for both users. Report the outcome as a table with the actual answers, and say plainly if any cell failed.

## Repo conventions

- Suggested layout: `sp_graph/` (auth and Graph module), `mcp_server/`, `agent/`, `scripts/`, `webpart/`. Adjust if a tool expects otherwise.
- Python: `uv add` and `uv run`. Web part: the package manager the SPFx generator sets up.
- `.gitignore` must cover `.env`, every token cache file, `inventory.csv`, `.venv/`, `__pycache__/`, `node_modules/` and SPFx build output. Check the token caches and `.env` are ignored before the first commit.
- Commit after each passing step with a short message.
- Finish with a README: versions installed, the commands to start the MCP server and the A2A server, how to build the web part, and how to refresh each credential.

## Out of scope

Stop and ask if a change seems to need any of these; do not build them on your own initiative:

- Reading file content, a vector index, or embeddings
- Cloud deployment, Docker, or CI
- Writing to SharePoint
- Separate app registrations per service, or app-only (no user) Graph access
- A model gateway, or any AWS credential handling beyond boto3's default resolution
- Conversation history across page loads
- Retry and throttling frameworks, configuration systems, or abstractions for cases that do not exist yet
