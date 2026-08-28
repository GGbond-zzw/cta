"""One transparent medium-frequency Trend baseline."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.schema import make_factor_table


def compute_trend_factor(
    continuous_prices: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    lookback: int = 60,
    signal_scale: float = 0.20,
    price_field: str = "close",
) -> pd.DataFrame:
    """Compute ratio-adjusted close momentum without filling missing prices.

    ``raw_factor(t) = price(t) / price(t-lookback) - 1``. The output dated t
    uses close(t), is available only after that close, and cannot trade at it.
    """

    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if continuous_prices.attrs.get("usage") != "signal_research_only":
        raise ValueError("Trend requires Phase 2 signal/research continuous prices")
    if continuous_prices.attrs.get("cash_pnl_allowed") is not False:
        raise ValueError("Trend input must be explicitly prohibited from cash P&L")
    if continuous_prices.attrs.get("adjust_type") != "pre" or continuous_prices.attrs.get(
        "adjust_method"
    ) != "prev_close_ratio":
        raise ValueError("Trend requires pre-adjusted prev_close_ratio prices")

    required = ("trading_date", "underlying_symbol", price_field)
    missing = sorted(set(required) - set(continuous_prices.columns))
    if missing:
        raise ValueError(f"continuous_prices is missing fields: {missing}")
    prices = continuous_prices.loc[:, required].copy()
    prices = prices.rename(columns={"underlying_symbol": "instrument"})
    prices["trading_date"] = pd.to_datetime(
        prices["trading_date"], errors="raise"
    ).dt.normalize()
    prices["instrument"] = (
        prices["instrument"].astype("string").str.strip().str.upper()
    )
    prices[price_field] = pd.to_numeric(prices[price_field], errors="coerce")
    if prices.duplicated(["trading_date", "instrument"]).any():
        raise ValueError("continuous_prices contains duplicate date/instrument rows")
    prices = prices.sort_values(["instrument", "trading_date"]).reset_index(drop=True)

    # 要求窗口内每个交易期都有有效价格，避免通过隐式填充制造趋势信号。
    valid_price = prices[price_field].where(prices[price_field].gt(0))
    base_price = valid_price.groupby(prices["instrument"], sort=False).shift(
        lookback
    )
    window_count = valid_price.groupby(prices["instrument"], sort=False).transform(
        lambda values: values.rolling(
            lookback + 1, min_periods=lookback + 1
        ).count()
    )
    prices["raw_factor"] = (valid_price / base_price - 1.0).where(
        window_count.eq(lookback + 1)
    )
    result = make_factor_table(
        prices.loc[:, ["trading_date", "instrument", "raw_factor"]],
        universe,
        factor_name=f"trend_{lookback}d",
        signal_scale=signal_scale,
    )
    result.attrs.update(
        {
            "definition": "price_t / price_t_minus_lookback - 1",
            "lookback_trading_periods": lookback,
            "price_field": price_field,
            "adjust_method": "prev_close_ratio",
        }
    )
    return result
