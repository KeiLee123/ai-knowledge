# Knowledge Brain — Current State

## 2026-11-22 — HKeL Linux ZIP-member fix (Draft, not deployed)

PR118 merged as `2eae0ad`; exact post-merge CI passed. Approved VPS sync and
default no-write CLI passed, but real official-source read was BLOCKED because
the official ZIP uses Windows separators. Read-only diagnosis confirmed the
same source version/manifest/archive and one backslash-named Cap123 member.
The scoped feature fix compares original ZIP names with separator substitution
only and rejects alias ambiguity/NUL/traversal fixtures. No registry/source
SHA, parser, Frozen layer or storage changes; runtime fix not yet verified.
See Issue59 and the bounded contract. Real baseline/Drive/index/legal remain open.

## 2026-11-22 — HKeL Cap123 manual Staging watch (Draft; not deployed)

Issue #59: `hkel_watch_staging_v1.py` adds the missing isolated single-chapter
manual watch entry point, reusing the existing law registry/version helpers,
Cap123 XML parser and M10B immutable-file helpers. Default is no-network,
no-write planning; public-source fetch and confirmed Staging baseline/candidate
modes are separate. No Drive/DB/model/timer or accepted-baseline advancement.
See [bounded contract](hkel_manual_watch_staging_v1.md). This is a Draft proposal,
not Continuous Watch, active HKeL ingestion or operational authorization.

Base staging `afefeda2ca22de0d9351b6565a08ae53d2938abe` includes merged PR #117;
exact merge CI 45014216863 passed. Separately approved VPS code sync and actual
APP145/149 default NO_CHANGE CLI checks passed on 2026-11-22. This supersedes
the older PR #117 Draft/pending snapshot below only for those bounded results.
Real changed-source/Drive/index acceptance and legal currentness remain open.
HKeL source audit found no Staging baseline; Production bootstrap/ingestor
must not be used as a shortcut. The new adapter has not been sent to VPS.

## 2026-11-22 — Gate 1 candidate validation adapter (Draft; not deployed)

Issue #59: `beta_validate_drive_candidate_v1.py` joins a freshly read existing
versioned Drive object to the same M9 candidate's existing M10B-1 parse and
M10B-2A in-memory lexical evidence. Default is a local non-write plan; Drive
read and isolated candidate-workspace write are separate explicit modes.
See [contract and remaining gates](beta_drive_isolated_candidate_validation_v1.md).
PR #117 review reproduced and fixed an early lexical failure being misreported
as a reference mismatch; a regression preserves the BLOCKED cause and stages.
Base staging SHA: `9667c26d229f2df5688dd5d63ee23da95aca2f7c`.
This is an additive engineering proposal, not real changed-source acceptance,
shared-DB ingestion, new deployment or authorization to merge. The older
snapshot below is historical; exact feature head/CI belong to its Draft PR.

Earlier same-day independent acceptance at that base SHA: seven Browser cases
Q01/Q06/Q09/Q14/Q15/Q19/Q19b, one explicitly authorized Staging Feedback saved,
and VPS Linux 41/41 existing synthetic candidate tests passed. These bounded
results do not establish legal semantics, currentness, full USER_BETA or this
new adapter's runtime acceptance; safe detailed evidence is in the owner's
2026-11-22 local handoff reports and the dated canonical Drive Current State
handoff linked above in the repository governance.

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
