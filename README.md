# plugin-integrator-tiingo

Tiingo for [Liminal](https://github.com/pcxmac-dev/liminal-charts): one plugin, two feeds on one free
account key (`TIINGO_API_KEY`):

- `tiingo`: US stock daily bars from 1962, split-adjusted here from Tiingo's split factors; a closed
  archive (a symbol's whole history in one request, then not asked again);
- `tiingofx` (tiingo (forex)): currency pairs' 1-minute bars from 2020, kept up to date, three whole
  days a request.

On a paid plan (`TIINGO_PLAN=power` or `commercial`; its scan tells Starter from a paid plan by the
News API) it also polls Blue Ocean's overnight session live for the stocks open on a chart
(`tiingoboats`, tiingo (blue ocean)). Both feeds share the key's limits: one rate window, one daily
cap, one count of different symbols a month.

A Liminal provider plugin released on its own: a class each on the class contract (plugin API 2.0),
`TiingoPlugin` and `TiingoForex`, both `TiingoFeed` (a `FeedPlugin`, what the two share). The app finds it
through the entry point group `liminal.providers` and lists it on the Plugins view and in
`liminal-charts plugins` as `package: plugin-integrator-tiingo`, with this package's version.

## Install

Into the app's environment, from the app's folder:

```powershell
.venv\Scripts\python.exe -m pip install "plugin-integrator-tiingo @ git+https://github.com/pcxmac-dev/plugin-integrator-tiingo@v0.2.0"
```

or with the app's plugins (`pip install -e ".[plugins]"` in liminal-charts). The app loads it on its next
start. Save the key with the app's `tools/set-key.ps1` (it is read from your user environment
variables only, never written to a file).

## Shanghai and Shenzhen

The stocks feed carries the A-shares Tiingo serves (from 2007-01-04), under the library's names for
a listing abroad: `600519.SS` (Shanghai, XSHG) and `000001.SZ` (Shenzhen, XSHE); `SSE:600519` and
`600519::XSHG` mean the same. Tiingo lists them by their bare codes, which the feed asks for. Their
days are the exchanges' own calendar days (every weekday, until the library carries their holidays),
their day bars stamped at midnight New York of the local date like every stock's. With
`TIINGO_LISTINGS=on` (the Plugins view, or the key script) the directory lists every A-share Tiingo
serves, from its supported-tickers file: about 10 MB, downloaded at each directory refresh while on,
so turn it on for the listing and off again on a plan of 1 GB a month.

## Compatibility

It is written for plugin API 2.0 (each feed's `api`: the class contract of liminal-libs 1.3.0, a plugin
an instance of a `FeedPlugin` subclass; the exchanges a feed carries, `exchanges`; the machine-wide
ledger and the session calendar reached through the contract). An app offering 2.0 or a later 2.x loads
it; an app of another major leaves it out and says why on the Plugins view.

## Develop

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install "liminal-libs @ git+https://github.com/pcxmac-dev/liminal-libs@release/0.2.0"
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

Tests never send requests (a fake client answers) and never read your keys.
