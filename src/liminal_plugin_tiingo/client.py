"""Tiingo's sources (tiingo.com): the stocks' daily bars from 1962 (the US) and 2007 (Shanghai's and
Shenzhen's A-shares), adjusted here for splits only (from Tiingo's split factors, so they continue the
other feeds' split-adjusted bars without a dividend seam), and the currencies' 1-minute bars from 2020;
on the app's keyless client with Tiingo's token."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

from liminal_lib.errors import NotEntitled, SourceError
from liminal_lib.models import Exchange, Instrument, Stock, country, exchange_name, listing_ticker, suffix_mic
from liminal_lib.sources.archive import ET, Archive as _Archive, bounds as _bounds, ms as _ms
from liminal_lib.sources.base import Page
from liminal_lib.sources.http import PublicClient

# The exchanges abroad Tiingo carries here (plugin API 1.12: Provider.exchanges), by Tiingo's exchange
# code: Shanghai's and Shenzhen's A-shares, which it lists under their bare codes (asked 2026-11-02:
# /tiingo/daily/600519 answers exchangeCode SHG and startDate 2007-01-04; 000001, SHE). A listing is
# stored as 600519.SS and 000001.SZ (the library's notation) and asked for by its code.
EXCHANGE_CODES = {"XSHG": "SHG", "XSHE": "SHE"}
MICS = {code: mic for mic, code in EXCHANGE_CODES.items()}
FILES = "https://apimedia.tiingo.com"  # Tiingo's files, apart from its API (no key goes there)
SUPPORTED_TICKERS = FILES + "/docs/tiingo/daily/supported_tickers.zip"  # every ticker it serves, ~10 MB
LISTING_DAYS = 14  # a listing Tiingo last served longer ago than this is no longer listed


def tiingo_symbol(ticker: str) -> str:
    """Tiingo's name for a stock: BRK-B for BRK.B; a listing abroad by its bare code (600519 for 600519.SS)."""
    t = ticker.upper()
    base, dot, tail = t.rpartition(".")
    if base and dot and suffix_mic(tail) in EXCHANGE_CODES:
        return base
    return t.replace(".", "-")


def split_adjust(rows: list[dict]) -> list[dict]:
    """Tiingo's raw daily rows (oldest first, with splitFactor on split days) as split-adjusted bars:
    prices divided, volume multiplied, by the product of every later split. Dividends are not
    adjusted (the other feeds' bars are split-adjusted only)."""
    out = []
    factor = 1.0
    for r in reversed(rows):
        d = datetime.fromisoformat(r["date"].replace("Z", "+00:00")).date()
        p = lambda k: (float(r[k]) / factor) if r.get(k) is not None else None  # noqa: E731
        out.append({"t": _ms(datetime(d.year, d.month, d.day, tzinfo=ET)), "o": p("open"), "h": p("high"),
                    "l": p("low"), "c": p("close"), "v": float(r["volume"]) * factor if r.get("volume") is not None else None,
                    "vw": None, "n": None})
        split = float(r.get("splitFactor") or 1.0)
        if split and split != 1.0:
            factor *= split  # this day's split applies to every earlier day
    return out[::-1]


