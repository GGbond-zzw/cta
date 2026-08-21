from __future__ import annotations

import os

import pytest

from china_cta.data.contracts import (
    get_contract_roles,
    get_contract_snapshot,
    get_curve_snapshot,
    get_research_universe,
    get_roll_map,
    get_signal_continuous_price,
)
from china_cta.data.rqdata_adapter import RQDataAdapter, RQDataConfig


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_RQDATA_INTEGRATION") != "1",
        reason="set RUN_RQDATA_INTEGRATION=1 for licensed RQData checks",
    ),
]

RESEARCH_DATE = "2020-06-15"
PRODUCTS = ("RB", "CU", "IF", "AG")


def licensed_adapter(tmp_path) -> RQDataAdapter:
    local = RQDataConfig.from_environment()
    adapter = RQDataAdapter(
        RQDataConfig(uri=local.uri, market=local.market, cache_dir=tmp_path)
    )
    adapter.connect(lazy=False)
    return adapter


def test_phase2_historical_universe_and_curves(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    universe = get_research_universe(adapter, RESEARCH_DATE)

    eligible = set(universe.loc[universe["eligible"], "instrument"])
    assert set(PRODUCTS).issubset(eligible)
    assert "SI" not in set(universe["instrument"])
    for product in PRODUCTS:
        snapshot = get_contract_snapshot(adapter, product, RESEARCH_DATE)
        curve = get_curve_snapshot(adapter, product, RESEARCH_DATE)
        official_contracts = set(
            adapter.get_future_contracts(product, RESEARCH_DATE)
        )

        assert set(snapshot["order_book_id"]) == official_contracts
        assert snapshot["maturity_date"].is_monotonic_increasing
        assert set(curve["order_book_id"]).issubset(official_contracts)
        assert curve["price"].notna().all()
        assert snapshot["dominant_rank"].eq(1).sum() == 1


def test_phase2_dominant_roll_roles_and_continuous_price(tmp_path) -> None:
    adapter = licensed_adapter(tmp_path)
    for product in PRODUCTS:
        roles = get_contract_roles(adapter, product, RESEARCH_DATE)
        roll_map = get_roll_map(adapter, product, "2020-04-01", "2020-08-31")

        assert roles.signal_contract == roles.trade_contract
        assert roles.trade_contract in roles.curve_contracts
        assert roll_map["changed"].any()

    continuous = get_signal_continuous_price(
        adapter,
        "RB",
        "2020-06-12",
        "2020-06-16",
        fields="close",
    )
    assert not continuous.empty
    assert continuous.attrs["usage"] == "signal_research_only"
    assert continuous.attrs["cash_pnl_allowed"] is False
