# M4 — VPS Staging Live Verification

Status: RUNBOOK READY  
Environment: VPS Staging only  
Production impact: NONE

## Purpose

M4 live-verifies the consolidated Jason OS Knowledge Staging lifecycle after:

- M1 structured-table retrieval evidence;
- M2 official-source multimodal Staging close-loop;
- M3 release artifact profiles.

The qualification candidate is `BD_PNAP_APP146`.

M4 does not merge `staging` to `main`, does not deploy to Production, does not populate a Production release contract, and does not authorize a Production write.

## Expected architecture

```text
APP146 official source
      |
      v
baseline / checksum gate
      |
      v
Drive Staging + Canonical verification
      |
      v
router -> multimodal-v2
      |
      v
guarded multimodal v2 Staging write
      |
      v
isolated Staging DB
      |
      v
semantic retrieval validation
      |
      v
READY_FOR_PRODUCTION_REVIEW
```

## Safety boundary

The live run must satisfy all of the following before ingestion:

- repository path is `/opt/ai-knowledge-staging`;
- Git branch is exactly `staging`;
- worktree is clean before update;
- update is fast-forward only;
- Staging DB is fixed to `jason-os-knowledge-db-staging`;
- Staging DB container labels match the canary contract;
- Staging DB network mode is `none`;
- Staging DB publishes no ports;
- Production DB target is forbidden by the canary guard;
- no Production script is invoked by this runbook;
- Tesseract exists and the configured OCR languages are available;
- Hermes Vision environment is readable without printing secrets.

## Live verification sequence

### 1. Update Staging from GitHub

Use `git merge --ff-only origin/staging`.

Record the deployed commit.

### 2. Dependency preflight

Verify:

- Python venv exists;
- `tesseract` exists;
- `eng` and `chi_tra` OCR languages exist;
- Hermes environment file exists;
- `DEEPSEEK_API_KEY` is configured without printing its value;
- `rclone` exists.

### 3. Runtime isolation guard

Run:

```bash
.venv/bin/python run_multimodal_canary_v2.py --verify-only
```

Required result:

```text
CANARY GUARD: PASS
No ingestion command executed.
```

### 4. APP146 read-only plan

Run the official-source orchestrator without `--execute`.

Required properties:

- `recommended_pipeline` = `multimodal-v2`;
- `pipeline` = `multimodal-v2`;
- `production_write` = false;
- final status = `OFFICIAL_SOURCE_PLAN_READY`.

If `SOURCE_CHANGED_REVIEW_REQUIRED` appears, stop. Do not update the baseline automatically.

### 5. APP146 Staging execution

Run with both explicit Staging flags:

```text
--execute
--confirm-staging-processing
```

The orchestrator may reuse already-verified Drive objects and an existing checksum-matching Staging document.

If the Staging document does not exist, it may:

- create the approved Drive Staging object;
- create the approved Canonical Current object;
- invoke the guarded Multimodal v2 Staging writer;
- generate OCR / Vision / structured-table evidence as selected by the existing v2 gates;
- create Staging chunks and embeddings.

### 6. Semantic retrieval validation

M2 automatically runs the read-only Staging validator for APP146:

```text
query:
What safety measures are recommended for swing-type and sliding metal gates?

expected terms:
hinge
stopper
```

Required final status:

```text
STATUS: READY_FOR_PRODUCTION_REVIEW
```

## Success criteria

M4 is LIVE VERIFIED only when the run records all of the following:

- deployed Git commit;
- canary guard PASS;
- APP146 route = `multimodal-v2`;
- Staging DB document exists for the approved checksum;
- semantic retrieval validation passes;
- expected terms are found;
- final `staging_status` = `VALIDATED`;
- final `production_ready` = true;
- final `production_write` = false;
- no Production command or write is executed.

## Failure handling

Fail closed.

Do not retry with weaker flags and do not change the approved baseline during the same run.

If Vision fails because Hermes configuration is unavailable, repair the Staging dependency and rerun M4. Do not bypass the Vision gate by changing the router or source profile.

If the official source checksum changed, treat it as a new source-review event rather than an ingestion failure.

## After success

After M4 is live-verified:

1. update the capability/status documents with the deployed commit and APP146 proof;
2. keep Production unchanged;
3. proceed to the next Production-v2 live verification milestone only through read-only Production gates first.
