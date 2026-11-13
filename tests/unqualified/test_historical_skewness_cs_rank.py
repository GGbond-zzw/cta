"""Focused offline checks for the cross-sectional skewness factor."""

from __future__ import annotations

import pandas as pd
import pytest

from china_cta.factors.unqualified.historical_skewness_cs_rank import (
    compute_historical_skewness_factor_cs_rank,
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


def test_cs_rank_uses_only_eligible_same_day_peers() -> None:
    frames = [
        _prices_from_returns([-0.20, 0.02, 0.03, 0.04], "RB"),
        _prices_from_returns([-0.10, -0.02, 0.02, 0.10], "IF"),
        _prices_from_returns([0.20, -0.02, -0.03, -0.04], "CU"),
        _prices_from_returns([-0.50, 0.01, 0.02, 0.03], "AG"),
    ]
    prices = pd.concat(frames, ignore_index=True)
    prices.attrs.update(frames[0].attrs)
    universe = _universe(prices, excluded="AG")

    with_excluded = compute_historical_skewness_factor_cs_rank(
        prices, universe, lookback=4
    )
    eligible_prices = prices.loc[prices["underlying_symbol"].ne("AG")].copy()
    eligible_prices.attrs.update(prices.attrs)
    without_excluded = compute_historical_skewness_factor_cs_rank(
        eligible_prices, universe, lookback=4
    )

    pd.testing.assert_frame_equal(with_excluded, without_excluded)
    latest = with_excluded.loc[
        with_excluded["trading_date"].eq(with_excluded["trading_date"].max())
    ].set_index("instrument")
    assert latest.loc["RB", "signal"] == pytest.approx(1.0)
    assert latest.loc["IF", "signal"] == pytest.approx(0.0)
    assert latest.loc["CU", "signal"] == pytest.approx(-1.0)
    assert set(with_excluded["instrument"]) == {"RB", "IF", "CU"}
    assert with_excluded.attrs["minimum_valid_peers"] == 2
    assert with_excluded.attrs["earliest_trade_at"] == "next_trading_session"


def test_cs_rank_ties_are_neutral_and_single_peer_is_unavailable() -> None:
    rb = _prices_from_returns([-0.10, -0.02, 0.02, 0.10], "RB")
    cu = _prices_from_returns([-0.10, -0.02, 0.02, 0.10], "CU")
    tied_prices = pd.concat([rb, cu], ignore_index=True)
    tied_prices.attrs.update(rb.attrs)
    tied = compute_historical_skewness_factor_cs_rank(
        tied_prices, _universe(tied_prices), lookback=4
    )
    latest = tied.loc[tied["trading_date"].eq(tied["trading_date"].max())]
    assert latest["signal"].eq(0.0).all()

    single = compute_historical_skewness_factor_cs_rank(
        rb, _universe(rb), lookback=4
    )
    assert single["signal"].isna().all()
