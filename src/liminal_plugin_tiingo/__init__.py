"""Tiingo (tiingo.com) for Liminal: US stock daily bars from 1962 and Shanghai's and Shenzhen's
A-shares from 2007 with a free account key (a closed archive), its forex minutes from 2020 (a feed
of this plugin on the same key), and Blue Ocean's overnight nights polled live on a paid plan.

A Liminal plugin released on its own, registered under the entry point group `liminal.providers` as
`tiingo`: one plugin, two feeds (PLUGINS: the stocks' daily archive `tiingo`, its forex `tiingofx`),
a class each on the class contract (plugin API 2.0, liminal_lib.sources.plugin: what a feed declares
class attributes, what it does methods): `TiingoPlugin` (TIINGO) and `TiingoForex` (FOREX) share the
base `TiingoFeed`, which holds what both declare and do alike (the key, the plan's view of the
settings, the window kept, the client: one account's limits). It relies on plugin API 2.0 (the
exchanges a feed carries, `exchanges`, so a listing abroad, 600519.SS, comes to it and to no US feed)
and nothing of the app outside it (docs/ARCHITECTURE.md in liminal: "Providers are plugins"); its
version is this distribution's (pyproject.toml), so the classes' versions are left empty.

Its scan (`capabilities`, one request each) asks what else the account's plan gives: IEX's minute
bars (one exchange), forex and crypto bars, and Blue Ocean's overnight bars (a paid add-on,
2026-10-27: $9 a month; Alpaca's free plan has them: the Alpaca plugin's BOATS, and from earlier:
Tiingo had none before 2024-09-25, asked 2026-10-28). The stocks' daily bars are collected here, the
forex minutes on a feed of this plugin on this key's limits (FOREX below: tiingo (forex)).

Its plan is found in part: Tiingo's API has no account endpoint and sends no rate-limit headers
(2026-10-27), but its News API is the paid plans' (Power, Commercial) and not Starter's (the pricing
table, 2026-10-27), so the scan's News request tells Starter from a paid plan. Power and Commercial
reach the same data at other limits: a paid key is taken for Power, the lower limits, unless
TIINGO_PLAN says commercial (starter, the default; power; commercial: the key script and the Plugins
view offer them). It also asks for the fundamentals add-on, of a stock outside the Dow 30 (those
are free to evaluate)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from liminal_lib.config import Tier
from liminal_lib.errors import SourceError
from liminal_lib.freshness import Delay
from liminal_lib.sources.archive import ET
from liminal_lib.sources.http import PublicClient
from liminal_lib.sources.registry import FeedPlugin, KeyVar, MachineLedger, Scanned, limiter, machine_caps
from liminal_lib.sources.stream import Live, session_at
from .client import TiingoFxSource, TiingoSource

API = "https://api.tiingo.com"
KEY = "TIINGO_API_KEY"  # a free tiingo.com account's token, a user environment variable (the app's set-key.ps1)
# Its free plan and caps (once the app's config.PUBLIC_FEEDS["tiingo"]): Starter allows 50 requests an
# hour and 1,000 a day; kept a little inside.
TIER = Tier("tiingo-free", requests_per_minute=None, history_years=None, history_start=date(1962, 1, 1))
PER_RUN, PER_DAY = 45, 900
# Blue Ocean's night under way, live from Tiingo (BoatsPoller): a feed of its own, one venue's nights
TIINGO_BOATS = "tiingoboats"
BARS = "open,high,low,close,volume"

# Tiingo's plans (tiingo.com/about/pricing, both tables: "I am an Individual" and "I am a Business or
# Organization", 2026-10-27), each kept a little inside: (plan, requests an hour (a run's cap too: the
# sync runs hourly), a day, different symbols a month).
#   Starter (free): 50 an hour, 1,000 a day, 500 symbols, 1 GB a month.
#   Power (individuals, $30 a month or $300 a year): 10,000 an hour, 100,000 a day, every symbol
#     (110,397), 40 GB a month.
#   Commercial (a business's internal use, up to two developers, $50 a month or $499 a year): 20,000 an
#     hour, 150,000 a day, every symbol, 100 GB a month.
# Enterprise and redistribution are priced by Tiingo's sales, with no published limits: not offered.
PLANS = {
    "starter": (TIER, PER_RUN, PER_DAY, 450),
    "power": (replace(TIER, name="tiingo-power"), 9_500, 95_000, None),
    "commercial": (replace(TIER, name="tiingo-commercial"), 19_000, 142_500, None),
}
ALIASES = {"free": "starter", "business": "commercial"}
PLAN_NOTE = ("Tiingo's API does not say which plan a key is on (no account endpoint, no rate-limit headers). "
             "Its scan tells Starter from a paid plan by the News API, which only Power and Commercial have; "
             "it cannot tell Power from Commercial (the same data, other limits), so a paid key gets Power's "
             "limits unless you set TIINGO_PLAN=commercial")
NEWS = "news (the paid plans: Power and Commercial, not Starter)"
FUNDAMENTALS = "fundamentals (an add-on; asked for ROKU: the Dow 30 are free to evaluate)"


def api_key(settings) -> str | None:
    """The Tiingo key among the settings' plugin variables (Settings.env), spaces around it taken off
    (one pasted with a newline made every request fail), or None."""
    return (settings.env.get(KEY) or "").strip() or None


def listings_on(settings) -> bool:
    """TIINGO_LISTINGS: whether the A-shares are listed in the directory from Tiingo's supported-tickers
    file (about 10 MB, at each directory refresh while on)."""
    return (settings.env.get("TIINGO_LISTINGS") or "").strip().lower() in ("on", "1", "true", "yes")


def plan_of(settings) -> str:
    """TIINGO_PLAN's plan (an unknown value: Starter, the free plan's limits, never more)."""
    name = (settings.env.get("TIINGO_PLAN") or "starter").strip().lower()
    name = ALIASES.get(name, name)
    return name if name in PLANS else "starter"


def monthly_symbols(source, settings, key):
    """The plan's different symbols a month on a Tiingo source (the app's collector._monthly_symbol),
    counted for the key on the whole machine: its stocks and its forex (FOREX) take the same places."""
    source.symbols_per_month = PLANS[plan_of(settings)][3]
    source.symbol_ledger = MachineLedger("tiingo:symbols", key)
    return source


def probes(today: date) -> list[tuple[str, str, dict]]:
    """(what, path, params) of the scan: a recent weekday of a busy symbol at each endpoint."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    d = day.isoformat()
    return [
        ("stock daily bars, from 1962", "/tiingo/daily/AAPL/prices", {"startDate": d, "endDate": d}),
        ("stock 1-minute bars from IEX (one exchange)", "/iex/AAPL/prices",
         {"startDate": d, "endDate": d, "resampleFreq": "1min", "afterHours": "true", "columns": BARS}),
        ("stock overnight bars from Blue Ocean (20:00-04:00)", "/boats/AAPL/prices",
         {"startDate": d, "endDate": d, "resampleFreq": "1min", "columns": BARS}),
        ("forex 1-minute bars", "/tiingo/fx/prices", {"tickers": "eurusd", "startDate": d, "endDate": d,
                                                      "resampleFreq": "1min"}),
        ("crypto bars", "/tiingo/crypto/prices", {"tickers": "btcusd", "startDate": d, "endDate": d,
                                                  "resampleFreq": "1min"}),
        (NEWS, "/tiingo/news", {"tickers": "aapl", "limit": 1, "startDate": d}),
        (FUNDAMENTALS, "/tiingo/fundamentals/ROKU/daily", {"startDate": d, "endDate": d, "columns": "marketCap"}),
    ]


