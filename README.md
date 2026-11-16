# china-cta

A reproducible CTA research framework for Chinese commodity futures: factor
construction, Bayesian parameter tuning on a strict in-sample window, factor
correlation analysis, and a portfolio backtest with next-open execution and
explicit trading costs.

The qualified book is **four sleeves**, all validated on the same conventions:

| sleeve | module | role |
| --- | --- | --- |
| `fixed_maturity_carry_90_180d` | `china_cta/factors/qualified/fixed_maturity_carry.py` | term-structure carry on a fixed maturity pair |
| `xsmom_252_21` | `china_cta/factors/qualified/xsmom_252_21.py` | cross-sectional momentum |
| `oi_participation_trend_60d` | `china_cta/factors/qualified/oi_participation_trend.py` | trend gated by open-interest participation |
| `historical_skewness_252d` | `china_cta/factors/qualified/historical_skewness.py` | cross-sectional skewness rank |

Everything else in `china_cta/factors/unqualified/` is kept for research but is
**not** part of the book: see [docs/FACTOR_CLASSIFICATION.md](docs/FACTOR_CLASSIFICATION.md).

## Execution conventions

* Signals are computed on the close of day `t`.
* Positions are filled at the **open of day `t+1`** and rolled at the open of `t+2`
  (`china_cta/research/fast_backtest.py`, `execution_price_field="open"`).
* Daily return of a sleeve = equal-weight mean of `signal * forward_return` across
  eligible instruments; `net = gross - 1bp * turnover`.
* No leverage and no volatility targeting by default; `50_backtest_portfolio.py`
  can apply a trailing realised-volatility target (`--vol-target`).

## Quick start

```bash
conda env create -f environment.yml        # or: pip install -e .
python scripts/10_fetch_research_inputs.py  # RQData -> data/research_inputs/cta_alpha22
python scripts/12_add_open_from_bundle.py    # add the open column the engine fills on
python scripts/30_tune_factors.py --trials 60
python scripts/31_tune_factors_by_process.py --trials 300 --processes 3
python scripts/32_verify_tuning_outputs.py
python scripts/40_correlation_report.py
python scripts/50_backtest_portfolio.py --vol-target 0.0
python scripts/50_backtest_portfolio.py --vol-target 0.2 --run-name equal_weight_4f
python scripts/60_render_run_chart.py
python scripts/70_native_backtest.py --start 2016-01-04 --end 2026-10-30
```

Stage `50` is the research-layer book (continuous exposure, 1bp turnover cost).
Stage `70` replays the same signals into an **RQAlpha native futures account**
(50M capital, 50% margin budget, integer lots, 25% volume cap, one-tick slippage,
native per-fill commissions) and is the result layer to quote. Conventions are
documented in [docs/NATIVE_ACCOUNT_SPEC.md](docs/NATIVE_ACCOUNT_SPEC.md).

The full walk-through, including what each artifact means, is in
[docs/PIPELINE.md](docs/PIPELINE.md).

## Layout

```
china_cta/
  data/          RQData adapter, contract helpers, liquidity screen, bundle reader
  factors/       factor contracts (schema.py) + qualified/ + unqualified/
  research/      fast_backtest.py, bayesian_tuning.py, seasonality studies
  portfolio/     allocation and volatility helpers (Phase 5 semantics)
  formal_backtest/  native_account.py (RQAlpha account) + legacy RQAlpha Plus adapter
  validation/    reconciliation helpers
scripts/
  10..70         the numbered research pipeline
  research/      historical studies kept for reference (not part of the book)
docs/            pipeline, data, factor classification, research notes
changes/         one directory per repository-wide change, with a file-level record
tests/           pytest suite (qualified/unqualified factors, engine, tuning)
```

## Verified numbers

Four-sleeve equal-weight book, next-open fills, 1bp per unit turnover:

| window | Sharpe | annualised | volatility | max drawdown |
| --- | --- | --- | --- | --- |
| 2016-01-04 .. 2025-12-31 | 1.49 | 3.95% | 2.66% | -4.45% |
| 2025 only | 1.64 | 5.11% | 3.11% | -3.71% |

With a 20% trailing volatility target (60-day window, 10x leverage cap) the same
book reaches a 1.58 Sharpe over 2016-2025 (29.9% annualised, 19.3% volatility,
-22.9% max drawdown). 2026-01-05 .. 2026-09-04, rebuilt from a local RQAlpha
bundle, gives 0.84 unlevered and 1.12 at 20% volatility.

These are research results on an in-sample-tuned book; the out-of-sample window
has been inspected repeatedly, so treat the 2025 figures as optimistic.

## Native account result layer

`70_native_backtest.py` replays the book into an RQAlpha futures account
(50M capital, 50% margin budget, integer lots, 1-tick slippage, native fees) and
calibrates the research leverage once so realised volatility hits the 20% target:
pass 1 comes out at 8.8% volatility, the calibration multiplies exposure by 2.27,
pass 2 reaches 20.0%. The margin budget is applied to the **live account equity**
(50% of that day's equity, `margin_basis="live_equity"`), so exposure compounds with the
book instead of shrinking against a frozen 50M base.

| segment | Sharpe | annualised | volatility | max drawdown |
| --- | --- | --- | --- | --- |
| train 2016-01-04 .. 2021-12-31 | 1.71 | 30.7% | 16.5% | -15.0% |
| validation 2022-01-04 .. 2024-12-31 | 0.52 | 3.3% | 6.8% | -9.4% |
| test 2025-01-02 .. 2026-09-04 | 0.93 | 6.6% | 7.2% | -8.8% |
| overall | 1.35 | 28.4% | 20.0% | -27.5% |

Trading friction over the full window: 7.4M commission and 25.9M one-tick
slippage, i.e. 12.3% of gross P&L, or roughly 6.5% of capital per year.
The native account needs contract-level bars from a local RQAlpha bundle, so it
stops at the bundle's last trading day (2026-09-04) rather than at the research
inputs' last day.

## Environment notes

* `rqdatac` is required by `10_fetch_research_inputs.py`; on locked-down Windows
  hosts it is blocked by the application control policy. Use
  `20_rebuild_inputs_from_bundle.py` with a local RQAlpha bundle as the fallback
  (see [docs/DATA.md](docs/DATA.md)).
* `12_add_open_from_bundle.py` needs the same local bundle: it is the fallback
  for filling `open` when stage 0 could not request it from RQData.
* On hosts with Smart App Control enabled, stage 0 (`rqdatac`) is blocked by
  code-integrity policy; run it from WSL2 instead, see
  [docs/LINUX_SETUP.md](docs/LINUX_SETUP.md).
* `rqalpha_plus` is only needed by the legacy `china_cta/formal_backtest/adapter.py`
  (kept for reference); the native result layer uses plain `rqalpha` 6.x, which is
  pure Python, so it runs even where the `rqalpha_plus` native modules are blocked.
* `pandas` is used without `pytables`, so the bundle is read through `h5py`.
