from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.unqualified.multi_horizon_trend import (
    calculate_multi_horizon_trend,
)


def research_prices(values: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trading_date": pd.date_range("2024-01-02", periods=len(values), freq="B"),
            "underlying_symbol": "RB",
            "close": values,
        }
    )
    frame.attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
        }
    )
    return frame


def test_multi_horizon_trend_averages_risk_adjusted_components() -> None:
    prices = research_prices([100.0, 101.0, 103.0, 102.0, 105.0, 108.0])
    result = calculate_multi_horizon_trend(
        prices,
        horizons=(2, 3),
        volatility_lookback=2,
        component_clip=None,
    )
    daily_returns = np.array([105.0 / 102.0 - 1.0, 108.0 / 105.0 - 1.0])
    annualized_vol = daily_returns.std(ddof=1) * math.sqrt(252)
    expected_2 = (108.0 / 102.0 - 1.0) / (annualized_vol * math.sqrt(2 / 252))
    expected_3 = (108.0 / 103.0 - 1.0) / (annualized_vol * math.sqrt(3 / 252))
    assert result.loc[5, "raw_factor"] == pytest.approx((expected_2 + expected_3) / 2)
    assert result.loc[5, "valid_horizons"] == 2
