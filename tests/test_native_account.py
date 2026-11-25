from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from china_cta.formal_backtest import native_account as native


def _config(**overrides) -> native.NativeAccountConfig:
    base = {
        "start_date": "2020-01-02",
        "end_date": "2020-01-31",
        "bundle_path": "unused",
        "output_dir": "unused",
        "initial_capital": 1_000_000.0,
        "margin_budget": 0.50,
    }
    base.update(overrides)
    return native.NativeAccountConfig(**base)


def _market(bars: pd.DataFrame, margin_rate: float = 0.10, multiplier: float = 10.0) -> dict:
    instruments = pd.DataFrame(
        {
            "order_book_id": ["RB2005"],
            "product": ["RB"],
            "contract_multiplier": [multiplier],
            "tick_size": [1.0],
        }
    )
    terms = pd.DataFrame(
        {"product": ["RB"], "margin_rate": [margin_rate], "tick_size": [1.0]}
    )
    return {"bars": bars, "instruments": instruments, "terms": terms}


def _bars(prices: list[tuple[str, float]]) -> pd.DataFrame:
    rows = [
        {
            "order_book_id": "RB2005",
            "trading_date": pd.Timestamp(date),
            "open": close,
            "close": close,
            "settlement": close,
            "high": close,
            "low": close,
            "volume": 10_000.0,
        }
        for date, close in prices
    ]
    return pd.DataFrame(rows)


def test_combine_sleeves_spreads_each_sleeve_evenly() -> None:
    signals = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2020-01-02"] * 3),
            "sleeve": ["carry", "carry", "momentum"],
            "product": ["RB", "I", "RB"],
            "signal": [1.0, 0.5, -1.0],
        }
    )
    exposure = native.combine_sleeves(signals, {"carry": 0.5, "momentum": 0.5})

    by_product = exposure.set_index("product")["exposure"]
    # carry holds 0.5 of capital: 0.5*1.0/2 = 0.25 on RB, 0.5*0.5/2 = 0.125 on I;
    # momentum adds 0.5*(-1.0) = -0.5 of capital on RB
    assert by_product["RB"] == pytest.approx(0.25 - 0.5)
    assert by_product["I"] == pytest.approx(0.125)


def test_build_target_quantities_truncates_lots() -> None:
    exposure = pd.DataFrame(
        {"trading_date": pd.to_datetime(["2020-01-02"]), "product": ["RB"], "exposure": [0.5]}
    )
    dominant = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2020-01-02"]),
            "product": ["RB"],
            "dominant_order_book_id": ["RB2005"],
        }
    )
    market = _market(_bars([("2020-01-02", 1000.0), ("2020-01-03", 1000.0)]))

    targets = native.build_target_quantities(
        exposure,
        dominant,
        market,
        pd.Series({pd.Timestamp("2020-01-02"): 2.0}),
        _config(),
    )

    # notional = 1e6 * 2.0 * 0.5, contract value = 1000 * 10 -> 100 lots, no margin cap
    assert len(targets) == 1
    row = targets.iloc[0]
    assert row["target_quantity"] == 100
    assert row["trading_date"] == pd.Timestamp("2020-01-03")
    assert row["source_tag"] == "four_factor_book"


def test_build_target_quantities_respects_margin_budget() -> None:
    exposure = pd.DataFrame(
        {"trading_date": pd.to_datetime(["2020-01-02"]), "product": ["RB"], "exposure": [5.0]}
    )
    dominant = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2020-01-02"]),
            "product": ["RB"],
            "dominant_order_book_id": ["RB2005"],
        }
    )
    market = _market(_bars([("2020-01-02", 1000.0), ("2020-01-03", 1000.0)]), margin_rate=0.20)

    targets = native.build_target_quantities(
        exposure, dominant, market, None, _config(margin_budget=0.10)
    )

    # 500 lots would need 1e6 of margin; the 100k budget scales it down to 10%
    assert int(targets.iloc[0]["target_quantity"]) == 50
    assert targets.iloc[0]["quantity_before_margin_scale"] == 500


