"""The Tiingo plugin, run against the app installed beside it: its daily bars and their split
adjustment, its forex windows, its plans, its Blue Ocean poller's reading, and the app loading its
two feeds from this package with its own version and the facts they had as built-ins."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from importlib.metadata import version

import pytest

from liminal_lib import freshness
from liminal_lib.collector import history_floor
from liminal_lib.config import load_settings
from liminal_lib.errors import NotEntitled
from liminal_lib.sources import feed_profiles, is_archive, markets, provider, providers, rate_window, registry, supports
from liminal_lib.sources.archive import ET, ms
from liminal_lib.sources.http import PublicClient
from liminal_lib.symbols import resolve

import liminal_plugin_tiingo as tiingo
from liminal_plugin_tiingo import PER_DAY, PER_RUN, TIER, TIINGO_BOATS, BoatsPoller, _iso_ms, boats_live, plan_of
from liminal_plugin_tiingo.client import TiingoFxSource, TiingoSource, split_adjust

from .conftest import FakeResponse, FakeSession

KEYS = {"TIINGO_API_KEY": "k"}


def _client(responses):
    session = FakeSession(responses)
    return PublicClient("https://x.test/api", session=session, sleep=lambda s: None), session


def test_tiingo_is_split_adjusted_only_and_needs_a_key():
    rows = [{"date": "2020-08-27T00:00:00.000Z", "open": 500.0, "high": 510.0, "low": 490.0, "close": 500.0,
             "volume": 100, "splitFactor": 1.0, "divCash": 0.8},
            {"date": "2020-08-31T00:00:00.000Z", "open": 127.0, "high": 131.0, "low": 126.0, "close": 129.0,
             "volume": 400, "splitFactor": 4.0, "divCash": 0.0}]
    out = split_adjust(rows)
    assert out[0]["c"] == 125.0 and out[0]["v"] == 400.0  # before the 4:1 split: /4 prices, x4 volume
    assert out[1]["c"] == 129.0 and out[1]["v"] == 400.0  # the split day is already in new shares
    assert out[0]["t"] == ms(datetime(2020, 8, 27, tzinfo=ET))
    client, session = _client([FakeResponse(200, rows)])
    keyed = TiingoSource(PublicClient("https://api.tiingo.com", headers={"Authorization": "Token K"},
                                      session=session, sleep=lambda s: None), has_key=True)
    bars = next(keyed.bar_pages("BRK.B", date(2020, 1, 1), date(2020, 12, 31), "day"))
    assert len(bars) == 2 and session.calls[0][0].endswith("/tiingo/daily/BRK-B/prices")
    assert session.calls[0][2]["Authorization"] == "Token K"
    keyless = TiingoSource(_client([])[0], has_key=False)
    assert not keyless.serves("stock") and keyless.resolutions("stock") == ()
    with pytest.raises(NotEntitled):
        next(keyless.bar_pages("AAPL", date(2020, 1, 1), date(2020, 1, 2), "day"))


class FakeTiingo:
    """Answers /tiingo/fx/prices with a bar every 6 hours of the days asked."""

    def __init__(self):
        self.asked = []
        self.requests_made = 0

    def get(self, path, params):
        self.asked.append((path, dict(params)))
        self.requests_made += 1
        d, last = date.fromisoformat(params["startDate"]), date.fromisoformat(params["endDate"])
        rows = []
        while d <= last:
            for h in (0, 6, 12, 18):
                t = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
                rows.append({"date": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "ticker": params["tickers"],
                             "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15})
            d += timedelta(days=1)
        return rows


def test_a_forex_pair_is_asked_three_whole_days_at_a_time_newest_first():
    client = FakeTiingo()
    pages = list(TiingoFxSource(client, has_key=True).bar_pages(
        "C:EURUSD", date(2026, 10, 20), date(2026, 10, 27), "minute", descending=True, asset="fx"))
    assert [(p["startDate"], p["endDate"]) for _, p in client.asked] == [
        ("2026-10-26", "2026-10-27"), ("2026-10-23", "2026-10-25"), ("2026-10-20", "2026-10-22")]
    assert {p["tickers"] for _, p in client.asked} == {"eurusd"} and client.asked[0][0] == "/tiingo/fx/prices"
    assert [len(p) for p in pages] == [8, 12, 12]
    first = pages[0]
    assert first[0]["t"] > first[-1]["t"] and first[0]["v"] is None  # newest first; forex has no volume
    day = 86_400_000
    lo = int(datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp() * 1000)
    assert first.window == (lo, lo + 2 * day)  # each window recorded, empty or not
    inst = TiingoFxSource(client, has_key=True).instrument("C:EURUSD")
    assert inst.ticker == "EURUSD" and inst.details["venue"] == "Tiingo"


def test_nothing_before_2020_is_asked_and_only_minutes_with_a_key():
    client = FakeTiingo()
    pages = list(TiingoFxSource(client, has_key=True).bar_pages(
        "C:GBPUSD", date(2019, 12, 1), date(2020, 1, 2), "minute", asset="fx"))
    assert client.asked[0][1]["startDate"] == "2020-01-01" and len(client.asked) == 1  # Tiingo refuses earlier
    assert sum(len(p) for p in pages) == 8
    with pytest.raises(NotEntitled):
        next(TiingoFxSource(client, has_key=True).bar_pages("C:EURUSD", date(2026, 1, 5), date(2026, 1, 5), "hour"))
    with pytest.raises(NotEntitled):
        next(TiingoFxSource(client, has_key=False).bar_pages("C:EURUSD", date(2026, 1, 5), date(2026, 1, 5), "minute"))


def test_its_plans_are_your_choice_and_kept_inside_what_tiingo_publishes():
    for env, plan in (({}, "starter"), ({"TIINGO_PLAN": "free"}, "starter"), ({"TIINGO_PLAN": "Business"}, "commercial"),
                      ({"TIINGO_PLAN": "power"}, "power"), ({"TIINGO_PLAN": "gold"}, "starter")):
        assert plan_of(load_settings(env={**KEYS, **env}, env_file=None)) == plan  # unknown: never more than Starter
    published = {"starter": (50, 1_000), "power": (10_000, 100_000), "commercial": (20_000, 150_000)}
    for name, (_, per_hour, per_day, _) in tiingo.PLANS.items():  # each a little inside what Tiingo publishes
        assert per_hour <= published[name][0] * 0.95 and per_day <= published[name][1] * 0.95
    assert tiingo.PLANS["starter"][:3] == (TIER, PER_RUN, PER_DAY)
    assert "no account endpoint, no rate-limit headers" in tiingo.PLAN_NOTE
    assert len(tiingo.probes(date(2026, 10, 27))) == 7 and tiingo.probes(date(2026, 10, 27))[0][2]["startDate"] == "2026-10-26"
    assert tiingo.api_key(load_settings(env={"TIINGO_API_KEY": " k\n"}, env_file=None)) == "k"  # pasted with a newline


def test_the_night_is_polled_only_on_a_paid_plan_with_live_stocks_online_and_its_times_are_read():
    assert boats_live(load_settings(env={**KEYS, "TIINGO_PLAN": "power"}, env_file=None))
    assert not boats_live(load_settings(env=KEYS, env_file=None))  # Starter: 50 an hour would all go on this
    assert not boats_live(load_settings(env={**KEYS, "TIINGO_PLAN": "power", "LIVE_STOCKS": "off"}, env_file=None))
    assert not boats_live(load_settings(env={"TIINGO_PLAN": "power"}, env_file=None))  # no key
    assert not boats_live(load_settings(env={**KEYS, "TIINGO_PLAN": "power", "LIMINAL_OFFLINE": "1"}, env_file=None))
    assert BoatsPoller.symbol("BRK.B") == "brk-b" and BoatsPoller.url("BRK.B") == "https://api.tiingo.com/boats/brk-b/prices"
    at = lambda *a, **k: int(datetime(*a, **k, tzinfo=ET).timestamp() * 1000)  # noqa: E731
    assert _iso_ms("2026-10-28T03:43:14.003025142-04:00") == at(2026, 10, 28, 3, 43, 14, 3025)
    assert _iso_ms("2026-10-28T07:43:00.000Z") == at(2026, 10, 28, 3, 43)
    poller = BoatsPoller(client=None)  # as the recorder makes it (night_poller): the clock is its own
    assert poller.now().tzinfo is timezone.utc and poller.source == TIINGO_BOATS and poller.account == "tiingo"
    night = poller.night(datetime(2026, 10, 27, 23, 5, tzinfo=ET))  # a Tuesday night: Blue Ocean trades
    assert night is not None and night.open <= datetime(2026, 10, 27, 23, 5, tzinfo=ET) < night.close
    assert poller.night(datetime(2026, 10, 28, 12, 0, tzinfo=ET)) is None  # by day


def test_the_app_loads_its_two_feeds_from_this_package_with_its_own_version():
    registry.reload()
    assert [p.name for p in tiingo.PLUGINS] == ["tiingo", "tiingofx"] and not hasattr(tiingo, "PLUGIN")
    for name in ("tiingo", "tiingofx"):
        p = provider(name)
        assert p is not None, dict(registry.errors())
        assert p.origin in {"package: liminal-plugin-tiingo (liminal_plugin_tiingo)", "plugins/liminal-plugin-tiingo (liminal_plugin_tiingo)"}  # its package, or its checkout in the workspace\'s plugin directory
        assert p.version == version("liminal-plugin-tiingo") and p.api == "1.10"
        assert registry.api_refusal(p.api) is None
    assert tiingo.TIINGO.version == "" and tiingo.FOREX.version == ""
    assert not [why for where, why in registry.errors() if "tiingo" in where or "tiingo" in why]
    row = {r["name"]: r for r in registry.menu()}["tiingo"]
    assert (row["version"], row["api"]) == (version("liminal-plugin-tiingo"), "1.10")
    assert registry.plugin_feeds("tiingo") == ["tiingo", "tiingofx"] and registry.plugin_of("tiingofx") == "tiingo"


def test_it_keeps_the_facts_it_had_built_in(monkeypatch):
    registry.reload()
    s = load_settings(env=KEYS, env_file=None)
    view = s.for_source("tiingo")
    assert (view.tier, view.max_requests_per_run, view.max_requests_per_day) == (TIER, PER_RUN, PER_DAY)
    assert rate_window("tiingo", s) == (45, 3600.0) and rate_window("tiingofx", s) == rate_window("tiingo", s)
    power = load_settings(env={**KEYS, "TIINGO_PLAN": "power"}, env_file=None)
    assert power.for_source("tiingo").tier.name == "tiingo-power" and power.for_source("tiingo").max_requests_per_day == 95_000
    assert is_archive("tiingo") and not is_archive("tiingofx")
    assert markets("tiingo", s) == {"stock": "sip"} and markets("tiingofx", s) == {"fx": "tiingofx"}
    assert supports("tiingo", resolve("AAPL")) and not supports("tiingo", resolve("EURUSD"))
    assert history_floor(view.tier, date(2026, 10, 27)) == date(1962, 1, 1)
    fx = power.for_source("tiingofx")
    assert fx.tier.name == "tiingo-power" and history_floor(fx.tier, date(2026, 10, 28), "fx") == date(2020, 1, 1)
    assert freshness.plan_delay(fx.tier, "fx").kind == "utc_day"  # whole days: history, not live
    assert feed_profiles(power)["tiingofx"].venues == {"fx": "tiingofx"}  # its own market
    assert not feed_profiles(load_settings(env={}, env_file=None))["tiingofx"].assets  # no key: serves nothing
    assert feed_profiles(load_settings(env={}, env_file=None))["tiingo"].assets == frozenset()
    fxp = provider("tiingofx")
    assert (fxp.title, fxp.part_of, fxp.account, fxp.archival) == ("Forex", "tiingo", "tiingo", False)
    assert [(f.name, f.asset, f.partial) for f in provider("tiingo").live] == [(TIINGO_BOATS, "stock", True)]
    # one account: the window and the day's cap are held under Tiingo's name, shared with its stocks feed
    held = []
    monkeypatch.setattr(tiingo, "limiter", lambda name, st, key: held.append(("window", name)))
    monkeypatch.setattr(tiingo, "machine_caps", lambda client, name, st, key: held.append(("day", name)) or client)
    source = tiingo.build_forex(power, 5)
    assert held == [("window", "tiingo"), ("day", "tiingo")] and source.name == "tiingofx"
    assert source.symbols_per_month is None and tiingo.build(s, 5).symbols_per_month == 450  # Power: every symbol
