# Changelog

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