class TiingoSource(_Archive):
    """Stock daily history with a free Tiingo key: the US from 1962, Shanghai's and Shenzhen's A-shares
    from 2007. One request returns a symbol's whole history (needed anyway: a split today changes
    the adjustment of every earlier day)."""

    name = "tiingo"
    assets = ("stock",)

    def __init__(self, client: PublicClient, has_key: bool, listings_on: bool = False, today: date | None = None,
                 files: PublicClient | None = None):
        super().__init__(client)
        self.has_key = has_key
        self.files = files  # a keyless client of Tiingo's file host (the API client sends the key to its host alone)
        self.listings_on = listings_on  # TIINGO_LISTINGS: the A-shares listed from the supported-tickers file
        self.today = today
        self._history: dict[str, list[dict]] = {}
        self._supported: list[dict] | None = None

    def serves(self, asset: str) -> bool:
        return asset == "stock" and self.has_key

    def resolutions(self, asset: str) -> tuple[str, ...]:
        return ("day",) if asset == "stock" and self.has_key else ()

    def exchanges(self) -> list[Exchange]:
        """The exchanges abroad it carries (plugin API 1.12), by name: Shanghai and Shenzhen. The US
        exchanges' rows are the whole-market feeds'."""
        return [Exchange(self.name, i, exchange_name(mic) or mic, country("CN"), mic=mic, acronym=code, type="exchange")
                for i, (mic, code) in enumerate(sorted(EXCHANGE_CODES.items()), 1)]

    def instrument(self, ticker: str, resolve_exchange: bool = True) -> Instrument:
        """A listing abroad's record (one request): its name, its exchange, and Tiingo's first day of
        it (2007-01-04 for the A-shares: Tiingo's start, not the listing's). A US stock's identity is
        the whole-market feeds' (Massive's record dates it: the Archive's rule)."""
        if not self.has_key:
            raise NotEntitled(401, "TIINGO_API_KEY not set; nothing sent")
        sym = tiingo_symbol(ticker)
        if sym == ticker.upper().replace(".", "-"):
            raise NotImplementedError("tiingo has no reference data for US stocks here")
        r = self.client.get(f"/tiingo/daily/{sym}")
        if not isinstance(r, dict) or not r.get("ticker"):
            raise SourceError(0, f"unexpected Tiingo answer for {sym}")
        code = str(r.get("exchangeCode") or "").upper()
        mic = MICS.get(code)
        exchange = Exchange(self.name, 0, exchange_name(mic) or code, country("CN"), mic=mic, acronym=code,
                            type="exchange") if mic else None
        start = str(r.get("startDate") or "")[:10]
        return Stock(ticker=ticker.upper(), name=r.get("name"), primary_exchange=exchange, currency="CNY",
                     list_date=date.fromisoformat(start) if start else None, details=r)

    def _supported_rows(self) -> list[dict]:
        if self._supported is None:
            if self.files is None:
                self.files = PublicClient(FILES, sleep=self.client.sleep) if hasattr(self.client, "sleep") else PublicClient(FILES)
            data, _ = self.files.get_bytes(SUPPORTED_TICKERS)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
                if name is None:
                    raise SourceError(0, "Tiingo's supported-tickers file has no CSV in it")
                text = z.read(name).decode("utf-8", "replace")
            self._supported = list(csv.DictReader(io.StringIO(text)))
        return self._supported

    def listings(self, exchange: str) -> list[dict]:
        """Every A-share Tiingo serves on an exchange it carries (XSHG, XSHE), from its supported-tickers
        file (every ticker it serves, about 10 MB zipped: one download a run), under their stored
        names (600519.SS). Only with TIINGO_LISTINGS on: the file is heavy for a daily directory
        refresh on a plan of 1 GB a month. The US exchanges' listings are the whole-market feeds'
        directory: an empty answer here."""
        mic = exchange.upper()
        code = EXCHANGE_CODES.get(mic)
        if code is None:
            return []
        if not self.listings_on:
            raise NotImplementedError("TIINGO_LISTINGS is off: Tiingo's supported-tickers file is not downloaded")
        cut = ((self.today or date.today()) - timedelta(days=LISTING_DAYS)).isoformat()
        out = []
        for r in self._supported_rows():
            if (r.get("exchange") or "").upper() != code or (r.get("assetType") or "").lower() != "stock":
                continue
            if (r.get("endDate") or "") < cut:
                continue  # Tiingo stopped serving it: delisted
            out.append({"ticker": listing_ticker(r["ticker"], mic), "name": None, "exchange": mic, "type": "CS",
                        "figi": None, "kind": "stock"})
        return out

    def _all(self, ticker: str) -> list[dict]:
        sym = tiingo_symbol(ticker)
        if sym not in self._history:
            rows = self.client.get(f"/tiingo/daily/{sym}/prices", {"startDate": "1950-01-01", "format": "json",
                                                                   "resampleFreq": "daily"})
            if not isinstance(rows, list):
                raise SourceError(0, f"unexpected Tiingo answer for {sym}")
            self._history[sym] = split_adjust(rows)
        return self._history[sym]

    def bar_pages(self, ticker, start, end, timespan, multiplier=1, descending=False, asset="stock",
                  limit: int | None = None) -> Iterator[list[dict]]:
        if not self.has_key:
            raise NotEntitled(401, "TIINGO_API_KEY not set; nothing sent")
        if timespan != "day":
            raise NotEntitled(0, "Tiingo serves daily bars here")
        a, b = _bounds(start, end, ET)
        bars = [x for x in self._all(ticker) if a <= x["t"] < b]
        bars.sort(key=lambda x: -x["t"] if descending else x["t"])
        yield bars[:limit] if limit else bars


