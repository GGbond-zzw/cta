"""Frozen single-factor builder; no fitting."""
from __future__ import annotations
import pandas as pd
from china_cta.factors.mined.expressions import compute_features,evaluate,feature_node as feat,binary,unary,to_long
from china_cta.factors.schema import make_factor_table
def build(inputs: dict) -> pd.DataFrame:
    panel=inputs['continuous_prices'].rename(columns={'underlying_symbol':'instrument'}).copy()
    flows=inputs.get('product_flows')
    if flows is not None:
        panel=panel.merge(flows.rename(columns={'product':'instrument'}),on=['trading_date','instrument'],how='left',validate='one_to_one')
        for field,total in [('volume','volume_total'),('open_interest','oi_total'),('total_turnover','turnover_total')]:
            panel[field]=panel[total].combine_first(panel[field])
    features,_=compute_features(panel)
    raw=evaluate(binary('mul',feat('return_1'),unary('std',unary('std',feat('volume_change'),20),5)),features)*-1
    return make_factor_table(to_long(raw,factor_name='volume_variability_weighted_reversal'),inputs['universe'],factor_name='volume_variability_weighted_reversal',signal_scale=0.0007038049575569826)
