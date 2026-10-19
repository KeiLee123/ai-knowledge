#!/usr/bin/env python3

import sync_anki_reviews_v1 as sync


def test_empty_primary_falls_back() -> None:
    calls = []

    def fake_invoke(
        action,
        params,
        endpoint,
        api_key,
    ):
        calls.append(action)

        if action == "getReviewsOfCards":
            return {
                "101": [],
                "102": [],
            }

        if action == "cardReviews":
            return [
                [
                    1001,
                    101,
                    0,
                    3,
                    -600,
                    0,
                    2500,
                    1200,
                    0,
                ],
                [
                    1002,
                    102,
                    0,
                    2,
                    -600,
                    0,
                    2500,
                    900,
                    0,
                ],
            ]

        raise AssertionError(
            f"unexpected action: {action}"
        )

    original = sync.invoke
    sync.invoke = fake_invoke

    try:
        result = sync.get_reviews(
            [101, 102],
            "Deck",
            sync.DEFAULT_ENDPOINT,
            None,
        )

    finally:
        sync.invoke = original

    assert calls == [
        "getReviewsOfCards",
        "cardReviews",
    ]

    assert result["101"][0]["ease"] == 3
    assert result["102"][0]["ease"] == 2


def test_nonempty_primary_does_not_fallback() -> None:
    calls = []

    def fake_invoke(
        action,
        params,
        endpoint,
        api_key,
    ):
        calls.append(action)

        if action == "getReviewsOfCards":
            return {
                "101": [
                    {
                        "id": 2001,
                        "ease": 3,
                    }
                ]
            }

        raise AssertionError(
            f"unexpected action: {action}"
        )

    original = sync.invoke
    sync.invoke = fake_invoke

    try:
        result = sync.get_reviews(
            [101],
            "Deck",
            sync.DEFAULT_ENDPOINT,
            None,
        )

    finally:
        sync.invoke = original

    assert calls == [
        "getReviewsOfCards",
    ]

    assert result["101"][0]["ease"] == 3


def test_true_empty_history_stays_empty() -> None:
    calls = []

    def fake_invoke(
        action,
        params,
        endpoint,
        api_key,
    ):
        calls.append(action)

        if action == "getReviewsOfCards":
            return {
                "101": [],
            }

        if action == "cardReviews":
            return []

        raise AssertionError(
            f"unexpected action: {action}"
        )

    original = sync.invoke
    sync.invoke = fake_invoke

    try:
        result = sync.get_reviews(
            [101],
            "Deck",
            sync.DEFAULT_ENDPOINT,
            None,
        )

    finally:
        sync.invoke = original

    assert calls == [
        "getReviewsOfCards",
        "cardReviews",
    ]

    assert result == {
        "101": [],
    }


def main() -> None:
    test_empty_primary_falls_back()
    test_nonempty_primary_does_not_fallback()
    test_true_empty_history_stays_empty()

    print(
        "SR-G regression test PASS"
    )
    print(
        "Empty primary response fallback: PASS"
    )
    print(
        "Non-empty primary response: PASS"
    )
    print(
        "True empty history: PASS"
    )


if __name__ == "__main__":
    main()
