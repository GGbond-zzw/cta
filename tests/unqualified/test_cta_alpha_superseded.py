"""Factor-level tests for qualified factors."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from china_cta.factors.cta_common import cross_sectional_table
from china_cta.factors.cta_curve import calculate_curve_metrics
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum
from china_cta.factors.unqualified.breakout_55 import calculate_breakout_55


def research_prices(series: dict[str, list[float]]) -> pd.DataFrame:
    frames = []
    for instrument, values in series.items():
        dates = pd.bdate_range("2023-01-02", periods=len(values))
        frames.append(
            pd.DataFrame(
                {
                    "trading_date": dates,
                    "underlying_symbol": instrument,
                    "close": values,
                    "high": [value + 1.0 for value in values],
                    "low": [value - 1.0 for value in values],
                    "volume": 1_000.0,
                    "open_interest": 1_000.0,
                }
            )
        )
    result = pd.concat(frames, ignore_index=True)
    result.attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
        }
    )
    return result


def universe_for(prices: pd.DataFrame) -> pd.DataFrame:
    return (
        prices.loc[:, ["trading_date", "underlying_symbol"]]
        .rename(columns={"underlying_symbol": "instrument"})
        .drop_duplicates()
        .assign(eligible=True)
        .reset_index(drop=True)
    )


def snapshots(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame["maturity_date"] = pd.to_datetime(frame["maturity_date"]).dt.normalize()
    frame["days_to_maturity"] = (
        frame["maturity_date"] - frame["trading_date"]
    ).dt.days
    frame["price_field"] = "close"
    return frame.rename(
        columns={"instrument": "underlying_symbol", "contract": "order_book_id"}
    )


def test_breakout_55_is_bounded_and_one_for_monotonic_prices() -> None:
    values = [100.0 + index for index in range(120)]
    prices = research_prices({"RB": values})
    prices.loc[:, "high"] = values
    prices.loc[:, "low"] = [value - 2.0 for value in values]
    result = calculate_breakout_55(prices, window=55)
    valid = result["raw_factor"].dropna()
    assert not valid.empty
    assert valid.between(-1.0, 1.0).all()
    assert result["raw_factor"].iloc[-1] == pytest.approx(1.0)


def test_cross_sectional_momentum_ranks_two_peers_symmetrically() -> None:
    rising = [100.0 * (1.001 ** index) for index in range(300)]
    falling = [100.0 * (0.999 ** index) for index in range(300)]
    prices = research_prices({"RB": rising, "CU": falling})
    universe = universe_for(prices)
    raw = calculate_time_series_momentum(prices, lookback=252, skip=21)
    factor = cross_sectional_table(
        raw, universe, factor_name="xsmom_252_21"
    )
    latest = factor.iloc[-2:]
    scores = latest.set_index("instrument")["raw_factor"].to_dict()
    assert scores["RB"] == pytest.approx(1.0)
    assert scores["CU"] == pytest.approx(-1.0)


def test_carry_metrics_match_manual_formula() -> None:
    rows = [
        {"trading_date": "2024-01-02", "instrument": "RB", "contract": "RB2402", "maturity_date": "2024-01-12", "price": 999.0},
        {"trading_date": "2024-01-02", "instrument": "RB", "contract": "RB2402b", "maturity_date": "2024-02-02", "price": 110.0},
        {"trading_date": "2024-01-02", "instrument": "RB", "contract": "RB2403", "maturity_date": "2024-03-03", "price": 108.0},
        {"trading_date": "2024-01-02", "instrument": "RB", "contract": "RB2404", "maturity_date": "2024-04-02", "price": 100.0},
    ]
    result = calculate_curve_metrics(snapshots(rows), min_days_to_maturity=30)
    row = result.iloc[0]
    assert row["near_contract"] == "RB2402B"
    assert row["far_contract"] == "RB2403"
    assert row["third_contract"] == "RB2404"
    assert row["carry_ann"] == pytest.approx((110.0 / 108.0 - 1.0) * 365.0 / 30.0)
    assert row["ts_slope"] == pytest.approx(math.log(108.0 / 110.0) / 30.0)
    assert row["ts_curvature"] == pytest.approx((100.0 - 2 * 108.0 + 110.0) / 108.0)


def test_carry_requires_two_eligible_contracts() -> None:
    rows = [
        {"trading_date": "2024-01-02", "instrument": "RB", "contract": "RB2402", "maturity_date": "2024-02-02", "price": 110.0},
    ]
    result = calculate_curve_metrics(snapshots(rows), min_days_to_maturity=30)
    assert pd.isna(result.iloc[0]["carry_ann"])
    assert result.iloc[0]["status"] == "insufficient_contracts"
