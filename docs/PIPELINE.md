# Pipeline

Every stage is a numbered script in `scripts/`. Defaults point at the validated
four-sleeve book, so a stage can be re-run with no arguments.

| stage | script | input | output |
| --- | --- | --- | --- |
| 0 | `10_fetch_research_inputs.py` | RQData | `data/research_inputs/cta_alpha22/` |
| 0b | `12_add_open_from_bundle.py` | RQAlpha bundle | same tables + `open` column |
| 0c | `20_rebuild_inputs_from_bundle.py` | RQAlpha bundle | `data/research_inputs/cta_alpha22_extended/` |
| 1 | `30_tune_factors.py` | stage 0 | `results/tuning/qualified4_300/` |
| 1b | `31_tune_factors_by_process.py` | stage 0 | same layout, one OS process per factor |
| 1c | `32_verify_tuning_outputs.py` | stage 1 | console checks |
| 2 | `40_correlation_report.py` | stage 1 | `results/tuning/factor_correlation_4f/` |
| 3 | `50_backtest_portfolio.py` | stage 0 + 1 | `results/final_4f/` |
| 4 | `60_render_run_chart.py` | stage 3 | `comparison_equity.png` |
| 5 | `70_native_backtest.py` | stage 0 + 1 | `results/final_4f_native_vol20/` |
| 6 | `15_select_liquid_universe.py` | RQData | liquidity screen artefacts |

## Stage 0 - research inputs

`10_fetch_research_inputs.py --start 2016-01-01 --refresh` (`--end` defaults to today)
writes six parquet tables: `continuous_prices`, `contract_snapshots`,
`dominant_map`, `member_rank`, `universe`, `warehouse_stocks`. The script is
idempotent per table and refuses to overwrite without `--refresh`.

On hosts where Smart App Control blocks `rqdatac`, run this stage inside WSL2
(see [LINUX_SETUP.md](LINUX_SETUP.md)); the rest of the pipeline stays on
Windows. Stage 0 requests `open` directly, so the `open` column is native.

## Stage 0b - the open column (fallback)

RQData's daily futures bars expose `close`, `high`, `low`, `volume` and
`open_interest`, but not `open`. The execution engine fills at the next open, so
the price table needs one:

```bash
python scripts/12_add_open_from_bundle.py \
    --input-dir data/research_inputs/cta_alpha22 \
    --bundle C:/Users/ct/Desktop/python/CTA/Mikuang_data/.rqalpha/bundle
```

The script joins the bundle's raw open on the dominant contract and rescales it
with `cached_close / raw_close`, so open and close share one price level. It is
idempotent and prints the `open/close` ratio quantiles as a sanity check. Dates
the bundle does not reach yet raise an error unless `--fill-missing-with-close`
is passed; the fallback is recorded in the parquet metadata as
`open_source=close_fallback`.

## Stage 1 - Bayesian tuning

```bash
python scripts/30_tune_factors.py --trials 60 --workers 6
python scripts/31_tune_factors_by_process.py --trials 300 --processes 3
```

* In-sample: 2016-01-04 .. 2021-12-31. Out-of-sample: 2022-01-04 .. 2025-12-31.
* Objective: training-period net Sharpe subject to
  `observations >= 10000`, `max_drawdown >= -40%`, `mean_turnover <= 0.5`.
* `signal_scale` is **pinned to the baseline** by default; `--tune-scale` (or
  dropping `--no-scale-tune` on the multi-process runner) searches it again
  inside the historical range and writes to a separate directory.
* TPE sampler, `seed=42`, `multivariate=True`, `group=True`,
  `n_startup_trials=10`; the baseline parameter set is always evaluated first.

Each factor directory holds `trials.csv`, `best_params.json` and
`best_factor.parquet`; the study writes `summary.csv` and `manifest.json`.
The multi-process runner additionally supports resuming from `study.sqlite3`
with `--resume`.

## Stage 2 - correlation report

`40_correlation_report.py` rebuilds every sleeve once at its tuned parameters
and writes daily net returns, then three matrices into
`results/tuning/factor_correlation_4f/`:

* `corr_returns_10y.csv`, `corr_returns_10y_spearman.csv`
* `corr_returns_2025.csv`
* `corr_signals_10y.csv` (cross-sectional rank correlation of signals)
* `correlation_matrices.png`

