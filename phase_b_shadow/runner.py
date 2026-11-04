"""One bounded shadow conversion, with atomic artifacts and duplicate hold."""

import json
import os
from importlib.metadata import version
from pathlib import Path

from build_multimodal_chunks_v2 import build_output
from extract_document_v2 import sha256_file
from phase_b_shadow import CONFIG_VERSION
from phase_b_shadow.contract import ContractGap, load_fixture, task_id
from phase_b_shadow.docling_adapter import build_manifest, convert_pdf
from phase_b_shadow.model_inventory import verify_model_bundle
from route_document_v2 import assess_manifest


def _atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run_fixture(fixture_id: str, expected_sha256: str, input_dir: Path,
                output_dir: Path, model_dir: Path, converter=convert_pdf,
                parser_version: str | None = None) -> dict:
    if os.environ.get("JASON_OS_ENV") != "staging":
        raise ContractGap("shadow runner requires explicit staging identity")
    if (input_dir.is_symlink() or output_dir.is_symlink()
            or not input_dir.is_dir() or not output_dir.is_dir()
            or input_dir.resolve() == output_dir.resolve()):
        raise ContractGap("isolated non-symlink input and output directories are required")
    fixture, source = load_fixture(input_dir / "catalog.json", fixture_id, input_dir)
    if expected_sha256 != fixture.sha256:
        raise ContractGap("task SHA256 differs from the allowlisted fixture")
    key = task_id(fixture)
    artifact = output_dir / f"{key}.manifest.json"
    candidate = output_dir / f".{key}.candidate.json"
    receipt = output_dir / f"{key}.result.json"
    lock = output_dir / f"{key}.lock"
    candidate_temp = candidate.with_suffix(candidate.suffix + ".tmp")
    if lock.exists():
        raise ContractGap("task already active or crashed; manual reconciliation required")
    if candidate.exists() or candidate_temp.exists():
        raise ContractGap("unreconciled candidate manifest; manual reconciliation required")
    if receipt.exists():
        if receipt.is_symlink():
            raise ContractGap("existing receipt is redirected")
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        if previous.get("task_id") != key or previous.get("source_sha256") != fixture.sha256:
            raise ContractGap("existing receipt identity mismatch")
        status = previous.get("status")
        if status not in ("READY_SHADOW", "AUTO_HOLD_CONTRACT_GAP", "AUTO_HOLD_RUNTIME_ERROR"):
            raise ContractGap("existing receipt has unknown status")
        if status == "READY_SHADOW":
            verify_model_bundle(model_dir, fixture.model_bundle_sha256)
            if (artifact.is_symlink() or not artifact.is_file()
                    or sha256_file(artifact) != previous.get("manifest_sha256")):
                raise ContractGap("existing manifest is missing or changed")
        elif artifact.exists() or artifact.is_symlink():
            raise ContractGap("HOLD receipt coexists with a published manifest")
        return {**previous, "duplicate": True}
    if artifact.exists() or artifact.is_symlink():
        raise ContractGap("orphan published manifest without receipt; manual reconciliation required")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ContractGap("task already active or crashed; manual reconciliation required") from exc
    manifest_published = False
    ready_receipt_committed = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(key + "\n")
        model_version_file = model_dir / "model-version.txt"
        if (model_version_file.is_symlink() or not model_version_file.is_file()
                or not 0 < model_version_file.stat().st_size <= 256
                or model_version_file.read_text(encoding="utf-8").strip() != fixture.model_version):
            raise ContractGap("reviewed model version does not match the mounted model directory")
        model_inventory = verify_model_bundle(model_dir, fixture.model_bundle_sha256)
        document = converter(source, model_dir)
        if sha256_file(source) != fixture.sha256:
            raise ContractGap("source changed during parsing")
        manifest = build_manifest(
            document, fixture, source, parser_version or version("docling"),
            fixture.model_version, model_inventory["model_bundle_sha256"]
        )
        route = assess_manifest(manifest, allow_partial=False)
        if route["source"]["sha256"] != fixture.sha256:
            raise ContractGap("router source SHA256 mismatch")
        # The chunk contract must pass before a manifest is published at
        # its final, discoverable path. A failed build only leaves a HOLD receipt.
        _atomic_json(candidate, manifest)
        chunks = build_output(candidate, manifest, target_chars=1800, overlap_chars=250)
        if chunks["source_manifest"]["document_sha256"] != fixture.sha256:
            raise ContractGap("chunk builder source SHA256 mismatch")
        if not chunks["chunks"]:
            raise ContractGap("chunk builder produced no grounded chunks")
        os.replace(candidate, artifact)
        manifest_published = True
        result = {"task_id": key, "fixture_id": fixture_id, "source_sha256": fixture.sha256,
                  "status": "READY_SHADOW", "manifest": artifact.name,
                  "manifest_sha256": sha256_file(artifact), "model_version": fixture.model_version,
                  "model_bundle_sha256": model_inventory["model_bundle_sha256"],
                  "config_version": CONFIG_VERSION,
                  "route": route["decision"]["recommended_pipeline"],
                  "chunk_count": len(chunks["chunks"]), "duplicate": False,
                  "database_write_performed": False}
        _atomic_json(receipt, result)
        ready_receipt_committed = True
        return result
    except ContractGap as exc:
        result = {"task_id": key, "fixture_id": fixture_id, "source_sha256": fixture.sha256,
                  "status": "AUTO_HOLD_CONTRACT_GAP", "reason": str(exc), "duplicate": False,
                  "database_write_performed": False}
        _atomic_json(receipt, result)
        return result
    except OSError:
        raise
    except Exception as exc:
        result = {"task_id": key, "fixture_id": fixture_id, "source_sha256": fixture.sha256,
                  "status": "AUTO_HOLD_RUNTIME_ERROR", "reason": type(exc).__name__,
                  "duplicate": False, "database_write_performed": False}
        _atomic_json(receipt, result)
        return result
    finally:
        # Python exceptions (including chunk/route failures) cannot leave an
        # unpublished candidate behind. On SIGKILL the lock remains to HOLD
        # the next run for manual reconciliation, as documented.
        candidate.unlink(missing_ok=True)
        candidate_temp.unlink(missing_ok=True)
        # Keep the lock for manual reconciliation if a manifest was already
        # published but its READY receipt could not be committed. Pre-publication
        # transient I/O errors remain eligible for bounded Celery retries.
        if not manifest_published or ready_receipt_committed:
            lock.unlink(missing_ok=True)
