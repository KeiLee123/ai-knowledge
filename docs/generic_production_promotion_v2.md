# Generic Production Promotion v2

Status: STAGING IMPLEMENTATION / CI QUALIFICATION

## Purpose

Generic Production Promotion v2 replaces the need for a new candidate-specific Python writer for every text-based official source.

APP-145 Production Promotion v1 remains frozen and unchanged.

## Architecture

```text
Staging VALIDATED
      |
      v
Release Proposal Generator
      |
      v
Git-controlled Release Contract
  release_reviewed: true
  write_authorized: false
      |
      v
Production Verify / Prepare
      |
      v
Human review of live preflight
      |
      v
Git change:
  write_authorized: true
      |
      v
Production Readiness Gate
      |
      v
Explicit Production Writer
      |
      v
Atomic COMMIT
      |
      v
Mandatory read-only Validator
      |
      v
VERIFIED / freeze record

Break-glass Recovery exists separately and is never automatic.
```

## Safety principles

- GitHub remains the code and release-contract Source of Truth.
- Google Drive Current remains the canonical document Source of Truth.
- Production DB is fixed to `ai-knowledge-db-jiyckdrlappwgimwebnzxwmr`.
- Staging DB is forbidden from Production v2 write paths.
- Release contracts lock canonical SHA-256, deterministic chunks SHA-256, chunk count and embedding count.
- The deterministic router must select `legacy-v1`.
- The frozen ingestion version remains `canonical-text-ingestion-v1`.
- Production verify / prepare is read-only.
- Production readiness is read-only.
- Production write requires both Git authorization and explicit CLI confirmation.
- The writer performs a zero-state check before preparation and again immediately before COMMIT.
- Post-write validation is mandatory.
- Recovery is manual break-glass only.
- No v2 code modifies APP-145 v1 Production behavior.

## Release contract

Each source is represented under `production_release_registry_v2.yaml`.

A reviewed contract contains:

```yaml
canonical_text_release_v2:
  enabled: true
  release_id: source-checksum-prefix
  controller_environment: production
  remote: "gdrive-bd-write:"
  source: "Current/..."
  db_container: "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
  required_route: "legacy-v1"
  frozen_ingestion_version: "canonical-text-ingestion-v1"
  expected_sha256: "..."
  expected_chunks_sha256: "..."
  expected_chunk_count: 8
  expected_embedding_count: 8
  semantic_validation:
    checks:
      - label: staging_qualified_query
        query: "..."
        expect_terms:
          - "..."
  release_reviewed: true
  write_authorized: false
  require_confirmation: true
```

The initial proposal always sets:

```text
release_reviewed = false
write_authorized = false
```

Those values cannot be elevated by the proposal generator.

## Staging proposal

```bash
python propose_production_release_v2.py SOURCE_ID \
  --workdir /tmp/source-release-v2
```

This is Staging-only. It validates the existing Staging milestone, rebuilds deterministic chunks, and reports the canonical and chunks hashes needed for review.

It has no Production query or write path.

## Production verify / prepare

After the reviewed contract is merged to `main`:

```bash
python prepare_canonical_text_production_v2.py SOURCE_ID \
  --verify
```

or:

```bash
python prepare_canonical_text_production_v2.py SOURCE_ID \
  --prepare \
  --workdir /tmp/source-production-v2
```

Prepare may create embeddings and inspect the transaction in memory. It does not execute SQL.

## Write authorization

The final write gate is a separate Git-controlled change:

```yaml
write_authorized: true
```

The readiness gate refuses a contract without that authorization.

## Production readiness

```bash
python validate_production_write_readiness_v2.py SOURCE_ID \
  --prepared-workdir /tmp/source-production-v2
```

It verifies:

- Production guard
- clean Git worktree
- reviewed and write-authorized contract
- canonical artifact SHA
- chunks artifact SHA
- deterministic chunk contract
- Production zero-state
- recovery transaction structure
- read-only validator readiness

It performs no database write.

## Production write

```bash
python write_canonical_text_production_v2.py SOURCE_ID \
  --write \
  --confirm-production-write \
  --prepared-workdir /tmp/source-production-v2
```

The writer repeats zero-state checks, builds the transaction from the reviewed artifacts, executes one atomic transaction, and immediately invokes the v2 validator.

Automatic recovery is deliberately disabled.

## Recovery

Preview:

```bash
python recover_canonical_text_production_v2.py SOURCE_ID --preview
```

Break-glass recovery:

```bash
python recover_canonical_text_production_v2.py SOURCE_ID \
  --recover \
  --confirm-production-recovery
```

Recovery locks to the exact checksum, v2 release gate, release ID and frozen ingestion version.

## Current boundary

The v2 registry intentionally begins empty.

The first real candidate will be APP-149. Its release contract is not populated until the Staging proposal generator is live-run and its hashes are reviewed.

No APP-149 Production write is authorized by the implementation itself.
