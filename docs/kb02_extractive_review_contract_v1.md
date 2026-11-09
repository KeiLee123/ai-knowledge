# KB-02 — Bounded Extractive Cited Response Preview (Staging-only)

Status: Draft/offline review composer. No Private Beta UI, Hermes, SQL, model
provider, public endpoint, scheduler or Production activation in this PR.

## Architecture and reuse

Problem: KB-01 verified that selected literal quotes exist in a pinned original
PDF at the cited physical page. That does NOT prove those quotes answer the
question. Existing Beta UI is Evidence-only; we must not turn cosine-ranked
candidate text into a confident legal answer.

This PR adds a small replaceable, deterministic review composer:
1. Trusted internal caller supplies source ID, question, explicit reviewer- or
   operator-selected citation S-IDs and literal excerpts, plus a LOCAL copy of
   the approved original PDF. Never accept source metadata or a claimed
   verified JSON packet from an API client.
2. `kb02_extractive_review_staging_v1.build_review_preview` calls EXISTING
   `beta_ask_staging_v1.build_packet`, which enforces clean Staging,
   pre-approved Registry/source SHA and DB read-only retrieval.
3. The composer independently calls the existing
   `qa.currentness_abstention` before any quote verification.
4. It requires complete existing indexed-Chunk coverage (currently two
   eight-chunk approved source snapshots); incomplete coverage or NO selected
   excerpts returns honest `EVIDENCE_ONLY_REVIEW_REQUIRED`.
5. With 1–3 explicit selected excerpts, it re-reads Source Registry identity
   via `qa.approved_source` and calls KB-01 `verify_quote` for EVERY quote
   against indexed Chunk and the approved original PDF physical page and SHA.
   Any failed quote blocks the entire result; no partial falsely verified list.
6. It returns the ORIGINAL literal text with the ORIGINAL S-ID, page, chunk
   and SHA. A neutral safety lead-in says semantic relevance, material
   exceptions, current legal applicability and sufficiency are NOT confirmed.

No automatic ranking/intent model, no Gold-based semantic claim, no artificial
confidence score. No summary or conclusion is authored by an LLM; the
`answer` string is the fixed warning plus verbatim selected excerpts.

## Non-negotiable output

Status: `EXTRACTIVE_QUOTES_REVIEW_REQUIRED` (not ANSWER_VERIFIED).
`semantic_answer_support=NOT_EVALUATED`.
`material_conditions_checked=false`.
`current_legal_applicability=NOT_VERIFIED`.
`review_required=true`; `ai_answer_generated=false`;
`external_model_called=false`; `production_write=false`.

Do not promote the UI into an answer if Q06, Appendix A/B or AS temporary-
absence conditional context has not been independently assessed. The UI and
professional QA belong to KB-03 and later CF-M2, not this adapter.

## Validation and known limitations

Offline test `python test_kb02_extractive_review_staging_v1.py`: actual
synthetic two-page PDF with mocked existing guarded Staging retrieval,
one/two selected exact quotes, correct citations, currentness refusal,
incomplete coverage refusal, no selection, tampered PDF, wrong physical
page, malformed selectors, wrong source, missing guard and no network code.

Future real Staging acceptance (NOT YET RUN): use the existing approved
APP145/APP149 source snapshots / PDF by SHA, select the question-relevant
literal passages and check original physical page and material surrounding
conditions. Specifically Q01/Q06/Q09/Q14/Q15 and negative Q19/Q19b. The
previous KB-01 probe verifies any bounded literal overlap from the specific
chunk; that is intentionally NOT enough to certify KB-02 question relevance.

A future authenticated private UI must NOT trust caller-provided packet
`guard_ok`, `read_only`, `approved_baseline` or "reviewer approved" labels;
it must call the guarded Staging function itself. Render quote text as text,
not HTML; no raw source text in logs or exception codes.

Tracking: #60 (CF-01 Beta), #106 (Master Epic), KB-01 PR #107 accepted on
VPS Staging for mechanical PDF integrity only. No Frozen v1.3 changes.
Rollback: close/discard Draft PR, no deployed side effects.
