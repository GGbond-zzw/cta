# Commodity factor v2 design

Historical performance figures below describe earlier universes/definitions.
For the current fixed-30 rerun, use `results/all_factors_fixed30_summary.csv`
and each run's `config.json`; do not interpret the historical tables as the
performance of the updated pool or fixed-maturity Carry.

The current fixed-30 runs use a 1 bp turnover-cost proxy; the earlier
2 bp figures are retained only as history.

## Decision

The v2 core contains three independent economic themes instead of three
variants of price trend:

1. **Robust Trend** — average volatility-normalized returns over 20, 60, 120
   and 252 sessions.
2. **Fixed-maturity Carry** — annualized log spread between linearly
   interpolated 90-day and 180-day real-contract close prices.
3. **Aggregate OI Growth** — 20-session growth in open interest summed across
   every active real contract.

Basis-momentum remains a lower-weight curve-dynamics candidate. Historical
skewness and cross-sectional low volatility remain defensive satellite
factors. Short-term reversal stays experimental.

## Why the original three were changed

- The single 60-day Trend is sensitive to one arbitrary horizon. The new
  version diversifies horizon choice and makes component magnitudes comparable
  through time-series volatility normalization.
- Carry now uses common 90/180-calendar-day targets rather than four contracts
  whose maturity spans differ across products. Each target uses its nearest
  surrounding real contracts; an exact target quote is used directly.
- OI-confirmed Trend multiplies another trend signal by positive dominant OI
  growth and discards every window containing a roll. The new OI signal is an
  independent flow characteristic and aggregates the entire curve, so contract
  migration does not create a false change.

## Candidate tiers

### Core

- Multi-horizon Trend
- Fixed-maturity Carry
- Aggregate OI Growth

### Satellite

- Basis-momentum
- Eligible-universe cross-sectional historical skewness
- Eligible-universe cross-sectional low volatility

### Coverage-dependent research

- Seasonally adjusted warehouse-receipt change
- Top-member long/short pressure and concentration
- Amihud illiquidity and volume/OI crowding
- Curve curvature or butterfly

### Deferred

- A universal spot-futures value factor: RQData does not provide a common spot
  series for the full commodity universe.
- CFTC-style hedging pressure: the required trader classification is not a
  common domestic-futures field.
- Margin and fee changes as alpha: these are better used in risk, capacity and
  transaction-cost models.

## Validation gates

Every candidate must use the same 2016-2025 universe, one-session execution
lag and cost convention. Promotion into a combined portfolio requires:

1. positive net performance in multiple subperiods;
2. reasonable product coverage and no single-product dependence;
3. stability under adjacent parameter choices;
4. double-cost and delayed-execution stress tests;
5. incremental performance after controlling for the other core factors;
6. a formal backtest using real contracts, fees, margin and integer positions.

## v3 redesign after the first full-sample test

The first 2016-2025 test did not support promoting the original robust Trend
or aggregate OI Growth into production. The redesign deliberately changes the
signal definitions rather than optimizing the old parameters against one
sample.

### Slow direction-voting Trend

For each horizon `h` in 63, 126 and 252 sessions, define

`D_h = sign(log(P_t / P_(t-h)))`.

The factor averages the three direction votes, applies a 10-session EWM,
ignores an absolute score below 0.05 and updates once every five observations.
It then estimates annualized volatility with a 20-session EWM half-life and
multiplies the vote by `min(1, 15% / forecast volatility)`. This is a true
exposure-risk adjustment: high-volatility products are reduced, but quiet
products are never levered up. The construction removes the noisy 20-day leg
and reduces trading without using future information.

### OI-participation Trend

Aggregate OI remains useful as participation evidence but is no longer an
independent directional alpha. Total curve OI growth is measured over 60
sessions, smoothed over 10 sessions, and standardized against the instrument's
own trailing 252-session distribution using at least 126 observations. The
clipped z-score is mapped to a bounded weight:

`W_oi = 0.5 * (1 + tanh(clip(z_oi, -3, 3)))`.

