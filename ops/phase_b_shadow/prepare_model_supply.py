"""Bounded off-VPS model acquisition evidence; downloads NO documents or application data.

This tool must run only on a separately authorized ephemeral preparation runner.
It prints public model SHA256 metadata; never uploads or publishes model weights.
"""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

from phase_b_shadow.model_inventory import inventory_model_bundle

# Immutable upstream revisions inspected against docling-project/docling@v2.146.0.
# TableFormer is intentionally pinned to the commit behind the source's v2.3.0 tag.
SOURCES = (
    ("docling-project/docling-layout-heron", "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"),
    ("docling-project/docling-layout-heron-onnx", "40bde044036bb181c130ddf6c51792187268748f"),
    ("docling-project/docling-models", "fc0f2d45e2218ea24bce5045f58a389aed16dc23"),
)
CANDIDATE_ID = "docling_21460_heron_tableformer_candidate"
MAX_SOURCE_BYTES = 2 * 1024**3


def main() -> None:
    runner_temp = os.environ.get("RUNNER_TEMP")
    if not runner_temp:
        raise RuntimeError("RUNNER_TEMP required; this is not a VPS utility")
    temp = Path(runner_temp)
    model_dir = temp / "phase-b-model-supply" / "models"
    report_dir = temp / "phase-b-model-supply" / "report"
    model_dir.mkdir(parents=True, exist_ok=False)
    report_dir.mkdir(parents=True, exist_ok=True)

    api = HfApi(token=False)
    sources = []
    for repo_id, revision in SOURCES:
        metadata = api.model_info(repo_id=repo_id, revision=revision, files_metadata=True)
        if metadata.sha != revision:
            raise RuntimeError(f"unexpected resolved revision for {repo_id}")
        siblings = metadata.siblings or []
        declared_size = sum((s.size or 0) for s in siblings)
        if declared_size > MAX_SOURCE_BYTES:
            raise RuntimeError(f"source exceeds 2GiB preflight bound: {repo_id}")
        destination = model_dir / repo_id.replace("/", "--")
        print(f"Fetching immutable {repo_id}@{revision}, advertised bytes={declared_size}", flush=True)
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=str(destination),
            token=False,
            max_workers=2,
        )
        # huggingface_hub may create metadata under local_dir; do not hash or
        # distribute it as part of the model bundle.
        cache_metadata = destination / ".cache" / "huggingface"
        if cache_metadata.is_dir() and not cache_metadata.is_symlink():
            shutil.rmtree(cache_metadata)
        cache_parent = destination / ".cache"
        if cache_parent.is_dir() and not any(cache_parent.iterdir()):
            cache_parent.rmdir()
        card = getattr(metadata, "card_data", None)
        license_value = getattr(card, "license", None)
        if not isinstance(license_value, (str, list)):
            license_value = str(license_value) if license_value else None
        sources.append({
            "repo_id": repo_id,
            "resolved_commit_sha": metadata.sha,
            "license_metadata": license_value,
            "advertised_bytes": declared_size,
            "relative_model_folder": destination.relative_to(model_dir).as_posix(),
        })

    (model_dir / "model-version.txt").write_text(CANDIDATE_ID + "\n", encoding="utf-8")
    inventory = inventory_model_bundle(model_dir)
    report = {
        "status": "CANDIDATE_BYTES_HASHED_NOT_APPROVED_FOR_DEPLOYMENT",
        "purpose": "Code-only off-VPS model byte integrity evidence",
        "docling_app_version_target": "2.146.0",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revisions": sources,
        "inventory": inventory,
        "model_files_uploaded_to_github": False,
        "cpu_image_built": False,
        "staging_runtime_performed": False,
        "redistribution_review_complete": False,
        "private_model_delivery_completed": False,
    }
    output = report_dir / "model-inventory.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("MODEL_INVENTORY_SUMMARY=" + json.dumps({
        "model_bundle_sha256": inventory["model_bundle_sha256"],
        "file_count": inventory["file_count"],
        "total_bytes": inventory["total_bytes"],
        "sources": [{"repo_id": r["repo_id"], "sha": r["resolved_commit_sha"]} for r in sources],
        "status": report["status"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
