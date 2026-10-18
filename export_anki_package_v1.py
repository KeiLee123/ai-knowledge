#!/usr/bin/env python3

import argparse
import hashlib
import html
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import genanki


EXPORTER_VERSION = "sr-e-1"
SUPPORTED_SCHEMA = "anki-card-manifest-v1"

MODEL_ID = 1768432197
MODEL_NAME = "Jason OS v1"


FIELDS = [
    "Question",
    "Answer",
    "Explanation",
    "Image",
    "RelatedKnowledge",
    "SourceTitle",
    "SourcePage",
    "SourceURL",
    "SourceFileID",
    "SourceFilename",
    "ChunkIDs",
    "CardKey",
    "Tags",
]


CSS = """
.card {
  font-family: Arial, sans-serif;
  font-size: 20px;
  text-align: left;
  color: #222;
  background: #fff;
  line-height: 1.45;
  max-width: 900px;
  margin: 0 auto;
}

.visual img {
  display: block;
  max-width: 100%;
  max-height: 65vh;
  margin: 0 auto 18px auto;
}

.question {
  font-size: 1.15em;
  font-weight: 600;
}

.answer {
  font-size: 1.08em;
  margin-bottom: 14px;
}

.explanation,
.related {
  margin-top: 14px;
}

.source {
  margin-top: 20px;
  padding-top: 10px;
  border-top: 1px solid #ccc;
  font-size: 0.82em;
  color: #666;
}

.meta {
  display: none;
}
""".strip()


FRONT_TEMPLATE = """
<div class="visual">{{Image}}</div>
<div class="question">{{Question}}</div>
""".strip()


BACK_TEMPLATE = """
{{FrontSide}}
<hr id="answer">

<div class="answer">{{Answer}}</div>

{{#Explanation}}
<div class="explanation">
  <strong>Explanation</strong><br>
  {{Explanation}}
</div>
{{/Explanation}}

{{#RelatedKnowledge}}
<div class="related">
  <strong>Related knowledge</strong><br>
  {{RelatedKnowledge}}
</div>
{{/RelatedKnowledge}}

<div class="source">
  <strong>Source</strong><br>
  {{SourceTitle}} {{SourcePage}}
  {{#SourceURL}}
  — <a href="{{SourceURL}}">Open original</a>
  {{/SourceURL}}
  {{#SourceFilename}}
  <br>{{SourceFilename}}
  {{/SourceFilename}}
</div>

<div class="meta">
  {{CardKey}}
  {{ChunkIDs}}
  {{SourceFileID}}
  {{Tags}}
</div>
""".strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if (
        payload.get("schema_version")
        != SUPPORTED_SCHEMA
    ):
        raise RuntimeError(
            "Unsupported manifest schema: "
            f"{payload.get('schema_version')!r}"
        )

    cards = payload.get("cards")

    if not isinstance(cards, list):
        raise RuntimeError(
            "cards must be a list"
        )

    if not cards:
        raise RuntimeError(
            "Manifest has no cards"
        )

    deck = payload.get("deck")

    if not isinstance(deck, dict):
        raise RuntimeError(
            "deck must be an object"
        )

    deck_name = str(
        deck.get("name")
        or ""
    ).strip()

    if not deck_name:
        raise RuntimeError(
            "deck.name is required"
        )

    return payload


def stable_positive_id(
    namespace: str,
    value: str,
) -> int:
    digest = hashlib.sha256(
        (
            namespace
            + "\n"
            + value
        ).encode("utf-8")
    ).digest()

    # Keep IDs in a conventional positive 10-digit-ish range
    # and below signed 32-bit max.
    return (
        1_000_000_000
        + (
            int.from_bytes(
                digest[:8],
                "big",
            )
            % 1_000_000_000
        )
    )


def clean_tag(value: str) -> str:
    value = str(
        value or ""
    ).strip()

    value = re.sub(
        r"\s+",
        "_",
        value,
    )

    return value


def source_page_label(
    source: dict,
) -> str:
    start = source.get(
        "page_start"
    )

    end = source.get(
        "page_end"
    )

    if not isinstance(start, int):
        return ""

    if (
        not isinstance(end, int)
        or end == start
    ):
        return f"p.{start}"

    return f"pp.{start}-{end}"


def related_html(
    values,
) -> str:
    if not isinstance(
        values,
        list,
    ):
        return ""

    cleaned = [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]

    if not cleaned:
        return ""

    items = "".join(
        "<li>"
        + html.escape(
            value
        )
        + "</li>"
        for value in cleaned
    )

    return (
        "<ul>"
        + items
        + "</ul>"
    )


