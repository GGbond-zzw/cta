"""Focused offline checks for the absolute historical-skewness factor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.schema import FACTOR_COLUMNS
from china_cta.factors.qualified.historical_skewness import (
    calculate_historical_skewness,
    compute_historical_skewness_factor,
)


def _prices(values: dict[str, list[float]]) -> pd.DataFrame:
    dates = pd.date_range(
        "2024-01-02", periods=len(next(iter(values.values()))), freq="B"
    )
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "trading_date": dates,
                    "underlying_symbol": instrument,
                    "close": closes,
                }
            )
            for instrument, closes in values.items()
        ],
        ignore_index=True,
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


def _prices_from_returns(returns: list[float], instrument: str = "RB") -> pd.DataFrame:
    closes = [100.0]
    for value in returns:
        closes.append(closes[-1] * (1.0 + value))
    return _prices({instrument: closes})


def _universe(prices: pd.DataFrame, *, excluded: str | None = None) -> pd.DataFrame:
    frame = prices.loc[:, ["trading_date", "underlying_symbol"]].rename(
        columns={"underlying_symbol": "instrument"}
    )
    frame["eligible"] = frame["instrument"].ne(excluded)
    return frame


def test_skewness_matches_complete_return_window_and_direction() -> None:
    returns = [-0.20, 0.02, 0.03, 0.04]
    prices = _prices_from_returns(returns)
    diagnostic = calculate_historical_skewness(prices, lookback=4)

    expected = pd.Series(returns, dtype="float64").skew()
    last = diagnostic.iloc[-1]
    assert last["raw_skewness"] == pytest.approx(expected)
    assert last["raw_factor"] == pytest.approx(-expected)
    assert last["raw_factor"] > 0
    assert diagnostic.iloc[:-1]["raw_factor"].isna().all()


def test_missing_price_is_not_filled_and_requires_a_complete_window() -> None:
    prices = _prices({"RB": [100, 101, np.nan, 103, 104, 105, 106, 107]})
    diagnostic = calculate_historical_skewness(prices, lookback=3)

    assert diagnostic.loc[:5, "raw_factor"].isna().all()
    assert diagnostic.loc[6:, "raw_factor"].notna().all()


def test_factor_uses_standard_schema_and_point_in_time_universe() -> None:
    rb = _prices_from_returns([-0.20, 0.02, 0.03, 0.04], "RB")
    cu = _prices_from_returns([0.20, -0.02, -0.03, -0.04], "CU")
    prices = pd.concat([rb, cu], ignore_index=True)
    prices.attrs.update(rb.attrs)
    universe = _universe(prices, excluded="CU")

    factor = compute_historical_skewness_factor(
        prices, universe, lookback=4, signal_scale=1.0
    )

    assert tuple(factor.columns) == FACTOR_COLUMNS
    assert set(factor["instrument"]) == {"RB"}
    assert factor["factor_name"].eq("historical_skewness_4d").all()
    assert factor["signal"].dropna().between(-1.0, 1.0).all()
    assert factor.attrs["earliest_trade_at"] == "next_trading_session"
    assert factor.attrs["raw_factor_normalization"] == "none"


def test_future_price_change_cannot_rewrite_past_values() -> None:
    prices = _prices_from_returns([-0.08, 0.01, 0.02, 0.03, 0.04, 0.05])
    original = calculate_historical_skewness(prices, lookback=3)
    changed = prices.copy()
    changed.attrs.update(prices.attrs)
    changed.loc[changed.index[-1], "close"] = 999.0
    later = calculate_historical_skewness(changed, lookback=3)

    pd.testing.assert_frame_equal(original.iloc[:-1], later.iloc[:-1])


def test_rejects_non_project_prices_bad_windows_and_duplicates() -> None:
    prices = _prices_from_returns([0.01, 0.02, 0.03])
    prices.attrs.pop("cash_pnl_allowed")
    with pytest.raises(ValueError, match="cash P&L"):
        calculate_historical_skewness(prices, lookback=3)

    valid = _prices_from_returns([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="lookback"):
        calculate_historical_skewness(valid, lookback=True)
    with pytest.raises(ValueError, match="lookback"):
        calculate_historical_skewness(valid, lookback=2)

    duplicate = pd.concat([valid, valid.iloc[[0]]], ignore_index=True)
    duplicate.attrs.update(valid.attrs)
    with pytest.raises(ValueError, match="duplicate"):
        calculate_historical_skewness(duplicate, lookback=3)
