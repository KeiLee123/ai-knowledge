# M8 — Scheduled Source Monitoring v1

Status: AUTONOMOUSLY VERIFIED / OPERATIONAL

## Purpose

M8 adds a reproducible systemd scheduling layer around the live-verified M5E official-source monitor.

M8 does not move source monitoring into the Production runtime. The scheduler remains Staging-only because the current M5D/M5E state contract uses:

```text
/var/lib/jason-os/source-monitor-staging
```

and Production source-monitor state is explicitly forbidden by the version snapshot store.

## MVP scope

The first scheduled canary is:

```text
source_id = BD_PNAP_APP149
frequency = daily
time = 09:15 Asia/Hong_Kong
environment = staging
```

APP-149 is the only M8 MVP scheduled source. Additional registry sources remain outside this first scheduler milestone.

## Runtime architecture

```text
systemd timer
    |
    v
jason-os-source-monitor-staging.service
    |
    v
ops/run_source_monitor_staging_v1.sh
    |
    +-- flock overlap guard
    |
    v
monitor_official_source_v1.py
    |
    v
/var/lib/jason-os/source-monitor-staging
    |
    +-- version-snapshots/
    +-- runs/BD_PNAP_APP149/<timestamp>/
```

Each scheduled run retains its monitor output and any downloaded candidate under the Staging runtime state root.

## Safety boundary

M8 must not:

- use a Production source-monitor state root;
- write to the Production database;
- install or enable itself merely because code is deployed;
- schedule any source other than APP-149 in the MVP;
- bypass the existing M5E candidate pre-gate.

The runner emits explicit:

```text
production_access=false
production_write=false
```

before invoking M5E.

## Overlap handling

The runner uses a non-blocking `flock` lock.

If a prior scheduled run is still active, the next run exits cleanly with:

```text
STATUS: SOURCE_MONITOR_STAGING SKIPPED_ALREADY_RUNNING
```

This prevents concurrent candidate downloads and duplicate monitor runs.

## Deployment boundary

The repository contains the service and timer definitions, but no installer or automatic enable action.

Required rollout sequence:

```text
GitHub staging CI
  -> Staging VPS deploy
  -> contract test
  -> install unit files
  -> systemctl daemon-reload
  -> manual service run
  -> verify NO_CHANGE / safety boundary
  -> timer still disabled
  -> explicit timer enable decision
```

Timer enablement is a separate operational milestone.


## Staging live verification

Verified Staging commit:

```text
e56a6dd68c44869f55f0029cf19bd553cfd0e41e
```

Manual systemd service verification completed successfully with the timer still disabled.

Observed run:

```text
source_id = BD_PNAP_APP149
run_dir = /var/lib/jason-os/source-monitor-staging/runs/BD_PNAP_APP149/20261024T162333Z
decision = NO_CHANGE
action = NONE
candidate_downloaded = false
production_access = false
production_write = false
```

Stored reference SHA-256 before and after the run:

```text
4514531e59caf76782120cf83377bcea6ad8a23f076e6b03b2247b193ae8682c
```

Reference advance:

```text
false
```

systemd result:

```text
Result=success
ExecMainStatus=0
ActiveState=inactive
SubState=dead
```

Timer state after verification:

```text
enabled = false
active = false
```

Production database writes were not performed, and no Production source-monitor state root was used.


## Timer activation record

Activation baseline:

```text
GitHub main    = 84d220cb84320c7b87f9c84fe4b97fcd14d174da
GitHub staging = 84d220cb84320c7b87f9c84fe4b97fcd14d174da
Production VPS = 84d220cb84320c7b87f9c84fe4b97fcd14d174da
Staging VPS    = 84d220cb84320c7b87f9c84fe4b97fcd14d174da
```

Activated unit:

```text
jason-os-source-monitor-staging.timer
```

Activation result:

```text
enabled = true
active = true
```

Scheduled cadence:

```text
daily 09:15 Asia/Hong_Kong
```

Observed next trigger at activation time:

```text
2026-10-25 01:15:00 UTC
= 2026-10-25 09:15:00 Asia/Hong_Kong
```

The service remained a oneshot unit with the previously verified successful manual execution result:

```text
Result=success
ExecMainStatus=0
ActiveState=inactive
SubState=dead
```

Activation did not modify the Production database and did not install a Production source-monitor timer.

### Operational boundary

M8 is operational because the reviewed timer definition is installed, enabled, and active on the Staging VPS.

The first timer-triggered autonomous execution has now been separately recorded and verified. M8 has therefore progressed from enabled/operational to autonomously verified.

## Freeze status

The M8 MVP deployment definition is frozen at the activation baseline above.

Changes to any of the following require regression coverage before rollout:

- scheduler runner behavior;
- systemd service definition;
- timer cadence;
- Staging state-root boundary;
- APP-149 canary lock;
- overlap protection;
- Production-access/write safety guards.

Production source-monitor runtime remains forbidden.


## First autonomous scheduled-run verification

The first timer-triggered run was observed at:

```text
2026-10-25 01:15:08 UTC
= 2026-10-25 09:15:08 Asia/Hong_Kong
```

Runtime identity:

```text
source_id = BD_PNAP_APP149
repo_branch = staging
repo_commit = be0a038ef3f3d5bd666a89e4201768e4de2394ae
run_dir = /var/lib/jason-os/source-monitor-staging/runs/BD_PNAP_APP149/20261025T011508Z
```

Observed monitor result:

```text
decision = NO_CHANGE
action = NONE
baseline_status = UNCHANGED
candidate_downloaded = false
production_access = false
production_write = false
```

systemd result:

```text
Result=success
ExecMainStatus=0
ActiveState=inactive
SubState=dead
```

Stored reference SHA-256 remained unchanged:

```text
4514531e59caf76782120cf83377bcea6ad8a23f076e6b03b2247b193ae8682c
```

The timer remained armed after execution:

```text
enabled = true
active = true
next = 2026-10-26 01:15:00 UTC
```

No manual service start was performed for this proof.

Verification conclusion:

```text
M8 FIRST AUTONOMOUS RUN VERIFICATION: PASS
```

This closes the M8 MVP operational proof: the timer definition, activation state, scheduled execution path, Staging-only safety boundary, retained artifact path, and non-advancing reference behavior have all been observed live.
