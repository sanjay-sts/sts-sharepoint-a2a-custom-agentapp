# Step 7 results: two-user test (2026-10-13)

User A: stsadmin@2tdgcb.onmicrosoft.com (global admin). User B: AdeleV@2tdgcb.onmicrosoft.com (licensed, no admin roles; member of Test site 1 and Mark 8 Project Team; not a member of sts it services, Contoso Team, testing team).

Inventory at test time: 56 files across 8 sites with content. The only PDF modified in the last 30 days is `sharpeointragoptions.pdf` in Test site 1, uploaded by Adele Vance on 2026-10-13.

| # | Question | User A | User B | Pass |
|---|---|---|---|---|
| 1 | What sites can you see? | 20 sites (all of inventory; the 403 content-storage site excluded) | 13 sites; none of sts it services, Contoso Team, testing team | yes |
| 2 | How many files are in each site, by type? | 55 (run before the upload) / all cells match inventory | Mark 8: 6 (3 docx, 1 gif, 2 pptx); Test site 1: 10 (1 docx, 8 pdf, 1 xlsx). Only B's sites | yes |
| 3 | List the PDFs in Test site 1 modified in the last 30 days | 1: sharpeointragoptions.pdf, 2026-10-13, Adele Vance | same | yes |
| 4 | Find 2023-Annual-Report-1.pdf (sts it services) and say who last modified it | Found; Maya Amar, 2024-02-08 23:43 UTC, link to stsitservices | Not found after three searches | yes |
| 5 | Is there a file called quarterly-unicorn-budget-2031.xlsx? | Nothing found | Nothing found | yes |

MCP log callers: every A request logged `caller=stsadmin@...`, every B request `caller=AdeleV@...`. B never saw a site or file B cannot open.

## Defect found and fixed during the gate

The model assumed a 2025 date, so question 3 for A first returned four PDFs. Fix: `agent/graph.py` now puts today's UTC date in the system prompt per request (commit 43adf3a). Rerun returned the single correct file.

## Observation, not a failure

Give @ Contoso, Live @ Contoso and Work @ Contoso open for Adele in the browser but do not appear in B's site list. `list_sites` uses Graph `sites?search=*`, which omits sites where access comes only from a tenant-wide "Everyone" claim rather than membership. B therefore sees fewer sites than the browser, never more. Those three sites hold four files in total.
