# Phase B: Direct Official Docling MVP Pilot v0.1

Status: EXPERIMENT ONLY — not Staging-accepted, no deployment authorization.

## Architecture
Public SHA-pinned APP149.pdf -> preflight -> official Docling CPU Python API -> metadata-only JSON report -> review.
No Celery, Redis, PostgreSQL, writer, scheduler, Source Registry change, Anki write, network service or Production dependency.

The parser is the upstream Docling package, not custom parsing logic. GitHub is code SoT, Google Drive is official raw document SoT. The local model cache is temporary and not a new authoritative store.

Pinned public source: APP149.pdf, 25,520 bytes, 5 pages,
SHA256 a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8.
The current official version is NOT inferred from this pinned historical fixture. Any changed official bytes must HOLD, not silently approve.

## Off-VPS first: one-shot public smoke
A feature-only GitHub Actions workflow, phase-b-direct-docling-once.yml, installs the previously reviewed CPU Torch wheel pair and docling==2.146.0, fetches a public BD APP149 PDF, enforces pinned SHA, and calls ops/phase_b_direct_docling_pilot.py.
It runs on an ephemeral runner and uploads only a short metadata JSON. No PDF, parsed text, weights, credentials or Docker images are uploaded. Default Docling may fetch public model weights on first use; remote *document-processing services* and plugins remain disabled.

This is intentionally not a VPS deployment. GitHub validation and an off-VPS parser smoke cannot be relabeled STAGING_VERIFIED.

## Later Staging pilot, after VPS preflight
The same script can be run in a separately approved, disposable Python 3.12 CPU-only environment with a local pinned APP149 fixture. Do not pip-install into either shared /opt/ai-knowledge or /opt/ai-knowledge-staging application venv. No database, Docker socket, Production mounts, M8/M9 changes or ingress ports.

Illustrative command after operator preflight:

    mkdir -p -m 700 /tmp/phase-b-direct-docling-output
    python ops/phase_b_direct_docling_pilot.py /tmp/phase-b-direct-docling-fixture/APP149.pdf \
        --report /tmp/phase-b-direct-docling-output/report.json

The optional --offline flag forbids automatic model downloads (requires an existing cache). Without it, outbound model fetches must be explicitly permitted by sandbox policy. GitHub runner enforces a 240 second process timeout and Docling has 120 seconds document_timeout, but no evidence yet proves the actual VPS 3GiB limit. Peak process RSS is not the same as cgroup peak memory.

## Acceptance and stopping
Limited mechanical PASS requires the pinned SHA, 5 physical pages, official Docling SUCCESS, five returned page IDs, nonambiguous item provenance and text on each page. Table numerical accuracy, reading-order semantics, bbox fidelity, official revision/current-law status, DB ingestion and Product Beta are NOT validated.
Source version/SHA conflict, OOM, timeout, model API/runtime issue, missing page or ambiguous provenance => AUTO_HOLD and stop only this disposable experiment.

PR #95 remains Draft, unmerged, and retains its optional hardened Celery/Redis/model-bundle design. The MVP does not require a model vault first. Next gate after inspecting the real GitHub report: separately approved bounded VPS Staging smoke and native-text/provenance comparison. No Production, main, Frozen Retrieval, M8/M9, Drive Current, PostgreSQL or Anki mutation.

Official sources:
https://github.com/docling-project/docling
https://docling-project.github.io/docling/usage/advanced_options/
https://docling-project.github.io/docling/reference/pipeline_options/



## 2026-11-05 — ARM64 direct-parser experiment: decision / HOLD

Operator-provided VPS read-only preflight: 2 vCPU **aarch64** ARM64, Python
3.12.3; 11 GiB RAM total, ~8.1 GiB available at that check, **no swap**,
81 GiB free disk; Production checkout
`daacbb4557e17790fdef18e492d5b83f4fcf7a23`, Staging checkout
`3f1ac00590c8f6dc1e73cc581d4b1aa295498bcd`. Host capacity is a
plausible first signal but does not establish Docker cgroup headroom,
multi-service interference or real VPS parser behavior.

Real native x86_64 and ARM64 GitHub Actions pipeline, both processing the
**same** pinned 25,520-byte BD APP149 PDF with the same SHA256, completed
mechanical PASS on exact feature HEAD
`61133fcc12201cf0613032016f35fefb471e9c48`:
https://github.com/KeiLee123/ai-knowledge/actions/runs/41883338734 .
Same-head repo Validation also PASS:
https://github.com/KeiLee123/ai-knowledge/actions/runs/41883328362 .

Critical cross-architecture difference in metadata-only reports:

| Field | x86_64 | ARM64 |
|---|---:|---:|
| Docling pages | 5/5 | 5/5 |
| Page/provenance HOLD items | 0 | 0 |
| Direct `doc.tables` count | **3** | **0** |
| `TableItem` class count | **3** | **0** |
| Earlier `item.label == table` count | **3** | **0** |
| Non-table text characters in earlier paired run | 10,057 | 10,179 |
| Peak Python process RSS in earlier paired run | ~1.822 GiB | ~1.646 GiB |
| PyTorch version | 2.9.1+cpu (CPU index) | 2.9.1 (PyPI ARM64) |