## Stage 3 - portfolio backtest

```bash
python scripts/50_backtest_portfolio.py                       # unlevered, 2016-2025
python scripts/50_backtest_portfolio.py --vol-target 0.2 --run-name equal_weight_4f
python scripts/50_backtest_portfolio.py --specs-file my_specs.json   # several books at once
```

Capital is split equally across sleeves (`--weights` overrides), each sleeve
pays its own turnover cost, and the book return is the weighted sum of sleeve
returns. Outputs per run: `config.json`, `overall.csv`, `by_year.csv`,
`by_instrument.csv`, `daily_net_return.csv`. The run directory also gets
`final_summary.csv`, `combo_comparison.csv`, `cost_report.csv`,
`sleeve_daily_net_return.csv` and `comparison_equity.png`.

`--vol-target` adds a second run named `<run-name>_vol<NN>` that scales the book
by `target / trailing 60-day realised volatility` (shifted one day, capped at
`--vol-max-leverage`, default 10x) and writes `leverage.csv`.

`cost_report.csv` reports, per scope (window and each calendar year):
gross and net return, total and annualised cost, cost share of gross, cost over
volatility, turnover, and the implied basis points per unit turnover.

## Stage 4 - chart

`60_render_run_chart.py --results-dir results/final_4f --start 2026-01-01 --end 2026-09-04`
re-renders `comparison_equity.png` from saved CSVs without re-running the
backtest.

## Stage 5 - rebuilding inputs from a local bundle

`20_rebuild_inputs_from_bundle.py` reproduces the six tables from an RQAlpha
bundle, keeping the cached 2016-2025 history byte-identical and reconstructing
the extension with the `prev_close_ratio` chaining convention. It validates
itself against the cache (snapshots and continuous returns) and prints both
checks. See [DATA.md](DATA.md).

## Reproducibility notes

* Backtests are deterministic: the same inputs and parameters reproduce Sharpe
  to 1e-15, and the tuned baseline trial reproduces the legacy
  `results/qualified` numbers exactly.
* `seed=42` makes TPE trajectories comparable across runs; a 300-trial study
  starts with the same 60 trials as a 60-trial study.
* The pipeline is multiprocessing-based on Windows; each worker loads the
  parquet inputs once (about 0.7 GB) before building factors.

## 阶段 70：原生账户结果层

`scripts/70_native_backtest.py` 把四个 sleeve 的信号重放进 RQAlpha 原生期货账户
（整数手、50% 保证金预算、25% 成交量上限、1 跳滑点、逐笔手续费），并对 20% 波动目标
做一次原生层校准。口径与复现见 [NATIVE_ACCOUNT_SPEC.md](NATIVE_ACCOUNT_SPEC.md)。

```bash
python scripts/70_native_backtest.py --start 2016-01-04 --end 2026-10-30
```

产出目录 `results/final_4f_native_vol20/`：`daily_equity.csv`、`daily_equity_pass1.csv`、
`trades.csv`（逐笔成交与手续费）、`target_positions.csv`、`daily_risk.csv`、
`vol_calibration.csv`、`segments.csv`、`segments_by_book.csv`、`by_year.csv`、
`by_year_by_book.csv`、`by_instrument.csv`、`by_instrument_by_book.csv`、
`attribution_reconciliation.csv`、`equity_comparison.png`。

最近一次全区间结果（2016-01-04..2026-09-04，2593 个交易日）：

| 口径 | 夏普 | 年化 | 波动 | 最大回撤 |
| --- | --- | --- | --- | --- |
| 研究层（阶段 3，1bp 换手成本） | 1.58 | 19.2% | 19.2% | -22.9% |
| 原生账户 pass 1（研究杠杆原样） | 1.35 | 26.3% | 18.6% | -25.7% |
| 原生账户 pass 2（校准 x1.08） | 1.35 | 28.4% | 20.0% | -27.5% |

口径提醒：原生账户按合约级行情回放，止于本地 bundle 的最后交易日（2026-09-04）。
保证金预算按**当日账户权益**的 50% 计算（`margin_basis="live_equity"`），实际占用
26%–37%、上限从未被触及，实现波动 20.0%，与目标一致。
