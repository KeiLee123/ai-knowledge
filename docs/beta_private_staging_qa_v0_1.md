# Knowledge Brain — Private Beta Staging Q&A v0.1

Status: ADDITIVE GITHUB STAGING CANDIDATE. Not a web app, not publicly exposed,
not a Production deployment, and not an independent professional-answer approval.

## Architecture

User's question (local VPS CLI)
  → fixed APP145 / APP149 source allowlist in Source Registry
  → fixed approved baseline SHA256 in Source Monitor Staging state
  → existing Staging runtime + DB integrity guard (checks chunk+embedding counts)
  → existing local E5 embedding and checksum-scoped Staging retrieval (Top 5)
  → source page, official URL, chunk metadata + original evidence
  → optional explicitly authorized external-model draft
  → deterministic citation-reference validation, human review required

No change to Frozen Graph-aware Retrieval v1.3, Answer v1.3, M8/M9,
Source Registry, approved baseline, Current Drive, Production DB, or Anki.

## First operator command — evidence only (safe default)

From a clean checkout at /opt/ai-knowledge-staging on the staging branch:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python beta_ask_staging_v1.py \
      --source BD_PNAP_APP145 \
      --top-k 5 \
      --full-evidence \
      "Under APP-145, which enforcement authority handles building construction and which handles fire service installations?"

This reads only Staging DB jason-os-knowledge-db-staging and the existing
baseline/registry, uses local embedding on 127.0.0.1, and prints original
source page and official URL for the retrieved evidence. It does NOT claim
that the mere presence of 5 chunks establishes a correct answer.

Expected source on the known real query: APP145 paragraph 9, page 3,
is chunk 115, ranked #3 in the 2026-10-31 VPS trace. That is an operator
observation, not an embedded acceptance shortcut.

## Optional AI draft — explicit separate operator approval

The feature can ask the DeepSeek Chat Completions API to draft a response
from ONLY the retrieved publicly available BD excerpts. It does not
receive VPS credentials, private Drive documents, or other source families.

Never store credentials in GitHub. Set JASON_BETA_LLM_API_KEY through the
operator's approved secret mechanism. The script intentionally does not read
the existing Production answer layer or Production .env. Supported model
selection: JASON_BETA_MODEL=deepseek-flash (default), or deepseek-v4-pro.

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python beta_ask_staging_v1.py \
      --source BD_PNAP_APP145 \
      --generate-answer \
      --confirm-external-api \
      "Under APP-145, which enforcement authority handles building construction and which handles fire service installations?"

External model calls require BOTH flags and a nonempty
JASON_BETA_LLM_API_KEY. The script does not accept arbitrary API URLs.
The output uses JSON mode and enforces known source markers [S1] ... [S5].
An invalid/empty/truncated model output fails closed. An insufficient
evidence decision produces a system-owned abstention. A citation-valid
model response is still labeled DRAFT_REVIEW_REQUIRED: syntactically
valid references cannot guarantee factual support or legal correctness.

## Limitations and safeguards

- Only APP145 and APP149 are allowed. No cross-source answers yet.
- Source version is identified by approved PDF SHA256. Revision date and
  current legal applicability are NOT VERIFIED by this entrypoint.
- The official URL and PDF page are grounded in Source Registry + Staging DB.
- The system does not send any content to an external API in the default mode.
- External generation sends only the question + bounded public BD excerpts,
  by explicit operator opt-in.
- No web UI, port, server, daily timer, or automated publishing.
- No per-question history or persistent chat data is stored.
- This is a constrained operator-driven Private Beta slice; a normal user
  interface and independent citation/answer-quality acceptance are pending.

## Quality gate

Run focused tests:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python test_beta_ask_staging_v1.py

Then on live Staging run the evidence-only command with APP145. Check:
- Staging-only, read-only, no Production write
- page 3 paragraph 9 is retrieved and source URL resolves
- correct PDF checksum and expected Staging DB integrity
- no misleading claim that this index proves October 2010 is current law
- complete AI draft and human-revised answer only after explicit permission
- at least 5 professional user questions, one genuine insufficient-evidence
  case, source links and reviewer feedback before declaring Beta ready

Gate1 official new-version Drive candidate → versioned isolated Staging
index, HKeL Watch, Private Beta UI, Anki cards remain separate OPEN tasks.

Related issues: https://github.com/KeiLee123/ai-knowledge/issues/60
Architecture decision:
https://docs.google.com/document/d/1dfIGsY_VDwXS_B-DSlNtAB8SkOsvGkx5b-owgqSgQMQ/edit
