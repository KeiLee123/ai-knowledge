#!/usr/bin/env python3

import argparse
import json
import sys


REQUIRED_TOP = {
    "query",
    "english_query",
    "technical_terms",
    "references",
    "retrieval",
    "primary_results",
    "graph_links",
    "graph_results",
    "graph_expansion_failures",
}


def validate(path):

    errors = []
    warnings = []

    def error(msg):
        errors.append(msg)

    def warn(msg):
        warnings.append(msg)


    with open(
        path,
        encoding="utf-8",
    ) as f:
        d = json.load(f)


    # ========================================================
    # Top-level contract
    # ========================================================

    missing = (
        REQUIRED_TOP
        - set(d)
    )

    if missing:
        error(
            "missing top-level fields: "
            + ", ".join(
                sorted(missing)
            )
        )


    retrieval = d.get(
        "retrieval",
        {}
    )

    for field in (
        "primary_engine",
        "graph_engine",
        "graph_hops",
        "primary_limit",
        "graph_limit",
        "activation_limit",
    ):
        if field not in retrieval:
            error(
                f"retrieval missing {field}"
            )


    if (
        retrieval.get(
            "primary_engine"
        )
        != "hybrid-search-v3"
    ):
        error(
            "unexpected primary_engine"
        )


    if (
        retrieval.get(
            "graph_engine"
        )
        != "graph-search-v1"
    ):
        error(
            "unexpected graph_engine"
        )


    if retrieval.get(
        "graph_hops"
    ) != 1:
        error(
            "graph_hops must be 1"
        )


    primary = (
        d.get(
            "primary_results"
        )
        or []
    )

    links = (
        d.get(
            "graph_links"
        )
        or []
    )

    results = (
        d.get(
            "graph_results"
        )
        or []
    )

    failures = (
        d.get(
            "graph_expansion_failures"
        )
        or []
    )


    if failures:
        error(
            "graph_expansion_failures "
            f"is not empty: {len(failures)}"
        )


    # ========================================================
    # Graph links
    # ========================================================

    edge_keys = []
    link_by_edge = {}


    common_link_fields = {
        "relationship",
        "edge_key",
        "source_ref",
        "source_chunk_ids",
        "target_ref",
        "source_match_mode",
        "activation_status",
        "activation_mode",
        "activation_chunk_ids",
        "evidence_status",
        "trigger_matches",
    }


    for i, link in enumerate(
        links,
        1,
    ):

        prefix = (
            f"graph_links[{i}]"
        )


        missing = (
            common_link_fields
            - set(link)
        )

        if missing:

            error(
                prefix
                + " missing: "
                + ", ".join(
                    sorted(missing)
                )
            )


        edge_key = link.get(
            "edge_key"
        )


        if not edge_key:

            error(
                prefix
                + " has empty edge_key"
            )

        else:

            edge_keys.append(
                edge_key
            )

            link_by_edge[
                edge_key
            ] = link


        activation = link.get(
            "activation_status"
        )

        evidence = link.get(
            "evidence_status"
        )

        relationship = link.get(
            "relationship"
        )


        if activation not in {
            "active",
            "inactive",
            "activation-failed",
        }:

            error(
                prefix
                + " invalid activation_status: "
                + repr(activation)
            )


        if activation == "active":

            if not link.get(
                "activation_chunk_ids"
            ):

                error(
                    prefix
                    + " active but has no "
                    "activation_chunk_ids"
                )


        if activation == "inactive":

            if evidence != "inactive-source":

                error(
                    prefix
                    + " inactive edge must have "
                    "evidence_status=inactive-source"
                )


        if (
            relationship
            == "explicit-reference"
        ):

            if evidence == "added":

                error(
                    prefix
                    + " document-level edge "
                    "must never add evidence"
                )


        if (
            relationship
            == "explicit-section-reference"

            and activation
            == "active"

            and link.get(
                "target_section_id"
            )
            is not None

            and evidence
            in {
                "added",
                "already-primary",
                "resolved-no-new-evidence",
                "graph-limit",
            }
        ):

            if (
                link.get(
                    "resolver_status"
                )
                != "resolved"
            ):

                error(
                    prefix
                    + " active section edge "
                    "is not resolver_status=resolved"
                )


            if (
                link.get(
                    "resolver_fallback_count",
                    0,
                )
                != 0
            ):

                error(
                    prefix
                    + " resolved edge has fallback"
                )


            if not link.get(
                "resolver_selected_chunk_ids"
            ):

                error(
                    prefix
                    + " resolved section edge "
                    "has no selected chunks"
                )


    if (
        len(edge_keys)
        != len(
            set(edge_keys)
        )
    ):

        error(
            "duplicate edge_key remains "
            "after graph deduplication"
        )


    # ========================================================
    # Graph results
    # ========================================================

    primary_ids = {
        int(x["chunk_id"])
        for x in primary
        if x.get(
            "chunk_id"
        )
        is not None
    }


    graph_ids = {
        int(x["chunk_id"])
        for x in results
        if x.get(
            "chunk_id"
        )
        is not None
    }


    expected_ranks = list(
        range(
            1,
            len(results) + 1,
        )
    )

    actual_ranks = [
        x.get(
            "graph_rank"
        )
        for x in results
    ]


    if actual_ranks != expected_ranks:

        error(
            "graph_rank is not "
            "sequential from 1"
        )


    provenance_keys = set()


    for i, result in enumerate(
        results,
        1,
    ):

        prefix = (
            f"graph_results[{i}]"
        )


        if (
            result.get(
                "retrieval_origin"
            )
            != "graph-section-semantic"
        ):

            error(
                prefix
                + " unexpected retrieval_origin"
            )


        if (
            result.get(
                "graph_relationship_confidence"
            )
            != "high"
        ):

            error(
                prefix
                + " confidence is not high"
            )


        if (
            result.get(
                "graph_evidence_selection"
            )
            != "deterministic"
        ):

            error(
                prefix
                + " selection is not deterministic"
            )


        paths = (
            result.get(
                "graph_paths"
            )
            or []
        )


        if not paths:

            error(
                prefix
                + " has no graph_paths"
            )

            continue


        chunk_id = int(
            result[
                "chunk_id"
            ]
        )


        for j, path_info in enumerate(
            paths,
            1,
        ):

            pfx = (
                f"{prefix}.graph_paths[{j}]"
            )


            if (
                path_info.get(
                    "relationship"
                )
                != "explicit-section-reference"
            ):

                error(
                    pfx
                    + " is not "
                    "explicit-section-reference"
                )


            edge_key = (
                path_info.get(
                    "edge_key"
                )
            )


            if (
                edge_key
                not in link_by_edge
            ):

                error(
                    pfx
                    + " references unknown edge_key"
                )

                continue


            link = (
                link_by_edge[
                    edge_key
                ]
            )


            if (
                link.get(
                    "activation_status"
                )
                != "active"
            ):

                error(
                    pfx
                    + " points to inactive edge"
                )


            if (
                link.get(
                    "resolver_status"
                )
                != "resolved"
            ):

                error(
                    pfx
                    + " points to unresolved resolver"
                )


            selected_ids = {
                int(x)
                for x in (
                    link.get(
                        "resolver_selected_chunk_ids"
                    )
                    or []
                )
            }


            if (
                chunk_id
                not in selected_ids
            ):

                error(
                    pfx
                    + " target chunk is not in "
                    "resolver_selected_chunk_ids"
                )


            if (
                path_info.get(
                    "evidence_resolver"
                )
                != "section-evidence-resolver-v1"
            ):

                error(
                    pfx
                    + " unexpected evidence_resolver"
                )


            mappings = (
                path_info.get(
                    "source_mappings"
                )
                or []
            )


            if not mappings:

                error(
                    pfx
                    + " has no source_mappings"
                )


            for mapping in mappings:

                if (
                    mapping.get(
                        "resolution_mode"
                    )
                    not in {
                        "single-target",
                        "citation-term",
                        "definition-identity",
                    }
                ):

                    error(
                        pfx
                        + " invalid resolution_mode"
                    )


            provenance_key = (
                chunk_id,
                edge_key,
                json.dumps(
                    mappings,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )


            if (
                provenance_key
                in provenance_keys
            ):

                error(
                    pfx
                    + " duplicate provenance path"
                )

            provenance_keys.add(
                provenance_key
            )


    # ========================================================
    # Added section edges must be represented
    # ========================================================

    for i, link in enumerate(
        links,
        1,
    ):

        if (
            link.get(
                "relationship"
            )
            != "explicit-section-reference"
        ):

            continue


        if (
            link.get(
                "evidence_status"
            )
            != "added"
        ):

            continue


        selected = {
            int(x)
            for x in (
                link.get(
                    "resolver_selected_chunk_ids"
                )
                or []
            )
        }


        missing_targets = (
            selected
            - graph_ids
            - primary_ids
        )


        if missing_targets:

            error(
                f"graph_links[{i}] selected "
                "chunks missing from both "
                "primary and graph results: "
                + ", ".join(
                    str(x)
                    for x in sorted(
                        missing_targets
                    )
                )
            )


    # ========================================================
    # Report
    # ========================================================

    print(
        "=" * 90
    )

    print(
        path
    )

    print(
        "=" * 90
    )

    print(
        "primary results :",
        len(primary),
    )

    print(
        "graph links     :",
        len(links),
    )

    print(
        "graph results   :",
        len(results),
    )

    print(
        "errors          :",
        len(errors),
    )

    print(
        "warnings        :",
        len(warnings),
    )


    for msg in errors:
        print(
            "ERROR:",
            msg,
        )


    for msg in warnings:
        print(
            "WARNING:",
            msg,
        )


    if errors:

        print(
            "CONTRACT: FAIL"
        )

        return False


    print(
        "CONTRACT: PASS"
    )

    return True


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "files",
        nargs="+",
    )

    args = parser.parse_args()


    ok = True


    for path in args.files:

        if not validate(
            path
        ):

            ok = False


    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
