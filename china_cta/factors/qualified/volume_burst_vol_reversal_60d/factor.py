"""放量叠加波动扩张的反转（表达式类，随包携带成品信号）。

公式与参数见 `parameters.json` 的 ``expression`` 字段；成品信号在同一个文件夹的
``signals.parquet``，因为公式依赖“品种级成交量/持仓量/成交额”的聚合口径，本地研究
面板只有主力合约口径，重算只能得到相关 0.93–0.99 的近似，无法逐位还原。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FACTOR_NAME = "volume_burst_vol_reversal_60d"
SIGNALS = Path(__file__).with_name("signals.parquet")
COLUMNS = ("trading_date", "instrument", "factor_name", "raw_factor", "signal")


def build(inputs) -> pd.DataFrame:
    """Return the shipped signal table pinned to this package."""

    frame = pd.read_parquet(SIGNALS)
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{SIGNALS.name} is missing columns: {missing}")
    frame = frame.loc[:, list(COLUMNS)].copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str).str.upper()
    frame["raw_factor"] = frame["raw_factor"].astype(float)
    frame["signal"] = frame["signal"].astype(float)
    frame["factor_name"] = FACTOR_NAME
    return frame.sort_values(["trading_date", "instrument"]).reset_index(drop=True)
