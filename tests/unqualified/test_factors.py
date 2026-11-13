from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.unqualified.carry import (
    calculate_near_main_carry,
    compute_carry_factor,
)
from china_cta.factors.schema import FACTOR_COLUMNS, make_factor_table
from china_cta.factors.unqualified.trend import compute_trend_factor


def universe_for(dates, instruments=("RB",), eligible=True) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trading_date": date,
                "instrument": instrument,
                "eligible": eligible,
            }
            for date in pd.to_datetime(dates)
            for instrument in instruments
        ]
    )


def signal_prices(values, *, instrument="RB") -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "trading_date": pd.date_range("2020-01-02", periods=len(values), freq="B"),
            "underlying_symbol": instrument,
            "close": values,
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


def carry_snapshot(*, near_price=110.0, include_near=True) -> pd.DataFrame:
    rows = [
        {
            "trading_date": "2020-06-12",
            "underlying_symbol": "RB",
            "order_book_id": "RB2006",
            "maturity_date": "2020-06-15",
            "days_to_maturity": 3,
            "price": near_price,
            "price_field": "close",
            "dominant_rank": pd.NA,
        },
        {
            "trading_date": "2020-06-12",
            "underlying_symbol": "RB",
            "order_book_id": "RB2007",
            "maturity_date": "2020-07-15",
            "days_to_maturity": 33,
            "price": 108.0,
            "price_field": "close",
            "dominant_rank": pd.NA,
        },
        {
            "trading_date": "2020-06-12",
            "underlying_symbol": "RB",
            "order_book_id": "RB2010",
            "maturity_date": "2020-10-15",
            "days_to_maturity": 125,
            "price": 100.0,
            "price_field": "close",
            "dominant_rank": 1,
        },
    ]
    if not include_near:
        rows = rows[-1:]
    return pd.DataFrame(rows)


def test_factor_schema_filters_universe_and_clips_signal() -> None:
    raw = pd.DataFrame(
        {
            "trading_date": ["2020-01-02", "2020-01-02"],
            "instrument": ["rb", "si"],
            "raw_factor": [0.30, -0.30],
        }
    )
    universe = pd.DataFrame(
        {
            "trading_date": ["2020-01-02", "2020-01-02"],
            "instrument": ["RB", "SI"],
            "eligible": [True, False],
        }
    )

    result = make_factor_table(
        raw, universe, factor_name="trend_60d", signal_scale=0.20
    )

    assert tuple(result.columns) == FACTOR_COLUMNS
    assert result["instrument"].tolist() == ["RB"]
    assert result.loc[0, "raw_factor"] == 0.30
    assert result.loc[0, "signal"] == 1.0
    assert result.attrs["signal_available_at"] == "after_close_of_trading_date"
    assert result.attrs["earliest_trade_at"] == "next_trading_session"
    assert result.attrs["signal_is_position"] is False


def test_factor_schema_preserves_negative_short_bias() -> None:
    result = make_factor_table(
        pd.DataFrame(
            {
                "trading_date": ["2020-01-02"],
                "instrument": ["CU"],
                "raw_factor": [-0.10],
            }
        ),
        universe_for(["2020-01-02"], instruments=("CU",)),
        factor_name="carry_near_main",
        signal_scale=0.20,
    )

    assert result.loc[0, "signal"] == pytest.approx(-0.5)


def test_trend_is_manual_return_and_preserves_insufficient_history() -> None:
    prices = signal_prices([100.0, 110.0, 121.0])
    universe = universe_for(prices["trading_date"])

    result = compute_trend_factor(
        prices, universe, lookback=2, signal_scale=0.20
    )

    assert tuple(result.columns) == FACTOR_COLUMNS
    assert result["factor_name"].unique().tolist() == ["trend_2d"]
    assert result["raw_factor"].iloc[:2].isna().all()
    assert result.loc[2, "raw_factor"] == pytest.approx(121.0 / 100.0 - 1.0)
    assert result.loc[2, "signal"] == 1.0


