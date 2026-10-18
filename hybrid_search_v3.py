import argparse
import json
import re
import subprocess
import urllib.request
import yaml
from pathlib import Path
from collections import defaultdict

DB_CONTAINER = "ai-knowledge-db-jiyckdrlappwgimwebnzxwmr"
EMBED_URL = "http://127.0.0.1:8088/embed"

LEGISLATION_REGISTRY = Path(
    "/opt/ai-knowledge/legislation_registry.yaml"
)

parser = argparse.ArgumentParser()

parser.add_argument("--query", required=True)
parser.add_argument("--english-query", required=True)

parser.add_argument(
    "--terms",
    default="",
    help="Comma-separated English technical terms"
)

parser.add_argument(
    "--refs",
    default="",
    help="Comma-separated exact references, e.g. s.16(3A),APP-19"
)

parser.add_argument(
    "--document-title",
    default="",
    help="Optional document scope"
)

parser.add_argument("--limit", type=int, default=5)

parser.add_argument(
    "--include-synthetic",
    action="store_true",
    help="Include synthetic / POC documents"
)

parser.add_argument(
    "--json-output",
    action="store_true",
    help="Return retrieval results as JSON"
)

args = parser.parse_args()

terms = [
    x.strip().lower()
    for x in args.terms.split(",")
    if x.strip()
]

raw_refs = [
    x.strip()
    for x in args.refs.split(",")
    if x.strip()
]


def normalize_ref_candidate(value):

    return " ".join(
        (value or "")
        .strip()
        .split()
    )


def parse_chapter_reference(value):

    ref = normalize_ref_candidate(
        value
    )

    m = re.fullmatch(
        r"(?i)^cap(?:\.|\s|_)*(?P<chapter>\d+[a-z]*)$",
        ref,
    )

    if not m:
        return None

    return (
        "CAP_"
        + m.group("chapter").upper()
    )


def parse_qualified_legal_reference(value):

    ref = normalize_ref_candidate(
        value
    )

    m = re.fullmatch(
        r"(?i)^cap(?:\.|\s|_)*(?P<chapter>\d+[a-z]*)\s+(?:s(?:ection)?\.?\s*)?(?P<section>\d+[a-z]*(?:\([0-9a-z]+\))*)$",
        ref,
    )

    if not m:
        return None

    return {
        "legislation_id":
            "CAP_" + m.group(
                "chapter"
            ).upper(),

        "section_number":
            m.group(
                "section"
            )
    }


def is_exact_reference(value):

    ref = normalize_ref_candidate(
        value
    )

    if not ref:
        return False

    if parse_qualified_legal_reference(
        ref
    ):
        return True

    # Main-body statutory provisions:
    # 16, 16A, 16(3A), 16(3)(d),
    # s.16(3A), section 16(3A)
    if re.fullmatch(
        r'''(?ix)
        (?:
            s(?:ection)?\.?\s*
        )?
        \d+[A-Z]*
        (?:
            \(
                [0-9A-Z]+
            \)
        )*
        ''',
        ref
    ):
        return True

    # Schedule references:
    # Sch.7 s.16
    # Sch.5 Pt.5 s.1
    # Schedule Pt.2 s.1
    # Sch.3 para.(1)
    if re.fullmatch(
        r'''(?ix)
        sch(?:edule)?\.?
        \s*
        (?:\d+)?
        (?:
            \s+
            pt\.?\s*\d+
        )?
        \s+
        (?:
            s(?:ection)?\.?\s*
            \d+[A-Z]*
            (?:
                \(
                    [0-9A-Z]+
                \)
            )*
            |
            para(?:graph)?\.?\s*
            \(
                [0-9A-Z]+
            \)
        )
        ''',
        ref
    ):
        return True

    # Ordinance chapter references:
    # Cap.123, Cap 123, CAP_123
    if re.fullmatch(
        r'''(?ix)
        cap
        (?:\.|\s|_)*
        \d+[A-Z]*
        ''',
        ref
    ):
        return True

    # APP / PNAP code-like references:
    # APP-1, APP-001, PNAP APP-19
    if re.fullmatch(
        r'''(?ix)
        (?:
            PNAP[\s_-]*
        )?
        APP[\s_-]*
        \d+[A-Z]*
        ''',
        ref
    ):
        return True

    return False


