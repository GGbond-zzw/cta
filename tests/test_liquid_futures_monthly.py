import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "15_select_liquid_universe.py"
sys.path.insert(0, str(SCRIPTS))
if not SCRIPT.exists():  # pragma: no cover - the script is part of the repo
    pytest.skip(f"{SCRIPT.name} is missing", allow_module_level=True)
SPEC = importlib.util.spec_from_file_location("select_liquid_universe", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_previous_month_must_be_complete():
    start, end = MODULE.month_dates("2025-02", today=date(2025, 2, 1))
    assert str(start.date()) == "2025-01-01"
    assert str(end.date()) == "2025-01-31"
    with pytest.raises(ValueError, match="not fully closed"):
        MODULE.month_dates("2025-02", today=date(2025, 1, 31))


def test_every_day_top_sixty_percent_and_no_future_window(monkeypatch):
    calendar = [f"2025-01-{day:02d}" for day in range(1, 6)]
    prior_days = calendar[-2:]
    symbols = ["AA", "BB", "CC", "DD", "EE"]
    master = pd.DataFrame([
        (symbol + "2501", symbol, "DCE", "Commodity", 10,
         "2024-01-01", "2026-01-31") for symbol in symbols
    ], columns=["order_book_id", "underlying_symbol", "exchange", "product",
                "contract_multiplier", "listed_date", "de_listed_date"])
    bars = pd.DataFrame([
        (day, symbol + "2501", 100, 200, 10)
        for day in calendar for symbol in symbols
    ], columns=["trading_date", "order_book_id", "volume", "open_interest", "settlement"])
    observed_windows = []

    def fake_screen(_master, _bars, dates, _config):
        observed_windows.append((dates[-1], dates[:], sorted(_bars.trading_date.unique())))
        order = symbols if dates[-1] == prior_days[0] else ["AA", "BB", "DD", "CC", "EE"]
        return pd.DataFrame({
            "underlying_symbol": order, "rank": [1, 2, 3, 4, 5],
            "score": [1.0, 0.8, 0.6, 0.4, 0.2],
            "exclusion_reason": [""] * 5,
        })

    monkeypatch.setattr(MODULE, "screen_products", fake_screen)
    daily = MODULE.evaluate_daily_ranks(
        master, bars, calendar, prior_days,
        MODULE.ScreenConfig(window=3, top=2), top_share=0.6)
    assert (daily["top60_cutoff_rank"] == 3).all()
    assert observed_windows == [
        ("2025-01-04", calendar[1:4], calendar[1:4]),
        ("2025-01-05", calendar[2:5], calendar[2:5]),
    ]
    summary = MODULE.select_monthly(daily, prior_days, top=2)
    assert summary.loc[summary["selected"], "underlying_symbol"].tolist() == ["AA", "BB"]
    assert not summary.loc[summary["underlying_symbol"].eq("CC"), "all_days_top60"].iloc[0]
    assert not summary.loc[summary["underlying_symbol"].eq("DD"), "all_days_top60"].iloc[0]
    assert int(summary["all_days_top60"].sum()) == 2

    # A missing settlement on the evaluation day cannot borrow yesterday's score.
    damaged = bars.copy()
    damaged.loc[(damaged["trading_date"] == prior_days[-1])
                & (damaged["order_book_id"] == "BB2501"), "settlement"] = float("nan")
    daily_damaged = MODULE.evaluate_daily_ranks(
        master, damaged, calendar, prior_days,
        MODULE.ScreenConfig(window=3, top=2), top_share=0.6)
    row = daily_damaged.loc[(daily_damaged["trading_date"] == prior_days[-1])
                            & (daily_damaged["underlying_symbol"] == "BB")].iloc[0]
    assert not row["qualified"]
    assert "incomplete_current_day" in row["exclusion_reason"]


def test_missing_prior_month_day_rejected():
    daily = pd.DataFrame([
        {"trading_date": "2025-01-04", "underlying_symbol": "AA",
         "qualified": True, "score": 1.0, "rank": 1}
    ])
    with pytest.raises(ValueError, match="trading date is missing"):
        MODULE.select_monthly(daily, ["2025-01-04", "2025-01-05"], top=1)
