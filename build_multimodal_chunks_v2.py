#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
from pathlib import Path


BUILDER_VERSION = "phase-d-1.3"
SUPPORTED_SCHEMA = "document-manifest-v2"

DEFAULT_TARGET_CHARS = 1800
DEFAULT_OVERLAP_CHARS = 250


def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("schema_version") != SUPPORTED_SCHEMA:
        raise RuntimeError(
            f"Unsupported manifest schema: {data.get('schema_version')!r}"
        )

    if not isinstance(data.get("units"), list):
        raise RuntimeError("Manifest units must be a list")

    source = data.get("source") or {}

    if not source.get("sha256"):
        raise RuntimeError("Manifest source.sha256 is missing")

    return data


def split_text(
    text: str,
    target_chars: int,
    overlap_chars: int,
) -> list[str]:
    text = normalize_text(text)

    if not text:
        return []

    paragraphs = [
        p.strip()
        for p in re.split(r"\n\s*\n", text)
        if p.strip()
    ]

    if not paragraphs:
        return [text]

    chunks = []
    current = ""

    for paragraph in paragraphs:
        candidate = (
            paragraph
            if not current
            else current + "\n\n" + paragraph
        )

        if current and len(candidate) > target_chars:
            chunks.append(current.strip())

            overlap = current[-overlap_chars:] if overlap_chars else ""

            current = (
                overlap + "\n\n" + paragraph
                if overlap
                else paragraph
            ).strip()

        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks


def serialize_structured_table(table: dict) -> str:
    rows = table.get("rows") or []

    if not isinstance(rows, list):
        return ""

    rendered_rows = []

    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, list):
            continue

        cells = []

        for cell in row:
            value = normalize_text(
                "" if cell is None else str(cell)
            )

            value = re.sub(
                r"\s*\n\s*",
                " ",
                value,
            )

            cells.append(value)

        if not any(cells):
            continue

        rendered_rows.append(
            "Row "
            f"{row_index}: "
            + " | ".join(cells)
        )

    if not rendered_rows:
        return ""

    table_index = table.get("table_index")

    if isinstance(table_index, int):
        label = f"Table {table_index + 1}"
    else:
        label = "Table"

    return (
        label
        + "\nRows:\n"
        + "\n".join(rendered_rows)
    )


def unit_evidence(unit: dict) -> list[dict]:
    evidence = []

    native_text = normalize_text(
        unit.get("text") or ""
    )

    ocr = unit.get("ocr") or {}
    ocr_text = ""

    if (
        ocr.get("status") == "text_recovered"
        and ocr.get("text")
    ):
        ocr_text = normalize_text(
            ocr.get("text") or ""
        )

    if native_text and ocr_text:
        evidence.append({
            "origin": "fused_text",
            "modality": "text",
            "tier": "primary",
            "derived": True,
            "derivation": {
                "type": "text_fusion",
                "components": [
                    "native_text",
                    "ocr_text",
                ],
                "ocr": {
                    "engine": ocr.get("engine"),
                    "engine_version":
                        ocr.get("engine_version"),
                    "languages":
                        ocr.get("languages"),
                    "dpi":
                        ocr.get("dpi"),
                },
            },
            "text": (
                native_text
                + "\n\n"
                + ocr_text
            ),
        })

    elif native_text:
        evidence.append({
            "origin": "native_text",
            "modality": "text",
            "tier": "primary",
            "derived": False,
            "text": native_text,
        })

    elif ocr_text:
        evidence.append({
            "origin": "ocr_text",
            "modality": "text",
            "tier": "primary",
            "derived": True,
            "derivation": {
                "type": "ocr",
                "engine": ocr.get("engine"),
                "engine_version":
                    ocr.get("engine_version"),
                "languages":
                    ocr.get("languages"),
                "dpi":
                    ocr.get("dpi"),
            },
            "text": ocr_text,
        })

    tables = unit.get("tables") or []

    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue

            table_text = serialize_structured_table(
                table
            )

            if not table_text:
                continue

            evidence.append({
                "origin": "structured_table",
                "modality": "table",
                "tier": "primary",
                "derived": True,
                "derivation": {
                    "type": "table_extraction",
                    "detection_strategy":
                        table.get("detection_strategy"),
                },
                "metadata": {
                    "table_index":
                        table.get("table_index"),
                    "table_bbox":
                        table.get("bbox"),
                    "table_row_count":
                        table.get("row_count"),
                    "table_column_count":
                        table.get("column_count"),
                    "table_detection_strategy":
                        table.get("detection_strategy"),
                },
                "text": table_text,
            })

    vision = unit.get("vision") or {}
    result = vision.get("result") or {}

    if (
        vision.get("status") == "described"
        and result.get("useful") is True
        and result.get("retrieval_text")
    ):
        visual_text = normalize_text(
            result.get("retrieval_text") or ""
        )

        if visual_text:
            evidence.append({
                "origin": "visual_understanding",
                "modality": "visual",
                "tier": "supplementary",
                "derived": True,
                "derivation": {
                    "type": "vision",
                    "model": vision.get("model"),
                    "prompt_version":
                        vision.get("prompt_version"),
                    "confidence":
                        result.get("confidence"),
                    "page_type":
                        result.get("page_type"),
                },
                "text": visual_text,
            })

    return evidence