def extract_explicit_legal_references(text):

    text = text or ""

    found = []
    qualified_chapters = set()

    # --------------------------------------------------------
    # First harvest document-qualified provisions.
    #
    # Examples:
    #   Cap.123 Section 1(2)
    #   Cap 121 s.2(2)
    #   CAP_572 5(1)
    # --------------------------------------------------------

    qualified_pattern = re.compile(
        r"(?i)\bcap(?:\.|\s|_)*(?P<chapter>\d+[a-z]*)\s+(?:s(?:ection)?\.?\s*)?(?P<section>\d+[a-z]*(?:\([0-9a-z]+\))*)"
    )

    for match in qualified_pattern.finditer(
        text
    ):

        chapter = (
            match.group("chapter")
            .upper()
        )

        section = (
            match.group("section")
        )

        found.append(
            f"Cap.{chapter} Section {section}"
        )

        qualified_chapters.add(
            chapter
        )

    # --------------------------------------------------------
    # Then harvest chapter-only references.
    #
    # Do not add Cap.123 separately if the same query already
    # contains Cap.123 Section 1(2), otherwise whole-document
    # retrieval could crowd out the more precise reference.
    # --------------------------------------------------------

    chapter_pattern = re.compile(
        r"(?i)\bcap(?:\.|\s|_)*(?P<chapter>\d+[a-z]*)\b"
    )

    for match in chapter_pattern.finditer(
        text
    ):

        chapter = (
            match.group("chapter")
            .upper()
        )

        if chapter in qualified_chapters:
            continue

        found.append(
            f"Cap.{chapter}"
        )

    return found


deterministic_refs = (
    extract_explicit_legal_references(
        args.query
    )
)

candidate_refs = (
    raw_refs
    + deterministic_refs
)

refs = []
seen_refs = set()

for ref in candidate_refs:

    if not is_exact_reference(
        ref
    ):
        continue

    key = (
        normalize_ref_candidate(
            ref
        ).lower()
    )

    if key in seen_refs:
        continue

    seen_refs.add(
        key
    )

    refs.append(
        normalize_ref_candidate(
            ref
        )
    )


# ------------------------------------------------------------
# Reference classification
#
# Stronger references suppress weaker duplicates.
#
# Example:
#
#   Cap.123 Section 1(2)
#   1(2)
#   Cap.123
#   Cap.121
#
# becomes:
#
#   exact_refs:
#       Cap.123 Section 1(2)
#
#   document_scope_refs:
#       CAP_121
# ------------------------------------------------------------

exact_refs = []
document_scope_refs = []

seen_exact_refs = set()
seen_document_scopes = set()

qualified_chapters = set()
qualified_sections = set()

# ------------------------------------------------------------
# Pass 1:
# collect document-qualified legal references first.
# ------------------------------------------------------------

for ref in refs:

    qualified = (
        parse_qualified_legal_reference(
            ref
        )
    )

    if not qualified:
        continue

    normalized = (
        normalize_ref_candidate(
            ref
        )
    )

    key = normalized.lower()

    if key not in seen_exact_refs:

        seen_exact_refs.add(
            key
        )

        exact_refs.append(
            normalized
        )

    qualified_chapters.add(
        qualified[
            "legislation_id"
        ].lower()
    )

    qualified_sections.add(
        qualified[
            "section_number"
        ].lower()
    )


# ------------------------------------------------------------
# Pass 2:
# classify remaining references.
# ------------------------------------------------------------

for ref in refs:

    if parse_qualified_legal_reference(
        ref
    ):
        continue

    chapter_ref = (
        parse_chapter_reference(
            ref
        )
    )

    if chapter_ref:

        chapter_key = (
            chapter_ref.lower()
        )

        # Example:
        #
        # Cap.123 Section 1(2)
        # + Cap.123
        #
        # Do not add CAP_123 as a semantic document scope.
        if (
            chapter_key
            in qualified_chapters
        ):
            continue

        if (
            chapter_key
            not in seen_document_scopes
        ):

            seen_document_scopes.add(
                chapter_key
            )

            document_scope_refs.append(
                chapter_ref
            )

        continue

    normalized = (
        normalize_ref_candidate(
            ref
        )
    )

    key = normalized.lower()

    # Example:
    #
    # Cap.123 Section 1(2)
    # + 1(2)
    #
    # Suppress the unqualified duplicate so it cannot
    # match section 1(2) in unrelated legislation.
    if key in qualified_sections:
        continue

    if key in seen_exact_refs:
        continue

    seen_exact_refs.add(
        key
    )

    exact_refs.append(
        normalized
    )


# ------------------------------------------------------------
# Retrieval terms
#
# Chapter references are scope metadata, not lexical search
# terms. Keeping "Cap.572" in PHRASE / FTS would match the
# standard prefix of almost every semantic chunk in that law.
# ------------------------------------------------------------

filtered_terms = []

for term in terms:

    normalized_term = (
        normalize_ref_candidate(
            term
        )
    )

    if parse_chapter_reference(
        normalized_term
    ):
        continue

    if parse_qualified_legal_reference(
        normalized_term
    ):
        continue

    filtered_terms.append(
        term
    )

