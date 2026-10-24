from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent / "ops" / "audit_vps_storage_v1.sh"


def main() -> int:
    raw = SCRIPT_PATH.read_text(encoding="utf-8")
    lower = raw.lower()

    required = (
        "jason os vps storage audit v1",
        "read-only",
        "df -hp",
        "docker system df",
        "docker ps -a",
        "docker volume ls",
        "journalctl --disk-usage",
        "audit complete - no cleanup or write action was performed",
    )
    for token in required:
        assert token in lower, f"required audit behavior missing: {token}"

    forbidden = (
        "docker system prune",
        "docker image prune",
        "docker volume prune",
        "docker container prune",
        "rm -rf",
        "truncate ",
        "journalctl --vacuum",
        "apt clean",
        "apt-get clean",
        "find / -delete",
        "psql ",
    )
    for token in forbidden:
        assert token not in lower, f"destructive or mutating command found: {token}"

    assert "healthy" in lower
    assert "observe" in lower
    assert "warning" in lower
    assert "cleanup required" in lower
    assert "critical" in lower

    print("VPS storage audit contract: PASS")
    print("Mutation commands: none")
    print("Storage policy thresholds: present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
