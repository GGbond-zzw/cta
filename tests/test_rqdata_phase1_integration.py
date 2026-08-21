from __future__ import annotations

import os

import pandas as pd
import pytest

from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_RQDATA_INTEGRATION") != "1",
        reason="set RUN_RQDATA_INTEGRATION=1 for licensed RQData checks",
    ),
]

PRODUCTS = ("RB", "CU", "IF")
RESEARCH_DATE = "2026-08-17"


def licensed_adapter(tmp_path) -> RQDataAdapter:
    local = RQDataConfig.from_environment()
    adapter = RQDataAdapter(
        RQDataConfig(uri=local.uri, market=local.market, cache_dir=tmp_path)
    )
    adapter.connect(lazy=False)
    return adapter


def test_rb_cu_if_phase1_data_contracts(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    instruments = adapter.get_future_instruments(RESEARCH_DATE)
    dominant = adapter.get_dominant_map(PRODUCTS, RESEARCH_DATE, RESEARCH_DATE)
    real_contracts = dominant["dominant_order_book_id"].tolist()
    details = adapter.get_instrument_details(real_contracts)
    bars = adapter.get_bars(real_contracts, RESEARCH_DATE, RESEARCH_DATE)
    parameters = adapter.get_trading_parameters(
        real_contracts, RESEARCH_DATE, RESEARCH_DATE
    )

    instrument_products = set(
        instruments.loc[
            instruments["underlying_symbol"].isin(PRODUCTS), "underlying_symbol"
        ]
    )
    assert instrument_products == set(PRODUCTS)
    assert set(details["underlying_symbol"]) == set(PRODUCTS)
    assert set(bars["order_book_id"]) == set(real_contracts)
    assert set(parameters["order_book_id"]) == set(real_contracts)


def test_real_night_minutes_keep_both_dates(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    bars = adapter.get_bars(
        "AG2209",
        "2022-05-12",
        "2022-05-12",
        frequency="1m",
    )

    assert {"datetime", "trading_date"}.issubset(bars.columns)
    night_rows = bars.loc[
        bars["datetime"].dt.normalize() < bars["trading_date"]
    ]
    assert not night_rows.empty
    assert (night_rows["trading_date"] == pd.Timestamp("2022-05-12")).all()
