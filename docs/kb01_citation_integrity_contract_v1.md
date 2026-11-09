# KB-01 — Original-PDF Citation Integrity (Staging-only / Offline v1)

Status: code-only feature branch for review. Does not activate answer generation,
change Private Beta UI, permit automated indexing, or constitute a Production release.

## Architecture and compatibility contract

Current APP145/APP149 Private Beta returns guarded Source/Chunk/Page candidates.
A retrieved passage is not proof that a literal quote exists on the selected PDF
physical page. The new citation_integrity_staging_v1.verify_quote function is a
small, replaceable mechanical verification step between existing guarded retrieval
and any future extractive-answer compositor.

Trust and data flow:
1. beta_ask_staging_v1.approved_source(source_id) supplies trusted Source Registry +
   baseline identity. Caller-supplied/user-authored source metadata is NOT authority.
2. Guarded beta_ask_staging_v1.build_packet supplies an evidence packet with
   explicit read_only=True and guard_ok=True. The existing
   beta_private_ui_staging_v1.ask_evidence returns a display-oriented packet
   without those fields: it MUST NOT be passed straight to the verifier.
   A future separate authenticated adapter may reconstruct a trusted internal
   retrieval packet from the existing guarded path; it MUST NOT let clients
   assert read_only/guard_ok themselves. Do not accept user-authored packets.
3. A separately approved local PDF copy is supplied by the caller. The verifier
   never downloads PDFs, invokes rclone, writes files, queries DB, or calls models.
4. Caller provides selected S-ID and exact excerpt. Verify Source ID, official URL,
   SHA256, Chunk ID, physical page, quote in Chunk and quote on that PDF page.
5. On success, result MECHANICAL_PDF_PAGE_QUOTE_MATCH has S-ID, Chunk ID, source
   SHA256, physical page and official URL #page=N. Any mismatch raises a stable
   CitationRefused reason (fail closed).

Only Unicode NFC and whitespace folding are used; no paraphrase, fuzzy match,
hyphen rewriting, semantic inference, or present-applicability determination.

## Safety status

semantic_answer_support: NOT_EVALUATED. Literal quote match does not establish
question relevance, completeness of exceptions, or professional answer correctness.
current_legal_applicability: NOT_VERIFIED. Historic pinned PDF identity does not
prove today's legal effect. ai_answer_generated=false, production_write=false.
Existing CURRENTNESS_UNVERIFIED_ABSTAIN remains a hard refusal.
Original ranking, all 16 evidence candidates, frozen retrieval and private UI
are intentionally untouched; no automatic UI, CLI, Scheduler, model or DB wiring.

## Testing and gate

Offline: python test_citation_integrity_staging_v1.py. Tests use actual two-page
synthetic PDFs: success, wrong checksum, wrong page, quote absent from indexed
Chunk, source/url mismatch, currentness abstention, mixed-source identity,
symlink rejection and corrupt original PDF.

OPERATOR-VERIFIED ISOLATED STAGING PDF INTEGRITY (2026-11-10):
APP145 and APP149 approved SHA identities matched historical pinned PDFs.
Q01/Q06/Q09/Q14/Q15 matched bounded literal indexed Chunk excerpts on the
same PDF physical pages; Q19 currentness refusal passed. This was a read-only
VPS operator test of the PR head (b8744dcd...), not an active UI integration.
It does NOT validate semantic question-answer relevance, applicability, or the
completeness of Appendix content; Q06's matched excerpt may be context only.

NOT YET VERIFIED: running Private Beta UI integration, condition-aware
answer fidelity, complete Appendix/form interpretation, out-of-corpus Q19b,
user-facing browser acceptance, deployment or Production. This PR's current
head includes subsequent type-safety hardening; recheck exact CI before merge.

Next gate: after exact-head PR CI and review, approve a controlled code-only
GitHub Staging merge, then separately synchronize/review the operator VPS
Staging checkout before any UI wiring. Do not alter
Frozen Graph-aware Retrieval v1.3, M8/M9, Source Registry, Google Drive Current,
PostgreSQL roles/data, personal Anki, or main.

Tracking: GitHub Issue #60, Master Epic #106, Beta-First Contract CF-01.
