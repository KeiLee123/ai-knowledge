# M10B-2A Gold Test Case Contract v0.1

Status: SYNTHETIC-ONLY ENGINEERING FIXTURE. GitHub Staging PR review required. No real APP145 or APP149 official Gold Page has been verified.

Architecture: https://docs.google.com/document/d/1eev9RtJm7L_71Q0VQFDTMphtfqzHGyXzjphZTVTzaRg/edit

## Architecture boundary

The Gold Case contract sits after a trusted candidate-only local lexical index and before semantic/answer validation. It compares independently authored expected page numbers, excerpts, terms and explicit positive/negative labels against lexical top-k hits. For synthetic tests, fixed PDF pages and Gold labels are authored separately from the ranker output. Never generate Gold labels from the system's own search results.

`m10b2a_gold_cases_v1.py` is a **pure evaluation helper**, not an official document-validation CLI. It has no filesystem writes, DB, Drive, network, embedding calls, or Production actions. `test_m10b2a_gold_cases_v1.py` creates a clearly labeled fake two-page PDF in a temporary test directory only.

## Data contract

- Version: `m10b2a-gold-suite-v1`.
- Scope: strictly `synthetic`; `review_status: synthetic_only`; `gold_provenance: synthetic_authored_independently`.
- Must match explicit synthetic fixture ID and source ID, with unique case IDs.
- Positive cases need an authored query, nonempty expected page(s), terms and an exact excerpt. Page labels are not inferred from retrieved output.
- Negative cases need an authored query, no expected page/terms/excerpt and a **no hits** criterion. A superficial lexical overlap on a negative case counts as a FAIL, not as proof the system understands abstention.
- Each candidate manifest SHA is bound to the actual candidate SHA. Each chunk's content, origin and page boundaries are checked against the synthetic PDF's page text by an existing pure provenance guard.
- The result can be `SYNTHETIC_GOLD_CASES_PASSED` or `SYNTHETIC_GOLD_CASES_FAILED`. Every result retains `gold_page_verified: null`, `official_document_verified: false`, `semantic_verified: false`, `answer_verified: false`, `retrieval_verified: false`, `write_authorized: false`.

## Test scope

The positive fixtures assert a fabricated appointment statement on **synthetic page 1**, fabricated emergency/muster statement on **synthetic page 2**, and a clearly unrelated negative query. Negative/security tests include a near-miss query that overlaps words but should not have an answer, forged gold page, wrong excerpt, empty expectations, duplicate case IDs, fake human approval, wrong source and fixture, candidate SHA mismatch, chunk page/provenance/content tamper, out-of-range gold page, invalid k, and symlinked case file.

These page numbers **do not refer to the actual Building Department APP149 PDF**. They must never be copied into a real official Gold Case.

## Real official Gold Case promotion gate (future separate milestone)

Do NOT reclassify this synthetic suite as `human_verified`. Instead create a new official fixture and an independent review record:

1. Exact official source ID, authority, document code, document SHA256 and official file or reference URL.
2. Human or independently verified reviewer, reviewed_at, unambiguous quoted source excerpt, physical PDF page number and PDF-byte/source fingerprint.
3. Positive questions, hard negatives and cross-page near misses; decision rationale and second reviewer for high-risk regulatory interpretations.
4. Evidence must be checked independently of this retrieval system. A model's own answer/search result is not adequate ground truth.
5. Separate code/PR review expands the contract to permit only reviewed, source-bound official cases; no change to Frozen M9 or v1.3.
6. No automatic elevation from lexical hit to semantic/answer correctness or M5B release qualification.

## Release boundary

GitHub is the code Source of Truth. Google Drive is the architecture/decision Source of Truth. Additive files on a feature branch, CI review, staging-only merge, then VPS Staging synthetic acceptance. No new timer, no Production deployment, no shared DB/pgvector or Drive Current edits. A full M10B-2B semantic retrieval adapter is a separate gated decision.