def test_trend_missing_price_invalidates_full_window_without_filling() -> None:
    prices = signal_prices([100.0, np.nan, 121.0])

    result = compute_trend_factor(
        prices,
        universe_for(prices["trading_date"]),
        lookback=2,
    )

    assert result["raw_factor"].isna().all()
    assert result["signal"].isna().all()


def test_trend_does_not_reference_a_future_price() -> None:
    prices = signal_prices([100.0, 105.0, 110.0, 1_000.0])
    universe = universe_for(prices["trading_date"])
    original = compute_trend_factor(prices, universe, lookback=2)
    changed = prices.copy()
    changed.attrs = prices.attrs.copy()
    changed.loc[3, "close"] = 10.0
    recomputed = compute_trend_factor(changed, universe, lookback=2)

    assert original.loc[2, "raw_factor"] == recomputed.loc[2, "raw_factor"]
    assert original.loc[2, "raw_factor"] == pytest.approx(0.10)


def test_trend_rejects_non_ratio_continuous_adjustment() -> None:
    prices = signal_prices([100.0, 101.0])
    prices.attrs["adjust_method"] = "prev_close_spread"

    with pytest.raises(ValueError, match="prev_close_ratio"):
        compute_trend_factor(
            prices, universe_for(prices["trading_date"]), lookback=1
        )


def test_carry_selects_real_near_and_main_and_is_manually_reproducible() -> None:
    snapshots = carry_snapshot()

    diagnostics = calculate_near_main_carry(snapshots)
    factor = compute_carry_factor(
        snapshots,
        universe_for(["2020-06-12"]),
        signal_scale=0.20,
    )

    expected = (110.0 / 100.0 - 1.0) * 365.0 / 122.0
    assert diagnostics.loc[0, "near_contract"] == "RB2006"
    assert diagnostics.loc[0, "far_contract"] == "RB2010"
    assert diagnostics.loc[0, "maturity_gap_days"] == 122
    assert diagnostics.loc[0, "raw_factor"] == pytest.approx(expected)
    assert tuple(factor.columns) == FACTOR_COLUMNS
    assert factor.loc[0, "raw_factor"] == pytest.approx(expected)
    assert factor.loc[0, "signal"] == pytest.approx(min(expected / 0.20, 1.0))
    assert factor.loc[0, "factor_name"] == "carry_near_main"


def test_carry_does_not_skip_a_selected_contract_with_missing_price() -> None:
    diagnostics = calculate_near_main_carry(carry_snapshot(near_price=np.nan))

    assert diagnostics.loc[0, "near_contract"] == "RB2006"
    assert pd.isna(diagnostics.loc[0, "raw_factor"])


def test_carry_with_only_one_contract_is_unavailable() -> None:
    diagnostics = calculate_near_main_carry(carry_snapshot(include_near=False))

    assert pd.isna(diagnostics.loc[0, "near_contract"])
    assert pd.isna(diagnostics.loc[0, "raw_factor"])


def test_carry_with_no_earlier_maturity_is_unavailable() -> None:
    snapshots = carry_snapshot(include_near=False)
    same_maturity = snapshots.iloc[0].copy()
    same_maturity["order_book_id"] = "RB2010B"
    same_maturity["dominant_rank"] = pd.NA
    snapshots = pd.concat(
        [snapshots, same_maturity.to_frame().T], ignore_index=True
    )

    diagnostics = calculate_near_main_carry(snapshots)

    assert pd.isna(diagnostics.loc[0, "near_contract"])
    assert pd.isna(diagnostics.loc[0, "raw_factor"])


def test_carry_requires_close_curve() -> None:
    snapshots = carry_snapshot()
    snapshots["price_field"] = "settlement"

    with pytest.raises(ValueError, match="close"):
        calculate_near_main_carry(snapshots)
