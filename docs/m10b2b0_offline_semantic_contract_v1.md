# M10B-2B-0 Offline Semantic Contract v0.1

Status: feature branch / staging PR gate. NO LIVE MODEL CALLS. No VPS deployment or Production changes.

Architecture decision (Google Drive): https://docs.google.com/document/d/1togruRi30usv0TEilCIBYxAwtbaaR5t2prb-6pQj1pE/edit

## Architecture / system boundaries

M10B-2B-0 implements only a **pure offline 384-dimensional vector ranking/evaluation contract**. It extends the M10B-2A native-text chunk/page provenance and synthetic Gold Case contract without modifying any frozen code. It does **not** use a real embedding model, localhost HTTP, DB/pgvector, Google Drive, Docker, external Vision, or a Production pipeline. Model input is a synthetic orthogonal vector fixture, manually specified and independent of the Gold labels.

`m10b2b0_offline_semantic_v1.py` exposes `validate_vector()`, `normalize_corpus()`, `rank_cosine()`, and `evaluate_offline_synthetic()` pure functions. It has no CLI or network adapter. The runner is its test script; real local embedding integration is specifically deferred to M10B-2B-1 after security verification.

## Input/admission

- Only a `document-manifest-v2` native PDF manifest, verified page-scoped chunks, source_id, exact candidate SHA and a validated synthetic Gold Suite are accepted. `verify_chunks()` ties each chunk to the same PDF page's native original text and denies derived/OCR/Vision data.
- A separate prediction dictionary supplies query vectors and explicit `abstain` decisions. **The evaluator must not derive predictions from expected Gold pages or positive/negative labels.** Its result is therefore only a test of ranking/contract mechanics, not trained model behavior.
- Synthetic model contract is pinned to `synthetic-orthogonal-vectors-v1`, revision `fixed-test-fixture-v1`, mode `offline-synthetic`, adapter `offline-fixture-only-v1`, dimension 384. The name `multilingual-e5-small` is prohibited at this stage: claiming a real model from fake vectors would be misleading.
- Reject missing/extra vector keys, wrong model revision/dimensions, nonfinite/zero vectors, nonnumeric/bool inputs, wrong candidate SHA, wrong source/fixture, Gold Case impersonation, altered page/text provenance and out-of-bound pages.
- Normalize valid vectors to unit length. Cosine ranking is deterministic and has a stable page/chunk tie-breaker. Reports show page/chunk IDs, content SHA, cosine, Gold synthetic page ranking and metrics.

## Synthetic evaluation

Use the existing two-page fabricated PDF and synthetic Gold Suite (SYN_GOLD_P1_APPOINTMENT, SYN_GOLD_P2_EVACUATION, SYN_GOLD_NEGATIVE_ABSENT). Add an authored paraphrase query (Who supervises small building jobs?) bound to the synthetic page 1 Gold. Add a hard negative query (authorized signatory jellyfish).

The vector fixture maps known synthetic page 1 and page 2 to orthogonal axes, plus independent query vectors and explicit simulated abstain flags. A hard negative forced to `abstain=false` is a **FAIL**, not evidence that cosine ranking can determine answerability. A correct page requires the expected excerpt and terms to be present in that ranked chunk in addition to a page-ID match.

Metrics are synthetic Hit@1, Hit@3, MRR for positive cases and negative false-positive count. No numerical benchmark is claimed for real world documents. The real Embedding Service is not called; `real_embedding_service_called=false`.

ALL test outputs retain `gold_page_verified=null`, `official_document_verified=false`, `semantic_verified=false`, `answer_verified=false`, `retrieval_verified=false`, `write_authorized=false`, `production_access=false`, `production_write=false`, `shared_db_access=false`, `artifact_written=false`.

## Regression gates

`test_m10b2b0_offline_semantic_v1.py` covers eleven regressions: synthetic positives/negative, paraphrase lexical miss, explicit negative abstention, wrong Gold page/excerpt, wrong page prediction, model/mode/revision mismatch, malformed/zero vectors, corpus/source/SHA tamper, forged official Gold, positive incorrectly abstained, and stable tie-breaking. The success case patches network and subprocess entrypoints to fail if inadvertently called.

Dedicated GitHub Actions on PR to staging must run M10A, M10B-0, M10B-1, M10B-2A lexical, M10B-2A Gold, and M10B-2B-0 regressions. Also require the existing full `Validation` workflow PASS before staging merge. Then run identical regression on VPS Staging pinned commit, without calling localhost model.

## Model/endpoint audit required before M10B-2B-1

Existing code mentions `http://127.0.0.1:8088/embed`, `multilingual-e5-small`, 384 vector dimensions and query/passage prefixes. These are existing **configuration claims only**, not an approved server identity. Verify actual binding address, model revision/digest, tokenizer and length policy, prefix behavior, egress/telemetry, response shape, 384 finite values, redirect/proxy handling and data retention independently on VPS Staging before allowing real PDF text to reach the endpoint.

Do not use `validate_staging_retrieval_v2.py` (shared DB + Docker); do not run existing benchmark orchestration. M10B-2B-1 will need a new separate allowlisted adapter and stricter runtime guard, not changes to Frozen v1.3.

## Official Gold / Production boundary

Synthetic Gold pages are *not* official APP145/APP149 pages. Official Gold requires an independent human/source verification record bound to a specific official file SHA, actual PDF page, excerpt, reviewer and review date. No approval, canonical promotion, M5D accepted-reference advance, release qualification or Production change is inferred from this offline contract.
