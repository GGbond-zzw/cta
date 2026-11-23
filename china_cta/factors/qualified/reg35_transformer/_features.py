"""Expanded causal price/volume/OI features, no external publication assumptions."""
from __future__ import annotations
import numpy as np
import pandas as pd

def build_features(p:dict[str,pd.DataFrame],pool:np.ndarray)->tuple[np.ndarray,list[str]]:
    c=p['close'].where(lambda x:x.gt(0)&np.isfinite(x));r=np.log(c/c.shift())
    h,l,o=p['high'],p['low'],p['open'];span=(h-l).where(lambda x:x.gt(0))
    v=p['volume'];oi=p['open_interest'];amount=p['total_turnover'];ids=p['ids']
    same=ids.notna()&ids.eq(ids.shift())
    loc=((2*c-h-l)/span).where(c.ge(l)&c.le(h))
    f={'return1':r,'range':span/c,'location':loc,'intraday':np.log(c/o),'gap':np.log(o/c.shift()),
       'log_volume':np.log1p(v),'log_oi':np.log1p(oi),'log_amount':np.log1p(amount),
       'oi_change':np.log(oi/oi.shift()).where(same),'volume_change':np.log(v/v.shift()).where(same),
       'churn':(v/oi).where(same),'roll_flag':(~same).astype(float)}
    for w in [5,10,20,60,120]:
        mu=c.rolling(w,min_periods=w).mean();sd=c.rolling(w,min_periods=w).std(ddof=0).where(lambda x:x.gt(1e-10))
        q=r.rolling(w,min_periods=w);stable=same.rolling(w,min_periods=w).sum().eq(w)
        f.update({f'momentum{w}':q.sum(),f'volatility{w}':q.std(),
            f'bb_z{w}':(c-mu)/sd,f'bandwidth{w}':4*sd/mu,
            f'efficiency{w}':q.sum()/r.abs().rolling(w,min_periods=w).sum().where(lambda x:x.gt(1e-10)),
            f'volume_ratio{w}':np.log(v/v.rolling(w,min_periods=w).mean().shift()).where(stable),
            f'oi_growth{w}':np.log(oi/oi.shift(w)).where(stable),
            f'location_mean{w}':loc.rolling(w,min_periods=w).mean(),
            f'up_fraction{w}':r.gt(0).astype(float).where(r.notna()).rolling(w,min_periods=w).mean(),
            f'skew{w}':q.skew(),f'autocorr{w}':q.corr(r.shift()),
            f'illiquidity{w}':np.log1p(1e10*r.abs()/amount.where(amount.gt(0))).rolling(w,min_periods=w).mean().where(stable)})
    vol20=r.rolling(20,min_periods=20).std().shift().where(lambda x:x.gt(1e-10))
    f['shock']=r/vol20
    f['vol_ratio']=f['volatility5']/f['volatility60'].where(lambda x:x.gt(1e-10))
    peers=r.where(pool).mean(axis=1)
    f['market_return']=pd.DataFrame(np.repeat(peers.to_numpy()[:,None],c.shape[1],axis=1),index=c.index,columns=c.columns)
    f['relative_return']=r.sub(peers,axis=0)
    f['relative_momentum20']=f['momentum20'].sub(f['momentum20'].where(pool).mean(axis=1),axis=0)
    for name in ['momentum20','bb_z20','volatility20','volume_ratio20']:
        rank=f[name].where(pool).rank(axis=1,pct=True)
        f['cs_rank_'+name]=2*rank-1
    names=list(f);x=np.stack([f[n].to_numpy(dtype=float) for n in names],axis=-1)
    return np.where(np.isfinite(x),x,np.nan).astype(np.float32),names
