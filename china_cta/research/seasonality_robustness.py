"""Robustness checks for the preliminary calendar-month return screen."""

from __future__ import annotations

import numpy as np
import pandas as pd


def monthly_volatility_panel(
    daily_returns: pd.DataFrame, *, min_coverage: float = 0.8,
    min_valid_days: int = 10,
) -> pd.DataFrame:
    """Monthly log daily-RMS volatility, with explicit coverage gates.

    Daily RMS rather than monthly realized volatility avoids mechanical
    differences caused by the number of trading days in a calendar month.
    """
    required = {"trading_date", "underlying_symbol", "log_return"}
    if required - set(daily_returns):
        raise ValueError("daily_returns is missing required columns")
    if not 0 < min_coverage <= 1 or min_valid_days < 2:
        raise ValueError("invalid coverage or minimum valid days")
    frame = daily_returns.loc[:, list(required)].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame["log_return"] = pd.to_numeric(frame["log_return"], errors="coerce")
    if frame.duplicated(["trading_date", "underlying_symbol"]).any():
        raise ValueError("duplicate product-date in daily_returns")
    frame["month"] = frame["trading_date"].dt.to_period("M")
    frame["squared_return"] = frame["log_return"] ** 2
    grouped = frame.groupby(["underlying_symbol", "month"], observed=True)
    result = grouped.agg(
        mean_squared_return=("squared_return", "mean"),
        valid_days=("log_return", "count"),
        observed_days=("log_return", "size"),
    ).reset_index()
    result["coverage"] = result["valid_days"] / result["observed_days"]
    positive_variance = result["mean_squared_return"].where(
        result["mean_squared_return"].gt(0)
    )
    result["log_daily_rms_volatility"] = 0.5 * np.log(positive_variance)
    invalid = (
        result["coverage"].lt(min_coverage)
        | result["valid_days"].lt(min_valid_days)
        | ~np.isfinite(result["log_daily_rms_volatility"])
    )
    result.loc[invalid, "log_daily_rms_volatility"] = np.nan
    result["year"] = result["month"].dt.year
    result["calendar_month"] = result["month"].dt.month
    return result