A targeted second **metadata-only** diagnostic inspected the actual Docling
document table collection, item classes and labels (not merely the report
counter) on both architectures:
https://github.com/KeiLee123/ai-knowledge/actions/runs/41884246605 .
Again both conversion status SUCCESS, both Docling 2.146.0,
docling-core 2.106.0, docling-ibm-models 4.0.4. x86_64 returned 3 actual
TableItems, ARM64 returned 0; therefore the discrepancy is **not** caused
solely by a typo in the pilot's `table_count` condition. This does not
establish which platform's table detection is correct; visually verified
ground truth and model asset fingerprints were not collected.

**Separate acceptance gates:**
- Official Docling on ARM64, off-VPS, pinned PDF, bounded 5 pages:
  **RUNTIME_MECHANICAL_PASS_LIMITED**.
- Cross-architecture table content / layout equivalence:
  **AUTO_HOLD / NOT VERIFIED**.
- VPS Staging Docling install/inference, model integrity and 3-GiB
  container headroom: **NOT VERIFIED**.
- Existing ingestion/quality-gate compatibility, DB integration, official
  edition currentness, semantic/numerical accuracy, Beta and Production:
  **NOT VERIFIED / NO PROMOTION**.

**Decision: Do not deploy or connect ARM64 Docling to Knowledge Brain
ingestion on the present evidence.** Prefer the existing vetted document
pipeline for Beta. Keep Docling as a *replaceable optional* parser candidate
and PR #96 as Draft. PR #95 remains separate Draft. There is no need to add
Celery, Redis, model vault or VPS setup to investigate this difference.
If Docling is later resumed, the **one** justified quality gate is a
bounded human-verified source-page table-layout comparison plus an
x86/ARM model-file/version identity check; make that a prerequisite before
any Staging parser adoption. CI green for mechanical conversion must never
be construed as table quality PASS.

The GitHub Actions metadata ZIPs are ephemeral (three-day retention);
durable non-sensitive evidence is this file, the PR discussion and Google
Drive Knowledge Brain Development State. No original PDF text or model
weights were committed.



## 2026-11-05 — Pinned PDF visual inspection + dual-architecture model SHA audit

**Status: EXPERIMENT OBSERVED / PRODUCTION & VPS STAGING STILL HOLD.**

Reused an existing approved official APP149.pdf from connected Knowledge
Brain Google Drive (Drive file ID
`1D8e2EWeR9ocs8dXzQPjEtmrTc8HwOBPu`), downloaded complete raw
25,520-byte PDF and independently recalculated SHA256
`a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`.
Thus the PDF rendered here was byte-for-byte the fixture in GitHub Actions.
Rendered five pages at 140 dpi and inspected visual layout; no OCR needed.

Observed by page (not a certified specialist gold annotation):
- Page 1: official three-column page header and continuous narrative;
  **no conventional numerical data table**. Four vector drawing paths.
- Pages 2–3: prose; zero vector paths.
- Page 4, Appendix A: fillable-looking paper form for change of authorized
  signatory, two rows of three MW submission-number input groups, signature
  lines and blank fields; 102 vector paths.
- Page 5, Appendix B: related temporary AS notification form, two rows
  of three boxed MW input groups, signature and personal-information
  blank fields; 102 vector paths.
- Therefore **three x86 TableItems are not evidence of correct data-table
  extraction**. Page 1 may be page-header misclassification; pages 4–5
  are forms with tabular-looking field boxes rather than demonstrated
  business data tables. Conversely zero ARM TableItems is not proof
  of form-layout preservation. Our original cross-architecture
  table-count-only quality criterion was insufficient.

