# M5A — APP149 Generic Release Proposal Proof

Status: LIVE VERIFIED  
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

## Live verification record

Verified on 2026-10-24.

- VPS Staging commit: `49360697647ec66d8233ce0190a1a1ebd8a94c8e`
- source ID: `BD_PNAP_APP149`
- artifact profile: `canonical-text-v1`
- Staging document ID: `3`
- canonical SHA-256: `a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8`
- deterministic chunks SHA-256: `4accbc06df6f304f6bed49545a5132639af23a01385f406f8252a3a46db71cdd`
- chunk count: `8`
- expected evidence counts: `native_text = 8`
- release ID: `bd_pnap_app149-a5b4d5a1af5f`
- Staging validation status: `VERIFIED`
- semantic expected terms: `authorized`, `signatory`, `minor`, `works`
- two independent proposal runs produced the same `contract_proposal`
- two independent proposal runs produced the same `chunks_sha256`
- `release_reviewed = false`
- `write_authorized = false`
- `production_access = false`
- `production_write = false`
- Git worktree remained clean
- command block exit code: `0`

## Determinism defect found and fixed

The first determinism proof failed because the release chunk artifact included the absolute temporary manifest path under `source_manifest.path`.

This made otherwise-identical release artifacts differ across work directories.

The fix at commit `4936069` changes the path field to the stable manifest basename and adds a regression test proving identical outputs across different temporary directories.

This correction preserved manifest SHA, document SHA, chunk content and provenance. It removed only machine-local path volatility from the hash-critical artifact.

## Governance state after M5A

M5A qualifies the proposal as deterministic evidence for human review.

It does **not** mean:

- `release_reviewed = true`;
- `write_authorized = true`;
- the APP149 release contract is present in `production_release_registry_v2.yaml`;
- Production has been queried or modified.

The next gate is explicit human review of this exact proposal before any registry change.
