#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


ROUTER_VERSION = "phase-d5-1"
SUPPORTED_SCHEMA = "document-manifest-v2"

OCR_IMAGE_COVERAGE_THRESHOLD = 0.10
LOW_TEXT_IMAGE_THRESHOLD = 250
LARGE_IMAGE_COVERAGE_THRESHOLD = 0.25
LARGE_IMAGE_TEXT_THRESHOLD = 300
VECTOR_ITEM_THRESHOLD = 500


def load_manifest(path: Path) -> dict:
    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        data.get("schema_version")
        != SUPPORTED_SCHEMA
    ):
        raise RuntimeError(
            "Unsupported manifest schema: "
            f"{data.get('schema_version')!r}"
        )

    if not isinstance(
        data.get("units"),
        list,
    ):
        raise RuntimeError(
            "Manifest units must be a list"
        )

    return data


def image_coverage(
    unit: dict,
) -> float:
    width = unit.get("width")
    height = unit.get("height")

    try:
        page_area = (
            float(width)
            * float(height)
        )
    except (TypeError, ValueError):
        return 0.0

    if page_area <= 0:
        return 0.0

    best = 0.0

    for image in (
        unit.get("images")
        or []
    ):
        bbox = image.get("bbox")

        if (
            not isinstance(
                bbox,
                list,
            )
            or len(bbox) != 4
        ):
            continue

        try:
            x0, y0, x1, y1 = [
                float(value)
                for value in bbox
            ]
        except (
            TypeError,
            ValueError,
        ):
            continue

        area = max(
            0.0,
            x1 - x0,
        ) * max(
            0.0,
            y1 - y0,
        )

        best = max(
            best,
            area / page_area,
        )

    return min(
        1.0,
        best,
    )


def assess_unit(
    unit: dict,
) -> dict:
    page = unit.get("page_number")
    text_chars = int(
        unit.get("text_chars")
        or 0
    )

    images = (
        unit.get("images")
        or []
    )

    image_count = len(
        images
    )

    coverage = image_coverage(
        unit
    )

    vector_metrics = (
        unit.get(
            "vector_metrics"
        )
        or {}
    )

    vector_items = int(
        vector_metrics.get(
            "meaningful_drawing_item_count"
        )
        or 0
    )

    ocr_candidate = bool(
        unit.get(
            "ocr_candidate"
        )
    )

    strong_ocr_candidate = (
        ocr_candidate
        and (
            coverage
            >= OCR_IMAGE_COVERAGE_THRESHOLD
        )
    )

    low_text_image = (
        image_count > 0
        and text_chars
        < LOW_TEXT_IMAGE_THRESHOLD
        and coverage
        >= OCR_IMAGE_COVERAGE_THRESHOLD
    )

    large_image_low_text = (
        image_count > 0
        and coverage
        >= LARGE_IMAGE_COVERAGE_THRESHOLD
        and text_chars
        < LARGE_IMAGE_TEXT_THRESHOLD
    )

    high_vector_complexity = (
        vector_items
        >= VECTOR_ITEM_THRESHOLD
    )

    reasons = []

    if strong_ocr_candidate:
        reasons.append(
            "ocr_scan_candidate"
        )

    if low_text_image:
        reasons.append(
            "low_text_image"
        )

    if large_image_low_text:
        reasons.append(
            "large_image_low_text"
        )

    if high_vector_complexity:
        reasons.append(
            "high_vector_complexity"
        )

    return {
        "page_number":
            page,
        "text_chars":
            text_chars,
        "image_count":
            image_count,
        "max_image_coverage":
            round(
                coverage,
                4,
            ),
        "vector_items":
            vector_items,
        "ocr_candidate":
            ocr_candidate,
        "strong_ocr_candidate":
            strong_ocr_candidate,
        "low_text_image":
            low_text_image,
        "large_image_low_text":
            large_image_low_text,
        "high_vector_complexity":
            high_vector_complexity,
        "route_reasons":
            reasons,
    }


