"""Exchange/social inventory growth (unavailable, unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import FactorDataUnavailable


def build(inputs: dict) -> pd.DataFrame:
    raise FactorDataUnavailable(
        "RQData 只提供注册仓单（on_warrant），没有独立的社会库存/交易所库存序列；"
        "inventory_mom_20 与 receipt_mom_20 不能共用同一份数据冒充两个因子。"
    )
