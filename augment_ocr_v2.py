#!/usr/bin/env python3

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


AUGMENTER_VERSION = "phase-b-1"
SUPPORTED_SCHEMA = "document-manifest-v2"
DEFAULT_LANGUAGES = "eng+chi_tra"
DEFAULT_DPI = 300


def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


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

    source = data.get("source") or {}
    if not source.get("sha256"):
        raise RuntimeError("Manifest source.sha256 is missing")

    if not isinstance(data.get("units"), list):
        raise RuntimeError("Manifest units must be a list")

    return data


def validate_pdf_against_manifest(pdf_path: Path, manifest: dict) -> None:
    source = manifest["source"]
    expected_sha = source["sha256"]
    actual_sha = sha256_file(pdf_path)

    if actual_sha != expected_sha:
        raise RuntimeError(
            "PDF SHA256 does not match manifest source.sha256: "
            f"expected {expected_sha}, got {actual_sha}"
        )

    if (manifest.get("document") or {}).get("kind") != "pdf":
        raise RuntimeError("Phase B OCR currently supports PDF manifests only")


def tesseract_version() -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract executable not found in PATH")

    result = subprocess.run(
        [exe, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    first_line = (result.stdout or "").splitlines()
    return first_line[0].strip() if first_line else "tesseract"


def tesseract_languages() -> set[str]:
    exe = shutil.which("tesseract")
    if not exe:
        raise RuntimeError("tesseract executable not found in PATH")

    result = subprocess.run(
        [exe, "--list-langs"],
        check=True,
        capture_output=True,
        text=True,
    )

    lines = [line.strip() for line in (result.stdout or "").splitlines()]
    return {
        line
        for line in lines
        if line and not line.lower().startswith("list of available languages")
    }


def validate_languages(language_spec: str) -> list[str]:
    requested = [item.strip() for item in language_spec.split("+") if item.strip()]
    if not requested:
        raise RuntimeError("At least one OCR language is required")

    available = tesseract_languages()
    missing = [lang for lang in requested if lang not in available]

    if missing:
        raise RuntimeError(
            "Requested Tesseract languages are unavailable: "
            + ", ".join(missing)
        )

    return requested


def candidate_units(manifest: dict) -> list[dict]:
    candidates = []

    for unit in manifest["units"]:
        if unit.get("unit_type") != "page":
            continue
        if not unit.get("ocr_candidate"):
            continue
        if unit.get("blank"):
            continue
        if not isinstance(unit.get("page_number"), int):
            continue
        candidates.append(unit)

    return candidates


def ocr_page(page, languages: str, dpi: int, tessdata: str | None) -> str:
    kwargs = {
        "language": languages,
        "dpi": dpi,
        "full": True,
    }

    if tessdata:
        kwargs["tessdata"] = tessdata

    textpage = page.get_textpage_ocr(**kwargs)
    text = page.get_text("text", textpage=textpage)
    return normalize_text(text)


def augment_manifest(
    manifest: dict,
    pdf_path: Path,
    languages: str,
    dpi: int,
    tessdata: str | None,
) -> dict:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for OCR augmentation") from exc

    requested_languages = validate_languages(languages)
    engine_version = tesseract_version()

    augmented = copy.deepcopy(manifest)
    candidates = candidate_units(augmented)

    processed = []
    failed = []
    total_ocr_text_chars = 0

    doc = pymupdf.open(pdf_path)

    try:
        page_count = len(doc)

        for unit in candidates:
            page_number = unit["page_number"]

            if page_number < 1 or page_number > page_count:
                error = (
                    f"Page {page_number} is outside PDF page count {page_count}"
                )
                unit["ocr"] = {
                    "eligible": True,
                    "performed": False,
                    "engine": "tesseract",
                    "engine_version": engine_version,
                    "languages": requested_languages,
                    "dpi": dpi,
                    "mode": "full-page",
                    "text": "",
                    "text_chars": 0,
                    "error": error,
                }
                failed.append(page_number)
                continue

            try:
                text = ocr_page(
                    doc[page_number - 1],
                    languages=languages,
                    dpi=dpi,
                    tessdata=tessdata,
                )

                unit["ocr"] = {
                    "eligible": True,
                    "performed": True,
                    "engine": "tesseract",
                    "engine_version": engine_version,
                    "languages": requested_languages,
                    "dpi": dpi,
                    "mode": "full-page",
                    "text": text,
                    "text_chars": len(text),
                    "error": None,
                }

                total_ocr_text_chars += len(text)
                processed.append(page_number)

            except Exception as exc:
                unit["ocr"] = {
                    "eligible": True,
                    "performed": False,
                    "engine": "tesseract",
                    "engine_version": engine_version,
                    "languages": requested_languages,
                    "dpi": dpi,
                    "mode": "full-page",
                    "text": "",
                    "text_chars": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                failed.append(page_number)

    finally:
        doc.close()

    augmented.setdefault("augmentations", {})
    augmented["augmentations"]["ocr"] = {
        "augmenter_version": AUGMENTER_VERSION,
        "engine": "tesseract",
        "engine_version": engine_version,
        "languages": requested_languages,
        "dpi": dpi,
        "mode": "full-page",
        "tessdata": tessdata,
        "candidate_units": [unit["page_number"] for unit in candidates],
        "processed_units": processed,
        "failed_units": failed,
        "total_ocr_text_chars": total_ocr_text_chars,
    }

    augmented.setdefault("extraction", {})
    augmented["extraction"]["ocr_performed"] = bool(processed)

    return augmented


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase B OCR augmenter for document-manifest-v2. "
            "Only units already marked ocr_candidate=True are OCR'd. "
            "Original extracted text is preserved."
        )
    )
    parser.add_argument("manifest", help="Phase A JSON manifest")
    parser.add_argument("pdf", help="Original PDF matching manifest source.sha256")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Write augmented manifest to a new JSON file",
    )
    parser.add_argument(
        "--languages",
        default=DEFAULT_LANGUAGES,
        help=f"Tesseract language spec (default: {DEFAULT_LANGUAGES})",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"OCR render DPI (default: {DEFAULT_DPI})",
    )
    parser.add_argument(
        "--tessdata",
        default="/usr/share/tesseract-ocr/5/tessdata",
        help="Tesseract tessdata directory",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    pdf_path = Path(args.pdf)
    output_path = Path(args.output)

    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")
    if output_path.resolve() == manifest_path.resolve():
        raise SystemExit("Refusing to overwrite the Phase A manifest")
    if args.dpi < 72 or args.dpi > 600:
        raise SystemExit("--dpi must be between 72 and 600")

    tessdata = args.tessdata
    if tessdata and not Path(tessdata).is_dir():
        raise SystemExit(f"Tessdata directory not found: {tessdata}")

    try:
        manifest = load_manifest(manifest_path)
        validate_pdf_against_manifest(pdf_path, manifest)
        augmented = augment_manifest(
            manifest,
            pdf_path,
            languages=args.languages,
            dpi=args.dpi,
            tessdata=tessdata,
        )
    except Exception as exc:
        raise SystemExit(
            f"OCR augmentation failed: {type(exc).__name__}: {exc}"
        ) from exc

    if args.compact:
        payload = json.dumps(
            augmented,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        payload = json.dumps(
            augmented,
            ensure_ascii=False,
            indent=2,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
