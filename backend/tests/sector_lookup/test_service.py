"""cache -> client -> validate -> merge, with fakes. No network."""

from __future__ import annotations

import asyncio

from app.sector_lookup import SectorLookupCache, build_payload, lookup_sectors
from app.sector_lookup.schema import LookupOutput, TickerClassification

MODEL = "test-model"


class FakeClient:
    def __init__(self, answer=None, exc=None, delay=0.0):
        self.answer = answer
        self.exc = exc
        self.delay = delay
        self.calls = []

    async def classify(self, payload):
        self.calls.append(payload)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        if callable(self.answer):
            return self.answer(payload)
        return self.answer

    async def aclose(self):
        pass


def _all(kind="stock", sector="Industrials"):
    def answer(payload):
        return LookupOutput(
            classifications=[
                TickerClassification(
                    ticker=t, kind=kind, sector=sector, confidence="medium",
                    rationale="Makes things.", searched=False,
                )
                for t in payload.tickers
            ]
        )

    return answer


async def _run(client, tickers, cache=None, **kw):
    return await lookup_sectors(
        client=client, payload=build_payload(tickers), cache=cache, model=MODEL, **kw
    )


async def test_no_client_is_unavailable():
    r = await _run(None, ["AAA"])
    assert r.source == "unavailable" and r.suggestions == []


async def test_happy_path_and_cache_hit():
    cache = SectorLookupCache()
    fake = FakeClient(_all())
    r = await _run(fake, ["AAA", "BBB"], cache)
    assert r.source == "model"
    assert [s.ticker for s in r.suggestions] == ["AAA", "BBB"]
    assert r.unchecked == []

    r2 = await _run(fake, ["BBB", "AAA"], cache)
    assert len(fake.calls) == 1  # second lookup served from cache
    assert [s.ticker for s in r2.suggestions] == ["AAA", "BBB"]

    # A cached answer comes back even with no client at all.
    r3 = await _run(None, ["AAA"], cache)
    assert r3.source == "model" and r3.suggestions[0].ticker == "AAA"


async def test_batches_split_and_each_is_validated():
    fake = FakeClient(_all())
    r = await _run(fake, [f"T{i:02d}" for i in range(7)], batch_size=3)
    assert len(fake.calls) == 3
    assert len(r.suggestions) == 7


async def test_client_error_degrades_to_unavailable():
    r = await _run(FakeClient(exc=RuntimeError("boom")), ["AAA"])
    assert r.source == "unavailable"


async def test_client_none_answer_degrades():
    r = await _run(FakeClient(answer=None), ["AAA"])
    assert r.source == "unavailable"


async def test_timeout_degrades():
    # timeout_s + 5s grace is the effective bound; push it below the delay.
    r = await _run(FakeClient(_all(), delay=0.5), ["AAA"], timeout_s=-4.9)
    assert r.source == "unavailable"


async def test_partial_answer_reports_unchecked():
    def only_first(payload):
        return LookupOutput(classifications=_all()(payload).classifications[:1])

    r = await _run(FakeClient(only_first), ["AAA", "BBB"])
    assert r.source == "model"
    assert [s.ticker for s in r.suggestions] == ["AAA"]
    assert r.unchecked == ["BBB"]


async def test_unknown_is_not_cached():
    cache = SectorLookupCache()
    fake = FakeClient(_all(kind="unknown", sector=None))
    await _run(fake, ["AAA"], cache)
    await _run(fake, ["AAA"], cache)
    assert len(fake.calls) == 2


async def test_cache_is_bounded():
    cache = SectorLookupCache(capacity=2)
    await _run(FakeClient(_all()), ["AAA", "BBB", "CCC"], cache)
    assert len(cache._store) == 2
