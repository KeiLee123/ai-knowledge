# KB-03 / Issue #97 — APP149 real-ranking baseline v0.1

## Decision (architecture before fix)

**Goal:** measure whether real Private Beta question-first retrieval ranks APP149 procedural body above irrelevant notification forms for questions about conditions, **without** suppressing the correct appendix when the user asks for a form.

The existing private UI performs a two-source Staging search over approved APP145 + APP149 snapshots, globally sorted by cosine distance. It returns all 16 indexed chunks. **Full retrieval (16/16) measures coverage, not relevance or correct top-ranked evidence.**

This PR adds an **operator-run, strictly read-only baseline reporter** calling the existing `beta_private_ui_staging_v1.ask_evidence` function. It adds no ranking weights, model provider, new HTTP endpoint, DB schema, feedback write, original PDF processing, Production deployment or Frozen Retrieval changes.

## Candidate cases, NOT human Gold

| Case | User intent | Candidate APP149 chunk | PDF page |
|---|---|---:|---:|
| Q09 | temporary AS absence procedure | 121 | 2 |
| Q10 | AS not present (ambiguous: physical vs unable to act) | 121 | 2 |
| Q11 | replacement AS eligibility | 122 | 2 |
| Q12 | AS absent over 30 days | 123 | 3 |
| Q13 | two AS for one submission | 120 | 1 |
| Q14 | change AS Appendix A **form** | 124 | 4 |
| Q15 | temporary replacement Appendix B **form** | 125 | 5 |
| Q16 | AS absence over 30 days (English) | 123 | 3 |

These anchors were already proposed in the [canonical Natural-Language QA Draft](https://docs.google.com/document/d/1YLqD6YXa4sU_bLtcuAJ7vKvtfJ60XjuQlR6rEHNTtnc/edit). A professional reviewer has **not** turned them into Gold. Q09 may also need chunk122, and Q14/Q15 need relevant body context. Do not equate `candidate_hit_top3` with a legally correct answer.

The reporter measures: global `first_anchor_rank`, candidate hit in Top3/Top5, first APP149 form rank, whether a form outranks an APP149 body candidate (not a form query), and exact global Top5 source/chunk/page metadata. Q14 and Q15 serve as controls to prevent a proposed universal form-demotion rule.

## Run safety and operator acceptance

**Do not run until GitHub PR exact-head CI and isolated synthetic tests PASS.** The program is intended for a guarded, clean, pinned Staging checkout and an isolated PR worktree, never Production.

Commands below are runbook examples, **not** authorization to change live status or deploy:

```bash
# from a safe isolated feature worktree containing this script
PYTHONDONTWRITEBYTECODE=1 \
/opt/ai-knowledge-staging/.venv/bin/python -B \
  kb03_issue97_app149_ranking_baseline_staging_v1.py --run-live

# After checking first four cases, all draft APP149 cases, still read-only:
PYTHONDONTWRITEBYTECODE=1 \
/opt/ai-knowledge-staging/.venv/bin/python -B \
  kb03_issue97_app149_ranking_baseline_staging_v1.py \
  --run-live --case-ids Q09,Q10,Q11,Q12,Q13,Q14,Q15,Q16
```

`--run-live` is mandatory. Live baseline requests use only the existing Staging database and local embedding endpoint behind the existing clean Staging checkout/source SHA/integrity checks. No AI draft, API key, feedback read/write, disk artifact or production access is needed. Output is one JSON object printed to the private terminal; it intentionally excludes request IDs, document text, full user question strings and quotes. Never copy raw feedback comments or tokens.

**Fail closed:** any unexpected source, partial coverage, source chunk/page identity change, URL identity conflict, duplicate item or unknown case rejects the baseline. A correct chunk anywhere in 16/16 is **not** Top3/Top5 success unless its rank qualifies. If the controlled source set changes, update this contract only after independent validation.

**Acceptance gates:**
- 8 synthetic-only test cases, including body vs form controls, missing anchor, inaccurate page, unexpected source, partial coverage, duplicate IDs and no-leak.
- Exact-head GitHub CI PASS.
- Operator isolated VPS synthetic suite PASS.
- Operator actual Staging baseline Q09/Q11/Q14/Q15, each globally ranked across both sources and reported with anchored chunk/page; capture real observed metrics *without* calling them Gold.
- Analyze whether a separate display/selection adapter is justified. No ranking code change or Staging deployment as part of baseline.
- Require separate PR and actual browser QA before claiming relevance improvement.

Related tracking: [Issue #97](https://github.com/KeiLee123/ai-knowledge/issues/97), [Gate2 #60](https://github.com/KeiLee123/ai-knowledge/issues/60). GitHub code Source of Truth; Google Drive native Docs governance Source of Truth. Production and frozen Retrieval v1.3 are unchanged.
