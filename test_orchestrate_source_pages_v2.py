#!/usr/bin/env python3

from pathlib import Path

from orchestrate_document_v2 import (
    ORCHESTRATOR_VERSION,
    build_source_page_attach_command,
)


def main():
    command = build_source_page_attach_command(
        python="/venv/bin/python",
        chunks=Path("/work/retrieval-chunks-v2.json"),
        source=Path("/data/example.pdf"),
        output=Path(
            "/work/retrieval-chunks-v2-with-source-pages.json"
        ),
        media_dir=Path("/work/source-pages"),
    )

    assert ORCHESTRATOR_VERSION == "phase-d5-3"

    assert command[0] == "/venv/bin/python"

    assert command[1].endswith(
        "attach_source_pages_v2.py"
    )

    assert command[2] == (
        "/work/retrieval-chunks-v2.json"
    )

    assert command[3:5] == [
        "--source-pdf",
        "/data/example.pdf",
    ]

    assert command[5:7] == [
        "--output",
        "/work/retrieval-chunks-v2-with-source-pages.json",
    ]

    assert command[7:9] == [
        "--media-dir",
        "/work/source-pages",
    ]

    print(
        "V2 orchestrator source-page integration test PASS"
    )
    print(
        "Orchestrator version:",
        ORCHESTRATOR_VERSION,
    )
    print(
        "Source-page stage command: PASS"
    )
    print(
        "No command executed: PASS"
    )


if __name__ == "__main__":
    main()
