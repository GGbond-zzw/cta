# Factor classification

`china_cta/factors/classification.py` is the single source of truth. From 2026-11
the qualified set is the **nine sleeves of the live book**: four written in this
package plus five mined sleeves exported as frozen signals. Everything else is
research material.

```python
from china_cta.factors import classification

classification.QUALIFIED_SLEEVE_COUNT      # 9
classification.qualified_sleeve_names()    # book order, package sleeves first
classification.classification("xsmom_252_21")              # 'qualified'
classification.classification("volume_oi_coflow_10d")      # 'retired'
classification.classification("breakout_55")               # 'unqualified'
```

## Qualified: package sleeves (4)

| factor | module | direction | tuned parameters |
| --- | --- | --- | --- |
| `fixed_maturity_carry_90_180d` | `factors/qualified/fixed_maturity_carry.py` | long backwardation, short contango | near 80d, far 170d, min days to maturity 11, max gap 80d, scale 0.0764 |
| `xsmom_252_21` | `factors/qualified/xsmom_252_21.py` | long past winners, short losers | lookback 246, skip 53, scale 0.6398 |
| `oi_participation_trend_60d` | `factors/qualified/oi_participation_trend.py` | trend vote gated by OI participation | horizons (63, 126, 252), OI growth 68, normalisation 360, scale 0.6157 |
| `historical_skewness_252d` | `factors/qualified/historical_skewness.py` | long negative skew, short positive skew | lookback 441, scale 0.99998 |

All four were re-tuned with next-open execution and 1bp costs (300 trials,
seed 42, scale pinned).

## Qualified: exported sleeves (5)

Frozen expressions from the mining search; direction and scale are fitted there and
never re-fitted here. See `docs/EXPORTED_SLEEVES.md` for the expressions.

| sleeve | source | package |
| --- | --- | --- |
| `crowded_trend_reversal_60d` | `mined_4a51bf38703a` (原8号) | `old-mined-20261116` |
| `volume_burst_vol_reversal_60d` | `mined_8eb423cac50b` (上一轮1号) | `old-mined-20261116` |
| `turnover_surprise_channel_ratio` | `mined_f0dd19ea2ff1` (本轮1号) | `round2-20261119` |
| `inverse_oi_turnover_surprise_ratio` | `mined_cbe804196d96` (本轮8号) | `round2-20261119` |
| `volume_variability_weighted_reversal` | `mined_57002a2d5f10` (本轮20号) | `round2-20261119` |

The nine-sleeve book on the native account (2016-01-04..2026-09-04, 50M capital,
50% margin on live equity, 1-tick slippage, native commissions) prints Sharpe
1.7018, annualised 37.79%, volatility 20.02%, max drawdown -20.18%,
26.08x ending equity.

## Retired exported sleeves (2)

Kept in the registry so historical runs stay reproducible, excluded from the book:

* `volume_oi_coflow_10d` — research-layer out-of-sample Sharpe is negative
  (-0.27 over 2022-2025), and it has no parameter with a positive optimum.
* `volume_channel_price_oi_volatility` — 0.72 daily-return correlation with
  `turnover_surprise_channel_ratio`; dropping it costs 0.03 Sharpe and saves
  about two points of friction.

## Unqualified

* Previously qualified, now retired: `breakout_55`, `carry_ann`,
  `vol_scaled_carry`, `historical_skewness_252d_cs_rank`. They stay in
  `factors/unqualified/` because the modules document the research history, but
  the registry and `research.bayesian_tuning.TUNING_SPECS` exclude them.
* Data-limited: `basis_mom_20`, `ls_ratio_z`, `inventory_mom_20`,
  `spot_profit_z`. RQData exposes no commodity basis, retail long/short ratio,
  independent inventory series, or spot processing margin for these 30 products.
* Negative or flat out-of-sample Sharpe in the 26-factor screen: `lowvol`,
  `receipt_mom_20`, `ts_slope`, `aggregate_oi_growth_20d`, `oi_price_confirm_20`,
  `ts_curvature`, `st_reversal_5`, `xsmom_63`, `broker_net_chg_5` and the other
  middle-of-the-table variants.

## Migration notes

* `historical_skewness_252d` (absolute skewness) used to live in
  `factors/unqualified/historical_skewness.py`, while the retired
  cross-sectional variant lived in `factors/qualified/historical_skewness_cs.py`.
  The two modules were swapped so the qualified module name matches the qualified
  factor.
* Before 2026-11 the registry only knew the four package sleeves; the five mined
  sleeves were passed in on the command line. `classification.QUALIFIED_SLEEVES`
  now names all nine, and `tests/test_qualification_registry.py` locks the set.
