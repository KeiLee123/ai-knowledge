#!/usr/bin/env bash
# M11 PR #101: isolated, read-only VPS Staging retrieval acceptance.
# Requires EXPECTED_PR_HEAD (exact 40-hex PR commit) and pinned P0 Staging.
# Only fetch the PR object + this script into a private temp directory.
# No staging checkout, DB schema, Production, Drive or model-generation writes.
set -euo pipefail
umask 077

ROOT="/opt/ai-knowledge-staging"
BASE="6ae6d9c7f29b0fd2c9b5b2ee49e7ccf23de363c1"
SHA_PDF="a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8"
SHA_MODULE_BLOB="a1f6297650427cce363a4c764f93fdafbcd404fb"
DOC_URL="https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnap/APP/APP149.pdf"

test "$EXPECTED_PR_HEAD" != "" && [[ "$EXPECTED_PR_HEAD" =~ ^[a-f0-9]{40}$ ]]
test -d "$ROOT/.git"
test -x "$ROOT/.venv/bin/python"
test "$(git -C "$ROOT" branch --show-current)" = "staging"
test "$(git -C "$ROOT" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(git -C "$ROOT" rev-parse "$EXPECTED_PR_HEAD^{commit}")" = "$EXPECTED_PR_HEAD"

TMP="$(mktemp -d /tmp/jason-m11-pr101-readonly-XXXXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT

# Copy a single module from the exact PR object. No git checkout/worktree edits.
git -C "$ROOT" show "$EXPECTED_PR_HEAD:m11_automated_quality_probe_v1.py" > "$TMP/m11_automated_quality_probe_v1.py"
test "$(git -C "$ROOT" hash-object "$TMP/m11_automated_quality_probe_v1.py")" = "$SHA_MODULE_BLOB"

# Official public file is verified byte-for-byte against previously pinned
# APP149. This does not establish that the document is current law.
curl --fail --show-error --silent --location --proto '=https' \
  --proto-redir '=https' --tlsv1.2 --max-time 60 --max-filesize 3000000 \
  --output "$TMP/APP149.pdf" "$DOC_URL"
test "$(sha256sum "$TMP/APP149.pdf" | cut -d' ' -f1)" = "$SHA_PDF"

# Offline M11 scanner + existing Staging read-only retrieval only.
# Credentials for external answer-generation models are withheld.
env -u DEEPSEEK_API_KEY -u JASON_BETA_LLM_API_KEY -u OPENAI_API_KEY \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT" \
  "$ROOT/.venv/bin/python" - "$TMP/m11_automated_quality_probe_v1.py" "$TMP/APP149.pdf" <<'PY'
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys

script, pdf = map(Path, sys.argv[1:])
expected_root = Path("/opt/ai-knowledge-staging").resolve()
spec = importlib.util.spec_from_file_location("m11_pr101_probe", script)
if spec is None or spec.loader is None:
    raise SystemExit("M11_PR101_REFUSED: module_loader_unavailable")
module = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(module)

# Verify imports came from the guarded, clean Staging checkout, not Production.
if Path(module.qa.__file__).resolve() != expected_root / "beta_ask_staging_v1.py":
    raise SystemExit("M11_PR101_REFUSED: wrong_qa_import")
import validate_staging_retrieval_v2 as retrieval
if (retrieval.DEFAULT_EMBED_URL != "http://127.0.0.1:8088/embed"
        or retrieval.STAGING_DB_CONTAINER != "jason-os-knowledge-db-staging"):
    raise SystemExit("M11_PR101_REFUSED: unexpected_endpoint_or_database")

# Any PDF tool diagnostics on stdout remain in memory (not the terminal).
with contextlib.redirect_stdout(io.StringIO()):
    report = module.build_report(pdf, include_retrieval=True)

def need(ok, why):
    if not ok:
        raise SystemExit("M11_PR101_REFUSED: " + why)

doc = report["document"]
silver = report["evidence_verifier"]
r = report["retrieval"]
need(report["environment"] == "staging_retrieval_readonly", "environment")
need(report["source_id"] == "BD_PNAP_APP149", "source_identity")
need(doc["source_sha256"] == "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8", "pdf_sha")
need(doc["physical_pages"] == 5, "page_count")
need(silver["case_count"] == 5, "silver_inventory")
need((silver["auto_evidence_checked"], silver["auto_hold_unverified"],
      silver["auto_rejected_evidence"]) == (1, 4, 0), "silver_regression")
need(silver["official_gold_approved"] == 0, "gold_claim")
need(report["answer_correctness_accuracy"] == "UNKNOWN_NOT_MEASURED", "answer_accuracy_claim")
need(report["anki_card_accuracy"] == "UNKNOWN_NOT_MEASURED", "anki_accuracy_claim")
for field in ("external_ai_called", "shared_db_write", "canonical_drive_write",
              "production_write", "anki_package_created"):
    need(report[field] is False, "unexpected_" + field)
need(r["tested_source"] == "BD_PNAP_APP149", "retrieval_source")
need(r["current_law_question"] == "CURRENTNESS_UNVERIFIED_ABSTAIN", "currentness_guard")
need(r["semantic_answer_accuracy"] == "NOT_MEASURED", "semantic_claim")
need(r["proposed_pages_are_not_official_gold"] is True, "unverified_gold_claim")
cases = r["cases"]
need(len(cases) == 3, "retrieval_cases")
ranks = {}
for case in cases:
    cid = case["case_id"]
    need(cid in ("APP149-DRAFT-P01", "APP149-DRAFT-P02",
                 "APP149-DRAFT-M01") and cid not in ranks, "unexpected_case")
    need(case["all_indexed_chunks_returned"] is True, "incomplete_index")
    need(case["answer_generated"] is False and
         case["answer_correctness_verified"] is False, "answer_claim")
    rank = case["first_proposed_page_rank"]
    need(type(rank) is int and 1 <= rank <= 8, "missing_proposed_page")
    ranks[cid] = rank

# Redacted metadata only: never print raw queries, PDF excerpts or credentials.
print("M11_PR101_RETRIEVAL_PAGES:", json.dumps(ranks, sort_keys=True))
print("M11_PR101_SILVER_COUNTS: checked=1 held=4 mismatches=0")
print("M11_PR101_CURRENTNESS: CURRENTNESS_UNVERIFIED_ABSTAIN")
print("M11_PR101_ANSWER_ACCURACY: UNKNOWN_NOT_MEASURED")
print("M11_PR101_PROPOSED_PAGES_ARE_NOT_GOLD: true")
if all(rank <= 2 for rank in ranks.values()):
    print("M11_PR101_VPS_STAGING_READONLY_ACCEPTANCE: PASS")
else:
    print("M11_PR101_VPS_STAGING_READONLY_ACCEPTANCE: RANKING_REVIEW_REQUIRED")
    raise SystemExit(4)
PY

# Confirm the live checked-out Staging source remained unmodified.
test "$(git -C "$ROOT" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$ROOT" status --porcelain)"
echo "M11_PR101_STAGING_WORKTREE: CLEAN"