def _prediction_errors(matrix: np.ndarray, min_train_years: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return test-year indices and squared errors for month/baseline forecasts."""
    present = np.isfinite(matrix)
    values = np.where(present, matrix, 0.0)
    prior_month_sum = np.cumsum(values, axis=0) - values
    prior_month_count = np.cumsum(present, axis=0) - present
    prior_total_sum = prior_month_sum.sum(axis=1)
    prior_total_count = prior_month_count.sum(axis=1)
    eligible = present & (prior_month_count >= min_train_years)
    seasonal = np.divide(
        prior_month_sum, prior_month_count,
        out=np.zeros_like(values), where=prior_month_count > 0,
    )
    baseline = np.divide(
        prior_total_sum, prior_total_count,
        out=np.zeros(len(matrix)), where=prior_total_count > 0,
    )[:, None]
    seasonal_se = np.where(eligible, (values - seasonal) ** 2, 0.0)
    baseline_se = np.where(eligible, (values - baseline) ** 2, 0.0)
    return eligible, seasonal_se, baseline_se


def _null_shuffle_within_year(matrix: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    shuffled = matrix.copy()
    for row in shuffled:
        locations = np.flatnonzero(np.isfinite(row))
        row[locations] = rng.permutation(row[locations])
    return shuffled


def _bh_qvalues(pvalues: np.ndarray) -> np.ndarray:
    order = np.argsort(pvalues)
    ranks = np.arange(1, len(pvalues) + 1)
    sorted_q = np.minimum.accumulate(
        (pvalues[order] * len(pvalues) / ranks)[::-1]
    )[::-1]
    qvalues = np.empty(len(pvalues))
    qvalues[order] = np.minimum(sorted_q, 1.0)
    return qvalues


def calendar_return_robustness(
    monthly: pd.DataFrame, *, min_train_years: int = 5,
    min_test_years: int = 3, permutations: int = 2000, seed: int = 20260930,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Year-level OOS errors plus within-year month-label permutation/FDR check.

    Null shuffling preserves each year's distribution and missing month slots,
    but destroys the association between returns and calendar-month labels.
    This is a diagnostic, not proof of tradable or physical seasonality.
    """
    required = {"underlying_symbol", "year", "calendar_month", "log_return"}
    if required - set(monthly):
        raise ValueError("monthly is missing required columns")
    if min_train_years < 2 or min_test_years < 1 or permutations < 1:
        raise ValueError("invalid training/test/permutation settings")
    frame = monthly.loc[:, list(required)].copy()
    frame["log_return"] = pd.to_numeric(frame["log_return"], errors="coerce")
    frame = frame.dropna(subset=["log_return"])
    if frame.duplicated(["underlying_symbol", "year", "calendar_month"]).any():
        raise ValueError("duplicate product-year-calendar_month")
    if not frame["calendar_month"].between(1, 12).all():
        raise ValueError("calendar_month must be 1..12")
    rng = np.random.default_rng(seed)
    summaries, year_rows = [], []
    for product, group in frame.groupby("underlying_symbol", sort=True):
        years = np.arange(int(group["year"].min()), int(group["year"].max()) + 1)
        matrix = np.full((len(years), 12), np.nan)
        for row in group.itertuples():
            matrix[int(row.year) - years[0], int(row.calendar_month) - 1] = float(row.log_return)
        eligible, seasonal_se, baseline_se = _prediction_errors(matrix, min_train_years)
        active_years = int(np.count_nonzero(eligible.any(axis=1)))
        baseline_total = float(baseline_se.sum())
        seasonal_total = float(seasonal_se.sum())
        oos_r2 = 1 - seasonal_total / baseline_total if active_years >= min_test_years and baseline_total > 0 else np.nan
        gain = baseline_total - seasonal_total
        positive_years = 0
        for i, year in enumerate(years):
            if not eligible[i].any():
                continue
            year_gain = float(baseline_se[i].sum() - seasonal_se[i].sum())
            positive_years += year_gain > 0
            year_rows.append({
                "underlying_symbol": product, "year": year,
                "tested_months": int(eligible[i].sum()),
                "baseline_squared_error": float(baseline_se[i].sum()),
                "seasonal_squared_error": float(seasonal_se[i].sum()),
                "squared_error_gain": year_gain,
            })
        pvalue = np.nan
        if np.isfinite(oos_r2):
            exceedances = 0
            for _ in range(permutations):
                null = _null_shuffle_within_year(matrix, rng)
                _, null_seasonal, null_baseline = _prediction_errors(null, min_train_years)
                exceedances += (null_baseline.sum() - null_seasonal.sum()) >= gain
            pvalue = (exceedances + 1) / (permutations + 1)
        summaries.append({
            "underlying_symbol": product, "tested_years": active_years,
            "tested_months": int(eligible.sum()),
            "oos_seasonal_r2": oos_r2,
            "positive_gain_years": positive_years,
            "permutation_p": pvalue,
        })
    summary = pd.DataFrame(summaries)
    summary["fdr_q"] = np.nan
    valid = summary["permutation_p"].notna()
    if valid.any():
        summary.loc[valid, "fdr_q"] = _bh_qvalues(summary.loc[valid, "permutation_p"].to_numpy())
    summary["robust_evidence"] = np.where(
        summary["fdr_q"].lt(0.05) & summary["oos_seasonal_r2"].gt(0)
        & (summary["positive_gain_years"] >= np.ceil(summary["tested_years"] / 2)),
        "passes_diagnostics", "not_established",
    )
    return summary.sort_values("oos_seasonal_r2", ascending=False, na_position="last"), pd.DataFrame(year_rows)
