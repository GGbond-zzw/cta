"""Catalog-level tests for the eleven-package CTA factor registry."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from china_cta.factors.cta_catalog import (
    AVAILABLE_FACTORS,
    FACTOR_SPECS,
    UNAVAILABLE_FACTORS,
    build_all,
    spec_table,
)
from china_cta.factors.schema import FACTOR_COLUMNS

ELEVEN = (
    "fixed_maturity_carry_90_180d",
    "historical_skewness_252d",
    "oi_participation_trend_60d",
    "xsmom_252_21",
    "our_close_carry_smooth5",
    "our_reg35_transformer",
    "crowded_trend_reversal_60d",
    "volume_burst_vol_reversal_60d",
    "turnover_surprise_channel_ratio",
    "inverse_oi_turnover_surprise_ratio",
    "volume_variability_weighted_reversal",
)


def research_prices(periods: int = 320) -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-03", periods=periods)
    rows = []
    for instrument, base in (("RB", 4_000.0), ("CU", 60_000.0)):
        for index, date in enumerate(dates):
            close = base * (1.0 + 0.0005 * index + 0.02 * math.sin(index / 9.0))
            turnover = close * (10_000.0 + index)
            rows.append(
                {
                    "trading_date": date,
                    "underlying_symbol": instrument,
                    "close": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "volume": 10_000.0 + index,
                    "open_interest": 20_000.0 + index,
                    "total_turnover": turnover,
                }
            )
    panel = pd.DataFrame(rows)
    panel.attrs.update(
        {
            "usage": "signal_research_only",
            "cash_pnl_allowed": False,
            "adjust_type": "pre",
            "adjust_method": "prev_close_ratio",
        }
    )
    return panel


def universe_for(prices: pd.DataFrame) -> pd.DataFrame:
    return (
        prices.loc[:, ["trading_date", "underlying_symbol"]]
        .rename(columns={"underlying_symbol": "instrument"})
        .drop_duplicates()
        .assign(eligible=True)
        .reset_index(drop=True)
    )


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


def test_catalog_contains_eleven_unique_specs_with_expected_availability() -> None:
    assert len(FACTOR_SPECS) == 11
    names = [spec.name for spec in FACTOR_SPECS]
    assert tuple(names) == ELEVEN
    assert set(AVAILABLE_FACTORS) | set(UNAVAILABLE_FACTORS) == set(names)
    assert set(UNAVAILABLE_FACTORS) == {"our_reg35_transformer"}
    assert len(AVAILABLE_FACTORS) == 10
    for spec in FACTOR_SPECS:
        assert spec.signal_scale > 0
        if not spec.available:
            assert spec.reason
    table = spec_table()
    assert len(table) == 11
    assert table["factor_name"].is_unique
    assert table["available"].sum() == 10


def test_build_all_returns_every_available_factor_on_synthetic_panel() -> None:
    # 520 sessions so the tuned 441-day skewness lookback still produces values.
    panel = research_prices(periods=520)
    dates = pd.DatetimeIndex(sorted(panel["trading_date"].unique()))
    universe = universe_for(panel)
    rows = []
    mapping_rows = []
    for instrument, base in (("RB", 4_000.0), ("CU", 60_000.0)):
        for index, date in enumerate(dates):
            close = base * (1.0 + 0.0005 * index + 0.02 * math.sin(index / 9.0))
            contracts = [
                f"{instrument}2409",
                f"{instrument}2412",
                f"{instrument}2503",
            ]
            for offset, contract in enumerate(contracts):
                rows.append(
                    {
                        "trading_date": date,
                        "instrument": instrument,
                        "contract": contract,
                        "maturity_date": date + pd.Timedelta(days=60 * (offset + 1)),
                        "price": close * (1.0 + 0.01 * offset),
                        "open_interest": 10_000.0,
                    }
                )
            chosen = contracts[(index // 40) % 3]
            mapping_rows.append(
                {
                    "trading_date": date,
                    "underlying_symbol": instrument,
                    "dominant_order_book_id": chosen,
                    "changed": index > 0
                    and ((index - 1) // 40) % 3 != (index // 40) % 3,
                }
            )
    curve = snapshots(rows)
    mapping = pd.DataFrame(mapping_rows)
    inputs = {
        "continuous_prices": panel,
        "contract_snapshots": curve,
        "dominant_map": mapping,
        "universe": universe,
    }

    factors, unavailable = build_all(inputs)
    assert set(factors) == set(AVAILABLE_FACTORS)
    assert set(unavailable) == set(UNAVAILABLE_FACTORS)
    # oi_participation_trend needs three live contracts per product and 252 OI
    # observations, which this two-product/three-contract panel cannot satisfy.
    needs_long_history = {"oi_participation_trend_60d"}
    for name, table in factors.items():
        assert tuple(table.columns) == FACTOR_COLUMNS
        assert table["factor_name"].eq(name).all()
        if name not in needs_long_history:
            assert table["raw_factor"].notna().any()
