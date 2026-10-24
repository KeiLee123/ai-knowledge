#!/usr/bin/env python3

import argparse
import json
import os
import re
import tempfile

from datetime import datetime, timezone
from pathlib import Path

from version_qualification_policy_v1 import (
    AUTO_QUALIFIED,
    NO_CHANGE,
    QUALIFIED,
    evaluate_version_update,
    validate_qualification_record,
)
from version_signal_extractor_v1 import (
    compare_version_snapshots,
)


STORE_VERSION = 1
SAFE_SOURCE_ID = re.compile(
    r"^[A-Za-z0-9_.-]+$"
)


def validate_state_root(
    value,
) -> Path:
    path = Path(
        value
    ).expanduser()

    if not path.is_absolute():
        raise ValueError(
            "state-root must be absolute"
        )

    lowered = str(
        path
    ).lower()

    if (
        "source-monitor-production"
        in lowered
    ):
        raise ValueError(
            "Production state root is forbidden"
        )

    return path.resolve()


def validate_source_id(
    source_id: str,
) -> str:
    if not SAFE_SOURCE_ID.fullmatch(
        source_id
    ):
        raise ValueError(
            "source_id contains unsafe characters"
        )

    return source_id


def current_snapshot_path(
    state_root: Path,
    source_id: str,
) -> Path:
    validate_source_id(
        source_id
    )

    return (
        state_root
        / "version-snapshots"
        / "current"
        / f"{source_id}.json"
    )


def history_snapshot_path(
    state_root: Path,
    source_id: str,
    document_sha256: str,
) -> Path:
    validate_source_id(
        source_id
    )

    sha = str(
        document_sha256
        or ""
    ).strip().lower()

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        sha,
    ):
        raise ValueError(
            "Invalid document SHA-256"
        )

    return (
        state_root
        / "version-snapshots"
        / "history"
        / source_id
        / f"{sha}.json"
    )


