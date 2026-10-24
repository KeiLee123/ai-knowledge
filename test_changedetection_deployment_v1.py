from pathlib import Path
import yaml

COMPOSE_PATH = Path(__file__).resolve().parent / "ops" / "changedetection" / "docker-compose.staging.yml"
EXPECTED_IMAGE = (
    "dgtlmoon/changedetection.io@"
    "sha256:04eaae7915bad711160cb15abe160f6d3fabe98bbbd658509d4b7a654000fb2d"
)


def main() -> int:
    raw = COMPOSE_PATH.read_text(encoding="utf-8")
    cfg = yaml.safe_load(raw)

    services = cfg.get("services") or {}
    service = services.get("changedetection")
    assert isinstance(service, dict), "changedetection service is missing"

    assert service.get("image") == EXPECTED_IMAGE, "image must be official and digest-pinned"
    assert service.get("container_name") == "jason-os-changedetection-staging"
    assert service.get("restart") == "unless-stopped"

    ports = [str(x) for x in service.get("ports", [])]
    assert ports == ["127.0.0.1:5001:5000"], "UI must be loopback-only on staging"

    assert service.get("privileged") not in (True, "true", "True"), "privileged mode is forbidden"
    assert service.get("network_mode") != "host", "host networking is forbidden"

    volumes = [str(x) for x in service.get("volumes", [])]
    assert any(v.endswith(":/datastore") for v in volumes), "persistent datastore is required"
    assert all("/var/run/docker.sock" not in v for v in volumes), "Docker socket mount is forbidden"

    labels = service.get("labels") or {}
    assert labels.get("com.jasonos.environment") == "staging"
    assert labels.get("com.jasonos.purpose") == "source-change-detect"

    declared_volumes = cfg.get("volumes") or {}
    volume = declared_volumes.get("changedetection_staging_data") or {}
    assert volume.get("name") == "jason-os-changedetection-staging-data"

    declared_networks = cfg.get("networks") or {}
    network = declared_networks.get("changedetection_staging_net") or {}
    assert network.get("name") == "jason-os-changedetection-staging-net"
    assert network.get("driver") == "bridge"

    lower = raw.lower()
    forbidden = (
        "ai-knowledge-db",
        "postgres_password",
        "google_application_credentials",
        "gdrive:",
        "rclone",
        "/var/run/docker.sock",
    )
    for token in forbidden:
        assert token not in lower, f"forbidden coupling or credential surface found: {token}"

    print("Changedetection staging deployment contract: PASS")
    print("Official image: digest-pinned")
    print("UI exposure: 127.0.0.1:5001 only")
    print("Knowledge DB coupling: none")
    print("Google Drive credentials: none")
    print("Detector scope: shared multi-source platform")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
