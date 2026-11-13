import numpy as np
import pandas as pd
import pytest

from china_cta.research.curve_seasonality import (
    annual_delivery_month_panel,
    daily_curve_residuals,
    delivery_month_from_id,
)


def test_delivery_month_comes_from_contract_code_not_maturity_date():
    assert delivery_month_from_id("M2005") == 5
    assert delivery_month_from_id("CF501") == 1
    with pytest.raises(ValueError):
        delivery_month_from_id("M888")


def test_same_day_linear_curve_has_zero_residuals():
    tenors = [60, 120, 180, 240]
    frame = pd.DataFrame({
        "trading_date": ["2020-01-02"] * 4,
        "underlying_symbol": ["M"] * 4,
        "order_book_id": ["M2003", "M2005", "M2007", "M2009"],
        "days_to_maturity": tenors,
        "price": np.exp(7 + 0.1 * np.array(tenors) / 365),
        "price_field": ["close"] * 4,
        "volume": [100] * 4,
        "open_interest": [100] * 4,
    })
    residuals = daily_curve_residuals(frame)
    assert len(residuals) == 4
    assert np.max(np.abs(residuals["curve_residual"])) < 1e-12
    frame.loc[0, "price"] *= 1.1
    residuals = daily_curve_residuals(frame)
    assert np.max(np.abs(residuals["curve_residual"])) > 0.01
    annual = annual_delivery_month_panel(residuals, min_distinct_days=1)
    assert set(annual["delivery_month"]) == {3, 5, 7, 9}


def test_insufficient_curve_contracts_do_not_create_observations():
    frame = pd.DataFrame({
        "trading_date": ["2020-01-02"] * 3,
        "underlying_symbol": ["M"] * 3,
        "order_book_id": ["M2003", "M2005", "M2007"],
        "days_to_maturity": [60, 120, 180],
        "price": [100, 101, 102],
        "price_field": ["close"] * 3,
        "volume": [100] * 3,
        "open_interest": [100] * 3,
    })
    assert daily_curve_residuals(frame).empty


def test_relative_liquidity_filter_can_remove_illiquid_curve():
    frame = pd.DataFrame({
        "trading_date": ["2020-01-02"] * 4,
        "underlying_symbol": ["M"] * 4,
        "order_book_id": ["M2003", "M2005", "M2007", "M2009"],
        "days_to_maturity": [60, 120, 180, 240],
        "price": [100, 101, 102, 103],
        "price_field": ["close"] * 4,
        "volume": [10000, 10000, 10000, 10],
        "open_interest": [10000, 10000, 10000, 10],
    })
    assert len(daily_curve_residuals(frame)) == 4
    assert daily_curve_residuals(
        frame, min_volume_share=0.01, min_open_interest_share=0.01,
    ).empty
    assert len(daily_curve_residuals(frame, curve_degree=2)) == 4
