import numpy as np
import pandas as pd
import pytest

from china_cta.research.seasonality_robustness import (
    _bh_qvalues,
    calendar_return_robustness,
    monthly_volatility_panel,
)


def test_bh_qvalues_are_monotone_and_ordered():
    q = _bh_qvalues(np.array([0.02, 0.001, 0.9]))
    assert q[1] == pytest.approx(0.003)
    assert q[0] == pytest.approx(0.03)
    assert q[2] == pytest.approx(0.9)


def test_year_level_gains_and_oos_match_original_screen():
    rows = [("M", year, month, 0.08 if month == 1 else -0.01)
            for year in range(2010, 2020) for month in range(1, 13)]
    frame = pd.DataFrame(rows, columns=["underlying_symbol", "year", "calendar_month", "log_return"])
    result, years = calendar_return_robustness(frame, permutations=29, seed=1)
    assert result.iloc[0]["tested_years"] == 5
    assert result.iloc[0]["tested_months"] == 60
    assert result.iloc[0]["oos_seasonal_r2"] == pytest.approx(1)
    assert result.iloc[0]["positive_gain_years"] == 5
    assert years["squared_error_gain"].gt(0).all()


def test_insufficient_history_is_not_labeled_positive():
    frame = pd.DataFrame({"underlying_symbol": ["X"] * 24,
                          "year": np.repeat([2020, 2021], 12),
                          "calendar_month": list(range(1, 13)) * 2,
                          "log_return": [0.01] * 24})
    result, years = calendar_return_robustness(frame, permutations=9)
    assert np.isnan(result.iloc[0]["permutation_p"])
    assert result.iloc[0]["robust_evidence"] == "not_established"
    assert years.empty


def test_monthly_volatility_uses_daily_rms_and_coverage():
    daily = pd.DataFrame({
        "trading_date": ["2020-01-02", "2020-01-03", "2020-01-06",
                         "2020-02-03", "2020-02-04", "2020-02-05"],
        "underlying_symbol": ["M"] * 6,
        "log_return": [0.01, -0.01, 0.01, 0.02, np.nan, np.nan],
    })
    result = monthly_volatility_panel(daily, min_coverage=0.8, min_valid_days=2)
    assert result.iloc[0]["log_daily_rms_volatility"] == pytest.approx(np.log(0.01))
    assert np.isnan(result.iloc[1]["log_daily_rms_volatility"])
