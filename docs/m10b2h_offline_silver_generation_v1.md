# M10B-2H — Offline Silver Candidate Generator + Risk Review Queue v0.1

**Status:** GitHub staging-only engineering candidate; no live model or official Gold deployment.

## Architecture (MVP first)

The existing M10B-2F verifier safely checks source PDF bytes and candidate quote/page/context, while M10B-2G established this works on a pinned, real APP149 Drive copy. However manually authoring each Silver question will not scale. M10B-2H adds a separate **deterministic rule-based passage-cloze generator**, then reuses the M10B-2F verifier and converts its result to a redacted review queue with reproducible quality sampling. It intentionally avoids a live LLM because Oracle VPS security review is paused.

Pipeline: caller-supplied **in-memory PDF bytes** + pinned SHA256/source/version → M10B-2F native-text page extraction → context window / unique quote / deterministic *literal completion* candidate → M10B-2F independent code-path exact page/context/SHA verification → review queue: required human review, evidence remediation, or sampled machine-checked item → redacted report.

**Important limitation:** generator and verifier use the *same source PDF*. Their quote match is a mechanical self-grounding check, not independent evaluation of semantic truth or model answer quality. Automatically generated passage-cloze queries are intentionally simple literal retrieval prompts, NOT representative natural-language questions. This stage never claims verified real semantic retrieval, human approval, or official source authentication.

## Reusable APIs

- `build_generated_silver_suite(pdf_bytes, *, source_id, document_version, suite_id, expected_sha256, max_cases=15, max_per_page=2)` returns an **EPHEMERAL in-memory suite** with raw source excerpts for M10B-2F. It must never be logged, exported to Drive Current, placed into GitHub, or auto-approved as Gold.
- `run_offline_silver_generation(pdf_bytes, *, ..., sample_percent=10, sample_seed="audit-v1")` builds, verifies and **returns only a redacted report**: source IDs/SHA, case counts, verifier checksums, case IDs and risk-review routes. No raw excerpts, PDF text, queries or vectors.

Identity is supplied by caller and **SHA256 is recomputed from the actual bytes before extraction**; it is a local byte consistency gate, not proof the PDF was genuinely published by an authority. Only `safe_id`-validated ASCII identities and bounded 3 MB, 30-page, 50-case input supported. Default max 15 cases, 2 per page; no OCR on scanned/image-only pages, and insufficient unique native text causes a safe rejection.

## Generator contract

For each page, split native extracted text into whitespace-normalized words, then pick up to two non-overlapping deterministic eight-word snippets with six immediately adjacent words of context on either side. Skip duplicates across pages and unsafe/missing text. Generate a clearly labelled **POSITIVE_CONTEXT_CLOZE_ONLY** question asking what wording follows a supplied context phrase. All extracted quote and context fields are verified again by unchanged M10B-2F. Do **not** automatically manufacture Negative, Near-miss, official Gold, or complex cross-section legal questions: those would require human semantics and separate evidence standards.

Any auto-generated quote matching the pinned source returns *Silver-only evidence*. Terms for duties, legal obligations, numbers or fees will trigger M10B-2F's `HUMAN_REVIEW_REQUIRED`. This is a conservative keyword heuristic, **not** a calibrated legal risk model. Machine output must never become official Gold without separate independent human audit.

## Risk-based review and quality sampling

- `REQUIRED_HUMAN_REVIEW`: M10B-2F determines high-risk semantics; review queue priority 1. Nothing is marked as human-reviewed by mere queue placement.
- `EVIDENCE_REMEDIATION`: M10B-2F rejects quote/page/context; priority 0 for source/anchor repair, NOT automatic approval.
- `SAMPLED_HUMAN_QA`: deterministic SHA256(seed + "|" + case_id) selection among machine-matched low-risk candidates, priority 2. Sample percent 0–20, 10 default; at least one when percent >0 and machine cases exist.

Sampling is **operational pilot only** and is not a statistically verified representative sample. The 10% default is a trial budget, not a claim that 90% of legal review can be skipped or Gold accuracy established. No sample has been reviewed until an independent human does so; sample outcomes and thresholds are not yet implemented. Future stages can introduce stratification by source, category, risk and actual human error rates.

## Security boundaries and report labels

`official_source_verified=false`; `gold_page_verified=null`; `human_gold_cases_approved=0`; `human_reviewed=false`; `independent_answer_correctness_verified=false`; `semantic_verified=false`; `real_embedding_service_called=false`; `production_access=false`; `write_authorized=false`; `artifact_written=false`. Output includes `generated_from_same_pdf_as_evidence=true` and `sample_statistics_validated=false`, making the self-grounding limitation explicit.

No file read/write, HTTP, Database, Embedding API, background job or external process in the new module. It receives PDF bytes already in memory, reuses M10B-2F, creates only in-memory objects, and prints nothing. No original APP149 raw PDF is committed to the repository. Any later real PDF pilot needs a separately approved operator read-only Drive stream and SHA/size/page gate; the Drive read is an outbound request distinct from the pure module.

GitHub staging module remains replaceable and additive. **Frozen Graph-aware Retrieval v1.3**, Production/main, canonical Source Registry, M5D/M8/M9, shared DB, Google Drive Current, Oracle Firewall, Docker/Coolify and Live Embedding stay untouched.

## Synthetic regression acceptance

`test_m10b2h_offline_silver_generation_v1.py` contains **21** fictional PDF regression tests for: candidate creation and exact M10B-2F contract; stable case IDs and physical pages; normative-risk routing; negative/near-miss non-generation; QA sample queue, 0% sample and order; duplicate/scanned/no-text rejection; wrong SHA/drift/IDs/budgets; verifier quote/page/context tamper; report determinism, redaction and no filesystem/network/subprocess IO.

CI uses a **synthetic two-page PDF only**, pinned PyMuPDF, and runs all previous 12 M10A–M10B-2G suites plus M10B-2H. After PR CI and additive diff checks, merge to staging only; both post-merge CI & Full Validation must pass at the merged staging SHA. Then the user can run offline synthetic tests and a redacted preview on VPS Staging. **No automatic Production deployment.**

## Next gate

Only after synthetic acceptance: explicitly design a **read-only APP149 or multi-document Silver generation** trial, still redacted and using original PDF SHA pinning. Assess relevance failures and false-confidence risks via a carefully designed human sampled audit set. That trial must not self-certify Gold or be used as a real semantic benchmark without independent human review.

Architectural decision: https://docs.google.com/document/d/1rQgXAnPa7pU8F3Pw44b9LOB27yBvSW3QpuFBeeUizoM/edit
M10B-2G Acceptance: https://docs.google.com/document/d/14dUsSIIo8-SATdGkpzTiuKh4WD5z1w4tuZxXrn-LkkY/edit
