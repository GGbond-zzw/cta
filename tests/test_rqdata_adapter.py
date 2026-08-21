from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from china_cta.data.rqdata_adapter import (
    DataValidationError,
    INSTRUMENT_DETAIL_COLUMNS,
    INSTRUMENT_MASTER_COLUMNS,
    RQDataAdapter,
    RQDataConfig,
)


def adapter_with_cache(tmp_path: Path) -> RQDataAdapter:
    return RQDataAdapter(RQDataConfig(cache_dir=tmp_path))


def test_config_prefers_rqdatac2_conf(monkeypatch) -> None:
    monkeypatch.setenv("RQDATAC_CONF", "rqdata://fallback")
    monkeypatch.setenv("RQDATAC2_CONF", "rqdata://preferred")
    monkeypatch.setenv("CTA_RQDATA_CACHE_DIR", "project-cache")

    config = RQDataConfig.from_environment()

    assert config.uri == "rqdata://preferred"
    assert config.market == "cn"
    assert config.cache_dir == Path("project-cache")


def test_trading_calendar_calls_rqdata_and_hits_cache(monkeypatch, tmp_path) -> None:
    calls = 0
    monkeypatch.setattr("rqdatac.initialized", lambda: True)

    def fake_get_trading_dates(start_date, end_date, market):
        nonlocal calls
        calls += 1
        assert (start_date, end_date, market) == (
            "2026-08-10",
            "2026-08-12",
            "cn",
        )
        return [pd.Timestamp("2026-08-10").date(), pd.Timestamp("2026-08-12").date()]

    monkeypatch.setattr("rqdatac.get_trading_dates", fake_get_trading_dates)
    adapter = adapter_with_cache(tmp_path)

    first = adapter.get_trading_calendar("2026-08-10", "2026-08-12")
    second = adapter.get_trading_calendar("2026-08-10", "2026-08-12")

    assert calls == 1
    assert first.equals(second)
    assert first.tolist() == [
        pd.Timestamp("2026-08-10"),
        pd.Timestamp("2026-08-12"),
    ]


