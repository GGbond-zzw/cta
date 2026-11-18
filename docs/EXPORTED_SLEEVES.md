# 挖掘因子（exported sleeves）

这四个 sleeve 之外，项目还接收由表达式搜索（挖掘项目）产出的冻结信号。它们不是手写因子：
搜索过程给出表达式、方向和尺度，导出包把信号冻结成 parquet，本仓库只负责登记与重放。

## 登记表

| sleeve 名 | 挖掘编号 | 导出目录 | 方向 | 尺度 | 一句话解释 |
|---|---|---|---:|---:|---|
| `crowded_trend_reversal_60d` | `mined_4a51bf38703a`（原8号） | `old_08` | +1 | 0.7073720289720415 | 趋势与“通道位置 × 波动”的 60 日相关性取负：趋势越被高波动/高位推动，越反向做 |
| `volume_oi_coflow_10d` | `mined_7dffc88fcdec`（原2号） | `old_02` | +1 | 0.7148378264008488 | 成交量变化与持仓量超预期同向共振（量仓同增 = 新资金进场）的 10 日相关性 |
| `volume_burst_vol_reversal_60d` | `mined_8eb423cac50b`（本轮1号） | `new_01_previous_round` | −1 | 0.3029101622490162 | 放量加速与波动放大（vol20/vol60）20 日相关性、再取 60 日均值后取负：放量拉升后反转 |

## 命名规则

`<测什么>_<窗口>`：

* `crowded_trend` = 趋势被“高位 × 高波动”推动（拥挤），`reversal` = 方向取负；
* `volume_oi_coflow` = 量仓同向流入；
* `volume_burst_vol` = 放量叠加波动放大，`reversal` = 方向取负。

数值后缀是表达式中最关键的窗口（60 日 / 10 日），与项目既有命名（`..._60d`、`..._252d`）一致。
挖掘侧的中文标签（原8号、原2号、本轮1号）保留在登记表的“挖掘编号”列与 `exported.py` 的
`description` 字段里，两边可以互查。

## 数据契约

`signals.parquet` 必需列：`trading_date`（信息日 T，收盘）、`instrument`（品种代码）、
`raw_factor`、`signal`（已定向、已按 scale 缩放并截断到 [−1, 1]）、`factor_name`。
`definition.json` 提供 `name`、`fitted.direction`、`fitted.scale`、表达式树。

`china_cta/factors/exported.py` 在加载时校验：

1. 目录与 `signals.parquet` 存在；
2. 必需列齐全、`(trading_date, instrument)` 不重复、`|signal| ≤ 1`；
3. 若存在 `definition.json`，其 `name`/`direction`/`scale` 必须与登记表一致（防止导出包被换掉）。

## 与四因子一起使用时

* 组合权重等权（N 个 sleeve 各 1/N）；
* 信号按信息日 T 记录，原生账户在 T+1 的开盘竞价成交（`next_trading_day`）；
* 导出包覆盖 35 个品种，进入组合前与项目 `universe` 做同样的 PIT 连接，只保留项目可定价的 30 个；
* 结果写进 `config.json` 的 `sleeves`、`sleeve_weights`、`exported_package`、`exported_sleeves`。
