#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path("/opt/ai-knowledge")
sys.path.insert(0, str(BASE_DIR))

from query_normalizer import (
    normalize,
    sanitize_technical_terms,
    load_env_file,
    read_default_model,
    ENV_FILE,
    CONFIG_FILE,
)

from document_scope_resolver_v1 import (
    resolve_document_scope,
)
from query_subject_resolver_v1 import (
    resolve_query_subject,
)
from structural_completion_v1 import (
    apply_structural_completion,
)

env = load_env_file(ENV_FILE)

API_KEY = env["DEEPSEEK_API_KEY"]

BASE_URL = (
    env.get("DEEPSEEK_BASE_URL")
    or "https://api.deepseek.com"
).rstrip("/")

MODEL = read_default_model(CONFIG_FILE)


def prepare_answer_retrieval(
    graph_payload,
):

    """
    Convert Graph-aware Retrieval v1 output into the legacy
    answer-layer retrieval contract:

        retrieval["results"]

    Primary evidence always remains first.

    Only graph_results may become supplementary answer
    evidence. graph_links are retrieval/provenance metadata
    and are NEVER passed as legal evidence.
    """

    if not isinstance(
        graph_payload,
        dict,
    ):

        raise RuntimeError(
            "Graph retrieval payload "
            "is not a JSON object."
        )


    failures = (
        graph_payload.get(
            "graph_expansion_failures"
        )
        or []
    )


    # Fail closed.
    #
    # Do not silently answer from a partially failed graph
    # expansion when the retrieval engine itself reports an
    # error.
    if failures:

        raise RuntimeError(
            "Graph retrieval reported "
            f"{len(failures)} "
            "expansion failure(s)."
        )


    primary_results = (
        graph_payload.get(
            "primary_results"
        )
        or []
    )

    graph_results = (
        graph_payload.get(
            "graph_results"
        )
        or []
    )


    if not isinstance(
        primary_results,
        list,
    ):

        raise RuntimeError(
            "primary_results is not a list."
        )


    if not isinstance(
        graph_results,
        list,
    ):

        raise RuntimeError(
            "graph_results is not a list."
        )


    # --------------------------------------------------------
    # Graph evidence acceptance gate.
    #
    # Graph-aware Retrieval v1 currently permits only:
    #
    #   graph-section-semantic
    #   + deterministic selection
    #   + explicit provenance path
    #
    # into the answer evidence set.
    # --------------------------------------------------------

    for item in graph_results:

        if (
            item.get(
                "retrieval_origin"
            )
            != "graph-section-semantic"
        ):

            raise RuntimeError(
                "Unexpected graph retrieval origin "
                f"for chunk {item.get('chunk_id')}."
            )


        if (
            item.get(
                "graph_evidence_selection"
            )
            != "deterministic"
        ):

            raise RuntimeError(
                "Non-deterministic graph evidence "
                f"for chunk {item.get('chunk_id')}."
            )


        if not (
            item.get(
                "graph_paths"
            )
            or []
        ):

            raise RuntimeError(
                "Graph evidence has no provenance "
                f"path for chunk {item.get('chunk_id')}."
            )


    # --------------------------------------------------------
    # Stable ordering:
    #
    # primary first
    # graph supplementary second
    # --------------------------------------------------------

    primary_ordered = sorted(
        primary_results,
        key=lambda item: (
            item.get(
                "rank"
            )
            if item.get(
                "rank"
            )
            is not None
            else 999999
        ),
    )


    graph_ordered = sorted(
        graph_results,
        key=lambda item: (
            item.get(
                "graph_rank"
            )
            if item.get(
                "graph_rank"
            )
            is not None
            else 999999
        ),
    )


    results = []

    seen_chunk_ids = set()

    primary_added = 0
    graph_added = 0


    def add_evidence(
        original,
        origin,
    ):

        nonlocal primary_added, graph_added


        if not isinstance(
            original,
            dict,
        ):

            raise RuntimeError(
                "Evidence item is not "
                "a JSON object."
            )


        chunk_id = original.get(
            "chunk_id"
        )


        if chunk_id is None:

            raise RuntimeError(
                "Evidence item has no chunk_id."
            )


        chunk_id = int(
            chunk_id
        )


        # Defensive deduplication.
        #
        # Primary wins if the same chunk somehow also appears
        # through Graph expansion.
        if chunk_id in seen_chunk_ids:
            return


        if not original.get(
            "content"
        ):

            raise RuntimeError(
                "Evidence chunk has no content: "
                f"{chunk_id}"
            )


        item = dict(
            original
        )


        if origin == "primary":

            item[
                "primary_rank"
            ] = item.get(
                "rank"
            )

            primary_added += 1

        else:

            graph_added += 1


        item[
            "answer_evidence_origin"
        ] = origin


        # ----------------------------------------------------
        # The answer renderer has always treated "rank" as
        # the [S#] identifier.
        #
        # Reassign one contiguous evidence namespace:
        #
        #   S1..Sn = primary
        #   then supplementary Graph evidence.
        # ----------------------------------------------------

        item[
            "rank"
        ] = (
            len(results)
            + 1
        )


        results.append(
            item
        )

        seen_chunk_ids.add(
            chunk_id
        )


    for item in primary_ordered:

        add_evidence(
            item,
            "primary",
        )


    for item in graph_ordered:

        add_evidence(
            item,
            "graph",
        )


    output = dict(
        graph_payload
    )


    # Legacy Answer Layer contract.
    output[
        "results"
    ] = results


    # Diagnostic metadata only.
    output[
        "answer_evidence"
    ] = {
        "primary_count":
            primary_added,

        "graph_count":
            graph_added,

        "total_count":
            len(results),

        "ordering":
            "primary-then-graph",

        "graph_policy":
            "deterministic-only",
    }


    return output



