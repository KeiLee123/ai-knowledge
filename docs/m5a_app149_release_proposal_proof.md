# M5A — APP149 Generic Release Proposal Proof

Status: RUNBOOK READY  
Environment: VPS Staging only  
Production access: NONE  
Production write: NONE

## Purpose

M5A proves that the already-qualified APP149 Staging artifact can deterministically generate a Generic Production Promotion v2 release proposal.

This milestone does not populate `production_release_registry_v2.yaml`, does not mark a release reviewed, does not authorize a Production write, and does not query the Production DB.

## Candidate

- source ID: `BD_PNAP_APP149`
- artifact profile: `canonical-text-v1`
- expected Staging document ID from the prior qualification: `3`

## Expected path

```text
APP149 approved baseline
      |
      v
existing Staging qualification
      |
      v
read-only Staging semantic validator
      |
      v
canonical Drive checksum verification
      |
      v
deterministic legacy-v1 routing
      |
      v
deterministic canonical-text chunks
      |
      v
release_v2 proposal
  artifact_profile = canonical-text-v1
  release_reviewed = false
  write_authorized = false
  production_access = false
  production_write = false
```

## Determinism proof

Run the proposal generator twice in separate work directories.

Both runs must return identical:

- Staging document ID;
- canonical SHA-256;
- chunks SHA-256;
- chunk count;
- complete `contract_proposal`.

## Safety requirements

Before each proof:

- Git branch must be exactly `staging`;
- worktree must be clean;
- Staging canary guard must pass;
- APP149 baseline must already exist;
- APP149 must already exist in the isolated Staging DB;
- no Production command may be called;
- `production_release_registry_v2.yaml` must remain unchanged.

The proposal generator is not permitted to elevate:

```text
release_reviewed = false
write_authorized = false
```

## M5A success criteria

M5A is LIVE VERIFIED only when:

- both independent proposals succeed;
- both proposals are byte-equivalent in their release contract content;
- `artifact_profile` = `canonical-text-v1`;
- `required_route` = `legacy-v1`;
- `frozen_ingestion_version` = `canonical-text-ingestion-v1`;
- `expected_evidence_counts.native_text` equals chunk count;
- `staging_validation_status` = `VERIFIED`;
- `release_reviewed` = false;
- `write_authorized` = false;
- `require_confirmation` = true;
- top-level `production_access` = false;
- top-level `production_write` = false;
- Git worktree remains clean after the run.

## After success

The proposal values are evidence for human review only.

A later milestone may add the reviewed APP149 contract to GitHub with:

```text
release_reviewed = true
write_authorized = false
```

That is still not Production write authorization.

The separate `write_authorized = true` change remains a later explicit gate.
