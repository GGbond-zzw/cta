"""Factor-level tests for unqualified factors."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from china_cta.factors.cta_common import FactorDataUnavailable
from china_cta.factors.cta_momentum_base import calculate_time_series_momentum
from china_cta.factors.unqualified.broker_net_chg_5 import (
    calculate_broker_net_chg_5,
)
from china_cta.factors.unqualified.ema_xover_20_100 import calculate_ema_xover
from china_cta.factors.unqualified.lowvol import calculate_lowvol
from china_cta.factors.unqualified.oi_price_confirm_20 import (
    calculate_oi_price_confirm_20,
)
from china_cta.factors.unqualified.receipt_mom_20 import calculate_receipt_mom_20
from china_cta.factors.unqualified.roll_return_63 import calculate_roll_return_63
from china_cta.factors.unqualified.st_reversal_5 import calculate_st_reversal_5
from china_cta.factors.unqualified.virtual_ratio_chg import (
    calculate_virtual_ratio_chg,
)


def research_prices(
    series: dict[str, list[float]],
    *,
    volume: float = 1_000.0,
    open_interest: float = 1_000.0,
) -> pd.DataFrame:
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
                    "volume": volume,
                    "open_interest": open_interest,
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


def test_tsmom_252_21_matches_manual_lagged_return() -> None:
    values = [100.0 + index for index in range(300)]
    prices = research_prices({"RB": values})
    result = calculate_time_series_momentum(prices, lookback=252, skip=21)
    expected = values[278] / values[47] - 1.0
    assert result["raw_factor"].iloc[-1] == pytest.approx(expected)
    assert result["raw_factor"].iloc[:252].isna().all()
    assert pd.notna(result["raw_factor"].iloc[252])


def test_tsmom_window_rejects_a_missing_price_inside_the_window() -> None:
    values = [100.0 + index for index in range(300)]
    values[100] = np.nan
    prices = research_prices({"RB": values})
    result = calculate_time_series_momentum(prices, lookback=252, skip=21)
    assert pd.isna(result["raw_factor"].iloc[279])


def test_ema_xover_is_positive_for_an_uptrend() -> None:
    values = [100.0 * (1.002 ** index) for index in range(200)]
    prices = research_prices({"RB": values})
    result = calculate_ema_xover(prices)
    assert result["raw_factor"].iloc[-1] > 0


def test_roll_return_is_positive_in_backwardation_and_accumulates() -> None:
    dates = pd.bdate_range("2024-01-02", periods=70)
    rows = []
    for date in dates:
        for contract, price, maturity in (
            ("RB2405", 100.0, "2024-05-15"),
            ("RB2410", 90.0, "2024-10-15"),
        ):
            rows.append(
                {
                    "trading_date": date,
                    "instrument": "RB",
                    "contract": contract,
                    "maturity_date": maturity,
                    "price": price,
                }
            )
    mapping = pd.DataFrame(
        {
            "trading_date": dates,
            "underlying_symbol": "RB",
            "dominant_order_book_id": ["RB2405"] * 65 + ["RB2410"] * 5,
            "changed": [False] * 65 + [True] + [False] * 4,
        }
    )
    result = calculate_roll_return_63(snapshots(rows), mapping, window=63)
    assert result["raw_factor"].iloc[64] == pytest.approx(0.0)
    assert result["raw_factor"].iloc[65] == pytest.approx(100.0 / 90.0 - 1.0)
    assert result["raw_factor"].iloc[62:].notna().all()


def test_oi_price_confirmation_uses_price_sign_and_oi_growth() -> None:
    rising = [100.0 + index for index in range(30)]
    prices = research_prices({"RB": rising}, open_interest=100.0)
    prices.loc[prices.index, "open_interest"] = [
        100.0 + index for index in range(30)
    ]
    result = calculate_oi_price_confirm_20(prices)
    assert result["raw_factor"].iloc[-1] == pytest.approx(math.log(129.0 / 109.0))
    falling = [130.0 - index for index in range(30)]
    falling_prices = research_prices({"RB": falling}, open_interest=100.0)
    falling_prices.loc[falling_prices.index, "open_interest"] = [
        100.0 + index for index in range(30)
    ]
    assert calculate_oi_price_confirm_20(falling_prices)["raw_factor"].iloc[-1] < 0


def test_virtual_ratio_change_uses_oi_over_volume() -> None:
    prices = research_prices(
        {"RB": [100.0] * 21}, volume=1_000.0, open_interest=1_000.0
    )
    prices.loc[prices.index[-1], "volume"] = 500.0
    result = calculate_virtual_ratio_chg(prices)
    assert result["raw_factor"].iloc[-1] == pytest.approx(1.0)


def _member_frame(dates: pd.DatetimeIndex, long_values: list[float]) -> pd.DataFrame:
    rows = []
    for date, long_value in zip(dates, long_values, strict=True):
        rows.append(
            {
                "trading_date": date,
                "underlying_symbol": "RB",
                "side": "long",
                "rank": 1,
                "member_name": "A",
                "volume": long_value,
            }
        )
        rows.append(
            {
                "trading_date": date,
                "underlying_symbol": "RB",
                "side": "short",
                "rank": 1,
                "member_name": "B",
                "volume": 50.0,
            }
        )
    return pd.DataFrame(rows)


def test_broker_net_change_is_scaled_by_total_oi() -> None:
    dates = pd.bdate_range("2024-01-02", periods=6)
    member = _member_frame(dates, [100.0, 101.0, 102.0, 103.0, 104.0, 110.0])
    rows = []
    for date in dates:
        for contract, price in (("RB2405", 100.0), ("RB2410", 90.0)):
            rows.append(
                {
                    "trading_date": date,
                    "instrument": "RB",
                    "contract": contract,
                    "maturity_date": "2025-01-01",
                    "price": price,
                    "open_interest": 500.0,
                }
            )
    result = calculate_broker_net_chg_5(
        snapshots(rows), member, top_n=20, lookback=5
    )
    assert result["raw_factor"].iloc[-1] == pytest.approx(0.01)


def test_receipt_growth_matches_log_ratio() -> None:
    dates = pd.bdate_range("2024-01-02", periods=21)
    warehouse = pd.DataFrame(
        {
            "trading_date": dates,
            "underlying_symbol": "RB",
            "on_warrant": [100.0] * 20 + [200.0],
        }
    )
    result = calculate_receipt_mom_20(warehouse)
    assert result["raw_factor"].iloc[-1] == pytest.approx(math.log(2.0))
    assert result["raw_factor"].iloc[:20].isna().all()


def test_lowvol_and_short_term_reversal_have_expected_signs() -> None:
    values = [100.0 + (index % 2) * 2.0 + index * 0.1 for index in range(60)]
    prices = research_prices({"RB": values})
    lowvol = calculate_lowvol(prices)
    valid = lowvol["raw_factor"].dropna()
    assert not valid.empty
    assert valid.lt(0).all()
    manual_returns = pd.Series(values).pct_change().pipe(np.log1p)
    manual_vol = manual_returns.rolling(20, min_periods=20).std(ddof=1) * math.sqrt(252)
    assert valid.iloc[-1] == pytest.approx(-manual_vol.iloc[-1])
    reversal = calculate_st_reversal_5(prices)
    assert reversal["raw_factor"].iloc[-1] == pytest.approx(
        -(values[-1] / values[-6] - 1.0)
    )


def test_unavailable_factors_raise_with_reason() -> None:
    from china_cta.factors.unqualified.inventory_mom_20 import (
        build as build_inventory,
    )
    from china_cta.factors.unqualified.ls_ratio_z import build as build_ls_ratio
    from china_cta.factors.unqualified.spot_profit_z import build as build_spot_profit

    for builder in (build_inventory, build_ls_ratio, build_spot_profit):
        with pytest.raises(FactorDataUnavailable):
            builder({})