def media_field_and_files(
    card: dict,
    media_root: Path | None,
) -> tuple[str, list[Path]]:
    media = card.get(
        "media"
    ) or []

    if not isinstance(media, list):
        raise RuntimeError(
            "card.media must be a list"
        )

    if not media:
        return "", []

    if media_root is None:
        raise RuntimeError(
            "Manifest references media but "
            "--media-root was not supplied"
        )

    image_tags = []
    files = []

    for item in media:
        if not isinstance(
            item,
            dict,
        ):
            raise RuntimeError(
                "Media item must be an object"
            )

        if item.get(
            "kind"
        ) != "pdf_page":
            raise RuntimeError(
                "Unsupported media kind: "
                f"{item.get('kind')!r}"
            )

        filename = str(
            item.get(
                "filename"
            )
            or ""
        ).strip()

        if not filename:
            raise RuntimeError(
                "Media filename missing"
            )

        if (
            Path(filename).name
            != filename
        ):
            raise RuntimeError(
                "Media filename must be "
                "a basename"
            )

        path = (
            media_root
            / filename
        ).resolve()

        if not path.is_file():
            raise RuntimeError(
                "Media file not found: "
                f"{path}"
            )

        expected_sha = str(
            item.get(
                "sha256"
            )
            or ""
        ).strip()

        if expected_sha:
            actual_sha = (
                sha256_file(
                    path
                )
            )

            if (
                actual_sha
                != expected_sha
            ):
                raise RuntimeError(
                    "Media checksum mismatch "
                    f"for {filename}: "
                    f"expected={expected_sha} "
                    f"actual={actual_sha}"
                )

        image_tags.append(
            '<img src="'
            + html.escape(
                filename,
                quote=True,
            )
            + '">'
        )

        files.append(
            path
        )

    return (
        "<br>".join(
            image_tags
        ),
        files,
    )


def model() -> genanki.Model:
    return genanki.Model(
        MODEL_ID,
        MODEL_NAME,
        fields=[
            {"name": name}
            for name in FIELDS
        ],
        templates=[
            {
                "name":
                    "Jason OS Recall",
                "qfmt":
                    FRONT_TEMPLATE,
                "afmt":
                    BACK_TEMPLATE,
            }
        ],
        css=CSS,
        sort_field_index=0,
    )


def note_from_card(
    card: dict,
    note_model: genanki.Model,
    media_root: Path | None,
) -> tuple[
    genanki.Note,
    list[Path],
    str,
]:
    if not isinstance(card, dict):
        raise RuntimeError(
            "Card is not an object"
        )

    card_key = str(
        card.get(
            "card_key"
        )
        or ""
    ).strip()

    if not card_key:
        raise RuntimeError(
            "card_key is required"
        )

    question = str(
        card.get(
            "question"
        )
        or ""
    ).strip()

    answer = str(
        card.get(
            "answer"
        )
        or ""
    ).strip()

    if not question:
        raise RuntimeError(
            f"Question missing for "
            f"card_key={card_key}"
        )

    if not answer:
        raise RuntimeError(
            f"Answer missing for "
            f"card_key={card_key}"
        )

    source = (
        card.get("source")
        or {}
    )

    if not isinstance(
        source,
        dict,
    ):
        raise RuntimeError(
            "card.source must be an object"
        )

    chunk_ids = (
        source.get(
            "chunk_ids"
        )
        or []
    )

    if not isinstance(
        chunk_ids,
        list,
    ):
        raise RuntimeError(
            "source.chunk_ids must "
            "be a list"
        )

    image_html, media_files = (
        media_field_and_files(
            card,
            media_root,
        )
    )

    tags = [
        clean_tag(value)
        for value in (
            card.get(
                "tags"
            )
            or []
        )
        if clean_tag(value)
    ]

    # Stable Anki note identity is derived only from
    # Jason OS CardKey. Re-exporting the same card
    # therefore preserves note identity.
    guid = genanki.guid_for(
        card_key
    )

    source_url = str(
        source.get(
            "source_url"
        )
        or ""
    ).strip()

    fields = [
        html.escape(
            question
        ),
        html.escape(
            answer
        ),
        html.escape(
            str(
                card.get(
                    "explanation"
                )
                or ""
            ).strip()
        ),
        image_html,
        related_html(
            card.get(
                "related_knowledge"
            )
        ),
        html.escape(
            str(
                source.get(
                    "document_title"
                )
                or ""
            )
        ),
        html.escape(
            source_page_label(
                source
            )
        ),
        html.escape(
            source_url,
            quote=True,
        ),
        html.escape(
            str(
                source.get(
                    "source_file_id"
                )
                or ""
            )
        ),
        html.escape(
            str(
                source.get(
                    "source_filename"
                )
                or ""
            )
        ),
        html.escape(
            ",".join(
                str(value)
                for value in chunk_ids
            )
        ),
        html.escape(
            card_key
        ),
        html.escape(
            " ".join(tags)
        ),
    ]

    note = genanki.Note(
        model=note_model,
        fields=fields,
        tags=tags,
        guid=guid,
    )

    return (
        note,
        media_files,
        guid,
    )


