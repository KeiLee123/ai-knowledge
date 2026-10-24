#!/usr/bin/env python3

from pathlib import Path
import json
import tempfile

from route_document_v2 import assess_manifest
from build_multimodal_chunks_v2 import (
    build_output,
    unit_evidence,
)
from ingest_manifest_v2 import merged_chunk_metadata


CHECKSUM = "a" * 64


def manifest_with_units(units):
    return {
        "schema_version": "document-manifest-v2",
        "source": {
            "filename": "Construction-Drawing.pdf",
            "sha256": CHECKSUM,
        },
        "document": {
            "kind": "pdf",
            "page_count": 44,
        },
        "selection": {
            "page_numbers": None,
        },
        "units": units,
    }


def page(
    page_number,
    text="",
    *,
    width=1000,
    height=1000,
    images=None,
    tables=None,
    vector_items=0,
    ocr_candidate=False,
    visual_candidate=False,
    ocr=None,
    vision=None,
):
    return {
        "unit_index": page_number - 1,
        "unit_type": "page",
        "page_number": page_number,
        "width": width,
        "height": height,
        "text": text,
        "text_chars": len(text),
        "images": images or [],
        "tables": tables or [],
        "vector_metrics": {
            "meaningful_drawing_item_count": vector_items,
        },
        "ocr_candidate": ocr_candidate,
        "visual_candidate": visual_candidate,
        "blank": False,
        "ocr": ocr or {},
        "vision": vision or {},
    }


def assert_router_contract():
    p2 = page(
        2,
        text="Coursework 50%\nExamination 50%",
    )

    p44 = page(
        44,
        text="",
        images=[
            {
                "bbox": [0, 0, 800, 800],
            }
        ],
        vector_items=700,
        ocr_candidate=True,
        visual_candidate=True,
    )

    route = assess_manifest(
        manifest_with_units([p2, p44]),
        allow_partial=False,
    )

    decision = route["decision"]
    summary = route["signal_summary"]

    assert decision["eligible_for_v2"] is True
    assert decision["recommended_pipeline"] == "multimodal-v2"
    assert 44 in summary["strong_signal_pages"]

    reasons = set(
        route["unit_assessments"][1]["route_reasons"]
    )

    assert "high_vector_complexity" in reasons
    assert "low_text_image" in reasons


def assert_evidence_normalization_contract():
    native = page(
        2,
        text="Coursework 50%",
    )

    evidence = unit_evidence(native)

    assert len(evidence) == 1
    assert evidence[0]["origin"] == "native_text"
    assert evidence[0]["tier"] == "primary"
    assert evidence[0]["derived"] is False

    fused = page(
        3,
        text="Native heading",
        ocr={
            "status": "text_recovered",
            "text": "OCR body",
            "engine": "tesseract",
            "engine_version": "test",
            "languages": ["eng"],
            "dpi": 300,
        },
    )

    evidence = unit_evidence(fused)

    assert len(evidence) == 1
    assert evidence[0]["origin"] == "fused_text"
    assert evidence[0]["tier"] == "primary"
    assert evidence[0]["derived"] is True

    visual = page(
        44,
        vision={
            "status": "described",
            "model": "test-model",
            "prompt_version": "visual-evidence-v1",
            "result": {
                "useful": True,
                "retrieval_text": (
                    "The drawing contains Top, Front and Side views."
                ),
                "confidence": 0.9,
                "page_type": "technical_drawing",
            },
        },
    )

    evidence = unit_evidence(visual)

    assert len(evidence) == 1
    assert evidence[0]["origin"] == "visual_understanding"
    assert evidence[0]["tier"] == "supplementary"
    assert evidence[0]["derived"] is True


