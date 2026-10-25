# M9A — APP145 Staging Reference Preparation Architecture v1

Status: DESIGN ONLY / NO STATE WRITE AUTHORIZED

## Purpose

M9A prepares BD_PNAP_APP145 to become eligible for M9 multi-source monitoring by creating its first accepted Staging version reference through the existing guarded lifecycle.

M9A does not schedule APP145.

M9A does not modify the frozen M8 scheduler.

M9A does not access or write the Production database.

## Why APP145

The M9 readiness audit found:

```text
BD_PNAP_APP145 current reference = absent
BD_PNAP_APP146 current reference = absent
BD_PNAP_APP149 current reference = present
```

Per the M9 MVP sequencing rule, APP145 is the first preparation target because it provides the simpler first expansion path and has mature deterministic lifecycle history.

## Reuse existing modules

M9A does not introduce a new reference generator.

The intended path reuses:

```text
propose_production_release_v2.py
        |
        | Staging-only deterministic proposal
        | production_access=false
        | production_write=false
        | write_authorized=false
        v
version_snapshot_store_v1.py
        |
        | explicit --initialize
        | explicit --confirm-staging-state-write
        v
/var/lib/jason-os/source-monitor-staging/
    version-snapshots/current/BD_PNAP_APP145.json
```

The proposal name contains "production release" because it models the release contract, but the proposal generator itself is explicitly Staging-only and performs no Production access or write.

## Preconditions

Reference initialization is not allowed until every precondition is proven.

### 1. Git runtime

```text
checkout = /opt/ai-knowledge-staging
branch = staging
worktree = clean
```

### 2. Source Registry

APP145 must remain:

```text
enabled = true
canonical_text_ingestion.enabled = true
controller_environment = staging
allow_production_write = false
```

### 3. Approved source baseline

The following file must already exist and be valid:

```text
/var/lib/jason-os/source-monitor-staging/baselines/BD_PNAP_APP145.json
```

The baseline supplies the expected canonical document SHA-256 and optional content length.

M9A must not create or alter this baseline as part of reference initialization.

### 4. Canonical Drive source

The APP145 canonical document must be downloadable from the configured Staging-controlled Drive path and must match the approved baseline checksum.

Google Drive remains the document Source of Truth.

### 5. Staging DB qualification

The approved APP145 checksum must already exist in the isolated Staging DB.

The existing proposal generator requires an existing Staging document ID and runs the configured semantic validation before it will emit a proposal.

M9A must not use Production DB rows as a substitute.

### 6. Reference absence

Before initialization:

```text
/var/lib/jason-os/source-monitor-staging/version-snapshots/current/BD_PNAP_APP145.json
```

must not exist.

Initialization is create-once and must fail closed if the reference already exists.

## Phase A — Read-only preflight

Before any state write, collect:

- Git branch / commit / clean status;
- M8 timer enabled/active state;
- APP145 baseline existence;
- APP145 baseline document SHA-256;
- APP145 baseline content length;
- APP145 current-reference absence;
- APP145 Staging DB document presence for the baseline checksum;
- current Production access/write flags remain false.

If any item fails, stop.

No reference initialization occurs during Phase A.

## Phase B — Deterministic proposal proof

Run `propose_production_release_v2.py` for APP145 twice in separate retained temporary work directories.

Both outputs must agree on:

- source ID;
- Staging document ID;
- canonical SHA-256;
- chunks SHA-256;
- chunk count;
- artifact profile;
- release ID;
- version-signal snapshot;
- qualification record;
- complete contract proposal.

Required safety fields:

```text
production_access = false
production_write = false
contract_proposal.release_v2.write_authorized = false
qualification.status = qualified
qualification.decision = AUTO_QUALIFIED
qualification.mode = initial_release
```

If the two proposals differ, stop.

## Phase C — Explicit Staging reference initialization

Only after Phase A and Phase B pass may the existing snapshot-store write gate be used:

```text
version_snapshot_store_v1.py
    BD_PNAP_APP145
    --state-root /var/lib/jason-os/source-monitor-staging
    --proposal-log <verified proposal log>
    --initialize
    --confirm-staging-state-write
```

This is the only state-changing step in M9A.

The store must reject:

- unsafe source IDs;
- Production state roots;
- Production access/write proposals;
- write-authorized release proposals;
- non-qualified initial releases;
- an already-existing current reference.

## Phase D — Post-write verification

After initialization, verify:

- current reference exists;
- stored `source_id = BD_PNAP_APP145`;
- stored release ID matches the verified proposal;
- stored artifact profile matches the verified proposal;
- qualification is `qualified / AUTO_QUALIFIED / initial_release`;
- stored document SHA-256 matches the approved APP145 baseline;
- reference file SHA-256 is recorded;
- no APP149 reference changed;
- M8 timer remains enabled and active;
- no Production source-monitor state exists;
- Production DB was not modified.

## What M9A does not do

M9A does not:

- add APP145 to an M9 schedule manifest;
- enable an M9 timer;
- disable the M8 timer;
- advance APP145 beyond the initialized reference;
- run Production promotion;
- write the Production DB;
- modify APP145 canonical Drive content;
- modify frozen M8 scheduler files.

## Rollback boundary

Because initialization creates one Staging operational-state file, rollback before M9 scheduling is simple:

```text
remove only the newly created APP145 current reference
```

However, rollback must be explicit and evidence-preserving; do not automatically delete the reference on later test failure.

No Production rollback is required because M9A does not touch Production.

## Acceptance criteria

M9A architecture is accepted when:

1. existing generic proposal tooling is reused;
2. APP145 baseline and Staging DB presence are mandatory preconditions;
3. deterministic proposal proof occurs before the write;
4. initialization uses the explicit Staging state-write confirmation flag;
5. reference absence is checked before initialization;
6. APP149 reference integrity is protected;
7. M8 timer remains unchanged;
8. Production access/write remain false;
9. scheduling remains out of scope.

## Next execution gate

The next step after this architecture is a read-only APP145 preflight.

No state write is authorized until that preflight succeeds.


## Phase B live deterministic proposal proof

Verified on VPS Staging.

Runtime baseline:

```text
branch = staging
commit = 4e02befd604640ca12b070ec993ae3104454d20c
worktree = clean
```

Two independent proposal runs were generated in separate work directories.

Observed deterministic result:

```text
source_id = BD_PNAP_APP145
staging_document_id = 2
canonical_sha256 = dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c
chunks_sha256 = d8fecb22255115751ed84dfdd945b1b0b92022d09baaa1bd5c1019586fb74120
chunk_count = 8
release_id = bd_pnap_app145-dc3262cc55c5
artifact_profile = canonical-text-v1
qualification_status = qualified
qualification_decision = AUTO_QUALIFIED
qualification_mode = initial_release
write_authorized = false
production_access = false
production_write = false
complete_proposal_match = true
```

Proof directory:

```text
/tmp/m9a-app145-phase-b-20261025T013921Z
```

Post-proof safety:

```text
APP145 reference write performed = false
APP149 reference modified = false
M8 timer modified = false
Production DB accessed = false
Production DB modified = false
```

Phase B conclusion:

```text
M9A APP145 PHASE B: PASS
```

Phase C may now initialize the APP145 Staging reference through the explicit guarded snapshot-store write path. Scheduling remains out of scope.
