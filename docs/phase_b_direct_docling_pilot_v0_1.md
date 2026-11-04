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