terms = filtered_terms


def expand_registry_authority_terms(
    current_terms,
    scope_refs
):

    if not scope_refs:
        return current_terms

    if not LEGISLATION_REGISTRY.exists():
        return current_terms

    with LEGISLATION_REGISTRY.open(
        "r",
        encoding="utf-8"
    ) as f:

        registry = yaml.safe_load(
            f
        )

    laws = registry.get(
        "legislation",
        {}
    )

    authorities = registry.get(
        "authorities",
        {}
    )

    query_text = " ".join([
        args.query,
        args.english_query,
        " ".join(current_terms),
    ]).lower()

    expanded = list(
        current_terms
    )

    seen = {
        x.strip().lower()
        for x in expanded
        if x.strip()
    }

    def add_term(value):

        value = (
            (value or "")
            .replace("-", " ")
            .strip()
            .lower()
        )

        value = " ".join(
            value.split()
        )

        if (
            not value
            or value in seen
        ):
            return

        seen.add(
            value
        )

        expanded.append(
            value
        )

    for cap_key in scope_refs:

        law_cfg = laws.get(
            cap_key,
            {}
        )

        links = (
            law_cfg.get(
                "responsible_authorities",
                []
            )
            or []
        )

        for link in links:

            code = (
                link.get(
                    "authority_code"
                )
                or ""
            )

            authority_cfg = (
                authorities.get(
                    code,
                    {}
                )
            )

            authority_name = (
                authority_cfg.get(
                    "name"
                )
                or ""
            )

            statutory_officer = (
                link.get(
                    "statutory_officer"
                )
                or ""
            )

            role = (
                link.get(
                    "role"
                )
                or ""
            )

            mentioned = False

            if (
                authority_name
                and authority_name.lower()
                in query_text
            ):
                mentioned = True

            if (
                statutory_officer
                and statutory_officer.lower()
                in query_text
            ):
                mentioned = True

            if code:

                code_pattern = (
                    r"(?<![a-z0-9])"
                    + re.escape(
                        code.lower()
                    )
                    + r"(?![a-z0-9])"
                )

                if re.search(
                    code_pattern,
                    query_text
                ):
                    mentioned = True

            if not mentioned:
                continue

            # Preserve the entity itself and expand to the
            # statutory officer and statutory role recorded
            # in the legislation registry.
            add_term(
                authority_name
            )

            add_term(
                statutory_officer
            )

            add_term(
                role
            )

    return expanded


terms = expand_registry_authority_terms(
    terms,
    document_scope_refs
)


def expand_legal_intent_terms(
    current_terms
):

    expanded = list(
        current_terms
    )

    seen = {
        x.strip().lower()
        for x in expanded
        if x.strip()
    }

    def add_term(value):

        value = " ".join(
            (value or "")
            .strip()
            .lower()
            .split()
        )

        if (
            not value
            or value in seen
        ):
            return

        seen.add(
            value
        )

        expanded.append(
            value
        )

    query_text = " ".join([
        args.query,
        args.english_query,
    ]).lower()

    # --------------------------------------------------------
    # Applicability / scope intent
    #
    # Do not use the generic word "application" as a trigger,
    # because legislation also contains procedural
    # applications to courts / authorities.
    #
    # Examples:
    #   適用於咩建築物
    #   what buildings does this apply to
    #   which buildings are covered by the Ordinance
    # --------------------------------------------------------

    applicability_markers = [
        "適用",
        "apply to",
        "applies to",
        "applicable to",
        "covered by",
        "coverage of",
        "scope of applicability",
    ]

    if any(
        marker in query_text
        for marker
        in applicability_markers
    ):

        add_term(
            "applies to"
        )

        add_term(
            "application of ordinance"
        )

    return expanded


terms = expand_legal_intent_terms(
    terms
)


def sql_quote(value):
    return value.replace("'", "''")


def run_sql(sql):
    output = subprocess.check_output([
        "docker", "exec", "-i", DB_CONTAINER,
        "psql",
        "-U", "ai_knowledge",
        "-d", "ai_knowledge",
        "-At",
        "-F", "\t",
        "-v", "ON_ERROR_STOP=1",
        "-c", sql
    ], text=True)

    return [
        line
        for line in output.splitlines()
        if line.strip()
    ]


