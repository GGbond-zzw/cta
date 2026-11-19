# 挖掘因子（exported sleeves）

手写四因子之外，项目还接收由表达式搜索（挖掘项目）产出的冻结信号。它们不是手写因子：
搜索过程给出表达式、方向和尺度，导出包把信号冻结成 parquet，本仓库只负责登记与重放。

目前登记了两轮导出的七个 sleeve，其中 `volume_oi_coflow_10d` 已退出组合（样本外为负、且没有
可调维度），保留登记是为了历史结果可追溯。

## 登记表

| sleeve 名 | 挖掘编号 | 轮次 | 导出目录 | 方向 | 尺度 | 一句话解释 |
|---|---|---|---|---:|---:|---|
| `crowded_trend_reversal_60d` | `mined_4a51bf38703a`（原8号） | 一轮 | `old_08` | +1 | 0.7073720289720415 | 趋势与“通道位置 × 波动”的 60 日相关性取负：趋势越被高波动/高位推动，越反向做 |
| `volume_oi_coflow_10d` | `mined_7dffc88fcdec`（原2号） | 一轮 | `old_02` | +1 | 0.7148378264008488 | 成交量变化与持仓量超预期同向共振的 10 日相关性（已退出组合） |
| `volume_burst_vol_reversal_60d` | `mined_8eb423cac50b`（上一轮1号） | 一轮 | `new_01_previous_round` | −1 | 0.3029101622490162 | 放量加速与波动放大（vol20/vol60）20 日相关性、再取 60 日均值后取负 |
| `turnover_surprise_channel_ratio` | `mined_f0dd19ea2ff1`（本轮1号） | 二轮 | `current_01_turnover_surprise_channel_ratio` | +1 | 4.414286511620197 | 成交额相对前 20 日均值的偏离，除以收盘价在 20 日高低区间内的居中位置 |
| `volume_channel_price_oi_volatility` | `mined_bdfbd7063550`（本轮6号） | 二轮 | `current_06_volume_channel_price_oi_volatility` | +1 | 5.3720659606008665 | 成交量五日变化与通道位置之比，加上价仓交互项 60 日差值的 5 日标准差 |
| `inverse_oi_turnover_surprise_ratio` | `mined_cbe804196d96`（本轮8号） | 二轮 | `current_08_inverse_oi_turnover_surprise_ratio` | −1 | 3.13168742823665 | 持仓量异动除以成交额异动的 10 日均值，训练拟合方向为负 |
| `volume_variability_weighted_reversal` | `mined_57002a2d5f10`（本轮20号） | 二轮 | `current_20_volume_variability_weighted_reversal` | −1 | 0.0007038049575569826 | 一日收益乘以成交量变化的 20 日标准差、再取 5 日标准差，拟合方向为负 |

## 命名规则

`<测什么>_<窗口>`：

* `crowded_trend` = 趋势被“高位 × 高波动”推动（拥挤），`reversal` = 方向取负；
* `volume_oi_coflow` = 量仓同向流入；
* `volume_burst_vol` = 放量叠加波动放大，`reversal` = 方向取负；
* `turnover_surprise_channel_ratio` = 成交额异动 ÷ 通道位置；
* `volume_channel_price_oi_volatility` = 量变/通道 + 价仓波动；
* `inverse_oi_turnover_surprise_ratio` = 持仓异动 ÷ 成交额异动，取反；
* `volume_variability_weighted_reversal` = 用量变波动加权的短期反转。

数值后缀是表达式中最关键的窗口，与项目既有命名（`..._60d`、`..._252d`）一致。挖掘侧的中文
标签保留在登记表“挖掘编号”列与 `exported.py` 的 `description` 字段里，两边可以互查。

## 多包混装

一个组合可以同时使用多轮导出。`exported.py` 的 `locate()` 会把每个请求的 sleeve 分配到真正
包含它的那个包目录，重复指定同一个包或找不到都会直接报错：

```bash
python scripts/70_native_backtest.py \
  --factors historical_skewness_252d,fixed_maturity_carry_90_180d,xsmom_252_21,oi_participation_trend_60d \
  --extra-package C:/Users/ct/Desktop/一轮三因子 \
  --extra-package C:/Users/ct/Desktop/二轮四因子 \
  --extra-factors crowded_trend_reversal_60d,volume_burst_vol_reversal_60d,turnover_surprise_channel_ratio,volume_channel_price_oi_volatility,inverse_oi_turnover_surprise_ratio,volume_variability_weighted_reversal \
  --book-factors turnover_surprise_channel_ratio,volume_channel_price_oi_volatility,inverse_oi_turnover_surprise_ratio,volume_variability_weighted_reversal \
  --out-dir results/final_10f_native
```

`scripts/40_correlation_report.py` 同样支持 `--extra-package` / `--extra-factors`，因此相关性
分析可以覆盖“手写因子 + 挖掘因子”的混合组合。

## 数据契约

`signals.parquet` 必需列：`trading_date`（信息日 T，收盘）、`instrument`（品种代码）、
`raw_factor`、`signal`（已定向、已按 scale 缩放并截断到 [−1, 1]）、`factor_name`。
`definition.json` 提供 `factor_name`（一轮导出用 `name`）、`fitted.direction`、`fitted.scale`、
表达式树。

`china_cta/factors/exported.py` 在加载时校验：

1. 目录与 `signals.parquet` 存在；
2. 必需列齐全、`(trading_date, instrument)` 不重复、`|signal| ≤ 1`；
3. 若存在 `definition.json`，其编号、`direction`、`scale` 必须与登记表一致（防止导出包被换掉）。

## 与既有因子一起使用时

* 组合权重等权（N 个 sleeve 各 1/N）；
* 信号按信息日 T 记录，原生账户在 T+1 的开盘竞价成交（有夜盘品种即 T 日晚 21:00）；
* 导出包覆盖 30 个品种（含项目未定价的 BU/C/FU/HC/RM），进入组合前与项目 `universe` 做同样的
  PIT 连接，会打印被剔除的品种；
* 结果写进 `config.json` 的 `sleeves`、`sleeve_weights`、`exported_packages`、`exported_sleeves`。

## 当前十腿组合

四条手写 sleeve + 六条挖掘 sleeve（一轮两条、二轮四条），各 1/10。原生账户口径
（5000 万本金、50% 保证金按实时权益、1 跳滑点、原生手续费）2016-01-04..2026-09-04：
夏普 1.7293、年化 38.56%、波动 20.03%、最大回撤 −20.32%；三段训练 1.6783 / 验证 1.4040 /
测试 2.3955。研究层等权（1bp）夏普 2.0108。

需要注意的是二轮四条 sleeve 的单腿原生账户表现接近零（0.06 / −0.03 / −0.08 / −0.38），
它们靠与其余六条的低相关（均值 0.067）贡献组合夏普，而日均换手 0.21–0.37 也让摩擦占毛利
升到 22.4%（七腿时为 13.5%）。
