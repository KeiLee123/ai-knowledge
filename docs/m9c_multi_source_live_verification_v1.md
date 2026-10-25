# M9C — Multi-Source Live Verification v1

Status: NORMAL PATH LIVE VERIFIED / FAILURE ISOLATION PROOF PENDING

## Purpose

M9C proves the M9B multi-source orchestration layer on VPS Staging before any scheduler cutover.

M9C does not activate the M9 batch timer.

## Environment

```text
Git branch = staging
Git commit = fe04d9d7ee92cf31ad90c4b7a0a8401e754bd6dd
State root = /var/lib/jason-os/source-monitor-staging
```

## Scheduled sources

```text
BD_PNAP_APP149
BD_PNAP_APP145
```

APP146 remains unscheduled.

## Normal-path manual batch proof

Verified on 2026-10-25 UTC.

Batch:

```text
batch_timestamp = 20261025T020004Z
overall_status = SUCCESS
production_access = false
production_write = false
summary_path =
/var/lib/jason-os/source-monitor-staging/batches/20261025T020004Z/summary.json
```

Per-source results:

```text
BD_PNAP_APP149
execution_status = EXECUTION_SUCCESS
baseline_status = UNCHANGED
decision = NO_CHANGE
action = NONE
candidate_downloaded = false
return_code = 0
run_dir =
/var/lib/jason-os/source-monitor-staging/runs/BD_PNAP_APP149/20261025T020004Z

BD_PNAP_APP145
execution_status = EXECUTION_SUCCESS
baseline_status = UNCHANGED
decision = NO_CHANGE
action = NONE
candidate_downloaded = false
return_code = 0
run_dir =
/var/lib/jason-os/source-monitor-staging/runs/BD_PNAP_APP145/20261025T020005Z
```

## Reference integrity

Before and after the batch:

```text
APP145 reference SHA-256 =
26638377376ba8b8f4b1256de583f894e641e386e5f44a4053bc02c978599ecd

APP149 reference SHA-256 =
4514531e59caf76782120cf83377bcea6ad8a23f076e6b03b2247b193ae8682c
```

Both references remained unchanged.

## Scheduler safety

After the manual batch:

```text
M8 timer enabled = true
M8 timer active = true
M8 timer modified = false

M9 batch timer installed = false
M9 batch timer enabled = false
M9 batch service installed = false
```

## Production safety

```text
Production DB accessed = false
Production DB modified = false
Production source-monitor state used = false
```

## Normal-path conclusion

```text
M9C MANUAL MULTI-SOURCE BATCH: PASS
```

The normal multi-source path is now live verified.

## Remaining M9C gate

Before M9C can be declared complete, prove runtime failure isolation.

The failure-isolation proof must demonstrate:

1. one approved source runner can fail;
2. the later approved source still executes;
3. the batch summary records PARTIAL_FAILURE;
4. the successful source retains its real monitor decision;
5. both references remain unchanged;
6. no Production access/write occurs;
7. M8 remains active;
8. M9 timer remains uninstalled/disabled.

The failure must be injected through a temporary test runner or test-only configuration. The real monitor, source registry, schedule allowlist, references, M8 files, and Production environment must remain unchanged.
