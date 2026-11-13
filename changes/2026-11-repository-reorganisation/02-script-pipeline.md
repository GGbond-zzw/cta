# 2. Script pipeline

`scripts/` used to mix the runnable path with one-off studies. It is now:

```
scripts/
  10_fetch_research_inputs.py      <- fetch_cta_alpha_inputs.py
  15_select_liquid_universe.py     <- select_liquid_futures_monthly.py
  12_add_open_from_bundle.py       <- new: RQData inputs do not carry `open`
  20_rebuild_inputs_from_bundle.py <- new: bundle -> research inputs
  30_tune_factors.py               <- tune_qualified_factors.py
  31_tune_factors_by_process.py    <- run_qualified5_300.py (workspace script)
  32_verify_tuning_outputs.py      <- verify_tuning.py (workspace script)
  40_correlation_report.py         <- factor_correlation.py (workspace script)
  50_backtest_portfolio.py         <- final_backtest_4f.py (workspace script)
  60_render_run_chart.py           <- render_vol20_2025.py (workspace script)
  research/                        <- 17 historical studies + 2 new wrappers
```

Changes inside the migrated scripts:

* `10_...`: unchanged behaviour, only the filename and module docstring.
* `15_...`: unchanged behaviour.
* `12_...`: new stage. RQData's daily bars have no `open`, while the execution
  engine fills at the next open; this script joins the bundle's raw open on the
  dominant contract, rescales it by `cached_close / raw_close`, and can fall back
  to close for dates the bundle does not cover (recorded in the metadata).
* `20_...`: new stage. It reuses the workspace `bundle_loader` logic through the
  new package module `china_cta/data/rqalpha_bundle.py`, writes the extended
  input directory, and validates itself against the cached tables.
* `30_...`: default output moved to `results/tuning/qualified4_300`; help text
  now says four factors.
* `31_...`: `FACTORS`, the default output directory and the summary builder were
  reduced to the four qualified sleeves.
* `32_...`: gained `--tuned-dir` (default `results/tuning/qualified4_300`).
* `40_...`: default `--tuned-dir` is `results/tuning/qualified4_300`, default
  `--out-dir` is `results/tuning/factor_correlation_4f`.
* `50_...`: default `--tuned-dir` is `results/tuning/qualified4_300`.
* `60_...`: loads `50_backtest_portfolio.py` from the same directory and
  defaults to `results/final_4f` over 2016-01-04 .. 2025-12-31.

New package module `china_cta/data/rqalpha_bundle.py` holds the bundle reader
(`load_instruments`, `load_bars`, `load_contract_bars`) so the pipeline no longer
depends on a workspace-side helper script.
