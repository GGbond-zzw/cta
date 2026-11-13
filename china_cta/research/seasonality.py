"""Point-in-time diagnostics for calendar seasonality in commodity futures."""

from __future__ import annotations

import numpy as np
import pandas as pd


def held_contract_returns(dominant_map: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Price yesterday's dominant *real contract* on both consecutive dates.

    A roll changes tomorrow's selected contract; it never creates a return
    by dividing prices of two different contracts. Missing prices remain NaN.
    """
    required_map = {"trading_date", "underlying_symbol", "dominant_order_book_id"}
    required_bars = {"trading_date", "order_book_id", "close"}
    if required_map - set(dominant_map) or required_bars - set(bars):
        raise ValueError("dominant_map or bars is missing required columns")
    mapping = dominant_map.loc[:, list(required_map)].copy()
    prices = bars.loc[:, list(required_bars)].copy()
    for frame in (mapping, prices):
        frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    if mapping.duplicated(["trading_date", "underlying_symbol"]).any():
        raise ValueError("duplicate product-date in dominant_map")
    if prices.duplicated(["trading_date", "order_book_id"]).any():
        raise ValueError("duplicate contract-date in bars")
    mapping = mapping.sort_values(["underlying_symbol", "trading_date"])
    mapping["held_contract"] = mapping.groupby("underlying_symbol")[
        "dominant_order_book_id"
    ].shift(1)
    mapping["previous_date"] = mapping.groupby("underlying_symbol")[
        "trading_date"
    ].shift(1)
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    current = prices.rename(columns={"order_book_id": "held_contract", "close": "current_price"})
    previous = prices.rename(columns={"trading_date": "previous_date", "order_book_id": "held_contract", "close": "previous_price"})
    result = mapping.merge(current, on=["trading_date", "held_contract"], how="left", validate="many_to_one")
    result = result.merge(previous, on=["previous_date", "held_contract"], how="left", validate="many_to_one")
    valid = result["previous_price"].gt(0) & result["current_price"].gt(0)
    result["log_return"] = np.where(
        valid, np.log(result["current_price"] / result["previous_price"]), np.nan
    )
    return result[["trading_date", "underlying_symbol", "held_contract", "log_return"]]


def monthly_return_panel(daily_returns: pd.DataFrame, *, min_coverage: float = 0.8) -> pd.DataFrame:
    """Sum daily log returns only for sufficiently covered product-months."""
    if not 0 < min_coverage <= 1:
        raise ValueError("min_coverage must be in (0, 1]")
    required = {"trading_date", "underlying_symbol", "log_return"}
    if required - set(daily_returns):
        raise ValueError("daily_returns is missing required columns")
    frame = daily_returns.loc[:, list(required)].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    if frame.duplicated(["trading_date", "underlying_symbol"]).any():
        raise ValueError("duplicate product-date in daily_returns")
    frame["month"] = frame["trading_date"].dt.to_period("M")
    grouped = frame.groupby(["underlying_symbol", "month"], observed=True)["log_return"]
    result = grouped.agg(log_return="sum", valid_days="count", observed_days="size").reset_index()
    result["coverage"] = result["valid_days"] / result["observed_days"]
    result.loc[result["coverage"] < min_coverage, "log_return"] = np.nan
    result["year"] = result["month"].dt.year
    result["calendar_month"] = result["month"].dt.month
    return result


def calendar_return_diagnostics(
    monthly: pd.DataFrame, *, min_train_years: int = 5, min_test_years: int = 3
) -> pd.DataFrame:
    """Rank return seasonality using expanding-year, out-of-sample predictions.

    The seasonal prediction for a product-month is the historical mean for
    that calendar month using strictly earlier years. Its comparator is the
    historical unconditional mean; neither sees the test year.
    """
    required = {"underlying_symbol", "year", "calendar_month", "log_return"}
    if required - set(monthly):
        raise ValueError("monthly is missing required columns")
    if min_train_years < 2 or min_test_years < 1:
        raise ValueError("invalid training/test year thresholds")
    frame = monthly.loc[:, list(required)].copy()
    frame = frame.dropna(subset=["log_return"])
    if frame.duplicated(["underlying_symbol", "year", "calendar_month"]).any():
        raise ValueError("duplicate product-year-calendar_month")
    records = []
    for product, group in frame.groupby("underlying_symbol", sort=True):
        years = sorted(group["year"].unique())
        actual, seasonal, baseline = [], [], []
        test_years = set()
        for year in years:
            train = group.loc[group["year"] < year]
            if train["year"].nunique() < min_train_years:
                continue
            means = train.groupby("calendar_month")["log_return"].mean()
            counts = train.groupby("calendar_month")["year"].nunique()
            comparator = float(train["log_return"].mean())
            for row in group.loc[group["year"] == year].itertuples():
                month = int(row.calendar_month)
                if counts.get(month, 0) < min_train_years:
                    continue
                actual.append(float(row.log_return))
                seasonal.append(float(means[month]))
                baseline.append(comparator)
                test_years.add(int(year))
        n = len(actual)
        if n and len(test_years) >= min_test_years:
            mse_seasonal = float(np.mean((np.array(actual) - np.array(seasonal)) ** 2))
            mse_baseline = float(np.mean((np.array(actual) - np.array(baseline)) ** 2))
            oos_r2 = 1 - mse_seasonal / mse_baseline if mse_baseline > 0 else np.nan
        else:
            oos_r2 = np.nan
        records.append({
            "underlying_symbol": product,
            "history_years": len(years),
            "tested_years": len(test_years),
            "tested_months": n,
            "oos_seasonal_r2": oos_r2,
            "evidence": "insufficient_history" if len(test_years) < min_test_years
                else "positive_oos" if np.isfinite(oos_r2) and oos_r2 > 0
                else "not_supported",
        })
    return pd.DataFrame(records)
