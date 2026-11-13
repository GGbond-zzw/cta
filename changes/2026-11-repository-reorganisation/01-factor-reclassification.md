# 1. Factor reclassification

Before: `classification.QUALIFIED_FACTORS` held seven names, and the module that
implements the qualified `historical_skewness_252d` lived under
`factors/unqualified/`, while the retired cross-sectional variant lived under
`factors/qualified/`.

After: four qualified sleeves, and module locations that match their status.

| file | change |
| --- | --- |
| `factors/qualified/breakout_55.py` | moved to `factors/unqualified/` |
| `factors/qualified/carry_ann.py` | moved to `factors/unqualified/` |
| `factors/qualified/vol_scaled_carry.py` | moved to `factors/unqualified/` |
| `factors/qualified/historical_skewness_cs.py` | moved to `factors/unqualified/historical_skewness_cs_rank.py` |
| `factors/unqualified/historical_skewness.py` | moved to `factors/qualified/historical_skewness.py` |
| `factors/qualified/__init__.py` | rewritten: exports only the four sleeves |
| `factors/unqualified/__init__.py` | rewritten: also exports the four retired modules |
| `factors/classification.py` | `QUALIFIED_FACTORS` = four names, docstring updated |
| `factors/__init__.py` | the two skewness imports now point at their new modules |
| `research/bayesian_tuning.py` | dropped the four retired specs, their suggest functions and builder branches |

Effect on `TUNING_SPECS`, `SCALE_RANGES`, `SCALE_TUNED_SPECS`: four entries each.
`cta_catalog.FACTOR_SPECS` still lists all 22 catalogue factors, so the research
catalogue is unchanged; only the qualified book shrank.
