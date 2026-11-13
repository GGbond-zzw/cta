"""Rebuild paper-inspired seasonality screens from existing commodity data.

The fourth (spot/futures basis) screen requires an explicit spot CSV. A futures
curve is not silently substituted for a spot series.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def bh(values: pd.Series) -> pd.Series:
    valid = values.dropna().astype(float)
    if valid.empty:
        return pd.Series(np.nan, index=values.index)
    order = valid.sort_values().index
    n = len(order)
    adjusted = np.minimum.accumulate(
        (valid.loc[order].to_numpy() * n / np.arange(1, n + 1))[::-1]
    )[::-1]
    result = pd.Series(np.nan, index=values.index)
    result.loc[order] = np.minimum(adjusted, 1)
    return result


def oos_same_month(frame: pd.DataFrame, value: str, min_years: int = 5) -> tuple[float, int]:
    actual, seasonal, baseline = [], [], []
    years = sorted(frame["year"].unique())
    for year in years:
        train = frame.loc[frame.year < year]
        means = train.groupby("calendar_month")[value].agg(["mean", "count"])
        base = train[value].mean()
        for row in frame.loc[frame.year == year].itertuples():
            m = row.calendar_month
            if m in means.index and means.loc[m, "count"] >= min_years:
                actual.append(getattr(row, value))
                seasonal.append(means.loc[m, "mean"])
                baseline.append(base)
    if not actual:
        return np.nan, 0
    a, s, b = map(np.asarray, (actual, seasonal, baseline))
    denominator = np.mean((a - b) ** 2)
    return (1 - np.mean((a - s) ** 2) / denominator if denominator > 0 else np.nan, len(a))


def monthly_group_test(frame: pd.DataFrame, value: str) -> tuple[float, float]:
    groups = [g[value].dropna().to_numpy() for _, g in frame.groupby("calendar_month")]
    groups = [g for g in groups if len(g) >= 3]
    if len(groups) < 3:
        return np.nan, np.nan
    return float(stats.f_oneway(*groups).pvalue), float(stats.kruskal(*groups).pvalue)


def li_screen(daily: pd.DataFrame, monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    half = daily.dropna(subset=["log_return"]).copy()
    half["trading_date"] = pd.to_datetime(half.trading_date)
    half["month"] = half.trading_date.dt.to_period("M")
    half["half"] = np.where(half.trading_date.dt.day <= 15, 1, 2)
    paired = half.groupby(["underlying_symbol", "month", "half"])["log_return"].sum().unstack()
    paired = paired.dropna(subset=[1, 2]).reset_index()
    eligible = monthly.dropna(subset=["log_return"])[["underlying_symbol", "month"]].drop_duplicates().copy()
    eligible["month"] = pd.PeriodIndex(eligible["month"], freq="M")
    paired = paired.merge(eligible, on=["underlying_symbol", "month"], how="inner")
    rows = []
    for symbol, group in monthly.dropna(subset=["log_return"]).groupby("underlying_symbol"):
        p_anova, p_kw = monthly_group_test(group, "log_return")
        oos, tested = oos_same_month(group, "log_return")
        halves = paired.loc[paired.underlying_symbol == symbol]
        diff = (halves[1] - halves[2]).to_numpy()
        half_p = float(stats.ttest_1samp(diff, 0).pvalue) if len(diff) >= 5 else np.nan
        rows.append({"underlying_symbol": symbol, "monthly_anova_p": p_anova,
                     "monthly_kruskal_p": p_kw, "half_month_mean_diff": np.mean(diff) if len(diff) else np.nan,
                     "half_month_p": half_p, "same_month_oos_r2": oos, "tested_months": tested})
    summary = pd.DataFrame(rows)
    for name in ("monthly_anova_p", "monthly_kruskal_p", "half_month_p"):
        summary[name.replace("_p", "_q")] = bh(summary[name])
    return summary, paired


def hac_dummy(y: np.ndarray, indicator: np.ndarray, lag: int = 3) -> tuple[float, float]:
    x = np.column_stack((np.ones(len(y)), indicator))
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y - x @ beta
    bread = np.linalg.inv(x.T @ x)
    scores = x * residual[:, None]
    meat = scores.T @ scores
    for k in range(1, min(lag, len(y) - 1) + 1):
        cross = scores[k:].T @ scores[:-k]
        meat += (1 - k / (lag + 1)) * (cross + cross.T)
    se = np.sqrt(max((bread @ meat @ bread)[1, 1], 0))
    p = float(2 * stats.norm.sf(abs(beta[1] / se))) if se > 0 else np.nan
    return float(beta[1]), p


def ssa_forecast(y: np.ndarray, rank: int = 12, embedding: int = 36) -> float:
    n = len(y)
    if n < embedding + 2:
        return np.nan
    matrix = np.column_stack([y[k:k + embedding] for k in range(n - embedding + 1)])
    u, singular, vh = np.linalg.svd(matrix, full_matrices=False)
    rank = min(rank, len(singular) - 1)
    reconstructed = (u[:, :rank] * singular[:rank]) @ vh[:rank]
    series = np.bincount(np.add.outer(np.arange(embedding), np.arange(matrix.shape[1])).ravel(),
                         weights=reconstructed.ravel()) / np.bincount(
                             np.add.outer(np.arange(embedding), np.arange(matrix.shape[1])).ravel())
    vectors = u[:, :rank]
    pi = vectors[-1]
    denominator = 1 - pi @ pi
    if denominator <= 1e-8:
        return np.nan
    recurrence = (vectors[:-1] @ pi) / denominator
    return float(recurrence @ series[-embedding + 1:])


def kosch_screen(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    coefficient_rows, forecast_rows = [], []
    for symbol, group in monthly.dropna(subset=["log_return"]).groupby("underlying_symbol"):
        group = group.sort_values("month")
        y = group.log_return.to_numpy(dtype=float)
        months = group.calendar_month.to_numpy(dtype=int)
        for m in range(1, 13):
            if np.count_nonzero(months == m) >= 5 and np.count_nonzero(months != m) >= 20:
                beta, p = hac_dummy(y, (months == m).astype(float))
                coefficient_rows.append({"underlying_symbol": symbol, "calendar_month": m,
                                         "month_excess_return": beta, "hac_p": p})
        # The published rolling window requires 120 consecutive monthly observations.
        indexed = group.set_index(pd.PeriodIndex(group.month, freq="M"))["log_return"]
        complete = indexed.reindex(pd.period_range(indexed.index.min(), indexed.index.max(), freq="M"))
        for position in range(120, len(complete)):
            train = complete.iloc[position - 120:position].to_numpy(dtype=float)
            actual = complete.iloc[position]
            if not np.isfinite(actual) or not np.isfinite(train).all():
                continue
            prediction = ssa_forecast(train)
            if np.isfinite(prediction):
                forecast_rows.append({"underlying_symbol": symbol, "month": str(complete.index[position]),
                                      "actual": actual, "ssa_forecast": prediction,
                                      "baseline_forecast": float(train.mean())})
    coefficients = pd.DataFrame(coefficient_rows)
    coefficients["hac_q"] = bh(coefficients.hac_p)
    forecasts = pd.DataFrame(forecast_rows)
    return coefficients, forecasts


def maitra_screen(volatility: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol, group in volatility.dropna(subset=["log_daily_rms_volatility"]).groupby("underlying_symbol"):
        group = group.sort_values("month")
        p_anova, p_kw = monthly_group_test(group, "log_daily_rms_volatility")
        oos, tested = oos_same_month(group, "log_daily_rms_volatility")
        rows.append({"underlying_symbol": symbol, "month_effect_anova_p": p_anova,
                     "month_effect_kruskal_p": p_kw, "same_month_oos_r2": oos,
                     "tested_months": tested,
                     "model_scope": "monthly volatility group test; no GARCH or structural-break terms"})
    result = pd.DataFrame(rows)
    result["month_effect_anova_q"] = bh(result.month_effect_anova_p)
    return result


def brooks_basis_screen(spot_csv: Path | None, snapshot_dir: Path, output: Path,
                        date_col: str, symbol_col: str, price_col: str) -> dict:
    if spot_csv is None:
        return {"status": "not_run", "reason": (
            "checked local RQAlpha bundles contain futures but no all-commodity spot series; "
            "RQData Spot documentation covers SGEX precious metals only; "
            "futures curve is not spot-futures basis"
        )}
    spot = pd.read_csv(spot_csv)
    required = {date_col, symbol_col, price_col}
    if missing := required - set(spot):
        raise ValueError(f"spot CSV missing {sorted(missing)}")
    spot = spot.rename(columns={date_col: "trading_date", symbol_col: "underlying_symbol",
                                price_col: "spot_price"})
    spot["trading_date"] = pd.to_datetime(spot.trading_date).dt.normalize()
    spot["underlying_symbol"] = spot.underlying_symbol.astype(str).str.upper()
    spot["spot_price"] = pd.to_numeric(spot.spot_price, errors="coerce")
    spot = spot.loc[spot.spot_price.gt(0)].copy()
    if spot.duplicated(["trading_date", "underlying_symbol"]).any():
        raise ValueError("duplicate spot date/product; provide one comparable spot price per product-day")
    if spot.empty:
        raise ValueError("spot CSV has no valid positive prices")
    futures = []
    for file in sorted(snapshot_dir.glob("snapshots_*.parquet")):
        part = pd.read_parquet(file, columns=["trading_date", "underlying_symbol", "order_book_id",
                                              "days_to_maturity", "price", "price_field", "volume", "open_interest"])
        part["trading_date"] = pd.to_datetime(part.trading_date).dt.normalize()
        part["underlying_symbol"] = part.underlying_symbol.astype(str).str.upper()
        part = part.merge(spot[["trading_date", "underlying_symbol", "spot_price"]],
                          on=["trading_date", "underlying_symbol"], how="inner")
        if part.empty:
            continue
        part = part.loc[part.price_field.eq("close") & part.price.gt(0)
                        & part.volume.gt(0) & part.open_interest.gt(0)].copy()
        for tenor, target, tolerance in ((6, 183, 90), (12, 365, 120)):
            candidates = part.loc[(part.days_to_maturity - target).abs().le(tolerance)].copy()
            candidates["tenor_months"] = tenor
            candidates["tenor_gap_days"] = (candidates.days_to_maturity - target).abs()
            candidates = candidates.sort_values(["trading_date", "underlying_symbol",
                                                  "tenor_gap_days", "open_interest"],
                                                 ascending=[True, True, True, False])
            candidates = candidates.drop_duplicates(["trading_date", "underlying_symbol"])
            futures.append(candidates)
    if not futures:
        return {"status": "not_run", "reason": "no matched spot/futures trading dates with 6m or 12m contracts"}
    spot = pd.concat(futures, ignore_index=True)
    spot["month"] = spot.trading_date.dt.to_period("M")
    spot = spot.sort_values("trading_date").drop_duplicates(
        ["underlying_symbol", "month", "tenor_months"], keep="last")
    spot["calendar_month"] = spot.month.dt.month
    spot["year"] = spot.month.dt.year
    spot["log_basis"] = np.log(spot.price / spot.spot_price)
    spot[["underlying_symbol", "trading_date", "order_book_id", "spot_price", "price",
          "tenor_months", "days_to_maturity", "log_basis"]].to_csv(
              output / "brooks_matched_basis.csv", index=False, encoding="utf-8-sig")
    rows = []
    for (symbol, tenor), group in spot.groupby(["underlying_symbol", "tenor_months"]):
        p_anova, p_kw = monthly_group_test(group, "log_basis")
        oos, tested = oos_same_month(group, "log_basis")
        rows.append({"underlying_symbol": symbol, "tenor_months": tenor,
                     "month_effect_anova_p": p_anova, "month_effect_kruskal_p": p_kw,
                     "same_month_oos_r2": oos, "tested_months": tested})
    result = pd.DataFrame(rows)
    if not result.empty:
        result["month_effect_anova_q"] = bh(result.month_effect_anova_p)
    result.to_csv(output / "brooks_basis_by_product.csv", index=False, encoding="utf-8-sig")
    return {"status": "computed", "source": str(spot_csv), "rows": len(result),
            "matched_months": len(spot), "caution": "spot and futures units must match; 6m/12m are nearest-contract approximations"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("results/commodity_seasonality_2010_2026"))
    parser.add_argument("--spot-csv", type=Path)
    parser.add_argument("--snapshot-dir", type=Path, default=Path("results/all_commodity_curves"))
    parser.add_argument("--spot-date-col", default="trading_date")
    parser.add_argument("--spot-symbol-col", default="underlying_symbol")
    parser.add_argument("--spot-price-col", default="spot_price")
    args = parser.parse_args()
    output = args.input_dir / "paper_methods"
    output.mkdir(parents=True, exist_ok=True)
    daily = pd.read_csv(args.input_dir / "daily_returns.csv")
    monthly = pd.read_csv(args.input_dir / "monthly_returns.csv")
    volatility = pd.read_csv(args.input_dir / "volatility_seasonality/monthly_volatility.csv")
    li, half = li_screen(daily, monthly)
    kosch, forecasts = kosch_screen(monthly)
    maitra = maitra_screen(volatility)
    for name, frame in (("li_by_product.csv", li), ("li_half_month_panel.csv", half),
                        ("kosch_month_coefficients.csv", kosch), ("kosch_ssa_forecasts.csv", forecasts),
                        ("maitra_by_product.csv", maitra)):
        frame.to_csv(output / name, index=False, encoding="utf-8-sig")
    # Replace the old derived screens in their established locations. Raw return
    # and monthly-volatility inputs remain as the source for repeatable runs.
    li.to_csv(args.input_dir / "return_diagnostics.csv", index=False, encoding="utf-8-sig")
    old_robustness = args.input_dir / "robustness"
    old_robustness.mkdir(exist_ok=True)
    kosch.to_csv(old_robustness / "robustness_by_product.csv", index=False, encoding="utf-8-sig")
    forecasts.to_csv(old_robustness / "robustness_by_year.csv", index=False, encoding="utf-8-sig")
    (old_robustness / "metadata.json").write_text(json.dumps({
        "replaced_by": "Kosch and Forsberg month regression and SSA screen",
        "product_file_granularity": "one row per product and calendar month",
        "year_file_granularity": "one row per product and forecast month",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    old_volatility = args.input_dir / "volatility_seasonality"
    maitra.to_csv(old_volatility / "volatility_by_product.csv", index=False, encoding="utf-8-sig")
    year_volatility = volatility.groupby(["underlying_symbol", "year"], as_index=False)[
        "log_daily_rms_volatility"].mean()
    year_volatility.to_csv(old_volatility / "volatility_by_year.csv", index=False, encoding="utf-8-sig")
    (old_volatility / "metadata.json").write_text(json.dumps({
        "replaced_by": "Maitra-inspired monthly volatility group screen",
        "limitations": "GARCH, EGARCH and structural-break terms not implemented",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    basis = brooks_basis_screen(args.spot_csv, args.snapshot_dir, output,
                                args.spot_date_col, args.spot_symbol_col, args.spot_price_col)
    metadata = {"source": str(args.input_dir), "papers": ["Li et al. 2024", "Kosch and Forsberg 2026",
                "Maitra 2018", "Brooks et al. 2013"], "method_notes": {
                    "li": "half-month paired returns, monthly ANOVA/Kruskal, expanding same-month OOS",
                    "kosch": "HAC month dummy and rank-12 SSA with 120-month rolling windows; RLSSA not implemented",
                    "maitra": "monthly volatility group test; GARCH/EGARCH and break terms not implemented",
                    "brooks": basis}, "data_caveat": "existing monthly returns exclude boundary months and use prior-day dominant contracts"}
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(li)} return and {len(maitra)} volatility product rows to {output}")
    print(f"Brooks basis: {basis['status']}")


if __name__ == "__main__":
    main()
