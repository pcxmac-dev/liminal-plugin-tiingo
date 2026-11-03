# Changelog

## 1.5.1 (2026-11-03)

`TIINGO_LISTINGS` has its choices (off, on) in the record, so the app's Plugins view offers it beside the plan.

## 1.5.0 (2026-11-02)

Shanghai's and Shenzhen's A-shares (the user: "update existing plugins, add exchanges where applicable and
symbols"): the stocks feed carries them (plugin API 1.12, `Provider.exchanges`: every US listing, XSHG and XSHE),
stored as `600519.SS` and `000001.SZ` (the library's notation) and asked for by their bare codes, Tiingo's form
(`/tiingo/daily/600519`, from 2007-01-04). A listing's record names it and its exchange (`instrument`); the
exchanges come by name (`exchanges`); with `TIINGO_LISTINGS=on` the A-shares are listed in the directory from
Tiingo's supported-tickers file (about 10 MB, at each directory refresh while on). Requires liminal-lib 1.2.0.

## 1.4.1 (2026-11-02)

The plugin imports the library as `liminal_lib` and depends on liminal-lib (the app, renamed liminal-app, is no longer needed to run the tests; the user, 2026-11-02: "lets rename the app to liminal-app").

## 1.4.0 (2026-11-01)

- Released as its own package, `liminal-plugin-tiingo`, registered under the entry point group
  `liminal.providers` (a module of two feeds: `tiingo`, `tiingofx`); its version is the distribution's.
- Its free plan and caps are in it (`TIER`, `PER_RUN`, `PER_DAY`), no longer in the app's
  `config.PUBLIC_FEEDS`; its key is read from the settings' plugin variables (`Settings.env`), no
  longer from a field of the app's settings.
- Plugin API 1.10: the machine-wide symbol ledger and the session calendar (Blue Ocean's nights)
  are reached through the contract (`liminal.sources.registry.MachineLedger`,
  `liminal.sources.stream.session_at`).

## 1.3.0 (2026-10-31)

- Built into the app (then massive-collate): its live Blue Ocean nights and its client in its
  module (plugin API 1.6).

## 1.2.0 and before

- Built into the app (then massive-collate); see the app's history.
