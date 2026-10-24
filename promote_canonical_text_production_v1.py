#!/usr/bin/env python3

import argparse
import json
import tempfile
from pathlib import Path

from build_multimodal_chunks_v2 import build_output
from extract_document_v2 import build_manifest
from ingest_canonical_staging_v1 import (
    ALLOWED_REMOTE,
    download_canonical,
    load_registry,
    validate_source_id,
)
from ingest_canonical_text_staging_v1 import (
    REQUIRED_ROUTE,
    VERSION as FROZEN_INGESTION_VERSION,
    validate_legacy_route,
    write_json,
)
from ingest_manifest_v2 import (
    DEFAULT_EMBED_URL,
    EMBED_MODEL,
    EXPECTED_DIMENSIONS,
    check_database_contract,
    inspect_transaction_sql,
    load_chunks,
    precompute_embeddings,
    sql_quote,
    vector_literal,
)
from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)
from route_document_v2 import assess_manifest


VERSION = "canonical-text-production-promotion-v1"


def sha256_file(path):
    import hashlib

    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def validate_promotion_config(config):
    errors = []

    if config.get("enabled") is not True:
        errors.append("canonical_text_production_promotion must be enabled")

    if config.get("controller_environment") != "production":
        errors.append("controller_environment must be production")

    if config.get("remote") != ALLOWED_REMOTE:
        errors.append("remote must be the isolated BD writer")

    source_path = config.get("source")

    if (
        not isinstance(source_path, str)
        or source_path.startswith("/")
        or not source_path.startswith("Current/")
        or not source_path.lower().endswith(".pdf")
    ):
        errors.append("source must be a PDF under Current/")

    if config.get("db_container") != PRODUCTION_DB_CONTAINER:
        errors.append("db_container must be the fixed Production DB")

    if config.get("db_container") == STAGING_DB_CONTAINER:
        errors.append("Staging DB container is forbidden")

    if config.get("required_route") != REQUIRED_ROUTE:
        errors.append("required_route must be legacy-v1")

    if (
        config.get("frozen_ingestion_version")
        != FROZEN_INGESTION_VERSION
    ):
        errors.append(
            "frozen_ingestion_version must match "
            f"{FROZEN_INGESTION_VERSION}"
        )

    checksum = str(config.get("expected_sha256") or "").lower()

    if (
        len(checksum) != 64
        or any(ch not in "0123456789abcdef" for ch in checksum)
    ):
        errors.append("expected_sha256 must be a lowercase SHA-256 hex string")

    expected_chunks = config.get("expected_chunk_count")

    if not isinstance(expected_chunks, int) or expected_chunks <= 0:
        errors.append("expected_chunk_count must be a positive integer")

    expected_embeddings = config.get("expected_embedding_count")

    if (
        not isinstance(expected_embeddings, int)
        or expected_embeddings <= 0
    ):
        errors.append("expected_embedding_count must be a positive integer")

    if (
        isinstance(expected_chunks, int)
        and isinstance(expected_embeddings, int)
        and expected_chunks != expected_embeddings
    ):
        errors.append(
            "expected_embedding_count must equal expected_chunk_count"
        )

    if config.get("allow_production_write", False) is not False:
        errors.append("P2 allow_production_write must be false")

    if errors:
        raise RuntimeError("; ".join(errors))


def resolve_promotion_source(registry, source_id):
    validate_source_id(source_id)

    source = (registry.get("sources") or {}).get(source_id)

    if not isinstance(source, dict):
        raise RuntimeError(f"Unknown source: {source_id}")

    if source.get("enabled") is not True:
        raise RuntimeError("Source is not enabled")

    config = source.get("canonical_text_production_promotion")

    if not isinstance(config, dict):
        raise RuntimeError(
            "canonical_text_production_promotion config missing"
        )

    validate_promotion_config(config)

    return source, config, (registry.get("defaults") or {})


def verify_canonical_download(path, config):
    actual_sha256 = sha256_file(path)
    actual_size = path.stat().st_size
    expected_sha256 = config["expected_sha256"].lower()

    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "Canonical SHA-256 does not match the Git-controlled "
            "Production promotion candidate"
        )

    return {
        "sha256": actual_sha256,
        "size_bytes": actual_size,
        "verified": True,
    }