def document_scope(
    alias="d",
    include_reference_scope=True
):

    conditions = []

    if not args.include_synthetic:

        conditions.append(
            f"COALESCE("
            f"({alias}.metadata->>'synthetic')::boolean, "
            f"false"
            f") = false"
        )

    if args.document_title:

        title = sql_quote(
            args.document_title
        )

        conditions.append(
            f"{alias}.title = '{title}'"
        )

    # --------------------------------------------------------
    # Chapter-only references act as document scopes.
    #
    # Example:
    #   Cap.572 + natural-language question
    #
    # Semantic / lexical retrieval is constrained to CAP_572.
    # Exact provision retrieval deliberately disables this
    # scope so mixed cross-law queries still work.
    # --------------------------------------------------------

    if (
        include_reference_scope
        and document_scope_refs
    ):

        scope_parts = []

        for legislation_id in (
            document_scope_refs
        ):

            q = sql_quote(
                legislation_id.lower()
            )

            scope_parts.append(
                f"""
                (
                    LOWER(
                        COALESCE(
                            {alias}.metadata
                                ->> 'legislation_id',
                            ''
                        )
                    ) = '{q}'

                    OR LOWER(
                        COALESCE(
                            {alias}.source_file_id,
                            ''
                        )
                    ) LIKE
                        'hkel:{q}:%'
                )
                """
            )

        conditions.append(
            "("
            + " OR ".join(
                scope_parts
            )
            + ")"
        )

    if not conditions:
        return ""

    return (
        "\n        AND "
        + "\n        AND ".join(
            conditions
        )
    )


def embed(text):
    payload = json.dumps(
        {"inputs": "query: " + text},
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request) as response:
        vector = json.loads(
            response.read().decode("utf-8")
        )[0]

    if len(vector) != 384:
        raise RuntimeError(
            f"Expected 384 dimensions, got {len(vector)}"
        )

    return vector


def vector_search(query, limit=20):

    vector = embed(query)

    vector_literal = (
        "[" + ",".join(str(x) for x in vector) + "]"
    )

    sql = f"""
    SELECT
        c.id,
        COALESCE(NULLIF(c.metadata->>'topic',''), d.topic, ''),
        COALESCE(d.title,''),
        COALESCE(s.section_number,''),
        COALESCE(s.heading,''),
        ROUND(
            (
                1 -
                (
                    (e.embedding::vector(384))
                    <=>
                    ('{vector_literal}'::vector(384))
                )
            )::numeric,
            6
        ),
        REPLACE(REPLACE(c.content, E'\\t', ' '), E'\\n', ' ')
    FROM embeddings e
    JOIN chunks c
        ON c.id = e.chunk_id
    JOIN documents d
        ON d.id = c.document_id
    LEFT JOIN sections s
        ON s.id = c.section_id
    WHERE
        e.provider = 'local'
        AND e.model = 'multilingual-e5-small'
        AND COALESCE(
            c.metadata->>'retrieval_role',
            'legacy'
        ) <> 'legal-exact'
        {document_scope("d")}
    ORDER BY
        (e.embedding::vector(384))
        <=>
        ('{vector_literal}'::vector(384))
    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):

        parts = line.split("\t", 6)

        rows.append({
            "id": int(parts[0]),
            "topic": parts[1],
            "document": parts[2],
            "section_number": parts[3],
            "heading": parts[4],
            "similarity": float(parts[5]),
            "content": parts[6]
        })

    return rows


def technical_phrase_search(limit=20):

    if not terms:
        return []

    score_parts = []
    where_parts = []

    for term in terms:

        quoted = sql_quote(term)

        # Multi-word phrases receive slightly more weight.
        word_count = len(term.split())
        term_weight = 1.0 + ((word_count - 1) * 0.5)

        score_parts.append(
            f"""
            CASE
                WHEN POSITION(
                    '{quoted}' IN LOWER(c.content)
                ) > 0
                THEN {term_weight}
                ELSE 0
            END
            """
        )

        where_parts.append(
            f"""
            POSITION(
                '{quoted}' IN LOWER(c.content)
            ) > 0
            """
        )

    score_expression = " + ".join(score_parts)
    where_expression = " OR ".join(where_parts)

    sql = f"""
    SELECT
        c.id,
        COALESCE(NULLIF(c.metadata->>'topic',''), d.topic, ''),
        COALESCE(d.title,''),
        COALESCE(s.section_number,''),
        COALESCE(s.heading,''),
        ({score_expression})::numeric AS phrase_score,
        REPLACE(REPLACE(c.content, E'\\t', ' '), E'\\n', ' ')
    FROM chunks c
    JOIN documents d
        ON d.id = c.document_id
    LEFT JOIN sections s
        ON s.id = c.section_id
    WHERE
        ({where_expression})
        AND COALESCE(
            c.metadata->>'retrieval_role',
            'legacy'
        ) <> 'legal-exact'
        {document_scope("d")}
    ORDER BY
        phrase_score DESC,
        c.id
    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):

        parts = line.split("\t", 6)

        rows.append({
            "id": int(parts[0]),
            "topic": parts[1],
            "document": parts[2],
            "section_number": parts[3],
            "heading": parts[4],
            "phrase_score": float(parts[5]),
            "content": parts[6]
        })

    return rows


