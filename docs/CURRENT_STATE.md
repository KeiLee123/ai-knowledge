# Knowledge Brain — Current State

**Snapshot date:** 2026-11-01 (GitHub + existing Google Drive product decisions; **not a live VPS audit**).  
**Owner workstream:** Knowledge Brain backend; consume from 03 — Knowledge & Learning, and expose read-only interfaces to Jarvis Core where warranted.  
**Status:** Existing Production baseline protected; Staging development active; **private usable Beta not yet fully accepted**.

## 1. Exact GitHub baseline at audit

| Ref | SHA | Meaning |
| --- | --- | --- |
| `main` | `2a1aad8e6b740a0b28ea1cb3e07107fb2b8e7c46` | Frozen reviewed baseline; **not** proof of live VPS HEAD |
| `staging` | `0ea64f727f835a210914242a56c6d4cfc4f66778` | Last audited staging tip |
| `main...staging` | 107 commits ahead / 0 behind, 95 changed files | Nontrivial staged delta; **do not bulk merge** |

**IMPORTANT:** If HEAD changes after this snapshot, this table is history, not current truth. Read live GitHub refs and target Issues before coding. The governance-only PR containing this file is *also* not included in the above baseline.

## 2. Active objective and queue

**Delivery goal:** Move existing components toward a useful private, source-grounded Knowledge Brain Beta. Current immediate emphasis is real Document v2 ingestion quality, followed by evidence-grounded answer/Anki quality, then the held question-first interface.

| Priority | Tracking | Current disposition | Exit gate |
| --- | --- | --- | --- |
| P0 | [#87](https://github.com/KeiLee123/ai-knowledge/issues/87), [Draft PR #88](https://github.com/KeiLee123/ai-knowledge/pull/88) | **CONTINUE** as sole active delivery; real table PDF structural audit | CI + isolated Staging read-only real-file evidence, table/page/route/chunk integrity and explicit limitations |
| P1 | [#85](https://github.com/KeiLee123/ai-knowledge/issues/85), [Draft PR #86](https://github.com/KeiLee123/ai-knowledge/pull/86) | **HOLD queued** until P0 evidence triaged; no duplicate offline Gold milestones | Automated checks with honest UNKNOWN semantic accuracy and bounded Staging acceptance; no Anki collection writes |
| P2 | [#83](https://github.com/KeiLee123/ai-knowledge/issues/83), [Draft PR #84](https://github.com/KeiLee123/ai-knowledge/pull/84) | **HOLD**; preserve draft, no merge before genuine Staging/browser acceptance | Question-first approved-source retrieval, correct source currentness/coverage, private loopback security |
| Product | [#58](https://github.com/KeiLee123/ai-knowledge/issues/58), [#59](https://github.com/KeiLee123/ai-knowledge/issues/59), [#60](https://github.com/KeiLee123/ai-knowledge/issues/60) | **OPEN** integrated Beta gates, not extra parallel features | Real source-change→Drive Staging→isolated ingest, HKeL watch, useful query & safe Anki export, feedback loop |

**Safety exception:** Emergency independent security issue can interrupt this order. These are triage **recommendations**, not a change to Issue state or PR merge authorization.

## 3. Existing capabilities / evidence boundaries

- Frozen Production Graph-aware retrieval and answer v1.3: `answer_knowledge.py`, `graph_search_v1.py`, `hybrid_search_v3.py`. Keep regression controls.
- Document v2: `extract_document_v2.py`, `route_document_v2.py`, `build_multimodal_chunks_v2.py`, optional separate OCR/Vision stages and provenance. **APP149 native text acceptance is not table/OCR semantic acceptance.**
- Official monitoring: M8/M9 mechanisms with prior autonomous Staging evidence for approved APP145/APP149; **today's timer/DB health not independently checked**.
- Private UI v0.1 code exists in `staging` with loopback/SSH approach; **not the full accepted end-user Beta**.
- HKeL parser exists; `law_watch.py` continuous Watch Mode is not yet delivered per [#59](https://github.com/KeiLee123/ai-knowledge/issues/59).
- Anki generator / source locator / exporter / review sync exist. Their mere presence proves neither useful cards nor safe personal collection imports.
- Hermes staged experiment includes a blocked persistent path, ephemeral canary plan and explicit security gates; **do not assume Hermes MCP is deployed**.

## 4. Decisions and conflict resolution

- [Approved Beta-First Product Contract](https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit) = top-level product priority; no broad agency expansion before usable Beta.
- [#85](https://github.com/KeiLee123/ai-knowledge/issues/85) (2026-11-01) updates the M11 quality gate to **machine-only evidence checks with AUTO_HOLD / abstention**, instead of obligatory manual Gold/Anki content review. **Do not call automated checks Gold or human verified.** Product-level Beta usefulness remains unproven; do not silently change the overarching acceptance definition. Reconcile any conflicts in the approved Drive contract **before claiming USER_BETA completion**.
- Stage/source constraints remain: GitHub code authority, Drive product/source authority, distinct Staging/Production, review before risky writes, never automatically mutate personal Anki or allow unapproved model egress.

## 5. Next smallest action

Perform a **read-only** reconciliation of PR #88 vs Issue #87 and exact pinned test fixture, identify the outstanding *real Staging table-PDF acceptance* proof; record results in #87 and #88. Once verified, decide whether PR #88 is acceptable or needs a minimal repair. **Do not start a new M12, new parser or broad cleanup.**

**Unknown until independently verified:** actual VPS checkout/dirty state, installed timers, real production/service health, latest Staging datasets, Anki import behavior, model-egress permissions. Never mark deployed solely from GitHub files.

See [governance](DEVELOPMENT_GOVERNANCE.md) and [dated audit](DEVELOPMENT_HEALTH_AUDIT_2026-11-01.md).
