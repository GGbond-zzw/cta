"""Select a fixed monthly commodity pool from prior-month daily top-60% ranks.

For each trading day of the preceding calendar month, the v2 liquidity score
uses that day and the preceding 59 trading days only. A product must qualify
on every prior-month trading day before it can compete for the monthly top 30.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig
from china_cta.data.liquidity_screen import REAL_CONTRACT, ScreenConfig, screen_products


def month_dates(month: str, today: date | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return bounds of the *completed* calendar month preceding target month."""
    try:
        target = pd.Period(month, freq="M")
    except ValueError as exc:
        raise ValueError("--month must be YYYY-MM") from exc
    if str(target) != month:
        raise ValueError("--month must be YYYY-MM")
    prior = target - 1
    start, end = prior.start_time.normalize(), prior.end_time.normalize()
    if end.date() >= (today or date.today()):
        raise ValueError(f"Previous month {prior} has not fully closed yet")
    return start, end


def load_live_history(month: str, window: int):
    prior_start, prior_end = month_dates(month)
    adapter = RQDataAdapter(replace(RQDataConfig.from_environment(), cache_dir=None))
    calendar = adapter.get_trading_calendar(
        (prior_start - pd.Timedelta(days=window * 4)).date(), prior_end.date())
    calendar = [day.date().isoformat() for day in calendar]
    prior_days = [day for day in calendar if prior_start <= pd.Timestamp(day) <= prior_end]
    if not prior_days:
        raise RuntimeError(f"No trading days in preceding month {prior_start:%Y-%m}")
    first_position = calendar.index(prior_days[0])
    if first_position < window - 1:
        raise RuntimeError(f"Need {window - 1} trading days before {prior_days[0]}")
    history_start = calendar[first_position - window + 1]
    master = adapter.get_future_instruments()
    master = master.loc[
        master["product"].eq("Commodity")
        & master["order_book_id"].astype(str).str.fullmatch(REAL_CONTRACT.pattern)
        & (pd.to_datetime(master["listed_date"], errors="coerce") <= prior_end)
        & (pd.to_datetime(master["de_listed_date"], errors="coerce") >= pd.Timestamp(history_start))
    ].copy()
    ids = master["order_book_id"].astype(str).tolist()
    frames = []
    for offset in range(0, len(ids), 50):
        frames.append(adapter.get_bars(
            ids[offset:offset + 50], history_start, prior_days[-1],
            fields=("settlement", "volume", "open_interest")))
    if not frames:
        raise RuntimeError("No commodity contract bars returned")
    return master, pd.concat(frames, ignore_index=True), calendar, prior_days


def evaluate_daily_ranks(master: pd.DataFrame, bars: pd.DataFrame,
                         calendar: list[str], prior_days: list[str],
                         config: ScreenConfig, top_share: float = 0.6) -> pd.DataFrame:
    """Score independently each day and compare with that day's whole commodity universe."""
    if not 0 < top_share <= 1:
        raise ValueError("top_share must be in (0, 1]")
    calendar = sorted(dict.fromkeys(calendar))
    prior_days = sorted(dict.fromkeys(prior_days))
    if not set(prior_days) <= set(calendar):
        raise ValueError("prior_days must be trading dates in calendar")
    bars = bars.copy()
    bars["trading_date"] = bars["trading_date"].astype(str).str[:10]
    master = master.loc[master["product"].eq("Commodity")
                        & master["order_book_id"].astype(str).str.fullmatch(REAL_CONTRACT.pattern)].copy()
    listed = pd.to_datetime(master["listed_date"], errors="coerce")
    delisted = pd.to_datetime(master["de_listed_date"], errors="coerce")
    records = []
    for day in prior_days:
        position = calendar.index(day)
        if position < config.window - 1:
            raise ValueError(f"Insufficient lookback before {day}")
        window_dates = calendar[position - config.window + 1:position + 1]
        active_master = master.loc[(listed <= pd.Timestamp(day)) & (delisted >= pd.Timestamp(day))]
        candidates = sorted(active_master["underlying_symbol"].dropna().astype(str).unique())
        cutoff = max(1, math.floor(top_share * len(candidates)))
        if len(candidates) < config.top:
            raise RuntimeError(f"Only {len(candidates)} active commodity products on {day}")
        current_bars = bars.loc[bars["trading_date"].eq(day)
                                & bars["order_book_id"].isin(active_master["order_book_id"])]
        observed = current_bars["order_book_id"].map(
            active_master.set_index("order_book_id")["underlying_symbol"]
        ).nunique()
        if observed < math.ceil(0.9 * len(candidates)):
            raise RuntimeError(f"Market bars incomplete on {day}: {observed}/{len(candidates)} products")
        current = current_bars.merge(
            active_master[["order_book_id", "underlying_symbol", "contract_multiplier"]],
            on="order_book_id", how="left", validate="many_to_one")
        for field in ("volume", "open_interest", "settlement", "contract_multiplier"):
            current[field] = pd.to_numeric(current[field], errors="coerce")
        priced = (current["settlement"] > 0) & (current["contract_multiplier"] > 0)
        current["covered_volume"] = current["volume"].where(priced, 0)
        current["covered_oi"] = current["open_interest"].where(priced, 0)
        coverage = current.groupby("underlying_symbol").agg(
            volume=("volume", "sum"), oi=("open_interest", "sum"),
            covered_volume=("covered_volume", "sum"), covered_oi=("covered_oi", "sum"))
        valid_today = set(coverage.loc[
            (coverage["covered_volume"] >= 0.95 * coverage["volume"])
            & (coverage["covered_oi"] >= 0.95 * coverage["oi"])
            & (coverage["covered_volume"] > 0)].index)
        window_bars = bars.loc[bars["trading_date"].isin(window_dates)]
        score_master = master.loc[master["underlying_symbol"].isin(candidates)]
        scores = screen_products(score_master, window_bars, window_dates, config)
        by_symbol = scores.set_index("underlying_symbol")
        for symbol in candidates:
            row = by_symbol.loc[symbol] if symbol in by_symbol.index else None
            rank = row["rank"] if row is not None else pd.NA
            reason = str(row["exclusion_reason"]) if row is not None else "no_window_bars"
            if symbol not in valid_today:
                reason = ";".join(filter(None, [reason, "incomplete_current_day"]))
            qualified = bool(reason == "" and pd.notna(rank) and rank <= cutoff)
            records.append({
                "trading_date": day, "underlying_symbol": symbol,
                "candidate_count": len(candidates), "top60_cutoff_rank": cutoff,
                "rank": rank, "score": float(row["score"]) if row is not None and pd.notna(row["score"]) else float("nan"),
                "qualified": qualified, "exclusion_reason": reason,
            })
    return pd.DataFrame(records)