def validate_frozen_chunk_contract(payload, config):
    chunks = payload.get("chunks") or []
    expected = int(config["expected_chunk_count"])

    if len(chunks) != expected:
        raise RuntimeError(
            "Frozen chunk count drift: "
            f"expected {expected}, got {len(chunks)}"
        )

    counts = (payload.get("summary") or {}).get("counts_by_origin") or {}

    if counts.get("native_text") != expected:
        raise RuntimeError(
            "Frozen native_text count drift: "
            f"expected {expected}, got {counts.get('native_text')}"
        )

    for index, chunk in enumerate(chunks):
        metadata = chunk.get("metadata") or {}

        if metadata.get("evidence_origin") != "native_text":
            raise RuntimeError(
                f"Chunk {index} is not native_text"
            )

        if metadata.get("evidence_tier") != "primary":
            raise RuntimeError(
                f"Chunk {index} is not primary evidence"
            )

    return {
        "chunk_count": len(chunks),
        "native_text_chunks": expected,
        "frozen_chunk_contract_ok": True,
    }


def production_document_metadata(
    payload,
    chunks_path,
    canonical_source,
    canonical_sha256,
):
    source_manifest = payload.get("source_manifest") or {}
    summary = payload.get("summary") or {}

    return {
        "synthetic": False,
        "ingestion_version": FROZEN_INGESTION_VERSION,
        "ingester_version": FROZEN_INGESTION_VERSION,
        "release_gate": VERSION,
        "multimodal": False,
        "routing_profile": REQUIRED_ROUTE,
        "canonical_source": canonical_source,
        "canonical_sha256": canonical_sha256,
        "source_filename": source_manifest.get("document_name"),
        "source_chunks_file": chunks_path.name,
        "source_chunks_schema": payload.get("schema_version"),
        "source_manifest_sha256": source_manifest.get("sha256"),
        "retrieval_chunk_count": summary.get(
            "chunk_count",
            len(payload.get("chunks") or []),
        ),
        "evidence_counts": summary.get("counts_by_origin") or {},
    }


def production_chunk_metadata(chunk):
    metadata = dict(chunk.get("metadata") or {})

    metadata.update(
        {
            "synthetic": False,
            "ingestion_version": FROZEN_INGESTION_VERSION,
            "ingester_version": FROZEN_INGESTION_VERSION,
            "release_gate": VERSION,
            "retrieval_role": "text-primary",
            "multimodal": False,
        }
    )

    return metadata


