#!/usr/bin/env python3

from run_multimodal_canary_v2 import (
    PRODUCTION_DB_CONTAINER,
    STAGING_DB_CONTAINER,
)
from validate_staging_retrieval_v2 import (
    EXPECTED_DIMENSIONS,
    assert_read_only_sql,
    build_retrieval_sql,
    parse_rows,
    validate_checksum,
)


def assert_staging_is_not_production():
    assert (
        STAGING_DB_CONTAINER
        != PRODUCTION_DB_CONTAINER
    )


def assert_sql_is_read_only():
    checksum = "a" * 64
    vector = [0.0] * EXPECTED_DIMENSIONS

    sql = build_retrieval_sql(
        checksum=checksum,
        vector=vector,
        limit=5,
    )

    assert checksum in sql
    assert "SELECT" in sql
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    assert "DELETE" not in sql

    assert_read_only_sql(sql)


def assert_invalid_checksum_rejected():
    try:
        validate_checksum(
            "not-a-checksum"
        )
    except RuntimeError:
        return

    raise AssertionError(
        "Invalid checksum was accepted"
    )


def assert_row_parser():
    import base64

    content = "Top Front Side views Ø20"
    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    raw = (
        "123\t44\t44\tvisual_understanding\t"
        "supplementary\tmultimodal-supplementary\t"
        "0.12345\t"
        + encoded
        + "\n"
    )

    rows = parse_rows(raw)

    assert len(rows) == 1
    assert rows[0]["chunk_id"] == 123
    assert rows[0]["page_start"] == 44
    assert rows[0]["evidence_origin"] == "visual_understanding"
    assert rows[0]["content"] == content


def main():
    assert_staging_is_not_production()
    assert_sql_is_read_only()
    assert_invalid_checksum_rejected()
    assert_row_parser()

    print(
        "Staging retrieval validator test PASS"
    )
    print(
        "Production DB exclusion: PASS"
    )
    print(
        "Read-only SQL guard: PASS"
    )
    print(
        "Checksum validation: PASS"
    )
    print(
        "Result parser: PASS"
    )


if __name__ == "__main__":
    main()
