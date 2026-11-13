# Factor classification

`china_cta/factors/classification.py` is the single source of truth: only the
four sleeves below are qualified. Everything else is research material.

## Qualified (the book)

| factor | module | direction | tuned parameters |
| --- | --- | --- | --- |
| `fixed_maturity_carry_90_180d` | `factors/qualified/fixed_maturity_carry.py` | long backwardation, short contango | near 80d, far 170d, min days to maturity 11, max gap 80d, scale 0.0764 |
| `xsmom_252_21` | `factors/qualified/xsmom_252_21.py` | long past winners, short losers | lookback 246, skip 53, scale 0.6398 |
| `oi_participation_trend_60d` | `factors/qualified/oi_participation_trend.py` | trend vote gated by OI participation | horizons (63, 126, 252), OI growth 68, normalisation 360, scale 0.6157 |
| `historical_skewness_252d` | `factors/qualified/historical_skewness.py` | long negative skew, short positive skew | lookback 441, scale 0.99998 |

All four were re-tuned with next-open execution and 1bp costs (300 trials,
seed 42, scale pinned) and re-validated as a four-sleeve book.

## Unqualified

* Previously qualified, now retired: `breakout_55`, `carry_ann`,
  `vol_scaled_carry`, `historical_skewness_252d_cs_rank`. They are kept in
  `factors/unqualified/` because their modules still document the research
  history, but `classification.QUALIFIED_FACTORS` and
  `research.bayesian_tuning.TUNING_SPECS` no longer include them.
* Data-limited: `basis_mom_20`, `ls_ratio_z`, `inventory_mom_20`,
  `spot_profit_z`. RQData exposes no commodity basis, retail long/short ratio,
  independent inventory series, or spot processing margin for these 30 products.
* Negative or flat out-of-sample Sharpe in the 26-factor screen: `lowvol`,
  `receipt_mom_20`, `ts_slope`, `aggregate_oi_growth_20d`, `oi_price_confirm_20`,
  `ts_curvature`, `st_reversal_5`, `xsmom_63`, `broker_net_chg_5` and the other
  middle-of-the-table variants.

## Migration note

`historical_skewness_252d` (absolute skewness) used to live in
`factors/unqualified/historical_skewness.py`, while the retired cross-sectional
variant lived in `factors/qualified/historical_skewness_cs.py`. The two modules
were swapped so the qualified module name matches the qualified factor.
