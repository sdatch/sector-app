"""The real client against a mocked HTTP transport: no key, no network.

Checks what actually goes on the wire (symbols only, web search capped, the
refusal fallback, no user identity) and that a paused server-tool turn is
resumed. Skipped where the optional `anthropic` package is not installed.
"""

from __future__ import annotations

import json

import pytest

anthropic = pytest.importorskip("anthropic")
# SDK 1.x is built on httpx2; its transports and responses come from there.
httpx = pytest.importorskip("httpx2")

from app.config import Settings  # noqa: E402
from app.sector_lookup import build_payload  # noqa: E402
from app.sector_lookup.client import AnthropicSectorLookupClient  # noqa: E402


def _message(content, stop_reason="end_turn"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


ANSWER = {
    "classifications": [
        {
            "ticker": "NEWCO",
            "company_name": "NewCo Inc",
            "kind": "stock",
            "sector": "Industrials",
            "confidence": "medium",
            "rationale": "Makes industrial equipment.",
            "searched": True,
        }
    ]
}


def _client(responses, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=responses.pop(0))

    settings = Settings(anthropic_api_key="test-key", sector_lookup_enabled=True)
    c = AnthropicSectorLookupClient(settings)
    c._client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return c


async def test_request_shape_and_parsed_answer():
    seen: list[httpx.Request] = []
    c = _client([_message([{"type": "text", "text": json.dumps(ANSWER)}])], seen)
    out = await c.classify(build_payload(["NEWCO"]))

    assert out is not None
    assert out.classifications[0].sector == "Industrials"

    body = json.loads(seen[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen[0].headers["anthropic-beta"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "medium"
    assert body["tools"] == [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
    ]
    assert "metadata" not in body  # no user identity
    # The only portfolio content in the request is the symbol list.
    assert body["messages"][0]["content"].endswith("NEWCO")


async def test_pause_turn_is_resumed():
    seen: list[httpx.Request] = []
    paused = _message(
        [
            {"type": "text", "text": "Let me check NEWCO."},
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
             "input": {"query": "NEWCO stock"}},
        ],
        stop_reason="pause_turn",
    )
    done = _message([{"type": "text", "text": json.dumps(ANSWER)}])
    c = _client([paused, done], seen)
    out = await c.classify(build_payload(["NEWCO"]))

    assert out is not None
    assert len(seen) == 2
    resumed = json.loads(seen[1].content)["messages"]
    assert [m["role"] for m in resumed] == ["user", "assistant"]


async def test_refusal_is_no_answer():
    seen: list[httpx.Request] = []
    c = _client([_message([], stop_reason="refusal")], seen)
    assert await c.classify(build_payload(["NEWCO"])) is None


async def test_http_error_is_no_answer():
    def handler(request):
        return httpx.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "x"}})

    c = AnthropicSectorLookupClient(Settings(anthropic_api_key="k"))
    c._client = anthropic.AsyncAnthropic(
        api_key="k", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await c.classify(build_payload(["NEWCO"])) is None


def test_answer_is_read_after_the_last_tool_block():
    """Text before a search is narration, not the answer; an answer split
    across blocks (as citations split text) is joined."""
    from types import SimpleNamespace as B

    from app.sector_lookup.client import extract_answer

    blob = json.dumps(ANSWER)
    content = [
        B(type="text", text="Let me look that up."),
        B(type="server_tool_use"),
        B(type="web_search_tool_result"),
        B(type="text", text=blob[:40]),
        B(type="text", text=blob[40:]),
    ]
    out = extract_answer(content)
    assert out is not None and out.classifications[0].ticker == "NEWCO"
    assert extract_answer([B(type="text", text="not json")]) is None
    assert extract_answer([]) is None
