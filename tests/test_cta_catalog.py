"""Catalog-level tests for the 22-factor CTA alpha registry."""

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


def research_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-03", periods=320)
    rows = []
    for instrument, base in (("RB", 4_000.0), ("CU", 60_000.0)):
        for index, date in enumerate(dates):
            close = base * (1.0 + 0.0005 * index + 0.02 * math.sin(index / 9.0))
            rows.append(
                {
                    "trading_date": date,
                    "underlying_symbol": instrument,
                    "close": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "volume": 10_000.0 + index,
                    "open_interest": 20_000.0 + index,
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


def test_catalog_contains_22_unique_specs_with_expected_availability() -> None:
    assert len(FACTOR_SPECS) == 22
    names = [spec.name for spec in FACTOR_SPECS]
    assert len(set(names)) == 22
    assert set(AVAILABLE_FACTORS) | set(UNAVAILABLE_FACTORS) == set(names)
    assert len(AVAILABLE_FACTORS) == 18
    assert set(UNAVAILABLE_FACTORS) == {
        "basis_mom_20",
        "ls_ratio_z",
        "inventory_mom_20",
        "spot_profit_z",
    }
    for spec in FACTOR_SPECS:
        assert spec.signal_scale > 0
        if not spec.available:
            assert spec.reason
    table = spec_table()
    assert len(table) == 22
    assert table["factor_name"].is_unique
    assert table["available"].sum() == 18


def test_build_all_returns_every_available_factor_on_synthetic_panel() -> None:
    dates = pd.bdate_range("2022-01-03", periods=320)
    panel = research_prices()
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
                        "maturity_date": date + pd.Timedelta(days=90 * (offset + 1)),
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
    warehouse = pd.DataFrame(
        {
            "trading_date": list(dates) * 2,
            "underlying_symbol": ["RB"] * len(dates) + ["CU"] * len(dates),
            "on_warrant": list(1_000.0 + np.arange(len(dates))) * 2,
        }
    )
    member_rows = []
    for instrument in ("RB", "CU"):
        for index, date in enumerate(dates):
            for side in ("long", "short"):
                for rank in (1, 2, 3):
                    member_rows.append(
                        {
                            "trading_date": date,
                            "underlying_symbol": instrument,
                            "side": side,
                            "rank": rank,
                            "member_name": f"{side}{rank}",
                            "volume": 1_000.0 + 10.0 * index + rank,
                        }
                    )
    member = pd.DataFrame(member_rows)

    factors, unavailable = build_all(
        continuous_prices=panel,
        contract_snapshots=curve,
        dominant_map=mapping,
        warehouse_stocks=warehouse,
        member_rank=member,
        universe=universe,
    )
    assert set(factors) == set(AVAILABLE_FACTORS)
    assert set(unavailable) == set(UNAVAILABLE_FACTORS)
    for name, table in factors.items():
        assert tuple(table.columns) == FACTOR_COLUMNS
        assert table["factor_name"].eq(name).all()
        assert table["raw_factor"].notna().any()
