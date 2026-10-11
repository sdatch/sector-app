"""
The only module that talks to the network.

`import anthropic` lives inside the constructor on purpose: the SDK is an
optional dependency of this app, and a module-level import would make
`import app.main` fail wherever narration is switched off — which is the
default, and the state of every test environment. Nothing imports the SDK until
a request actually needs it.

Failure policy: `max_retries=0`. A deterministic fallback already exists and is
better than making the user wait out a retry for cosmetic text. Every error is
caught by the caller and turned into "no narration", never into a 5xx.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.config import Settings

from .payload import NarrationPayload
from .prompt import SYSTEM_PROMPT, user_message
from .schema import NarrationOutput

log = logging.getLogger(__name__)


@runtime_checkable
class NarrationClient(Protocol):
    async def generate(
        self, payload: NarrationPayload
    ) -> NarrationOutput | None: ...

    async def aclose(self) -> None: ...


class AnthropicNarrationClient:
    def __init__(self, settings: Settings) -> None:
        import anthropic  # lazy — see module docstring

        self._anthropic = anthropic
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.narration_timeout_s,
            max_retries=0,
        )

    async def generate(self, payload: NarrationPayload) -> NarrationOutput | None:
        a = self._anthropic
        try:
            response = await self._client.messages.parse(
                model=self._settings.narration_model,
                max_tokens=self._settings.narration_max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message(payload)}],
                output_format=NarrationOutput,
                output_config={"effort": self._settings.narration_effort},
                # No `metadata={"user_id": ...}`: this request must not carry
                # user identity (PRD NFR-3).
            )
        except (
            a.APITimeoutError,
            a.APIConnectionError,
            a.RateLimitError,
            a.APIStatusError,
        ) as exc:
            log.warning("narration request failed: %s", type(exc).__name__)
            return None
        except Exception:  # noqa: BLE001 — cosmetic text may never 500 a page
            log.warning("narration request failed unexpectedly", exc_info=True)
            return None

        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            log.warning(
                "narration refused (category=%s)", getattr(details, "category", None)
            )
            return None
        if stop == "max_tokens":
            # Truncated prose would fail validation anyway; say why in the log.
            log.warning("narration hit max_tokens; raise narration_max_tokens")
            return None
        return getattr(response, "parsed_output", None)

    async def aclose(self) -> None:
        await self._client.close()


class StubNarrationClient:
    """Dev/QA stand-in: writes the same sentence the real model is asked for,
    from the payload alone. No network, no key, no spend.

    It exists so the narrated UI — above all its disclosure line — can be
    reviewed before anyone pays for a token. It is deliberately dull: if the
    stub's output ever fails validate_output, the validator is too strict,
    because this is close to the best case a real reply can look like.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, payload: NarrationPayload) -> NarrationOutput:
        from .schema import NarratedMove

        self.calls += 1
        return NarrationOutput(
            moves=[
                NarratedMove(
                    from_sector=m.from_sector,
                    to_sector=m.to_sector,
                    text=(
                        f"Moving {m.move_pct} of the portfolio from "
                        f"{m.from_sector} to {m.to_sector} takes return per "
                        f"unit of risk from {m.sharpe_before} to "
                        f"{m.sharpe_after}, with volatility at "
                        f"{m.vol_after_pct} and expected return at "
                        f"{m.return_after_pct}."
                    ),
                )
                for m in payload.moves
            ]
        )

    async def aclose(self) -> None:
        return None


def get_client(app) -> NarrationClient | None:
    """The app's narration client, or None when the feature is off.

    Constructed on first use and cached on `app.state.narration_client`, which
    is also the seam tests replace with a fake.
    """
    existing = getattr(app.state, "narration_client", None)
    if existing is not None:
        return existing

    settings = app.state.settings
    if not settings.narration_enabled:
        return None

    if settings.narration_stub and not settings.is_production:
        client = StubNarrationClient()
        app.state.narration_client = client
        return client

    if not settings.anthropic_api_key:
        return None

    try:
        client = AnthropicNarrationClient(settings)
    except ImportError:
        # Flag on but the optional dependency is absent: degrade, don't crash.
        log.warning("narration_enabled but the `anthropic` package is missing")
        return None
    app.state.narration_client = client
    return client
