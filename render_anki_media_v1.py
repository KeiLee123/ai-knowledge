#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf


RENDERER_VERSION = "sr-d-1"
SUPPORTED_SCHEMA = "anki-card-manifest-v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        payload.get("schema_version")
        != SUPPORTED_SCHEMA
    ):
        raise RuntimeError(
            "Unsupported manifest schema: "
            f"{payload.get('schema_version')!r}"
        )

    cards = payload.get("cards")

    if not isinstance(cards, list):
        raise RuntimeError(
            "cards must be a list"
        )

    return payload


def referenced_checksums(
    payload: dict,
) -> set[str]:
    values = set()

    for card in payload["cards"]:
        source = (
            card.get("source")
            or {}
        )

        checksum = str(
            source.get(
                "document_checksum",
                ""
            )
            or ""
        ).strip()

        if checksum:
            values.add(checksum)

    return values


def card_pages(
    card: dict,
) -> list[int]:
    source = (
        card.get("source")
        or {}
    )

    start = source.get(
        "page_start"
    )

    end = source.get(
        "page_end"
    )

    if not isinstance(start, int):
        return []

    if not isinstance(end, int):
        end = start

    if start < 1 or end < start:
        return []

    if end - start > 20:
        raise RuntimeError(
            "Refusing to render a card "
            "with a page span over 20 pages"
        )

    return list(
        range(start, end + 1)
    )


def collect_pages(
    payload: dict,
    requested_pages: set[int],
) -> list[int]:
    pages = set()

    for card in payload["cards"]:
        for page in card_pages(card):
            if (
                requested_pages
                and page not in requested_pages
            ):
                continue

            pages.add(page)

    return sorted(pages)


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


def render_page(
    doc,
    page_number: int,
    output_path: Path,
    dpi: int,
) -> dict:
    if (
        page_number < 1
        or page_number > len(doc)
    ):
        raise RuntimeError(
            f"Page {page_number} is outside "
            f"PDF page count {len(doc)}"
        )

    page = doc[
        page_number - 1
    ]

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

    pix.save(
        output_path
    )

    return {
        "kind": "pdf_page",
        "page_number": page_number,
        "filename":
            output_path.name,
        "relative_path":
            "media/"
            + output_path.name,
        "sha256":
            sha256_file(
                output_path
            ),
        "mime_type": "image/png",
        "pixel_width": pix.width,
        "pixel_height": pix.height,
        "renderer_version":
            RENDERER_VERSION,
    }


