#!/usr/bin/env python3

import json
import tempfile
from pathlib import Path

import pymupdf

from attach_source_pages_v2 import (
    ATTACHER_VERSION,
    attach_source_visuals,
    media_filename,
    sha256_file,
)


def build_pdf(path: Path) -> None:
    doc = pymupdf.open()

    try:
        page1 = doc.new_page(
            width=320,
            height=240,
        )
        page1.insert_text(
            (40, 60),
            "Page 1",
        )

        page2 = doc.new_page(
            width=320,
            height=240,
        )
        page2.insert_text(
            (40, 60),
            "Page 2 source evidence",
        )

        doc.save(path)

    finally:
        doc.close()


def chunks_payload(
    checksum: str,
) -> dict:
    return {
        "schema_version":
            "retrieval-chunks-v2",
        "builder_version":
            "test",
        "source_manifest": {
            "path":
                "/tmp/test-manifest.json",
            "sha256":
                "b" * 64,
            "document_sha256":
                checksum,
            "document_name":
                "example.pdf",
        },
        "policy": {
            "database_write_performed":
                False,
            "embedding_performed":
                False,
            "model_call_performed":
                False,
        },
        "summary": {
            "chunk_count": 1,
        },
        "chunks": [
            {
                "chunk_index": 0,
                "content":
                    "Page 2 source evidence",
                "content_chars": 22,
                "page_start": 2,
                "page_end": 2,
                "metadata": {
                    "evidence_origin":
                        "native_text",
                    "evidence_tier":
                        "primary",
                    "modality":
                        "text",
                    "page_number":
                        2,
                },
            }
        ],
    }


def assert_source_page_contract():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf = root / "example.pdf"

        build_pdf(pdf)

        checksum = sha256_file(
            pdf
        )

        payload = chunks_payload(
            checksum
        )

        media_a = root / "media-a"
        media_b = root / "media-b"

        first = attach_source_visuals(
            payload,
            pdf,
            media_a,
            dpi=144,
        )

        second = attach_source_visuals(
            payload,
            pdf,
            media_b,
            dpi=144,
        )

        expected_name = media_filename(
            checksum,
            2,
        )

        assert expected_name == (
            "jasonos_"
            + checksum[:12]
            + "_p0002.png"
        )

        first_visuals = (
            first["chunks"][0]["metadata"][
                "source_visuals"
            ]
        )

        second_visuals = (
            second["chunks"][0]["metadata"][
                "source_visuals"
            ]
        )

        assert len(first_visuals) == 1
        assert len(second_visuals) == 1

        first_visual = first_visuals[0]
        second_visual = second_visuals[0]

        assert first_visual[
            "page_number"
        ] == 2

        assert first_visual[
            "filename"
        ] == expected_name

        assert first_visual[
            "relative_path"
        ] == (
            "source-pages/"
            + expected_name
        )

        assert first_visual[
            "renderer_version"
        ] == ATTACHER_VERSION

        assert first_visual[
            "mime_type"
        ] == "image/png"

        assert first_visual[
            "sha256"
        ] == second_visual[
            "sha256"
        ]

        assert (
            media_a / expected_name
        ).is_file()

        assert (
            media_b / expected_name
        ).is_file()

        summary = first[
            "source_visuals"
        ]

        assert summary[
            "source_pdf_sha256"
        ] == checksum

        assert summary[
            "rendered_pages"
        ] == [2]

        assert summary[
            "rendered_media_count"
        ] == 1

        assert summary[
            "attached_reference_count"
        ] == 1

        assert summary[
            "database_write_performed"
        ] is False

        assert summary[
            "model_call_performed"
        ] is False

        assert summary[
            "embedding_performed"
        ] is False


def assert_checksum_guard():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf = root / "example.pdf"

        build_pdf(pdf)

        payload = chunks_payload(
            "0" * 64
        )

        try:
            attach_source_visuals(
                payload,
                pdf,
                root / "media",
                dpi=144,
            )

        except RuntimeError as exc:
            assert (
                "checksum does not match"
                in str(exc)
            )

        else:
            raise AssertionError(
                "checksum mismatch was not rejected"
            )


def main():
    assert_source_page_contract()
    assert_checksum_guard()

    print(
        "Source page reference test PASS"
    )
    print(
        "Deterministic filename: PASS"
    )
    print(
        "Deterministic render hash: PASS"
    )
    print(
        "Chunk source_visuals provenance: PASS"
    )
    print(
        "Checksum guard: PASS"
    )
    print(
        "No model / embedding / DB write: PASS"
    )


if __name__ == "__main__":
    main()