def retrieve(question, normalized):

    scope = resolve_document_scope(
        question
    )


    # --------------------------------------------------------
    # Query Subject Resolver v1.
    #
    # A subject lock is permitted only when deterministic
    # corpus evidence confirms the candidate inside the
    # uniquely resolved source document.
    #
    # If confirmation fails, preserve Query Normalizer v1
    # output unchanged.
    # --------------------------------------------------------

    effective_normalized = dict(
        normalized
    )


    subject_resolution = (
        resolve_query_subject(
            question,
            scope,
        )
    )


    if (
        subject_resolution.get(
            "status"
        )
        == "confirmed"
    ):

        subject = (
            subject_resolution.get(
                "subject"
            )
        )

        terms = sanitize_technical_terms(
            [
                subject,
            ]
        )


        if terms:

            effective_normalized[
                "technical_terms"
            ] = terms


    cmd = [
        sys.executable,
        str(
            BASE_DIR
            / "graph_search_v1.py"
        ),

        "--query",
        question,

        "--english-query",
        normalized[
            "english_query"
        ],

        "--terms",
        ",".join(
            effective_normalized[
                "technical_terms"
            ]
        ),

        "--refs",
        ",".join(
            normalized[
                "references"
            ]
        ),

        "--limit",
        "5",

        "--json-output",
    ]


    if (
        scope.get(
            "status"
        )
        == "resolved"
        and scope.get(
            "document_title"
        )
    ):

        cmd.extend([
            "--document-title",
            scope[
                "document_title"
            ],
        ])


    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )


    if result.returncode != 0:

        raise RuntimeError(
            result.stdout.strip()
            or result.stderr.strip()
        )


    graph_payload = json.loads(
        result.stdout
    )


    # Preserve deterministic source-document resolution
    # for audit/debugging.
    graph_payload[
        "document_scope"
    ] = scope


    # Query Subject Resolver diagnostics.
    graph_payload[
        "query_subject_resolution"
    ] = subject_resolution

    graph_payload[
        "original_technical_terms"
    ] = list(
        normalized[
            "technical_terms"
        ]
    )

    graph_payload[
        "effective_technical_terms"
    ] = list(
        effective_normalized[
            "technical_terms"
        ]
    )


    prepared = prepare_answer_retrieval(
        graph_payload
    )

    return apply_structural_completion(
        prepared
    )



