"""Spot processing-profit z-score (unavailable, unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import FactorDataUnavailable


def build(inputs: dict) -> pd.DataFrame:
    raise FactorDataUnavailable(
        "RQData 不提供覆盖 30 个商品品种的现货加工利润序列；spot_profit_z 不计算。"
    )