def fts_search(limit=20):

    if not terms:
        return []

    web_terms = []

    for term in terms:

        # Phrase searches for multi-word technical expressions.
        if " " in term:
            web_terms.append(f'"{term}"')
        else:
            web_terms.append(term)

    web_query = " OR ".join(web_terms)
    web_query = sql_quote(web_query)

    sql = f"""
    SELECT
        c.id,
        COALESCE(NULLIF(c.metadata->>'topic',''), d.topic, ''),
        COALESCE(d.title,''),
        COALESCE(s.section_number,''),
        COALESCE(s.heading,''),
        ROUND(
            ts_rank_cd(
                c.search_vector,
                websearch_to_tsquery(
                    'simple',
                    '{web_query}'
                )
            )::numeric,
            6
        ),
        REPLACE(REPLACE(c.content, E'\\t', ' '), E'\\n', ' ')
    FROM chunks c
    JOIN documents d
        ON d.id = c.document_id
    LEFT JOIN sections s
        ON s.id = c.section_id
    WHERE
        c.search_vector @@
        websearch_to_tsquery(
            'simple',
            '{web_query}'
        )
        AND COALESCE(
            c.metadata->>'retrieval_role',
            'legacy'
        ) <> 'legal-exact'
        {document_scope("d")}
    ORDER BY
        ts_rank_cd(
            c.search_vector,
            websearch_to_tsquery(
                'simple',
                '{web_query}'
            )
        ) DESC
    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):

        parts = line.split("\t", 6)

        rows.append({
            "id": int(parts[0]),
            "topic": parts[1],
            "document": parts[2],
            "section_number": parts[3],
            "heading": parts[4],
            "fts_score": float(parts[5]),
            "content": parts[6]
        })

    return rows



def definition_query_intent():

    q = (
        f"{args.query} "
        f"{args.english_query}"
    ).lower()

    # Strong English definition patterns.
    if "definition of" in q:
        return True

    if q.strip().startswith(
        "define "
    ):
        return True

    if (
        "what does" in q
        and " mean" in q
    ):
        return True

    if (
        "what is the meaning of" in q
        or "meaning of" in q
    ):
        return True

    # Chinese / Cantonese definition patterns.
    for marker in [
        "定義",
        "意思",
        "咩意思",
        "乜意思",
        "是什麼",
        "是甚麼",
        "係咩意思",
        "係乜意思",
        "什麼是",
        "甚麼是",
    ]:
        if marker in q:
            return True

    return False


def definition_candidates():

    ignored = {
        "buildingsordinance",
        "buildingordinance",
        "buildingcontrol",
        "definition",
        "meaning",
    }

    candidates = []

    for term in terms:

        raw = (
            term
            .strip()
            .lower()
        )

        normalized = "".join(
            ch
            for ch in raw
            if ch.isalnum()
        )

        if (
            len(normalized) < 3
            or normalized in ignored
        ):
            continue

        candidates.append(
            (
                raw,
                normalized
            )
        )

    # Preserve order while removing duplicates.
    seen = set()
    output = []

    for item in candidates:

        if item[1] in seen:
            continue

        seen.add(
            item[1]
        )

        output.append(
            item
        )

    return output


def definition_search(limit=20):

    # Exact provision mode must remain deterministic.
    if exact_refs:
        return []

    candidates = (
        definition_candidates()
    )

    if not candidates:
        return []

    definition_intent = (
        definition_query_intent()
    )

    conditions = []
    priority_cases = []

    for raw, normalized in candidates:

        raw_q = sql_quote(
            raw
        )

        normalized_q = sql_quote(
            normalized
        )

        normalized_name = """
        regexp_replace(
            LOWER(
                COALESCE(
                    c.metadata
                    ->> 'definition_name',
                    ''
                )
            ),
            '[^a-z0-9]+',
            '',
            'g'
        )
        """

        # ----------------------------------------------------
        # Explicit definition question:
        #
        # allow both exact definition-name matches and
        # definition-content matches.
        # ----------------------------------------------------

        if definition_intent:

            conditions.append(
                f"""
                (
                    {normalized_name}
                        = '{normalized_q}'

                    OR POSITION(
                        '{raw_q}'
                        IN LOWER(c.content)
                    ) > 0
                )
                """
            )

            priority_cases.append(
                f"""
                CASE
                    WHEN {normalized_name}
                        = '{normalized_q}'
                        THEN 1

                    WHEN POSITION(
                        '{raw_q}'
                        IN LOWER(c.content)
                    ) > 0
                        THEN 2

                    ELSE 99
                END
                """
            )

        # ----------------------------------------------------
        # Non-definition question:
        #
        # use definitions only as precise semantic anchors.
        # Do NOT broadly search definition content, otherwise
        # generic terms would pull unrelated definitions.
        #
        # Example:
        #   "enforcement authority 分別負責邊方面"
        #       -> EnforcementAuthority definition
        # ----------------------------------------------------

        else:

            conditions.append(
                f"""
                (
                    {normalized_name}
                        = '{normalized_q}'
                )
                """
            )

            priority_cases.append(
                f"""
                CASE
                    WHEN {normalized_name}
                        = '{normalized_q}'
                        THEN 1

                    ELSE 99
                END
                """
            )

    where_expression = (
        " OR ".join(
            conditions
        )
    )

    priority = (
        "LEAST("
        + ",".join(
            priority_cases
        )
        + ")"
    )

    sql = f"""
    SELECT
        c.id,
        COALESCE(
            NULLIF(
                c.metadata->>'topic',
                ''
            ),
            d.topic,
            ''
        ),
        COALESCE(
            d.title,
            ''
        ),
        COALESCE(
            s.section_number,
            ''
        ),
        COALESCE(
            NULLIF(
                s.heading,
                ''
            ),
            'Definition: '
            || COALESCE(
                c.metadata
                ->> 'definition_name',
                ''
            )
        ),
        REPLACE(
            REPLACE(
                c.content,
                E'\\t',
                ' '
            ),
            E'\\n',
            ' '
        )
    FROM chunks c
    JOIN documents d
        ON d.id = c.document_id
    LEFT JOIN sections s
        ON s.id = c.section_id
    WHERE
        c.metadata
            ->> 'semantic_type'
            = 'definition'

        AND COALESCE(
            c.metadata
                ->> 'retrieval_role',
            'legacy'
        ) <> 'legal-exact'

        AND (
            {where_expression}
        )

        {document_scope("d")}

    ORDER BY
        {priority},
        c.id

    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):

        parts = line.split(
            "\t",
            5
        )

        rows.append({
            "id":
                int(parts[0]),

            "topic":
                parts[1],

            "document":
                parts[2],

            "section_number":
                parts[3],

            "heading":
                parts[4],

            "content":
                parts[5],
        })

    return rows