The final raw signal is `Slow direction-voting Trend * W_oi`, again updated every
five observations. Weak relative OI participation reduces exposure but cannot
reverse the price trend. Missing OI invalidates the signal on that date rather
than silently carrying a stale observation forward.

The old v2 Trend and OI implementations remain as frozen baselines. Carry has
been replaced by the fixed-maturity definition documented below. The
v3 pair must pass the same validation gates above before either is combined
with Carry or basis momentum.

### First v3 full-sample result

All figures below use the earlier point-in-time universe, one-session
execution lag and 2 bp turnover-cost proxy. They are historical and are not
the fixed-30, 1 bp results in `results/`.

| model | net Sharpe | max drawdown | mean turnover proxy | rough cost |
|---|---:|---:|---:|---:|
| v2 multi-horizon Trend | 0.264 | -17.34% | 8.67% | 3.78% |
| v2 aggregate OI Growth | 0.114 | -15.98% | 15.10% | 7.28% |
| v3 slow direction vote | 0.343 | -19.69% | 2.36% | 1.03% |
| v3 OI-participation Trend | 0.528 | -9.31% | 2.15% | 0.93% |

The slow vote improves Sharpe and turnover but fails the drawdown gate as a
standalone model. It is therefore retained as an intermediate signal, not a
promoted standalone factor. The OI-participation version improves both Sharpe
and drawdown while cutting turnover materially, so it is the only v3 candidate
promoted to the next robustness stage. This is still an in-sample research
result: double-cost, delayed execution, adjacent parameters and leave-one-
product-out tests remain mandatory before portfolio use.

## Fixed-maturity Carry construction

`calculate_curve_carry` and `compute_curve_carry_factor` retain their entrypoint
names but replace the old four-contract OLS definition. `contracts_to_use` is
removed; callers use `near_days=90`, `far_days=180`,
`min_days_to_maturity=30`, and `max_gap_days=120` by default.

For each same-day product curve, remove contracts with at most 30 calendar days
remaining. For a target h, select the nearest lower and upper maturities D1/D2.
Compute `w=(D2-h)/(D2-D1)` and `P(h)=w*F(D1)+(1-w)*F(D2)`.
An exact quote at h needs no second contract. The factor is
`(log(P(90))-log(P(180)))*365/90`: backwardation is positive.

Maturity is the supplied `maturity_date`, not the contract month or delivery
period midpoint. The supplied days must agree with the actual date difference.
There is no extrapolation, forward fill or replacement of a missing selected
quote with a farther contract. Gaps above 120 days, non-positive/non-finite
prices, or duplicate eligible tenors leave the factor missing. The gap limit
is a configurable research choice, not an empirically validated optimum.
No additional contract-volume/OI screen is introduced here; upstream product
eligibility is not a guarantee that each bracket contract is liquid.

Diagnostics expose both fixed prices, targets, bracket contract IDs, days,
lower weights, gaps and statuses. The standardized factor name is
`fixed_maturity_carry_90_180d`. The research run uses a new result directory,
preserving historical four-contract results. Fixed prices are signal/research
estimates, not cash P&L marks or a self-financing return index. Existing
after-close availability and next-session execution conventions still apply.

Validate coverage by product and date, bracket gaps, and adjacent tenor/gap
choices before interpreting a performance change. Previously recorded Carry
results do not describe this new factor; a fresh backtest is required.

## Data references

- Ricequant futures API: <https://www.ricequant.com/doc/rqdata/python/futures-mod>
- Ricequant generic market data API:
  <https://www.ricequant.com/doc/rqdata/python/generic-api>
- Fan and Zhang, *The Untold Story of Commodity Futures in China*:
  <https://doi.org/10.1002/fut.22087>
- Boons and Prado, *Basis-Momentum*:
  <https://doi.org/10.1111/jofi.12738>
- Sakkas and Tessaromatis, *Factor Based Commodity Investing*:
  <https://doi.org/10.1016/j.jbankfin.2020.105807>
