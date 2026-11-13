# 3. Tests and result directories

## Tests

| old | new |
| --- | --- |
| `tests/qualified/test_cta_alpha_qualified.py` | `tests/unqualified/test_cta_alpha_superseded.py` |
| `tests/qualified/test_historical_skewness_cs.py` | `tests/unqualified/test_historical_skewness_cs_rank.py` |
| `tests/unqualified/test_historical_skewness.py` | `tests/qualified/test_historical_skewness_252d.py` |

`tests/qualified/` now covers the four sleeves; `tests/unqualified/` covers the
retired and research factors.

## Results

| old | new |
| --- | --- |
| `results/tuning/qualified5_300/` | `results/tuning/qualified4_300/` |
| `results/tuning/qualified5_300/vol_scaled_carry/` | `results/unqualified/vol_scaled_carry_tuning_300/` |

`summary.csv` and `manifest.json` in the new directory list four factors and
record `retired_factors: ["vol_scaled_carry"]`. No study data was recomputed;
only the grouping changed.

## Verification performed

* `pytest tests/qualified tests/unqualified tests/test_bayesian_tuning.py tests/test_bayesian_tuning_scale.py`
  -> 73 passed, 3 skipped.
* All nine numbered scripts respond to `--help` with exit code 0.
* `python -m compileall china_cta scripts tests` passes except for paths whose
  `__pycache__` directories carry ACLs that deny the sandbox user.
* End-to-end smoke test after the move: `scripts/50_backtest_portfolio.py`
  with two sleeves over 2025-01-01 .. 2025-06-30 wrote every expected artefact
  (per-sleeve run directories, `final_summary.csv`, `combo_comparison.csv`,
  `cost_report.csv`, `comparison_equity.png`) and reported a 1.0 bp implied cost.
* `git status --porcelain` after the reorganisation: 9 modified, 9 deleted,
  41 untracked entries (the new pipeline scripts, `docs/` and `changes/`).
* Full `pytest tests` stops at `tests/test_formal_backtest.py` with
  `ImportError: DLL load failed while importing daybar` - `rqalpha_plus` is
  blocked by the Windows application control policy. This is an environment
  issue, unrelated to the reorganisation, and the research pipeline does not
  import `rqalpha_plus`.
