# M10B-2G — APP149 Read-only Silver Pilot Architecture v0.1

**Status:** GitHub staging feature, real APP149 VPS read-only acceptance PENDING. Code Source of Truth = GitHub. Document Source of Truth = Google Drive `06_Knowledge / Architecture`.

## Architecture

The already VPS-accepted M10B-2F verifier checks a supplied PDF's raw SHA256 and exact quote/page/adjacent context. This new M10B-2G adapter pins **one previously user-inspected Drive PDF version** and a small, explicitly drafted Silver Candidate Suite to that SHA. The adapter does not change M10B-2F, the M10B-2A synthetic Gold contract, Frozen Graph-aware Retrieval v1.3 or any production component.

Flow: operator-authorized read-only retrieval of the chosen APP149 Drive copy → bytes supplied in memory → M10B-2G hard-coded file SHA/version/page count → M10B-2F literal source/quote/page/context checks → redacted result (one machine-checked low-risk evidence case; deadlines and other interpretations routed to human review). The adapter itself performs **zero file reads, writes, network requests, database operations or model inference**.

Official PDF URL: https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnap/APP/APP149.pdf

Drive Current PDF was previously inspected and user reported that content matched; **official website raw PDF bytes have not been independently hashed and compared**. Therefore the adapter never sets `official_source_verified=true`.

## Pinned source identity

- `source_id=BD_PNAP_APP149`
- `document_version=2010-12` (PDF indicates first issue December 2010)
- `sha256=a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`
- Exactly **5 physical PDF pages**; 1-based page numbers, NOT printed footer labels
- Original PDF bytes remain in an existing Google Drive read-only source location; GitHub CI **must not include the original PDF**.
- The connector-confirmed Drive Current APP folder ID for optional operator-controlled VPS `rclone cat` is `11pzQeyfCDjgK0vzNy0rAlGDmg4Sxn8oD`. This is only an access locator; byte SHA remains mandatory, no identity inferred from folder names.

## Curated Silver case inventory — not official Gold

`APP149-SILVER-L01` (page 1): low-risk literal phrase on what the appointed PRC person is commonly called. Proposed machine evidence check only.

`APP149-DRAFT-P01` (page 2 / §6(b)): advance notice and sudden illness exception, including 7-day and 3-day provisions. Because this is a regulatory deadline, expected to remain `HUMAN_REVIEW_REQUIRED` even if exact quote/page/context match.

`APP149-DRAFT-P02` (page 2 / §6(d)): nominated temporary acting period, proof for extension, 14-day and 30-day conditions. Regulatory interpretation remains human-required. The pilot checks the short 14-day/extension extract and does not claim to verify every condition.

`APP149-DRAFT-M01` (page 3 / §9): near-miss: temporary AS may sign inspection records but is not permitted to sign supervision plans or specified forms. Needs review comparing §9 with §2 on page 1.

`APP149-DRAFT-N01` (no proposed page): whether APP149 itself establishes a fixed filing fee. Native text no-hit cannot prove absence. The Negative case ALWAYS routes to human review, and does not assert a formal `SHOULD_ABSTAIN` Gold label.

The first four cases have manually curated quote and immediate-context anchors, confirmed against a local inspection of the pinned Drive-copy bytes before GitHub commit. This preliminary source grounding is not independent human legal review.

## Trust boundary and output

Public API `run_app149_readonly_pilot(pdf_bytes)`: rejects any differing raw SHA, malformed PDF, wrong page count, invalid identity or evidence suite before claiming success. Produces a bounded redacted report through existing M10B-2F. The output **does not include raw PDF, queries, actual quote or page text**.

Required flags: `source_bytes_match_pinned_drive_copy=true`, `official_web_pdf_binary_match_verified=false`, `official_source_verified=false`, `human_gold_cases_approved=0`, `gold_page_verified=null`, `real_embedding_service_called=false`, `shared_db_access=false`, `production_access=false`, `write_authorized=false`, `artifact_written=false`.

**The presence of `MACHINE_EVIDENCE_CHECKED` means only that a literal source string, physical page and context match. It does not mean semantic accuracy, source authenticity, regulator approval or Official Gold.**

This is deliberately **not an autonomous AI case generator**. Automated generation is a separate later milestone with risk sampling, source-grounding and human Gold audit controls.

## CI and acceptance protocol

A fully synthetic five-page PDF CI fixture validates the same pinning primitive, wrong SHA/page/source, near-miss, numeric obligations, Negative route, wrong quotes/context/duplicates, reviewed-Gold forgery, source bytes drift, output redaction, deterministic report, and no I/O. The CI must NEVER fetch APP149 or include authentic regulatory PDFs. CI runs all earlier offline regression suites M10A–M10B-2F plus M10B-2G.

GitHub feature branch → draft PR → dedicated PR CI PASS → review additive diff → squash-merge to Staging → dedicated post-merge CI and Full Validation PASS on same SHA → manually run pinned VPS Staging tests and **read-only** APP149 `rclone cat` pipeline.

The approved VPS command reads Drive Current APP149.pdf via `rclone cat` to stdout and pipes it directly into Python stdin. It makes **no local PDF copy and no Drive writes**. This Google Drive read is the only planned outbound request; it must not be misrepresented as a fully network-free process. It does not touch Live Embedding or any third-party model endpoint. The local module is pure in-memory after the bytes are received.

The SHA of incoming real PDF is checked *before* any case count is claimed. If the actual Drive source is missing, changed, unsupported or inaccessible, the command fails closed and no acceptance is granted.

## Why this helps scale

This tests the end-to-end *mechanical* source matching on a real regulatory document without authorizing the system to promote Silver to official human Gold. On a future pipeline, low-risk cases may be machine checked and sampled, while deadlines, legal obligations, Negative or near-miss interpretations remain in the review queue. Manual reviews can focus on important cases instead of every document or page.

## Release constraints

- No Production/main changes
- No Frozen retrieval v1.3 modifications
- No shared database, M5D/M8/M9 or Source Registry changes
- No Google Drive Current writes
- No Oracle Firewall/Docker/Coolify/security audit changes
- No real embedding, pgvector or autonomous agents

Related architecture:
https://docs.google.com/document/d/1rQgXAnPa7pU8F3Pw44b9LOB27yBvSW3QpuFBeeUizoM/edit
https://docs.google.com/document/d/1MnQE02dpNFp277esu7OjXJI___4N3c4oFIP2NOeKCK4/edit
