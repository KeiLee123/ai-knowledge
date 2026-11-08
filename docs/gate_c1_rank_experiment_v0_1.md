# Gate C-1 — Non-Active In-Memory Re-ranking Experiment v0.1

Status: DRAFT PR prototype only; NO runtime/UI integration or VPS deployment.

## Architecture
User question -> existing approved APP145/APP149 -> unchanged Staging evidence retrieval -> pure experiment strategies -> sanitized original vs candidate rank report.
Original evidence, IDs, contents, page URLs, source SHA validation and API output are NOT changed. This code is never imported by the Private Beta UI.

## Three policies
- original: no changes.
- source_cohesion: group candidates by first seen source while keeping within-source original rank. This helps diagnose cross-source noise but DOES NOT solve Q09 by itself.
- source_cohesion_form_aware: additionally try a small structural heuristic. For form-location questions (表格/表單/附錄/form/appendix/template), promote form-like chunks; otherwise present plain paragraphs first. It looks for appendix labels, notification-form headings and blank-fill underscores. This is an uncalibrated probe, not reliable bilingual legal-intent understanding.

Each policy emits only source/chunk/page plus original_rank and candidate_rank. No full excerpts, raw question, secrets, legal conclusions, probability/confidence score or local files. Input unchanged; all 16 remain available in the original results.

## Acceptance boundaries
Existing user-supplied Staging baseline at commit 099094e04bc0ea46fba3eee2cba9050d1a209e7f: Q01/Q05/Q09 target original rank 6; 16 in-scope DRAFT anchors Top3=7/16, Top5=13/16; currentness 4/4 PASS. Target 13/16 Top3 and 15/16 Top5 are proposals, not achieved and not Gold. Q14/Q15 specifically check that appendix requests are not blindly penalized. Q10 ambiguity requires professional review. Mixed-document/source and out-of-scope detection are NOT proven.

## Run offline (any safe checkout of this feature branch)
    PYTHONDONTWRITEBYTECODE=1 python3 -B test_gate_c1_rank_experiment_v1.py

## Run real Staging comparison (ONLY after separate Draft PR review, CI pass, approved merge into staging, VPS clean Staging sync)
    cd /opt/ai-knowledge-staging
    env -u JASON_BETA_LLM_API_KEY -u DEEPSEEK_API_KEY -u OPENAI_API_KEY PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B gate_c1_rank_trial_staging_v1.py

The trial is executed manually, read-only. The existing qa.build_packet guard requires clean staging branch and healthy approved source SHA/integrity, Staging DB and local embeddings. It prints case IDs and three ranks only, no question text or evidence excerpts. Abort on any integrity/currentness regression. Verify Production Git HEAD separately before and after operator run.

## Release gate
Do not merge or deploy just because synthetic CI is green. First inspect Draft PR, run focused offline tests, complete GitHub CI, then separately authorize Staging sync and 20-question real comparison. Evaluate candidate ordering versus untouched original ordering. Require professional review of Draft QA labels before making any performance or legal-quality acceptance claim. If policies fail target or harm Q14/Q15, reject/discard; no activation and no automatic fallback-to-generation.

Never modify Frozen Retrieval/Answer v1.3, Production/main, Staging/Production DB schema, Source Registry, M8/M9, Drive Current, Docling Phase B, Anki, SSH security or model permissions. P1 evidence sufficiency (Issue #99) remains independent and OFF. Work tracking: GitHub Issue #97. Google Drive QA Document SoT: https://docs.google.com/document/d/1YLqD6YXa4sU_bLtcuAJ7vKvtfJ60XjuQlR6rEHNTtnc/edit.