def verify_package(
    package_path: Path,
    expected_guids: set[str],
    expected_media_count: int,
) -> dict:
    with zipfile.ZipFile(
        package_path,
        "r",
    ) as archive:
        names = set(
            archive.namelist()
        )

        if (
            "collection.anki2"
            not in names
        ):
            raise RuntimeError(
                "Package missing "
                "collection.anki2"
            )

        if "media" not in names:
            raise RuntimeError(
                "Package missing media map"
            )

        media_map = json.loads(
            archive.read(
                "media"
            ).decode(
                "utf-8"
            )
        )

        if (
            len(media_map)
            != expected_media_count
        ):
            raise RuntimeError(
                "Package media count mismatch: "
                f"expected={expected_media_count} "
                f"actual={len(media_map)}"
            )

        with tempfile.TemporaryDirectory(
            prefix="jasonos-apkg-verify-"
        ) as temp_dir:
            collection_path = (
                Path(temp_dir)
                / "collection.anki2"
            )

            collection_path.write_bytes(
                archive.read(
                    "collection.anki2"
                )
            )

            conn = sqlite3.connect(
                collection_path
            )

            try:
                rows = conn.execute(
                    "SELECT guid FROM notes"
                ).fetchall()

            finally:
                conn.close()

    actual_guids = {
        str(row[0])
        for row in rows
    }

    if actual_guids != expected_guids:
        raise RuntimeError(
            "Package note GUID mismatch"
        )

    return {
        "zip_ok": True,
        "note_count":
            len(actual_guids),
        "media_count":
            expected_media_count,
        "stable_guids_ok":
            True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export an anki-card-manifest-v1 "
            "to an Anki .apkg package. "
            "Creates a file only; does not "
            "connect to or modify Anki."
        )
    )

    parser.add_argument(
        "manifest",
        help=(
            "Input anki-card-manifest-v1 JSON"
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Output .apkg path",
    )

    parser.add_argument(
        "--media-root",
        help=(
            "Directory containing media files "
            "referenced by the manifest"
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    args = parser.parse_args()

    manifest_path = (
        Path(args.manifest)
        .expanduser()
        .resolve()
    )

    output_path = (
        Path(args.output)
        .expanduser()
        .resolve()
    )

    media_root = (
        Path(args.media_root)
        .expanduser()
        .resolve()
        if args.media_root
        else None
    )

    if not manifest_path.is_file():
        raise SystemExit(
            f"Manifest not found: "
            f"{manifest_path}"
        )

    if (
        output_path.suffix.lower()
        != ".apkg"
    ):
        raise SystemExit(
            "--output must end in .apkg"
        )

    if (
        output_path.exists()
        and not args.overwrite
    ):
        raise SystemExit(
            "Output already exists. "
            "Use --overwrite to replace it."
        )

    if (
        media_root is not None
        and not media_root.is_dir()
    ):
        raise SystemExit(
            f"Media root not found: "
            f"{media_root}"
        )

    try:
        payload = load_manifest(
            manifest_path
        )

        deck_name = str(
            payload["deck"]["name"]
        ).strip()

        deck_id = stable_positive_id(
            "jason-os-deck-v1",
            deck_name,
        )

        note_model = model()

        deck = genanki.Deck(
            deck_id,
            deck_name,
        )

        deck.description = (
            "Generated by Jason OS from "
            "source-grounded Knowledge Brain "
            "evidence."
        )

        media_paths = {}
        expected_guids = set()

        for card in payload["cards"]:
            note, media_files, guid = (
                note_from_card(
                    card,
                    note_model,
                    media_root,
                )
            )

            if guid in expected_guids:
                raise RuntimeError(
                    "Duplicate stable note GUID: "
                    f"{guid}"
                )

            expected_guids.add(
                guid
            )

            deck.add_note(
                note
            )

            for path in media_files:
                media_paths[
                    path.name
                ] = path

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        package = genanki.Package(
            deck
        )

        package.media_files = [
            str(
                media_paths[name]
            )
            for name in sorted(
                media_paths
            )
        ]

        package.write_to_file(
            str(output_path)
        )

        verification = (
            verify_package(
                output_path,
                expected_guids,
                len(media_paths),
            )
        )

    except Exception as exc:
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass

        raise SystemExit(
            "Anki package export failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    print(
        output_path
    )

    print(
        "Exporter version:",
        EXPORTER_VERSION,
    )

    print(
        "Deck:",
        deck_name,
    )

    print(
        "Deck ID:",
        deck_id,
    )

    print(
        "Notes:",
        verification[
            "note_count"
        ],
    )

    print(
        "Media files:",
        verification[
            "media_count"
        ],
    )

    print(
        "Stable GUIDs verified:",
        verification[
            "stable_guids_ok"
        ],
    )

    print(
        "Package ZIP verified:",
        verification[
            "zip_ok"
        ],
    )

    print(
        "Package SHA256:",
        sha256_file(
            output_path
        ),
    )

    print(
        "Package bytes:",
        output_path.stat().st_size,
    )

    print(
        "Database write performed:",
        False,
    )

    print(
        "Anki connection performed:",
        False,
    )


if __name__ == "__main__":
    main()
