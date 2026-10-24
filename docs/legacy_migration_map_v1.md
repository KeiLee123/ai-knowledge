# Jason OS Knowledge — Legacy Migration Map v1

Status: MIGRATION PLAN  
Date: 2026-10-24

## Principle

Do not copy every VPS-only file back into GitHub.

For each legacy or local artifact:

```text
still required?
  |
  +-- no  -> archive / retire
  |
  +-- yes -> architecture still valid?
               |
               +-- yes -> keep + test + document
               |
               +-- no  -> replace behind regression tests
```

Cleanup is intentionally last.

## Keep / freeze

### Retrieval core

Keep and freeze:

- `answer_knowledge.py`
- `ask_knowledge.py`
- `graph_search_v1.py`
- `hybrid_search_v3.py`
- `query_normalizer.py`
- `query_subject_resolver_v1.py`
- `document_scope_resolver_v1.py`
- `structural_completion_v1.py`
- `section_evidence_resolver_v1.py`

Reason: active Production retrieval/answer baseline.

### HKeL current parser

Keep:

- `ingest_hkel.py`
- `parse_hkel_xml_v5.py`
- `legislation_registry.yaml`

Treat HKeL as a specialized legal adapter until a staging-first replacement is proven.

### Multimodal v2 foundation

Keep:

- `extract_document_v2.py`
- `route_document_v2.py`
- `augment_ocr_v2.py`
- `augment_vision_v2.py`
- `build_multimodal_chunks_v2.py`
- `attach_source_pages_v2.py`
- `orchestrate_document_v2.py`
- `run_multimodal_canary_v2.py`
- `validate_staging_retrieval_v2.py`
- `benchmark_multimodal_retrieval_v2.py`

Extend rather than replace.

### Production Promotion v1

Keep frozen:

- APP-145 Production Promotion v1 stack
- its regression tests
- its release evidence

Do not use it as the template for every new source.

## Extend

### Structured table evidence

Status: COMPLETE in GitHub `staging` / CI VERIFIED; VPS deployment pending.

Implemented:

- emit `structured_table` evidence;
- preserve page number, bbox, table index, row/column counts and detection strategy;
- treat source-grounded structured tables as primary table evidence;
- add regression coverage for serialization, metadata, summary counts and ingestion role;
- preserve existing native/OCR/Vision behavior.

### Official Source Processing v1

Extend the current multimodal branch from:

```text
MULTIMODAL_STAGING_HANDOFF_REQUIRED
```

to:

```text
multimodal evidence build
-> Staging write
-> multimodal retrieval validation
-> READY_FOR_PRODUCTION_REVIEW
```

Use existing Multimodal v2 modules.

### Generic Production Promotion v2

Evolve the contract from text-specific:

```text
canonical_text_release_v2
required_route = legacy-v1
```

toward profile-based release artifacts.

Do not create separate full promotion engines for each modality.

## Retire as operational entrypoints

### `ingest_document.py`

Classification:

- legacy;
- generic;
- direct Production writer;
- no modern Staging-first lifecycle.

Target:

- keep temporarily for compatibility;
- stop presenting it as the default ingestion command;
- disable/remove its user-facing wrapper only after replacement operational paths are proven.

### `ingest_gdrive_auto.py`

Classification:

- legacy Google Drive -> Production path;
- ultimately invokes the generic direct Production writer.

Target:

- retire as an approved Production workflow;
- retain only until callers are reconciled.

### `orchestrate_document_v2.py --write`

Classification:

- low-level engine;
- generic write capability.

Target:

- keep as an internal engine;
- approved operational entrypoints should use environment-specific guards;
- do not expose direct Production use as the standard workflow.

### `poc_stress_ingest.py`

Classification:

- experimental;
- direct Production write capable;
- hard-coded synthetic benchmark document.

Target:

- isolate or retire from active operational surfaces;
- never treat it as an approved Production command.

## Legacy implementations

Mark historical / legacy:

- `hybrid_search.py`
- `hybrid_search_v2.py`
- `parse_hkel_xml.py`
- `parse_hkel_xml_v2.py`
- `parse_hkel_xml_v3.py`
- `parse_hkel_xml_v4.py`
- old audit variants tied to old parser versions

Do not delete until dependency checks and regression coverage confirm they are unused.

## Pre-Git backups

Production VPS historical `pre-*` / backup files are not active source code.

Policy:

- keep the VPS audit snapshot in Google Drive;
- do not copy historical variants back into active Git branches;
- if an old variant contains a missing capability, port that capability into current code with tests instead of restoring the historical file.

## CLI wrappers

### Keep

Safe/read-oriented operational commands:

- `answer-knowledge`
- `ask-knowledge`
- `graph-search`
- `classify-knowledge`
- `classify-gdrive`
- `validate-taxonomy`
- `law-info`

### Temporary / specialized

- `ingest-hkel`

Retain until HKeL has a validated staging-first lifecycle.

### Retire

- `ingest-knowledge`
- `ingest-gdrive-auto`

Retire only after replacement paths are live-verified.

### Rework

- `law-watch`

Current implementation provides bootstrap/baseline only; the command name suggests a continuous watcher that does not yet exist.

## Deployment as code

Target repository layout, introduced gradually rather than via a large refactor:

```text
ops/
  systemd/
  cli/
  install/
```

The goal is that a VPS can be reconstructed from GitHub definitions without manually recreating wrappers.

Do not move frozen Python modules into a new `src/` hierarchy merely for aesthetics.

## Migration gates

Every retirement requires:

1. replacement path identified;
2. regression tests passing;
3. Staging live verification;
4. operational wrapper/caller reconciliation;
5. Production read-only verification where relevant;
6. explicit approval before Production-impacting changes;
7. post-change validation.

## Ordered migration

### M0 — Governance freeze

Add architecture, capability and migration documents.

Production impact: none.

### M1 — Structured table evidence

Status: COMPLETE in GitHub `staging` / CI VERIFIED.

First-class table evidence and regression tests are implemented.

VPS deployment: pending.

Production impact: none until separately promoted.

### M2 — Multimodal Staging close-loop

Integrate existing v2 canary/write/validation path with official-source processing.

Production impact: none.

### M3 — Release artifact profiles

Generalize Generic Production Promotion v2 contract without changing APP-145 v1.

Production impact: none.

### M4 — VPS Staging verification

Deploy and validate the consolidated lifecycle on VPS Staging.

Production impact: none.

### M5 — APP-149 generic text proof

Use explicit Production gates and human authorization.

### M6 — Multimodal generic promotion proof

Qualify a multimodal release profile through the same generic promotion engine.

### M7 — CLI deployment reconciliation

Add reproducible safe CLI definitions and retire old direct-Production wrappers.

### M8 — Monitoring schedule

Install scheduled source monitoring only after end-to-end lifecycle behavior is verified.

### M9 — HKeL modernization

Add actual change-watch behavior and eventually move HKeL ingestion toward Staging-first release control.

### M10 — Cleanup

Remove or archive obsolete Production root files only after all prior gates pass.