def render_deterministic_sources(
    answer,
    results
):

    # --------------------------------------------------------
    # Remove any Sources section the model generated despite
    # instructions. The application owns provenance rendering.
    # --------------------------------------------------------

    answer = answer.strip()

    answer = re.sub(
        r"(?is)\n"
        r"(?:#{1,6}\s*)?"
        r"(?:\*\*)?"
        r"Sources"
        r"(?:\*\*)?"
        r"\s*:?\s*\n.*$",
        "",
        answer
    ).rstrip()

    # --------------------------------------------------------
    # Extract source markers in first-use order.
    # --------------------------------------------------------

    cited = []

    for match in re.finditer(
        r"\[S(\d+)\]",
        answer
    ):

        rank = int(
            match.group(1)
        )

        if rank not in cited:
            cited.append(
                rank
            )

    result_by_rank = {}

    for item in results:

        try:
            rank = int(
                item.get(
                    "rank"
                )
            )
        except (
            TypeError,
            ValueError
        ):
            continue

        result_by_rank[
            rank
        ] = item

    invalid = [
        rank
        for rank in cited
        if rank not in result_by_rank
    ]

    if invalid:

        raise RuntimeError(
            "Answer contains invalid source "
            "markers: "
            + ", ".join(
                f"S{rank}"
                for rank in invalid
            )
        )

    # --------------------------------------------------------
    # Fail visibly if the model returned an evidence-based
    # answer without citing any retrieved evidence.
    # --------------------------------------------------------

    if not cited:

        return (
            answer
            + "\n\n"
            + "## Sources\n"
            + "- No source markers were cited "
              "in the generated answer."
        )

    # --------------------------------------------------------
    # Render provenance directly from retrieval metadata.
    # URLs are never rewritten by the language model.
    # --------------------------------------------------------

    source_lines = []

    for rank in cited:

        item = result_by_rank[
            rank
        ]

        parts = [
            f"[S{rank}] "
            f"{item.get('document') or 'Unknown document'}"
        ]

        section = item.get(
            "section_number"
        )

        heading = item.get(
            "heading"
        )

        if section:

            section_text = (
                f"Section {section}"
            )

            if heading:
                section_text += (
                    f" — {heading}"
                )

            parts.append(
                section_text
            )

        elif heading:

            parts.append(
                heading
            )

        page_start = item.get(
            "page_start"
        )

        page_end = item.get(
            "page_end"
        )

        if page_start is not None:

            if (
                page_end is not None
                and page_end != page_start
            ):

                parts.append(
                    f"Pages "
                    f"{page_start}-{page_end}"
                )

            else:

                parts.append(
                    f"Page {page_start}"
                )

        source_file_id = item.get(
            "source_file_id"
        )

        if source_file_id:

            parts.append(
                "Source File ID: "
                + str(
                    source_file_id
                )
            )

        source_url = item.get(
            "source_url"
        )

        if source_url:

            parts.append(
                "Source URL: "
                + str(
                    source_url
                )
            )

        source_lines.append(
            "- "
            + " | ".join(
                parts
            )
        )

    return (
        answer
        + "\n\n"
        + "## Sources\n"
        + "\n".join(
            source_lines
        )
    )

