# KB03 / Issue #97 — APP149 opt-in reading modes v0.1

Status: **Staging code candidate; browser UAT and source-version acceptance required; NO Production.**

## Why this MVP, not an automatic reranker?

The real eight-case APP149 candidate-anchor ranking baseline (PR #112, GitHub staging commit 4f29a015cca18a2199d89b1d2ac30ebd9653f6cc) found candidate Top3 = 4/8, Top5 = 7/8. Q09 body #121 (PDF p2) was global S6, while notification form #125 was global S3; Q14 and Q15 explicitly ask for forms, which ranked S5 and S4. The correct user experience cannot be a global form demotion.

**MVP rule:** keep source search, local embedding, evidence list, global ranking, S-IDs, source page URLs, and quote-preview contract absolutely unchanged. Offer a manual, labeled **document-section reading mode** rather than claiming calibrated intent detection, reranking or answer relevance.

## Architecture (replaceable display-only module)

Existing guarded question-first /api/ask -> unchanged 16 evidence entries sorted by original distance -> existing browser showResult -> **opt-in display order only** (same document objects/card DOM nodes, original S-IDs and original rank labels).

Three choices:
1. **Original global ranking (default).** All evidence in original S1, S2 ... order.
2. **APP149 body first.** APP149 PDF pages 1–3 first; remaining entries retain relative original order. This is only a document-section navigation mode, not proof of direct answerability.
3. **APP149 appendix/form pages first.** APP149 PDF pages 4–5 first; remaining entries retain relative original order. For Q14/Q15 form queries, this helps navigate to forms without claiming higher semantic accuracy.

**No automatic selection:** original view is always the default on each new query. Changing view moves existing card DOM nodes; it neither regenerates card markup nor resets typed quote text, event handlers or the server's request→S-ID mapping. All retrieved cards stay accessible. Each card always displays the source's **original global rank** and unchanged S-ID.

**Version gate / fail closed:** allow the two APP149-specific modes ONLY when the actual /api/ask response has (a) exactly one approved APP149 source with pinned source checksum a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8 (this is the reviewed beta PDF baseline, NOT a statement of present legal validity); (b) 8/8 valid APP149 chunks and complete source coverage; (c) exactly the expected chunk/page map {119:1,120:1,121:2,122:2,123:3,124:4,125:5,126:5}, unique IDs, unchanged global S order, and full overall coverage (8 or 16 depending on manual vs auto scope). Other response/source versions conservatively show only original order. SHA/page mapping is a small replaceable UI constant, not a transformation of the source.

**Safeguards:** no new HTTP route, imports, third-party JS/CDN, LLM call, database write, token storage, feedback write/read, or modified citation/quote verification. Existing latest/currentness refusal banners remain first, above cards; page citation links and Q06 explicitly selected literal quote remain intact. Accessibility: the selector has associated label and hint; source card DOM is reordered to match visual/read order, not CSS-only presentation order.

## Acceptance and regression

- Source-pinned, synthetic-only static contract and **actual pure JS helper evaluation by Node in CI**: original order preserved; Q09 body and Q14/Q15 forms prioritized in their manually chosen modes; all S IDs preserved; cloned malformed checksum/page/duplicate/missing-chunk data refuses special modes; original data never mutated.
- Existing Private Beta UI, quote-preview, Q06, source and currentness security tests unchanged and PASS. No change to Frozen Retrieval v1.3.
- CI result for exact PR head required.
- Operator performs **isolated feature worktree** checks without editing VPS Staging's current branch, and then a separate owner-run **real browser via existing loopback/SSH tunnel**, on actual pinned approved source. Browser must demonstrate: original is default, both other modes visible only for matching source, Q09 body #121 page2 can be reached early in manual body view, Q14/Q15 forms can be found early in form view, S6/S5/S4 text and source page links retain original identities, quote-preview works after switching modes, typed quote text retained, Q19/Q19b warnings unchanged, full 16 source entries available.
- Do not call manual mode a genuine semantic retrieval rank improvement; Q09 original **rank6 remains rank6**.
- Keep PR Draft until real browser UAT; no GitHub staging merge, VPS deployment or Production promotion based on CI alone.

Tracked at https://github.com/KeiLee123/ai-knowledge/issues/97 and within Beta Gate 2 https://github.com/KeiLee123/ai-knowledge/issues/60. GitHub code Source of Truth; Google Drive document Source of Truth.
