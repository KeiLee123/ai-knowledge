# Gate C-1b — No-Regression Acceptance Contract v0.1

Status: isolated offline evaluator only, no rank model, no UI/API integration, no release approval.
Code Source of Truth: https://github.com/KeiLee123/ai-knowledge
Document Source of Truth: https://docs.google.com/document/d/1YLqD6YXa4sU_bLtcuAJ7vKvtfJ60XjuQlR6rEHNTtnc/edit
Tracked in GitHub #97; original rejected experiment Draft PR #103 left unchanged.

## Architecture before implementation

Pinned operator-observed rank-only snapshot (16 draft candidate anchors, original/C1 policies)
-> pure evaluator -> named reasons for hard regressions + numeric target status.
No database access, model, SSH, official PDF fetch, personal questions, token, source chunk text, or runtime writes.
This does NOT score semantic correctness, true clause completeness, PDF citation integrity, currentness, or professional Gold.

## Rules — hard experimental no-harm

H1: An anchor at original rank <=5 cannot move below rank 5.
H2: An anchor originally at rank #1 cannot move below rank 3.
H3: Exactly 16 pinned Q01–Q16 unique case IDs, integer ranks 1–16, unchanged operator baseline; incomplete/invalid/duplicate/unpinned tables fail closed.
H4: For any future LIVE candidate, currentness Q17–Q20 must remain 4/4 PASS, integrity/source SHA/official PDF page links, P0 sufficiency-unverified copy, all original evidence IDs, authentication and no-model egress must be checked separately. This offline checker explicitly reports those checks as NOT TESTED.
N1: Q09 candidate anchor APP149 #121 should move into Top5 without any hard regression.
N2: Proposed numerical targets Top3 >= 13/16; Top5 >= 15/16. Still based on DRAFT anchors, not Gold; do not claim legal answer accuracy.
N3: No release without independent professional Gold labels, multi-clause and ambiguous question review, held-out questions, and real Staging user QA.

## Verified C1 data replay (operator supplied; no new retrieval)

Original Top3 7/16 Top5 13/16: no_harm=true but target HOLD.
Source Cohesion Top3 8/16 Top5 14/16: Q04 rank 4 -> 11, HARD REJECT.
Form-aware Top3 9/16 Top5 12/16: Q04 4 -> 10, Q06 1 -> 6, Q07 1 -> 6, Q13 1 -> 4, Q09 6 -> 7, HARD REJECT.
Q14/Q15 are form-location queries, so a general appendix penalty is prohibited.

Only the first draft-candidate anchor rank per case was recorded, not whether combined passages truly answer the user's question.
These 16 cases can reveal regressions; they are not evidence that a better ranker will generalize. Future design must use independently reviewed and held-out questions.

## Local and CI tests

PYTHONDONTWRITEBYTECODE=1 python3 -B test_gate_c1b_no_regression_v1.py

The test replays all three observed rank series and intentionally proves BOTH C1 policies fail the hard gate; also tests a fictitious numerically-perfect ranker still cannot be released, and malformed/forged ranks are refused.
One additional step is registered in the existing Validation CI workflow. This is not an active Staging/Production deploy.

## Next separate design (no implementation authorization)

A replaceable, disabled-by-default, clause-/intent-aware candidate presentation adapter evaluated against human-reviewed APP145/APP149 Gold; no first-source bias, global appendix demotion, source-page heuristics, keyword-only legal judgment or unsupported positive sufficiency claim. Maintain full original evidence and a safe fallback to unchanged order. Review proposed gains AND harmed cases before any merge, VPS deployment or product activation.

Frozen Retrieval v1.3, Production/main, Staging DB and app, source registry, M8/M9, Anki, P1 insufficiency Issue #99 and model egress remain unchanged.
