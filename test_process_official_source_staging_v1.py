#!/usr/bin/env python3

from pathlib import Path

import detect_source_changes_v1 as detector
import process_official_source_staging_v1 as pipeline


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "source_registry_v1.yaml"


def route(name):
    return {
        "decision": {
            "production_decision_valid": True,
            "recommended_pipeline": name,
        }
    }


registry = detector.load_registry(
    REGISTRY
)

sources = registry["sources"]

assert (
    pipeline.choose_pipeline(
        route("legacy-v1"),
        sources["BD_PNAP_APP145"],
    )
    == "legacy-v1"
)

assert (
    pipeline.choose_pipeline(
        route("legacy-v1"),
        sources["BD_PNAP_APP149"],
    )
    == "legacy-v1"
)

assert (
    pipeline.choose_pipeline(
        route("multimodal-v2"),
        sources["BD_PNAP_APP146"],
    )
    == "multimodal-v2"
)

validation_145 = (
    pipeline.validation_config(
        sources["BD_PNAP_APP145"]
    )
)

assert validation_145["expect_terms"] == [
    "fire",
    "safety",
]

validation_149 = (
    pipeline.validation_config(
        sources["BD_PNAP_APP149"]
    )
)

assert validation_149["expect_terms"] == [
    "authorized",
    "signatory",
    "minor",
    "works",
]

validation_146 = (
    pipeline.validation_config(
        sources["BD_PNAP_APP146"]
    )
)

assert validation_146["expect_terms"] == [
    "hinge",
    "stopper",
]

writer_command = (
    pipeline.build_writer_command(
        python="python",
        repo_root=ROOT,
        source_id="BD_PNAP_APP149",
        state_root=Path("/tmp/state"),
    )
)

assert writer_command[-1] == "--execute"
assert "--source" in writer_command
assert "BD_PNAP_APP149" in writer_command

promotion_command = (
    pipeline.build_promotion_command(
        python="python",
        repo_root=ROOT,
        source_id="BD_PNAP_APP149",
        state_root=Path("/tmp/state"),
    )
)

assert promotion_command[-1] == "--execute"

text_command = (
    pipeline.build_text_write_command(
        python="python",
        repo_root=ROOT,
        source_id="BD_PNAP_APP149",
        state_root=Path("/tmp/state"),
        workdir=Path("/tmp/work"),
    )
)

assert "--write" in text_command
assert "--confirm-staging-write" in text_command

validate_command = (
    pipeline.build_text_validation_command(
        python="python",
        repo_root=ROOT,
        source_id="BD_PNAP_APP149",
        state_root=Path("/tmp/state"),
        source=sources["BD_PNAP_APP149"],
    )
)

assert "--query" in validate_command
assert validate_command.count(
    "--expect-term"
) == 4

multimodal_command = (
    pipeline.build_multimodal_write_command(
        python="python",
        repo_root=ROOT,
        source=sources["BD_PNAP_APP146"],
        source_file=Path("/tmp/APP146.pdf"),
        workdir=Path("/tmp/mm-work"),
        defaults=registry.get("defaults") or {},
    )
)

assert "run_multimodal_canary_v2.py" in (
    " ".join(multimodal_command)
)
assert "--write" in multimodal_command
assert "--confirm-staging-write" in multimodal_command
assert "jason-os-knowledge-db-staging" not in (
    multimodal_command
)

multimodal_validate_command = (
    pipeline.build_multimodal_validation_command(
        python="python",
        repo_root=ROOT,
        source=sources["BD_PNAP_APP146"],
        checksum="a" * 64,
    )
)

assert "validate_staging_retrieval_v2.py" in (
    " ".join(multimodal_validate_command)
)
assert "--checksum" in multimodal_validate_command
assert multimodal_validate_command.count(
    "--expect-term"
) == 2
assert "hinge" in multimodal_validate_command
assert "stopper" in multimodal_validate_command

source_text = (
    ROOT
    / "process_official_source_staging_v1.py"
).read_text(
    encoding="utf-8"
)

for forbidden in (
    "PRODUCTION_DB_CONTAINER",
    "production_release_registry",
    "write_canonical_text_production",
    "--confirm-production-write",
):
    assert forbidden not in source_text

assert (
    "MULTIMODAL_STAGING_HANDOFF_REQUIRED"
    not in source_text
)

assert (
    "build_multimodal_write_command"
    in source_text
)

assert (
    "build_multimodal_validation_command"
    in source_text
)

assert (
    "READY_FOR_PRODUCTION_REVIEW"
    in source_text
)

assert (
    "SOURCE_CHANGED_REVIEW_REQUIRED"
    in source_text
)

print(
    "Official Source Processing Pipeline v1 contract test PASS"
)
print(
    "Staging-only orchestration: PASS"
)
print(
    "Legacy-v1 reusable text path: PASS"
)
print(
    "Multimodal Staging close-loop: PASS"
)
print(
    "Production write path: ABSENT"
)