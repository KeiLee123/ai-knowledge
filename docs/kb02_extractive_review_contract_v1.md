# KB-02 — Bounded Extractive Cited Response Preview (Staging-only)

Status: code-only Staging Draft review composer; nine offline regression tests
passed. On 2026-11-10 the owner performed a bounded *read-only operator*
real APP145/APP149 test of the earlier Draft head 3c57e3f; all seven expected
preview/abstention cases and final Git/Production checks passed. This is NOT
a semantic answer or user-browser acceptance. No Private Beta UI, Hermes,
new SQL, model provider, public endpoint, scheduler or Production activation.

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

OPERATOR EVIDENCE, 2026-11-10 (read-only, premerge Draft head 3c57e3f):
- /opt/ai-knowledge-staging clean branch staging at bf300666...; PR #108
  fetched to FETCH_HEAD and its KB02 module loaded in temporary /tmp.
- Approved APP145/149 PDF copies read from Drive Current to /tmp.
- Explicit selections passed KB02 source-extract preview: Q01 APP145
  S3 page3; Q09 APP149 S1 page2; Q14 APP149 S2 page4; Q15 APP149 S4
  page5. Verified quote-to-original-PDF-page by existing KB01.
- Q06 with zero selected quotes -> EVIDENCE_ONLY_REVIEW_REQUIRED.
  Q19 currentness -> CURRENTNESS_UNVERIFIED_ABSTAIN.
  Q19b with zero selections -> EVIDENCE_ONLY_REVIEW_REQUIRED.
- Final clean Staging SHA and unchanged Production Git SHA assertions
  completed; command ended KB-02 READ-ONLY CHECK COMPLETE.
This proves the *mechanical selected-excerpt composition path* on real
approved files, not the questions' professional answer sufficiency. In
particular Q06 and Q19b refusal was caused by empty selections and is NOT
a validated semantic out-of-scope/insufficiency classifier. Evidence has
not been audited for completeness of legal conditions, forms, or exceptions.
Actual private-browser/user Beta and authenticated quote-selection workflow
remain UNVERIFIED. This PR does not wire the function into any UI.

Gate after any code-only GitHub Staging merge: separate exact-SHA VPS
fast-forward and regression, with no deployment to Production. No professional
Gold signoff inferred from operator literal-PDF proof.

A future authenticated private UI must NOT trust caller-provided packet
`guard_ok`, `read_only`, `approved_baseline` or "reviewer approved" labels;
it must call the guarded Staging function itself. Render quote text as text,
not HTML; no raw source text in logs or exception codes.

Tracking: #60 (CF-01 Beta), #106 (Master Epic), KB-01 PR #107 accepted on
VPS Staging for mechanical PDF integrity only. No Frozen v1.3 changes.
Rollback: close/discard Draft PR, no deployed side effects.
