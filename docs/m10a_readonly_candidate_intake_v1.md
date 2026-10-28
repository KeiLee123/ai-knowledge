# M10A — Read-only Candidate Intake v1

Status: LOCAL FIXTURE VERIFIED / FEATURE BRANCH / NOT DEPLOYED.
Architecture: https://docs.google.com/document/d/1dYNlvmkSuGJgXjf83xMd1kZ5VEv-aQpapNlEGFjr5uQ/edit

M10A reads frozen M9 batch summaries from `batches/<timestamp>/summary.json`, and cross-checks individual `runs/<source_id>/<timestamp>/monitor-output.txt` evidence. It does not download data, ingest, write state, call Google Drive, touch a database or change frozen scheduling.

## Invocation

```bash
python m10_candidate_intake_v1.py --summary /var/lib/jason-os/source-monitor-staging/batches/<UTC_TIMESTAMP>/summary.json
python test_m10_candidate_intake_v1.py
```

Staging-only path and Production flags are validated. Each candidate must be an existing PDF under its M9 run directory whose SHA matches the monitor result. Accepted Staging reference identity, source ID, monitor decision/action and prior issue/revision dates are checked. If any source has contradictory evidence, it is BLOCKED without suppressing other sources.

`READY_FOR_STAGING_VALIDATION` means only intake validity, **not** successful validation, qualification, Drive Current replacement, source baseline advancement or Production authorization.

M9's existing output does not cryptographically bind the accepted reference snapshot at observation time: M10B must add a stronger time-of-observation reference fingerprint and re-evaluate version policy before Staging ingestion. This is a known limitation of this read-only bridge.

Tests cover valid intake, determinism, no writes, NO_CHANGE, REVIEW_REQUIRED, BLOCKED, forged monitor/batch mismatch, Production flag, stale reference, tampered bytes, symlink escape, and multi-source failure isolation.

CI workflow is unchanged. Run this new regression standalone; existing M9/M8 regressions remain authoritative. No VPS or Production deployment is performed by this PR.
