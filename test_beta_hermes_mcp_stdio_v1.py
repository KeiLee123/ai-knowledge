#!/usr/bin/env python3
"""Offline MCP protocol test: real list_tools/call_tool, zero Docker or model calls."""

import asyncio
import json
from unittest.mock import patch

from mcp import Client
import beta_hermes_mcp_stdio_v1 as svc


def packet():
    return {
        "environment": "staging",
        "read_only": True,
        "production_write": False,
        "guard_ok": True,
        "source": {
            "source_id": "BD_PNAP_APP149",
            "title": "Authorized Signatories",
            "official_url": (
                "https://www.bd.gov.hk/doc/en/resources/"
                "codes-and-references/practice-notes-and-circular-letters/"
                "pnap/APP/APP149.pdf"
            ),
            "approved_baseline": True,
            "checksum": "a" * 64,
        },
        "integrity": {"integrity_ok": True},
        "question": "What are the requirements for a temporary AS?",
        "evidence": [{
            "id": "S1", "page": 2, "chunk_id": 121,
            "content": "Nominate a temporary AS, paragraph 6.",
        }],
        "answer_status": "EVIDENCE_ONLY_REVIEW_REQUIRED",
    }


async def test_real_mcp_protocol():
    with patch.object(svc, "build_packet", return_value=packet()) as mocked:
        async with Client(svc.mcp) as client:
            listed = await client.list_tools()
            assert len(listed.tools) == 1
            tool = listed.tools[0]
            assert tool.name == svc.TOOL_NAME
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.open_world_hint is False

            result = await client.call_tool(svc.TOOL_NAME, {
                "source_id": "BD_PNAP_APP149",
                "question": "What are the requirements for a temporary AS?",
            })
            assert result.is_error is False, result
            as_text = json.dumps(result.structured_content, ensure_ascii=False) + " " + " ".join(getattr(part, "text", "") for part in result.content)
            assert "BD_PNAP_APP149" in as_text
            assert "APP149.pdf#page=2" in as_text
            assert "EVIDENCE_ONLY_REVIEW_REQUIRED" in as_text
            assert "NOT_VERIFIED" in as_text
            mocked.assert_called_once_with(
                "BD_PNAP_APP149",
                "What are the requirements for a temporary AS?", 5,
            )


async def test_refusal_is_safe():
    with patch.object(
        svc, "build_packet",
        side_effect=RuntimeError("private path/credentials leaked"),
    ):
        async with Client(svc.mcp) as client:
            result = await client.call_tool(svc.TOOL_NAME, {
                "source_id": "BD_PNAP_APP149",
                "question": "What are the requirements for a temporary AS?",
            })
            assert result.is_error is False
            text = json.dumps(result.structured_content) + " " + " ".join(getattr(part, "text", "") for part in result.content)
            assert "REFUSED" in text
            assert "private path" not in text
            assert "credentials" not in text
            assert "EVIDENCE_RETRIEVAL_UNAVAILABLE" in text


def test_no_server_or_prod_paths():
    from pathlib import Path
    s = Path(svc.__file__).read_text(encoding="utf-8")
    for bad in (
        "streamable-http", "uvicorn", "0.0.0.0", "listen(",
        "API_SERVER_KEY", "JASON_BETA_LLM_API_KEY",
        "import subprocess", "subprocess.run(", "answer_knowledge.py",
        "/opt/ai-knowledge/", "graph_search_v1.py",
    ):
        assert bad not in s, bad


def main():
    test_no_server_or_prod_paths()
    print("test_no_server_or_prod_paths: PASS")
    asyncio.run(test_real_mcp_protocol())
    print("test_real_mcp_protocol: PASS")
    asyncio.run(test_refusal_is_safe())
    print("test_refusal_is_safe: PASS")
    print("HERMES MCP STDIO CONTRACT: PASS")


if __name__ == "__main__":
    main()
