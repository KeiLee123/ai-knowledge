#!/usr/bin/env python3
"""Read-only, one-PDF official Docling pilot. No DB, queue, writer or model vault.

Writes only a metadata report; does not expose extracted document text.
First use may download public models, unless --offline is selected.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import resource
import sys
import time
from pathlib import Path

SOURCE_SHA256 = "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8"
SOURCE_BYTES = 25520
SOURCE_PAGES = 5
MAX_PDF_BYTES = 5 * 1024 * 1024


def preflight(pdf: Path) -> dict:
    """Verify pinned public APP149 bytes before importing Docling/model code."""
    if pdf.name != "APP149.pdf" or pdf.is_symlink() or not pdf.is_file():
        raise ValueError("only a regular local APP149.pdf is accepted")
    size = pdf.stat().st_size
    if size != SOURCE_BYTES or size > MAX_PDF_BYTES:
        raise ValueError("APP149 file size is different from pinned source")
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("APP149 SHA256 mismatch; stop, never substitute a newer edition")
    import pymupdf
    with pymupdf.open(pdf) as source:
        if source.is_encrypted or len(source) != SOURCE_PAGES:
            raise ValueError("APP149 physical page preflight failed")
        native_chars = [len(page.get_text("text")) for page in source]
    return {"source_id": "BD_PNAP_APP149", "sha256": digest, "bytes": size,
            "physical_pages": SOURCE_PAGES, "native_text_chars_by_page": native_chars}


def parse(pdf: Path, source: dict) -> dict:
    """Run the *official* package directly, without Celery/Redis or DB hooks."""
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        document_timeout=120, do_ocr=False, do_table_structure=True,
        enable_remote_services=False, allow_external_plugins=False,
        generate_page_images=False, generate_picture_images=False,
        accelerator_options=AcceleratorOptions(num_threads=1, device=AcceleratorDevice.CPU),
    )
    started = time.monotonic()
    result = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
    ).convert(pdf, max_num_pages=SOURCE_PAGES, max_file_size=MAX_PDF_BYTES)
    duration = round(time.monotonic() - started, 2)

    status = getattr(getattr(result, "status", None), "value", None)
    doc = getattr(result, "document", None)
    pages = getattr(doc, "pages", None)
    page_numbers = sorted(pages) if isinstance(pages, dict) else []
    per_page = {str(n): {"text_chars": 0, "table_count": 0, "item_count": 0}
                for n in range(1, SOURCE_PAGES + 1)}
    ambiguous = 0
    labels = {}
    item_classes = {}
    table_collection_count = len(getattr(doc, "tables", []) or []) if doc is not None else 0
    if doc is not None:
        for raw in doc.iterate_items():
            item = raw[0] if isinstance(raw, tuple) else raw
            kind = type(item).__name__
            item_classes[kind] = item_classes.get(kind, 0) + 1
            item_label = getattr(getattr(item, "label", None), "value",
                                 getattr(item, "label", None))
            label_key = str(item_label)
            labels[label_key] = labels.get(label_key, 0) + 1
            provenance = getattr(item, "prov", None)
            if not isinstance(provenance, list) or len(provenance) != 1:
                ambiguous += 1
                continue
            number = getattr(provenance[0], "page_no", None)
            if number not in range(1, SOURCE_PAGES + 1):
                ambiguous += 1
                continue
            row = per_page[str(number)]
            row["item_count"] += 1
            if item_label == "table":
                row["table_count"] += 1
            else:
                row["text_chars"] += len(getattr(item, "text", "") or "")

    complete = (status == "success" and page_numbers == list(range(1, SOURCE_PAGES + 1))
                and ambiguous == 0 and all(v["text_chars"] > 0 for v in per_page.values()))
    return {
        "status": "MECHANICAL_PILOT_PASS_LIMITED" if complete else "AUTO_HOLD_INCOMPLETE_EVIDENCE",
        "docling_conversion_status": status,
        "docling_version": importlib.metadata.version("docling"),
        "torch_version": importlib.metadata.version("torch"),
        "docling_core_version": importlib.metadata.version("docling-core"),
        "docling_ibm_models_version": importlib.metadata.version("docling-ibm-models"),
        "docling_table_collection_count": table_collection_count,
        "docling_item_label_counts": labels,
        "docling_item_class_counts": item_classes,
        "processing_seconds": duration,
        "peak_process_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "docling_page_numbers": page_numbers,
        "per_page": per_page,
        "ambiguous_provenance_items": ambiguous,
        "model_download_policy": "automatic_cache_on_first_use_unless_offline",
        "source": source,
        "claims_not_established": [
            "semantic accuracy", "numeric table accuracy", "official edition validity",
            "VPS Staging acceptance", "DB ingestion", "Product Beta acceptance",
        ],
        "db_write_performed": False,
        "production_write_performed": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Isolated direct Docling APP149 pilot")
    p.add_argument("pdf", type=Path, help="local pinned public APP149.pdf")
    p.add_argument("--report", type=Path, required=True, help="metadata-only report JSON")
    p.add_argument("--offline", action="store_true", help="reject model downloads; cache must exist")
    args = p.parse_args()
    if args.report.suffix != ".json" or not args.report.parent.is_dir() or args.report.is_symlink():
        p.error("report parent must already exist; use an isolated private directory")
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    evidence = {"status": "AUTO_HOLD_NOT_COMPLETED", "pdf_text_exposed": False}
    rc = 1
    try:
        source = preflight(args.pdf)
        evidence = parse(args.pdf, source)
        rc = 0 if evidence["status"] == "MECHANICAL_PILOT_PASS_LIMITED" else 1
    except Exception as exc:
        evidence = {"status": "AUTO_HOLD_EXCEPTION", "exception_type": type(exc).__name__,
                    "pdf_text_exposed": False, "db_write_performed": False,
                    "production_write_performed": False}
        print("AUTO_HOLD_EXCEPTION: " + type(exc).__name__, file=sys.stderr)
    temp = args.report.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp, args.report)
    print(json.dumps({"status": evidence["status"], "report": str(args.report)}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