**Independent model fingerprint test**: kept the original exact-SHA
APP149 conversion with one extra **post-conversion, read-only**
`~/.cache/docling/models` and `~/.cache/huggingface/hub` public-model
cache hash inventory in the existing one-shot feature workflow.
[Both native GitHub job runs #41886453033](https://github.com/KeiLee123/ai-knowledge/actions/runs/41886453033)
COMPLETED SUCCESS on code head
`ab7caa503cf6508a33be07710b7033265a3fc311`. The same-head
[Validation #41886465245](https://github.com/KeiLee123/ai-knowledge/actions/runs/41886465245)
also COMPLETED SUCCESS. Downloaded both metadata-only ZIP artifacts and
independently compared every entry. Both environments reported ten
model-related cache files under Hugging Face cache, total
**529,890,792 bytes per platform**; **10 of 10 same relative paths,
file sizes, model revisions and SHA256 hashes**. Compared cached assets
include the Layout Heron model and TableFormer fast/accurate weights
and configs; raw weights were *not* uploaded. The Docling cache
directory contained no inventory matches on either run; that is
consistent but cannot prove every installed-package resource or
inference backend is byte-identical.

Matched model-cache bytes **rule out a mismatch among these ten
downloaded model assets as the cause** of observed `TableItem` output
variation; they do **not** prove identical PyTorch/CPU kernels,
transitive dependency implementations, postprocessing numerical
behavior, or every model artifact outside these cache roots.
x86 Torch 2.9.1+cpu and ARM PyPI Torch 2.9.1 differ by wheel/CPU
architecture. Do not assert the *root cause* has been proven.

As a confirmation of prior results, this model audit again returned
`docling_conversion_status=success` on all five pages for both
platforms, yet x86 `document.tables=3`, ARM `document.tables=0`
with both marked `MECHANICAL_PILOT_PASS_LIMITED`. The report
must not be used as a semantic quality certification.

**Updated acceptance contract:** For APP149 and other official
blank-forms/notice templates, replace any standalone "number of
TableItems == expected" verdict with an independent form-layout
evaluation: preserve six MW submission-number fields per appendix,
field-label relationships, page addressability, and signature areas.
Do not automatically mark either parser as superior without
representative form-structure evaluation. Routine prose and structured
forms may require different adapters/quality guards.
Existing Document v2 remains the Beta path and all
frozen/Production/DB/timer boundaries remain untouched.

**Next** if Docling remains a future candidate: investigate the
architecture-dependent model inference / postprocessing under controlled
equal-model/equal-input conditions, and validate a form-field mapping
against the rendered pages. This is an optional, narrowly scoped
quality R&D gate, not a reason to install Celery/Redis/model vault
or touch VPS now. PR #96 and PR #95 remain separate Drafts.


## 2026-11-05 — APP149 Appendix A/B form-anchor pilot: bounded observation

GitHub **code HEAD** `a58dbb122fd9de53bf0b7f8e2703d2576277b7a9` uses
two additive read-only files:
- `ops/phase_b_app149_form_probe.py`: PDF-native gold checks on pinned
  Appendices A/B: exactly six printed "MW" anchors in two rows x three
  columns, page-specific reference x/y coordinates (tolerance 1.5 PDF
  points), three signature labels and at least 100 vector paths.
  This checks the *paper form source*, not interpretation accuracy.
- `ops/phase_b_direct_docling_pilot.py`: during existing official Docling
  conversion, records per-page MW and signature text token counts,
  candidate item bboxes and how many of the six known native anchor
  points are inside MW-bearing item regions. It publishes **counts and
  coverage only**; no document contents or model weights.

Exact-code-head [dual-native real-public-PDF run #41891835929](https://github.com/KeiLee123/ai-knowledge/actions/runs/41891835929)
**COMPLETED SUCCESS** in GitHub Actions x86_64 and ARM64.
[Same-head Validation #41891845833](https://github.com/KeiLee123/ai-knowledge/actions/runs/41891845833)
also **COMPLETED SUCCESS**. Downloaded and independently checked the
sanitized JSON artifacts, x86 artifact #13353217991 and ARM artifact
#13354336441 (ephemeral three-day retention), both reports showed
`MECHANICAL_PILOT_PASS_LIMITED` plus separate
`AUTO_HOLD_FORM_FIELD_RELATIONSHIPS_NOT_CERTIFIED`.

| Per page | Source p4 / p5 | x86_64 p4 / p5 | ARM64 p4 / p5 |
|---|---|---|---|
| Printed MW anchors | 6 / 6 | — | — |
| Native reference shape 2 x 3 | yes / yes | — | — |
| MW tokens in Docling | — | 6 / 6 | 6 / 6 |
| Printed MW positions covered by MW-bearing Docling element bboxes | — | 6 / 6 | 6 / 6 |
| MW-bearing Docling **items** | — | 1 / 1 | 6 / 6 |
| Signature labels | 3 / 3 | 3 / 3 | 3 / 3 |
| `docling.document.tables` (whole PDF) | not a ground-truth data-table target | 3 | 0 |

Nuance: **x86 groups the six MW anchors into a single element per page**
(the earlier TableItem interpretation), whereas **ARM has six MW-bearing
elements per page**. So raw TableItem count is not a suitable
cross-platform quality KPI for these public paper forms. Identical
source PDF, previously matched 10/10 cached model SHA256 files, and
this new per-anchor evidence do **not** prove the exact reason for
different layout grouping. Nor does rough item-box coverage prove
the printed blank boxes remain individually addressable, signature
roles are correctly associated, or all reading order is valid.

**Acceptance decision**: pinned-source paper-layout reference
`PASS`; both native official Docling 5-page conversion and public
MW text-anchor/provenance-region coverage `PASS_LIMITED`; **both
platforms' semantic form-field mapping `AUTO_HOLD_NOT_CERTIFIED`**.
No requirement to make ARM return three TableItems. This probe is
experimental and deliberately leaves the trusted Document v2 routing,
VPS Staging, DB Writer, Frozen v1.3, Source Registry, M8/M9, Anki,
Google Drive Current and Production unchanged. PR #96 remains Draft;
PR #95 remains a separate Draft. The next decision is whether the Beta
actually needs field-level form understanding; if not, do not spend
additional engineering on this optional Docling R&D gate.
