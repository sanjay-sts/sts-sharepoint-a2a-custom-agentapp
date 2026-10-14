# Next steps (updated 2026-10-14 morning)

Branch `#10_local_test`. Steps 1 to 9 pass and are committed. Step 10's main pass check also passed: a full streamed round trip in the hosted workbench as user A ("What sites can you see?" returned 20 sites with links). Step 10 gate confirmed by the owner on 2026-10-14 after all three error states (AWS credentials, 401, network) were shown in the workbench.

## Start-up checklist for the next session

1. `aws sso login --profile admin` (session expires in hours; `AWS_PROFILE=admin` is in `.env`).
2. Terminal 1: `uv run python -m mcp_server.server`
3. Terminal 2: `uv run python -m agent.a2a_server`
4. Terminal 3: `cd webpart && netstat -ano | findstr :4321` (kill any PID listed), then `npx heft start --nobrowser`
5. Open `https://2tdgcb.sharepoint.com/_layouts/15/workbench.aspx` as stsadmin, add AgentChat.
6. Token caches `.token_cache_a.json` / `.token_cache_b.json` still work silently; delete one to force a fresh device-code sign-in.

## Step 10: remaining forced error states (gate)

| State | How to force it | Expected bar |
|---|---|---|
| 401 | Property pane > API resource = `https://graph.microsoft.com`, send a question, then restore `api://1162088a-3e99-4dad-b52e-d1f2ce5f1c72` | "Sign-in to the agent failed ... (401)" |
| Network | Stop the A2A server, send a question, start it again | "Cannot reach the agent ..." |
| AWS credentials | Already observed for real on 2026-10-13 when the SSO session expired | "The agent's AWS credentials have expired ..." (wording fix committed in 45e639b; re-check once) |

Owner confirms, then commit "Step 10: chat UI gate passed".

## Step 11: package and deploy

```
cd webpart
npx heft build --production
npx heft package-solution --production
```
Report the path `webpart/sharepoint/solution/sp-agent-chat.sppkg`. Owner: upload to the app catalog (`/sites/appcatalog` exists), enable, approve `sp-agent-poc / access_as_user` under SharePoint admin centre > Advanced > API access, add AgentChat to a modern page. Python servers must be running on this machine. Pass: an answer on the real page. Update README if anything differs, commit.

## Step 12: final check

Owner runs the five step-7 questions on the page as stsadmin, then as AdeleV in a separate browser profile (Adele also gets the local-network prompt once). Expected answers are in `docs/step7-results.md`. Report as a table with actual answers; say plainly if any cell fails or if Adele ever sees a site or file she cannot open. Commit "Step 12: final check".

## Housekeeping, owner's call

- Mark 8 Project Team group lost 16 members when Adele was removed; restore if unintended.
- `Directory.Read.All` was added to `sp-agent-poc` for the user survey only; it can be removed. `.token_cache_dir.json` (gitignored) holds the matching cache and can be deleted.
- The AWS deployment design (Lambda + Function URL) in `docs/superpowers/specs/2026-10-13-steps-7-12-design.md` Phase 3 is not needed; localhost works from the workbench.
- Hosted workbench retires 1 Dec 2026; after that use a modern page with the debug query string.

## Prompt to paste into a new session

```
Continue the SharePoint discovery agent PoC on branch #10_local_test.
Read CLAUDE.md, docs/next-steps.md and docs/step7-results.md first.
Steps 1 to 9 pass; step 10's round trip passed. Resume at the two forced
error states in docs/next-steps.md, then steps 11 and 12. Stop at the
step 10 gate until I confirm. Ask me to run the interactive parts (SSO
login, workbench, app catalog).
```
