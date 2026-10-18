import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

HERMES_DIR = Path(
    "/data/coolify/services/"
    "rgu4flce2juuzyq6idzr49z2/.hermes"
)

ENV_FILE = HERMES_DIR / ".env"
CONFIG_FILE = HERMES_DIR / "config.yaml"


def load_env_file(path):
    values = {}

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        values[key] = value

    return values


def read_default_model(path):
    lines = path.read_text().splitlines()

    in_top_model_block = False

    for line in lines:

        # top-level model:
        if line == "model:":
            in_top_model_block = True
            continue

        if in_top_model_block:

            # next top-level block
            if line and not line.startswith((" ", "\t")):
                break

            match = re.match(
                r"^\s+default:\s*(.+?)\s*$",
                line
            )

            if match:
                value = match.group(1).strip()
                return value.strip("'\"")

    return "deepseek-flash"


env = load_env_file(ENV_FILE)

API_KEY = env.get("DEEPSEEK_API_KEY")

BASE_URL = (
    env.get("DEEPSEEK_BASE_URL")
    or "https://api.deepseek.com"
).rstrip("/")

MODEL = read_default_model(CONFIG_FILE)


if not API_KEY:
    raise SystemExit(
        "DEEPSEEK_API_KEY was not found in Hermes .env"
    )


SYSTEM_PROMPT = """
You are a retrieval query normalizer for a professional knowledge base.

Your job is NOT to answer the user's question.

Convert the user's question into structured JSON for retrieval.

Return JSON with exactly these keys:

{
  "english_query": "concise professional English retrieval query",
  "technical_terms": [
    "high precision English technical phrase"
  ],
  "references": [
    "explicit section/document reference"
  ],
  "domain": "domain-name"
}

Rules:

1. english_query
- Translate Chinese or Cantonese into professional English terminology.
- Preserve the user's actual meaning.
- Preserve explicit section numbers, document codes and technical identifiers.
- Make it suitable for semantic retrieval.

2. technical_terms
- Return 0 to 6 precise English technical terms or phrases.
- Prefer phrases likely to appear in professional source documents.
- Avoid generic words such as "building", "problem", "effect".
- You may infer a standard technical term when the user's wording
  clearly describes that concept.
- Example: concrete cover separating before falling away may suggest
  "concrete delamination".

3. references
- Include ONLY references explicitly stated by the user.
- Do NOT invent statutory sections, codes, PNAP numbers, APP numbers,
  standards or document references.
- Normalize obvious section notation.
- Example:
  "Section 16(3A)" -> "16(3A)"
- If no explicit reference exists, return [].

4. domain
Choose the most suitable concise domain such as:
- building-surveying
- building-control
- concrete-repair
- fire-safety
- contract-administration
- dilapidations
- investment
- business
- general

5. Output valid JSON only.
6. Do not provide explanations.
7. Do not answer the underlying question.

Example input:
石屎未爆落，但保護層已經同底層分離，這種缺陷叫甚麼？

Example JSON output:
{
  "english_query":
    "concrete cover separation from underlying concrete before visible spalling",
  "technical_terms": [
    "concrete delamination",
    "separation"
  ],
  "references": [],
  "domain": "concrete-repair"
}
""".strip()


def call_deepseek(query):

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": query
            }
        ],
        "response_format": {
            "type": "json_object"
        },
        "thinking": {
            "type": "disabled"
        },
        "reasoning_effort": "none",
        "max_tokens": 350,
        "stream": False
    }

    request = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        body = json.loads(
            response.read().decode("utf-8")
        )

    content = body["choices"][0]["message"]["content"]

    if not content:
        raise RuntimeError(
            "DeepSeek returned empty content"
        )

    result = json.loads(content)

    return result


INTENT_ONLY_TECHNICAL_TERMS = {
    "definition",
}


GENERIC_DEFINITION_MODIFIERS = {
    "statutory",
    "legal",
    "technical",
    "formal",
}


