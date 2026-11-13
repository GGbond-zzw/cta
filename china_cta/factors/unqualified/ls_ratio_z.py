"""Retail long/short ratio z-score (unavailable, unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import FactorDataUnavailable


def build(inputs: dict) -> pd.DataFrame:
    raise FactorDataUnavailable(
        "RQData 不提供散户多空比（ls_ratio）；会员持仓不能替代散户情绪，"
        "因此 ls_ratio_z 不计算。"
    )
