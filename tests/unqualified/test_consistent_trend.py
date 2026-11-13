from __future__ import annotations

import pandas as pd
import pytest

from china_cta.factors.unqualified.consistent_trend import calculate_consistent_trend


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


def test_volatility_scaler_reduces_choppy_trend_with_same_endpoint() -> None:
    straight = research_prices([100, 102, 104, 106, 108, 110, 112])
    choppy = research_prices([100, 108, 101, 109, 102, 111, 112])
    straight_score = calculate_consistent_trend(
        straight,
        horizons=(3, 6),
        smoothing_span=1,
        deadband=0,
        rebalance_every=1,
    ).loc[6, "raw_factor"]
    choppy_score = calculate_consistent_trend(
        choppy,
        horizons=(3, 6),
        smoothing_span=1,
        deadband=0,
        rebalance_every=1,
    ).loc[6, "raw_factor"]
    assert straight_score == pytest.approx(1.0)
    assert 0 < choppy_score < straight_score


def test_consistent_trend_updates_only_on_rebalance_observations() -> None:
    prices = research_prices([100, 101, 102, 103, 104, 105, 104, 103, 102])
    result = calculate_consistent_trend(
        prices,
        horizons=(2, 3),
        smoothing_span=1,
        deadband=0,
        rebalance_every=3,
    )
    assert result.loc[6, "raw_factor"] == result.loc[7, "raw_factor"]