def assess_manifest(
    manifest: dict,
    allow_partial: bool,
) -> dict:
    document = (
        manifest.get("document")
        or {}
    )

    selection = (
        manifest.get("selection")
        or {}
    )

    kind = document.get(
        "kind"
    )

    selected_pages = (
        selection.get(
            "page_numbers"
        )
    )

    partial_manifest = bool(
        selected_pages
    )

    units = [
        unit
        for unit in manifest["units"]
        if (
            unit.get("unit_type")
            == "page"
        )
    ]

    unit_assessments = [
        assess_unit(unit)
        for unit in units
    ]

    strong_pages = [
        item
        for item in unit_assessments
        if item[
            "route_reasons"
        ]
    ]

    reason_pages = {}

    for item in strong_pages:
        for reason in (
            item["route_reasons"]
        ):
            reason_pages.setdefault(
                reason,
                [],
            ).append(
                item[
                    "page_number"
                ]
            )

    eligible_by_signal = (
        kind == "pdf"
        and bool(
            strong_pages
        )
    )

    production_decision_valid = (
        not partial_manifest
        or allow_partial
    )

    eligible = (
        eligible_by_signal
        and production_decision_valid
    )

    reasons = []

    if kind != "pdf":
        reasons.append(
            "non_pdf_uses_v1"
        )

    elif partial_manifest and not allow_partial:
        reasons.append(
            "partial_manifest_not_valid_for_production_routing"
        )

    elif eligible_by_signal:
        reasons.append(
            "strong_multimodal_signal_detected"
        )

    else:
        reasons.append(
            "no_strong_multimodal_signal"
        )

    recommended_pipeline = (
        "multimodal-v2"
        if eligible
        else "legacy-v1"
    )

    return {
        "router_version":
            ROUTER_VERSION,
        "schema_version":
            manifest.get(
                "schema_version"
            ),
        "source": {
            "filename":
                (
                    manifest.get(
                        "source"
                    )
                    or {}
                ).get(
                    "filename"
                ),
            "sha256":
                (
                    manifest.get(
                        "source"
                    )
                    or {}
                ).get(
                    "sha256"
                ),
        },
        "document": {
            "kind":
                kind,
            "page_count":
                document.get(
                    "page_count"
                ),
            "manifest_unit_count":
                len(units),
            "partial_manifest":
                partial_manifest,
            "selected_pages":
                selected_pages,
        },
        "decision": {
            "eligible_for_v2":
                eligible,
            "eligible_by_signal":
                eligible_by_signal,
            "production_decision_valid":
                production_decision_valid,
            "recommended_pipeline":
                recommended_pipeline,
            "reasons":
                reasons,
        },
        "signal_summary": {
            "strong_signal_pages": [
                item[
                    "page_number"
                ]
                for item in strong_pages
            ],
            "reason_pages":
                reason_pages,
            "strong_signal_page_count":
                len(strong_pages),
            "max_vector_items":
                max(
                    (
                        item[
                            "vector_items"
                        ]
                        for item
                        in unit_assessments
                    ),
                    default=0,
                ),
            "max_image_coverage":
                round(
                    max(
                        (
                            item[
                                "max_image_coverage"
                            ]
                            for item
                            in unit_assessments
                        ),
                        default=0.0,
                    ),
                    4,
                ),
        },
        "thresholds": {
            "ocr_image_coverage":
                OCR_IMAGE_COVERAGE_THRESHOLD,
            "low_text_image_chars":
                LOW_TEXT_IMAGE_THRESHOLD,
            "large_image_coverage":
                LARGE_IMAGE_COVERAGE_THRESHOLD,
            "large_image_text_chars":
                LARGE_IMAGE_TEXT_THRESHOLD,
            "vector_items":
                VECTOR_ITEM_THRESHOLD,
        },
        "unit_assessments":
            unit_assessments,
        "safety": {
            "model_call_performed":
                False,
            "embedding_performed":
                False,
            "database_write_performed":
                False,
            "production_pipeline_modified":
                False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically route a "
            "document-manifest-v2 to legacy v1 "
            "or multimodal v2. No model calls, "
            "embeddings, or DB writes."
        )
    )

    parser.add_argument(
        "manifest",
        help=(
            "Phase A document-manifest-v2 JSON"
        ),
    )

    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Allow a diagnostic partial-page "
            "manifest to produce a v2 decision. "
            "Do not use for production routing."
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Optional JSON output path"
        ),
    )

    args = parser.parse_args()

    path = Path(
        args.manifest
    )

    if not path.is_file():
        raise SystemExit(
            f"Manifest not found: {path}"
        )

    try:
        manifest = load_manifest(
            path
        )

        result = assess_manifest(
            manifest,
            allow_partial=
                args.allow_partial,
        )

    except Exception as exc:
        raise SystemExit(
            "Routing assessment failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    payload = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )

    if args.output:
        output = Path(
            args.output
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            payload + "\n",
            encoding="utf-8",
        )

        print(output)

    else:
        print(payload)


if __name__ == "__main__":
    main()
