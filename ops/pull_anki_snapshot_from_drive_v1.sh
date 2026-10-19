#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <local-latest-json>" >&2
    exit 2
fi

DEST="$1"
REMOTE="${JASON_ANKI_INBOX_REMOTE:-gdrive-out:Jason-OS/Anki-Inbox}"
SOURCE="${REMOTE%/}/latest.json"

mkdir -p "$(dirname "$DEST")"

TMP="${DEST}.tmp"

rm -f "$TMP"

rclone copyto "$SOURCE" "$TMP"

python3 - "$TMP" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(
    path.read_text(
        encoding="utf-8"
    )
)

if (
    payload.get("schema_version")
    != "anki-review-snapshot-v1"
):
    raise SystemExit(
        "Unexpected snapshot schema: "
        + repr(
            payload.get(
                "schema_version"
            )
        )
    )

if not payload.get(
    "created_at_utc"
):
    raise SystemExit(
        "Snapshot created_at_utc missing"
    )

print(
    "Snapshot validation: PASS"
)
PY

mv -f "$TMP" "$DEST"

echo "Pulled: $SOURCE"
echo "Local:  $DEST"