def rows_of(answer) -> int:
    """Bars in an answer: a list of bars, or crypto's [{priceData: [...]}]."""
    if isinstance(answer, list) and answer and isinstance(answer[0], dict) and "priceData" in answer[0]:
        return sum(len(a.get("priceData") or []) for a in answer)
    return len(answer) if isinstance(answer, list) else 0


# -- Blue Ocean's night, live: tiingo (blue ocean) ------------------------------------------------

def boats_live(settings) -> bool:
    """Whether Blue Ocean's nights are polled live from Tiingo (BoatsPoller): online, live stocks
    on, Tiingo's key set and a paid plan (Power or Commercial: Starter's 50 requests an hour would
    all go on this)."""
    if settings.offline or not settings.live_stocks or not api_key(settings):
        return False
    return plan_of(settings) != "starter"


def _iso_ms(text: str) -> int:
    """Tiingo's time (2026-10-28T07:43:00.000Z, or with an offset and nanoseconds) in ms."""
    text = str(text).replace("Z", "+00:00")
    head, _, rest = text.partition(".")
    if not rest:
        return int(datetime.fromisoformat(head).timestamp() * 1000)
    cut = next((i for i, ch in enumerate(rest) if ch in "+-"), len(rest))  # nanoseconds: microseconds kept
    return int(datetime.fromisoformat(f"{head}.{rest[:cut][:6]}{rest[cut:]}").timestamp() * 1000)