def assert_structured_table_evidence_contract():
    p6 = page(
        6,
        text="General requirements",
        tables=[
            {
                "table_index": 0,
                "detection_strategy": "lines",
                "bbox": [10.0, 20.0, 900.0, 400.0],
                "row_count": 3,
                "column_count": 3,
                "rows": [
                    [
                        "Item",
                        "Requirement",
                        "Limit",
                    ],
                    [
                        "Concrete cover",
                        "Minimum cover",
                        "40 mm",
                    ],
                    [
                        "Fire resistance",
                        "Rating",
                        "2 hours",
                    ],
                ],
            }
        ],
    )

    evidence = unit_evidence(p6)

    table_items = [
        item
        for item in evidence
        if item["origin"] == "structured_table"
    ]

    assert len(table_items) == 1

    table = table_items[0]

    assert table["modality"] == "table"
    assert table["tier"] == "primary"
    assert table["derived"] is True
    assert table["derivation"]["type"] == (
        "table_extraction"
    )
    assert table["metadata"]["table_index"] == 0
    assert table["metadata"]["table_row_count"] == 3
    assert table["metadata"]["table_column_count"] == 3
    assert table["metadata"]["table_bbox"] == [
        10.0,
        20.0,
        900.0,
        400.0,
    ]
    assert table["metadata"][
        "table_detection_strategy"
    ] == "lines"

    assert "Table 1" in table["text"]
    assert (
        "Row 2: Concrete cover | Minimum cover | 40 mm"
        in table["text"]
    )
    assert (
        "Row 3: Fire resistance | Rating | 2 hours"
        in table["text"]
    )

    manifest = manifest_with_units([p6])

    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "phase-a.json"
        manifest_path.write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        output = build_output(
            manifest_path=manifest_path,
            manifest=manifest,
            target_chars=1800,
            overlap_chars=250,
        )

    table_chunks = [
        chunk
        for chunk in output["chunks"]
        if chunk["metadata"]["evidence_origin"]
        == "structured_table"
    ]

    assert len(table_chunks) == 1

    chunk = table_chunks[0]
    metadata = chunk["metadata"]

    assert chunk["page_start"] == 6
    assert chunk["page_end"] == 6
    assert metadata["page_number"] == 6
    assert metadata["modality"] == "table"
    assert metadata["evidence_tier"] == "primary"
    assert metadata["table_index"] == 0
    assert metadata["table_row_count"] == 3
    assert metadata["table_column_count"] == 3
    assert metadata["table_detection_strategy"] == "lines"

    assert output["policy"]["structured_table"] == "primary"
    assert output["summary"]["counts_by_origin"][
        "structured_table"
    ] == 1
    assert output["summary"]["counts_by_modality"][
        "table"
    ] == 1

    merged = merged_chunk_metadata(
        chunk,
        synthetic=False,
    )

    assert merged["retrieval_role"] == (
        "multimodal-primary"
    )


def assert_provenance_contract():
    p44 = page(
        44,
        vision={
            "status": "described",
            "model": "test-model",
            "prompt_version": "visual-evidence-v1",
            "result": {
                "useful": True,
                "retrieval_text": "Front view includes a visible diameter label.",
                "confidence": 0.9,
                "page_type": "technical_drawing",
            },
        },
    )

    manifest = manifest_with_units([p44])

    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "phase-c.json"
        manifest_path.write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        output = build_output(
            manifest_path=manifest_path,
            manifest=manifest,
            target_chars=1800,
            overlap_chars=250,
        )

    assert output["source_manifest"]["document_sha256"] == CHECKSUM
    assert output["source_manifest"]["document_name"] == (
        "Construction-Drawing.pdf"
    )

    assert len(output["chunks"]) == 1

    chunk = output["chunks"][0]

    assert chunk["page_start"] == 44
    assert chunk["page_end"] == 44
    assert chunk["metadata"]["page_number"] == 44
    assert chunk["metadata"]["evidence_origin"] == (
        "visual_understanding"
    )
    assert chunk["metadata"]["evidence_tier"] == "supplementary"

    merged = merged_chunk_metadata(
        chunk,
        synthetic=False,
    )

    assert merged["retrieval_role"] == (
        "multimodal-supplementary"
    )
    assert merged["synthetic"] is False
    assert merged["ingestion_version"] == "v2"


def assert_release_artifact_path_independence():
    manifest = manifest_with_units([
        page(
            1,
            text=(
                "Authorized signatory "
                "requirements for minor works."
            ),
        )
    ])

    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    )

    with (
        tempfile.TemporaryDirectory() as tmp1,
        tempfile.TemporaryDirectory() as tmp2,
    ):
        path1 = Path(tmp1) / "phase-a.json"
        path2 = Path(tmp2) / "phase-a.json"

        path1.write_text(
            payload,
            encoding="utf-8",
        )
        path2.write_text(
            payload,
            encoding="utf-8",
        )

        output1 = build_output(
            manifest_path=path1,
            manifest=manifest,
            target_chars=1800,
            overlap_chars=250,
        )

        output2 = build_output(
            manifest_path=path2,
            manifest=manifest,
            target_chars=1800,
            overlap_chars=250,
        )

    assert output1 == output2

    assert output1[
        "source_manifest"
    ]["path"] == "phase-a.json"

    assert output1[
        "source_manifest"
    ]["sha256"] == output2[
        "source_manifest"
    ]["sha256"]


def assert_no_write_contract():
    route = assess_manifest(
        manifest_with_units([
            page(
                44,
                text="",
                images=[{"bbox": [0, 0, 800, 800]}],
                vector_items=700,
                ocr_candidate=True,
                visual_candidate=True,
            )
        ]),
        allow_partial=False,
    )

    safety = route["safety"]

    assert safety["model_call_performed"] is False
    assert safety["embedding_performed"] is False
    assert safety["database_write_performed"] is False
    assert safety["production_pipeline_modified"] is False


def main():
    assert_router_contract()
    assert_evidence_normalization_contract()
    assert_structured_table_evidence_contract()
    assert_provenance_contract()
    assert_release_artifact_path_independence()
    assert_no_write_contract()

    print("Multimodal ingestion contract test PASS")
    print("Router contract: PASS")
    print("Evidence normalization contract: PASS")
    print("Structured table evidence contract: PASS")
    print("Provenance contract: PASS")
    print("Release artifact path independence: PASS")
    print("No-write safety contract: PASS")


if __name__ == "__main__":
    main()