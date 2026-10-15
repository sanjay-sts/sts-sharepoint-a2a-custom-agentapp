# Step 12 results: final check on the real page (2026-10-14)

Page: home page of Test site 1 (`https://2tdgcb.sharepoint.com/sites/Testsite1`), AgentChat web part from the deployed package `sp-agent-chat.sppkg` (built from commit 394c9dc). Backend on the owner's machine: MCP server 127.0.0.1:8001, A2A server 127.0.0.1:8002, Bedrock via AWS SSO profile.

User A: stsadmin@2tdgcb.onmicrosoft.com in a normal browser profile. User B: AdeleV@2tdgcb.onmicrosoft.com in a separate browser profile. Inventory regenerated the same morning: 68 files across 9 sites with content (the package upload added 12 files to the Apps site).

| # | Question | Expected A | Actual A | Pass | Expected B | Actual B | Pass |
|---|---|---|---|---|---|---|---|
| 1 | What sites can you see? | 20 sites | 20 sites, all listed with links | yes | 12 sites, none of sts it services, Contoso Team, testing team, Mark 8 | 12 sites, exactly those | yes |
| 2 | How many files are in each site, by type? | 68 files; per-site, per-type counts as in inventory.csv | 68 files across 9 sites; every site/type cell matches | yes | Test site 1: 10 (8 pdf, 1 docx, 1 xlsx); Apps allowed | Apps 12 (6 js, 2 json, 2 png, 1 sppkg, 1 txt), Test site 1 10 (8 pdf, 1 docx, 1 xlsx); total 22 | yes |
| 3 | List the PDFs in Test site 1 modified in the last 30 days | 1: sharpeointragoptions.pdf | 1: sharpeointragoptions.pdf, 2026-10-13, Adele Vance, 1.5 MB | yes | same | same | yes |
| 4 | Find 2023-Annual-Report-1.pdf and say who last modified it and when | Found; Maya Amar; 2024-02-08 23:43 UTC | Found; Maya Amar; February 8, 2024 23:43 UTC | yes | Not found | Not found after three searches | yes |
| 5 | Is there a file called quarterly-unicorn-budget-2031.xlsx? | Nothing found | "No, there is no file called ..." | yes | Nothing found | "No, there is no file called ..." | yes |

Callers: the A2A log shows five requests as stsadmin followed by five as AdeleV; the MCP log shows every tool call for each run under the same account. No cell failed. User B never saw a site or file she cannot open; the Apps site (tenant app catalog) is readable by all tenant users by design.

Results match step 7 (`docs/step7-results.md`) apart from the Apps site files, which did not exist at step 7.

## Issues found and fixed along the way

- Model assumed a 2025 date (step 7): today's date is now injected into the system prompt per request.
- `list_sites` trusted the search index, which lags permission changes: each site is now confirmed with a direct read.
- Web part `instanceof` on an Error subclass failed after downlevel: replaced with a duck-typed check.
- Web part properties were undefined on instances created before the manifest change: in-code defaults added.
- Orphaned SPFx dev server on port 4321 served a stale bundle ("Something went wrong"); documented in README.
- "Mismatched anonymous define()" on the published page when a tab still held debug-manifest state from the workbench; cleared by stopping the dev server and opening a fresh tab.

## Known limitations

- Markdown tables in answers render flattened with "·" separators; readable, not pretty.
- The hosted workbench retires 1 Dec 2026; development after that uses a page with the debug query string.
- The backend runs on the owner's machine. Public hosting (Lambda + Function URL design in the spec) was not needed and was not built.
