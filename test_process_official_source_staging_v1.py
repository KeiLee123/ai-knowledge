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
    "Multimodal handoff boundary: PASS"
)
print(
    "Production write path: ABSENT"
)
