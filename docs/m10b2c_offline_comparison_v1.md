# M10B-2C Offline Retrieval Comparison — Engineering Contract v0.1

**Status:** Staging-only candidate. This is an in-memory report on **fabricated synthetic vectors**, NOT actual Embedding performance.

## Architecture

The new pure helper `m10b2c_offline_comparison_v1.py` reuses the existing, unchanged M10B-2A synthetic Gold lexical evaluator and the M10B-2B-0 offline synthetic vector evaluator on the **same** candidate SHA, native page-chunk manifest, source, fixture and Gold suite. It combines their case-level results into a compact, deterministic, redacted comparison report. The helper never queries a service or opens any files. The test harness constructs a two-page synthetic PDF in a temporary test directory, as the existing earlier tests already do.

Pipeline: **trusted synthetic PDF manifest + chunks + independently authored Gold fixture + fabricated 384-D vector fixture** → both existing pure evaluators → aligned case IDs → JSON-compatible comparison dictionary (not written to disk).

The comparison report is **not** a benchmark of multilingual-e5-small. The synthetic vectors were assigned by hand, including the explicit negative-query abstention flags. They are not model predictions. In particular, `lexical_miss_fixture_vector_found` means only that the mock vector fixture was constructed to rank a page correctly; it cannot be stated as a real-model semantic win.

## Why this small MVP

The existing lexical and synthetic-vector evaluators were separately validated, but their outputs were not compared case by case. This stage gives the developer a reproducible proof that the evaluation pipeline can expose (a) literal-paraphrase lexical misses, (b) near-miss negative lexical false positives, and (c) an incorrectly abstaining or wrong-page vector fixture as an explicit failure. It supports a future dashboard/report but does not create one or any artifact file yet.

## Input, provenance and security

- `compare_synthetic_retrieval(...)` requires the same explicit `source_id`, exact `candidate_sha`, `fixture_id`, `suite`, `model_contract` and `top_k` for the two existing validators. Each validator independently checks native PDF page origin, chunk-page-text provenance and independently authored **synthetic-only** Gold cases.
- Model contract must remain `synthetic-orthogonal-vectors-v1`, 384D, revision `fixed-test-fixture-v1`, adapter `offline-fixture-only-v1`. It must not claim `intfloat/multilingual-e5-small` or the observed VPS Cache Snapshot as though any real vector was obtained.
- Both results must agree on candidate/source/fixture/suite and have `gold_page_verified=null`, `semantic_verified=false`, `answer_verified=false`, `retrieval_verified=false`, `shared_db_access=false`, `production_access=false`, and `write_authorized=false`. The helper rejects input/output inconsistencies.
- Case output: synthetic case ID/type, lexical and fabricated-vector pass/fail, reason, page numbers, case difference label; **no query text, source excerpt, raw vectors or document text**. Summary only counts, reasons, SHA256 reproducible report fingerprint and loud synthetic-only disclaimer.
- A lexical case failure is a useful baseline finding and does not automatically mean the comparison code failed. A synthetic vector case failure changes the report status to `OFFLINE_SYNTHETIC_COMPARISON_WITH_FIXTURE_FAILURES`. It cannot self-certify.
- Code has no CLI, HTTP, model call, Docker access, DB, pgvector, Google Drive access, disk writes, timer or Production hooks. Test data are temporary and synthetic.

## Expected synthetic-case observations

| Synthetic case | Lexical evaluation | Fabricated-vector evaluation | Interpretation |
| --- | --- | --- | --- |
| Fabricated page 1 question | PASS | PASS | Both synthetic checks found page |
| Fabricated page 2 question | PASS | PASS | Both synthetic checks found page |
| Unrelated negative | PASS | PASS | Both abstained |
| Page 1 paraphrase without literal overlap | FAIL | PASS | Known lexical limitation; **not verified model improvement** |
| Near-miss negative with token overlap | FAIL | PASS | Lexical false positive; mocked vector abstained by explicit supplied flag |

Expected **fabricated** summary on the five-case test: 3 synthetic positive cases; lexical positive pass count 2 vs fabricated-vector pass count 3; 2 synthetic negatives; lexical false positives 1 vs fabricated-vector false positives 0. These values are **test data**, not model accuracy claims.

## Regression & acceptance

`test_m10b2c_offline_comparison_v1.py` covers 15 tests: baseline counts; paraphrase lexical miss; near-miss negative; unrelated negative; negative false-positive failure; wrong page failure; wrong Gold page and excerpt; official Gold forgery; crossing source/SHA/fixture; invalid vectors/page tamper; impersonating real model; invalid top-k/no negative cases; safe redaction and no claims; report determinism and no PDF mutation; and network/subprocess blocking.

Dedicated GitHub CI should run this suite and earlier M10A, M10B-0, M10B-1, M10B-2A lexical, M10B-2A Gold, M10B-2B-0 and M10B-2B-1 audit regression suites. Existing full Validation should PASS on the exact staging SHA. Then VPS Staging can run **offline regression only** with pinned commit. Do not call the model, copy PDF to a live service, or change shared networks/Production.

## Trust boundary

Official APP145/APP149 Gold Pages have not undergone independent review. Real Embedding API egress and retention gates remain unapproved. **No change** to Frozen Graph-aware Retrieval v1.3, M8, M9, M5D, current canonical references or main/Production. Future actual Embedding comparison requires a separate Staging-only safe adapter and independent model behavior evaluation.

Architecture refs:
- Existing semantic contract: https://github.com/KeiLee123/ai-knowledge/blob/staging/docs/m10b2b0_offline_semantic_contract_v1.md
- Staging-only Embedding isolation design: https://docs.google.com/document/d/1e3MMNWMkLdCdY4URn8XAp4LhwDxlFht6Nb24R8lNF5s/edit
