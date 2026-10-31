# M10B-2I — APP149 Read-only Generated Silver Pilot v0.1

**Status:** GitHub Staging-only engineering proposal; VPS real-PDF acceptance pending.

## Architecture before implementation

M10B-2G showed that existing, hand-authored Silver candidates can be checked against the pinned APP149 PDF. M10B-2H passed offline Synthetic acceptance for rule-based passage completion generation + review queue. This adapter **composes** those separate modules for one explicitly pinned, read-only real document. It does not modify either previous module or Frozen Graph-aware Retrieval v1.3.

Data flow: operator-authorized Google Drive Current read (separate from this module) → **original PDF bytes in memory** → enforce pinned raw SHA256 → unchanged M10B-2H auto-generate native-text context-cloze candidates → unchanged M10B-2F page/quote/context verifier → risk review and reproducible 10% QA sample → **redacted** workflow report showing candidate counts, routing, and constraints.

The adapter contains no URL fetcher, filesystem access, embedding call, SQL query, model generation or write action. The command at a later VPS acceptance gate may run a **single explicit read-only Drive rclone cat** and stream the bytes through STDIN to Python; the application module itself has no network access.

## Pinned provenance

Constants imported unchanged from the accepted M10B-2G APP149 adapter:
- `BD_PNAP_APP149`
- `2010-12` — first issue date printed in PDF
- SHA256 `a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8` (known Google Drive original-byte copy)
- Exactly **5** physical PDF pages (1-based)
- `suite_id=app149-native-text-generated-silver-v1`

The real APP149 original PDF remains in Google Drive Current, not GitHub or CI. The user had previously checked content against the source; **official website original-byte equivalence has NOT been independently verified**, so `official_source_verified=false` and `official_website_raw_pdf_byte_match_verified=false`. Raw SHA matching proves *supplied bytes equal the pinned Drive copy*, not official provenance or current legal validity.

## MVP behavior

`run_app149_readonly_generated_silver(pdf_bytes: bytes) -> dict` accepts ONLY original PDF bytes as in-memory input. The underlying generator selects no more than **10 candidate questions**, at most **2 per page**, with deterministic context-cloze wording and a fixed **10% QA routing sample**. Page count and SHA must match hard-coded source identity, otherwise fail closed.

The generic internal `run_pinned_generated_profile` supports fully fictional 5-page regression testing with different SHA/source values and checks page count/source identity. The publicly exposed APP149 wrapper takes no tuning parameters; cannot silently change its pinned source, max cases, or sample policy.

**Generated questions are NOT natural user-style questions.** They ask what words follow an automatically selected sentence fragment. Source grounding and verification both rely on the *same* document, so matching the quote is not an independent semantic accuracy test. Numeric, obligation/permission or other high-impact statements still route to human review under M10B-2F's conservative heuristic; this heuristic is *not* a comprehensive legal review.

## Review workload proxy

The redacted report contains:
- `generated_case_count`, `verification_counts`
- `review_queue_count`, `human_review_required_count`, `sampled_qa_count`, `evidence_remediation_count`
- `not_queued_case_count`, `review_queue_fraction`, `not_queued_case_fraction` (fractions of **generated candidates only**)
- `review_all_cases_comparator_count` as a transparent hypothetical **review everything** count
- flags `review_queue_operational_proxy_only=true`, `review_time_saved_measured=false`, `question_usefulness_human_reviewed=false`, `sample_statistics_validated=false`

**Do NOT call the unqueued share “X% human time saved.”** Reviewing a short case versus fixing a difficult legal answer has different costs; some generated cloze questions are not useful; queue sampling is a workflow pilot, not a quality assurance guarantee. Separate independent usefulness audits, strata, actual outcomes, and reviewer time logs are required to establish savings.

## Security and epistemic controls

Always `human_review_completed_count=0`, `human_gold_cases_approved=0`, `gold_page_verified=null`, `independent_answer_correctness_verified=false`, `real_embedding_service_called=false`, `semantic_verified=false`, `production_access=false`, `write_authorized=false`, `artifact_written=false`. No actual Gold is validated or approved by this trial. PDF, questions, direct quote and surrounding text are NOT returned or written to GitHub/Google Drive.

M10B-0 historical safety findings are separate and remain open where not previously resolved: shared-DB coupling, real vision API egress, host/document identity cases. Existing frozen layers must not be changed without regression verification and release authorization.

## Synthetic test / CI coverage

- File: `m10b2i_app149_readonly_generated_silver_v1.py`
- Test: `test_m10b2i_app149_readonly_generated_silver_v1.py` (**21** synthetic tests)
- CI: `.github/workflows/m10b2i_app149_readonly_generated_silver.yml`
- Architecture: `docs/m10b2i_app149_readonly_generated_silver_v1.md`

Synthetic CI makes its OWN fictional five-page PDF in memory and NEVER retrieves actual APP149 or uploads it. Tests reject a fictional PDF at the real APP149 pinned adapter, changed SHA, wrong PDF page count, unsafe ID, invalid sample or generation limits, empty/duplicated native text; check risk queue/QA sampling, deterministic report, no quoted text in output, no file/network/subprocess interaction, all official Gold and semantic flags false. CI includes ALL prior M10A to M10B-2H suites (13) plus M10B-2I = 14 suites.

**Gates:** PR dedicated CI PASS → review additive four-file diff → merge **staging** only → post-merge dedicated CI + Full Validation PASS on exact SHA → VPS Staging synthetic tests → separately approved real APP149 read-only generator trial. Only after the real trial should we assess actual queue fraction; no guessed numbers from synthetic cases. Production and Frozen modules remain untouched.

## Human usefulness audit (next independent phase)

A representative reviewer should assess a small sampled set of actual generated cases for: (1) whether a human would naturally ask the question; (2) whether the selected paragraph is meaningful in isolation; (3) whether the answer has adequate contextual scope; (4) if safety-risk routing was appropriate. Record case IDs, source SHA, ratings, reviewer, decision, and review time in a **separate human audit record**. Do not reuse generator self-labels as an independent Gold set. Do not create a new batch of Gold for every incoming PDF.

## Source of truth and boundaries

Code: GitHub `KeiLee123/ai-knowledge`. Documents: Google Drive `06_Knowledge / Architecture`.

No Production/main deployment, Frozen Graph-aware Retrieval v1.3 changes, M5D/M8/M9/source registry/shared DB/Google Drive Current writes, Oracle firewall/Docker/Coolify/security audit actions, or Live Embedding service. Oracle VPS security audit remains paused.

Prior decisions:
- Automated Silver risk design: https://docs.google.com/document/d/1rQgXAnPa7pU8F3Pw44b9LOB27yBvSW3QpuFBeeUizoM/edit
- APP149 M10B-2G accepted: https://docs.google.com/document/d/14dUsSIIo8-SATdGkpzTiuKh4WD5z1w4tuZxXrn-LkkY/edit
- M10B-2H Staging synthetic accepted: https://docs.google.com/document/d/1SgoRLXVPwW5nYC7sy8MZo18qUJMeHdLwBFHPOBAJzNA/edit
