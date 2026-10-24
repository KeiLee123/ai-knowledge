#!/usr/bin/env python3

import argparse
import json
import tempfile
from pathlib import Path

from build_multimodal_chunks_v2 import build_output
from extract_document_v2 import build_manifest
from ingest_canonical_staging_v1 import (
    ALLOWED_REMOTE,
    load_expected_baseline,
    load_registry,
    validate_source_id,
    verify_download,
    download_canonical,
)
from ingest_manifest_v2 import (
    DEFAULT_EMBED_URL,
    EMBED_MODEL,
    EXPECTED_DIMENSIONS,
    check_database_contract,
    execute_transaction,
    inspect_transaction_sql,
    load_chunks,
    precompute_embeddings,
    read_existing_document,
    sql_quote,
    vector_literal,
)
from route_document_v2 import assess_manifest
from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
    verify_runtime,
)


VERSION = "canonical-text-ingestion-v1"
REQUIRED_ROUTE = "legacy-v1"


def validate_text_ingestion_config(config):
    errors = []

    if config.get("enabled") is not True:
        errors.append("canonical_text_ingestion must be enabled")

    if config.get("controller_environment") != "staging":
        errors.append("controller_environment must be staging")

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

    if config.get("db_container") != STAGING_DB_CONTAINER:
        errors.append("db_container must be the fixed staging DB")

    if config.get("db_container") == PRODUCTION_DB_CONTAINER:
        errors.append("Production DB container is forbidden")

    if config.get("required_route") != REQUIRED_ROUTE:
        errors.append("required_route must be legacy-v1")

    if config.get("allow_production_write", False) is not False:
        errors.append("allow_production_write must be false")

    if errors:
        raise RuntimeError("; ".join(errors))


def resolve_text_source(registry, source_id):
    validate_source_id(source_id)

    source = (registry.get("sources") or {}).get(source_id)

    if not isinstance(source, dict):
        raise RuntimeError(f"Unknown source: {source_id}")

    if source.get("enabled") is not True:
        raise RuntimeError("Source is not enabled")

    config = source.get("canonical_text_ingestion")

    if not isinstance(config, dict):
        raise RuntimeError("canonical_text_ingestion config missing")

    validate_text_ingestion_config(config)

    return source, config, (registry.get("defaults") or {})


def validate_legacy_route(route):
    decision = route.get("decision") or {}

    if decision.get("production_decision_valid") is not True:
        raise RuntimeError("Router did not produce a valid full-document decision")

    if decision.get("eligible_for_v2") is not False:
        raise RuntimeError(
            "Text-only ingestion refused: document is eligible for multimodal-v2"
        )

    if decision.get("recommended_pipeline") != REQUIRED_ROUTE:
        raise RuntimeError(
            "Text-only ingestion refused: router did not select legacy-v1"
        )

    return decision


