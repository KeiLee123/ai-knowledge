# KB-03 — Private Beta Selected Citation Preview (Staging only)

Status: code-only DRAFT review. No new server is started automatically, no
Production deployment, and **not yet user-browser accepted**.

## Architecture / why it is additive

Goal: enable a human to select an exact excerpt from the existing private
Evidence Explorer, have the VPS check the quote against the approved original
PDF, and see the page-linked excerpt **without implying it answers the question**.

Reuse existing:
- beta_private_ui_staging_v1.py: localhost-only server, request-token +
  same-origin policy, no access log, in-memory recent request state,
  no-store/CSP, original question-first AUTO/manual source search and
  feedback pipeline.
- beta_ask_staging_v1.py: original clean Staging runtime/source/DB read-only
  guards, full eight-chunk approved baseline by source.
- kb02_extractive_review_staging_v1.py: explicitly selected source-local S-ID
  excerpt, currentness refusal/coverage guard and no semantic promotion.
- citation_integrity_staging_v1.py: exact approved source SHA, indexed Chunk,
  physical PDF page and literal quote check.

New thin adapter path:
1. Original authenticated POST /api/ask behaves as before. Store only a
   bounded in-memory request record: scope, normalized question, status, and
   mappings from user-visible **global S-IDs** to source-local S-IDs, source
   IDs, Chunk ID and original page (max 64 requests). No persistent query log.
2. Browser shows a collapsed "核實選定的原文引文" control for each retrieved
   evidence card, except currentness-refused results. A short editable exact
   quote seed is shown; the human explicitly clicks to check. This is NOT
   automatic rank-to-answer generation.
3. Authenticated same-origin POST /api/quote-preview accepts ONLY
   request_id, global evidence_id and literal quote (16–1500 chars). It never
   accepts source ID, DB destination, PDF path, guard_ok or verified labels.
4. Server obtains trusted source-local ID, source ID and expected Chunk/page
   from its own in-memory /api/ask result, obtains local PDF path by a hardcoded
   allowlist (APP145 or APP149), then invokes KB02 (which **requeries the
   existing guarded Staging retrieval**) and KB01 original PDF verifier.
5. Check that the reverified source, local evidence ID, Chunk ID and physical
   page still match the source/result originally shown. Any mismatch refuses;
   no partial verified response, no fabricated answer.
6. Return only literal quote, source/version SHA, physical page, link and
   unambiguous REVIEW_REQUIRED status. Browser uses DOM createElement and
   textContent/pre, not innerHTML, to prevent source-text HTML injection.

## Local original PDF cache contract

PDFs are **not auto-downloaded by the HTTP server**. Operator must
separately provision **byte-identical, approved, read-only copies** in:
  /var/lib/jason-os/private-beta-staging/approved-pdfs/APP145.pdf
  /var/lib/jason-os/private-beta-staging/approved-pdfs/APP149.pdf

Google Drive Current remains original source of truth. The cache is derived
runtime data, NOT authority. Missing copies fail closed with safe error; KB01
revalidates the actual PDF SHA against Source Registry for every request.
Never accept a client-supplied path or URL; no filesystem data-writing code
is introduced for this feature. Provisioning/deployment requires a separate
authorized, isolated VPS Staging operator step.

## Safety status and limits

- Status: EXTRACTIVE_QUOTES_REVIEW_REQUIRED; semantic_answer_support is
  NOT_EVALUATED, legal currentness NOT_VERIFIED, ai_answer_generated=false,
  production_write=false.
- AUTO_APPROVED global S-IDs are display names; server stores original
  source-local S-ID and checks physical Chunk/page after the fresh query.
  Never trust client-provided source or quote assurance.
- Q06/Q19b without selection are not semantic insufficiency classification;
  selecting a quote, even if source/page matched, does not establish question
  relevance, material exceptions or a valid legal interpretation.
- Existing source ranking, all 16 candidate excerpts, private feedback,
  source/currentness refusal, token-in-memory, localhost/CSP and frozen
  Graph-aware Retrieval remain unchanged in their operating contracts.
- No model calls, no new source provider, no new DB writes/schema, no Anki,
  no modifications to main, Production or official Drive Current.

## Acceptance before merge / runtime activation

Offline: run test_kb03_private_beta_quote_ui_v1.py + existing
test_beta_private_ui_staging_v1.py, test_beta_ask_staging_v1.py,
test_kb02_extractive_review_staging_v1.py,
test_citation_integrity_staging_v1.py.
New tests use a real generated synthetic PDF through the loopback HTTP
server; check successful quote/page, request origin/token, field allowlist,
AUTO S-ID mapping, stale request, malicious quote, currentness refusal,
missing original, old Feedback and DOM safe text rendering.

**Next gates:** exact-head GitHub CI; isolated VPS Staging read-only API check
with approved APP145/149 originals, prior to any code merge; controlled
code-only Staging merge and exact SHA smoke; separately explicit server start
via existing SSH tunnel with owner Private Beta browsing Q01/Q06/Q09/Q14/Q15
and Q19/Q19b and feedback. Any real-world authoritative explanation
requires separate material-condition review. NO automatic Production cutover.

Related: #60, #106, KB01 #107, KB02 #108, Beta-first CF-01.