def write_json_atomic(
    path: Path,
    payload: dict,
    *,
    replace: bool,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if (
        path.exists()
        and not replace
    ):
        raise FileExistsError(
            f"State already exists: {path}"
        )

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as temp:
        temp_path = Path(
            temp.name
        )

        json.dump(
            payload,
            temp,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        temp.write("\n")
        temp.flush()
        os.fsync(
            temp.fileno()
        )

    try:
        if (
            path.exists()
            and not replace
        ):
            raise FileExistsError(
                f"State already exists: {path}"
            )

        temp_path.replace(
            path
        )
    except Exception:
        temp_path.unlink(
            missing_ok=True
        )
        raise


def load_record(
    path: Path,
) -> dict:
    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        payload.get(
            "version_snapshot_store_version"
        )
        != STORE_VERSION
    ):
        raise ValueError(
            "Unsupported snapshot store version"
        )

    if not isinstance(
        payload.get("snapshot"),
        dict,
    ):
        raise ValueError(
            "Stored snapshot is missing"
        )

    return payload


def parse_proposal_log(
    path: Path,
) -> dict:
    text = path.read_text(
        encoding="utf-8"
    )

    decoder = json.JSONDecoder()
    found = []

    for index, char in enumerate(
        text
    ):
        if char != "{":
            continue

        try:
            obj, _ = (
                decoder.raw_decode(
                    text[index:]
                )
            )
        except Exception:
            continue

        if (
            isinstance(
                obj,
                dict,
            )
            and obj.get(
                "version"
            )
            == "production-release-proposal-v2"
        ):
            found.append(
                obj
            )

    if len(found) != 1:
        raise ValueError(
            "Expected exactly one "
            "production-release-proposal-v2 "
            f"JSON object; found {len(found)}"
        )

    return found[0]


def validate_proposal(
    proposal: dict,
    source_id: str,
) -> tuple[
    dict,
    dict,
    dict,
]:
    if (
        proposal.get(
            "source_id"
        )
        != source_id
    ):
        raise ValueError(
            "Proposal source_id mismatch"
        )

    if (
        proposal.get(
            "production_access"
        )
        is not False
        or proposal.get(
            "production_write"
        )
        is not False
    ):
        raise ValueError(
            "Unsafe proposal Production state"
        )

    contract = (
        proposal.get(
            "contract_proposal"
        )
        or {}
    )

    release = (
        contract.get(
            "release_v2"
        )
        or {}
    )

    if (
        release.get(
            "write_authorized"
        )
        is not False
    ):
        raise ValueError(
            "Snapshot store accepts only "
            "write_authorized=false proposals"
        )

    top_snapshot = proposal.get(
        "version_signals"
    )
    release_snapshot = release.get(
        "version_signals"
    )

    if (
        not isinstance(
            top_snapshot,
            dict,
        )
        or top_snapshot
        != release_snapshot
    ):
        raise ValueError(
            "Version signal snapshot mismatch"
        )

    if (
        top_snapshot.get(
            "document_sha256"
        )
        != proposal.get(
            "canonical_sha256"
        )
    ):
        raise ValueError(
            "Snapshot document SHA mismatch"
        )

    qualification = (
        release.get(
            "qualification"
        )
    )

    validate_qualification_record(
        qualification
    )

    return (
        top_snapshot,
        qualification,
        release,
    )


def now_utc() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def build_record(
    *,
    source_id: str,
    snapshot: dict,
    qualification: dict,
    release: dict,
    accepted_at: str | None = None,
) -> dict:
    return {
        "version_snapshot_store_version":
            STORE_VERSION,
        "source_id":
            source_id,
        "accepted_at":
            accepted_at
            or now_utc(),
        "release_id":
            release.get(
                "release_id"
            ),
        "artifact_profile":
            release.get(
                "artifact_profile"
            ),
        "qualification":
            qualification,
        "snapshot":
            snapshot,
    }


def initialize_reference(
    *,
    state_root: Path,
    source_id: str,
    proposal: dict,
    accepted_at: str | None = None,
) -> dict:
    (
        snapshot,
        qualification,
        release,
    ) = validate_proposal(
        proposal,
        source_id,
    )

    if (
        qualification.get(
            "mode"
        )
        != "initial_release"
        or qualification.get(
            "status"
        )
        != QUALIFIED
        or qualification.get(
            "decision"
        )
        != AUTO_QUALIFIED
    ):
        raise ValueError(
            "Initial reference requires "
            "AUTO_QUALIFIED initial_release"
        )

    path = current_snapshot_path(
        state_root,
        source_id,
    )

    record = build_record(
        source_id=source_id,
        snapshot=snapshot,
        qualification=qualification,
        release=release,
        accepted_at=accepted_at,
    )

    write_json_atomic(
        path,
        record,
        replace=False,
    )

    return {
        "status":
            "REFERENCE_INITIALIZED",
        "current_path":
            str(path),
        "record":
            record,
    }


def compare_reference(
    *,
    state_root: Path,
    source_id: str,
    proposal: dict,
) -> dict:
    current_path = (
        current_snapshot_path(
            state_root,
            source_id,
        )
    )

    if not current_path.exists():
        raise FileNotFoundError(
            f"Reference snapshot not found: "
            f"{current_path}"
        )

    stored = load_record(
        current_path
    )

    if (
        stored.get(
            "source_id"
        )
        != source_id
    ):
        raise ValueError(
            "Stored source_id mismatch"
        )

    (
        current_snapshot,
        proposal_qualification,
        release,
    ) = validate_proposal(
        proposal,
        source_id,
    )

    proposal_signals = (
        proposal_qualification.get(
            "signals"
        )
        or {}
    )

    signals = (
        compare_version_snapshots(
            stored[
                "snapshot"
            ],
            current_snapshot,
            staging_validation_verified=(
                proposal_signals.get(
                    "staging_validation_verified"
                )
                is True
            ),
            deterministic_release=(
                proposal_signals.get(
                    "deterministic_release"
                )
                is True
            ),
        )
    )

    qualification = (
        evaluate_version_update(
            signals
        )
    )

    return {
        "status":
            "REFERENCE_COMPARED",
        "source_id":
            source_id,
        "current_path":
            str(current_path),
        "previous_release_id":
            stored.get(
                "release_id"
            ),
        "current_release_id":
            release.get(
                "release_id"
            ),
        "signals":
            signals,
        "qualification":
            qualification,
        "previous_snapshot":
            stored[
                "snapshot"
            ],
        "current_snapshot":
            current_snapshot,
    }


def archive_current(
    *,
    state_root: Path,
    source_id: str,
    record: dict,
) -> str:
    previous_sha = (
        record[
            "snapshot"
        ].get(
            "document_sha256"
        )
    )

    path = history_snapshot_path(
        state_root,
        source_id,
        previous_sha,
    )

    if path.exists():
        existing = load_record(
            path
        )

        if existing != record:
            raise ValueError(
                "History collision with "
                "different record"
            )

        return str(path)

    write_json_atomic(
        path,
        record,
        replace=False,
    )

    return str(path)


def advance_reference(
    *,
    state_root: Path,
    source_id: str,
    proposal: dict,
    accepted_at: str | None = None,
) -> dict:
    comparison = compare_reference(
        state_root=state_root,
        source_id=source_id,
        proposal=proposal,
    )

    qualification = (
        comparison[
            "qualification"
        ]
    )

    if (
        qualification.get(
            "status"
        )
        != QUALIFIED
        or qualification.get(
            "decision"
        )
        != AUTO_QUALIFIED
    ):
        raise ValueError(
            "Reference advance requires "
            "AUTO_QUALIFIED version_update"
        )

    current_path = (
        current_snapshot_path(
            state_root,
            source_id,
        )
    )

    stored = load_record(
        current_path
    )

    history_path = archive_current(
        state_root=state_root,
        source_id=source_id,
        record=stored,
    )

    (
        snapshot,
        _initial_qualification,
        release,
    ) = validate_proposal(
        proposal,
        source_id,
    )

    record = build_record(
        source_id=source_id,
        snapshot=snapshot,
        qualification=qualification,
        release=release,
        accepted_at=accepted_at,
    )

    write_json_atomic(
        current_path,
        record,
        replace=True,
    )

    return {
        "status":
            "REFERENCE_ADVANCED",
        "current_path":
            str(current_path),
        "history_path":
            history_path,
        "record":
            record,
        "qualification":
            qualification,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Staging version-snapshot "
            "persistence and comparison. "
            "No Production access."
        )
    )

    parser.add_argument(
        "source_id"
    )

    parser.add_argument(
        "--state-root",
        required=True,
    )

    parser.add_argument(
        "--proposal-log",
        required=True,
    )

    mode = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    mode.add_argument(
        "--initialize",
        action="store_true",
    )
    mode.add_argument(
        "--compare",
        action="store_true",
    )
    mode.add_argument(
        "--advance",
        action="store_true",
    )

    parser.add_argument(
        "--confirm-staging-state-write",
        action="store_true",
    )

    args = parser.parse_args()

    state_root = validate_state_root(
        args.state_root
    )

    source_id = validate_source_id(
        args.source_id
    )

    proposal = parse_proposal_log(
        Path(
            args.proposal_log
        ).expanduser().resolve()
    )

    if (
        args.initialize
        or args.advance
    ):
        if (
            not args.confirm_staging_state_write
        ):
            raise SystemExit(
                "State write requires "
                "--confirm-staging-state-write"
            )

    if args.initialize:
        result = initialize_reference(
            state_root=state_root,
            source_id=source_id,
            proposal=proposal,
        )
    elif args.compare:
        result = compare_reference(
            state_root=state_root,
            source_id=source_id,
            proposal=proposal,
        )
    else:
        result = advance_reference(
            state_root=state_root,
            source_id=source_id,
            proposal=proposal,
        )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    print()

    if args.initialize:
        print(
            "STATUS: VERSION_REFERENCE_INITIALIZED"
        )
    elif args.compare:
        qualification = (
            result[
                "qualification"
            ]
        )
        print(
            "STATUS: VERSION_REFERENCE_COMPARED "
            + qualification[
                "decision"
            ]
        )
    else:
        print(
            "STATUS: VERSION_REFERENCE_ADVANCED"
        )


if __name__ == "__main__":
    main()
