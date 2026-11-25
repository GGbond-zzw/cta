from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.qualified.oi_participation_trend_60d import (
    calculate_oi_participation_trend,
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


def oi_snapshots(totals: list[float]) -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-02", periods=len(totals), freq="B")
    for date, total in zip(dates, totals, strict=True):
        for contract, fraction in (("RB2405", 0.4), ("RB2410", 0.6)):
            rows.append(
                {
                    "trading_date": date,
                    "underlying_symbol": "RB",
                    "order_book_id": contract,
                    "open_interest": total * fraction,
                }
            )
    return pd.DataFrame(rows)


def test_oi_participation_is_bounded_and_scales_trend_not_direction() -> None:
    prices = research_prices([100 + index for index in range(16)])
    totals = [
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
        115,
        125,
        140,
        160,
        185,
    ]
    result = calculate_oi_participation_trend(
        prices,
        oi_snapshots(totals),
        trend_horizons=(2, 3),
        trend_smoothing_span=1,
        trend_deadband=0,
        oi_growth_lookback=2,
        oi_smoothing_span=1,
        oi_normalization_lookback=4,
        minimum_oi_observations=3,
        rebalance_every=1,
    )
    valid = result.dropna(subset=["raw_factor"])
    assert valid["participation_weight"].between(0, 1).all()
    assert (valid["raw_factor"] >= 0).all()
    assert (
        valid.iloc[-1]["participation_weight"]
        > valid.iloc[0]["participation_weight"]
    )


def test_missing_oi_invalidates_participation_signal_without_filling() -> None:
    prices = research_prices([100 + index for index in range(12)])
    snapshots = oi_snapshots([100 + index for index in range(12)])
    target_date = prices.loc[7, "trading_date"]
    snapshots.loc[
        snapshots["trading_date"].eq(target_date)
        & snapshots["order_book_id"].eq("RB2405"),
        "open_interest",
    ] = np.nan
    result = calculate_oi_participation_trend(
        prices,
        snapshots,
        trend_horizons=(2, 3),
        trend_smoothing_span=1,
        trend_deadband=0,
        oi_growth_lookback=1,
        oi_smoothing_span=1,
        oi_normalization_lookback=3,
        minimum_oi_observations=2,
        rebalance_every=1,
    )
    exact = result.loc[result["trading_date"].eq(target_date)].iloc[0]
    assert pd.isna(exact["open_interest_growth"])
    assert pd.isna(exact["raw_factor"])
