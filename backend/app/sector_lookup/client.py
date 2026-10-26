"""
The only module that talks to the network.

Same shape and failure policy as narration/client.py: `import anthropic` lives
in the constructor so the app imports without the SDK, `max_retries=0`, and
every error becomes "no answer" (None), never a 5xx. A missing suggestion costs
the user nothing; they can still pick a sector by hand.

The request carries web search so the model can look up symbols it does not
know (recent listings, renames, small caps). The system prompt tells it to
search only when unsure, and `max_uses` caps the spend per call.

Why `create` + our own parse rather than `messages.parse`: the SDK's parse
validates *every* text block as the schema, and a web-search turn can carry
text that is not the answer (a note between searches, or one answer split
across citation-bearing blocks). The JSON schema is the same one `parse` would
send; we just read the answer from the text after the last tool result.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from app.config import Settings
from app.portfolios.sectors import SECTOR_CODE

from .payload import LookupPayload
from .prompt import SYSTEM_PROMPT, user_message
from .schema import LookupOutput, TickerClassification

log = logging.getLogger(__name__)

# Server-side refusal fallback: on a policy decline the API re-runs the request
# on a fallback model inside the same call, routed by refusal category.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# A long search turn can pause; resume it a bounded number of times.
_MAX_CONTINUATIONS = 3


@lru_cache(maxsize=1)
def _output_format() -> dict:
    from anthropic import transform_schema

    return {
        "type": "json_schema",
        "schema": transform_schema(LookupOutput.model_json_schema()),
    }


def extract_answer(content) -> LookupOutput | None:
    """The answer is the text after the last server-tool block, joined."""
    last_tool = -1
    for i, block in enumerate(content):
        if getattr(block, "type", None) != "text":
            last_tool = i
    text = "".join(
        b.text for b in content[last_tool + 1 :] if getattr(b, "type", None) == "text"
    ).strip()
    if not text:
        return None
    try:
        return LookupOutput.model_validate_json(text)
    except ValidationError:
        log.warning("sector lookup rejected: unparseable_answer")
        return None


@runtime_checkable
class SectorLookupClient(Protocol):
    async def classify(self, payload: LookupPayload) -> LookupOutput | None: ...

    async def aclose(self) -> None: ...


class AnthropicSectorLookupClient:
    def __init__(self, settings: Settings) -> None:
        import anthropic  # lazy — see module docstring

        self._anthropic = anthropic
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.sector_lookup_timeout_s,
            max_retries=0,
        )

    async def classify(self, payload: LookupPayload) -> LookupOutput | None:
        a = self._anthropic
        s = self._settings
        messages: list[dict] = [
            {"role": "user", "content": user_message(payload)}
        ]
        try:
            for _ in range(_MAX_CONTINUATIONS + 1):
                response = await self._client.beta.messages.create(
                    model=s.sector_lookup_model,
                    max_tokens=s.sector_lookup_max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=[
                        {
                            "type": "web_search_20260209",
                            "name": "web_search",
                            "max_uses": s.sector_lookup_max_searches,
                        }
                    ],
                    output_config={
                        "effort": s.sector_lookup_effort,
                        "format": _output_format(),
                    },
                    betas=[_FALLBACK_BETA],
                    fallbacks="default",
                    # No `metadata={"user_id": ...}`: this request must not
                    # carry user identity (PRD NFR-3).
                )
                if getattr(response, "stop_reason", None) != "pause_turn":
                    break
                # Resume the paused server-tool turn: re-send it as the
                # assistant's content, with no extra user message.
                messages = [messages[0], {"role": "assistant", "content": response.content}]
            else:
                log.warning("sector lookup still paused after %d continuations",
                            _MAX_CONTINUATIONS)
                return None
        except (
            a.APITimeoutError,
            a.APIConnectionError,
            a.RateLimitError,
            a.APIStatusError,
        ) as exc:
            log.warning("sector lookup request failed: %s %s",
                        type(exc).__name__, getattr(exc, "message", ""))
            return None
        except Exception:  # noqa: BLE001 — a suggestion may never 500 a page
            log.warning("sector lookup request failed unexpectedly", exc_info=True)
            return None

        _log_usage(response, len(payload.tickers))
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            log.warning(
                "sector lookup refused (category=%s)",
                getattr(details, "category", None),
            )
            return None
        if stop == "max_tokens":
            log.warning("sector lookup hit max_tokens; raise sector_lookup_max_tokens")
            return None
        return extract_answer(response.content)

    async def aclose(self) -> None:
        await self._client.close()


def _log_usage(response, n_tickers: int) -> None:
    """Cost visibility: one line per call with tokens and searches used."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    server = getattr(usage, "server_tool_use", None)
    log.info(
        "sector lookup: %d tickers, model=%s, in=%s out=%s searches=%s",
        n_tickers,
        getattr(response, "model", "?"),
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
        getattr(server, "web_search_requests", 0) if server else 0,
    )


class StubSectorLookupClient:
    """Dev/QA stand-in: no network, no key, no spend.

    Known stocks get the reference table's sector, so no disagreement appears;
    unknown symbols get a deterministic, plainly labelled fake suggestion so
    the accept/edit flow can be clicked through before anyone pays for a token.
    """

    def __init__(self, ticker_sector: dict[str, str]) -> None:
        self._table = ticker_sector
        self.calls = 0

    async def classify(self, payload: LookupPayload) -> LookupOutput:
        self.calls += 1
        sectors = list(SECTOR_CODE)
        out = []
        for t in payload.tickers:
            known = self._table.get(t)
            if known is not None:
                sector, confidence = known, "high"
            else:
                digest = hashlib.sha256(t.encode()).digest()
                sector, confidence = sectors[digest[0] % len(sectors)], "low"
            out.append(
                TickerClassification(
                    ticker=t,
                    company_name=None,
                    kind="stock",
                    sector=sector,
                    confidence=confidence,
                    rationale="Stub suggestion — not a real lookup.",
                    searched=False,
                )
            )
        return LookupOutput(classifications=out)

    async def aclose(self) -> None:
        return None


def get_client(app) -> SectorLookupClient | None:
    """The app's lookup client, or None when the feature is off.

    Constructed on first use and cached on `app.state.sector_lookup_client`,
    which is also the seam tests replace with a fake.
    """
    existing = getattr(app.state, "sector_lookup_client", None)
    if existing is not None:
        return existing

    settings = app.state.settings
    if not settings.sector_lookup_enabled:
        return None

    if settings.sector_lookup_stub and not settings.is_production:
        bundle = app.state.snapshots.get(settings.active_snapshot_id)
        client = StubSectorLookupClient(bundle.ticker_sector)
        app.state.sector_lookup_client = client
        return client

    if not settings.anthropic_api_key:
        return None

    try:
        client = AnthropicSectorLookupClient(settings)
    except ImportError:
        log.warning("sector_lookup_enabled but the `anthropic` package is missing")
        return None
    app.state.sector_lookup_client = client
    return client
