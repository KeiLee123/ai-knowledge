# Generic Production Promotion v2

Status: M5A LIVE VERIFIED / M5B POLICY QUALIFICATION CI VERIFIED

## Purpose

Generic Production Promotion v2 provides one Git-controlled release lifecycle for validated release artifacts.

APP-145 Production Promotion v1 remains frozen and unchanged.

## Architecture

```text
Staging VALIDATED
      |
      v
Deterministic Release Proposal
      |
      v
Policy Qualification
  AUTO_QUALIFIED
  REVIEW_REQUIRED
  BLOCKED
  NO_CHANGE
      |
      v
Git-controlled Release Contract
  qualification = policy-qualified
  write_authorized = false
      |
      v
Production Verify / Prepare
      |
      v
Production Readiness Gate
      |
      v
write_authorized gate
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
```

Break-glass recovery remains separate and manual.

## Safety principles

- GitHub is the code and release-contract Source of Truth.
- Google Drive Current is the canonical document Source of Truth.
- Production and Staging remain separate.
- Release contracts lock canonical SHA-256, deterministic chunks SHA-256, chunk/embedding counts and evidence counts.
- `artifact_profile` defines route, ingestion version and allowed evidence origins.
- Routine human release approval is replaced by `official-source-version-policy-v1`.
- Ambiguous changes route to exception review.
- `canonical-text-v1` is Production-write qualified by profile.
- `multimodal-v2` remains Production-write blocked.
- Production verify / prepare is read-only.
- Production readiness is read-only.
- Production write still requires the independent `write_authorized` gate and explicit CLI confirmation until automatic Production promotion is separately qualified.
- Zero-state checks and mandatory post-write validation remain unchanged.

## Release contract

Example:

```yaml
release_v2:
  enabled: true
  artifact_profile: canonical-text-v1
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
  expected_evidence_counts:
    native_text: 8

  staging_validation_status: VERIFIED

  qualification:
    method: policy
    policy_version: official-source-version-policy-v1
    mode: initial_release
    status: qualified
    decision: AUTO_QUALIFIED
    signals:
      official_source_identity: true
      staging_validation_verified: true
      deterministic_release: true
      canonical_checksum_locked: true
      chunks_checksum_locked: true

  write_authorized: false
  require_confirmation: true
```

The contract validator recomputes qualification from the policy signals.

## Initial-release proposal

The Staging proposal generator validates the Staging milestone, verifies the canonical checksum, builds the release artifact twice, verifies deterministic equivalence, locks the hashes, and evaluates the initial-release policy.

It performs no Production query or write.

## Future version updates

Automatic version qualification requires:

```text
same authority
same document code
same official host
newer issue/revision date OR changed edition
material metadata changed
checksum changed
normalized content changed
Staging VERIFIED
deterministic release
```

Ambiguous changes go to `REVIEW_REQUIRED`.

M5C implements issue/revision extraction plus material-metadata and normalized-content fingerprints in GitHub `staging`; VPS live verification remains pending.

## Production verify / prepare

After a policy-qualified contract exists:

```bash
python prepare_canonical_text_production_v2.py SOURCE_ID --verify
```

or:

```bash
python prepare_canonical_text_production_v2.py SOURCE_ID \
  --prepare \
  --workdir /tmp/source-production-v2
```

Prepare may generate embeddings and inspect an in-memory transaction. It does not execute SQL.

## Production write authorization

The current final write gate remains:

```yaml
write_authorized: true
```

This is deliberately separate from release qualification.

A later milestone may replace it with an automatic Production readiness policy after live qualification.

## APP149 M5A proof

APP149 is the first live `canonical-text-v1` proposal candidate.

Qualified deterministic values:

```text
release_id
bd_pnap_app149-a5b4d5a1af5f

canonical_sha256
a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8

expected_chunks_sha256
4accbc06df6f304f6bed49545a5132639af23a01385f406f8252a3a46db71cdd

expected_chunk_count
8

expected_embedding_count
8

expected_evidence_counts
native_text = 8
```

The hash-path determinism defect was fixed at commit `4936069`.

## Current boundary

The Production v2 registry remains empty.

M5B policy code and M5C version-signal extraction are CI-verified in GitHub `staging` but not yet live-deployed/verified together on VPS Staging.

No APP149 Production write is authorized.

Multimodal Production write remains blocked.