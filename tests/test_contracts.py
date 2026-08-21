from __future__ import annotations

import pandas as pd

from china_cta.data.contracts import (
    CONTRACT_SNAPSHOT_COLUMNS,
    ROLL_MAP_COLUMNS,
    ContractRoles,
    get_contract_roles,
    get_contract_snapshot,
    get_curve_snapshot,
    get_research_universe,
    get_roll_map,
    get_signal_continuous_price,
    get_trading_parameter_availability,
)


def instrument_master(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "order_book_id",
            "underlying_symbol",
            "exchange",
            "listed_date",
            "de_listed_date",
            "maturity_date",
            "contract_multiplier",
            "product",
        ],
    ).assign(
        listed_date=lambda frame: pd.to_datetime(frame["listed_date"]),
        de_listed_date=lambda frame: pd.to_datetime(frame["de_listed_date"]),
        maturity_date=lambda frame: pd.to_datetime(frame["maturity_date"]),
    )


class StubAdapter:
    def __init__(self) -> None:
        self.point_in_time = instrument_master(
            [
                (
                    "RB2007",
                    "RB",
                    "SHFE",
                    "2019-07-16",
                    "2020-07-15",
                    "2020-07-15",
                    10.0,
                    "Commodity",
                ),
                (
                    "RB2010",
                    "RB",
                    "SHFE",
                    "2019-10-16",
                    "2020-10-15",
                    "2020-10-15",
                    10.0,
                    "Commodity",
                ),
                (
                    "RB2101",
                    "RB",
                    "SHFE",
                    "2020-01-16",
                    "2021-01-15",
                    "2021-01-15",
                    10.0,
                    "Commodity",
                ),
                ("RB88", "RB", "SHFE", None, None, None, 10.0, "Commodity"),
                (
                    "IF2006",
                    "IF",
                    "CFFEX",
                    "2020-04-20",
                    "2020-06-19",
                    "2020-06-19",
                    300.0,
                    "Index",
                ),
            ]
        )
        self.full = pd.concat(
            [
                self.point_in_time,
                instrument_master(
                    [
                        (
                            "RB0910",
                            "RB",
                            "SHFE",
                            "2009-03-27",
                            "2009-10-15",
                            "2009-10-15",
                            10.0,
                            "Commodity",
                        ),
                        (
                            "IF1005",
                            "IF",
                            "CFFEX",
                            "2010-04-16",
                            "2010-05-21",
                            "2010-05-21",
                            300.0,
                            "Index",
                        ),
                        (
                            "SI2308",
                            "SI",
                            "GFEX",
                            "2022-12-22",
                            "2023-08-14",
                            "2023-08-14",
                            5.0,
                            "Commodity",
                        ),
                    ]
                ),
            ],
            ignore_index=True,
        )

    def get_future_instruments(self, date=None):
        return self.full.copy() if date is None else self.point_in_time.copy()

    def get_future_contracts(self, product, date):
        assert product == "RB"
        return ("RB2007", "RB2010", "RB2101")

    def get_bars(self, ids, start, end, *, fields):
        date = pd.Timestamp(start)
        if set(ids) == {"RB2007", "RB2010", "RB2101"}:
            return pd.DataFrame(
                {
                    "trading_date": [date, date],
                    "order_book_id": ["RB2007", "RB2010"],
                    fields[0]: [3550.0, 3600.0],
                    "volume": [10_000.0, 1_000_000.0],
                    "open_interest": [20_000.0, 1_500_000.0],
                }
            )
        return pd.DataFrame(
            {
                "trading_date": [date, date],
                "order_book_id": ["RB2010", "IF2006"],
                "volume": [1_000_000.0, 10.0],
                "open_interest": [1_500_000.0, 20.0],
            }
        )

    def get_dominant_map(self, product, start, end, *, rule, rank):
        assert product == "RB"
        dates = pd.date_range(start, end, freq="B")
        contracts = ["RB2007" if date < pd.Timestamp("2020-06-17") else "RB2010" for date in dates]
        return pd.DataFrame(
            {
                "trading_date": dates,
                "underlying_symbol": product,
                "dominant_order_book_id": contracts,
            }
        )

    def get_dominant_price(self, *args, **kwargs):
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2020-06-15")],
                "underlying_symbol": ["RB"],
                "close": [3600.0],
            }
        )