def strip_wrapping_quotes(value):

    value = value.strip()

    quote_pairs = (
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
    )

    while len(value) >= 2:

        matched = False

        for left, right in quote_pairs:

            if (
                value.startswith(left)
                and value.endswith(right)
            ):
                value = value[
                    len(left):
                    len(value) - len(right)
                ].strip()

                matched = True
                break

        if not matched:
            break

    return value


def normalize_technical_term(value):

    term = " ".join(
        str(value).strip().split()
    )

    if not term:
        return None

    key = term.casefold()

    if key in INTENT_ONLY_TECHNICAL_TERMS:
        return None

    # "definition of works"
    match = re.match(
        r"^definition\s+of\s+(.+)$",
        term,
        flags=re.IGNORECASE,
    )

    if match:

        subject = strip_wrapping_quotes(
            match.group(1)
        )

        if subject:
            term = subject

    else:

        # "works definition"
        # "\"works\" definition"
        match = re.match(
            r"^(.+?)\s+definition$",
            term,
            flags=re.IGNORECASE,
        )

        if match:

            subject = strip_wrapping_quotes(
                match.group(1)
            )

            if (
                subject.casefold()
                in GENERIC_DEFINITION_MODIFIERS
            ):
                return None

            if subject:
                term = subject

    term = strip_wrapping_quotes(
        term
    )

    if not term:
        return None

    return term


def sanitize_technical_terms(values):

    output = []
    seen = set()

    for value in values:

        term = normalize_technical_term(
            value
        )

        if not term:
            continue

        key = term.casefold()

        if key in seen:
            continue

        seen.add(key)
        output.append(term)

        if len(output) >= 6:
            break

    return output


def extract_explicit_subject(query):

    text = " ".join(
        str(query).strip().split()
    )

    patterns = (
        r"^what\s+does\s+(.+?)\s+mean(?:\s+under\b|\s+in\b|\?|$)",
        r"^what\s+is\s+the\s+definition\s+of\s+(.+?)(?:\s+under\b|\s+in\b|\?|$)",
        r"^define\s+(.+?)(?:\s+under\b|\s+in\b|\?|$)",
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        subject = strip_wrapping_quotes(
            match.group(1).strip(
                " ?"
            )
        )

        if (
            subject
            and len(subject) <= 120
        ):
            return subject

    return None


def apply_explicit_subject_lock(
    query,
    result,
):

    subject = extract_explicit_subject(
        query
    )

    if not subject:
        return result

    terms = sanitize_technical_terms(
        [
            subject,
        ]
    )

    if not terms:
        return result

    result[
        "technical_terms"
    ] = terms

    return result


def validate(result):

    required = {
        "english_query",
        "technical_terms",
        "references",
        "domain"
    }

    if set(result.keys()) != required:
        raise ValueError(
            f"Unexpected JSON keys: {result.keys()}"
        )

    if not isinstance(
        result["english_query"],
        str
    ):
        raise ValueError("english_query must be string")

    if not isinstance(
        result["technical_terms"],
        list
    ):
        raise ValueError("technical_terms must be list")

    if not isinstance(
        result["references"],
        list
    ):
        raise ValueError("references must be list")

    if not isinstance(
        result["domain"],
        str
    ):
        raise ValueError("domain must be string")

    result["technical_terms"] = (
        sanitize_technical_terms(
            result["technical_terms"]
        )
    )

    result["references"] = [
        str(x).strip()
        for x in result["references"][:8]
        if str(x).strip()
    ]

    return result


def normalize(query):

    last_error = None

    # JSON mode can occasionally return empty output,
    # so allow one retry.
    for attempt in range(2):

        try:
            result = validate(
                call_deepseek(query)
            )

            return apply_explicit_subject_lock(
                query,
                result,
            )

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"Query normalization failed: {last_error}"
    )


if __name__ == "__main__":

    if len(sys.argv) < 2:
        raise SystemExit(
            'Usage: python3 query_normalizer.py "question"'
        )

    query = " ".join(sys.argv[1:])

    result = normalize(query)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        )
    )
