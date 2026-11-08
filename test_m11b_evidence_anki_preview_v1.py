#!/usr/bin/env python3
"""Offline M11B contract tests; all source text, PDF, and DB packets are synthetic."""
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import m11b_evidence_anki_preview_v1 as b


def fake_packet():
    case = b.build_app149_candidate_suite()["cases"][0]
    ev = [{
        "id": "S" + str(n),
        "page": 1 if n == 1 else min(5, n),
        "chunk_id": 100 + n,
        "content": (
            case["context_before"] + " " + case["evidence_quote"]
            + " " + case["context_after"]
            if n == 1 else "Synthetic unrelated native evidence unit " + str(n)
        ),
    } for n in range(1, 9)]
    return {
        "environment": "staging",
        "database": b.qa.STAGING_DB_CONTAINER,
        "guard_ok": True,
        "read_only": True,
        "production_write": False,
        "question": case["query"],
        "source": {
            "source_id": b.PINNED_SOURCE_ID,
            "checksum": b.PINNED_PDF_SHA256,
            "official_url": b.OFFICIAL_URL,
            "title": "APP149",
            "revision_date": "NOT_VERIFIED",
            "currentness_verified": False,
        },
        "retrieval_coverage": {
            "complete_index_coverage": True,
            "indexed_chunks": 8,
            "retrieved_unique_chunks": 8,
        },
        "evidence": ev,
    }


def fake_silver():
    suite = b.build_app149_candidate_suite()
    cases = [{
        "case_id": c["case_id"],
        "status": ("MACHINE_EVIDENCE_CHECKED"
                   if c["case_id"] == b.CASE_ID else "HUMAN_REVIEW_REQUIRED"),
        "official_gold_approved": False,
        "human_reviewed": False,
    } for c in suite["cases"]]
    return {
        "source_id": b.PINNED_SOURCE_ID,
        "expected_original_pdf_sha256": b.PINNED_PDF_SHA256,
        "source_version": b.PINNED_DOCUMENT_VERSION,
        "case_count": 5,
        "human_gold_cases_approved": 0,
        "counts": {
            "MACHINE_EVIDENCE_CHECKED": 1,
            "HUMAN_REVIEW_REQUIRED": 4,
            "REJECTED_EVIDENCE_MISMATCH": 0,
        },
        "cases": cases,
    }


def refused(fn):
    try:
        fn()
    except b.PreviewRefused:
        return
    raise AssertionError("M11B unsafe candidate accepted")


def accepted():
    return b.build_preview_from_verified_packet(fake_packet(), fake_silver())


def test_one_low_risk_historical_preview_uses_existing_anki_schema():
    result = accepted()
    assert result["candidate_status"] == "TEST_ONLY_LITERAL_PREVIEW"
    assert result["quality"]["official_gold_approved"] == 0
    assert result["quality"]["publish_authorized"] is False
    assert result["quality"]["semantic_answer_accuracy"] == "UNKNOWN_NOT_MEASURED"
    assert result["external_ai_called"] is False
    assert result["anki_package_created"] is False
    manifest = result["manifest"]
    assert manifest["schema_version"] == "anki-card-preview-v1"
    assert manifest["exportable"] is False
    assert manifest["release_authorized"] is False
    assert manifest["generation"]["generated_card_count"] == 1
    assert manifest["generation"]["model_call_performed"] is False
    assert manifest["generation"]["literal_source_preview_only"] is True
    card = manifest["cards"][0]
    assert card["answer"] == "authorized signatory"
    assert "2010-12" in card["question"]
    assert card["source"]["chunk_ids"] == [101]
    assert card["source"]["document_id"] is None  # DB ID is not supplied
    assert card["source"]["page_start"] == 1
    assert card["source"]["document_checksum"] == b.PINNED_PDF_SHA256
    assert card["quality"]["release_authorized"] is False
    assert card["quality"]["legal_applicability_verified"] is False
    assert "test_only" in card["tags"]
    assert accepted()["manifest"]["cards"][0]["card_key"] == card["card_key"]


def test_source_currentness_database_checkout_and_coverage_fail_closed():
    packet = fake_packet()
    packet["source"]["currentness_verified"] = True
    refused(lambda: b.build_preview_from_verified_packet(packet, fake_silver()))
    packet = fake_packet()
    packet["database"] = "not_staging"
    refused(lambda: b.build_preview_from_verified_packet(packet, fake_silver()))
    packet = fake_packet()
    packet["retrieval_coverage"]["complete_index_coverage"] = False
    refused(lambda: b.build_preview_from_verified_packet(packet, fake_silver()))
    packet = fake_packet()
    packet["source"]["checksum"] = "0" * 64
    refused(lambda: b.build_preview_from_verified_packet(packet, fake_silver()))


def test_dangerous_silver_promotion_refused():
    silver = fake_silver()
    silver["cases"][1]["status"] = "MACHINE_EVIDENCE_CHECKED"
    refused(lambda: b.build_preview_from_verified_packet(fake_packet(), silver))
    silver = fake_silver()
    silver["cases"][0]["human_reviewed"] = True
    refused(lambda: b.build_preview_from_verified_packet(fake_packet(), silver))
    silver = fake_silver()
    silver["counts"]["HUMAN_REVIEW_REQUIRED"] = 3
    refused(lambda: b.build_preview_from_verified_packet(fake_packet(), silver))


