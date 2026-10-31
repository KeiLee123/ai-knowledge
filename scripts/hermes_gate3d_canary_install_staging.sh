#!/usr/bin/env bash
# Hermes Gate 3D-B: create isolated, inert MCP canary files in existing /opt/data.
# No MCP config activation; no service restart; no new mounts, ports, DB or LLM.
set -euo pipefail
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "CANARY STOPPED (exit $rc). Do not rerun before inspecting partial release." >&2; fi' EXIT

REPO="/opt/ai-knowledge-staging"
EXPECTED="57315d3ea2859bd4ccef89ccd2bba19f05679fb4"
CID="hermes-rgu4flce2juuzyq6idzr49z2"
HOST_SNAPSHOTS="/var/lib/jason-os/hermes-pnap-snapshots-staging"
RELEASE="/opt/data/jason-os-pnap-staging"
PYTHON="/opt/hermes/.venv/bin/python"

cd "$REPO"
export PYTHONDONTWRITEBYTECODE=1

echo "=== 1. IMMUTABLE SOURCE AND TARGET PREFLIGHT ==="
test "$(git branch --show-current)" = "staging"
test "$(git rev-parse HEAD)" = "$EXPECTED"
test -z "$(git status --porcelain)"
test "$(docker inspect -f '{{.State.Running}}' "$CID")" = "true"
test "$(docker inspect -f '{{.Config.User}}' "$CID")" = "root"
test "$(docker inspect -f '{{.HostConfig.Privileged}}' "$CID")" = "false"
test "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/opt/data"}}{{.RW}}{{end}}{{end}}' "$CID")" = "true"

docker exec "$CID" sh -c 'test ! -e /opt/data/jason-os-pnap-staging && test ! -L /opt/data/jason-os-pnap-staging'
docker exec "$CID" setpriv --reuid=65534 --regid=65534 --clear-groups \
  /usr/bin/env -i PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -c \
  'import os; assert os.geteuid() == 65534; assert os.access("/opt/data", os.X_OK), "UID 65534 cannot traverse /opt/data; do NOT chmod it"; assert not os.access("/opt/data/.env", os.R_OK), "Secrets readable by UID 65534"'

python3 - "$HOST_SNAPSHOTS" <<'PY'
import json
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
approved = {
    "BD_PNAP_APP145": (
        "dc3262cc55c5fd79d29f337fd811cdd871543f59d795972d9f30f558e313127c",
        "APP145.pdf",
    ),
    "BD_PNAP_APP149": (
        "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8",
        "APP149.pdf",
    ),
}
assert root.is_dir() and not root.is_symlink()
assert stat.S_IMODE(root.stat().st_mode) == 0o700
for source_id, (checksum, filename) in approved.items():
    path = root / (source_id + ".json")
    assert path.is_file() and not path.is_symlink()
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert path.stat().st_size <= 300000
    packet = json.loads(path.read_text(encoding="utf-8"))
    assert packet["schema_version"] == "hermes-approved-snapshot-v0.1"
    assert packet["source_id"] == source_id
    assert packet["approved_pdf_sha256"] == checksum
    assert packet["official_pdf_url"].startswith("https://www.bd.gov.hk/")
    assert packet["official_pdf_url"].endswith("/" + filename)
    assert packet["environment"] == "staging"
    assert packet["read_only_source"] is True
    assert packet["answer"] is None
    assert packet["current_legal_applicability"] == "NOT_VERIFIED"
    assert packet["chunk_count"] == len(packet["chunks"]) == 8
    print(source_id, "HOST VERIFIED", packet["chunk_count"], "chunks")
PY

CONFIG_BEFORE="$(docker exec "$CID" sha256sum /opt/data/config.yaml | cut -d ' ' -f 1)"

echo "=== 2. STAGE EXACTLY THREE FILES (NO CONFIG CHANGE) ==="
docker exec "$CID" mkdir -m 0700 "$RELEASE"
docker exec "$CID" mkdir -m 0700 "$RELEASE/snapshots"
docker cp "$REPO/beta_hermes_mcp_snapshot_stdio_v1.py" "$CID:$RELEASE/server.py"
for SOURCE in BD_PNAP_APP145 BD_PNAP_APP149; do
  docker cp "$HOST_SNAPSHOTS/$SOURCE.json" "$CID:$RELEASE/snapshots/$SOURCE.json"
