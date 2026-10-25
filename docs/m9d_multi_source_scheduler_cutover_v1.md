# M9D — Multi-Source Scheduler Cutover Architecture v1

Status: DESIGN / CUTOVER TOOLING PREPARATION
Live cutover: NOT YET AUTHORIZED

## Purpose

M9D replaces the frozen M8 APP149-only autonomous timer with the verified M9 multi-source batch timer.

The cutover must guarantee that APP149 is never scheduled by M8 and M9 at the same time.

M9D is the final Official Source Monitoring milestone.

## Starting state

Before cutover:

```text
M8 timer = installed / enabled / active
M8 scheduled source = BD_PNAP_APP149

M9 batch service = repo-defined, not installed
M9 batch timer = repo-defined, not installed
M9 scheduled sources =
  BD_PNAP_APP149
  BD_PNAP_APP145

APP149 reference = monitor-ready
APP145 reference = monitor-ready

M9B contract validation = PASS
M9C normal multi-source live proof = PASS
M9C failure isolation proof = PASS
```

Production remains out of scope.

## Cutover phases

### Phase 1 — Install M9 units without activation

Install only:

```text
jason-os-source-monitor-staging-batch.service
jason-os-source-monitor-staging-batch.timer
```

Then run:

```text
systemctl daemon-reload
```

Required state after installation:

```text
M8 timer = enabled + active
M9 timer = disabled + inactive
```

Installing the M9 units must not start or enable them.

### Phase 2 — Pre-cutover validation

Before changing any timer activation:

1. branch = `staging`;
2. worktree clean;
3. VPS commit equals reviewed GitHub cutover commit;
4. M8 frozen regression passes;
5. M9B contract passes;
6. schedule validator passes;
7. APP149 + APP145 reference SHA values match the accepted live proofs;
8. M8 timer enabled and active;
9. M9 timer disabled and inactive;
10. Production access/write remains false.

If any check fails, stop.

### Phase 3 — Atomic operational cutover

The required order is:

```text
disable --now M8 timer
        |
        v
verify M8 disabled + inactive
        |
        v
enable --now M9 batch timer
        |
        v
verify M9 enabled + active
```

M9 must never be enabled before M8 is disabled and confirmed inactive.

No manual batch should be started during the timer transition.

### Phase 4 — Post-cutover validation

Immediately verify:

```text
M8 = disabled + inactive
M9 = enabled + active
APP149 reference unchanged
APP145 reference unchanged
Production DB untouched
```

Also inspect the M9 timer's next trigger.

## First autonomous proof

M9D is not complete immediately after cutover.

Completion requires the first autonomous M9 batch triggered by systemd.

The autonomous batch must prove:

```text
trigger = systemd timer
source_ids = APP149 + APP145
overall_status = SUCCESS
APP149 = EXECUTION_SUCCESS / NO_CHANGE / NONE
APP145 = EXECUTION_SUCCESS / NO_CHANGE / NONE
references unchanged
production_access = false
production_write = false
```

The run must not be manually started for the completion proof.

## Rollback

Rollback is operational and must preserve the same no-double-schedule invariant.

Required order:

```text
disable --now M9 timer
        |
        v
verify M9 disabled + inactive
        |
        v
enable --now M8 timer
        |
        v
verify M8 enabled + active
```

Rollback does not delete M9 units or runtime batch artifacts.

References must not be changed by rollback.

## Tooling contract

M9D may add:

```text
ops/install_source_monitor_staging_batch_v1.sh
ops/cutover_source_monitor_staging_v1.sh
test_source_monitor_cutover_v1.py
docs/m9d_multi_source_scheduler_cutover_v1.md
```

The installer:

- copies M9 service/timer unit files;
- runs daemon-reload;
- explicitly refuses to enable/start M9.

The cutover script:

- requires an explicit confirmation argument;
- validates current timer state;
- disables M8 first;
- verifies M8 inactive/disabled;
- only then enables M9;
- verifies M9 active/enabled;
- supports an explicit rollback mode;
- does not run monitor batches directly;
- does not touch references;
- does not touch Production.

## Frozen layer rule

M8 files remain frozen:

```text
ops/run_source_monitor_staging_v1.sh
ops/systemd/jason-os-source-monitor-staging.service
ops/systemd/jason-os-source-monitor-staging.timer
```

M9D may operate on the installed M8 timer state during cutover, but must not edit the frozen M8 files.

## Authorization boundary

Creating and validating M9D tooling does not authorize live cutover.

Live cutover requires an explicit user authorization after:

- M9D CI passes;
- VPS Staging pre-cutover validation passes;
- M9 units are installed but remain disabled/inactive.

Until then:

```text
M8 stays enabled + active
M9 stays disabled + inactive
```