def test_performance_metrics_on_a_constant_return_series() -> None:
    equity = pd.Series(
        [100.0 * (1.001**step) for step in range(253)],
        index=pd.bdate_range("2020-01-01", periods=253),
    )
    metrics = native.performance_metrics(equity)

    assert metrics["periods"] == 252
    assert metrics["sharpe"] > 100  # constant return -> near-zero volatility
    assert metrics["max_drawdown"] == pytest.approx(0.0)


def test_segment_metrics_splits_train_validation_test() -> None:
    index = pd.bdate_range("2016-01-04", "2026-09-04")
    equity = pd.Series(100.0 * 1.0001 ** np.arange(len(index)), index=index)
    frame = native.segment_metrics(equity)

    assert list(frame["segment"]) == [name for name, _, _ in native.SEGMENTS] + ["overall"]
    train = frame.loc[frame["segment"] == "train_2016_2021"].iloc[0]
    assert train["end"] == "2021-12-31"
    overall = frame.loc[frame["segment"] == "overall"].iloc[0]
    assert overall["start"] == "2016-01-04"
    assert overall["end"] == "2026-09-04"


def test_attribute_pnl_reconciles_carry_and_trade_legs() -> None:
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    market = _market(
        pd.DataFrame(
            {
                "order_book_id": ["RB2005"] * 3,
                "trading_date": dates,
                "open": [1000.0, 1010.0, 1020.0],
                "close": [1005.0, 1015.0, 1025.0],
                "settlement": [1005.0, 1015.0, 1025.0],
                "high": [1006.0, 1016.0, 1026.0],
                "low": [999.0, 1009.0, 1019.0],
                "volume": [10_000.0] * 3,
            }
        )
    )
    positions = pd.DataFrame(
        {
            "trading_date": [dates[0], dates[1], dates[2]],
            "order_book_id": ["RB2005"] * 3,
            "quantity": [0.0, 10.0, 4.0],
        }
    )

    panel = native.attribute_pnl(positions, None, market)

    day2 = panel.loc[panel["trading_date"] == dates[1]].iloc[0]
    # bought 10 lots at the day-2 open 1010, marked to close 1015, one tick paid
    assert day2["pnl_carry"] == pytest.approx(0.0)
    assert day2["pnl_trade"] == pytest.approx(10 * 10 * (1015.0 - 1010.0) - 10 * 10 * 1.0)
    assert day2["slippage"] == pytest.approx(100.0)

    day3 = panel.loc[panel["trading_date"] == dates[2]].iloc[0]
    # still holding 10 lots into day 3: carry leg = 10 * 10 * (1025 - 1015);
    # the sell of 6 lots is valued from that day's open 1020 up to 1025, minus a tick
    assert day3["pnl_carry"] == pytest.approx(1000.0)
    assert day3["pnl_trade"] == pytest.approx(-6 * 10 * (1025.0 - 1020.0) - 6 * 10 * 1.0)


def test_annotate_execution_time_uses_the_previous_evening_for_night_contracts():
    trades = pd.DataFrame(
        {
            "datetime": ["2024-01-03 00:00:00", "2024-01-03 00:00:00"],
            "trading_datetime": ["2024-01-03 00:00:00", "2024-01-03 00:00:00"],
            "order_book_id": ["AG2406", "JD2405"],
        }
    )
    annotated = native.annotate_execution_time(
        trades, ["2024-01-02", "2024-01-03"], {"AG"}
    )
    assert annotated["night_session"].tolist() == [True, False]
    assert annotated.loc[0, "execution_time"] == "2024-01-02 21:00:00"
    assert annotated.loc[1, "execution_time"] == "2024-01-03 09:00:00"


def test_night_products_reads_the_first_trading_slot():
    instruments = pd.DataFrame(
        {
            "product": ["AG", "JD"],
            "trading_hours": [
                "21:01-02:30,09:01-10:15",
                "09:01-10:15,13:31-15:00",
            ],
        }
    )
    assert native.night_products(instruments) == {"AG"}
    assert native.product_of("RB2410") == "RB"


