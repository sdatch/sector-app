"""POST /v1/comparisons/{id}/narration end to end, with a fake client.

No network and no API key: `app.state.narration_client` is the seam, and the
fake records every payload it is handed so the privacy guarantee can be
asserted against what would really have been sent.
"""

from __future__ import annotations

import re

import pytest

from app.narration.schema import NarratedMove, NarrationOutput
from app.orchestration.rate_limit import SlidingWindowLimiter
from tests.api.conftest import equal_weight_request, snapshot_sectors

MODEL = "black_litterman"


class FakeNarrationClient:
    """Returns whatever it is told to, and remembers what it was asked."""

    def __init__(self, output=None, exc: Exception | None = None):
        self.output = output
        self.exc = exc
        self.calls = []

    async def generate(self, payload):
        self.calls.append(payload)
        if self.exc is not None:
            raise self.exc
        if callable(self.output):
            return self.output(payload)
        return self.output

    async def aclose(self):
        pass


def echo_valid(payload) -> NarrationOutput:
    """A well-formed reply: right shape, only supplied figures and sectors."""
    return NarrationOutput(
        moves=[
            NarratedMove(
                from_sector=m.from_sector,
                to_sector=m.to_sector,
                text=(
                    f"Moving {m.move_pct} from {m.from_sector} to "
                    f"{m.to_sector} lifts return per unit of risk from "
                    f"{m.sharpe_before} to {m.sharpe_after}, with volatility "
                    f"at {m.vol_after_pct}."
                ),
            )
            for m in payload.moves
        ]
    )


async def _comparison(client) -> str:
    sectors = snapshot_sectors(client)
    body = equal_weight_request(sectors, [MODEL])
    r = await client.post("/v1/comparisons", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def enable(client, fake=None):
    client.app.state.settings.narration_enabled = True
    client.app.state.narration_client = fake


async def narrate(client, cid, model=MODEL):
    return await client.post(
        f"/v1/comparisons/{cid}/narration", json={"model_id": model}
    )


# --- flag off ---------------------------------------------------------------


async def test_flag_off_returns_template_and_never_calls_the_client(client):
    cid = await _comparison(client)
    fake = FakeNarrationClient(output=echo_valid)
    client.app.state.narration_client = fake  # present but must not be used
    client.app.state.settings.narration_enabled = False

    r = await narrate(client, cid)
    assert r.status_code == 200
    assert r.json() == {
        "model_id": MODEL,
        "source": "template",
        "moves": [],
        "prompt_version": None,
    }
    assert fake.calls == []


# --- happy path -------------------------------------------------------------


async def test_valid_output_is_returned_and_tied_to_the_shifts(client):
    cid = await _comparison(client)
    fake = FakeNarrationClient(output=echo_valid)
    enable(client, fake)

    r = await narrate(client, cid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "claude"
    assert body["prompt_version"]

    resource = (await client.get(f"/v1/comparisons/{cid}")).json()
    shifts = resource["outcomes"][0]["outcome"]["suggested_shifts"]
    assert len(body["moves"]) == len(shifts)
    for got, want in zip(body["moves"], shifts):
        assert got["from_sector"] == want["from_sector"]
        assert got["to_sector"] == want["to_sector"]
        assert got["text"]


async def test_payload_sent_carries_no_identifying_data(client):
    cid = await _comparison(client)
    fake = FakeNarrationClient(output=echo_valid)
    enable(client, fake)
    await narrate(client, cid)

    blob = fake.calls[0].model_dump_json()
    assert client.user_email not in blob
    assert cid not in blob
    assert "100000" not in blob  # initial_value
    bundle = client.app.state.snapshots.get(
        client.app.state.settings.active_snapshot_id
    )
    # Word boundaries, not substrings: the universe holds one-letter tickers
    # like "C", whose letter turns up inside sector names ("Health Care").
    for ticker in bundle.ticker_price:
        assert not re.search(rf"\b{re.escape(ticker)}\b", blob), ticker


async def test_second_identical_request_is_a_cache_hit(client):
    cid = await _comparison(client)
    fake = FakeNarrationClient(output=echo_valid)
    enable(client, fake)

    first = await narrate(client, cid)
    second = await narrate(client, cid)
    assert first.json()["moves"] == second.json()["moves"]
    assert len(fake.calls) == 1


# --- degradation ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_text",
    [
        "You should buy Health Care right now, it is guaranteed to work.",
        "Consider XLE instead, it moves volatility to 9.99%.",
    ],
)
async def test_invalid_output_falls_back_to_template(client, bad_text):
    cid = await _comparison(client)

    def bad(payload):
        return NarrationOutput(
            moves=[
                NarratedMove(
                    from_sector=m.from_sector, to_sector=m.to_sector, text=bad_text
                )
                for m in payload.moves
            ]
        )

    enable(client, FakeNarrationClient(output=bad))
    r = await narrate(client, cid)
    assert r.status_code == 200
    assert r.json()["source"] == "template"
    assert r.json()["moves"] == []


async def test_client_failure_falls_back_to_template(client):
    cid = await _comparison(client)
    enable(client, FakeNarrationClient(exc=TimeoutError("boom")))
    r = await narrate(client, cid)
    assert r.status_code == 200
    assert r.json()["source"] == "template"


async def test_no_client_configured_falls_back_to_template(client):
    """Flag on but no API key: a 200 template, never a 500."""
    cid = await _comparison(client)
    client.app.state.settings.narration_enabled = True
    client.app.state.settings.anthropic_api_key = None
    client.app.state.narration_client = None
    r = await narrate(client, cid)
    assert r.status_code == 200
    assert r.json()["source"] == "template"


# --- access control and limits ---------------------------------------------


async def test_unknown_comparison_404s(client):
    enable(client, FakeNarrationClient(output=echo_valid))
    r = await narrate(client, "11111111-1111-1111-1111-111111111111")
    assert r.status_code == 404


async def test_model_not_in_the_comparison_404s(client):
    cid = await _comparison(client)  # black_litterman only
    enable(client, FakeNarrationClient(output=echo_valid))
    r = await narrate(client, cid, model="monte_carlo")
    assert r.status_code == 404
    assert r.json()["detail"] == "outcome_not_found"


async def test_csrf_header_required(client):
    cid = await _comparison(client)
    enable(client, FakeNarrationClient(output=echo_valid))
    r = await client.post(
        f"/v1/comparisons/{cid}/narration",
        json={"model_id": MODEL},
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403


async def test_rate_limited(client):
    cid = await _comparison(client)
    enable(client, FakeNarrationClient(output=echo_valid))
    # A fresh limiter of 1, and a cache that cannot absorb the second call.
    client.app.state.narration_limiter = SlidingWindowLimiter(1)

    assert (await narrate(client, cid)).status_code == 200
    client.app.state.narration_cache.__init__(256)  # drop the cached result
    second = await narrate(client, cid)
    assert second.status_code == 429
    assert second.headers["Retry-After"]