def exact_reference_search(limit=20):

    if not exact_refs:
        return []

    ref_conditions = []
    priority_cases = []

    for ref in exact_refs:

        qualified = (
            parse_qualified_legal_reference(
                ref
            )
        )

        # ----------------------------------------------------
        # Document-qualified legal reference
        #
        # Example:
        #   Cap.121 Section 2(2)
        #
        # Must match BOTH document and section.
        # ----------------------------------------------------

        if qualified:

            legislation_id = sql_quote(
                qualified[
                    "legislation_id"
                ].lower()
            )

            section_number = sql_quote(
                qualified[
                    "section_number"
                ].lower()
            )

            document_match = f"""
            (
                LOWER(
                    COALESCE(
                        d.metadata
                            ->> 'legislation_id',
                        ''
                    )
                ) = '{legislation_id}'

                OR LOWER(
                    COALESCE(
                        d.source_file_id,
                        ''
                    )
                ) LIKE
                    'hkel:{legislation_id}:%'
            )
            """

            ref_conditions.append(
                f"""
                (
                    {document_match}

                    AND LOWER(
                        COALESCE(
                            s.section_number,
                            ''
                        )
                    ) = '{section_number}'
                )
                """
            )

            priority_cases.append(
                f"""
                CASE
                    WHEN
                        {document_match}

                        AND LOWER(
                            COALESCE(
                                s.section_number,
                                ''
                            )
                        ) = '{section_number}'
                    THEN 1

                    ELSE 99
                END
                """
            )

            continue

        # ----------------------------------------------------
        # Chapter-only document reference
        #
        # Example:
        #   Cap.121
        #
        # Match the legislation document itself rather than
        # relying on title/content punctuation.
        # ----------------------------------------------------

        chapter_ref = (
            parse_chapter_reference(
                ref
            )
        )

        if chapter_ref:

            legislation_id = sql_quote(
                chapter_ref.lower()
            )

            document_match = f"""
            (
                LOWER(
                    COALESCE(
                        d.metadata
                            ->> 'legislation_id',
                        ''
                    )
                ) = '{legislation_id}'

                OR LOWER(
                    COALESCE(
                        d.source_file_id,
                        ''
                    )
                ) LIKE
                    'hkel:{legislation_id}:%'
            )
            """

            ref_conditions.append(
                f"""
                (
                    {document_match}
                )
                """
            )

            priority_cases.append(
                f"""
                CASE
                    WHEN {document_match}
                    THEN 2
                    ELSE 99
                END
                """
            )

            continue

        # ----------------------------------------------------
        # Existing unqualified reference behaviour
        # ----------------------------------------------------

        r = sql_quote(
            ref.lower()
        )

        ref_conditions.append(f"""
        (
            LOWER(COALESCE(s.section_number,'')) = '{r}'
            OR LOWER(COALESCE(s.heading,'')) LIKE '%{r}%'
            OR LOWER(COALESCE(d.title,'')) LIKE '%{r}%'
            OR LOWER(COALESCE(c.content,'')) LIKE '%{r}%'
        )
        """)

        priority_cases.append(f"""
        CASE
            WHEN LOWER(COALESCE(s.section_number,'')) = '{r}'
                THEN 1
            WHEN LOWER(COALESCE(s.heading,'')) LIKE '%{r}%'
                THEN 2
            WHEN LOWER(COALESCE(d.title,'')) LIKE '%{r}%'
                THEN 3
            WHEN LOWER(COALESCE(c.content,'')) LIKE '%{r}%'
                THEN 4
            ELSE 99
        END
        """)

    conditions = " OR ".join(ref_conditions)

    priority = (
        "LEAST(" +
        ",".join(priority_cases) +
        ")"
    )

    sql = f"""
    SELECT
        c.id,
        COALESCE(NULLIF(c.metadata->>'topic',''), d.topic, ''),
        COALESCE(d.title,''),
        COALESCE(s.section_number,''),
        COALESCE(s.heading,''),
        REPLACE(REPLACE(c.content, E'\\t', ' '), E'\\n', ' ')
    FROM chunks c
    JOIN documents d
        ON d.id = c.document_id
    LEFT JOIN sections s
        ON s.id = c.section_id
    WHERE
        ({conditions})
        AND COALESCE(
            c.metadata->>'retrieval_role',
            'legacy'
        ) <> 'legal-semantic'
        {document_scope(
            "d",
            include_reference_scope=False
        )}
    ORDER BY
        {priority},
        c.id
    LIMIT {limit};
    """

    rows = []

    for line in run_sql(sql):

        parts = line.split("\t", 5)

        rows.append({
            "id": int(parts[0]),
            "topic": parts[1],
            "document": parts[2],
            "section_number": parts[3],
            "heading": parts[4],
            "content": parts[5]
        })

    return rows


