"""Offline Phase B safety and compatibility regression; not VPS acceptance."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import yaml

from build_multimodal_chunks_v2 import build_chunks
from phase_b_shadow.contract import ContractGap, load_fixture, task_id
from phase_b_shadow.docling_adapter import build_manifest
from phase_b_shadow.runner import run_fixture


def box(l=10, t=10, r=100, b=30, origin="TOPLEFT"):
    return NS(l=l, t=t, r=r, b=b, coord_origin=origin)


def document(table=True, table_span=1, page_no=1):
    items = [NS(label="paragraph", text="Verified source text", prov=[NS(page_no=page_no, bbox=box())])]
    if table:
        cells = [NS(start_row_offset_idx=0, start_col_offset_idx=0, row_span=table_span,
                    col_span=1, text="17.5", bbox=box(12, 40, 80, 55))]
        items.append(NS(label="table", data=NS(num_rows=1, num_cols=1, table_cells=cells),
                        prov=[NS(page_no=1, bbox=box(10, 35, 100, 60))]))
    return NS(pages={1: NS(size=NS(width=612, height=792))},
              iterate_items=lambda: ((item, 0) for item in items))


class PhaseBShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.input_dir = base / "fixtures"
        self.output_dir = base / "artifacts"
        self.model_dir = base / "models"
        for directory in (self.input_dir, self.output_dir, self.model_dir):
            directory.mkdir()
        (self.model_dir / "model-version.txt").write_text("operator-reviewed-test-model-v1\n", encoding="utf-8")
        self.pdf = self.input_dir / "APP149.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n% offline contract fixture only\n")
        self.sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.entry = {"source_id": "BD_PNAP_APP149", "version_id": "offline_test_v1",
                      "model_version": "operator-reviewed-test-model-v1",
                      "filename": "APP149.pdf", "sha256": self.sha}
        self.write_catalog()

    def write_catalog(self):
        (self.input_dir / "catalog.json").write_text(
            json.dumps({"fixtures": {"app149_small": self.entry}}), encoding="utf-8")

    def fixture(self):
        return load_fixture(self.input_dir / "catalog.json", "app149_small", self.input_dir)[0]

    def test_sha_and_rejected_source_path_url(self):
        fixture = self.fixture()
        self.assertEqual(fixture.sha256, self.sha)
        self.assertEqual(task_id(fixture), task_id(fixture))
        for name in ("../APP149.pdf", "https://bd.gov.hk/APP149.pdf", "C:/APP149.pdf"):
            self.entry["filename"] = name
            self.write_catalog()
            with self.assertRaises(ContractGap):
                self.fixture()
        self.entry["filename"] = "APP149.pdf"
        self.entry["sha256"] = "0" * 64
        self.write_catalog()
        with self.assertRaises(ContractGap):
            self.fixture()
        self.entry["sha256"] = self.sha
        self.entry["source_id"] = "UNREGISTERED"
        self.write_catalog()
        with self.assertRaises(ContractGap):
            self.fixture()

    def test_manifest_page_table_and_chunk_provenance(self):
        manifest = build_manifest(document(), self.fixture(), self.pdf, "2.146.0", "test-model-v1")
        self.assertEqual(manifest["schema_version"], "document-manifest-v2")
        self.assertEqual(manifest["source"]["sha256"], self.sha)
        self.assertEqual(manifest["document"]["version_id"], "offline_test_v1")
        unit = manifest["units"][0]
        self.assertEqual(unit["page_number"], 1)
        self.assertEqual(unit["reading_order"][0]["order"], 0)
        table = unit["tables"][0]
        self.assertEqual(table["rows"], [["17.5"]])
        self.assertEqual(table["cell_provenance"][0]["bbox"], [12, 40, 80, 55])
        chunks = build_chunks(manifest, 1800, 250)
        self.assertEqual([c["metadata"]["evidence_origin"] for c in chunks],
                         ["native_text", "structured_table"])
        self.assertTrue(all(c["page_start"] == 1 for c in chunks))

    def test_bottom_left_conversion_and_gap_holds(self):
        doc = document(table=False)
        item = next(doc.iterate_items())[0]
        item.prov[0].bbox = box(10, 782, 100, 762, "BOTTOMLEFT")
        manifest = build_manifest(doc, self.fixture(), self.pdf, "2.146.0", "test-model-v1")
        self.assertEqual(manifest["units"][0]["reading_order"][0]["bbox"], [10, 10, 100, 30])
        for bad in (document(table_span=2), document(page_no=2)):
            with self.assertRaises(ContractGap):
                build_manifest(bad, self.fixture(), self.pdf, "2.146.0", "test-model-v1")
        doc = document(table=False)
        next(doc.iterate_items())[0].prov = []
        with self.assertRaises(ContractGap):
            build_manifest(doc, self.fixture(), self.pdf, "2.146.0", "test-model-v1")

    def test_runner_is_staging_only_atomic_and_duplicate_safe(self):
        calls = []
        def fake_converter(source, model_dir):
            calls.append(source)
            return document()
        with patch.dict(os.environ, {"JASON_OS_ENV": "production"}):
            with self.assertRaises(ContractGap):
                run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                            self.model_dir, fake_converter, "2.146.0")
        with patch.dict(os.environ, {"JASON_OS_ENV": "staging"}):
            first = run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                                self.model_dir, fake_converter, "2.146.0")
            second = run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                                 self.model_dir, fake_converter, "2.146.0")
        self.assertEqual(first["status"], "READY_SHADOW")
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(list(self.output_dir.glob("*.manifest.json"))), 1)
        self.assertFalse(list(self.output_dir.glob("*.lock")))
        self.assertFalse(first["database_write_performed"])
        (self.output_dir / first["manifest"]).write_text("tampered", encoding="utf-8")
        with patch.dict(os.environ, {"JASON_OS_ENV": "staging"}):
            with self.assertRaises(ContractGap):
                run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                            self.model_dir, fake_converter, "2.146.0")

    def test_existing_lock_and_contract_gap_fail_closed(self):
        fixture = self.fixture()
        lock = self.output_dir / f"{task_id(fixture)}.lock"
        lock.write_text("crashed", encoding="utf-8")
        with patch.dict(os.environ, {"JASON_OS_ENV": "staging"}):
            with self.assertRaises(ContractGap):
                run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                            self.model_dir, lambda *_: document(), "2.146.0")
        lock.unlink()
        with patch.dict(os.environ, {"JASON_OS_ENV": "staging"}):
            result = run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                                 self.model_dir, lambda *_: document(table_span=2), "2.146.0")
        self.assertEqual(result["status"], "AUTO_HOLD_CONTRACT_GAP")
        self.assertFalse(list(self.output_dir.glob("*.manifest.json")))

    def test_model_version_mismatch_holds_before_conversion(self):
        (self.model_dir / "model-version.txt").write_text("different-model", encoding="utf-8")
        with patch.dict(os.environ, {"JASON_OS_ENV": "staging"}):
            result = run_fixture("app149_small", self.sha, self.input_dir, self.output_dir,
                                 self.model_dir, lambda *_: self.fail("converter must not run"), "2.146.0")
        self.assertEqual(result["status"], "AUTO_HOLD_CONTRACT_GAP")
        self.assertFalse(list(self.output_dir.glob("*.manifest.json")))

    def test_celery_and_compose_isolation_contract(self):
        compose = yaml.safe_load((Path(__file__).parent / "ops/phase_b_shadow/compose.yaml").read_text(encoding="utf-8"))
        redis = compose["services"]["redis"]
        worker = compose["services"]["worker"]
        self.assertNotIn("ports", redis)
        self.assertNotIn("ports", worker)
        self.assertEqual(set(compose["services"]), {"redis", "worker"})
        self.assertTrue(compose["networks"]["phase_b_broker"]["internal"])
        self.assertEqual(worker["cpus"], 1.0)
        self.assertEqual(worker["mem_limit"], "3g")
        self.assertEqual(redis["mem_limit"], "256m")
        self.assertNotIn("beat", str(compose).lower())
        self.assertNotIn("docker.sock", str(compose))
        self.assertNotIn("postgres", str(compose).lower())
        self.assertNotIn("coolify-redis", str(compose))
        with patch.dict(os.environ, {"PHASE_B_REDIS_PASSWORD_FILE": str(self.model_dir / "redis-password")}):
            (self.model_dir / "redis-password").write_text("this-is-a-test-only-long-password", encoding="utf-8")
            from phase_b_shadow.celery_app import app, parse_pdf, QUEUE
            self.assertEqual(app.conf.task_serializer, "json")
            self.assertEqual(app.conf.accept_content, ["json"])
            self.assertEqual(app.conf.task_routes["phase_b_shadow.parse_pdf"]["queue"], QUEUE)
            self.assertEqual(parse_pdf.max_retries, 2)
            self.assertEqual(parse_pdf.soft_time_limit, 150)
            self.assertEqual(parse_pdf.time_limit, 180)
            self.assertTrue(app.conf.task_acks_late)

    def test_transient_io_retry_is_bounded(self):
        with patch.dict(os.environ, {"PHASE_B_REDIS_PASSWORD_FILE": str(self.model_dir / "redis-password"),
                                  "PHASE_B_INPUT_DIR": str(self.input_dir),
                                  "PHASE_B_OUTPUT_DIR": str(self.output_dir),
                                  "PHASE_B_MODEL_DIR": str(self.model_dir)}):
            (self.model_dir / "redis-password").write_text("this-is-a-test-only-long-password", encoding="utf-8")
            from phase_b_shadow.celery_app import parse_pdf
            with patch("phase_b_shadow.celery_app.run_fixture", side_effect=OSError("temporary disk failure")) as runner:
                result = parse_pdf.apply(args=("app149_small", self.sha), throw=False)
            self.assertTrue(result.failed())
            self.assertEqual(runner.call_count, 3)  # initial attempt + two retries


if __name__ == "__main__":
    unittest.main()
