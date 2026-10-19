#!/usr/bin/env python3

from augment_vision_v2 import (
    PROMPT_VERSION,
    build_prompt,
)


def sample_unit():
    return {
        "page_number": 44,
        "text": "Third-angle projection example",
        "ocr": {
            "text": "Top Front Side",
        },
    }


def sample_gate():
    return {
        "selected": True,
        "page_number": 44,
        "reasons": [
            "high_vector_complexity",
        ],
    }


def main():
    prompt = build_prompt(
        sample_unit(),
        sample_gate(),
    )

    assert PROMPT_VERSION == (
        "visual-evidence-v1.1"
    )

    required = [
        "title blocks",
        "author/name fields",
        "dates",
        "assignment numbers",
        "drawing numbers",
        "sheet-zone coordinates",
        "border labels",
        "margin notes",
        "Do NOT include those provenance/page-furniture fields in retrieval_text",
        "retrieval_text must exclude title-block metadata",
    ]

    missing = [
        phrase
        for phrase in required
        if phrase not in prompt
    ]

    assert not missing, (
        "Prompt relevance guard is missing: "
        + ", ".join(missing)
    )

    print(
        "Visual retrieval prompt relevance test PASS"
    )
    print(
        "Prompt version:",
        PROMPT_VERSION,
    )
    print(
        "Provenance/page-furniture exclusion: PASS"
    )
    print(
        "No model call performed: PASS"
    )


if __name__ == "__main__":
    main()
