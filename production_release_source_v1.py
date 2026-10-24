#!/usr/bin/env python3

import re
import subprocess

import yaml


REGISTRY_VERSION = 1
ALLOWED_REMOTE = "gdrive-bd-write:"
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_release_registry(path):
    payload = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Production release registry must be a mapping"
        )

    if (
        payload.get("production_release_registry_version")
        != REGISTRY_VERSION
    ):
        raise RuntimeError(
            "Unsupported Production release registry version"
        )

    return payload


def validate_source_id(source_id):
    if not SAFE_SOURCE_ID.fullmatch(source_id):
        raise RuntimeError(
            "Unsafe Production release source id"
        )

    return source_id


def canonical_remote_path(config):
    return config["remote"] + config["source"]


def download_canonical(config, destination):
    if config.get("remote") != ALLOWED_REMOTE:
        raise RuntimeError(
            "Production release remote must be the isolated BD writer"
        )

    result = subprocess.run(
        [
            "rclone",
            "copyto",
            canonical_remote_path(config),
            str(destination),
        ],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Canonical Drive download failed"
        )
