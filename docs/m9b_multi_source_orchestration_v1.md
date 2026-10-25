# M9B — Multi-Source Monitor Orchestration v1

Status: IMPLEMENTED IN GITHUB STAGING / CI + VPS LIVE PROOF PENDING

## Purpose

M9B implements the additive orchestration layer defined by M9 without modifying the frozen M8 APP149 scheduler.

M9B prepares APP149 and APP145 for one sequential Staging batch.

M9B does not activate the new batch timer.

## Source allowlist

The scheduled-source definition is separate from Source Registry membership:

```text
source_monitor_schedule_v1.yaml
```

MVP enabled sources:

```text
BD_PNAP_APP149
BD_PNAP_APP145
```

APP146 remains enabled in the Source Registry but is intentionally absent from the M9 schedule.

Therefore:

```text
registry enabled != scheduled
```

No source auto-discovery is implemented.

## Readiness validator

Module:

```text
validate_source_monitor_schedule_v1.py
```

Before batch execution it verifies:

- schedule schema/version;
- environment exactly `staging`;
- fixed MVP cadence `daily 09:15 Asia/Hong_Kong`;
- unique explicit source IDs;
- each enabled schedule source exists and is enabled in Source Registry;
- normal source registry validation passes;
- each source already has a current Staging version reference;
- Production source-monitor state roots remain rejected.

Missing references fail before source execution begins.

The validator does not initialize references.

## Generic per-source runner

Module:

```text
ops/run_source_monitor_staging_v2.sh
```

This is additive and does not replace or modify the frozen M8 runner.

The v2 runner:

- requires an explicit source ID;
- validates safe source-ID characters;
- requires the Staging state root;
- requires branch exactly `staging`;
- requires a clean worktree;
- records Git commit identity;
- uses a per-source nonblocking lock;
- invokes the existing `monitor_official_source_v1.py`;
- retains source run artifacts under the existing Staging run root;
- emits Production access/write false.

Per-source lock shape:

```text
/run/lock/jason-os-source-monitor-staging-<SOURCE_ID>.lock
```

## Batch dispatcher

Module:

```text
run_source_monitor_batch_v1.py
```

Execution model:

```text
validate full schedule/readiness
        |
        v
acquire batch lock
        |
        v
APP149 sequential run
        |
        v
APP145 sequential run
        |
        v
batch summary
```

Batch lock:

```text
/run/lock/jason-os-source-monitor-staging-batch.lock
```

Runtime source failure isolation:

- a source runner failure is recorded as `EXECUTION_FAILED`;
- later approved sources are still executed;
- batch result becomes `PARTIAL_FAILURE`;
- the process exits non-zero after the summary is written.

This differs from preflight failures, which fail closed before source execution.

## Batch artifact

Planned live path:

```text
/var/lib/jason-os/source-monitor-staging/
    batches/
        <UTC_TIMESTAMP>/
            summary.json
```

Summary includes:

- batch timestamp;
- Git branch / commit;
- scheduled source IDs;
- per-source execution status;
- baseline status;
- monitor decision / action;
- candidate flag;
- source run directory;
- overall batch status;
- Production access/write false.

## Production safety

M9B introduces no Production DB integration.

The runner and dispatcher retain:

```text
production_access = false
production_write = false
```

There is no Production source-monitor service or timer.

Reference initialization/advance is not part of batch execution.

## systemd definitions

New disabled-by-default definitions:

```text
ops/systemd/jason-os-source-monitor-staging-batch.service
ops/systemd/jason-os-source-monitor-staging-batch.timer
```

Target schedule definition:

```text
daily 09:15 Asia/Hong_Kong
```

The repository contains no installer and no automatic:

```text
systemctl enable
systemctl start
enable --now
systemctl restart
```

M9B timer activation is forbidden until M9C live verification and explicit cutover approval.

## M8 freeze boundary

Frozen M8 files remain separate:

```text
ops/run_source_monitor_staging_v1.sh
ops/systemd/jason-os-source-monitor-staging.service
ops/systemd/jason-os-source-monitor-staging.timer
```

The existing M8 contract test remains in CI.

M9B adds its own test rather than replacing M8 coverage.

## Regression test

Module:

```text
test_source_monitor_batch_v1.py
```

Coverage includes:

- explicit APP149 + APP145 allowlist;
- APP146 non-auto-discovery;
- reference readiness gate;
- missing-reference fail closed;
- sequential runtime failure isolation;
- generic v2 runner Staging guards;
- per-source lock contract;
- disabled-by-default systemd contract;
- no Production coupling;
- frozen M8 contract preservation.

CI adds:

```text
M9B Multi-source monitor orchestration contract test
```

## M9B completion gate

M9B implementation is not operationally complete until:

1. GitHub CI passes;
2. Staging VPS is aligned to the reviewed commit;
3. M8 frozen regression passes on VPS;
4. M9B contract test passes on VPS;
5. schedule validator passes using live APP149 + APP145 references;
6. batch service/timer definitions are inspected but timer remains disabled;
7. no Production DB access/write is observed.

Manual multi-source execution belongs to M9C.

## Current boundary

M9B implementation exists in GitHub Staging.

No M9B unit has been installed or enabled on the VPS yet.

The active autonomous scheduler remains frozen M8 APP149-only.


## VPS Staging live contract validation

Verified on VPS Staging.

Deployed commit:

```text
660e03ee1bd02e730d66453ab198f88a40c42e13
```

Observed results:

```text
M8 Source Monitor scheduler contract = PASS
M9B multi-source orchestration contract = PASS
Explicit source allowlist = PASS
Auto-discovery = ABSENT
Reference readiness gate = PASS
Sequential failure isolation = PASS
Per-source lock contract = PASS
M8 frozen scheduler = PRESERVED
Automatic M9 timer activation = ABSENT
Production DB coupling = ABSENT
```

Live schedule readiness:

```text
environment = staging
source_count = 2
source_ids =
  BD_PNAP_APP149
  BD_PNAP_APP145
production_access = false
production_write = false
STATUS = SOURCE_MONITOR_SCHEDULE_VALID
```

Reference integrity after deployment:

```text
BD_PNAP_APP145 =
26638377376ba8b8f4b1256de583f894e641e386e5f44a4053bc02c978599ecd

BD_PNAP_APP149 =
4514531e59caf76782120cf83377bcea6ad8a23f076e6b03b2247b193ae8682c
```

Both references remained unchanged.

Scheduler state after validation:

```text
M8 timer enabled = true
M8 timer active = true
M9B timer installed = false
M9B service installed = false
M9B timer enabled = false
```

Safety:

```text
Multi-source batch executed = false
M8 timer modified = false
APP145 reference modified = false
APP149 reference modified = false
Production DB accessed = false
Production DB modified = false
```

Conclusion:

```text
M9B STAGING CONTRACT VALIDATION: PASS
```

M9B implementation is now live-validated on Staging. The next milestone is M9C manual multi-source batch execution. M9B timer activation remains forbidden until M9D cutover.
