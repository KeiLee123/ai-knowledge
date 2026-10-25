import hashlib
import json
import tempfile
from pathlib import Path

import yaml

from run_source_monitor_batch_v1 import (
    execute_sources,
    overall_status,
)
from validate_source_monitor_schedule_v1 import (
    validate_schedule,
)


ROOT = Path(__file__).resolve().parent
SCHEDULE = ROOT / "source_monitor_schedule_v1.yaml"
REGISTRY = ROOT / "source_registry_v1.yaml"
RUNNER = ROOT / "ops" / "run_source_monitor_staging_v2.sh"
SERVICE = (
    ROOT
    / "ops"
    / "systemd"
    / "jason-os-source-monitor-staging-batch.service"
)
TIMER = (
    ROOT
    / "ops"
    / "systemd"
    / "jason-os-source-monitor-staging-batch.timer"
)

M8_RUNNER = ROOT / "ops" / "run_source_monitor_staging_v1.sh"
M8_SERVICE = (
    ROOT
    / "ops"
    / "systemd"
    / "jason-os-source-monitor-staging.service"
)
M8_TIMER = (
    ROOT
    / "ops"
    / "systemd"
    / "jason-os-source-monitor-staging.timer"
)


def write_reference(
    root: Path,
    source_id: str,
) -> None:
    path = (
        root
        / "version-snapshots"
        / "current"
        / f"{source_id}.json"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            {
                "version_snapshot_store_version": 1,
                "source_id": source_id,
                "snapshot": {
                    "document_sha256":
                        "a" * 64,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_schedule_contract() -> None:
    payload = yaml.safe_load(
        SCHEDULE.read_text(
            encoding="utf-8"
        )
    )

    assert (
        payload[
            "source_monitor_schedule_version"
        ]
        == 1
    )
    assert (
        payload["environment"]
        == "staging"
    )
    assert (
        payload["defaults"]
        == {
            "cadence": "daily",
            "timezone": "Asia/Hong_Kong",
            "time": "09:15",
        }
    )

    configured = [
        entry["source_id"]
        for entry in payload[
            "sources"
        ]
        if entry.get(
            "enabled"
        )
        is True
    ]

    assert configured == [
        "BD_PNAP_APP149",
        "BD_PNAP_APP145",
    ]

    # APP146 is enabled in the Source Registry but
    # is intentionally not auto-discovered into M9.
    assert (
        "BD_PNAP_APP146"
        not in configured
    )


def test_schedule_readiness() -> None:
    with tempfile.TemporaryDirectory() as d:
        state_root = Path(
            d
        ).resolve()

        write_reference(
            state_root,
            "BD_PNAP_APP149",
        )
        write_reference(
            state_root,
            "BD_PNAP_APP145",
        )

        result = validate_schedule(
            schedule_path=SCHEDULE,
            registry_path=REGISTRY,
            state_root=state_root,
            require_references=True,
        )

        assert (
            result["source_ids"]
            == [
                "BD_PNAP_APP149",
                "BD_PNAP_APP145",
            ]
        )
        assert (
            result[
                "production_access"
            ]
            is False
        )
        assert (
            result[
                "production_write"
            ]
            is False
        )

        (
            state_root
            / "version-snapshots"
            / "current"
            / "BD_PNAP_APP145.json"
        ).unlink()

        try:
            validate_schedule(
                schedule_path=SCHEDULE,
                registry_path=REGISTRY,
                state_root=state_root,
                require_references=True,
            )
        except FileNotFoundError:
            pass
        else:
            raise AssertionError(
                "Missing source reference did not fail closed"
            )


def test_failure_isolation() -> None:
    calls = []

    def fake_run(
        source_id: str,
    ) -> dict:
        calls.append(
            source_id
        )

        if (
            source_id
            == "BD_PNAP_APP149"
        ):
            raise RuntimeError(
                "simulated source failure"
            )

        return {
            "source_id": source_id,
            "execution_status":
                "EXECUTION_SUCCESS",
            "return_code": 0,
            "decision": "NO_CHANGE",
            "action": "NONE",
            "production_access": False,
            "production_write": False,
        }

    results = execute_sources(
        [
            "BD_PNAP_APP149",
            "BD_PNAP_APP145",
        ],
        fake_run,
    )

    assert calls == [
        "BD_PNAP_APP149",
        "BD_PNAP_APP145",
    ]

    assert (
        results[0][
            "execution_status"
        ]
        == "EXECUTION_FAILED"
    )
    assert (
        results[1][
            "execution_status"
        ]
        == "EXECUTION_SUCCESS"
    )
    assert (
        overall_status(
            results
        )
        == "PARTIAL_FAILURE"
    )


def test_runner_contract() -> None:
    text = RUNNER.read_text(
        encoding="utf-8"
    )
    lower = text.lower()

    assert (
        "set -euo pipefail"
        in text
    )
    assert (
        "/opt/ai-knowledge-staging"
        in text
    )
    assert (
        "/var/lib/jason-os/source-monitor-staging"
        in text
    )
    assert (
        "JASON_SOURCE_MONITOR_SOURCE_ID"
        in text
    )
    assert (
        "BD_PNAP_APP149"
        not in text
    )
    assert (
        "source-monitor-staging-$SOURCE_ID.lock"
        in text
    )
    assert (
        "flock -n 9"
        in text
    )
    assert (
        'branch --show-current'
        in text
    )
    assert (
        '!= "staging"'
        in text
    )
    assert (
        "status --porcelain"
        in text
    )
    assert (
        "monitor_official_source_v1.py"
        in text
    )
    assert (
        "production_access=false"
        in text
    )
    assert (
        "production_write=false"
        in text
    )
    assert (
        "source-monitor-production"
        not in lower
    )
    assert (
        "systemctl "
        not in lower
    )


def test_systemd_contract() -> None:
    service = SERVICE.read_text(
        encoding="utf-8"
    )
    timer = TIMER.read_text(
        encoding="utf-8"
    )
    combined = (
        service
        + "\n"
        + timer
    ).lower()

    assert (
        "Type=oneshot"
        in service
    )
    assert (
        "WorkingDirectory=/opt/ai-knowledge-staging"
        in service
    )
    assert (
        "run_source_monitor_batch_v1.py"
        in service
    )
    assert (
        "source_monitor_schedule_v1.yaml"
        in service
    )
    assert (
        "/var/lib/jason-os/source-monitor-staging"
        in service
    )

    assert (
        "OnCalendar=*-*-* 09:15:00 Asia/Hong_Kong"
        in timer
    )
    assert (
        "Persistent=true"
        in timer
    )
    assert (
        "Unit=jason-os-source-monitor-staging-batch.service"
        in timer
    )

    for token in (
        "systemctl enable",
        "systemctl start",
        "enable --now",
        "systemctl restart",
        "source-monitor-production",
        "ai-knowledge-db-",
    ):
        assert (
            token
            not in combined
        ), token


def test_m8_remains_frozen() -> None:
    # Regression boundary: M9B is additive and keeps the
    # original M8 APP149-only scheduler contract intact.
    runner = M8_RUNNER.read_text(
        encoding="utf-8"
    )
    service = M8_SERVICE.read_text(
        encoding="utf-8"
    )
    timer = M8_TIMER.read_text(
        encoding="utf-8"
    )

    assert (
        "BD_PNAP_APP149"
        in runner
    )
    assert (
        "M8 MVP scheduler is locked"
        in runner
    )
    assert (
        "JASON_SOURCE_MONITOR_SOURCE_ID=BD_PNAP_APP149"
        in service
    )
    assert (
        "Unit=jason-os-source-monitor-staging.service"
        in timer
    )

    # Print stable content fingerprints for live proof comparison.
    for label, content in (
        ("m8_runner", runner),
        ("m8_service", service),
        ("m8_timer", timer),
    ):
        digest = hashlib.sha256(
            content.encode(
                "utf-8"
            )
        ).hexdigest()
        assert len(
            digest
        ) == 64
        print(
            f"{label}_sha256={digest}"
        )


def main() -> int:
    test_schedule_contract()
    test_schedule_readiness()
    test_failure_isolation()
    test_runner_contract()
    test_systemd_contract()
    test_m8_remains_frozen()

    print(
        "M9B multi-source orchestration contract: PASS"
    )
    print(
        "Explicit source allowlist: PASS"
    )
    print(
        "Auto-discovery: ABSENT"
    )
    print(
        "Reference readiness gate: PASS"
    )
    print(
        "Sequential failure isolation: PASS"
    )
    print(
        "Per-source lock contract: PASS"
    )
    print(
        "M8 frozen scheduler: PRESERVED"
    )
    print(
        "Automatic M9 timer activation: ABSENT"
    )
    print(
        "Production DB coupling: ABSENT"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
