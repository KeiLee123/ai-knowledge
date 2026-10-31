# M10B-2E — Offline Ranking Diagnostics Contract v0.1

**Status:** GitHub staging-only candidate, not Production. No live model calls.

## Architecture

The validated M10B-2C report contains ordered synthetic page IDs for both lexical retrieval and manually authored 384-dimensional vector fixtures. M10B-2D verifies its exact schema, checksums, statuses, case alignment, synthetic model identity, Gold boundaries and redaction.

M10B-2E **only** composes these existing outputs into ranking diagnostics; no changes to Frozen modules or to M10B-2C / M10B-2D.

Pipeline: synthetic candidate PDF / authored Gold / fabricated vectors → M10B-2C in-memory comparison → M10B-2D strict validation → M10B-2E in-memory page-ranking diagnostics and optional Traditional Chinese Markdown string. **No HTTP, filesystem, database, Docker, Drive Current, scheduled jobs or Production actions.**

## M10B-2E MVP Outputs

Function `analyze_offline_ranking(comparison)` returns a bounded, deterministic diagnostic dictionary with a checksum. `render_ranking_markdown(comparison)` renders a legible human-facing summary, without writing a file.

For **synthetic positive** cases, each retrieval side reports:

- `first_expected_page_rank`: 1-based first position of an authored expected synthetic PDF page, or null if missing.
- `hit_at_1`: 1 only if first expected page is at rank 1; else 0.
- `reciprocal_rank`: 1/rank, or 0 if no expected page; summary MRR is macro-average across **all** positive cases (including misses).
- `precision_over_returned`: number of returned page IDs in the synthetic expected-page set divided by number **actually returned**. For an empty return on a positive case, score 0. This is deliberately **not standard Precision@K**: with Top-K=3, a 2-page synthetic corpus can only return 2 pages.
- `off_target_page_count`: returned page IDs **not in authored synthetic expected-page set**. This is a label-relative diagnostic, not proof that a page is objectively irrelevant in the real world.
- Count of returned pages and number of authored expected-page hits.

For **synthetic negative** cases (expected page list empty), return `abstained` and erroneous returned-page counts. Positive precision/rank/MRR are `null` (not applicable), not 100% when correctly abstaining.

Summary includes positive Hit@1 count, MRR, mean precision over actually returned pages (macro with positive misses scored 0), non-target returned-page counts and number of positive cases with extra pages, and negative false-positive case/page counts for both lexical and hand-authored vector fixture.

## Five-case synthetic expectation

From the existing, completely fabricated two-page fixture:

| Metric | Lexical | Hand-authored vectors |
| --- | ---: | ---: |
| Expected page at rank 1 | 2/3 | 3/3 |
| Positive MRR | 0.666667 | 1.0 |
| Mean precision over actual returned pages | 0.666667 | 0.5 |
| Positive non-expected pages returned | 0 | 3 |
| Negative case returned wrong pages | 1 | 0 |

This table is *not an empirical benchmark*. Its purpose is to prove ranking diagnostics catch a hidden issue: fabricated vector top-three searches often include a second non-target page, even though the first page is correct. It also shows that the lexical paraphrase deliberately misses and lexical near-miss negative falsely returns a page.

## Integrity and Privacy Boundary

M10B-2E calls M10B-2D `validate_comparison` first. This checks the complete original report schema, SHA256 reproducibility checksum, case/result provenance, labels, synthetic-only disclaimer and pinned fake model identity, and forces `real_embedding_service_called=false`, `semantic_verified=false`, `official_document_verified=false`, `gold_page_verified=null`, `production_access=false`, `shared_db_access=false` and no write authorization.

The diagnostics contain only safe IDs, page IDs, small counts and aggregate numbers. Neither query text, PDF text, Gold excerpts nor raw vectors are included. The diagnostic SHA256 is again for **reproducibility, not authentication**. Source and recipient must not mistake artificial expected-page labels for official legal accuracy.

## Tests and GitHub Gates

New `test_m10b2e_offline_ranking_diagnostics_v1.py` has 18 synthetic tests for default positive/negative case ranking, rank 2, wrong page, off-target pages, aggregate MRR/precision, empty-result denominator, false positives/abstention, Markdown readability, report checksum tampering, rehashed fabricated official/real-model claims, Markdown injection, cross-candidate identity, deterministic fingerprint, no network/files/processes and no raw text.

The dedicated GitHub workflow executes all earlier M10A / M10B-0 / M10B-1 / M10B-2A / M10B-2B-0 / M10B-2B-1 / M10B-2C / M10B-2D regressions plus 18 new tests. Full Validation must PASS on merged staging SHA before VPS Staging offline acceptance. GitHub is code Source of Truth; Google Drive is architecture Source of Truth.

## Release Boundary

Staging only; Production/main remains unchanged. No actual model request, Oracle firewall audit, Coolify network modification, real APP145/APP149 human Gold review, shared DB update or PDF export. Frozen Graph-aware Retrieval v1.3 not touched.

Next milestone after acceptance (separate decision): optional approved report export and/or independent Official Gold review protocol. Do not infer verified semantic retrieval from this fixture-based metric display.
