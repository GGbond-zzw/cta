"""趋势拥挤反转（表达式类）。

`-corr_60(mean_60(return_60), channel_position_20 × volatility_20)`：当“通道高位 + 高波动”把 60 日动量推高时，反向持有。窗口与尺度全部内联在本文件，`build()` 直接由研究面板现算，不读取任何缓存表。"""

from __future__ import annotations

from china_cta.factors.panel_features import (
    binary,
    evaluate,
    feature,
    features_for,
    to_long,
    unary,
)
from china_cta.factors.schema import make_factor_table

FACTOR_NAME = "crowded_trend_reversal_60d"
TREND_WINDOW = 60
CORRELATION_WINDOW = 60
DIRECTION = 1
SIGNAL_SCALE = 0.7073720289720415


def build(inputs) -> "pd.DataFrame":
    """Compute the factor straight from the research panel (no cached signal)."""

    features = features_for(inputs["continuous_prices"])
    expression = unary(
        "neg",
        {
            "op": "corr",
            "args": [
                unary("mean", feature("return_60"), TREND_WINDOW),
                {"op": "mul", "args": [feature("channel_position_20"), feature("volatility_20")]},
            ],
            "window": CORRELATION_WINDOW,
        },
    )
    values = evaluate(expression, features) * float(DIRECTION)
    table = make_factor_table(
        to_long(values, factor_name=FACTOR_NAME),
        inputs["universe"],
        factor_name=FACTOR_NAME,
        signal_scale=SIGNAL_SCALE,
    )
    table.attrs.update(
        {
            "definition": "neg(corr(mean(return_60, 60), mul(channel_position_20, volatility_20), 60))",
            "direction": DIRECTION,
            "signal_scale": SIGNAL_SCALE,
            "price_field": "close",
            "adjust_method": "prev_close_ratio",
            "raw_factor_normalization": "none",
        }
    )
    return table
