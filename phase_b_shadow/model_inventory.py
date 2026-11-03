"""Offline Docling model-asset inventory, never downloads or loads models.

Digest definition: SHA256 of UTF-8 text consisting of a schema line followed by
sorted 'relative_path<TAB>size_bytes<TAB>file_sha256<LF>' records, each with LF.
All files (including model-version.txt) are included; only regular, non-symlink
files qualify. The digest must be independently reviewed and pinned in the
read-only fixture catalog before any shadow conversion.
"""

import argparse
import hashlib
import json
from pathlib import Path

from phase_b_shadow.contract import ContractGap

SCHEMA = "phase-b-model-inventory-v1"
MAX_FILES = 4096
MAX_BYTES = 12 * 1024**3


def inventory_model_bundle(directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ContractGap("model bundle path must be a regular directory")
    rows = []
    total = 0
    for entry in sorted(directory.rglob("*"), key=lambda p: p.relative_to(directory).as_posix()):
        if entry.is_symlink():
            raise ContractGap("model bundle contains a symlink")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ContractGap("model bundle contains a non-regular file")
        name = entry.relative_to(directory).as_posix()
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ContractGap("model bundle contains an unsafe filename")
        size = entry.stat().st_size
        total += size
        if len(rows) >= MAX_FILES or total > MAX_BYTES:
            raise ContractGap("model bundle exceeds bounded inventory limits")
        digest = hashlib.sha256()
        count = 0
        with entry.open("rb") as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(data)
                count += len(data)
        if count != size:
            raise ContractGap("model bundle file changed during hashing")
        rows.append({"path": name, "size_bytes": size, "sha256": digest.hexdigest()})
    if not any(row["path"] == "model-version.txt" for row in rows):
        raise ContractGap("model bundle version marker is missing")
    if not any(row["path"] != "model-version.txt" for row in rows):
        raise ContractGap("model bundle has no model artifacts")
    canonical = SCHEMA + "\n" + "".join(
        f'{row["path"]}\t{row["size_bytes"]}\t{row["sha256"]}\n' for row in rows
    )
    return {
        "schema_version": SCHEMA,
        "model_bundle_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "file_count": len(rows),
        "total_bytes": total,
        "files": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Docling model bundle SHA256 inventory")
    parser.add_argument("directory", type=Path, help="Local, separately supplied offline model directory")
    args = parser.parse_args()
    print(json.dumps(inventory_model_bundle(args.directory), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