class BoatsPoller:
    """Blue Ocean's overnight session (20:00-04:00 ET, Sunday to Thursday nights), live, from Tiingo's
    REST API: it has no stream for it, but its answers are real time (the newest minute half a minute
    old, asked 2026-10-28 at 03:43 ET); Alpaca's real-time nights are a paid plan, its free one 16
    minutes behind. While a night is open, for the stocks open on a chart (the recorder's wanted
    stocks): their last sale and quote every BOATS_QUOTE_SECONDS, one request for them all (the
    price the pages show); and each one's minutes of the night every BOATS_BARS_SECONDS or so, the
    minutes over stored as the feed's own bars, the forming one as a built bar its final bar
    replaces (TIINGO_BOATS, one of the app's PARTIAL_FEEDS: a chart of all feeds shows them where no
    other feed has the night yet). On the Tiingo key's limits: its window and day cap (the client),
    its kills (a 429 or a refused key kills Tiingo's fetching, and this stops with it)."""

    source = TIINGO_BOATS
    account = "tiingo"  # the feed whose key, limits and kills these requests are
    title = "Blue Ocean from Tiingo"  # in the recorder's log

    def __init__(self, client, now=None):
        self.client = client
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.quotes_at = float("-inf")  # monotonic: the last quote request
        self.bars_at: dict[str, float] = {}  # ticker -> monotonic: its minutes last asked for
        self.final_to: dict[str, int] = {}  # ticker -> ms: its minutes stored final up to here
        self.refused_until = float("-inf")  # monotonic: Blue Ocean refused (no add-on) until then

    @staticmethod
    def symbol(ticker: str) -> str:
        return ticker.upper().replace(".", "-").lower()  # Tiingo's: brk-b

    @classmethod
    def url(cls, ticker: str) -> str:
        """Where a stock's minutes of the night come from (their provenance)."""
        return f"{API}/boats/{cls.symbol(ticker)}/prices"

    def night(self, t: datetime):
        """The Blue Ocean session open at `t` (the app's sessions.Session), or None."""
        return session_at("overnight", t)

    def quotes(self, tickers) -> dict[str, dict]:
        """{ticker: {price, last (ms), bid, ask}}: the last sale and quote of each, one request."""
        names = {self.symbol(t): t.upper() for t in tickers}
        rows = self.client.get("/boats/", {"tickers": ",".join(names)})
        out = {}
        for r in rows if isinstance(rows, list) else []:
            ticker = names.get(str(r.get("ticker") or "").lower())
            if ticker and r.get("last") is not None and r.get("lastSaleTimestamp"):
                out[ticker] = {"price": float(r["last"]), "last": _iso_ms(r["lastSaleTimestamp"]),
                               "bid": r.get("bidPrice"), "ask": r.get("askPrice")}
        return out

    def minutes(self, ticker: str, night, since_ms: int = 0) -> list[dict]:
        """The night's minutes from `since_ms` (its open at the latest), the forming one too (oldest
        first). Tiingo reads its dates in New York and, without an endDate, answers only startDate's
        hours before 04:00 ET: asked as the open's UTC date alone, a night came back empty all
        evening (2026-10-28). So from the New York date of the first minute wanted (the open's until
        the minutes after midnight are stored: the night before's last hours come with it, left out
        here) to the close's."""
        lo = int(night.open.timestamp() * 1000)
        first = datetime.fromtimestamp(max(lo, since_ms) / 1000, ET).date()
        rows = self.client.get(f"/boats/{self.symbol(ticker)}/prices",
                               {"startDate": first.isoformat(), "endDate": night.close.astimezone(ET).date().isoformat(),
                                "resampleFreq": "1min", "columns": "open,high,low,close,volume"})
        bars = []
        for r in rows if isinstance(rows, list) else []:
            t = _iso_ms(r["date"])
            if t >= lo:
                bars.append({"t": t, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                             "c": float(r["close"]), "v": float(r.get("volume") or 0), "vw": None, "n": None})
        return sorted(bars, key=lambda b: b["t"])


