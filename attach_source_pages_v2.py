#!/usr/bin/env python3

import argparse
import copy
import hashlib
import json
from pathlib import Path

import pymupdf


ATTACHER_VERSION = "phase-d2-1"
SUPPORTED_SCHEMA = "retrieval-chunks-v2"
DEFAULT_DPI = 144
RELATIVE_PREFIX = "source-pages"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def load_chunks(path: Path) -> dict:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if payload.get("schema_version") != SUPPORTED_SCHEMA:
        raise RuntimeError(
            "Unsupported chunks schema: "
            f"{payload.get('schema_version')!r}"
        )

    source = payload.get("source_manifest") or {}
    checksum = source.get("document_sha256")

    if not checksum:
        raise RuntimeError(
            "source_manifest.document_sha256 is missing"
        )

    chunks = payload.get("chunks")

    if not isinstance(chunks, list) or not chunks:
        raise RuntimeError(
            "chunks must be a non-empty list"
        )

    return payload


def media_filename(
    checksum: str,
    page_number: int,
) -> str:
    return (
        "jasonos_"
        f"{checksum[:12]}"
        "_p"
        f"{page_number:04d}"
        ".png"
    )


def chunk_pages(chunk: dict) -> list[int]:
    start = chunk.get("page_start")
    end = chunk.get("page_end")

    if not isinstance(start, int):
        return []

    if not isinstance(end, int):
        end = start

    if start < 1 or end < start:
        raise RuntimeError(
            "Invalid chunk page range: "
            f"{start}-{end}"
        )

    if end - start > 20:
        raise RuntimeError(
            "Refusing source visual render for "
            "a chunk spanning more than 20 pages"
        )

    return list(range(start, end + 1))


def collect_pages(payload: dict) -> list[int]:
    pages = set()

    for chunk in payload["chunks"]:
        pages.update(
            chunk_pages(chunk)
        )

    if not pages:
        raise RuntimeError(
            "No page-number provenance found in chunks"
        )

    return sorted(pages)


def render_page(
    doc,
    page_number: int,
    output_path: Path,
    dpi: int,
) -> dict:
    if page_number < 1 or page_number > len(doc):
        raise RuntimeError(
            f"Page {page_number} is outside "
            f"PDF page count {len(doc)}"
        )

    page = doc[page_number - 1]
    scale = dpi / 72.0

    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(
            scale,
            scale,
        ),
        alpha=False,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    pix.save(output_path)

    return {
        "kind": "pdf_page",
        "page_number": page_number,
        "filename": output_path.name,
        "relative_path": (
            RELATIVE_PREFIX
            + "/"
            + output_path.name
        ),
        "sha256": sha256_file(
            output_path
        ),
        "mime_type": "image/png",
        "pixel_width": pix.width,
        "pixel_height": pix.height,
        "dpi": dpi,
        "renderer_version": ATTACHER_VERSION,
    }


def attach_source_visuals(
    payload: dict,
    source_pdf: Path,
    media_dir: Path,
    dpi: int = DEFAULT_DPI,
) -> dict:
    expected_checksum = (
        payload["source_manifest"][
            "document_sha256"
        ]
    )

    actual_checksum = sha256_file(
        source_pdf
    )

    if actual_checksum != expected_checksum:
        raise RuntimeError(
            "Source PDF checksum does not match "
            "retrieval chunks. "
            f"expected={expected_checksum} "
            f"actual={actual_checksum}"
        )

    pages = collect_pages(
        payload
    )

    doc = pymupdf.open(
        source_pdf
    )

    rendered = {}

    try:
        for page_number in pages:
            filename = media_filename(
                expected_checksum,
                page_number,
            )

            rendered[page_number] = (
                render_page(
                    doc,
                    page_number,
                    media_dir / filename,
                    dpi,
                )
            )

    finally:
        doc.close()

    output = copy.deepcopy(
        payload
    )

    attached = 0

    for chunk in output["chunks"]:
        metadata = chunk.setdefault(
            "metadata",
            {},
        )

        visuals = [
            dict(
                rendered[page_number]
            )
            for page_number
            in chunk_pages(chunk)
            if page_number in rendered
        ]

        metadata[
            "source_visuals"
        ] = visuals

        attached += len(
            visuals
        )

    output["source_visuals"] = {
        "attacher_version":
            ATTACHER_VERSION,
        "source_pdf_name":
            source_pdf.name,
        "source_pdf_sha256":
            actual_checksum,
        "dpi":
            dpi,
        "rendered_pages":
            pages,
        "rendered_media_count":
            len(rendered),
        "attached_reference_count":
            attached,
        "relative_prefix":
            RELATIVE_PREFIX,
        "database_write_performed":
            False,
        "model_call_performed":
            False,
        "embedding_performed":
            False,
        "files": [
            rendered[page_number]
            for page_number
            in pages
        ],
    }

    output.setdefault(
        "policy",
        {},
    )[
        "source_visual_reference"
    ] = (
        "deterministic-original-pdf-page"
    )

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render deterministic original PDF pages "
            "and attach source visual references to "
            "retrieval-chunks-v2. No model, embedding, "
            "or database writes."
        )
    )

    parser.add_argument(
        "chunks",
        help="Input retrieval-chunks-v2 JSON",
    )

    parser.add_argument(
        "--source-pdf",
        required=True,
        help=(
            "Original PDF matching "
            "source_manifest.document_sha256"
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output retrieval-chunks-v2 JSON "
            "with source_visuals metadata"
        ),
    )

    parser.add_argument(
        "--media-dir",
        required=True,
        help=(
            "Directory for deterministic "
            "source page PNG files"
        ),
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
    )

    args = parser.parse_args()

    if args.dpi < 72 or args.dpi > 300:
        raise SystemExit(
            "--dpi must be between 72 and 300"
        )

    chunks_path = (
        Path(args.chunks)
        .expanduser()
        .resolve()
    )

    source_pdf = (
        Path(args.source_pdf)
        .expanduser()
        .resolve()
    )

    output_path = (
        Path(args.output)
        .expanduser()
        .resolve()
    )

    media_dir = (
        Path(args.media_dir)
        .expanduser()
        .resolve()
    )

    if not chunks_path.is_file():
        raise SystemExit(
            f"Chunks file not found: {chunks_path}"
        )

    if not source_pdf.is_file():
        raise SystemExit(
            f"Source PDF not found: {source_pdf}"
        )

    if source_pdf.suffix.lower() != ".pdf":
        raise SystemExit(
            "--source-pdf must be a PDF"
        )

    if output_path == chunks_path:
        raise SystemExit(
            "Refusing to overwrite "
            "the input chunks file"
        )

    try:
        payload = load_chunks(
            chunks_path
        )

        output = attach_source_visuals(
            payload,
            source_pdf,
            media_dir,
            dpi=args.dpi,
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_text(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    except Exception as exc:
        raise SystemExit(
            "Source page attachment failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    summary = output[
        "source_visuals"
    ]

    print(output_path)
    print(
        "Source checksum verified:",
        True,
    )
    print(
        "Rendered pages:",
        summary["rendered_pages"],
    )
    print(
        "Rendered media:",
        summary["rendered_media_count"],
    )
    print(
        "Attached references:",
        summary["attached_reference_count"],
    )
    print(
        "Database write performed:",
        False,
    )
    print(
        "Model call performed:",
        False,
    )
    print(
        "Embedding performed:",
        False,
    )


if __name__ == "__main__":
    main()
