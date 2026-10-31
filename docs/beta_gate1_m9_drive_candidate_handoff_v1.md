# Beta Gate 1A — M9 changed PDF → Versioned Google Drive Staging

Status: Engineering staging candidate handoff. **Not a deployed timer hook** and **not a complete Beta auto-ingestion flow**. Does not supersede M9D Frozen schedule.

## Why this is a product step

M9's existing systemd batch monitor discovers official BD PNAP document updates. When it reports CANDIDATE_NEW_VERSION it stores a checked PDF under a protected Staging runtime run directory, but does not deliver that file into Google Drive automatically. This standalone adapter **reuses that real M9 output and existing Drive writer** to close one missing link without changing Frozen M8/M9 code.

Flow:

Official PDF / M9 batch run → persisted \`monitor-output.txt\` → strict source & SHA check → immutable, content-addressed \`gdrive-bd-write:_Staging_Incoming/APP/_versioned_candidates/<SOURCE>/<SHA256>.pdf\` → Drive download round-trip checksum.

It does **not** advance a version reference, replace Current, update the Staging DB, promote to Production or schedule itself. A subsequent explicitly approved integration must connect versioned candidate staging to the existing Staging Source Processing Pipeline and then the scheduler through a **separate replaceable component**, after a real Drive write and rollback gate.

## File and command

\`beta_stage_monitor_candidate_v1.py\`

The only supported executable mode is on the clean \`staging\` branch at \`/opt/ai-knowledge-staging\`, using the fixed Source Registry and runtime state root \`/var/lib/jason-os/source-monitor-staging\`.

Default is READ-ONLY (safe preview):

\`\`\`bash
.venv/bin/python beta_stage_monitor_candidate_v1.py \
  --source BD_PNAP_APP149 \
  --run-dir /var/lib/jason-os/source-monitor-staging/runs/BD_PNAP_APP149/<M9_RUN_STAMP>
\`\`\`

The latest **real M9-generated** run directory must come from the actual systemd evidence. A \`NO_CHANGE\` outcome returns safely without running rclone or writing a new copy.

Only when a *genuine* monitored changed candidate is present and an operator explicitly authorizes the append-only destination:

\`\`\`bash
.venv/bin/python beta_stage_monitor_candidate_v1.py \
  --source BD_PNAP_APP149 \
  --run-dir /var/lib/jason-os/source-monitor-staging/runs/BD_PNAP_APP149/<M9_RUN_STAMP> \
  --confirm-drive-staging-write
\`\`\`

Do not use this flag with fabricated M9 logs or synthetic PDFs on real Drive. Source files are NOT included in GitHub. If no genuine changed candidate exists yet, keep the real upload acceptance PENDING. Do not force government document changes or touch M9 reference state to manufacture a run.

## Runtime contracts

- Only the currently registered \`BD_PNAP_APP\` family with an authorized \`gdrive-bd-write:\` remote and \`_Staging_Incoming/APP/\` prefix.
- Monitor output must be from the exact \`runs/<SOURCE>/<UTC_STAMP>\` directory and contain \`CANDIDATE_NEW_VERSION + STAGING_VALIDATION_REQUIRED + DOCUMENT_CHANGED\`, \`candidate_downloaded=true\`, and explicit \`production_access=false\`, \`production_write=false\`.
- Other decisions (\`POLICY_BLOCKED\`, \`EXCEPTION_REVIEW\`, bad SHA, wrong source, symlink path, wrong filename, invalid PDF magic or oversized candidate) fail closed. \`NO_CHANGE/NONE\` is a no-op.
- Check original candidate SHA before Drive operations, then after upload read the remote object back and SHA check. Destination is full SHA content-addressed and \`rclone --immutable\` forbids a conflicting overwrite. Re-run with a verified existing object returns \`ALREADY_STAGED_VERIFIED\`, no duplicate.
- No write to \`Current/\`, DB, Source Registry, snapshots, M8/M9 frozen timers or Production. Output reports only location, source, SHA and workflow state; it does not dump PDF body text.

## Quality-linked tests

\`test_beta_stage_monitor_candidate_v1.py\` checks M9 log structure and a fake rclone roundtrip integration, with unchanged/no-op, SHA tampering, blocked/ambiguous decisions, false production safety flags, source identity, symlink/path crossing, non-PDF/oversized, duplicate upload, existing-remote mismatch, unsafe target and an unchanged local artifact at upload time. It deliberately does not claim a real Drive upload from synthetic CI.

The existing full \`.github/workflows/validation.yml\` includes this focused suite rather than creating a fifteenth near-identical standalone M10 workflow. Frozen regressions continue to run.

## Acceptance and next Beta step

Gate A: GitHub PR checks and staging Full Validation PASS on exact SHA.
Gate B: VPS Staging local regression and read-only inspection of a real M9 run PASS, branch/clean worktree evidence.
Gate C: Genuine changed PDF (future, if available) staged under the authorized versioned Drive path, SHA roundtrip verified, no Current/Production changes.
Gate D: After controlled Staging source-processing integration and an independent version diff/answer proof, separately authorize a second automatic post-batch runner **without editing Frozen M9 units**.

Gate A/B do not imply Gate C/D are complete. HKeL periodic Watch Mode and automatic Knowledge DB indexing are still separate Beta #59 tasks. Do not expose VPS ports or activate legal Production writes.

Design contract: https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit
Beta issue: https://github.com/KeiLee123/ai-knowledge/issues/59