def generate_answer(question, retrieval):

    results = retrieval.get("results", [])

    if not results:
        return (
            "目前檢索到的證據不足以可靠回答這個問題。"
        )

    evidence_parts = []

    for item in results:

        source = f"[S{item['rank']}]"

        meta = [
            f"Document: {item.get('document') or 'Unknown'}"
        ]

        if item.get("section_number"):
            meta.append(
                f"Section: {item['section_number']}"
            )

        if item.get("heading"):
            meta.append(
                f"Heading: {item['heading']}"
            )

        page_start = item.get("page_start")
        page_end = item.get("page_end")

        if page_start is not None:
            if (
                page_end is not None
                and page_end != page_start
            ):
                meta.append(
                    f"Pages: {page_start}-{page_end}"
                )
            else:
                meta.append(
                    f"Page: {page_start}"
                )

        if item.get("repealed") is not None:
            meta.append(
                f"Repealed: {str(item['repealed']).lower()}"
            )

        if item.get("operative") is not None:
            meta.append(
                f"Operative: {str(item['operative']).lower()}"
            )

        if item.get("not_in_operation") is not None:
            meta.append(
                "Not In Operation: "
                f"{str(item['not_in_operation']).lower()}"
            )

        if item.get("omitted_as_spent") is not None:
            meta.append(
                "Omitted As Spent: "
                f"{str(item['omitted_as_spent']).lower()}"
            )

        if item.get("source_type"):
            meta.append(
                f"Source Type: {item['source_type']}"
            )

        if item.get("source_file_id"):
            meta.append(
                f"Source File ID: {item['source_file_id']}"
            )

        if item.get("source_url"):
            meta.append(
                f"Source URL: {item['source_url']}"
            )

        evidence_parts.append(
            "\n".join([
                source,
                *meta,
                "Content:",
                item["content"]
            ])
        )

    evidence = "\n\n".join(evidence_parts)

    system_prompt = """
You answer questions using ONLY the supplied knowledge-base evidence.

Rules:

1. Do not use outside knowledge to fill missing information.
2. Do not invent legal, statutory, technical or factual details.
3. If the supplied evidence is insufficient to answer the user's actual
   question reliably, explicitly say so and identify the material limitation.
   Do not describe evidence as insufficient merely because additional related
   material could exist when the supplied evidence already supports the answer.
4. If the source is obviously synthetic or test content, say that it
   cannot support a substantive professional conclusion.
5. Answer in the user's language unless there is a good reason not to.
6. Cite factual statements using [S1], [S2], etc.
7. Prefer the highest-ranked and most exact evidence.
8. For exact statutory references, do not rely on unrelated semantic
   results.
9. Keep professional terminology in English where useful, with Chinese
   explanation where appropriate.
10. Do not write a Sources section. Cite evidence inline using [S1], [S2],
    etc. only. The application will render the Sources section directly from
    retrieval metadata.
11. Describe a source only as strongly as the evidence supports.
    Do not turn an index/reference relationship into a broader legal
    characterization unless the source itself supports that characterization.
12. Treat explicit legal-status metadata as authoritative evidence about the
    status of a provision. Never present a provision marked Repealed: true,
    Operative: false, Not In Operation: true, or Omitted As Spent: true as
    currently operative law. State the relevant status clearly when it materially
    affects the answer. "Omitted as spent" is a distinct status and must not be
    described as "repealed" unless Repealed: true is also explicitly supplied.
13. Distinguish carefully between the indexed knowledge base and the evidence
    supplied for the current answer. If evidence that is necessary to answer the
    user's actual question is not supplied, say that the current evidence does
    not include it. Do not volunteer that unrelated, supplementary, or merely
    potentially relevant material is absent when its absence does not materially
    limit the answer. Do NOT claim that the knowledge base does not contain
    something unless the retrieval result explicitly establishes that fact.
14. Prefer neutral legal descriptions grounded in the text. Avoid loose phrases
    such as "outsourced", "bridge law", or similar characterizations unless the
    evidence itself uses or clearly supports that terminology.
15. Do not describe a statutory provision as "truncated", "cut off", or
    incomplete merely because its text ends with a colon, dash, or introductory
    phrase. Legal child provisions may be stored as separate atomic sections.
    If the required child provisions are not present in the supplied evidence,
    say that the current evidence does not include those child provisions.
16. Preserve official legislation and document titles exactly as supplied in the
    evidence. Do not invent, translate, abbreviate, or paraphrase an official
    title unless an official translated title is explicitly supplied in the
    evidence.
17. For yes/no or conditional questions, make the opening conclusion answer the
    user's stated condition directly and consistently with the supporting
    evidence. Do not begin with "yes" if the substantive conclusion is that the
    provision does not apply, and do not begin with "no" if it does apply.
    Restate any decisive condition, such as "the whole of the building", in the
    opening conclusion when it affects the answer.

18. Answer the user's actual question first and stop once it has been adequately
    answered. Evidence sufficiency is judged against the question asked, not
    against everything that could potentially be said about the wider topic.

19. Use retrieved evidence only when it materially supports or qualifies the
    answer. Do not mention, summarize, or cite evidence merely to say that it is
    irrelevant to the question.

20. For a definition question, give the definition and any cross-referenced
    definition or qualification needed to understand it. Do not add neighbouring
    definitions, examples of the term in use, related provisions, or broader
    statutory context unless they materially clarify the requested definition.

21. Do not discuss amendment history, operative/repealed metadata, related
    provisions, or missing supplementary material unless it materially changes
    the answer, is necessary to avoid a misleading conclusion, or the user asks
    about it specifically.

22. Do not add legal characterizations or interpretive consequences that are not
    stated or directly established by the supplied evidence. Prefer the statutory
    wording itself where a characterization would require interpretation. In
    particular, do not infer from the word "includes" alone that a statutory
    definition is non-exhaustive, illustrative, or broader than the listed text,
    and do not label a statutory interaction as a "priority rule" or similar term
    unless the supplied evidence itself supports that characterization.

23. When a factual or legal statement depends on combining more than one source,
    cite every source necessary to support the resulting statement. In particular,
    if one provision supplies a base definition and another provision modifies how
    that definition is to be read, do not attribute the modified wording to the
    base-definition source alone.
""".strip()

    user_prompt = f"""
QUESTION:
{question}

KNOWLEDGE-BASE EVIDENCE:

{evidence}
""".strip()

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "thinking": {
            "type": "disabled"
        },
        "reasoning_effort": "none",
        "max_tokens": 900,
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
        timeout=90
    ) as response:

        body = json.loads(
            response.read().decode("utf-8")
        )

    answer = (
        body["choices"][0]
        ["message"]
        ["content"]
    )

    return render_deterministic_sources(
        answer,
        results
    )


def main():

    if len(sys.argv) < 2:
        raise SystemExit(
            'Usage: answer-knowledge "question"'
        )

    question = " ".join(sys.argv[1:]).strip()

    normalized = normalize(question)

    retrieval = retrieve(
        question,
        normalized
    )

    print()
    print("=" * 78)
    print("ANSWER")
    print("=" * 78)
    print()

    answer = generate_answer(
        question,
        retrieval
    )

    print(answer)


if __name__ == "__main__":
    main()