def select_monthly(daily_ranks: pd.DataFrame, prior_days: list[str],
                   top: int = 30) -> pd.DataFrame:
    """Require top-60% qualification on every prior-month date; rank median score."""
    if top < 1:
        raise ValueError("top must be positive")
    month_days = sorted(set(prior_days))
    daily_ranks = daily_ranks.loc[daily_ranks["trading_date"].isin(month_days)].copy()
    if daily_ranks.duplicated(["trading_date", "underlying_symbol"]).any():
        raise ValueError("Duplicate product-day scores")
    if set(daily_ranks["trading_date"]) != set(month_days):
        raise ValueError("A prior-month trading date is missing")
    summary = daily_ranks.groupby("underlying_symbol", as_index=False).agg(
        observed_days=("trading_date", "nunique"),
        qualified_days=("qualified", "sum"),
        median_score=("score", "median"),
        worst_daily_rank=("rank", "max"),
    )
    summary["all_days_top60"] = (
        (summary["observed_days"] == len(month_days))
        & (summary["qualified_days"] == len(month_days))
    )
    summary = summary.sort_values(
        ["all_days_top60", "median_score", "underlying_symbol"],
        ascending=[False, False, True], na_position="last").reset_index(drop=True)
    eligible = summary["all_days_top60"]
    summary["monthly_rank"] = pd.array(
        [int(eligible.iloc[:i + 1].sum()) if eligible.iloc[i] else pd.NA
         for i in range(len(summary))], dtype="Int64")
    summary["selected"] = eligible & summary["monthly_rank"].le(top).fillna(False)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="Target holding month, YYYY-MM")
    parser.add_argument("--window", type=int, default=60,
                        help="Past trading days used for each daily liquidity score")
    parser.add_argument("--top-share", type=float, default=0.6)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--order-notional-cny", type=float)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.window < 5 or args.top < 1 or not 0 < args.top_share <= 1:
        parser.error("window >= 5, top >= 1, and top-share in (0, 1] are required")
    if args.order_notional_cny is not None and args.order_notional_cny <= 0:
        parser.error("order-notional-cny must be positive")
    month_dates(args.month)
    config = ScreenConfig(window=args.window, top=args.top,
                          order_notional_cny=args.order_notional_cny)
    master, bars, calendar, prior_days = load_live_history(args.month, args.window)
    daily = evaluate_daily_ranks(master, bars, calendar, prior_days, config, args.top_share)
    summary = select_monthly(daily, prior_days, args.top)
    output_dir = args.output_dir or Path("results") / f"liquidity_monthly_{args.month}"
    output_dir.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output_dir / "daily_ranks.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "monthly_diagnostics.csv", index=False, encoding="utf-8-sig")
    candidates = summary["all_days_top60"]
    if candidates.sum() < args.top:
        raise RuntimeError(
            f"Only {candidates.sum()} products were in the top {args.top_share:.0%} "
            f"on every day of {prior_days[0][:7]}; need {args.top}. "
            f"Diagnostics saved to {output_dir}; no selection generated.")
    chosen = summary.loc[summary["selected"], "underlying_symbol"].tolist()
    payload = {
        "holding_month": args.month,
        "ranking_month": prior_days[0][:7],
        "ranking_first_day": prior_days[0],
        "ranking_last_day": prior_days[-1],
        "ranking_trading_days": len(prior_days),
        "daily_lookback_days": args.window,
        "daily_top_share": args.top_share,
        "monthly_ordering": "median of daily v2 liquidity scores",
        "order_notional_cny": args.order_notional_cny,
        "products": chosen,
    }
    (output_dir / "selected_products.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Holding month {args.month}; ranking month {prior_days[0][:7]} "
          f"({len(prior_days)} trading days); persistent candidates {candidates.sum()}; selected {len(chosen)}")
    print(summary.loc[summary["selected"], ["monthly_rank", "underlying_symbol",
                                                     "median_score", "worst_daily_rank"]].to_string(index=False))
    print(f"Saved to {output_dir}")


if __name__ == "__main__":
    main()
