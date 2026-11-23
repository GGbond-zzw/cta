"""Build the eleven retained factors from one explicit local input directory.

Required parquet files: continuous_prices,contract_snapshots,dominant_map,universe.
Optional product_flows should be supplied to reproduce aggregated-flow mined
signals. No downloading, fitting, direction flips or account allocation occurs.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from china_cta.factors.qualified import BUILDERS

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',type=Path,required=True)
    p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--factors',default=','.join(BUILDERS))
    a=p.parse_args();names=a.factors.split(',')
    if not set(names).issubset(BUILDERS):raise ValueError('Unknown factor names')
    inputs={k:pd.read_parquet(a.input_dir/(k+'.parquet')) for k in
        ['continuous_prices','contract_snapshots','dominant_map','universe']}
    if (a.input_dir/'product_flows.parquet').exists():inputs['product_flows']=pd.read_parquet(a.input_dir/'product_flows.parquet')
    inputs['continuous_prices'].attrs.update(usage='signal_research_only',cash_pnl_allowed=False,adjust_type='pre',adjust_method='prev_close_ratio')
    a.out_dir.mkdir(parents=True,exist_ok=True)
    for name in names:
        table=BUILDERS[name](inputs);table.attrs={}
        folder=a.out_dir/name;folder.mkdir(exist_ok=True)
        table.to_parquet(folder/'signals.parquet',index=False)
        print(name,len(table),flush=True)
    (a.out_dir/'manifest.json').write_text(json.dumps(dict(factors=names,training=False,
        parameters='four original builders retain baseline defaults;override through historical tuning entrypoint',
        no_account_backtest=True),indent=2),encoding='utf8')

if __name__=='__main__':main()
