# Knowledge Brain — Agent / Codex Operating Rules

This is a **task router**, not a request to read the whole repository.

1. First read `docs/CURRENT_STATE.md` (short dated index); confirm the current GitHub branch SHA, open target Issue/PR and the date of that snapshot. If stale, reconcile before action.
2. Read `docs/DEVELOPMENT_GOVERNANCE.md` for delivery, evidence, handover and safety. For a task, read only relevant modules, tests and linked decisions. Do NOT bulk-load docs, historical chats or all repo files.
3. Product scope and priorities: the approved Google Drive Beta-First Product Contract (linked from README). GitHub owns code; Drive owns canonical documents and decisions. Do not silently redefine a decision in a code file.
4. At most **one active feature delivery** plus one independent urgent safety fix per repository, unless the owner explicitly approves an exception. Before adding a module/test/workflow, explain which user failure it addresses and which existing function can be reused.
5. Protect frozen Graph-aware Retrieval/Answer v1.3, M8/M9 source monitors, Production/main, approved source identity/checksums, Google Drive Current, personal Anki collection and Hermes/VPS security boundaries. Do not run Production-default scripts or external model endpoints without explicit operational approval.
6. A PR must identify: base/head SHA, changed paths, risks, tests and exact evidence, staging acceptance gaps, rollback, and next action. Never infer VPS state from GitHub. Distinguish `DESIGNED`, `CODED`, `CI_PASS`, `STAGING_ACCEPTED`, `USER_BETA`, `PRODUCTION_VERIFIED`.
7. **End of every coding task:** update the task Issue/PR handover with what changed, evidence links, what is NOT verified, blockers and a single next step. Propose a minimal `CURRENT_STATE.md` update when a milestone/active task/SHA changes. Keep the snapshot short, avoid duplicating source files.
8. Unknown, ambiguous or current-law-sensitive professional claims: fail closed/abstain rather than invent source authority or label machine checks as independently verified semantic accuracy.
9. This instructions file does **not** authorize installation, deployment, approval, deletion or production writes.
