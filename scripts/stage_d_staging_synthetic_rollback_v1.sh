#!/usr/bin/env bash
# Jason OS / Knowledge Brain — Stage D authorized one-shot Staging test.
# Mandatory --execute flag. Exactly one synthetic SQL transaction with
# explicit ROLLBACK, followed by independent zero-persistence readback.
# Does not exercise the original raw-v2 writer, which contains COMMIT.

set -euo pipefail

if [[ "${1:-}" != "--execute" || "${#}" -ne 1 ]]; then
  echo "STAGE D SAFE DEFAULT: no SQL executed"
  echo "Requires exactly one --execute flag for the approved Staging-only test."
  exit 0
fi

STAGING=/opt/ai-knowledge-staging
PROD=/opt/ai-knowledge
DB=jason-os-knowledge-db-staging
ROLE=ai_knowledge_writer_staging
STAGING_SHA=3f1ac00590c8f6dc1e73cc581d4b1aa295498bcd
PROD_SHA=daacbb4557e17790fdef18e492d5b83f4fcf7a23
PY="$STAGING/.venv/bin/python"

# 1. Fail closed against the exact, already reviewed environment.
test "$(git -C "$STAGING" branch --show-current)" = staging
test "$(git -C "$STAGING" rev-parse HEAD)" = "$STAGING_SHA"
test -z "$(git -C "$STAGING" status --porcelain)"
test "$(git -C "$PROD" rev-parse HEAD)" = "$PROD_SHA"
PROD_STATUS="$(git -C "$PROD" status --porcelain)"
test -x "$PY"
test "$(docker inspect -f '{{.State.Running}}' "$DB")" = true
test "$(docker inspect -f '{{.State.Health.Status}}' "$DB")" = healthy
test "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$DB")" = none
test "$(docker inspect -f '{{index .Config.Labels "com.jasonos.environment"}}' "$DB")" = staging
test "$(docker inspect -f '{{index .Config.Labels "com.jasonos.purpose"}}' "$DB")" = knowledge-canary
test "$(docker inspect -f '{{json .NetworkSettings.Ports}}' "$DB")" = '{}'

echo 'STAGE_D_ENVIRONMENT: PASS'

# Reuse the real application role guard in addition to SQL assertions.
(cd "$STAGING" && PYTHONDONTWRITEBYTECODE=1 "$PY" - <<'ROLE_PY'
from staging_db_target_guard_v1 import (
    verify_staging_writer_role,
    STAGING_DB_WRITER_ROLE,
    STAGING_DB_CONTAINER,
)
verify_staging_writer_role(STAGING_DB_CONTAINER, STAGING_DB_WRITER_ROLE)
print('STAGE_D_APPLICATION_WRITER_ROLE_GUARD: PASS')
ROLE_PY
)

# Unique synthetic checksum. Contains no private documents or source content.
CHECKSUM="$("$PY" - <<'PY'
import hashlib
import uuid
print(hashlib.sha256(b'JASON_OS_STAGE_D_ROLLBACK_' + uuid.uuid4().bytes).hexdigest())
PY
)"
[[ "$CHECKSUM" =~ ^[a-f0-9]{64}$ ]]
echo "STAGE_D_SYNTHETIC_CHECKSUM: $CHECKSUM"

# 2. Exactly one psql connection, one transaction. No COMMIT anywhere.
# If a query fails before ROLLBACK, ON_ERROR_STOP closes the connection,
# and PostgreSQL rolls back its uncommitted table rows.
docker exec -i "$DB" psql -X -qAt -v ON_ERROR_STOP=1 \
  -v "test_checksum=$CHECKSUM" -U "$ROLE" -d ai_knowledge -f - <<'SQL'
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '5s';

SELECT CASE WHEN
    current_database() = 'ai_knowledge'
    AND current_user = 'ai_knowledge_writer_staging'
    AND current_setting('transaction_read_only') = 'off'
    AND (SELECT count(*) FROM pg_roles WHERE rolname = current_user
         AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
         AND NOT rolcreaterole AND NOT rolinherit
         AND NOT rolreplication AND NOT rolbypassrls) = 1
    AND NOT EXISTS (SELECT 1 FROM pg_auth_members m
      JOIN pg_roles r ON r.oid = m.member
      WHERE r.rolname = current_user)
    AND (SELECT count(*) FROM pg_class c
         JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
         AND c.relname IN ('documents','chunks','embeddings')
         AND c.relkind IN ('r','p') AND NOT c.relrowsecurity) = 3
    AND (SELECT count(*) FROM public.documents
         WHERE checksum_sha256 = :'test_checksum') = 0
    AND has_table_privilege(current_user, 'public.documents', 'INSERT')
    AND has_table_privilege(current_user, 'public.chunks', 'INSERT')
    AND has_table_privilege(current_user, 'public.embeddings', 'INSERT')
    AND NOT has_table_privilege(current_user, 'public.documents', 'DELETE')
    AND NOT has_table_privilege(current_user, 'public.chunks', 'DELETE')
    AND NOT has_table_privilege(current_user, 'public.embeddings', 'DELETE')
    AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
  THEN 'true' ELSE 'false' END AS stage_d_preflight \gset
