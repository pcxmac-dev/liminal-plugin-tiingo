# liminal-plugin-tiingo

Tiingo for [Liminal](https://github.com/pcxmac-dev/liminal-app): one plugin, two feeds on one free
account key (`TIINGO_API_KEY`):

- `tiingo`: US stock daily bars from 1962, split-adjusted here from Tiingo's split factors; a closed
  archive (a symbol's whole history in one request, then not asked again);
- `tiingofx` (tiingo (forex)): currency pairs' 1-minute bars from 2020, kept up to date, three whole
  days a request.

On a paid plan (`TIINGO_PLAN=power` or `commercial`; its scan tells Starter from a paid plan by the
News API) it also polls Blue Ocean's overnight session live for the stocks open on a chart
(`tiingoboats`, tiingo (blue ocean)). Both feeds share the key's limits: one rate window, one daily
cap, one count of different symbols a month.

A Liminal provider plugin released on its own. The app finds it through the entry point group
`liminal.providers` and lists it on the Plugins view and in `liminal plugins`
as `package: liminal-plugin-tiingo`, with this package's version.

## Install

Into the app's environment, from the app's folder:

```powershell
.venv\Scripts\python.exe -m pip install "liminal-plugin-tiingo @ git+https://github.com/pcxmac-dev/liminal-plugin-tiingo@v1.4.1"
```

or with the app's plugins (`pip install -e ".[plugins]"` in liminal-app). The app loads it on its next
start. Save the key with the app's `tools/set-key.ps1` (it is read from your user environment
variables only, never written to a file).

## Compatibility

It is written for plugin API 1.10 (`PLUGIN.api`: the machine-wide ledger and the session calendar
reached through the contract). An app offering 1.10 or a later 1.x loads it; an app of another
major, or one older than 1.10, leaves it out and says why on the Plugins view.

## Develop

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install "liminal-lib @ git+https://github.com/pcxmac-dev/liminal-lib@main"
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

Tests never send requests (a fake client answers) and never read your keys.
