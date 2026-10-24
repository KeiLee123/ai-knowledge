from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / "ops" / "run_source_monitor_staging_v1.sh"
SERVICE = ROOT / "ops" / "systemd" / "jason-os-source-monitor-staging.service"
TIMER = ROOT / "ops" / "systemd" / "jason-os-source-monitor-staging.timer"


def main() -> int:
    runner = RUNNER.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    runner_lower = runner.lower()
    service_lower = service.lower()
    timer_lower = timer.lower()

    assert "set -euo pipefail" in runner
    assert "/opt/ai-knowledge-staging" in runner
    assert "/var/lib/jason-os/source-monitor-staging" in runner
    assert "BD_PNAP_APP149" in runner
    assert "flock -n 9" in runner
    assert 'branch --show-current' in runner
    assert '!= "staging"' in runner
    assert "status --porcelain" in runner
    assert "worktree must be clean" in runner
    assert "repo_commit=$REPO_COMMIT" in runner
    assert "monitor_official_source_v1.py" in runner
    assert "--source" in runner
    assert "--state-root" in runner
    assert "--workdir" in runner
    assert "monitor-output.txt" in runner
    assert "production_access=false" in runner
    assert "production_write=false" in runner
    assert "source-monitor-production" not in runner_lower
    assert "systemctl " not in runner_lower

    assert "Type=oneshot" in service
    assert "WorkingDirectory=/opt/ai-knowledge-staging" in service
    assert "JASON_SOURCE_MONITOR_SOURCE_ID=BD_PNAP_APP149" in service
    assert (
        "JASON_SOURCE_MONITOR_STATE_ROOT=/var/lib/jason-os/source-monitor-staging"
        in service
    )
    assert (
        "ExecStart=/bin/bash "
        "/opt/ai-knowledge-staging/ops/run_source_monitor_staging_v1.sh"
        in service
    )
    assert "source-monitor-production" not in service_lower

    assert "OnCalendar=*-*-* 09:15:00 Asia/Hong_Kong" in timer
    assert "Persistent=true" in timer
    assert "Unit=jason-os-source-monitor-staging.service" in timer
    assert "WantedBy=timers.target" in timer

    combined = "\n".join((runner_lower, service_lower, timer_lower))
    forbidden_activation = (
        "systemctl enable",
        "systemctl start",
        "enable --now",
        "systemctl restart",
    )
    for token in forbidden_activation:
        assert token not in combined, f"automatic activation is forbidden: {token}"

    forbidden_surfaces = (
        "ai-knowledge-db-",
        "production db",
        "source-monitor-production",
    )
    for token in forbidden_surfaces:
        assert token not in combined, f"Production coupling found: {token}"

    print("M8 Source Monitor scheduler contract: PASS")
    print("Environment: staging-only")
    print("Canary source: BD_PNAP_APP149")
    print("Schedule definition: daily 09:15 Asia/Hong_Kong")
    print("Overlap protection: flock")
    print("Checkout guard: staging branch + clean worktree")
    print("Run artifacts: retained under staging state root")
    print("Automatic timer activation: ABSENT")
    print("Production DB coupling: ABSENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
