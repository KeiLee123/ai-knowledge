from pathlib import Path


ROOT = Path(__file__).resolve().parent

INSTALLER = (
    ROOT
    / "ops"
    / "install_source_monitor_staging_batch_v1.sh"
)

CUTOVER = (
    ROOT
    / "ops"
    / "cutover_source_monitor_staging_v1.sh"
)

M8_RUNNER = (
    ROOT
    / "ops"
    / "run_source_monitor_staging_v1.sh"
)

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

M9_SERVICE = (
    ROOT
    / "ops"
    / "systemd"
    / "jason-os-source-monitor-staging-batch.service"
)

M9_TIMER = (
    ROOT
    / "ops"
    / "systemd"
    / "jason-os-source-monitor-staging-batch.timer"
)


def test_installer_contract() -> None:
    text = INSTALLER.read_text(
        encoding="utf-8"
    )
    lower = text.lower()

    assert "set -euo pipefail" in text
    assert "/opt/ai-knowledge-staging" in text
    assert "/etc/systemd/system" in text

    assert (
        "jason-os-source-monitor-staging-batch.service"
        in text
    )
    assert (
        "jason-os-source-monitor-staging-batch.timer"
        in text
    )

    assert (
        "systemctl daemon-reload"
        in text
    )

    assert (
        "systemctl is-enabled --quiet"
        in text
    )
    assert (
        "systemctl is-active --quiet"
        in text
    )

    # Installer may place unit files only.
    # It must never activate either scheduler.
    forbidden = (
        "systemctl enable ",
        "systemctl enable --now",
        "systemctl start ",
        "systemctl restart ",
        "systemctl disable ",
        "systemctl disable --now",
    )

    for token in forbidden:
        assert token not in lower, token

    assert (
        "m9_timer_enabled=false"
        in text
    )
    assert (
        "m9_timer_active=false"
        in text
    )

    assert (
        "source-monitor-production"
        not in lower
    )


def test_cutover_contract() -> None:
    text = CUTOVER.read_text(
        encoding="utf-8"
    )
    lower = text.lower()

    assert "set -euo pipefail" in text

    assert (
        "--confirm-cutover"
        in text
    )
    assert (
        "--confirm-rollback"
        in text
    )

    assert (
        'M8_TIMER="jason-os-source-monitor-staging.timer"'
        in text
    )
    assert (
        'M9_TIMER="jason-os-source-monitor-staging-batch.timer"'
        in text
    )

    cutover_start = text.index(
        "cutover()"
    )
    rollback_start = text.index(
        "rollback()"
    )

    cutover_body = text[
        cutover_start:rollback_start
    ]

    old_disable = (
        cutover_body.index(
            'systemctl disable --now "$M8_TIMER"'
        )
    )
    new_enable = (
        cutover_body.index(
            'systemctl enable --now "$M9_TIMER"'
        )
    )

    assert (
        old_disable
        < new_enable
    )

    assert (
        'require_disabled_inactive "$M8_TIMER"'
        in cutover_body
    )
    assert (
        'require_enabled_active "$M9_TIMER"'
        in cutover_body
    )

    # Failed M9 activation restores M8.
    assert (
        "CUTOVER FAILED: restoring M8"
        in cutover_body
    )
    assert (
        'systemctl enable --now "$M8_TIMER"'
        in cutover_body
    )

    rollback_body = text[
        rollback_start:
    ]

    new_disable = (
        rollback_body.index(
            'systemctl disable --now "$M9_TIMER"'
        )
    )
    old_enable = (
        rollback_body.index(
            'systemctl enable --now "$M8_TIMER"'
        )
    )

    assert (
        new_disable
        < old_enable
    )

    assert (
        "monitor_official_source_v1.py"
        not in text
    )
    assert (
        "run_source_monitor_batch_v1.py"
        not in text
    )

    assert (
        "version_snapshot_store_v1.py"
        not in text
    )

    assert (
        "source-monitor-production"
        not in lower
    )


def test_units_remain_staging_only() -> None:
    service = M9_SERVICE.read_text(
        encoding="utf-8"
    )
    timer = M9_TIMER.read_text(
        encoding="utf-8"
    )

    combined = (
        service
        + "\n"
        + timer
    ).lower()

    assert (
        "/opt/ai-knowledge-staging"
        in service
    )
    assert (
        "/var/lib/jason-os/source-monitor-staging"
        in service
    )
    assert (
        "run_source_monitor_batch_v1.py"
        in service
    )

    assert (
        "OnCalendar=*-*-* 09:15:00 Asia/Hong_Kong"
        in timer
    )

    assert (
        "source-monitor-production"
        not in combined
    )
    assert (
        "ai-knowledge-db-"
        not in combined
    )


def test_frozen_m8_files_unchanged_contract() -> None:
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


def main() -> int:
    test_installer_contract()
    test_cutover_contract()
    test_units_remain_staging_only()
    test_frozen_m8_files_unchanged_contract()

    print(
        "M9D scheduler cutover contract: PASS"
    )
    print(
        "Install without activation: PASS"
    )
    print(
        "Explicit cutover confirmation: PASS"
    )
    print(
        "M8 disabled before M9 enable: PASS"
    )
    print(
        "Failed cutover restores M8: PASS"
    )
    print(
        "Explicit rollback path: PASS"
    )
    print(
        "M9 disabled before M8 rollback enable: PASS"
    )
    print(
        "Direct batch execution from cutover: ABSENT"
    )
    print(
        "Reference mutation from cutover: ABSENT"
    )
    print(
        "Production coupling: ABSENT"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
