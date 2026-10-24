# M4 — VPS Staging Live Verification

Status: LIVE VERIFIED  
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

## Live verification record

Verified on 2026-10-24.

- VPS Staging path: `/opt/ai-knowledge-staging`
- deployed commit: `921e899fed7109b526700b470a5eeaa32d4539f2`
- candidate: `BD_PNAP_APP146`
- approved checksum: `60127b85a99b2a2931975ced68200cc0c468744c8d0df30a2e94e287dcd8a61e`
- route: `multimodal-v2`
- Staging document ID: `4`
- chunks: `12`
- evidence origins observed:
  - `native_text`: 11
  - `visual_understanding`: 1
- semantic query results: 10
- expected terms matched: `hinge`, `stopper`
- final Staging status: `VALIDATED`
- final status: `READY_FOR_PRODUCTION_REVIEW`
- Production write: false
- command block exit code: 0

The APP146 qualification exercised page-level Vision evidence. It did not contain a structured-table retrieval chunk, so M1 code is deployed to VPS Staging but table-specific live evidence remains a separate future canary if needed.

## After success

1. keep Production unchanged;
2. treat M2 as VPS LIVE VERIFIED;
3. treat M1 as deployed to VPS Staging, with table-specific live proof not yet exercised by APP146;
4. proceed to Generic Production Promotion v2 live verification through non-writing gates first.