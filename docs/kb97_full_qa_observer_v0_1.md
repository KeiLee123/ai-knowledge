# Issue #97 — 20-question read-only candidate QA observer v0.1

## Architecture and purpose

**Owner problem:** Private Beta successfully retrieves 16/16 excerpts from APP145/APP149, but complete retrieval does **not** establish source relevance, first useful clause rank, answer sufficiency, or current legal applicability. A ranking change without a recorded baseline can silently harm valid Appendix A/B form questions.

**Smallest next step:** Reuse the merged `beta_private_ui_staging_v1.ask_evidence` and existing `kb03_issue97_app149_ranking_baseline_staging_v1.validate_result` to measure the **20 draft questions** from the [Google Drive QA Decision Sheet](https://docs.google.com/document/d/1YLqD6YXa4sU_bLtcuAJ7vKvtfJ60XjuQlR6rEHNTtnc/edit), with Q19b as a separate unscored ambiguous question. This is a replaceable owner-only **measurement script**, not a new scorer, retrieval implementation, website endpoint or production scheduler.

The data path is:

`explicit operator --run-live -> existing guarded Staging question-first search -> two-source indexed-source integrity -> exact approved APP145/APP149 SHA check -> draft candidate anchor rank + currentness status -> metadata-only stdout`.

Only source IDs, Chunk IDs, physical PDF pages, original rank, status and SHA identity are emitted. **No question, evidence content, feedback, request_id, credential, Session Token or answer text** is emitted or written by this tool. It does not create logs or files, and does not call any external AI endpoint. The existing search may perform its already-approved local Staging embedding and read-only DB retrieval. This is **not** a no-IO live check: it only avoids new writes.

## Reuse, scope and safety

- Pinned GitHub `staging` base: `9667c26d229f2df5688dd5d63ee23da95aca2f7c` (PR #114).
- Approved historical *document identity only*: APP145 SHA256 `dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c`; APP149 SHA256 `a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`. The source SHA does **not** certify legal applicability or the latest version. If baseline source SHA changes, this pilot **refuses** until its reviewer contract is updated.
- Q01–Q16: primary draft candidate anchor rank (Top3/Top5). Q03 permits two already documented source candidates. Q10 marked ambiguous. Q14 is Appendix A form, Q15 Appendix B form; these should **not** be demoted as a blanket policy.
- Q17–Q20: require the **existing** `CURRENTNESS_UNVERIFIED_ABSTAIN`; it is not proof of general out-of-domain detection or insufficiency. Q19b: must remain `EVIDENCE_ONLY_REVIEW_REQUIRED`, with sufficiency **NOT_EVALUATED_AMBIGUOUS**.
- All cases must return exactly the two approved files and 16 indexed chunks with original S1–S16 identities and official PDF links. Incomplete or changed identity => refused, **no partial JSON report**.
- A DRAFT candidate anchor is **not** Gold and does not certify legal semantic answer quality, even if rank is Top1.
- Frozen Graph-aware Retrieval v1.3, source monitors M8/M9, UI/systemd, Production/main, DB schema, source registry, Drive Current, approved PDFs, Anki and external model configuration are **unchanged**.
- Draft PR / GitHub CI tests only. **No VPS deployment**, actual 20-query measured score, human professional validation, systemd restart, Source Registry update, or Production release is authorized.

## Offline test (no VPS or provider)

`python test_kb97_full_qa_observer_staging_v1.py`

## Future live Staging evaluation — requires separate explicit owner run authorization

Only after PR review / exact-head GitHub CI, run on a clean/pinned Staging checkout **without changing a running systemd service**:

`PYTHONDONTWRITEBYTECODE=1 /opt/ai-knowledge-staging/.venv/bin/python -B kb97_full_qa_observer_staging_v1.py --run-live --case-ids Q01,Q06,Q09,Q14,Q15,Q19,Q19b`

For full draft pilot use `--case-ids all`, a bounded 20-question read-only run. No default live run. **Never run this script without source SHA/checkout guards and a reviewed Staging gate.** Report is printed to the operator terminal only; do not persist raw questions or private results in GitHub/Drive.

## Acceptance gates

1. **CODED:** new module, synthetic regression, one existing CI step, and this guide; PR Draft. No existing runtime changes.
2. **CI_PASS:** exact-head Actions Validation success, including existing `test_beta_private_ui_staging_v1.py`, `test_kb03_issue97_app149_ranking_baseline_staging_v1.py`, quote and source-integrity tests.
3. **STAGING_MEASURED:** owner-read-only guarded run on actual VPS with exact code revision; record **only** source/chunk/page ranks and status. Distinguish infrastructure, missing source and relevance quality.
4. **HUMAN_GOLD_REVIEW:** independent qualified reviewer validates/corrects anchors (especially Q03/Q10/Q19b); until then results are **candidate observations**, not professional Gold.
5. Only later decide on a minimal, no-regression ranking or sufficiency **proposal**. Do not merge/activate Draft PR #100/#103/#104/#105 as a substitute.

Current status: **DRAFT_CODE_PENDING_CI / NOT_DEPLOYED / NOT_LIVE_MEASURED / GOLD_NOT_APPROVED**.