\if :stage_d_preflight
\else
  ROLLBACK;
  \echo STAGE_D_PREWRITE_GATE: REFUSED
  SELECT 1 / 0;
\endif

INSERT INTO public.documents (
  title, domain, topic, document_type, authority, jurisdiction,
  source_type, checksum_sha256, language, metadata
) VALUES (
  'STAGE_D_SYNTHETIC_ROLLBACK_ONLY', 'synthetic-staging', 'writer-role-test',
  'test', 'Jason OS Stage D', 'staging-only', 'local-file-v2',
  :'test_checksum', 'en',
  jsonb_build_object('synthetic', true, 'stage', 'D', 'checksum', :'test_checksum')
) RETURNING id AS doc_id \gset

INSERT INTO public.chunks (
  document_id, chunk_index, content, page_start, page_end, metadata
) VALUES (
  :'doc_id'::bigint, 0,
  'SYNTHETIC STAGING TRANSACTION TEST ONLY; NOT SOURCE EVIDENCE',
  NULL, NULL,
  jsonb_build_object('synthetic', true, 'stage', 'D', 'checksum', :'test_checksum')
) RETURNING id AS chunk_id \gset

INSERT INTO public.embeddings (chunk_id, provider, model, dimensions, embedding)
VALUES (
  :'chunk_id'::bigint, 'local', 'multilingual-e5-small', 384,
  ('[0.25,' || repeat('0,', 382) || '0]')::vector
) RETURNING id AS embedding_id \gset

SELECT CASE WHEN count(*) = 1
 AND min(d.checksum_sha256) = :'test_checksum'
 AND min(d.metadata->>'stage') = 'D'
 AND min(c.metadata->>'stage') = 'D'
 AND min(c.chunk_index) = 0
 AND min(e.dimensions) = 384
 AND min(vector_dims(e.embedding)) = 384
 AND min(e.provider) = 'local'
 AND min(e.model) = 'multilingual-e5-small'
THEN 'true' ELSE 'false' END AS stage_d_readback
FROM public.documents d
JOIN public.chunks c ON c.document_id = d.id
JOIN public.embeddings e ON e.chunk_id = c.id
WHERE d.id = :'doc_id'::bigint
  AND c.id = :'chunk_id'::bigint
  AND e.id = :'embedding_id'::bigint
  AND d.checksum_sha256 = :'test_checksum'
\gset

\if :stage_d_readback
  \echo STAGE_D_IN_TRANSACTION_READBACK: PASS
\else
  ROLLBACK;
  \echo STAGE_D_IN_TRANSACTION_READBACK: FAIL_ROLLED_BACK
  SELECT 1 / 0;
\endif

ROLLBACK;
\echo STAGE_D_EXPLICIT_ROLLBACK: COMPLETE
SQL

# 3. New separate PostgreSQL read-only connection verifies no persisted rows.
RESULT="$(docker exec -i "$DB" psql -X -qAt -v ON_ERROR_STOP=1 \
  -v "test_checksum=$CHECKSUM" -U "$ROLE" -d ai_knowledge -f - <<'SQL'
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT CASE WHEN
  current_user = 'ai_knowledge_writer_staging'
  AND (SELECT count(*) FROM public.documents
       WHERE checksum_sha256 = :'test_checksum') = 0
  AND (SELECT count(*) FROM public.chunks c JOIN public.documents d
       ON d.id = c.document_id
       WHERE d.checksum_sha256 = :'test_checksum') = 0
  AND (SELECT count(*) FROM public.embeddings e JOIN public.chunks c
       ON c.id = e.chunk_id JOIN public.documents d
       ON d.id = c.document_id
       WHERE d.checksum_sha256 = :'test_checksum') = 0
THEN 'STAGE_D_POST_ROLLBACK_ZERO_PASS'
ELSE 'STAGE_D_POST_ROLLBACK_ZERO_FAIL' END;
ROLLBACK;
SQL
)"
test "$RESULT" = STAGE_D_POST_ROLLBACK_ZERO_PASS
echo "$RESULT"

# 4. Integrity checks and explicit safety conclusion.
test "$(git -C "$STAGING" rev-parse HEAD)" = "$STAGING_SHA"
test -z "$(git -C "$STAGING" status --porcelain)"
test "$(git -C "$PROD" rev-parse HEAD)" = "$PROD_SHA"
test "$(git -C "$PROD" status --porcelain)" = "$PROD_STATUS"
echo 'STAGE_D_SYNTHETIC_TRANSACTION_ROLLBACK: PASS'
echo 'Note: PostgreSQL sequence counters can advance despite ROLLBACK.'
