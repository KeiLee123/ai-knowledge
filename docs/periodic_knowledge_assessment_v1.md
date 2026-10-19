# Jason OS — Periodic Knowledge Assessment v1

Status: STAGING
Phase: SR-I
Depends on: SR-G Anki Sync Connector, SR-H Knowledge Analytics

## Purpose

SR-I turns individual Knowledge Analytics reports into a time-series assessment.

Anki remains responsible for card scheduling.
SR-I schedules and compares analytics reports; it does not replace Anki or FSRS.

## Architecture

```text
Anki Desktop
    ↓
SR-G read-only review snapshot
    ↓
SR-H knowledge analytics report
    ↓
history of immutable reports
    ↓
SR-I periodic assessment
    ↓
weekly / monthly knowledge report
```

Transport from the user's device to Jason OS is deliberately replaceable.

The analytics contract must not depend on whether reports arrive by HTTPS, a local sync agent,
a temporary file transfer, or another approved outbound mechanism.

## MVP scope

SR-I v1 reads two or more `knowledge-analytics-report-v1` JSON files and produces:

- current knowledge coverage;
- change in reviewed-card coverage;
- observed review-rating changes;
- current weak-card and repeated-failure counts;
- changes in weak-card counts;
- topic-level coverage changes;
- topic-level weak-area changes;
- current data-sufficiency level;
- warnings when reports cannot be compared safely.

The first report establishes a baseline.
A trend requires at least two compatible reports.

## Compatibility rules

Reports are comparable only when:

- schema is `knowledge-analytics-report-v1`;
- deck scope is the same;
- required tag scope is the same;
- reports are ordered by their creation timestamp.

A changed mapped-card denominator is allowed, but must be reported.
A partial review window must be surfaced as a warning.

Negative changes in reviewed-card count must not automatically be called forgetting;
they may be caused by deck/card changes.

## Knowledge Growth

Knowledge Growth is an observed learning-progress estimate, not an absolute knowledge score.

Signals include:

```text
reviewed-card coverage delta
review-event delta
topic coverage delta
weak-card count delta
repeated-failure count delta
FSRS retrievability trend when available
```

A single Good/Easy session is descriptive only.
SR-I inherits SR-H's data-sufficiency label and must not manufacture confidence.

## Periodic report structure

```text
Current coverage
Coverage change
Observed recall signals
Weak-area trend
Repeated-failure trend
Topic changes
Source/topic areas to revisit
Data sufficiency
Warnings
```

## Storage

MVP stores reports as immutable JSON files.

Suggested future runtime layout:

```text
/var/lib/jason-os/knowledge-assessment/
  reports/
  assessments/
```

No production path is created by SR-I code itself.

A later deployment step may decide the final runtime path.

## Scheduling

Scheduling is outside the analytics engine.

Recommended future orchestration:

```text
Windows Anki machine
  Task Scheduler
    → SR-G snapshot
    → secure outbound transport

VPS
  scheduled job
    → SR-H report
    → append immutable report
    → SR-I weekly/monthly assessment
```

The local AnkiConnect endpoint remains localhost-only.

## Safety

SR-I v1:

- performs no Anki writes;
- performs no Knowledge Brain DB writes;
- performs no card deletion;
- performs no scheduler changes;
- does not expose AnkiConnect publicly;
- does not claim an absolute measure of human knowledge.

## SR-I validation contract

Using deterministic report fixtures, SR-I must correctly produce:

1. baseline/current report count;
2. reviewed-card coverage delta;
3. review-event delta;
4. weak-card delta;
5. repeated-failure delta;
6. topic-level reviewed-card delta;
7. topic-level weak-card delta;
8. a baseline-only insufficient-trend case;
9. explicit warnings for incompatible or partial-window data.

Runtime validation should then use a real SR-H report plus a synthetic earlier baseline.
