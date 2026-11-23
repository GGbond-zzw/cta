"""Frozen single-factor builder; no fitting."""
from __future__ import annotations
import pandas as pd
from china_cta.factors.mined.sleeves import build_mined_factor
def build(inputs: dict) -> pd.DataFrame:
    return build_mined_factor('volume_burst_vol_reversal_60d', {}, inputs)
