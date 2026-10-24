#!/usr/bin/env python3

import argparse
import hashlib
import json
import urllib.parse
import urllib.request

from datetime import datetime, timezone
from pathlib import Path

import yaml


DEFAULT_REGISTRY = (
    Path(__file__).resolve().with_name(
        "source_registry_v1.yaml"
    )
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_registry(path):
    with Path(path).open(
        "r",
        encoding="utf-8"
    ) as f:
        registry = yaml.safe_load(f)

    if not isinstance(registry, dict):
        raise ValueError(
            "Registry root must be a mapping."
        )

    if registry.get(
        "source_registry_version"
    ) != 1:
        raise ValueError(
            "Unsupported source_registry_version."
        )

    sources = registry.get("sources")

    if not isinstance(sources, dict):
        raise ValueError(
            "Registry sources must be a mapping."
        )

    return registry


def validate_url(url, allowed_hosts):
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme != "https":
        raise ValueError(
            f"Only HTTPS sources are allowed: {url}"
        )

    if not parsed.hostname:
        raise ValueError(
            f"Source URL has no hostname: {url}"
        )

    if parsed.hostname not in allowed_hosts:
        raise ValueError(
            "Source host is not allowed: "
            f"{parsed.hostname}"
        )


def validate_source(source_id, config):
    required = (
        "authority_code",
        "publisher",
        "source_family",
        "source_type",
        "document_code",
        "index_url",
        "canonical_url",
        "allowed_hosts",
        "expected_content_types",
    )

    missing = [
        key
        for key in required
        if key not in config
    ]

    if missing:
        raise ValueError(
            f"{source_id}: missing fields: "
            + ", ".join(missing)
        )

    allowed_hosts = config[
        "allowed_hosts"
    ]

    if not (
        isinstance(allowed_hosts, list)
        and allowed_hosts
        and all(
            isinstance(host, str)
            and host.strip()
            for host in allowed_hosts
        )
    ):
        raise ValueError(
            f"{source_id}: allowed_hosts "
            "must be a non-empty list."
        )

    validate_url(
        config["index_url"],
        allowed_hosts
    )

    validate_url(
        config["canonical_url"],
        allowed_hosts
    )

    expected = config[
        "expected_content_types"
    ]

    if not isinstance(expected, dict):
        raise ValueError(
            f"{source_id}: "
            "expected_content_types "
            "must be a mapping."
        )

    for key in (
        "index",
        "document",
    ):
        if not expected.get(key):
            raise ValueError(
                f"{source_id}: expected "
                f"content type missing for {key}."
            )


def fetch_resource(
    url,
    *,
    timeout_seconds,
    user_agent,
    allowed_hosts
):
    validate_url(
        url,
        allowed_hosts
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "*/*",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout_seconds
    ) as response:
        body = response.read()

        final_url = response.geturl()

        validate_url(
            final_url,
            allowed_hosts
        )

        headers = response.headers

        if hasattr(
            headers,
            "get_content_type"
        ):
            content_type = (
                headers.get_content_type()
            )
        else:
            content_type = (
                headers.get(
                    "Content-Type",
                    ""
                )
                .split(";", 1)[0]
                .strip()
                .lower()
            )

        return {
            "url": final_url,
            "status": getattr(
                response,
                "status",
                None
            ),
            "content_type": content_type,
            "content_length": len(body),
            "sha256": sha256_bytes(body),
            "etag": headers.get("ETag"),
            "last_modified": headers.get(
                "Last-Modified"
            ),
        }


def assert_content_type(
    source_id,
    label,
    observation,
    expected
):
    actual = observation.get(
        "content_type"
    )

    if actual != expected:
        raise RuntimeError(
            f"{source_id}: unexpected "
            f"{label} content type: "
            f"{actual!r}; expected "
            f"{expected!r}"
        )


def probe_source(
    source_id,
    config,
    defaults
):
    validate_source(
        source_id,
        config
    )

    timeout_seconds = int(
        defaults.get(
            "timeout_seconds",
            60
        )
    )

    user_agent = str(
        defaults.get(
            "user_agent",
            "Jason-OS-Source-Monitor/1.0"
        )
    )

    allowed_hosts = config[
        "allowed_hosts"
    ]

    index_observation = (
        fetch_resource(
            config["index_url"],
            timeout_seconds=(
                timeout_seconds
            ),
            user_agent=user_agent,
            allowed_hosts=allowed_hosts,
        )
    )

    document_observation = (
        fetch_resource(
            config["canonical_url"],
            timeout_seconds=(
                timeout_seconds
            ),
            user_agent=user_agent,
            allowed_hosts=allowed_hosts,
        )
    )

    expected = config[
        "expected_content_types"
    ]

    assert_content_type(
        source_id,
        "index",
        index_observation,
        expected["index"],
    )

    assert_content_type(
        source_id,
        "document",
        document_observation,
        expected["document"],
    )

    return {
        "source_id": source_id,
        "checked_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "authority_code": config[
            "authority_code"
        ],
        "publisher": config[
            "publisher"
        ],
        "source_family": config[
            "source_family"
        ],
        "document_code": config[
            "document_code"
        ],
        "index": index_observation,
        "document": (
            document_observation
        ),
    }


def select_sources(
    registry,
    source_id=None
):
    sources = registry["sources"]

    if source_id is not None:
        if source_id not in sources:
            raise KeyError(
                f"Unknown source: {source_id}"
            )

        selected = {
            source_id: sources[source_id]
        }
    else:
        selected = {
            key: config
            for key, config
            in sources.items()
            if config.get(
                "enabled",
                False
            )
        }

    if not selected:
        raise RuntimeError(
            "No source selected."
        )

    return selected


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Read-only HTTP probe for "
            "Jason OS Source Registry v1."
        )
    )

    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help=(
            "Path to source_registry_v1.yaml."
        ),
    )

    parser.add_argument(
        "--source",
        help=(
            "Probe one source ID. "
            "Default: all enabled sources."
        ),
    )

    args = parser.parse_args()

    registry = load_registry(
        args.registry
    )

    defaults = registry.get(
        "defaults",
        {}
    )

    selected = select_sources(
        registry,
        source_id=args.source
    )

    observations = []

    for source_id, config in (
        selected.items()
    ):
        observations.append(
            probe_source(
                source_id,
                config,
                defaults,
            )
        )

    payload = {
        "source_registry_version":
            registry[
                "source_registry_version"
            ],
        "probe_mode": "read-only",
        "observations": observations,
    }

    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