english_results = vector_search(
    args.english_query
)

original_results = vector_search(
    args.query
)

phrase_results = technical_phrase_search()

fts_results = fts_search()

reference_results = exact_reference_search()

definition_results = definition_search()

# Guardrail:
# if the user explicitly requested an exact reference,
# do not silently fall back to unrelated semantic results.
if exact_refs and not reference_results:
    print()
    print("EXACT REFERENCE RESULT:")
    print("No matching reference was found in the indexed knowledge base.")
    print()
    print("Requested exact references:")
    for ref in exact_refs:
        print(f"- {ref}")
    print()
    print(
        "Semantic results are suppressed because "
        "an exact provision reference was requested."
    )
    raise SystemExit(2)

# Exact-reference mode:
# when an explicit reference is found, suppress global semantic/lexical
# retrieval so unrelated chunks cannot contaminate statutory answers.
if (
    exact_refs
    and reference_results
    and not document_scope_refs
):
    phrase_results = []
    fts_results = []
    english_results = []
    original_results = []
    definition_results = []


scores = defaultdict(float)
records = {}
channels = defaultdict(dict)


def save_record(item):
    records[item["id"]] = item



def chunk_provenance(chunk_id):

    sql = f"""
    SELECT
        COALESCE(c.page_start::text,''),
        COALESCE(c.page_end::text,''),
        COALESCE(d.source_url,''),
        COALESCE(d.source_file_id,''),
        COALESCE(d.source_type,''),
        COALESCE(c.metadata->>'repealed',''),
        COALESCE(c.metadata->>'operative',''),
        COALESCE(c.metadata->>'not_in_operation',''),
        COALESCE(c.metadata->>'omitted_as_spent','')
    FROM chunks c
    JOIN documents d
        ON d.id = c.document_id
    WHERE c.id = {int(chunk_id)}
    LIMIT 1;
    """

    rows = run_sql(sql)

    if not rows:
        return {
            "page_start": None,
            "page_end": None,
            "source_url": "",
            "source_file_id": "",
            "source_type": "",
            "repealed": None,
            "operative": None,
            "not_in_operation": None,
            "omitted_as_spent": None
        }

    parts = rows[0].split("\t", 8)

    def parse_bool(value):
        if value == "":
            return None

        return value.lower() == "true"

    return {
        "page_start": int(parts[0]) if parts[0] else None,
        "page_end": int(parts[1]) if parts[1] else None,
        "source_url": parts[2],
        "source_file_id": parts[3],
        "source_type": parts[4],
        "repealed": parse_bool(parts[5]),
        "operative": parse_bool(parts[6]),
        "not_in_operation": parse_bool(parts[7]),
        "omitted_as_spent": parse_bool(parts[8])
    }


