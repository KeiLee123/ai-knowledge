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
