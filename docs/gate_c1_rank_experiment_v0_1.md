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

## Preferred operator gate: isolated live Staging comparison WITHOUT merging this feature
The GitHub PR must first be reviewed at an exact head commit SHA, with successful
offline CI. On the VPS, verify before/after that /opt/ai-knowledge-staging remains
on the expected clean staging SHA and Production Git remains on its expected
frozen SHA. Then clone the feature branch into a disposable, isolated /tmp
directory using the existing GitHub remote URL, WITHOUT checking it out into
the Staging working tree. Pin the clone's exact HEAD and parent to the reviewed
head and baseline. Verify the clone changes only this PR's expected five paths.

Before running the experiment, compare the following shared source files between
the isolated clone and /opt/ai-knowledge-staging with cmp -s:
beta_private_ui_staging_v1.py, beta_ask_staging_v1.py,
source_registry_v1.yaml. They must be byte-for-byte identical.
Use the Staging .venv Python with PYTHONDONTWRITEBYTECODE=1 and -B. Unset all
external model API keys. Run the offline experiment tests from the clone first.
Then invoke the clone's gate_c1_rank_trial_staging_v1.py; the unchanged
qa.build_packet() checks the REAL clean Staging checkout, approved source
SHA/integrity, Staging DB and local embedding service. Keep UI/source retrieval
code unchanged; never switch the active Staging branch or merge to run the trial.
Finally verify both worktrees and Production SHA, then remove ONLY the
disposable /tmp review clone. Do not paste remote credentials or private tokens.

The trial prints case IDs and three ranks only, no question text or evidence
excerpts. It compares original vs presentation ranking on 16 DRAFT anchors,
plus four currentness guard cases; not semantic quality or legal sufficiency.
One first-source error may make source_cohesion WORSE; form-aware can mix
Appendix A and B. The synthetic tests explicitly document both risks.
The resulting 20-case live evidence is the gate BEFORE even considering
a GitHub Staging merge.

## Release gate
Do not merge or deploy just because synthetic CI is green. First inspect Draft PR, run focused offline tests, complete GitHub CI, then use the isolated pre-merge Staging comparison above. Only after reviewing actual 20-question results should a separate merge/deploy proposal be considered. Evaluate candidate ordering versus untouched original ordering. Require professional review of Draft QA labels before making any performance or legal-quality acceptance claim. If policies fail target or harm Q14/Q15, reject/discard; no activation and no automatic fallback-to-generation.

Never modify Frozen Retrieval/Answer v1.3, Production/main, Staging/Production DB schema, Source Registry, M8/M9, Drive Current, Docling Phase B, Anki, SSH security or model permissions. P1 evidence sufficiency (Issue #99) remains independent and OFF. Work tracking: GitHub Issue #97. Google Drive QA Document SoT: https://docs.google.com/document/d/1YLqD6YXa4sU_bLtcuAJ7vKvtfJ60XjuQlR6rEHNTtnc/edit.
