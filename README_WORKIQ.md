# Work IQ discovery test

> **Preliminary. Run 1, 2026-10-15, as stsadmin, seeds indexed same day.**
> svc-discovery, the intended service account, got no seed documents back from Work IQ on day one.
> Run 2 (same seeds, about 24 hours later, as svc-discovery) is pending. See [Run 2 pending](#run-2-pending).

Question: does Work IQ find SharePoint documents that keyword search plus a Graph walk would miss? And at what cost and latency?

Method: 33 seeded documents whose matching route is known in advance, swept with the Work IQ remote MCP server's `retrieve` tool and compared with Graph controls on the same seeds. The agent, MCP server and web part in this repo were not changed.

## Seeds

`scripts/seed_docs.py` uploads to a `WorkIQSeed/` folder in the Documents library of seven sites and records every file in `seed_manifest.csv`.

| Route | Count | Designed to match only by |
|---|---|---|
| keyword | 9 | "policy" in the filename and body |
| metadata | 9 | DocType column = `Policy`; neutral filename and body |
| semantic | 9 | Meaning: leave, conduct, benefits, onboarding, safety, expenses, travel, remote work. No policy vocabulary anywhere (the script asserts this) |
| distractor | 6 | Nothing: unrelated content |

- **Formats:** docx, pdf, xlsx and txt, rotated across the seeds.
- **Near-duplicate pairs:** K02/K03 (expense policy) and S01/S02 (leave).
- **Superseded chain:** K04 → K05 → K06 (travel policy v1, v2, v3, dated 2024-03-01, 2025-02-01 and 2026-06-01).
- **Communication site seeds:** N01–N03 were meant as the negative control, but svc-discovery can read that site, so in Run 1 they are scored as visible. See the [caveat](#communication-site-caveat).
- **Keyword seeds and meaning:** they also match by meaning, since a travel policy is about travel. The keyword route is a fair test anyway, because the metadata and semantic seeds can't match a "policy" keyword search by their wording.

## Run 1 results (stsadmin, 2026-10-15)

The sweep, `scripts/workiq_sweep.py --user a`, made 16 `retrieve` calls with strategy `grounding`:
- **Pass 1:** one call for each of the 10 topics in `topics.txt`, scoped to `OneDriveAndSharePoint`.
- **Pass 2:** one call for each of the six readable sites, scoped with `items_by_url` and a combined HR-topics query.

Graph controls ran as stsadmin. The inventory is svc-discovery's walk, which covers every seed with DocType.

### Recall by route

| Method | Keyword (9) | Metadata (9) | Semantic (9) | Distractors hit (6) |
|---|---|---|---|---|
| **Work IQ retrieve, both passes** | 7 (78%) | **1 (11%)** | 3 (33%) | 0 |
| Work IQ retrieve, topic pass only | 7 (78%) | 0 | 2 (22%) | 0 |
| Graph Search `policy` | 7 (78%) | 8 (89%) | 0 | 0 |
| Graph Search, the 10 topic words | 7 (78%) | 8 (89%) | 5 (56%) | 0 |
| Name filter `polic` | 9 (100%) | 0 | 0 | 0 |
| Graph walk: name or DocType | 9 (100%) | 9 (100%) | 0 | 0 |

### Does Work IQ add recall over keyword search plus the walk?

Almost none in Run 1.

| | Seeds (of 27 relevant) |
|---|---|
| Found by keyword search + topic search + walk | 23 |
| Found by Work IQ retrieve | 11 |
| **Found only by Work IQ** | **1: S07** (working from home, pdf) |
| Found by the baseline, missed by Work IQ | 13: K02, K07, M01, M02, M04–M08, N02, N03, S01, S06 |
| Missed by everything | 3: S03 (conduct, pdf), S05 (onboarding, txt), S08 (expenses, txt) |

### Other measures

| Measure | Run 1 |
|---|---|
| Precision, all hit rows | 19 / 21 (90%). The two misses are SharePoint pages ("Home", "Building our COVID response") |
| Precision, rank 3 or better | 14 / 16 (88%). Rank cutoff, because hits carry no score |
| Distinct files cited | 13, of which 11 are seeds |
| Calls with zero hits | 7 / 16 (handbook, leave, conduct, onboarding, and the site passes for Mark 8, ragnestedgrouptest and Test site 1) |
| Latency per call | median 17.6 s, min 7.8 s, max 24.0 s, 256 s for 16 calls |
| Travel chain K04–K06 | Always returned together; no signal for which version is current |
| Near-duplicate pairs | Only one copy of each came back: K03 not K02, S02 not S01 |
| Communication site hits | 1 (N01, "policy" topic). Expected as stsadmin |
| **Cost (credits)** | |
| **Cost per document found only by Work IQ** | |

## Durable findings

These are unlikely to change with indexing lag. Run 2 will confirm them.

1. **Metadata route: 1 of 9.** Work IQ retrieve does not match custom columns: 0 of 9 in the topic pass, 1 in the site pass (M03). SharePoint search does: `policy` matches the DocType value for 8 of 9. A DocType column is exactly how an HR team would tag policies, so for curation this is the decisive gap.
2. **Format bias: 0 of 6 `.txt`.**

   | Format | Relevant seeds | Work IQ | Graph Search |
   |---|---|---|---|
   | docx | 9 | 5 | 8 |
   | pdf | 8 | 4 | 6 |
   | xlsx | 4 | 2 | 3 |
   | txt | 6 | **0** | 3 |

   Enterprise content is mostly docx and pdf, so this matters less in practice, but it explains several misses (K07, S05, S08).
3. **No `relevanceScore` or `sensitivityLabel` in retrieve hits.** Every hit has exactly `id, resourceId, webUrl, entityUrl, entityType, driveId, itemId, contentProtection, resourceMetadata.document.title`. This is a docs-versus-behaviour gap. Over A2A, a single sensitivity-label part comes back for the whole answer, not per document.
4. **Latency: median 17.6 s per call.** A 200-topic enterprise sweep is about an hour. That's fine for batch work and unusable for anything interactive.
5. **High precision, low recall.** Work IQ is a good confirmer and a poor enumerator. The backend reports 15–42 underlying results for a query (see `SearchMetadata` in the grounding markdown) and returns 0–7 of them.

## svc-discovery diagnosis

| Check | Result |
|---|---|
| HTTP | 200 or 202 on every request. No 403, no policy or billing error body |
| Token | Same audience (Work IQ app `fdcc1f02-…`) and the same four delegated scopes as stsadmin |
| MCP `retrieve` | Empty result (`retrievalHits: []`, `stoppedReason: completed`) for every query, scoped or not |
| A2A `SendMessage` | **Answers.** It cites two older SharePoint pages on mytesthrsite ("How we work", "Meet the team", modified 2025) but no seed documents. The answer text is duplicated |
| Graph Search as svc-discovery | Finds the seeds, for example S06, so the files are indexed and permission trimming works |
| Licences | Same `DEVELOPERPACK_E5` as stsadmin; neither account has a Copilot licence |
| Differences from stsadmin | Created **2026-10-15 19:00 UTC**, hours before the probes; usage location CA (stsadmin US); stsadmin also has a Copilot Studio trial (`CCIBOTS_PRIVPREV_VIRAL`) |

**Reading:** this is an empty 200, not a 403, a policy block or an auth failure. svc-discovery reaches older content but not documents added today, while stsadmin gets today's documents. That is consistent with per-user index lag for a new account; Run 2 tests it. If Run 2 is still empty, the next suspects are the usage location and the Copilot Studio trial licence.

## Communication site caveat

Communication site is the tenant root (`https://2tdgcb.sharepoint.com/`). It was meant as the negative control, but svc-discovery can read it: in Graph, a direct read of each N seed and its content returned 200 on 2026-10-15. The usual cause on a root site is "Everyone except external users" in the Visitors group.

- **Run 1:** N01 was a legitimate hit as stsadmin, who can open every site.
- **No negative control yet:** until that grant is removed and Graph Search as svc-discovery stops returning N01–N03, there is no real negative control, and a Communication site hit as svc-discovery proves nothing.
- **Re-check:** run `seed_docs.py --status` and expect `found no` on N01–N03 for svc-discovery. Then the isolation test can run.

## A2A record call

`scripts/workiq_ask.py --raw "List the HR policy documents you can find"`, A2A 1.0 `SendMessage`, HTTP 200, `TASK_STATE_COMPLETED`.

| User | Time | Cited | Considered, not cited |
|---|---|---|---|
| stsadmin | 26.6 s | K06, K05, K04, K03, K01 and an IT FAQ page | 24 (competitor reports and AWS PDFs; no seeds) |
| svc-discovery | 14.2 s | 2 mytesthrsite pages | 0 |

Response shape: `result.task.artifacts[].parts` contains:
- **The answer:** a text part in markdown with `[n](url#refid)` citations.
- **An `application/vnd.ms-workiq-reference` part:** `refid → {targetLink, isCitedInResponse}`.
- **An `application/vnd.ms-workiq.sensitivity-label` part:** one label for the whole answer.

## Run 2 pending

Plan: same seeds and `topics.txt`, no code change, about 24 hours after Run 1.

1. One probe as svc-discovery:
   `uv run scripts/workiq_mcp.py probe --user svc --name r2_p2 "What footwear do staff have to wear in the warehouse?"`
2. If it returns S06, run the full sweep as svc-discovery and score it:
   ```
   uv run scripts/workiq_sweep.py --user svc --rerun run2-svc
   uv run scripts/score_workiq.py --run run2-svc --user svc
   ```
3. Optionally, rerun as stsadmin (`--user a --rerun run2-a`) to separate indexing lag (recall rises for both) from run-to-run variance. S06 was found in a probe and missed in the sweep the same day.

| Measure | Run 1 (stsadmin) | Run 2 (svc-discovery) |
|---|---|---|
| Keyword recall | 7/9 | |
| Metadata recall | 1/9 | |
| Semantic recall | 3/9 | |
| Found only by Work IQ | S07 | |
| Precision (all / rank ≤ 3) | 90% / 88% | |
| Median latency | 17.6 s | |
| Credits | | |

## How to run

All outputs are git-ignored: `seed_manifest.csv`, `inventory.csv`, `workiq_*.csv` and `workiq_raw*.json`.

```
uv run scripts/seed_docs.py --check            # app-only token roles, resolve sites
uv run scripts/seed_docs.py                    # create DocType column, upload, write manifest
uv run scripts/seed_docs.py --status           # per-seed search visibility as svc-discovery
uv run scripts/list_sites.py --user svc        # Graph walk with DocType -> inventory.csv
uv run scripts/workiq_mcp.py tools --user svc  # Work IQ MCP tools and the retrieve schema
uv run scripts/workiq_sweep.py --user a        # sweep, run1
uv run scripts/score_workiq.py                 # recall, precision, latency for run1
uv run scripts/workiq_ask.py --user a --raw "question"   # A2A fallback
uv run scripts/seed_docs.py --delete           # remove WorkIQSeed from every site
```

Sign-in uses device code (MSAL) for every user. The Work IQ CLI is not used, because it fails with a WAM error on this machine. Token caches are `.token_cache_*.json`, all git-ignored.

## Permissions added for this test

| App | Permission | Type | Why | Remove after |
|---|---|---|---|---|
| `sp-agent-poc` | `Sites.ReadWrite.All` | Application | Upload the seeds and set DocType | Yes |
| `sp-agent-poc` | `Sites.Manage.All` | Application | Create the DocType column | Yes |

Only `scripts/seed_docs.py` uses these app-only grants. The agent, MCP server and web part only use delegated tokens.
