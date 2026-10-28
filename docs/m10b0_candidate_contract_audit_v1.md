# M10B-0 — Isolated Candidate Contract & Side-effect Audit v0.1

Status: Contract audit v0.1; GitHub staging review tracked in PR #45. This is **an audit**, not M10B candidate processing code or permission to write anywhere.

Design Source of Truth: https://docs.google.com/document/d/1aZBVFRR0IperUB18xMNkrLWxTZUCEJU9jh9OG07XXFg/edit

## Baseline
- Target: `KeiLee123/ai-knowledge` staging at `eb9dfbc5c13f5d29ad8312b4a61a5fc73ae9dfc5`.
- M10A VPS Staging live: offline fixture PASS; M9 20261028T011529Z APP149/APP145 NO_CHANGE. No actual new candidate has yet been live-verified.
- Existing Frozen M8/M9 and Knowledge Brain Graph-aware Retrieval v1.3 are not modified in this audit.

## 1. Interface / side-effect inventory

| Component | Audit finding | M10B-1 reuse decision |
|---|---|---|
| `m10_candidate_intake_v1.inspect_batch()` | Reads M9 artifacts, verifies SHA and Source/Reference (validation-time), emits no writes | ALLOW as input gate; independently recheck before processing |
| `extract_document_v2.build_manifest()` | Local PDF/text extraction, structured `document-manifest-v2` | ALLOW for isolated workspace; verify source bytes before and after |
| `route_document_v2.assess_manifest(..., allow_partial=False)` | Local deterministic route decision | ALLOW; reject partial manifests even if a fallback route is returned |
| `version_signal_extractor_v1.build_version_signal_snapshot()` / `compare_version_snapshots()` | Local metadata/content/identity fingerprint comparison | ALLOW only with nonblank Source Registry identity pre-gate and reference SHA lock |
| `version_qualification_policy_v1.evaluate_version_candidate()` | Candidate policy; does not authorize release | ALLOW read-only; never manually set staging_validation_verified to true |
| `build_multimodal_chunks_v2` | Local chunk conversion; not equivalent to OCR/vision completion | CONDITIONAL; provenance/coverage tests required |
| `orchestrate_document_v2.py --prepare` | Creates workspace; checks `read_existing_document()` in DB; calls `ingest_manifest_v2.py --check-db --prepare-write` | **DENY as directly reusable offline M10B worker** |
| `run_multimodal_canary_v2.py` | `--prepare` wrapper still calls above orchestrator, validates live Docker Staging DB | **DENY as fully isolated M10B worker** |
| `augment_vision_v2.py` | Reads DeepSeek credentials and submits page image+prompt to external `/chat/completions` | **DENY by default**; external data egress requires separate explicit approval and data-handling review |
| `augment_ocr_v2.py` | Local Tesseract subprocess, OS availability/language dependencies | CONDITIONAL: audit subprocess flags and file outputs before enabling |
| `ingest_canonical_text_staging_v1.py` | Requires `Current/`; SQL INSERT to shared documents/chunks/embeddings | **DENY for candidate isolation** |
| `ingest_manifest_v2.py` | DB check/write entrypoints; default DB is Production-named container | **DENY as candidate worker**; do not import/execute unguarded |
| `validate_staging_retrieval_v2.py` | Retrieves from existing Staging DB; talks to embedding endpoint; not candidate-only | **DENY for M10B isolated retrieval until explicitly separated** |
| `version_snapshot_store_v1.py` | Mutators exist for accepted references | Read-only current reference lookup only; never execute initialize/advance/update during M10B |

## 2. Critical gaps / mitigations

**G1 — Frozen identity comparator accepts absent identity**: `compare_version_snapshots()` compares `None == None` as true. Two snapshots missing `canonical_host` could appear matched. M10B Admission Gate must require nonempty/valid `authority_code`, `document_code`, `canonical_host` and match them against trusted Source Registry BEFORE using comparator/policy. Do not change frozen policy; add separate fail-closed adapter.

**G2 — Reference time-of-observation lock missing**: M9 output does not contain accepted reference *record* SHA at observation time. M10B can hash before/after validation and re-evaluate M5B candidate policy, but cannot claim M9 historical reference cryptographic linkage. If changed: REVIEW_REQUIRED; never overwrite M5D snapshot.

**G3 — Prepare is not sandboxed**: The standard multimodal wrapper carries DB reads, live Docker checks, local workdir writes and optionally externally hosted Vision. M10B-1 must call local pure parser/router functions individually; no `orchestrate_document_v2.py`, `run_multimodal_canary_v2.py`, or `ingest_manifest_v2.py` until separate isolated contract proof.

**G4 — External Vision data egress**: `augment_vision_v2.py` sends page imagery/prompt to a configured model API. No implicit candidate processing may invoke this. M10B-1 defaults to no external network; unsupported multimodal route => REVIEW_REQUIRED / RETRIEVAL_NOT_VERIFIED, not false success.

**G5 — Retrieval isolation**: The shared staging schema is not a candidate version namespace. M10B does not use existing Staging retrieval to claim a candidate-only hit. M10B-2 must define candidate in-memory search or separate disposable index before accepting retrieval canary.

**G6 — Text fingerprint caveat**: `version_signal_extractor_v1.manifest_text()` reads `unit.text`; OCR or derived Vision evidence may not affect its normalization. A multimodal candidate needs separate OCR/visual provenance and completeness checks, or REVIEW_REQUIRED. Never claim normalized text fingerprint covers every visual change.

**G7 — Full-document route guard**: The router can label a partial document's suggested fallback as `legacy-v1` even though `production_decision_valid=false`; M10B must check validity first. Validation must not silently downgrade multimodal to text-only.

**G8 — No real candidate live proof**: The recent actual M9 batches are NO_CHANGE. Use a clearly labeled synthetic/local test candidate before claiming the candidate path was live verified.

## 3. Hard boundaries and tests

`test_m10b0_candidate_contract_v1.py` exercises genuine M10A read-only fixture intake, NO_CHANGE does not create a workspace, policy rejects identity/date regression and cannot authorize release, highlights null-identity comparator gap, route rejects partial document, and checks the risk-bearing code paths are still identified. This is **contract drift detection**, not a guarantee of end-to-end non-write behavior. The audit test makes **no network/DB/Docker calls**.

Existing M8/M9, main, Production, M5D and v1.3 remain untouched. No update to existing GitHub workflow `validation.yml`; add a separate staging-target CI job.

## 4. M10B-1 prerequisites (blocking acceptance)

1. Trusted registry identity gate with nonempty identity, source enabled, exact allowlisted canonical host; no candidate-supplied endpoints/DB/Drive paths.
2. Byte/hash-locked and symlink-resistant candidate input, reference record before/after SHA, explicit read/write workspace boundaries.
3. Pure local parse & route, no subprocess to unapproved pipeline, no DB/Drive/API traffic; route validity verified before any status PASS.
4. New output states: PARSE_VERIFIED versus RETRIEVAL_NOT_VERIFIED versus STAGING_VERIFIED, with explicit cannot-authorize flags.
5. Fail closed on OCR/Vision required but not performed, no provenance, model mismatch or reference drift.
6. New regressions and CI on staging; live VPS synthetic canary with evidence; separate M10B-2 retrieval proof later.

## 5. Acceptance

- CI must pass `test_m10b0_candidate_contract_v1.py` and existing full staging Validation workflow.
- This audit alone **does not** establish M10B-1 implementation readiness for automatic candidate validation: G1-G7 remain blocking design gates.
- Merge only to GitHub `staging` after checks; VPS staging execution and production deployment are separate actions.
