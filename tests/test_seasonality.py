import numpy as np
import pandas as pd
import pytest

from china_cta.research.seasonality import (
    calendar_return_diagnostics,
    held_contract_returns,
    monthly_return_panel,
)


def test_roll_does_not_create_cross_contract_return():
    mapping = pd.DataFrame({
        "trading_date": ["2020-01-02", "2020-01-03", "2020-01-06"],
        "underlying_symbol": ["M"] * 3,
        "dominant_order_book_id": ["M2005", "M2009", "M2009"],
    })
    bars = pd.DataFrame({
        "trading_date": ["2020-01-02", "2020-01-03", "2020-01-03", "2020-01-06"],
        "order_book_id": ["M2005", "M2005", "M2009", "M2009"],
        "close": [100, 101, 200, 202],
    })
    result = held_contract_returns(mapping, bars)
    assert np.isnan(result.iloc[0]["log_return"])
    assert result.iloc[1]["log_return"] == pytest.approx(np.log(101 / 100))
    assert result.iloc[2]["log_return"] == pytest.approx(np.log(202 / 200))


def test_missing_same_contract_price_is_not_filled():
    mapping = pd.DataFrame({
        "trading_date": ["2020-01-02", "2020-01-03"],
        "underlying_symbol": ["M", "M"],
        "dominant_order_book_id": ["M2005", "M2009"],
    })
    bars = pd.DataFrame({
        "trading_date": ["2020-01-02", "2020-01-03"],
        "order_book_id": ["M2005", "M2009"],
        "close": [100, 200],
    })
    assert held_contract_returns(mapping, bars)["log_return"].isna().all()


def test_monthly_coverage_rejects_sparse_month():
    daily = pd.DataFrame({
        "trading_date": ["2020-01-02", "2020-01-03", "2020-01-06"],
        "underlying_symbol": ["M"] * 3,
        "log_return": [0.1, np.nan, np.nan],
    })
    result = monthly_return_panel(daily, min_coverage=0.8)
    assert result.iloc[0]["coverage"] == pytest.approx(1 / 3)
    assert np.isnan(result.iloc[0]["log_return"])


def test_oos_diagnostic_never_trains_on_test_year():
    rows = []
    for year in range(2010, 2020):
        for month in range(1, 13):
            rows.append(("M", year, month, 0.1 if month == 1 else -0.01))
    data = pd.DataFrame(rows, columns=[
        "underlying_symbol", "year", "calendar_month", "log_return"
    ])
    result = calendar_return_diagnostics(data, min_train_years=5, min_test_years=3)
    assert result.iloc[0]["tested_years"] == 5
    assert result.iloc[0]["oos_seasonal_r2"] == pytest.approx(1.0)
    altered = data.copy()
    altered.loc[altered["year"] == 2019, "log_return"] *= -1
    diagnostic = calendar_return_diagnostics(altered, min_train_years=5, min_test_years=3)
    assert diagnostic.iloc[0]["oos_seasonal_r2"] < 1
