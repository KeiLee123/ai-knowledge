"""Bounded fixture and task contracts; no URL or caller-supplied paths."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from extract_document_v2 import sha256_file
from phase_b_shadow import CONFIG_VERSION
import yaml

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_PDF_BYTES = 5 * 1024 * 1024


class ContractGap(ValueError):
    """A source or parsed field cannot safely satisfy the v2 contract."""


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    source_id: str
    version_id: str
    model_version: str
    filename: str
    sha256: str


def load_fixture(catalog: Path, fixture_id: str, input_dir: Path) -> tuple[Fixture, Path]:
    if not IDENTIFIER.fullmatch(fixture_id):
        raise ContractGap("invalid fixture_id")
    if catalog.resolve() != (input_dir / "catalog.json").resolve():
        raise ContractGap("catalog must be inside the isolated input directory")
    data = json.loads(catalog.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("fixtures"), dict):
        raise ContractGap("invalid fixture catalog")
    raw = data["fixtures"].get(fixture_id)
    if not isinstance(raw, dict):
        raise ContractGap("fixture is not allowlisted")
    for field in ("source_id", "version_id", "model_version"):
        if not isinstance(raw.get(field), str) or not IDENTIFIER.fullmatch(raw[field]):
            raise ContractGap(f"invalid {field}")
    registry = yaml.safe_load((Path(__file__).resolve().parent.parent / "source_registry_v1.yaml").read_text(encoding="utf-8"))
    registered = (registry.get("sources") or {}).get(raw["source_id"])
    if not isinstance(registered, dict) or registered.get("enabled") is not True or registered.get("source_type") != "official-document":
        raise ContractGap("source_id is not an enabled official document in Source Registry")
    filename = raw.get("filename")
    if (not isinstance(filename, str) or filename != Path(filename).name
            or filename in (".", "..") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.pdf", filename)):
        raise ContractGap("invalid PDF basename")
    digest = raw.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ContractGap("invalid pinned source SHA256")
    path = input_dir / filename
    if not path.is_file() or path.is_symlink() or path.resolve().parent != input_dir.resolve():
        raise ContractGap("source must be a regular PDF inside the isolated input directory")
    if path.stat().st_size > MAX_PDF_BYTES or path.stat().st_size == 0:
        raise ContractGap("source exceeds Phase B size bound or is empty")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ContractGap("source is not a PDF byte stream")
    if sha256_file(path) != digest:
        raise ContractGap("source SHA256 mismatch")
    try:
        import pymupdf
        with pymupdf.open(path) as pdf:
            if pdf.is_encrypted or not (1 <= len(pdf) <= 10):
                raise ContractGap("PDF is encrypted or exceeds the 10-page preflight bound")
    except ContractGap:
        raise
    except Exception as exc:
        raise ContractGap(f"PDF preflight failed: {type(exc).__name__}") from exc
    return Fixture(fixture_id, raw["source_id"], raw["version_id"], raw["model_version"], filename, digest), path


def task_id(fixture: Fixture) -> str:
    key = "\0".join((fixture.source_id, fixture.version_id, fixture.model_version, fixture.sha256, CONFIG_VERSION))
    return "phase-b-" + hashlib.sha256(key.encode("utf-8")).hexdigest()
