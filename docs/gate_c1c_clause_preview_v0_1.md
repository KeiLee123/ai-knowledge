# Gate C-1c — Human-Intent Clause Preview v0.1

Status: DRAFT, OFFLINE-ONLY experiment. No Private Beta integration, real-corpus reranking or legal/currentness authorization.
Code Source of Truth: https://github.com/KeiLee123/ai-knowledge
QA Document Source of Truth: https://docs.google.com/document/d/1YLqD6YXa4sU_bLtcuAJ7vKvtfJ60XjuQlR6rEHNTtnc/edit

## Architecture first
Original verified Staging evidence[] -> metadata extraction (future) -> explicit HUMAN-SUPPLIED intent code (only review scenarios) -> pure preview by provisional clause anchors -> independent no-regression / professional review (not automated here). No question->intent classifier exists.
Input is a sanitized rank/identity list (S-ID, source ID, chunk ID, PDF page, official URL) plus two source checksums. No raw user question, quoted paragraph, token, embeddings or database connection. Original and proposed presentation rank are both returned, and all items remain addressable by unchanged S IDs.

## Draft clause purpose catalog — NOT Gold
APP145: #115 enforcement jurisdiction, #113 New Territories / legacy exception, #116 difficulties/compliance, #117 drawings submission.
APP149: #121 temporary absence, #122 substitute eligibility, #123 absence >30 days, #124 Appendix A change-AS notice, #125 Appendix B temporary nomination form. Secondary context examples are draft only.
Catalog pins the historical two-source checksum identifiers from existing source records. Matching SHA proves only identity with those historical editions, not latest validity, legal answerability, or expert approval.

## Hard boundaries
- preview_manual_intent needs an explicit human intent code; unknown or mixed/ambiguous input leaves original rank unchanged.
- Absent target chunk or source SHA mismatch leaves original order unchanged.
- Malformed or untrusted identity/page/url or extra raw content fields are refused.
- Proposed ordering contains only metadata; preview_only=True, release_authorized=False, professional_gold_approved=False, currentness/sufficiency=False, runtime_wired=False.
- No import/wiring into current Beta API or UI; no changes to Frozen Retrieval, DB, indexes, official source registry or approved source SHA.
- The nine intent labels must not be converted into a general legal dictionary or current-law declaration before independent professional review.

## Offline tests (synthetic, not real ranking accuracy)
PYTHONDONTWRITEBYTECODE=1 python3 -B test_gate_c1c_clause_preview_v1.py
Seven synthetic contract tests cover Q09-like temporary AS absence, Appendix A/B difference, stable original top result, ambiguous fallback, SHA drift, malformed metadata and no runtime side effects.
Sample preview can move APP149 #121 from synthetic original rank six to first IF an expert manually supplies the intent; this does NOT mean automatic retrieval of Q09 has improved.

## Next acceptance dependencies
1. Independent professional review of source clauses/anchors and adequacy for each Q01–Q20 (plus held-out Cantonese/Chinese/English questions); mark Gold separately.
2. Develop/validate a separate conservative question-intent resolver; on ambiguity, use original order. No model/API provider activation without approval.
3. Use PR #104's No-Regression contract against actual live Staging 16+4, safeguarding Q04/Q06/Q07/Q09/Q14/Q15, citation identity, existing P0 insufficiency warning and currentness refusal 4/4.
4. Only consider guarded Staging activation with separately approved PR after qualitative and numeric targets pass. Source currentness / general answer sufficiency tracked separately (Issue #99).

Historical Gate C baseline: original Top3 7/16, Top5 13/16 Draft anchors; target 13/16 Top3 and 15/16 Top5 proposed only. Neither numeric improvement nor code/CI success is a legal quality claim.
Related: rejected C1 PR #103 and standalone C1b QA Draft PR #104 remain unmerged. Do not alter Production, Frozen v1.3, M8/M9, Anki or official source baseline.
