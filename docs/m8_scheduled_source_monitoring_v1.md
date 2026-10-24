# M8 — Scheduled Source Monitoring v1

Status: STAGING IMPLEMENTATION / TIMER NOT ENABLED

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