def build_chunks(
    manifest: dict,
    target_chars: int,
    overlap_chars: int,
) -> list[dict]:
    chunks = []

    for unit in manifest["units"]:
        if unit.get("unit_type") != "page":
            continue

        page_number = unit.get("page_number")

        if not isinstance(page_number, int):
            continue

        for evidence in unit_evidence(unit):
            parts = split_text(
                evidence["text"],
                target_chars=target_chars,
                overlap_chars=overlap_chars,
            )

            for local_index, content in enumerate(parts):
                metadata = {
                    "builder_version": BUILDER_VERSION,
                    "evidence_origin": evidence["origin"],
                    "modality": evidence["modality"],
                    "evidence_tier": evidence["tier"],
                    "derived": evidence["derived"],
                    "page_number": page_number,
                    "local_chunk_index": local_index,
                }

                if evidence.get("derivation"):
                    metadata["derivation"] = evidence["derivation"]

                if evidence.get("metadata"):
                    metadata.update(
                        evidence["metadata"]
                    )

                chunks.append({
                    "chunk_index": len(chunks),
                    "content": content,
                    "content_chars": len(content),
                    "page_start": page_number,
                    "page_end": page_number,
                    "metadata": metadata,
                })

    return chunks


def summarize(chunks: list[dict]) -> dict:
    counts_by_origin = {}
    counts_by_modality = {}
    chars_by_origin = {}
    pages_by_origin = {}

    for chunk in chunks:
        metadata = chunk["metadata"]
        origin = metadata["evidence_origin"]
        modality = metadata["modality"]
        chars = chunk["content_chars"]
        page = metadata["page_number"]

        counts_by_origin[origin] = counts_by_origin.get(origin, 0) + 1
        counts_by_modality[modality] = counts_by_modality.get(modality, 0) + 1
        chars_by_origin[origin] = chars_by_origin.get(origin, 0) + chars

        pages_by_origin.setdefault(origin, set()).add(page)

    return {
        "chunk_count": len(chunks),
        "total_chars": sum(
            chunk["content_chars"]
            for chunk in chunks
        ),
        "counts_by_origin": counts_by_origin,
        "counts_by_modality": counts_by_modality,
        "chars_by_origin": chars_by_origin,
        "pages_by_origin": {
            key: sorted(value)
            for key, value in pages_by_origin.items()
        },
    }


def build_output(
    manifest_path: Path,
    manifest: dict,
    target_chars: int,
    overlap_chars: int,
) -> dict:
    chunks = build_chunks(
        manifest,
        target_chars=target_chars,
        overlap_chars=overlap_chars,
    )

    return {
        "schema_version": "retrieval-chunks-v2",
        "builder_version": BUILDER_VERSION,
        "source_manifest": {
            "path": manifest_path.name,
            "sha256": sha256_file(manifest_path),
            "document_sha256": manifest["source"]["sha256"],
            "document_name": manifest["source"].get("filename"),
        },
        "policy": {
            "native_text": "primary",
            "ocr_text": "primary",
            "fused_text": "primary",
            "visual_understanding": "supplementary",
            "structured_table": "primary",
            "target_chars": target_chars,
            "overlap_chars": overlap_chars,
            "database_write_performed": False,
            "embedding_performed": False,
            "model_call_performed": False,
            "same_page_native_ocr_policy":
                "fuse-into-one-primary-evidence",
        },
        "summary": summarize(chunks),
        "chunks": chunks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic retrieval-ready chunks from a "
            "document-manifest-v2 augmented by Phase B/C."
        )
    )

    parser.add_argument(
        "manifest",
        help="Phase A/B/C JSON manifest",
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Write retrieval chunks JSON",
    )

    parser.add_argument(
        "--target-chars",
        type=int,
        default=DEFAULT_TARGET_CHARS,
        help=f"Chunk target size (default: {DEFAULT_TARGET_CHARS})",
    )

    parser.add_argument(
        "--overlap-chars",
        type=int,
        default=DEFAULT_OVERLAP_CHARS,
        help=f"Chunk overlap size (default: {DEFAULT_OVERLAP_CHARS})",
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    output_path = Path(args.output)

    if not manifest_path.is_file():
        raise SystemExit(
            f"Manifest not found: {manifest_path}"
        )

    if output_path.resolve() == manifest_path.resolve():
        raise SystemExit(
            "Refusing to overwrite the input manifest"
        )

    if args.target_chars < 200:
        raise SystemExit(
            "--target-chars must be at least 200"
        )

    if (
        args.overlap_chars < 0
        or args.overlap_chars >= args.target_chars
    ):
        raise SystemExit(
            "--overlap-chars must be >= 0 and < --target-chars"
        )

    try:
        manifest = load_manifest(
            manifest_path
        )

        output = build_output(
            manifest_path=manifest_path,
            manifest=manifest,
            target_chars=args.target_chars,
            overlap_chars=args.overlap_chars,
        )

    except Exception as exc:
        raise SystemExit(
            f"Chunk build failed: {type(exc).__name__}: {exc}"
        ) from exc

    if args.compact:
        payload = json.dumps(
            output,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    else:
        payload = json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        payload + "\n",
        encoding="utf-8",
    )

    print(output_path)


if __name__ == "__main__":
    main()