def write_json(path, payload):
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def text_document_metadata(
    payload,
    chunks_path,
    canonical_source,
):
    source_manifest = payload.get("source_manifest") or {}
    summary = payload.get("summary") or {}

    return {
        "synthetic": False,
        "ingestion_version": VERSION,
        "ingester_version": VERSION,
        "multimodal": False,
        "routing_profile": REQUIRED_ROUTE,
        "canonical_source": canonical_source,
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


def text_chunk_metadata(chunk):
    metadata = dict(chunk.get("metadata") or {})

    metadata.update(
        {
            "synthetic": False,
            "ingestion_version": VERSION,
            "ingester_version": VERSION,
            "retrieval_role": "text-primary",
            "multimodal": False,
        }
    )

    return metadata


def build_text_transaction_sql(
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
):
    chunks = payload["chunks"]

    if len(vectors) != len(chunks):
        raise RuntimeError(
            "Embedding count does not match chunk count: "
            f"{len(vectors)} != {len(chunks)}"
        )

    source_manifest = payload.get("source_manifest") or {}
    checksum = source_manifest["document_sha256"]

    doc_metadata = json.dumps(
        text_document_metadata(
            payload,
            chunks_path,
            canonical_source,
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
            text_chunk_metadata(chunk),
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
        "db_container": config["db_container"],
        "canonical_source": config["source"],
        "sha256": verified["sha256"],
        "size_bytes": verified["size_bytes"],
        "verified": True,
        "required_route": REQUIRED_ROUTE,
        "observed_route": route_decision.get("recommended_pipeline"),
        "multimodal": False,
        "chunk_count": len(chunks_payload.get("chunks") or []),
        "counts_by_origin": (
            (chunks_payload.get("summary") or {}).get("counts_by_origin") or {}
        ),
        "database_contract_ok": db_contract["contract_ok"],
        "duplicate_checksum": db_contract.get("duplicate_checksum"),
        "production_write": False,
        "database_write_requested": mode == "write",
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Staging-only text ingestion gate for canonical documents "
            "that the deterministic router classifies as legacy-v1."
        )
    )

    parser.add_argument("source_id")
    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parent / "source_registry_v1.yaml"
        ),
    )
    parser.add_argument(
        "--state-root",
        default="/var/lib/jason-os/source-monitor-staging",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--prepare",
        action="store_true",
        help=(
            "Build text chunks, precompute embeddings and validate "
            "the transaction without executing it."
        ),
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write only to the isolated Staging Knowledge DB.",
    )

    parser.add_argument(
        "--confirm-staging-write",
        action="store_true",
        help="Required together with --write.",
    )
    parser.add_argument(
        "--workdir",
        default="",
        help="Optional persistent directory for validation artifacts.",
    )

    args = parser.parse_args()

    if args.confirm_staging_write and not args.write:
        raise SystemExit("--confirm-staging-write requires --write")

    if args.write and not args.confirm_staging_write:
        raise SystemExit("--write requires --confirm-staging-write")

    repo_root = Path(__file__).resolve().parent
    temp_context = None

    try:
        guard = verify_runtime(repo_root)
        registry = load_registry(Path(args.registry).expanduser().resolve())

        source, config, defaults = resolve_text_source(
            registry,
            args.source_id,
        )

        expected = load_expected_baseline(
            Path(args.state_root).expanduser().resolve(),
            args.source_id,
        )

        if args.workdir:
            workdir = Path(args.workdir).expanduser().resolve()
            workdir.mkdir(parents=True, exist_ok=True)
        else:
            temp_context = tempfile.TemporaryDirectory(
                prefix="jason-os-canonical-text-"
            )
            workdir = Path(temp_context.name)

        source_file = workdir / Path(config["source"]).name
        phase_a_path = workdir / "phase-a.json"
        chunks_path = workdir / "retrieval-chunks-text-v1.json"

        download_canonical(config, source_file)
        verified = verify_download(source_file, expected)

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

        checksum = (
            chunks_payload["source_manifest"]["document_sha256"]
        )

        db_contract = check_database_contract(
            checksum,
            STAGING_DB_CONTAINER,
        )

        if not db_contract["contract_ok"]:
            raise RuntimeError("Staging database contract check failed")

        if db_contract.get("duplicate_checksum"):
            duplicate = db_contract["duplicate_checksum"]
            raise RuntimeError(
                "Document checksum already exists in Staging DB "
                f"as document_id={duplicate['document_id']}"
            )

        existing = read_existing_document(
            checksum,
            STAGING_DB_CONTAINER,
        )

        if existing:
            raise RuntimeError(
                "Document checksum already exists in Staging DB "
                f"as document_id={existing}"
            )

        mode_name = "write" if args.write else "prepare"

        summary = build_summary(
            source_id=args.source_id,
            mode=mode_name,
            guard=guard,
            config=config,
            verified=verified,
            route_decision=route_decision,
            chunks_payload=chunks_payload,
            db_contract=db_contract,
        )

        print(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
            )
        )

        vectors = precompute_embeddings(
            chunks_payload,
            DEFAULT_EMBED_URL,
        )

        sql = build_text_transaction_sql(
            payload=chunks_payload,
            vectors=vectors,
            chunks_path=chunks_path,
            title=str(
                source.get("title")
                or source.get("document_code")
                or "Canonical document"
            ),
            domain=str(source.get("domain") or "unknown"),
            topic=str(source.get("topic") or ""),
            document_type=str(
                config.get("document_type")
                or source.get("source_type")
                or "official-document"
            ),
            authority=str(source.get("authority_code") or ""),
            jurisdiction=str(defaults.get("jurisdiction") or "HK"),
            language=str(config.get("language") or "en"),
            source_url=str(source.get("canonical_url") or ""),
            canonical_source=config["source"],
        )

        inspection = inspect_transaction_sql(
            sql,
            len(chunks_payload["chunks"]),
        )

        print()
        print("TEXT_TRANSACTION")
        print(
            json.dumps(
                inspection,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not inspection["transaction_contract_ok"]:
            raise RuntimeError(
                "Generated text transaction failed structural validation"
            )

        if not args.write:
            print()
            print("STATUS: READY_FOR_STAGING_TEXT_WRITE")
            print("Transaction SQL was not executed.")
            print("Database writes performed: False")

            if args.workdir:
                print("Artifacts retained at:", workdir)

            return

        result = execute_transaction(
            sql,
            STAGING_DB_CONTAINER,
        )

        print()
        print("TEXT_INGESTION_COMMITTED")

        if result:
            print(result)

        print("STATUS: INGESTED_TEXT_TO_STAGING")
        print("Database writes performed: True")

        if args.workdir:
            print("Artifacts retained at:", workdir)

    except Exception as exc:
        raise SystemExit(
            "CANONICAL TEXT INGESTION FAILED: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    finally:
        if temp_context is not None:
            temp_context.cleanup()


if __name__ == "__main__":
    main()