# -- the feeds: one plugin, two classes on a base of their own ------------------------------------

class TiingoFeed(FeedPlugin):
    """What Tiingo's two feeds declare and do alike, on one account's key: where it is made and whether
    it is set, the plan's view of the app's settings (TIINGO_PLAN's caps and tier: `view`), the window
    the limiter keeps (`rate`: Starter's 50 an hour), and the client on the key, its window and day cap
    held for the machine under Tiingo's name (`client`: one account's limits, for both feeds)."""

    api = "2.0"  # the contract this plugin is written for (the classes; exchanges; MachineLedger, session_at); its version: the distribution's
    keys = (KeyVar(KEY),)
    signup = "tiingo.com: a free account's API token"

    def view(self, base):
        tier, per_run, per_day, _ = PLANS[plan_of(base)]
        return replace(base, tier=tier, max_requests_per_run=per_run, max_requests_per_day=per_day, origin=base)

    def rate(self, settings):
        return PLANS[plan_of(settings)][1], 3600.0  # Starter: 50 an hour

    def has_keys(self, settings) -> bool:
        return bool(api_key(settings))

    def client(self, settings, request_budget):
        """Tiingo's client on the key (the headers), its window and day cap held for the machine under
        Tiingo's name: one account's limits, for both feeds. Returns (the client, the key or None)."""
        key = api_key(settings)
        headers = {"Authorization": f"Token {key}"} if key else {}
        client = PublicClient(API, headers=headers, request_budget=request_budget,
                              rate_limiter=limiter("tiingo", settings, key))
        return machine_caps(client, "tiingo", settings, key), key


class TiingoPlugin(TiingoFeed):
    """Tiingo's stocks: the daily archive (US listings and the A-shares), its plan's report, its scan,
    and Blue Ocean's nights polled live on a paid plan."""

    name = "tiingo"
    title = "Tiingo"
    about = "US stock daily bars from 1962, Shanghai's and Shenzhen's A-shares from 2007 (a free account key)"
    order = 60
    assets = frozenset({"stock"})
    exchanges = frozenset({"US", "XSHG", "XSHE"})  # every US listing, and the A-shares (600519.SS, 000001.SZ)
    options = ("TIINGO_LISTINGS",)  # on: the A-shares listed in the directory from the supported-tickers file (~10 MB)
    archival = True
    tier = TIER
    per_run = PER_RUN
    per_day = PER_DAY
    limits = ("Starter (free): 50 requests an hour, 1,000 a day, 500 symbols and 1 GB a month; "
              "Power ($30 a month): 10,000 an hour, 100,000 a day, 40 GB a month; "
              "Commercial ($50 a month, a business): 20,000 an hour, 150,000 a day, 100 GB a month")
    symbols_per_month = 450  # Starter's 500 different symbols a month, a little inside (Power: PLANS)
    plan_vars = ("TIINGO_PLAN",)
    # TIINGO_LISTINGS: its choices, so the Plugins view offers it (off, the default, first)
    plan_choices = {"TIINGO_PLAN": tuple(PLANS), "TIINGO_LISTINGS": ("off", "on")}
    plan_note = PLAN_NOTE
    provides = {"stock": ("day",)}
    per_request = {"day": None}  # one request: a symbol's whole history

    def build(self, settings, request_budget):
        client, key = self.client(settings, request_budget)
        source = TiingoSource(client, has_key=bool(key), listings_on=listings_on(settings))
        return monthly_symbols(source, settings, key)

    def reporter(self, report, settings):
        """Its plan's symbols a month: TIINGO_PLAN's, or without the settings (the delivery scheme's
        reports) the plan its tier names: a paid plan's report said Starter's 450 to the scheme."""
        plan = plan_of(settings) if settings is not None else next(
            (name for name, p in PLANS.items() if p[0].name == report.plan), "starter")
        return replace(report, limits=replace(report.limits, symbols_a_month=PLANS[plan][3]))

    def markets(self, settings):
        return {"stock": "sip"}

    def scan(self, source, today: date | None = None) -> Scanned:
        """Each probe once; the plan from the News request: news served (articles), a paid plan
        (Power's limits, the lower: Commercial's answers are the same); refused by the plan (401, 403),
        Starter; anything else (a timeout, a server error, an answer without articles: an error said
        in a 200, an empty list), no plan: a paid plan's far higher limits are never taken on less."""
        out, plan, alike = [], {}, {}
        for what, path, params in probes(today or date.today()):
            try:
                answer = source.client.get(path, params)
                n = rows_of(answer)
            except SourceError as e:  # NotEntitled included: a refusal names the add-on it needs
                out.append((what, False, str(e)[:200]))
                if what == NEWS and e.status in (401, 403):
                    plan["TIINGO_PLAN"] = "starter"
                continue
            if what == NEWS:
                articles = isinstance(answer, list) and any(isinstance(a, dict) and (a.get("title") or a.get("id"))
                                                            for a in answer)
                if not articles:
                    out.append((what, False, f"answered without articles ({str(answer)[:120]}): the plan is not told"))
                    continue
                plan["TIINGO_PLAN"], alike["TIINGO_PLAN"] = "power", ("commercial",)
                out.append((what, True, "served: a paid plan, Power or Commercial (the same data)"))
            elif what == FUNDAMENTALS:
                out.append((what, True, f"served: the add-on ({n:,} rows)"))
            else:
                out.append((what, True, f"{n:,} bars for {params['startDate']}"))
        return Scanned(tuple(out), plan, alike)

    def night_poller(self, settings) -> BoatsPoller | None:
        """The poller of Blue Ocean's nights, on Tiingo's key's limits (its client: the window and day
        cap), when they are polled here (boats_live)."""
        return BoatsPoller(self.build(settings, None).client) if boats_live(settings) else None

    @property
    def live(self):
        """Blue Ocean's night under way, polled from Tiingo (tiingo (blue ocean)): one venue's nights."""
        return (Live(TIINGO_BOATS, "stock", poller=self.night_poller, label="tiingo (blue ocean)", partial=True),)