def test_missing_or_duplicate_quote_auto_hold_no_card():
    packet = fake_packet()
    packet["evidence"][0]["content"] = "A quote from a different paragraph"
    r = b.build_preview_from_verified_packet(packet, fake_silver())
    assert r["candidate_status"] == "AUTO_HOLD"
    assert r["manifest"] is None
    assert r["anki_package_created"] is False
    packet = fake_packet()
    packet["evidence"][1]["page"] = 1
    packet["evidence"][1]["content"] = packet["evidence"][0]["content"]
    r = b.build_preview_from_verified_packet(packet, fake_silver())
    assert r["candidate_status"] == "AUTO_HOLD"
    assert r["manifest"] is None


def test_source_sha_symlink_and_network_safety_before_retrieval():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.pdf"
        raw = b"%PDF-1.4 synthetic test bytes only\n" * 8
        path.write_bytes(raw)
        with patch.object(b.qa, "build_packet",
                          side_effect=AssertionError("no Staging IO")):
            refused(lambda: b.build_preview(path))
            link = Path(tmp) / "symlink.pdf"
            link.symlink_to(path)
            refused(lambda: b.build_preview(link))


def test_cli_strict_stdout_with_noisy_underlying_module():
    stdout, stderr = io.StringIO(), io.StringIO()

    def noisy(*args):
        print("SYNTHETIC_PDF_DIAGNOSTIC")
        return {"candidate_status": "AUTO_HOLD", "manifest": None}

    with patch.object(b, "build_preview", side_effect=noisy), \
         patch("sys.argv", ["m11b", "--pdf", "ignored.pdf"]), \
         contextlib.redirect_stdout(stdout), \
         contextlib.redirect_stderr(stderr):
        b.main()
    assert json.loads(stdout.getvalue())["candidate_status"] == "AUTO_HOLD"
    assert "SYNTHETIC_PDF_DIAGNOSTIC" in stderr.getvalue()
    assert "SYNTHETIC_PDF_DIAGNOSTIC" not in stdout.getvalue()


def test_test_only_preview_rejected_by_existing_exporter():
    import export_anki_package_v1 as exporter

    payload = accepted()["manifest"]
    assert payload["schema_version"] != exporter.SUPPORTED_SCHEMA
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        manifest = root / "preview.json"
        apkg = root / "UNAUTHORIZED.apkg"
        manifest.write_text(json.dumps(payload, ensure_ascii=False),
                            encoding="utf-8")
        try:
            exporter.load_manifest(manifest)
        except RuntimeError as exc:
            assert "Unsupported manifest schema" in str(exc)
        else:
            raise AssertionError("TEST-only preview accepted by exporter")

        with patch("sys.argv", ["existing-exporter", str(manifest),
                                "--output", str(apkg)]), \\
             contextlib.redirect_stdout(io.StringIO()):
            try:
                exporter.main()
            except SystemExit as exc:
                assert "Unsupported manifest schema" in str(exc)
            else:
                raise AssertionError("TEST-only preview was exported")
        assert not apkg.exists()


def test_existing_exporter_disposable_synthetic_export_fixture_only():
    """Export runs ONLY after an explicit transformation inside this CI test.

    This is a synthetic test fixture, not a product converter or a release path.
    The M11B feature module itself must never perform this transformation.
    """
    import export_anki_package_v1 as exporter

    payload = copy.deepcopy(accepted()["manifest"])
    assert payload["schema_version"] == "anki-card-preview-v1"
    payload["schema_version"] = exporter.SUPPORTED_SCHEMA
    payload.pop("exportable")
    payload.pop("release_authorized")
    payload["deck"]["name"] = "CI ONLY :: synthetic Anki exporter fixture"
    payload["generation"]["literal_source_preview_only"] = False
    for card in payload["cards"]:
        card.pop("quality")
        card["tags"] = ["synthetic", "ci_only"]
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        manifest = root / "synthetic-exportable-fixture.json"
        apkg = root / "synthetic-ci-fixture.apkg"
        manifest.write_text(json.dumps(payload, ensure_ascii=False),
                            encoding="utf-8")
        with patch("sys.argv", ["existing-exporter", str(manifest),
                                "--output", str(apkg)]), \\
             contextlib.redirect_stdout(io.StringIO()):
            exporter.main()
        assert apkg.is_file()
        with zipfile.ZipFile(apkg) as archive:
            assert "collection.anki2" in archive.namelist()
            assert "media" in archive.namelist()
        assert apkg.stat().st_size > 1000
    assert not apkg.exists()


def test_no_external_generation_write_or_collection_access():
    code = Path(b.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "generate_draft(", "call_model(", "get_model_config(",
        "api.deepseek.com", "urllib.request", "INSERT INTO",
        "subprocess.run(", "AnkiConnect", "localhost:8765",
        "gdrive-bd-write:", "genanki.Package(", "write_to_file(",
        "os.system(", "0.0.0.0",
    ):
        assert forbidden not in code, forbidden


def main():
    for key, fn in sorted(globals().items()):
        if key.startswith("test_") and callable(fn):
            fn()
            print(key + ": PASS")
    print("M11B SOURCE->EVIDENCE->TEST ANKI PREVIEW OFFLINE: PASS")


if __name__ == "__main__":
    main()
