"""Spot-futures basis momentum (unavailable, unqualified)."""

from __future__ import annotations

import pandas as pd

from china_cta.factors.cta_common import FactorDataUnavailable


def build(inputs: dict) -> pd.DataFrame:
    raise FactorDataUnavailable(
        "RQData 的 get_basis 仅覆盖股指期货；30 个商品品种没有统一现货序列，"
        "basis_mom_20 无法按原定义计算。"
    )