def tiingo_fx_pair(ticker: str) -> str:
    """Tiingo's name for a currency pair (eurusd): the watch row keeps Massive's (C:EURUSD)."""
    return ticker.upper().removeprefix("C:").lower()


class TiingoFxSource(_Archive):
    """Tiingo's forex: currency pairs' 1-minute bars (open, high, low, close; no volume) from
    2020-01-01, the earliest it serves ("End date must be >= 2020-01-01", asked 2026-10-28). One
    request gives at most about four days of minutes (5,772 bars for a whole year asked, 2026-10-28),
    so it is asked WINDOW_DAYS whole UTC days at a time, which always fit. A feed of its own (FOREX
    in the plugin) on the Tiingo key's limits; still trading, so kept up to date."""

    name = "tiingofx"
    assets = ("fx",)
    archival = False
    WINDOW_DAYS = 3  # 4,320 minutes: inside the ~5,772 one request gives
    START = date(2020, 1, 1)

    def __init__(self, client: PublicClient, has_key: bool):
        super().__init__(client)
        self.has_key = has_key

    def serves(self, asset: str) -> bool:
        return asset == "fx" and self.has_key

    def resolutions(self, asset: str) -> tuple[str, ...]:
        return ("minute",) if self.serves(asset) else ()

    def native_frames(self, asset: str) -> tuple[tuple[str, int], ...]:
        return ()  # its hours and days are built here from its minutes

    def bar_pages(self, ticker, start, end, timespan, multiplier=1, descending=False, asset="fx",
                  limit: int | None = None) -> Iterator[list[dict]]:
        if not self.has_key:
            raise NotEntitled(401, "TIINGO_API_KEY not set; nothing sent")
        if (timespan, multiplier) != ("minute", 1):
            raise NotEntitled(0, "Tiingo's forex is collected as 1-minute bars here")
        pair = tiingo_fx_pair(ticker)
        a, b = _bounds(start, end)
        a = max(a, _ms(datetime.combine(self.START, datetime.min.time(), timezone.utc)))
        day, step = 86_400_000, self.WINDOW_DAYS * 86_400_000
        windows, t = [], a // day * day  # whole UTC days: Tiingo is asked by date
        while t < b:
            windows.append((t, min(b, t + step)))
            t += step
        for lo, hi in (reversed(windows) if descending else windows):
            first = datetime.fromtimestamp(lo / 1000, timezone.utc).date()
            last = datetime.fromtimestamp((hi - 1) / 1000, timezone.utc).date()  # Tiingo's end date is inclusive
            rows = self.client.get("/tiingo/fx/prices", {"tickers": pair, "startDate": first.isoformat(),
                                                         "endDate": last.isoformat(), "resampleFreq": "1min"})
            if not isinstance(rows, list):
                raise SourceError(0, f"unexpected Tiingo answer for {pair}")
            bars = []
            for r in rows:
                ms = _ms(datetime.fromisoformat(r["date"]))
                if max(lo, a) <= ms < hi:
                    bars.append({"t": ms, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]),
                                 "c": float(r["close"]), "v": None, "vw": None, "n": None})
            bars.sort(key=lambda x: -x["t"] if descending else x["t"])
            yield Page(bars[:limit] if limit else bars, window=(max(lo, a), hi))
            if limit:
                return

    def instrument(self, ticker: str, resolve_exchange: bool = True) -> Instrument:
        pair = tiingo_fx_pair(ticker).upper()
        return Instrument(ticker=pair, name=f"{pair[:3]}/{pair[3:]} on Tiingo", details={"venue": "Tiingo"})