def test_future_instruments_match_phase1_schema(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    raw = pd.DataFrame(
        {
            "order_book_id": ["rb2610", "IF2609"],
            "underlying_symbol": ["rb", "IF"],
            "exchange": ["SHFE", "CFFEX"],
            "listed_date": ["2025-10-16", "2026-01-19"],
            "de_listed_date": ["2026-10-15", "2026-09-18"],
            "maturity_date": ["2026-10-15", "2026-09-18"],
            "contract_multiplier": [10.0, 300.0],
            "product": ["Commodity", "Index"],
            "ignored": [1, 2],
        }
    )

    def fake_all_instruments(**kwargs):
        assert kwargs == {"type": "Future", "date": "2026-08-17", "market": "cn"}
        return raw

    monkeypatch.setattr("rqdatac.all_instruments", fake_all_instruments)

    result = adapter_with_cache(tmp_path).get_future_instruments("2026-08-17")

    assert tuple(result.columns) == INSTRUMENT_MASTER_COLUMNS
    assert result["order_book_id"].tolist() == ["IF2609", "RB2610"]
    assert result["maturity_date"].dtype == "datetime64[ns]"


def test_future_contracts_use_rqdata_order_and_cache(monkeypatch, tmp_path) -> None:
    calls = 0
    monkeypatch.setattr("rqdatac.initialized", lambda: True)

    def fake_get_contracts(symbol, date, market):
        nonlocal calls
        calls += 1
        assert (symbol, date, market) == ("RB", "2020-06-15", "cn")
        return ["RB2007", "RB2010", "RB2101"]

    monkeypatch.setattr("rqdatac.futures.get_contracts", fake_get_contracts)
    adapter = adapter_with_cache(tmp_path)

    first = adapter.get_future_contracts("rb", "2020-06-15")
    second = adapter.get_future_contracts("rb", "2020-06-15")

    assert calls == 1
    assert first == second == ("RB2007", "RB2010", "RB2101")


def test_instrument_details_calls_tick_size_method(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("rqdatac.initialized", lambda: True)

    class FakeInstrument:
        order_book_id = "RB2610"
        underlying_symbol = "RB"
        exchange = "SHFE"
        listed_date = "2025-10-16"
        de_listed_date = "2026-10-15"
        maturity_date = "2026-10-15"
        contract_multiplier = 10.0
        product = "Commodity"
        margin_rate = 0.12

        @staticmethod
        def tick_size() -> float:
            return 1.0

    def fake_instruments(order_book_ids, market):
        assert order_book_ids == "RB2610"
        assert market == "cn"
        return FakeInstrument()

    monkeypatch.setattr("rqdatac.instruments", fake_instruments)

    result = adapter_with_cache(tmp_path).get_instrument_details("rb2610")

    assert tuple(result.columns) == INSTRUMENT_DETAIL_COLUMNS
    assert result.loc[0, "tick_size"] == 1.0
    assert result.loc[0, "contract_multiplier"] == 10.0
    assert result.loc[0, "margin_rate"] == 0.12


def test_daily_bars_hit_cache_with_identical_schema(monkeypatch, tmp_path) -> None:
    calls = 0
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    index = pd.MultiIndex.from_tuples(
        [("RB2610", pd.Timestamp("2026-08-17"))],
        names=["order_book_id", "date"],
    )
    raw = pd.DataFrame(
        {
            "open": [3150.0],
            "high": [3180.0],
            "low": [3130.0],
            "close": [3168.0],
            "settlement": [3160.0],
            "volume": [100_000.0],
            "open_interest": [200_000.0],
        },
        index=index,
    )

    def fake_get_price(order_book_ids, **kwargs):
        nonlocal calls
        calls += 1
        assert order_book_ids == "RB2610"
        assert kwargs["frequency"] == "1d"
        assert kwargs["adjust_type"] == "none"
        return raw

    monkeypatch.setattr("rqdatac.get_price", fake_get_price)
    adapter = adapter_with_cache(tmp_path)

    first = adapter.get_bars("rb2610", "2026-08-17", "2026-08-17")
    second = adapter.get_bars("rb2610", "2026-08-17", "2026-08-17")

    assert calls == 1
    pd.testing.assert_frame_equal(first, second)
    assert first.columns.tolist() == [
        "trading_date",
        "order_book_id",
        "open",
        "high",
        "low",
        "close",
        "settlement",
        "volume",
        "open_interest",
    ]
    metadata_path = next((tmp_path / "bars").glob("*.metadata.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["operation"] == "bars"
    assert metadata["cache_schema_version"] == 1
    assert metadata["rqdatac_version"]
    assert metadata["fetch_time_utc"].endswith("+00:00")
    assert metadata["request_params"]["order_book_ids"] == ["RB2610"]


def test_bars_accept_one_field_as_a_string(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    raw = pd.DataFrame(
        {"close": [3168.0]},
        index=pd.DatetimeIndex(["2026-08-17"], name="date"),
    )

    def fake_get_price(order_book_ids, **kwargs):
        assert kwargs["fields"] == ["close"]
        return raw

    monkeypatch.setattr("rqdatac.get_price", fake_get_price)

    result = adapter_with_cache(tmp_path).get_bars(
        "RB2610", "2026-08-17", "2026-08-17", fields="close"
    )

    assert result.columns.tolist() == ["trading_date", "order_book_id", "close"]


def test_night_minute_bars_keep_datetime_and_trading_date(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    index = pd.MultiIndex.from_tuples(
        [
            ("AG2209", pd.Timestamp("2022-05-11 21:01:00")),
            ("AG2209", pd.Timestamp("2022-05-12 09:01:00")),
        ],
        names=["order_book_id", "datetime"],
    )
    raw = pd.DataFrame(
        {
            "trading_date": [pd.Timestamp("2022-05-12")] * 2,
            "open": [4800.0, 4810.0],
            "high": [4805.0, 4815.0],
            "low": [4798.0, 4808.0],
            "close": [4802.0, 4812.0],
            "volume": [10.0, 20.0],
            "open_interest": [30_000.0, 30_020.0],
        },
        index=index,
    )

    def fake_get_price(order_book_ids, **kwargs):
        assert kwargs["frequency"] == "1m"
        assert "trading_date" in kwargs["fields"]
        return raw

    monkeypatch.setattr("rqdatac.get_price", fake_get_price)

    result = adapter_with_cache(tmp_path).get_bars(
        "AG2209", "2022-05-12", "2022-05-12", frequency="1m"
    )

    assert result.columns[:3].tolist() == [
        "datetime",
        "trading_date",
        "order_book_id",
    ]
    assert result.loc[0, "datetime"].date() == pd.Timestamp("2022-05-11").date()
    assert result.loc[0, "trading_date"] == pd.Timestamp("2022-05-12")


def test_minute_bars_reject_missing_trading_date(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    raw = pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex(["2022-05-11 21:01"], name="datetime"),
    )
    monkeypatch.setattr("rqdatac.get_price", lambda *args, **kwargs: raw)

    with pytest.raises(DataValidationError, match="trading_date"):
        adapter_with_cache(tmp_path).get_bars(
            "AG2209",
            "2022-05-12",
            "2022-05-12",
            frequency="1m",
            fields=["close"],
        )


def test_dominant_map_is_normalized(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr("rqdatac.initialized", lambda: True)

    def fake_get_dominant(symbol, **kwargs):
        calls.append((symbol, kwargs["rule"], kwargs["rank"]))
        return pd.Series(
            [f"{symbol}2610", f"{symbol}2610"],
            index=pd.DatetimeIndex(["2026-08-13", "2026-08-14"], name="date"),
        )

    monkeypatch.setattr("rqdatac.futures.get_dominant", fake_get_dominant)

    result = adapter_with_cache(tmp_path).get_dominant_map(
        ("rb", "if"), "2026-08-13", "2026-08-14"
    )

    assert calls == [("RB", 0, 1), ("IF", 0, 1)]
    assert result.columns.tolist() == [
        "trading_date",
        "underlying_symbol",
        "dominant_order_book_id",
    ]
    assert result["dominant_order_book_id"].tolist() == [
        "IF2610",
        "RB2610",
        "IF2610",
        "RB2610",
    ]


def test_dominant_price_is_signal_data_and_hits_cache(monkeypatch, tmp_path) -> None:
    calls = 0
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    index = pd.MultiIndex.from_tuples(
        [("RB", pd.Timestamp("2020-06-15"))],
        names=["underlying_symbol", "date"],
    )
    raw = pd.DataFrame(
        {"close": [3600.0], "volume": [1_000.0]},
        index=index,
    )

    def fake_get_dominant_price(symbols, **kwargs):
        nonlocal calls
        calls += 1
        assert symbols == "RB"
        assert kwargs["adjust_type"] == "pre"
        assert kwargs["adjust_method"] == "prev_close_spread"
        assert kwargs["fields"] == ["close", "volume"]
        return raw

    monkeypatch.setattr(
        "rqdatac.futures.get_dominant_price", fake_get_dominant_price
    )
    adapter = adapter_with_cache(tmp_path)

    first = adapter.get_dominant_price(
        "rb",
        "2020-06-15",
        "2020-06-15",
        fields=("close", "volume"),
    )
    second = adapter.get_dominant_price(
        "rb",
        "2020-06-15",
        "2020-06-15",
        fields=("close", "volume"),
    )

    assert calls == 1
    pd.testing.assert_frame_equal(first, second)
    assert first.columns.tolist() == [
        "trading_date",
        "underlying_symbol",
        "close",
        "volume",
    ]


def test_trading_parameters_preserve_provider_units(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("rqdatac.initialized", lambda: True)
    index = pd.MultiIndex.from_tuples(
        [("CU2610", pd.Timestamp("2026-08-17"))],
        names=["order_book_id", "trading_date"],
    )
    raw = pd.DataFrame(
        {
            "long_margin_ratio": [0.12],
            "short_margin_ratio": [0.13],
            "commission_type": ["by_money"],
            "open_commission": [0.00005],
            "client_limit": [1_000.0],
        },
        index=index,
    )

    def fake_get_trading_parameters(order_book_ids, **kwargs):
        assert order_book_ids == "CU2610"
        assert kwargs["start_date"] == "2026-08-17"
        return raw

    monkeypatch.setattr(
        "rqdatac.futures.get_trading_parameters", fake_get_trading_parameters
    )

    result = adapter_with_cache(tmp_path).get_trading_parameters(
        "cu2610", "2026-08-17", "2026-08-17"
    )

    assert result.columns[:2].tolist() == ["trading_date", "order_book_id"]
    assert result.loc[0, "open_commission"] == 0.00005
    assert result.loc[0, "commission_type"] == "by_money"
    assert result.loc[0, "long_margin_ratio"] == 0.12
