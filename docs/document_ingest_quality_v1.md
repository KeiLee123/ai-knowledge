# Document Ingestion Quality & Coverage v1

Status: **Draft PR #88 / Staging-only**. Source: Google Drive first, then GitHub. This module does not change the existing Document v2 Extractor, Router or Chunk Builder.

## Scope

The real Concrete Repair Sheet1 PDF has **298 physical pages** (observed via read-only PyMuPDF preflight), size **1,016,489 bytes**, and local SHA256 `6a506fb13e4c8f294268cdcb64aa89e4133dc26c63769b4b95b1a6b281c3c7ac`. These are observed operator values, not independent proof of official/legal source identity.

`audit_document_ingest_quality_v1.py` uses existing Document v2 `build_manifest(selected_pages=...)` to process **25 pages per batch**. The preflight limits document total to 500 pages and refuses mismatched input size/hash and invalid PDFs. Every batch carries original physical page IDs and the same source SHA. It requires complete, non-overlapping coverage of every page before returning a document-level report.

For each batch, reuse `route_document_v2.assess_manifest(allow_partial=True)` and `build_multimodal_chunks_v2.build_chunks` to inspect table rows, columns, page/bbox and chunk provenance. The aggregator counts pages, tables and chunks, tracks any OCR/table/route risks by page or batch, and auto-holds uncertainty. Zero tables in one batch is not treated as a full-document failure; zero tables across the whole document is. Internal mechanical checks never establish source cell/numeric/unit/semantic accuracy.

No PDF excerpts or cell values are printed. No model or OCR calls, DB access, Drive modification, Production write, Anki write or mandatory human verification. The report is read-only evidence for deciding where targeted fixes are needed. The source PDF remains in an ephemeral local directory and is not published to GitHub.

## Development and release boundary

- Existing single-manifest audit ceiling: 150 pages, preserved.
- New batched full-document ceiling: 500 pages, 25 pages per batch (not an unbounded extension).
- A 298-page PDF must produce 12 batches; the last covers pages 276–298. Gaps and duplicates are forbidden.
- Synthetic offline tests and full CI precede real VPS Staging acceptance.
- Staging acceptance of structural diagnostics is not acceptance of semantic answer, OCR, version/applicability, Anki, or Production ingest.
- Keep PR #88 Draft and unmerged until results inspected. Production and frozen modules unchanged.
