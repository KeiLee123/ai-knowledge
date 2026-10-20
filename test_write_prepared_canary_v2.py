#!/usr/bin/env python3

import json
import tempfile
from pathlib import Path

from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
)
from write_prepared_canary_v2 import (
    build_prepared_write_command,
    load_prepared_chunks,
)


def assert_command_locks_staging_db():
    repo_root = (
        Path(__file__)
        .resolve()
        .parent
    )

    command = build_prepared_write_command(
        repo_root=repo_root,
        python="/venv/bin/python",
        chunks_path=Path(
            "/tmp/retrieval-chunks-v2-with-source-pages.json"
        ),
        title="Construction Drawing",
        domain="engineering",
        topic="construction-drawing",
        document_type="technical-drawing",
        authority="",
        jurisdiction="HK",
        language="en",
        source_url="",
    )

    assert "--db-container" in command

    index = command.index(
        "--db-container"
    )

    assert command[
        index + 1
    ] == STAGING_DB_CONTAINER

    assert PRODUCTION_DB_CONTAINER not in command
    assert "--write" in command
    assert "--confirm-live-write" in command
    assert "--check-db" in command


def assert_valid_prepared_artifact():
    payload = {
        "schema_version":
            "retrieval-chunks-v2",
        "source_manifest": {
            "document_name":
                "example.pdf",
            "document_sha256":
                "a" * 64,
        },
        "chunks": [
            {
                "content": "example",
            }
        ],
    }

    with tempfile.TemporaryDirectory() as td:
        path = (
            Path(td)
            / "chunks.json"
        )

        path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        loaded = load_prepared_chunks(
            path
        )

        assert (
            loaded["source_manifest"][
                "document_sha256"
            ]
            == "a" * 64
        )


def assert_invalid_schema_rejected():
    payload = {
        "schema_version":
            "wrong-schema",
        "source_manifest": {
            "document_sha256":
                "b" * 64,
        },
        "chunks": [
            {
                "content": "example",
            }
        ],
    }

    with tempfile.TemporaryDirectory() as td:
        path = (
            Path(td)
            / "chunks.json"
        )

        path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        try:
            load_prepared_chunks(
                path
            )
        except RuntimeError:
            return

    raise AssertionError(
        "Invalid prepared schema was accepted"
    )


def main():
    assert_command_locks_staging_db()
    assert_valid_prepared_artifact()
    assert_invalid_schema_rejected()

    print(
        "Prepared canary writer test PASS"
    )
    print(
        "Fixed staging DB command: PASS"
    )
    print(
        "Production DB exclusion: PASS"
    )
    print(
        "Prepared artifact validation: PASS"
    )


if __name__ == "__main__":
    main()
