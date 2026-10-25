# M9 — Source Monitor Expansion Architecture v1

Status: DESIGN ONLY / NO IMPLEMENTATION

## Purpose

M9 defines how Jason OS can expand official-source monitoring from the single M8 APP149 canary to multiple explicitly approved sources without weakening the existing Staging-only and no-Production-write safety boundaries.

M9 is an orchestration milestone. It does not replace the M5E monitor engine.

## Current baseline

M8 is frozen and autonomously verified.

The M8 scheduler is intentionally locked to:

```text
BD_PNAP_APP149
```

The generic monitor engine already accepts a source ID:

```text
monitor_official_source_v1.py --source <SOURCE_ID>
```

Therefore M9 should reuse the existing monitor engine and add a new scheduling/orchestration layer rather than modify the frozen M8 runner.

Current source-monitor state remains:

```text
/var/lib/jason-os/source-monitor-staging
```

Production source-monitor state remains forbidden.

## Architectural decision

M9 introduces a separate multi-source orchestration path.

M8 files remain unchanged.

Planned logical architecture:

```text
systemd M9 batch timer
        |
        v
M9 batch dispatcher
        |
        +-- explicit schedule allowlist
        |
        +-- preflight / readiness validation
        |
        +-- source A -> generic per-source runner -> M5E monitor
        |
        +-- source B -> generic per-source runner -> M5E monitor
        |
        +-- source C -> generic per-source runner -> M5E monitor
        |
        v
batch summary artifact
```

The M5E monitor remains the source-level decision engine.

## Separation of responsibilities

### Source Registry

`source_registry_v1.yaml` continues to define source identity and source-processing policy.

Registry membership or `enabled: true` does not mean a source is automatically scheduled.

### M9 Schedule Manifest

M9 should use a separate GitHub-controlled schedule manifest.

Its purpose is only to answer:

```text
Which sources are approved for scheduled monitoring?
```

The schedule manifest must use an explicit allowlist.

M9 must not automatically schedule every registry source whose `enabled` field is true.

This preserves a clear distinction between:

```text
source exists
!=
source is monitoring-ready
!=
source is scheduled
```

For the MVP, all admitted sources share one daily cadence. Per-source cron expressions are deferred.

## Source admission gate

A source may enter the M9 schedule only when all required readiness checks pass.

Minimum gate:

1. source ID exists in `source_registry_v1.yaml`;
2. registry source is enabled;
3. source is explicitly present and enabled in the M9 schedule manifest;
4. canonical URL and host/content-type validation contracts exist;
5. a current Staging version reference exists for the source;
6. the Staging state-root contract accepts the path;
7. no Production source-monitor state is used;
8. monitor execution does not authorize Production access or write.

A missing reference is not silently initialized by the scheduler.

Reference initialization remains a separate explicit Staging operation.

## Execution model

M9 MVP runs sources sequentially.

Reasons:

- lower load on the official publisher;
- simpler logs;
- simpler failure analysis;
- no concurrency coordination beyond per-source locks;
- easier rollback and regression testing.

Parallel execution is deferred until there is evidence that sequential execution is insufficient.

## Failure isolation

Configuration/preflight errors fail the batch before source execution begins.

Once execution begins, runtime failure of one source must not prevent later approved sources from running.

Each source receives its own result.

Example logical result states:

```text
EXECUTION_SUCCESS
EXECUTION_FAILED
```

The monitor decision remains separate from execution health.

Examples of successful monitor decisions include:

```text
NO_CHANGE
CANDIDATE_NEW_VERSION
EXCEPTION_REVIEW
POLICY_BLOCKED
```

A policy decision is not the same as a crashed monitor process.

The batch dispatcher records both dimensions.

## Locking

M8 currently uses one M8-specific lock.

M9 should use per-source locks:

```text
/run/lock/jason-os-source-monitor-staging-<SOURCE_ID>.lock
```

This prevents duplicate execution of the same source while avoiding unnecessary blocking between unrelated sources.

The M9 dispatcher itself may also use one non-blocking batch lock to prevent duplicate daily batches.

## Runtime artifacts

Existing source run isolation is retained:

```text
/var/lib/jason-os/source-monitor-staging/
    runs/
        <SOURCE_ID>/
            <UTC_TIMESTAMP>/
                monitor-output.txt
                ...
```