# -- its forex: tiingo (forex) -----------------------------------------------------------------------
# Currency pairs' 1-minute bars from 2020, with the Tiingo key: a feed of this plugin (the user,
# 2026-10-30: "tiingo should be one plugin"), its own database file and watch rows (`tiingofx`), kept
# up to date, on Tiingo's limits: one account, so one rate window and one daily cap for both feeds.
# Its data is Tiingo's own (its own market here), not a copy of Massive's currencies. Taken to spend
# the paid plan's allowance, which the stocks' daily bars leave almost all unused (the user, 2026-10-28).
# Its currencies' history: from Tiingo's first forex minute (its plan's other limits are Tiingo's)
FX_TIER = Tier("tiingofx", requests_per_minute=None, history_years=None, history_start=TiingoFxSource.START)


class TiingoForex(TiingoFeed):
    """Tiingo's forex, a part of this plugin: the currencies' minutes on the same key and limits as the
    stocks, their history from 2020."""

    name = "tiingofx"
    title = "Forex"
    about = "currency pairs' 1-minute bars from 2020, from Tiingo (its key and limits)"
    order = 61
    account = "tiingo"
    part_of = "tiingo"
    assets = frozenset({"fx"})
    kind = "vendor"
    provides = {"fx": ("minute",)}
    per_request = {"minute": TiingoFxSource.WINDOW_DAYS * 1440}
    limits = "shares Tiingo's: its plan's requests an hour and a day, for both feeds"
    missing_keys_note = "key not set: Tiingo's forex comes with TIINGO_API_KEY"
    # When it publishes (the row the library's freshness.PLAN_DELAYS held for it, declared by the feed
    # itself since 2.0): taken for history, whole UTC days, through the day before (how soon its newest
    # minutes are final is not known; a minute asked too soon and found empty would be counted as held
    # and never asked again).
    delays = {"tiingofx": {"fx": Delay("utc_day")}}

    def view(self, base):
        """Tiingo's plan (its caps and window, TIINGO_PLAN), with the currencies' history from 2020."""
        out = super().view(base)
        return replace(out, tier=replace(out.tier, by_asset=(("fx", FX_TIER),)))

    def build(self, settings, request_budget):
        client, key = self.client(settings, request_budget)
        # its pairs take places among the plan's different symbols a month, with Tiingo's stocks
        return monthly_symbols(TiingoFxSource(client, has_key=bool(key)), settings, key)

    def markets(self, settings):
        return {"fx": "tiingofx"}


TIINGO, FOREX = TiingoPlugin(), TiingoForex()
PLUGINS = (TIINGO, FOREX)  # one plugin, two feeds: the stocks' daily archive, and its forex minutes
