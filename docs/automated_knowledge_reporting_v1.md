# Jason OS — Automated Knowledge Reporting v1

Status: STAGING
Phase: SR-J
Depends on: SR-G, SR-H, SR-I

## Goal

Make Jason OS knowledge reporting continue to work even when the Windows desktop is turned off and even when ChatGPT Scheduled Tasks are unavailable or at quota.

ChatGPT is the interpretation layer, not the scheduler.

## Architecture

    Windows Anki Desktop
        ↓ localhost AnkiConnect
    SR-G snapshot
        ↓
    Google Drive transport folder
        ↓
    VPS scheduled job
        ↓
    SR-H Knowledge Analytics
        ↓
    SR-I Periodic Assessment
        ↓
    Google Drive Knowledge-Reports
        ↓
    ChatGPT reads latest report when requested

## Responsibility boundaries

### Windows

Windows reads Anki only while the computer is on.

The Windows client:

- calls the frozen SR-G connector;
- writes a timestamped snapshot;
- updates latest.json;
- writes only into a user-selected Google Drive folder;
- performs no Knowledge Brain writes.

The recommended trigger is At logon with Start when available. This provides catch-up behavior after the computer was off.

### Google Drive

Google Drive is transport and report storage, not code Source of Truth.

Recommended folders:

    Jason-OS/
      Anki-Inbox/
        latest.json
        snapshots/
      Knowledge-Reports/
        latest.json
        latest.md
        report_*.json
        report_*.md

The existing dedicated output Drive can be used for both folders. The Business Knowledge Drive remains separate and read-only.

### VPS

The VPS is the reporting scheduler.

The job:

1. pulls Anki-Inbox/latest.json;
2. validates the snapshot;
3. creates an SR-H report if the snapshot is new;
4. keeps immutable SR-H history;
5. compares history with SR-I;
6. adds data-freshness metadata;
7. publishes latest.json and latest.md back to Drive.

### ChatGPT

ChatGPT reads the published report and explains it.

ChatGPT does not need public access to AnkiConnect, an AnkiWeb password, a dedicated Scheduled Task, or direct access to the Windows desktop.

## Data freshness

A report must never imply that old Anki telemetry is current.

SR-J adds snapshot_created_at_utc, report_generated_at_utc, age_hours, and status.

Default MVP rule:

- FRESH: snapshot age <= 48 hours;
- STALE: snapshot age > 48 hours;
- CLOCK_SKEW: snapshot timestamp is materially in the future.

The threshold is configurable.

If the desktop has been off for several days, the VPS may still publish a report, but the report must clearly show that the underlying Anki data is stale.

## Local runtime layout

The orchestrator uses a replaceable work directory:

    <work-dir>/
      inbox/
        latest.json
      analytics/
        <snapshot-time>_<hash>.json
        <snapshot-time>_<hash>.md
      assessments/
        <run-time>_<hash>.json
      publish/
        latest.json
        latest.md
        report_<run-time>.json
        report_<run-time>.md

No Production runtime directory is created by the repository itself.

## Transport

MVP uses the already-connected dedicated Google Drive account through rclone on the VPS.

Default remote locations:

    gdrive-out:Jason-OS/Anki-Inbox
    gdrive-out:Jason-OS/Knowledge-Reports

Both are configurable with environment variables.

The transport module is deliberately separate from analytics so it can later be replaced by HTTPS or another outbound channel without modifying frozen SR-G/SR-H/SR-I layers.

## Scheduling

Scheduling is deliberately outside the Python analytics engine.

For MVP:

- Windows: Task Scheduler at logon;
- VPS: systemd timer or cron, chosen during deployment.

No timer is enabled by repository code. The exact VPS schedule should be decided at deployment time.

## Safety

SR-J v1:

- does not expose AnkiConnect publicly;
- does not modify Anki;
- does not modify Knowledge Brain data;
- does not modify frozen SR-G/SR-H/SR-I code;
- stores no OAuth tokens or credentials in Git;
- uses rclone copy, not destructive remote sync;
- does not claim an absolute measure of human knowledge.

## SR-J validation contract

Before merge:

1. CI orchestration self-test passes;
2. staging can process one snapshot into SR-H + SR-I output;
3. reprocessing the same snapshot does not create duplicate analytics history;
4. data freshness is reported;
5. stale snapshot behavior is verified;
6. Drive pull/publish works against the dedicated output remote;
7. Git working tree remains clean.

Production deployment happens only after staging validation.