done

docker exec "$CID" chown root:root \
  "$RELEASE" "$RELEASE/snapshots" "$RELEASE/server.py" \
  "$RELEASE/snapshots/BD_PNAP_APP145.json" \
  "$RELEASE/snapshots/BD_PNAP_APP149.json"
docker exec "$CID" chmod 0555 "$RELEASE" "$RELEASE/snapshots"
docker exec "$CID" chmod 0444 \
  "$RELEASE/server.py" \
  "$RELEASE/snapshots/BD_PNAP_APP145.json" \
  "$RELEASE/snapshots/BD_PNAP_APP149.json"

for NAME in server.py snapshots/BD_PNAP_APP145.json snapshots/BD_PNAP_APP149.json; do
  case "$NAME" in
    server.py) HOST_FILE="$REPO/beta_hermes_mcp_snapshot_stdio_v1.py" ;;
    *) HOST_FILE="$HOST_SNAPSHOTS/$(basename "$NAME")" ;;
  esac
  HOST_HASH="$(sha256sum "$HOST_FILE" | cut -d ' ' -f 1)"
  CONTAINER_HASH="$(docker exec "$CID" sha256sum "$RELEASE/$NAME" | cut -d ' ' -f 1)"
  test "$HOST_HASH" = "$CONTAINER_HASH"
  echo "$NAME byte-for-byte: PASS"
done

echo "=== 3. REAL UID 65534 MCP CANARY (NO MODEL) ==="
docker exec -i "$CID" \
  setpriv --reuid=65534 --regid=65534 --clear-groups \
  /usr/bin/env -i PYTHONDONTWRITEBYTECODE=1 "$PYTHON" - <<'PY'
import asyncio
import json
import os
import runpy
from pathlib import Path
from mcp import Client

root = Path("/opt/data/jason-os-pnap-staging")
assert os.geteuid() == 65534
assert not os.access("/opt/data/.env", os.R_OK)
assert not os.access(root / "server.py", os.W_OK)
assert not os.access(root / "snapshots", os.W_OK)

namespace = runpy.run_path(str(root / "server.py"), run_name="hermes_canary")

for source in ("BD_PNAP_APP145", "BD_PNAP_APP149"):
    packet = namespace["validated_snapshot"](source)
    assert packet["chunk_count"] == len(packet["chunks"]) == 8
    assert packet["answer"] is None
    assert packet["answer_status"] == "EVIDENCE_ONLY_REVIEW_REQUIRED"
    assert all(item["pdf_page_start"] >= 1 for item in packet["chunks"])
    assert not os.access(root / "snapshots" / (source + ".json"), os.W_OK)
    print(source, "READER: PASS (8 chunks)")

async def check():
    async with Client(namespace["mcp"]) as client:
        tools = await client.list_tools()
        assert [item.name for item in tools.tools] == ["read_approved_pnap_source"]
        for source in ("BD_PNAP_APP145", "BD_PNAP_APP149"):
            result = await client.call_tool("read_approved_pnap_source", {"source_id": source})
            assert result.is_error is False
            content = json.dumps(result.structured_content, ensure_ascii=False)
            content += " " + " ".join(getattr(item, "text", "") for item in result.content)
            assert source in content
            assert "EVIDENCE_ONLY_REVIEW_REQUIRED" in content
            print(source, "MCP TOOL CALL: PASS")
asyncio.run(check())
print("UID 65534 SECRETS UNREADABLE: PASS")
PY

CONFIG_AFTER="$(docker exec "$CID" sha256sum /opt/data/config.yaml | cut -d ' ' -f 1)"
test "$CONFIG_BEFORE" = "$CONFIG_AFTER"
test -z "$(git status --porcelain)"
echo "HERMES GATE 3D-B CANARY FILES AND MCP PROTOCOL: PASS"
echo "MCP NOT REGISTERED; HERMES CHAT NOT ACTIVATED"