def attach_media(
    payload: dict,
    media_by_page: dict[int, dict],
    requested_pages: set[int],
) -> int:
    attached = 0

    for card in payload["cards"]:
        existing = (
            card.get("media")
            or []
        )

        if not isinstance(
            existing,
            list,
        ):
            raise RuntimeError(
                "card.media must be a list"
            )

        retained = [
            item
            for item in existing
            if not (
                isinstance(item, dict)
                and item.get("kind")
                    == "pdf_page"
                and item.get(
                    "renderer_version"
                )
                    == RENDERER_VERSION
            )
        ]

        additions = []

        for page in card_pages(card):
            if (
                requested_pages
                and page
                    not in requested_pages
            ):
                continue

            media = (
                media_by_page.get(
                    page
                )
            )

            if media:
                additions.append(
                    dict(media)
                )

        card["media"] = (
            retained
            + additions
        )

        attached += len(additions)

    return attached


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render original PDF pages for an "
            "anki-card-manifest-v1 manifest. "
            "No DB or Anki writes."
        )
    )

    parser.add_argument(
        "manifest",
        help=(
            "Input anki-card-manifest-v1 JSON"
        ),
    )

    parser.add_argument(
        "--source-pdf",
        required=True,
        help=(
            "Original PDF matching the "
            "manifest document checksum"
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output manifest with media metadata"
        ),
    )

    parser.add_argument(
        "--media-dir",
        required=True,
        help=(
            "Directory for rendered page images"
        ),
    )

    parser.add_argument(
        "--page",
        action="append",
        type=int,
        help=(
            "Optional page to render. "
            "Repeat for multiple pages. "
            "Without this option all card pages "
            "are rendered."
        ),
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=144,
    )

    args = parser.parse_args()

    if (
        args.dpi < 72
        or args.dpi > 300
    ):
        raise SystemExit(
            "--dpi must be between "
            "72 and 300"
        )

    requested_pages = set(
        args.page
        or []
    )

    if any(
        page < 1
        for page in requested_pages
    ):
        raise SystemExit(
            "--page values must be positive"
        )

    manifest_path = (
        Path(args.manifest)
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

    if not manifest_path.is_file():
        raise SystemExit(
            f"Manifest not found: "
            f"{manifest_path}"
        )

    if not source_pdf.is_file():
        raise SystemExit(
            f"Source PDF not found: "
            f"{source_pdf}"
        )

    if (
        source_pdf.suffix.lower()
        != ".pdf"
    ):
        raise SystemExit(
            "--source-pdf must be a PDF"
        )

    if (
        output_path
        == manifest_path
    ):
        raise SystemExit(
            "Refusing to overwrite "
            "the input manifest"
        )

    try:
        payload = load_manifest(
            manifest_path
        )

        checksums = (
            referenced_checksums(
                payload
            )
        )

        if not checksums:
            raise RuntimeError(
                "Manifest has no source "
                "document checksum"
            )

        if len(checksums) != 1:
            raise RuntimeError(
                "SR-D v1 accepts one source "
                "document per render pass"
            )

        expected_checksum = (
            next(iter(checksums))
        )

        actual_checksum = (
            sha256_file(
                source_pdf
            )
        )

        if (
            actual_checksum
            != expected_checksum
        ):
            raise RuntimeError(
                "Source PDF checksum does not "
                "match card manifest. "
                f"expected={expected_checksum} "
                f"actual={actual_checksum}"
            )

        pages = collect_pages(
            payload,
            requested_pages,
        )

        if not pages:
            raise RuntimeError(
                "No card source pages selected "
                "for rendering"
            )

        media_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        rendered = {}

        doc = pymupdf.open(
            source_pdf
        )

        try:
            for page_number in pages:
                filename = media_filename(
                    expected_checksum,
                    page_number,
                )

                path = (
                    media_dir
                    / filename
                )

                rendered[
                    page_number
                ] = render_page(
                    doc,
                    page_number,
                    path,
                    args.dpi,
                )

        finally:
            doc.close()

        attached_count = (
            attach_media(
                payload,
                rendered,
                requested_pages,
            )
        )

        generation = payload.setdefault(
            "generation",
            {},
        )

        generation.update({
            "media_rendered": True,
            "media_renderer_version":
                RENDERER_VERSION,
            "media_source_sha256":
                actual_checksum,
            "rendered_pages":
                pages,
            "rendered_media_count":
                len(rendered),
            "attached_media_count":
                attached_count,
            "anki_package_created":
                False,
        })

        payload["media"] = {
            "renderer_version":
                RENDERER_VERSION,
            "source_pdf_name":
                source_pdf.name,
            "source_pdf_sha256":
                actual_checksum,
            "dpi":
                args.dpi,
            "files": [
                rendered[
                    page_number
                ]
                for page_number in pages
            ],
        }

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    except Exception as exc:
        raise SystemExit(
            "Anki media rendering failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    print(
        output_path
    )

    print(
        "Source checksum verified:",
        True,
    )

    print(
        "Rendered pages:",
        pages,
    )

    print(
        "Rendered media:",
        len(rendered),
    )

    print(
        "Attached media:",
        attached_count,
    )

    print(
        "Database write performed:",
        False,
    )

    print(
        "Anki package created:",
        False,
    )


if __name__ == "__main__":
    main()
