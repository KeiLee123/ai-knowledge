#!/usr/bin/env python3

from production_promotion_guard_v1 import (
    PRODUCTION_DB_CONTAINER,
    REQUIRED_BRANCH,
    STAGING_DB_CONTAINER,
    evaluate_guardrails,
)


def healthy_inspect(name=PRODUCTION_DB_CONTAINER):
    return {
        "Name": "/" + name,
        "State": {
            "Running": True,
            "Status": "running",
            "Health": {
                "Status": "healthy",
            },
        },
    }


def test_valid_guard():
    result = evaluate_guardrails(
        branch=REQUIRED_BRANCH,
        container=PRODUCTION_DB_CONTAINER,
        inspect_data=healthy_inspect(),
    )

    assert result["guard_ok"] is True
    assert result["production_write_performed"] is False
    assert result["db_container"] == PRODUCTION_DB_CONTAINER
    assert (
        result["staging_db_container"]
        == STAGING_DB_CONTAINER
    )


def assert_rejected(
    *,
    branch=REQUIRED_BRANCH,
    container=PRODUCTION_DB_CONTAINER,
    inspect_data=None,
):
    if inspect_data is None:
        inspect_data = healthy_inspect()

    result = evaluate_guardrails(
        branch=branch,
        container=container,
        inspect_data=inspect_data,
    )

    assert result["guard_ok"] is False
    assert result["errors"]


def test_branch_lock():
    assert_rejected(
        branch="staging",
    )

    assert_rejected(
        branch="feature/test",
    )


def test_staging_db_rejected():
    assert_rejected(
        container=STAGING_DB_CONTAINER,
        inspect_data=healthy_inspect(
            STAGING_DB_CONTAINER
        ),
    )


def test_arbitrary_db_rejected():
    assert_rejected(
        container="some-other-postgres",
        inspect_data=healthy_inspect(
            "some-other-postgres"
        ),
    )


def test_inspected_name_must_match():
    assert_rejected(
        inspect_data=healthy_inspect(
            "wrong-container"
        ),
    )


def test_container_must_be_running():
    inspect_data = healthy_inspect()
    inspect_data["State"]["Running"] = False
    inspect_data["State"]["Status"] = "exited"

    assert_rejected(
        inspect_data=inspect_data,
    )


def test_unhealthy_container_rejected():
    inspect_data = healthy_inspect()
    inspect_data["State"]["Health"]["Status"] = "unhealthy"

    assert_rejected(
        inspect_data=inspect_data,
    )


def test_no_healthcheck_is_allowed():
    inspect_data = healthy_inspect()
    inspect_data["State"].pop("Health")

    result = evaluate_guardrails(
        branch=REQUIRED_BRANCH,
        container=PRODUCTION_DB_CONTAINER,
        inspect_data=inspect_data,
    )

    assert result["guard_ok"] is True
    assert result["health"] is None


def main():
    test_valid_guard()
    test_branch_lock()
    test_staging_db_rejected()
    test_arbitrary_db_rejected()
    test_inspected_name_must_match()
    test_container_must_be_running()
    test_unhealthy_container_rejected()
    test_no_healthcheck_is_allowed()

    print("Production promotion guard v1 contract test PASS")
    print("Main branch lock: PASS")
    print("Fixed Production DB lock: PASS")
    print("Staging DB rejection: PASS")
    print("Arbitrary DB rejection: PASS")
    print("Docker identity check: PASS")
    print("Container running/health check: PASS")
    print("Database write performed: False")


if __name__ == "__main__":
    main()