def _synthetic_market(days: int = 90) -> tuple[dict, "pd.DataFrame"]:
    import numpy as np
    import pandas as pd

    dates = pd.bdate_range("2021-01-04", periods=days)
    steps = np.arange(days)
    # Two product return streams with a stable, known volatility.
    first = 0.01 * np.sin(steps / 3.0) + 0.0015 * np.cos(steps / 7.0)
    second = 0.01 * np.cos(steps / 4.0)
    frames: list[pd.DataFrame] = []
    for product, returns in (("AA", first), ("BB", second)):
        close = 1000.0 * np.cumprod(1.0 + returns)
        frames.append(
            pd.DataFrame(
                {
                    "order_book_id": f"{product}2101",
                    "trading_date": dates,
                    "settlement": close,
                    "close": close,
                }
            )
        )
    bars = pd.concat(frames, ignore_index=True)
    dominant = pd.DataFrame(
        {
            "trading_date": list(dates) * 2,
            "product": ["AA"] * days + ["BB"] * days,
            "dominant_order_book_id": ["AA2101"] * days + ["BB2101"] * days,
        }
    )
    market = {"bars": bars, "instruments": pd.DataFrame(), "terms": pd.DataFrame()}
    return market, dominant


def test_ex_ante_leverage_hits_the_target_for_a_single_asset():
    import pandas as pd
    from china_cta.formal_backtest import native_account as native

    market, dominant = _synthetic_market()
    stamp = pd.Timestamp(market["bars"]["trading_date"].unique()[-1])
    unit = pd.DataFrame(
        {
            "trading_date": [stamp],
            "product": ["AA"],
            "capital_units": [1.0],
        }
    )
    path = native.ex_ante_leverage(
        unit, market, dominant, target=0.20, window=60, cap=10.0, min_periods=40,
        smoothing=0,
    )
    returns = native.product_close_returns(market, dominant)
    realised = float(returns.loc[returns.index < stamp, "AA"].tail(60).std(ddof=1)) * (252.0 ** 0.5)
    assert abs(float(path.loc[stamp]) - 0.20 / realised) < 1e-9


def test_ex_ante_leverage_respects_the_cap_and_the_warmup():
    import pandas as pd
    from china_cta.formal_backtest import native_account as native

    market, dominant = _synthetic_market()
    dates = pd.to_datetime(market["bars"]["trading_date"].unique())
    unit = pd.DataFrame(
        {
            "trading_date": [dates[10], dates[-1]],
            "product": ["AA", "AA"],
            "capital_units": [1.0, 1.0],
        }
    )
    path = native.ex_ante_leverage(
        unit, market, dominant, target=5.0, window=60, cap=2.5, min_periods=40,
        smoothing=0,
    )
    assert float(path.loc[dates[10]]) == 1.0  # not enough history yet
    assert float(path.loc[dates[-1]]) == 2.5  # target unreachable -> cap


def test_ex_ante_leverage_smoothing_damps_the_ratio():
    import pandas as pd
    from china_cta.formal_backtest import native_account as native

    market, dominant = _synthetic_market()
    dates = pd.to_datetime(market["bars"]["trading_date"].unique())
    unit = pd.DataFrame(
        {
            "trading_date": [dates[50], dates[-1]],
            "product": ["AA", "AA"],
            "capital_units": [1.0, 3.0],
        }
    )
    raw = native.ex_ante_leverage(
        unit, market, dominant, target=0.20, window=60, cap=50.0, min_periods=40,
        smoothing=0,
    )
    smooth = native.ex_ante_leverage(
        unit, market, dominant, target=0.20, window=60, cap=50.0, min_periods=40,
        smoothing=15,
    )
    # the smoothed path stays inside the raw range and is damped towards it
    low, high = float(raw.min()), float(raw.max())
    assert low - 1e-9 <= float(smooth.loc[dates[-1]]) <= high + 1e-9
    assert abs(float(smooth.loc[dates[-1]]) - float(raw.loc[dates[-1]])) > 1e-9