def test_research_universe_is_point_in_time_and_supports_liquidity() -> None:
    adapter = StubAdapter()

    result = get_research_universe(
        adapter,
        "2020-06-15",
        min_listing_history_days=365,
        min_volume=100.0,
        min_open_interest=100.0,
    )

    assert result.columns.tolist() == [
        "trading_date",
        "instrument",
        "eligible",
        "reason",
    ]
    assert set(result["instrument"]) == {"RB", "IF"}
    assert result.set_index("instrument").loc["RB", "eligible"]
    assert (
        result.set_index("instrument").loc["IF", "reason"]
        == "insufficient_liquidity"
    )
    assert "SI" not in set(result["instrument"])


def test_contract_and_curve_snapshots_keep_real_contract_semantics() -> None:
    adapter = StubAdapter()

    snapshot = get_contract_snapshot(adapter, "rb", "2020-06-15")
    curve = get_curve_snapshot(adapter, "rb", "2020-06-15")

    assert tuple(snapshot.columns) == CONTRACT_SNAPSHOT_COLUMNS
    assert snapshot["order_book_id"].tolist() == ["RB2007", "RB2010", "RB2101"]
    assert snapshot["maturity_date"].is_monotonic_increasing
    assert snapshot.set_index("order_book_id").loc["RB2007", "days_to_maturity"] == 30
    assert snapshot.set_index("order_book_id").loc["RB2007", "dominant_rank"] == 1
    assert pd.isna(snapshot.set_index("order_book_id").loc["RB2101", "price"])
    assert curve["order_book_id"].tolist() == ["RB2007", "RB2010"]
    assert "RB88" not in set(snapshot["order_book_id"])


def test_roll_map_marks_only_actual_dominant_changes() -> None:
    result = get_roll_map(StubAdapter(), "rb", "2020-06-15", "2020-06-19")

    assert tuple(result.columns) == ROLL_MAP_COLUMNS
    changed = result.loc[result["changed"]]
    assert changed["trading_date"].tolist() == [pd.Timestamp("2020-06-17")]
    assert changed.iloc[0]["previous_dominant_order_book_id"] == "RB2007"
    assert changed.iloc[0]["dominant_order_book_id"] == "RB2010"


def test_contract_roles_are_explicit_without_extra_hierarchy() -> None:
    roles = get_contract_roles(StubAdapter(), "rb", "2020-06-15")

    assert isinstance(roles, ContractRoles)
    assert roles.signal_contract == "RB2007"
    assert roles.trade_contract == "RB2007"
    assert roles.curve_contracts == ("RB2007", "RB2010", "RB2101")


def test_continuous_price_is_marked_signal_only() -> None:
    result = get_signal_continuous_price(
        StubAdapter(), "RB", "2020-06-15", "2020-06-15", fields="close"
    )

    assert result.attrs["usage"] == "signal_research_only"
    assert result.attrs["cash_pnl_allowed"] is False
    assert result.attrs["adjust_type"] == "pre"
    assert result.attrs["adjust_method"] == "prev_close_spread"
    assert result.attrs["rule"] == 0
    assert result.attrs["rank"] == 1


def test_trading_parameter_availability_blocks_post_close_decisions() -> None:
    availability = get_trading_parameter_availability().set_index("field")

    assert availability.loc["long_margin_ratio", "availability"] == "pre_open"
    assert availability.loc["long_margin_ratio", "allowed_for_same_day_decision"]
    assert availability.loc["open_commission", "availability"] == "post_close"
    assert not availability.loc[
        "open_commission", "allowed_for_same_day_decision"
    ]