# 1. Exact reference = strongest signal
for rank, item in enumerate(reference_results, 1):

    scores[item["id"]] += 8.0 / (60 + rank)

    save_record(item)

    channels[item["id"]]["REF"] = rank


# 2. Definition intent = strong structured semantic signal
for rank, item in enumerate(
    definition_results,
    1
):

    scores[item["id"]] += (
        7.0
        / (60 + rank)
    )

    save_record(
        item
    )

    channels[
        item["id"]
    ]["DEF"] = rank


# 3. Technical phrase = strong precision signal
for rank, item in enumerate(phrase_results, 1):

    scores[item["id"]] += 3.5 / (60 + rank)

    save_record(item)

    channels[item["id"]]["PHRASE"] = rank
    channels[item["id"]]["PHRASE_SCORE"] = \
        item["phrase_score"]


# 3. Full-text retrieval
for rank, item in enumerate(fts_results, 1):

    scores[item["id"]] += 2.0 / (60 + rank)

    save_record(item)

    channels[item["id"]]["FTS"] = rank


# 4. English semantic retrieval
for rank, item in enumerate(english_results, 1):

    scores[item["id"]] += 2.0 / (60 + rank)

    save_record(item)

    channels[item["id"]]["EN"] = rank
    channels[item["id"]]["EN_SIM"] = \
        item["similarity"]


# 5. Original-language vector = weak supplementary signal
for rank, item in enumerate(original_results, 1):

    scores[item["id"]] += 0.2 / (60 + rank)

    save_record(item)

    channels[item["id"]]["ORIG"] = rank


ranked = sorted(
    scores.items(),
    key=lambda x: x[1],
    reverse=True
)

if args.json_output:

    output_results = []

    for rank, (chunk_id, final_score) in enumerate(
        ranked[:args.limit],
        1
    ):
        item = records[chunk_id]
        ch = channels[chunk_id]

        provenance = chunk_provenance(chunk_id)

        output_results.append({
            "rank": rank,
            "chunk_id": chunk_id,
            "score": final_score,
            "topic": item.get("topic", ""),
            "document": item.get("document", ""),
            "section_number": item.get("section_number", ""),
            "heading": item.get("heading", ""),
            "page_start": provenance["page_start"],
            "page_end": provenance["page_end"],
            "source_type": provenance["source_type"],
            "source_file_id": provenance["source_file_id"],
            "source_url": provenance["source_url"],
            "repealed": provenance["repealed"],
            "operative": provenance["operative"],
            "not_in_operation": provenance["not_in_operation"],
            "omitted_as_spent": provenance["omitted_as_spent"],
            "content": item.get("content", ""),
            "channels": ch
        })

    print(json.dumps({
        "query": args.query,
        "english_query": args.english_query,
        "technical_terms": terms,
        "references": refs,
        "results": output_results
    }, ensure_ascii=False))

    raise SystemExit(0)


print()
print("ORIGINAL QUERY:")
print(args.query)

print()
print("NORMALIZED ENGLISH QUERY:")
print(args.english_query)

print()
print("TERMS:")
print(", ".join(terms) if terms else "(none)")

print()
print("REFERENCES:")
print(", ".join(refs) if refs else "(none)")

print()
print("EXACT REFERENCES:")
print(
    ", ".join(exact_refs)
    if exact_refs
    else "(none)"
)

print()
print("DOCUMENT SCOPES:")
print(
    ", ".join(document_scope_refs)
    if document_scope_refs
    else "(none)"
)

print()
print("HYBRID RETRIEVAL V3:")
print()


for rank, (chunk_id, final_score) in enumerate(
    ranked[:args.limit],
    1
):

    item = records[chunk_id]
    ch = channels[chunk_id]

    channel_text = []

    for name in [
        "REF",
        "DEF",
        "PHRASE",
        "FTS",
        "EN",
        "ORIG"
    ]:

        if name in ch:
            channel_text.append(
                f"{name}#{ch[name]}"
            )

    print(
        f"{rank}. "
        f"{item.get('topic') or '(no topic)'} "
        f"[chunk={chunk_id}] "
        f"score={final_score:.6f}"
    )

    print(
        "   channels:",
        ", ".join(channel_text)
    )

    if item.get("document"):
        print(
            "   document:",
            item["document"]
        )

    if item.get("section_number"):
        print(
            "   section:",
            item["section_number"],
            item.get("heading", "")
        )

    print(
        "   content:",
        item["content"][:220]
    )

    print()
