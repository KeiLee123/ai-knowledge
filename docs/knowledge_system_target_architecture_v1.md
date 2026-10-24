# Jason OS Knowledge System — Target Architecture v1

Status: ARCHITECTURE FREEZE / STAGING GOVERNANCE  
Date: 2026-10-24

## Purpose

This document records the target architecture after reconciling:

- the live Production VPS snapshot;
- the live Staging VPS snapshot;
- GitHub `main`;
- GitHub `staging`;
- pre-Git historical files;
- operational wrappers and systemd units.

It is an architecture and migration baseline. It does not authorize Production writes.

## Source of truth

- GitHub is the code, tests, deployment-definition and release-contract Source of Truth.
- Google Drive is the canonical document Source of Truth.
- Production and Staging remain separate environments.
- Frozen Production layers are not modified without regression coverage.

## Target architecture

```text
SOURCE LAYER
    |
    +-- Official PDF Adapter
    +-- DOCX / Text Adapter
    +-- HKeL Legal Adapter
    |
    v
Source Registry
    |
    v
Monitor / Baseline
    |
    v
Google Drive Canonical Artifact
    |
    v
Router
    |
    +-- legacy-v1 / text evidence builder
    +-- multimodal-v2 evidence builder
    |
    v
Normalized Evidence
    |
    +-- native_text
    +-- ocr_text
    +-- fused_text
    +-- visual_understanding
    +-- structured_table
    |
    v
STAGING DB
    |
    v
Validation
    |
    v
VALIDATED RELEASE
    |
    v
Release Artifact
    |
    v
Git-controlled Release Contract
    |
    v
Human Approval
    |
    v
Generic Production Promotion
    |
    v
PRODUCTION DB
    |
    v
Retrieval / Graph Brain v1.3  [FROZEN]
    |
    +-- Answer layer
    +-- Learning / Anki
```

## Architectural boundaries

### 1. Source adapters

Source-specific acquisition/parsing logic may differ.

Examples:

- Official PDFs use the document-manifest / routing pipeline.
- HKeL uses the legal XML parser and statutory-reference semantics.
- Future DOCX / text sources may use a separate adapter.

Adapters should converge on normalized evidence rather than forcing all source types through one parser.

### 2. Evidence preparation

Evidence builders decide **what evidence should exist**.

For multimodal documents, the current v2 stack already provides:

- native text extraction;
- table detection and structured rows;
- image and vector signals;
- selective OCR;
- selective Vision;
- page-aware routing signals;
- chunk metadata;
- source-page provenance.

Structured tables are now emitted as first-class `structured_table` retrieval evidence in GitHub `staging`, with table provenance metadata and CI regression coverage. This implementation has not yet been deployed to the audited VPS environments.

### 3. Staging lifecycle

All new official-source workflows should converge on:

```text
source
-> baseline / change gate
-> canonical Drive artifact
-> routing
-> evidence build
-> Staging DB
-> validation
-> READY_FOR_PRODUCTION_REVIEW
```

A checksum change must not be silently accepted.

### 4. Production promotion

Production promotion should decide **whether a validated release may enter Production**.

It should not know how OCR, Vision, table extraction or legal XML parsing works.

The GitHub `staging` contract is now profile-based (M3 / CI verified), for example:

```yaml
release:
  artifact_profile: canonical-text-v1
```

or:

```yaml
release:
  artifact_profile: multimodal-v2
```

The release governance remains common; the artifact profile defines route, ingestion version and allowed evidence expectations.

Current safety boundary: `canonical-text-v1` is Production-write qualified; `multimodal-v2` is registered for contract validation but Production write authorization is explicitly blocked until its writer/validator path is separately qualified.

### 5. Frozen retrieval core

Graph-aware Retrieval + Answer Pipeline v1.3 remains frozen.

Do not refactor or reorganize the frozen retrieval path merely to make the repository look cleaner.

Any modification requires regression tests and a new validated baseline.

### 6. Learning / Anki

Anki remains responsible for spaced-repetition scheduling.

Jason OS is responsible for:

- source-grounded card generation;
- source provenance;
- review telemetry;
- knowledge analytics;
- weak-area assessment;
- reporting.

Do not build a competing scheduling algorithm inside Jason OS unless a future requirement proves it necessary.

## Production safety model

The preferred safety model is:

```text
Staging validated
-> release proposal
-> Git review
-> Production verify / prepare
-> human review
-> Git write authorization
-> readiness gate
-> explicit CLI confirmation
-> atomic write
-> mandatory post-write validator
-> manual break-glass recovery only
```

APP-145 Production Promotion v1 remains frozen historical proof.

Generic Production Promotion v2 is the forward path but must evolve from text-specific contracts toward release-artifact profiles before becoming the universal Production mechanism.

## Operational principle

User-facing Production write entrypoints should be minimized.

Legacy generic direct writers must not become the recommended operational path.

Internal engines may remain write-capable where required, but approved operational wrappers should enforce environment-specific safety.

## Migration sequence

1. Freeze this architecture and capability inventory in GitHub.
2. Structured-table retrieval evidence with regression tests — COMPLETE in GitHub `staging` / CI verified; VPS deployment pending.
3. Official-source multimodal Staging close-loop — COMPLETE in GitHub `staging` / CI verified; VPS live verification pending.
4. Release Artifact Profiles — COMPLETE in GitHub `staging` / CI verified; VPS live verification pending.
5. Live-verify the generic Production v2 path on VPS Staging.
6. Qualify APP-149 as the first generic text release candidate.
7. Prove a multimodal generic release candidate.
8. Reconcile and install safe CLI deployment definitions.
9. Enable scheduled source monitoring only after the lifecycle closes end-to-end.
10. Retire legacy direct-Production entrypoints and historical root clutter last.

## Non-goals

This architecture freeze does not:

- merge `staging` to `main`;
- deploy K3 v2 to VPS;
- authorize APP-149 Production write;
- modify APP-145;
- delete pre-Git files;
- change frozen retrieval v1.3;
- enable automatic Production promotion.