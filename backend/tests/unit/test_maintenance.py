"""The maintenance sweep: the worker is the only thing that enqueues it."""

from __future__ import annotations

import pytest

from techtrend import cli
from techtrend.platform.config import settings


@pytest.fixture(autouse=True)
def _clear():
    settings.cache_clear()
    yield
    settings.cache_clear()


def _capture(monkeypatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    async def fake_enqueue(stage, key, payload=None, **kw):
        calls.append({"stage": stage, "key": key, **kw})
        return True

    monkeypatch.setattr(cli.queue, "enqueue", fake_enqueue)
    return calls


@pytest.mark.asyncio
async def test_sweep_enqueues_a_maintenance_job(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch)
    monkeypatch.setattr(cli.time, "time", lambda: 1_000_000.0)
    await cli._sweep_maintenance()
    assert calls[0]["stage"] == "maintenance"
    assert calls[0]["priority"] == 200  # behind live pipeline work


@pytest.mark.asyncio
async def test_repeat_sweeps_in_one_bucket_reuse_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop calls this every iteration; ON CONFLICT collapses them to one job."""
    monkeypatch.setenv("TT_MAINTENANCE_INTERVAL_S", "300")
    calls = _capture(monkeypatch)
    # Buckets are aligned to absolute time, so one bucket is [999_900, 1_000_200).
    for t in (1_000_000.0, 1_000_100.0, 1_000_199.0):
        monkeypatch.setattr(cli.time, "time", lambda t=t: t)
        await cli._sweep_maintenance()
    assert len({c["key"] for c in calls}) == 1


@pytest.mark.asyncio
async def test_crossing_the_interval_starts_a_new_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TT_MAINTENANCE_INTERVAL_S", "300")
    calls = _capture(monkeypatch)
    for t in (1_000_000.0, 1_000_400.0):  # different buckets
        monkeypatch.setattr(cli.time, "time", lambda t=t: t)
        await cli._sweep_maintenance()
    assert len({c["key"] for c in calls}) == 2


@pytest.mark.asyncio
async def test_interval_setting_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TT_MAINTENANCE_INTERVAL_S", "60")
    calls = _capture(monkeypatch)
    for t in (1_000_000.0, 1_000_090.0):  # 90s apart: one bucket at 300s, two at 60s
        monkeypatch.setattr(cli.time, "time", lambda t=t: t)
        await cli._sweep_maintenance()
    assert len({c["key"] for c in calls}) == 2


@pytest.mark.asyncio
async def test_buckets_align_to_absolute_time_not_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sweeps seconds apart can straddle a boundary and both enqueue.

    Harmless -- worst case is two maintenance jobs in quick succession -- but
    it means the interval is a ceiling on staleness, not a floor on spacing.
    """
    monkeypatch.setenv("TT_MAINTENANCE_INTERVAL_S", "300")
    calls = _capture(monkeypatch)
    for t in (1_000_199.0, 1_000_201.0):  # 2 seconds apart, either side of a boundary
        monkeypatch.setattr(cli.time, "time", lambda t=t: t)
        await cli._sweep_maintenance()
    assert len({c["key"] for c in calls}) == 2


def test_maintenance_handler_is_registered() -> None:
    assert "maintenance" in cli.HANDLERS
