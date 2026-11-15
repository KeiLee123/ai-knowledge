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

## Shared Jason OS development memory — 2026-11-02 addendum

This document is a dated GitHub technical navigation snapshot. For a new development task, retrieve the [M1 Master Index](https://docs.google.com/document/d/1QDcl287N5zFqeYEpukN10cd-2qv7lJEdNcT4rJ0lpTI/edit) and [Knowledge Brain Current State](https://docs.google.com/document/d/1ETsFRfbE2HsRG2yb78EKDfRm2VzveyLNkLS-cr1g6Nk/edit) first, follow the [M2 Preflight/Handoff SOP](https://docs.google.com/document/d/1_WZ2rtpQOEsQFAWq1zjgoSxAgf6qyRrbhKlmqJlql5U/edit), and use the [M3 audit](https://docs.google.com/document/d/1Kq28KgAtzR9zcn5iYA8VoznxyrW3PsfDN0LrlSUKqAg/edit) only as dated evidence. Reconcile live PR/CI and bounded VPS evidence separately. The original open-PR count predates this governance Draft [PR #89](https://github.com/KeiLee123/ai-knowledge/pull/89).

For [Document Ingestion PR #88](https://github.com/KeiLee123/ai-knowledge/pull/88), the pinned real VPS read-only audit already covered all 298 PDF pages, 148 structured table chunks and 148 writer-metadata checks with zero mismatches. Pages 151–298 were 148 extractor blank candidates, not independently rendered-blank pages. The separate render script passed synthetic CI on head a1b0f4856edf3c6090ce44fcbbd7d65cefcb1fa2, but the real 148-page raster test and database round-trip remain unverified. This addendum does not authorize Production deployment or modifications to Frozen v1.3.

## 2026-11-04 — Phase B code-only PR #95 audit addendum (GitHub only)

[Draft PR #95](https://github.com/KeiLee123/ai-knowledge/pull/95) targets
`staging` for a database-free Docling/Celery/Redis shadow worker; related
[Issue #94](https://github.com/KeiLee123/ai-knowledge/issues/94).
The code-only review added fail-closed source PDF page-count comparison,
Docling table-cell end-offset verification, and bounded/symlink-safe
fixture-catalog handling with offline regressions. **Exact updated PR
head and CI require checking live GitHub**; do not reuse the historical
FD4CF461 acceptance as evidence for this review commit. Real Docling
model execution, Staging resource benchmark, service deployment,
user Beta and Production are **NOT VERIFIED / NOT AUTHORIZED**.
PostgreSQL `trust` authentication and backup/restore remain separate
release HOLDs. Read the Google Drive Migration Contract and Beta-First
Product Contract for canonical decisions. Frozen Retrieval and M8/M9
are unchanged.

## 2026-11-05 — Phase B Off-VPS CPU Image Gate (GitHub-only, NOT VPS verified)

[Draft PR #95](https://github.com/KeiLee123/ai-knowledge/pull/95)
built a real CPU-only **candidate** Docker image outside the VPS:
[GitHub Actions #41876179138](https://github.com/KeiLee123/ai-knowledge/actions/runs/41876179138)
SUCCESS at commit `9f3aca8f4aa53241f55c94efee01786d917ed7e4`.
Uncompressed local size 1,867,147,090 bytes, nonroot UID 10001,
network-disabled read-only import PASS with 1 CPU / 3 GiB. Python
Docling 2.146.0 + CPU Torch imports pass; no inference. The image
was **not** pushed, retained, privately delivered or deployed. Existing
Validation #41876196709 SUCCESS (25 Phase B offline test methods)
at that same code commit. Prior immutable-source candidate model
inventory: 20 files / 701,224,343 bytes, but **no private binary
delivery/rehash**. Staging runtime, App149 provenance, Product Private
Beta and DB trust-auth/backup restore remain HOLD. Frozen Retrieval,
Production, DB and M8/M9 unchanged. Consult Issue #94 and the Phase B
Model Supply Gate; do not infer any live VPS state.
