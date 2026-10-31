# M10B-2F — Offline Silver Evidence Verifier Contract v0.1

**Status:** Engineering candidate for GitHub staging. No real Gold approval, no VPS/Production operation.

## Architecture first

Knowledge Brain's M10B-2A through M10B-2E regression success concerns synthetic pages, fabricated vector rankings and stable reports—not independently verified official legal answers. Manually certifying every PDF/case does not scale. Instead, implement an independent **mechanical source-evidence gate** before any human risk review. This module does **not** generate new questions, validate legal meaning, check live model quality or establish an official Gold benchmark.

**Flow:** synthetic PDF *bytes supplied in memory* + explicitly authored candidate case suite → source SHA256 + exact schema guard → PyMuPDF native-text extraction in memory → independently test proposed 1-based physical page, short quote, immediate surrounding context and uniqueness across all pages → machine evidence checked / needs independent human review / mismatch → deterministic redacted report in memory.

The actual APP149 PDF and pending case drafts are reference-only in this engineering phase. The CI fixtures are fictional, do not encode official APP149 obligations and do not read real production documents.

## Contract

Pure public API: `verify_silver_candidate_suite(pdf_bytes: bytes, suite: dict) -> dict`.
No CLI, database, file read/write, HTTP, Embedding service, cloud, Docker, timers or deployment. PDF byte upper bound = 3 MB; page count <=30; case count <=50. This is an **MVP guardrail**, not a universal PDF capability.

Input requires exact `version=m10b2f-candidate-suite-v1`, `scope=machine_evidence_candidate_only`, `suite_id`, `source_id`, `document_version`, `original_pdf_sha256`, and `cases`. Candidate cases each have exact `case_id`, `case_type`, `source_id`, `original_pdf_sha256`, `query`, `expected_physical_pdf_page`, `evidence_quote`, `context_before`, `context_after`.

The verifier checks **raw PDF bytes SHA256 against the declared SHA** and extracts native text directly from those exact bytes, so a free-floating page-string array cannot impersonate an independently grounded PDF. This is local byte consistency only; a hostile author could provide a forged PDF and matching SHA. Therefore `official_source_verified=false` and `official_document_verified=false` are ALWAYS present.

For non-negative cases, the quote must appear exactly once across the entire extracted document and must have its claimed immediate context on the claimed physical PDF page. Whitespace is folded for line wraps, but punctuation, numbers, letter case and Unicode lookalikes are NOT silently rewritten. Mismatch, absent native text, wrong page or quote ambiguity yields `REJECTED_EVIDENCE_MISMATCH`, not an auto pass. OCR/scanned docs will require a separate, independently approved ingestion design.

Only a non-normative **literal POSITIVE** case with uniquely matched page/quote/context can get `MACHINE_EVIDENCE_CHECKED`. Positive cases containing numerical/legal/normative terms (even though quote is exactly present) route to `HUMAN_REVIEW_REQUIRED`. So do `PARAPHRASE`, `NEAR_MISS` and all `NEGATIVE` claims: absence cannot be proved by failed keyword search. This simple heuristic is conservative and incomplete; it is a *review router*, not a legal risk classifier.

The return value is redacted: `case_id`, type, proposed page, match flag, status/reason and aggregate counts only; no query, raw quote, context, page text or PDF bytes. Reproducible `report_sha256` is for consistency, NOT proof of official authenticity.

**Invariant:** Never `HUMAN_REVIEWED`, `HUMAN_APPROVED_GOLD`, `gold_page_verified=true`, `semantic_verified=true`, `official_source_verified=true`, `answer_verified=true`, `real_embedding_service_called=true`, or write authorization. No Source Registry/accepted reference or Frozen v1.3 changes.

## Synthetic regression

`test_m10b2f_offline_silver_evidence_v1.py` generates a two-page, synthetic **non-official** PDF entirely in memory. It covers 19 checks:

1. Baseline low-risk machine match, high-risk numbers/obligations, Near-miss/Paraphrase/Negative routed to human review.
2. All official/Gold/semantic flags locked false.
3. Wrong quote fails; wrong page fails; wrong adjacent context fails.
4. Quote duplicated on two pages fails.
5. Scanned/no-native-text page not auto-qualified; out-of-range physical page rejected.
6. Forged human approval, unknown fields, changed scope fail closed.
7. Wrong PDF SHA/bytes, cross-source and case SHA fail closed.
8. Duplicate IDs, invalid types, negative page/quote claims, 0-based pages fail.
9. Invalid PDF bytes, unsafe markup/IDs fail.
10. Determinism/input immutability, report redaction, no file/network/subprocess IO.

Dedicated CI reruns M10A, M10B-0, M10B-1, M10B-2A lexical and synthetic Gold, M10B-2B-0, M10B-2B-1, M10B-2C, M10B-2D, M10B-2E and M10B-2F. Post-merge dedicated workflow and Full Validation must PASS at the exact staging SHA before pinned VPS staging offline regression. Production/frozen layers not modified.

## Gold / Silver distinction

`MACHINE_EVIDENCE_CHECKED` is *Silver Evidence* only: it proves a literal string exists on a physically numbered page with matching immediate context in the provided PDF bytes. It does **not** independently verify that the PDF came from an official source, that a query is semantically answered, that a passage is legally applicable or that a negative answer is correct.

A separate human-approved benchmark / QA Audit Set remains necessary for measuring real-world reliability; instead of checking every document, future risk-based human sampling can assess representative documents and higher-impact assertions.

## APP149 next read-only pilot

Once synthetic CI and VPS staging gates pass, a separate APP149 read-only pilot may use the already-grounded Drive PDF SHA `a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8` with explicit in-memory candidate citations in an isolated operator-controlled process. Before any real document processing, verify source authenticity and the same exact bytes, and do NOT transmit PDF text to unapproved Embedding or third-party model endpoints.

The previously user-reviewed APP149 textual comparison does not turn pending cases into approved official Gold. The two APP149 positive drafts concern deadlines and therefore should remain in `HUMAN_REVIEW_REQUIRED` even when the source text is mechanically matched. Negative and Near-miss remain pending.

## Release boundary

GitHub is Code Source of Truth; Google Drive is Document Source of Truth. New module + tests + contract + workflow additive-only. Frozen Graph-aware Retrieval v1.3, Production/main, shared DB, M5D/M8/M9, Source Registry, Drive Current, Oracle firewall, Docker/Coolify, and Live Embedding remain unchanged. Oracle VPS Security Audit is paused.

Architecture decision: https://docs.google.com/document/d/1rQgXAnPa7pU8F3Pw44b9LOB27yBvSW3QpuFBeeUizoM/edit
