from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.oi_confirmed_trend import (
    calculate_oi_confirmed_trend,
    compute_oi_confirmed_trend_factor,
)
from china_cta.factors.schema import FACTOR_COLUMNS


def research_prices(
    prices: list[float],
    open_interest: list[float],
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trading_date": pd.date_range("2020-01-02", periods=len(prices), freq="B"),
            "underlying_symbol": "RB",
            "close": prices,
            "open_interest": open_interest,
        }
    )
    frame.attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
            "rule": 0,
            "rank": 1,
        }
    )
    return frame


def dominant_map(prices: pd.DataFrame, *, change_at: int | None = None) -> pd.DataFrame:
    contracts = ["RB2005"] * len(prices)
    changed = [False] * len(prices)
    if change_at is not None:
        contracts[change_at:] = ["RB2010"] * (len(prices) - change_at)
        changed[change_at] = True
    return pd.DataFrame(
        {
            "trading_date": prices["trading_date"],
            "underlying_symbol": "RB",
            "dominant_order_book_id": contracts,
            "changed": changed,
        }
    )


def universe(prices: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trading_date": prices["trading_date"],
            "instrument": "RB",
            "eligible": True,
        }
    )


def test_oi_confirmed_trend_is_manually_reproducible() -> None:
    prices = research_prices([100.0, 105.0, 110.0], [1_000.0, 1_100.0, 1_210.0])
    mapping = dominant_map(prices)

    diagnostics = calculate_oi_confirmed_trend(prices, mapping, lookback=2)
    factor = compute_oi_confirmed_trend_factor(
        prices,
        mapping,
        universe(prices),
        lookback=2,
        signal_scale=0.02,
    )

    expected_price_return = 110.0 / 100.0 - 1.0
    expected_oi_change = 1_210.0 / 1_000.0 - 1.0
    expected_raw = expected_price_return * expected_oi_change
    assert diagnostics.loc[2, "price_return"] == pytest.approx(
        expected_price_return
    )
    assert diagnostics.loc[2, "open_interest_change"] == pytest.approx(
        expected_oi_change
    )
    assert diagnostics.loc[2, "raw_factor"] == pytest.approx(expected_raw)
    assert tuple(factor.columns) == FACTOR_COLUMNS
    assert factor.loc[2, "factor_name"] == "oi_confirmed_trend_2d"
    assert factor.loc[2, "raw_factor"] == pytest.approx(expected_raw)
    assert factor.loc[2, "signal"] == 1.0


def test_falling_open_interest_reduces_confirmation_to_zero() -> None:
    prices = research_prices([100.0, 105.0, 110.0], [1_000.0, 950.0, 900.0])

    result = calculate_oi_confirmed_trend(
        prices,
        dominant_map(prices),
        lookback=2,
    )

    assert result.loc[2, "price_return"] == pytest.approx(0.10)
    assert result.loc[2, "open_interest_change"] == pytest.approx(-0.10)
    assert result.loc[2, "oi_confirmation"] == 0.0
    assert result.loc[2, "raw_factor"] == 0.0


def test_roll_in_lookback_window_makes_factor_unavailable() -> None:
    prices = research_prices([100.0, 105.0, 110.0], [1_000.0, 1_100.0, 1_210.0])

    result = calculate_oi_confirmed_trend(
        prices,
        dominant_map(prices, change_at=1),
        lookback=2,
    )

    assert result.loc[2, "roll_in_window"]
    assert pd.isna(result.loc[2, "raw_factor"])


def test_missing_open_interest_invalidates_window_without_filling() -> None:
    prices = research_prices([100.0, 105.0, 110.0], [1_000.0, np.nan, 1_210.0])

    result = calculate_oi_confirmed_trend(
        prices,
        dominant_map(prices),
        lookback=2,
    )

    assert pd.isna(result.loc[2, "raw_factor"])


def test_future_perturbation_cannot_change_earlier_factor() -> None:
    prices = research_prices(
        [100.0, 105.0, 110.0, 1_000.0],
        [1_000.0, 1_100.0, 1_210.0, 9_000.0],
    )
    mapping = dominant_map(prices)
    original = calculate_oi_confirmed_trend(prices, mapping, lookback=2)
    changed = prices.copy()
    changed.attrs = prices.attrs.copy()
    changed.loc[3, ["close", "open_interest"]] = [1.0, 1.0]
    recomputed = calculate_oi_confirmed_trend(changed, mapping, lookback=2)

    assert original.loc[2, "raw_factor"] == recomputed.loc[2, "raw_factor"]


def test_oi_factor_rejects_non_ratio_adjusted_prices() -> None:
    prices = research_prices([100.0, 105.0], [1_000.0, 1_100.0])
    prices.attrs["adjust_method"] = "prev_close_spread"

    with pytest.raises(ValueError, match="prev_close_ratio"):
        calculate_oi_confirmed_trend(prices, dominant_map(prices), lookback=1)