M9 adds a batch-level summary:

```text
/var/lib/jason-os/source-monitor-staging/
    batches/
        <UTC_TIMESTAMP>/
            summary.json
```

The batch summary should contain only operational metadata, including:

- batch timestamp;
- Git commit;
- scheduled source IDs;
- per-source execution status;
- per-source monitor decision/action;
- run artifact path;
- Production access/write flags;
- overall batch status.

## Reference safety

M9 scheduling must not automatically advance stored version references.

The scheduled monitor may:

- compare the live source to the existing baseline;
- download a candidate when required;
- classify version signals;
- route the candidate to the existing Staging validation requirement.

It must not call the explicit reference-advance path.

Reference advancement remains a separate guarded lifecycle operation.

## Production boundary

M9 remains Staging-only.

It must not:

- create a Production source-monitor state root;
- schedule a Production monitor service;
- connect to the Production database;
- invoke Production promotion writers;
- convert a monitor decision directly into a Production write.

Expected monitor safety output remains:

```text
production_access = false
production_write = false
```

## Scheduling model

M9 MVP uses one daily batch schedule.

Initial target cadence:

```text
daily 09:15 Asia/Hong_Kong
```

This preserves the already verified M8 operational window.

The M9 timer must remain disabled during implementation and manual validation.

## M8 migration / cutover

M8 code remains frozen.

M9 must prove parity before M8 scheduling is retired.

Required cutover sequence:

```text
M9 architecture
  -> M9 contract implementation
  -> CI regression
  -> Staging deploy
  -> manual M9 APP149 parity run
  -> prepare at least one additional source reference
  -> manual multi-source batch proof
  -> verify source failure isolation
  -> M9 timer still disabled
  -> explicit cutover approval
  -> disable M8 timer
  -> verify M8 timer inactive
  -> enable M9 timer
  -> verify first autonomous M9 batch
```

There must never be a period where both M8 and M9 schedule APP149 automatically.

## Initial source expansion

No additional source is admitted merely because it is already present in the registry.

APP145 and APP146 are possible future candidates, but M9 implementation must first audit their source-monitor readiness and current version-reference state.

The first expansion source should be selected only after that readiness audit.

## MVP non-goals

M9 v1 does not include:

- automatic discovery of all enabled registry sources;
- parallel source monitoring;
- per-source cron schedules;
- Production monitoring;
- automatic Production promotion;
- automatic reference advancement;
- notification or paging;
- retry queues;
- distributed workers;
- database-backed scheduler state.

These can be added later only when operational evidence justifies them.

## Planned implementation modules

The architecture permits the following replaceable modules without modifying M8:

```text
source_monitor_schedule_v1.yaml
    explicit scheduling allowlist

validate_source_monitor_schedule_v1.py
    schedule + readiness contract validation

ops/run_source_monitor_staging_v2.sh
    generic safe per-source runner

run_source_monitor_batch_v1.py
    sequential dispatcher + failure isolation + summary

ops/systemd/jason-os-source-monitor-staging-batch.service
ops/systemd/jason-os-source-monitor-staging-batch.timer
    disabled-by-default M9 scheduler
```

Names are provisional until implementation begins.

## Regression boundary

Because M8 and the existing retrieval / Production promotion layers are frozen, M9 implementation must include regression tests that prove:

- M8 files remain unchanged;
- M8 scheduler contract still passes;
- M5E monitor behavior remains unchanged;
- Staging-only state-root validation still passes;
- Production access/write remains false;
- the M9 schedule does not auto-discover registry sources;
- missing references fail closed;
- one source failure does not suppress later source execution;
- M9 timer activation is absent from repository automation.

## M9 architecture acceptance criteria

Architecture is accepted when the following decisions are agreed:

1. M8 remains frozen and untouched.
2. M9 is a new orchestration layer over the generic M5E monitor.
3. Scheduled sources use an explicit allowlist separate from registry membership.
4. Source admission requires an existing Staging version reference.
5. MVP execution is sequential.
6. Runtime failures are isolated per source.
7. Run artifacts remain source-scoped and a batch summary is added.
8. References are never auto-advanced.
9. Production monitoring/writes remain forbidden.
10. M8-to-M9 cutover is explicit and never double-schedules APP149.

No implementation or timer change is authorized by this architecture document.