def build_production_transaction_sql(
    *,
    payload,
    vectors,
    chunks_path,
    title,
    domain,
    topic,
    document_type,
    authority,
    jurisdiction,
    language,
    source_url,
    canonical_source,
    canonical_sha256,
):
    chunks = payload["chunks"]

    if len(vectors) != len(chunks):
        raise RuntimeError(
            "Embedding count does not match chunk count: "
            f"{len(vectors)} != {len(chunks)}"
        )

    source_manifest = payload.get("source_manifest") or {}
    checksum = source_manifest["document_sha256"]

    if checksum != canonical_sha256:
        raise RuntimeError(
            "Transaction checksum does not match canonical SHA-256"
        )

    doc_metadata = json.dumps(
        production_document_metadata(
            payload,
            chunks_path,
            canonical_source,
            canonical_sha256,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    source_url_sql = (
        "'" + sql_quote(source_url) + "'"
        if source_url
        else "NULL"
    )

    lines = [
        r"\set ON_ERROR_STOP on",
        "BEGIN;",
        (
            "INSERT INTO documents ("
            "title, domain, topic, "
            "document_type, authority, "
            "jurisdiction, source_type, "
            "source_url, checksum_sha256, "
            "language, metadata"
            ") VALUES ("
            f"'{sql_quote(title)}', "
            f"'{sql_quote(domain)}', "
            f"'{sql_quote(topic)}', "
            f"'{sql_quote(document_type)}', "
            f"'{sql_quote(authority)}', "
            f"'{sql_quote(jurisdiction)}', "
            "'canonical-drive-text', "
            f"{source_url_sql}, "
            f"'{sql_quote(checksum)}', "
            f"'{sql_quote(language)}', "
            f"'{sql_quote(doc_metadata)}'::jsonb"
            ") RETURNING id AS doc_id "
            r"\gset"
        ),
    ]

    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        metadata = json.dumps(
            production_chunk_metadata(chunk),
            ensure_ascii=False,
            separators=(",", ":"),
        )

        page_start = (
            "NULL"
            if chunk.get("page_start") is None
            else str(int(chunk["page_start"]))
        )

        page_end = (
            "NULL"
            if chunk.get("page_end") is None
            else str(int(chunk["page_end"]))
        )

        lines.append(
            (
                "INSERT INTO chunks ("
                "document_id, chunk_index, content, "
                "page_start, page_end, metadata"
                ") VALUES ("
                ":'doc_id', "
                f"{index}, "
                f"'{sql_quote(chunk['content'])}', "
                f"{page_start}, "
                f"{page_end}, "
                f"'{sql_quote(metadata)}'::jsonb"
                ") RETURNING id AS chunk_id "
                r"\gset"
            )
        )

        lines.append(
            (
                "INSERT INTO embeddings ("
                "chunk_id, provider, model, dimensions, embedding"
                ") VALUES ("
                ":'chunk_id', "
                "'local', "
                f"'{EMBED_MODEL}', "
                f"{EXPECTED_DIMENSIONS}, "
                f"'{vector_literal(vector)}'::vector"
                ");"
            )
        )

    lines.extend(
        [
            r"\echo DOCUMENT_ID :doc_id",
            "COMMIT;",
        ]
    )

    return "\n".join(lines) + "\n"


def build_summary(
    *,
    source_id,
    mode,
    guard,
    config,
    verified,
    route_decision,
    chunks_payload,
    db_contract,
):
    return {
        "version": VERSION,
        "source_id": source_id,
        "mode": mode,
        "guard_ok": guard["guard_ok"],
        "branch": guard["branch"],
        "db_container": PRODUCTION_DB_CONTAINER,
        "canonical_source": config["source"],
        "sha256": verified["sha256"],
        "size_bytes": verified["size_bytes"],
        "verified": True,
        "frozen_ingestion_version": config["frozen_ingestion_version"],
        "required_route": REQUIRED_ROUTE,
        "observed_route": route_decision.get("recommended_pipeline"),
        "multimodal": False,
        "expected_chunk_count": config["expected_chunk_count"],
        "chunk_count": len(chunks_payload.get("chunks") or []),
        "expected_embedding_count": config["expected_embedding_count"],
        "database_contract_ok": db_contract["contract_ok"],
        "duplicate_checksum": db_contract.get("duplicate_checksum"),
        "production_write": False,
        "database_write_requested": False,
    }


def prepare_candidate(
    *,
    source_id,
    registry_path,
    workdir,
    guard,
):
    registry = load_registry(registry_path)

    source, config, defaults = resolve_promotion_source(
        registry,
        source_id,
    )

    source_file = workdir / Path(config["source"]).name
    phase_a_path = workdir / "phase-a.json"
    chunks_path = workdir / "retrieval-chunks-production-v1.json"

    download_canonical(config, source_file)
    verified = verify_canonical_download(source_file, config)

    manifest = build_manifest(source_file)
    write_json(phase_a_path, manifest)

    route = assess_manifest(
        manifest,
        allow_partial=False,
    )
    route_decision = validate_legacy_route(route)

    chunks_payload = build_output(
        manifest_path=phase_a_path,
        manifest=manifest,
        target_chars=1800,
        overlap_chars=250,
    )
    write_json(chunks_path, chunks_payload)

    chunks_payload = load_chunks(chunks_path)
    frozen = validate_frozen_chunk_contract(
        chunks_payload,
        config,
    )

    checksum = (
        chunks_payload["source_manifest"]["document_sha256"]
    )

    if checksum != config["expected_sha256"]:
        raise RuntimeError(
            "Prepared document checksum does not match release profile"
        )

    db_contract = check_database_contract(
        checksum,
        PRODUCTION_DB_CONTAINER,
    )

    if not db_contract["contract_ok"]:
        raise RuntimeError("Production database contract check failed")

    duplicate = db_contract.get("duplicate_checksum")

    if duplicate:
        raise RuntimeError(
            "Document checksum already exists in Production DB "
            f"as document_id={duplicate['document_id']}"
        )

    return {
        "source": source,
        "config": config,
        "defaults": defaults,
        "source_file": source_file,
        "chunks_path": chunks_path,
        "chunks_payload": chunks_payload,
        "verified": verified,
        "route_decision": route_decision,
        "frozen_contract": frozen,
        "db_contract": db_contract,
        "guard": guard,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Production Promotion v1 P2 verify/prepare gate. "
            "It may read the fixed Production DB for schema and "
            "duplicate checks, but it cannot execute a database write."
        )
    )

    parser.add_argument("source_id")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Verify canonical bytes, route, frozen chunk contract, "
            "Production schema and duplicate status. No embeddings."
        ),
    )
    mode.add_argument(
        "--prepare",
        action="store_true",
        help=(
            "Additionally precompute all embeddings and inspect the "
            "complete Production transaction without executing it."
        ),
    )

    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent / "source_registry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--workdir",
        default="",
        help="Optional persistent directory for read-only artifacts.",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    temp_context = None

    try:
        guard = verify_runtime(repo_root)

        if args.workdir:
            workdir = Path(args.workdir).expanduser().resolve()
            workdir.mkdir(parents=True, exist_ok=True)
        else:
            temp_context = tempfile.TemporaryDirectory(
                prefix="jason-os-production-promotion-"
            )
            workdir = Path(temp_context.name)

        candidate = prepare_candidate(
            source_id=args.source_id,
            registry_path=Path(args.registry).expanduser().resolve(),
            workdir=workdir,
            guard=guard,
        )

        summary = build_summary(
            source_id=args.source_id,
            mode="prepare" if args.prepare else "verify",
            guard=candidate["guard"],
            config=candidate["config"],
            verified=candidate["verified"],
            route_decision=candidate["route_decision"],
            chunks_payload=candidate["chunks_payload"],
            db_contract=candidate["db_contract"],
        )

        print(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
            )
        )

        if args.verify:
            print()
            print("STATUS: PRODUCTION_PROMOTION_VERIFIED")
            print("No embeddings were persisted.")
            print("No transaction was executed.")
            print("Database writes performed: False")

            if args.workdir:
                print("Artifacts retained at:", workdir)

            return

        vectors = precompute_embeddings(
            candidate["chunks_payload"],
            DEFAULT_EMBED_URL,
        )

        if len(vectors) != candidate["config"]["expected_embedding_count"]:
            raise RuntimeError(
                "Frozen embedding count drift: "
                f"expected "
                f"{candidate['config']['expected_embedding_count']}, "
                f"got {len(vectors)}"
            )

        sql = build_production_transaction_sql(
            payload=candidate["chunks_payload"],
            vectors=vectors,
            chunks_path=candidate["chunks_path"],
            title=str(
                candidate["source"].get("title")
                or candidate["source"].get("document_code")
                or "Canonical document"
            ),
            domain=str(
                candidate["source"].get("domain")
                or "unknown"
            ),
            topic=str(
                candidate["source"].get("topic")
                or ""
            ),
            document_type=str(
                candidate["config"].get("document_type")
                or candidate["source"].get("source_type")
                or "official-document"
            ),
            authority=str(
                candidate["source"].get("authority_code")
                or ""
            ),
            jurisdiction=str(
                candidate["defaults"].get("jurisdiction")
                or "HK"
            ),
            language=str(
                candidate["config"].get("language")
                or "en"
            ),
            source_url=str(
                candidate["source"].get("canonical_url")
                or ""
            ),
            canonical_source=candidate["config"]["source"],
            canonical_sha256=candidate["config"]["expected_sha256"],
        )

        inspection = inspect_transaction_sql(
            sql,
            len(candidate["chunks_payload"]["chunks"]),
        )

        print()
        print("PRODUCTION_TRANSACTION")
        print(
            json.dumps(
                inspection,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not inspection["transaction_contract_ok"]:
            raise RuntimeError(
                "Generated Production transaction failed "
                "structural validation"
            )

        print()
        print("STATUS: READY_FOR_PRODUCTION_TEXT_WRITE")
        print("Transaction SQL was not executed.")
        print("Database writes performed: False")

        if args.workdir:
            print("Artifacts retained at:", workdir)

    except Exception as exc:
        raise SystemExit(
            "PRODUCTION PROMOTION P2 FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()
