# 22 因子 CTA Alpha：在本项目中的实现与回测

来源：[quantskills/skill-futures-cta-alpha](https://github.com/quantskills/skill-futures-cta-alpha)，
`references/factor-catalog.md` 的 22 个因子设计。本文件记录这些设计如何映射到
`china-cta` 的五列因子契约、RQData 数据、固定 30 商品池和 Fast Research Backtest，
以及哪些设计因数据不可得而没有计算。

这不是对原仓库的移植：原仓库面向 Pandadata，本项目只复用**因子定义**，数据、PIT
口径、回测和成本全部沿用本项目既有设计。

## 1. 接口与口径

| 项 | 本项目的做法 |
|---|---|
| 输出 | `trading_date, instrument, factor_name, raw_factor, signal` |
| `signal` | `clip(raw_factor / signal_scale, -1, 1)`，不是仓位 |
| Universe | 固定 30 商品池 + 每日 PIT eligible 检查（上市 60 日、成交量/持仓量 ≥1000） |
| 价格 | 趋势/波动/反转用 `pre + prev_close_ratio` 主力连续收盘价；carry/期限用未复权真实合约收盘价 |
| 时点 | `t` 收盘后信号，`execution_lag=1`，最早 `t+1` 执行 |
| 回测 | `run_fast_research_backtest`，横截面等权、收盘到收盘、1bp 换手成本代理 |
| 区间 | 2016-01-04 至 2025-12-31 |
| 性质 | research-only；不是 NAV，不含真实手续费、保证金、整数手数和冲击成本 |

## 2. 数据映射

| 输入 | RQData 来源 | 覆盖 |
|---|---|---|
| 连续 close/high/low/volume/OI | `futures.get_dominant_price(rule=0, rank=1, adjust_type='pre', adjust_method='prev_close_ratio')` | 30 品种，64,842 行 |
| 真实合约 close/OI/到期日 | `get_bars` + instrument master（`load_contract_history`） | 30 品种，707,431 行 |
| 主力映射 | `futures.get_dominant(rule=0, rank=1)` | 30 品种，64,842 行 |
| 注册仓单 | `futures.get_warehouse_stocks().on_warrant` | 30 品种，64,558 行 |
| 会员持仓 | `futures.get_member_rank(rank_by='long'/'short')`，前 20 席 | 29 品种（SC 无数据），2,499,718 行 |

四个设计因缺少对应数据系列**不计算**：

| 因子 | 原因 |
|---|---|
| `basis_mom_20` | RQData `get_basis` 只覆盖股指期货；30 个商品没有统一现货序列，无法构造 `(现货-近月)/现货` |
| `inventory_mom_20` | RQData 只提供注册仓单，没有独立的社会库存/交易所库存序列；不能和 `receipt_mom_20` 共用同一份数据 |
| `ls_ratio_z` | 没有散户多空比；会员持仓不能替代散户情绪 |
| `spot_profit_z` | 没有覆盖 30 个品种的现货加工利润序列 |

## 3. 22 因子清单

族：A 时序动量、B 截面动量、C Carry/展期、D 期限结构、E 持仓/情绪、F 库存/仓单、
G 波动/反转。

| # | factor_name | 族 | 公式 | 数据 | 可算 | scale |
|---|---|---|---|---|---|---|
| 1 | `tsmom_252` | A | `P_t/P_{t-252}-1` | close | ✅ | 0.20 |
| 2 | `tsmom_252_21` | A | `P_{t-21}/P_{t-252}-1` | close | ✅ | 0.20 |
| 3 | `tsmom_63` | A | `P_t/P_{t-63}-1` | close | ✅ | 0.20 |
| 4 | `breakout_55` | A | `clip((P-mid)/(0.5(HH55-LL55)),-1,1)` | close/high/low | ✅ | 1.00 |
| 5 | `ema_xover_20_100` | A | `(EMA20-EMA100)/(HV20·P)` | close | ✅ | 0.50 |
| 6 | `xsmom_252_21` | B | 当日合格品种内对 12-1 收益排名 | close | ✅ | 1.00 |
| 7 | `xsmom_63` | B | 当日合格品种内对 3 月收益排名 | close | ✅ | 1.00 |
| 8 | `carry_ann` | C | `(Pn/Pf-1)·365/(Df-Dn)` | 近/次月真实合约 | ✅ | 0.20 |
| 9 | `roll_return_63` | C | 63 日换月日 `(P_old/P_new-1)` 累计 | 主力映射+真实合约 | ✅ | 0.05 |
| 10 | `basis_mom_20` | C | `basis_t-basis_{t-20}` | 现货 | ❌ | 0.20 |
| 11 | `vol_scaled_carry` | C | `carry_ann/HV20` | carry+close | ✅ | 0.50 |
| 12 | `ts_slope` | D | `ln(Pf/Pn)/(Df-Dn)` | 近/次月真实合约 | ✅ | 0.0005 |
| 13 | `ts_curvature` | D | `(P3-2P2+P1)/P2` | 三个最近真实合约 | ✅ | 0.05 |
| 14 | `oi_price_confirm_20` | E | `sign(P_t-P_{t-20})·ln(OI_t/OI_{t-20})` | close/OI | ✅ | 0.20 |
| 15 | `broker_net_chg_5` | E | `Δ(前20席净多,5日)/OI_t` | 会员持仓+OI | ✅ | 0.02 |
| 16 | `ls_ratio_z` | E | 散户多空比 60 日 z-score | 散户多空比 | ❌ | 1.00 |
| 17 | `virtual_ratio_chg` | E | `Δ(OI/成交量,20日)` | OI/volume | ✅（代理） | 0.20 |
| 18 | `inventory_mom_20` | F | `ln(库存_t/库存_{t-20})` | 库存 | ❌ | 0.20 |
| 19 | `receipt_mom_20` | F | `ln(仓单_t/仓单_{t-20})` | 仓单 | ✅ | 0.20 |
| 20 | `spot_profit_z` | F | 现货加工利润 60 日 z-score | 加工利润 | ❌ | 1.00 |
| 21 | `lowvol` | G | `-HV20` | close | ✅ | 0.20 |
| 22 | `st_reversal_5` | G | `-(P_t/P_{t-5}-1)` | close | ✅ | 0.05 |

## 4. 实现中的明确选择与偏离

1. **截面动量用排名而非 z-score**。原仓库对当日收益做 cross-sectional z-score；本项目
   已有 `historical_skewness_cs` 的截面排名惯例，且排名对异常值更稳健。`xsmom_*` 的
   `raw_factor` 是当日合格品种内的排名映射到 `[-1, 1]`，`signal_scale=1`。
2. **`ts_curvature` 除以 P2**。原公式是价格水平的三点曲率，跨品种不可比（AU 与 RB 价格
   量级差两个数量级）。本项目输出 `(P3-2P2+P1)/P2` 的无量纲曲率；这是唯一改变原公式
   代数形式的因子，已在因子 metadata 记录。
3. **`roll_return_63` 的符号**。原仓库 `build_continuous.py` 在换月日算
   `P_new/P_old-1`，但它的 `continuous-contract.md` 要求展期收益与 `carry_ann` 同号
   （backwardation 为正）。本项目按经济定义算 `P_old/P_new-1`，与 carry 同号；metadata
   里的 `reference_deviation` 记录了这一处修正。
4. **Carry 用最近的两个真实合约**，不是"近月/主力"。原目录写 `Pn/Pf` 为近月/次月；
   本项目按 `days_to_maturity > 30` 选最近两个合约，gap 必须为正。这样 `carry_ann` 与
   `ts_slope` 是同一对合约的两种表达（`ts_slope ≈ -carry_ann`），可以直接互相校验。
5. **`virtual_ratio_chg` 是代理**。RQData 没有直接"虚实盘比"字段，本项目用
   `持仓量/成交量` 的标准解释，metadata 标记 `proxy=True`。它不是原仓库的原始字段。
6. **`broker_net_chg_5` 用前 20 席**。多头取前 20 名多头席位持仓之和，空头取前 20 名
   空头席位之和，净多变化除以当日全曲线总 OI。SC 没有会员排名数据，因子覆盖 29 个品种。
7. **`signal_scale` 是研究选择**，不是优化结果。所有因子用同一个 `clip(raw/scale)` 映射；
   scale 由经济量级先验确定（例如 20% 年化 carry、5% 的 5 日反转），没有按回测收益调参。
8. **价格字段统一为 `close`**。这与本项目 2026-10 的全局口径一致；carry/期限使用未复权
   真实合约收盘价，趋势/波动使用比例复权连续收盘价。

## 5. 回测结果

下表按 Sharpe 排序；年化净收益已扣 1bp 换手成本代理。观测数因因子 warm-up 不同而略有差异。

| # | factor | 族 | 年化净收益 | 年化波动 | Sharpe | 最大回撤 | IC | Rank IC | 平均换手 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `xsmom_252_21` | B | 3.16% | 3.84% | 0.823 | -5.55% | 0.0235 | 0.0284 | 0.050 |
| 2 | `vol_scaled_carry` | C | 3.71% | 4.96% | 0.748 | -10.79% | 0.0095 | 0.0174 | 0.177 |
| 3 | `carry_ann` | C | 3.25% | 4.57% | 0.712 | -11.27% | 0.0083 | 0.0179 | 0.139 |
| 4 | `breakout_55` | A | 4.27% | 6.37% | 0.669 | -8.36% | 0.0156 | 0.0068 | 0.126 |
| 5 | `roll_return_63` | C | 1.88% | 3.61% | 0.522 | -5.81% | 0.0099 | 0.0118 | 0.012 |
| 6 | `ema_xover_20_100` | A | 2.28% | 4.68% | 0.486 | -8.89% | 0.0181 | 0.0158 | 0.023 |
| 7 | `tsmom_252` | A | 3.45% | 7.73% | 0.446 | -14.56% | 0.0226 | 0.0253 | 0.045 |
| 8 | `tsmom_252_21` | A | 3.25% | 7.55% | 0.431 | -13.99% | 0.0223 | 0.0284 | 0.047 |
| 9 | `tsmom_63` | A | 1.50% | 6.86% | 0.219 | -13.88% | 0.0080 | 0.0042 | 0.066 |
| 10 | `virtual_ratio_chg` | E | 1.31% | 6.53% | 0.201 | -12.54% | -0.0035 | -0.0045 | 0.590 |
| 11 | `xsmom_63` | B | 0.32% | 4.17% | 0.076 | -11.18% | 0.0079 | 0.0042 | 0.095 |
| 12 | `ts_curvature` | D | 0.17% | 2.47% | 0.070 | -6.25% | 0.0010 | 0.0025 | 0.119 |
| 13 | `oi_price_confirm_20` | E | 0.22% | 4.77% | 0.046 | -14.66% | 0.0030 | 0.0003 | 0.271 |
| 14 | `broker_net_chg_5` | E | -0.81% | 4.00% | -0.202 | -20.49% | 0.0024 | -0.0026 | 0.404 |
| 15 | `receipt_mom_20` | F | -1.51% | 4.78% | -0.317 | -20.61% | -0.0023 | -0.0045 | 0.081 |
| 16 | `st_reversal_5` | G | -2.60% | 6.34% | -0.409 | -29.06% | -0.0017 | 0.0084 | 0.254 |
| 17 | `lowvol` | G | -7.01% | 12.34% | -0.568 | -57.01% | -0.0066 | -0.0043 | 0.015 |
| 18 | `ts_slope` | D | -4.14% | 4.68% | -0.886 | -35.94% | -0.0084 | -0.0179 | 0.144 |

四个不可计算因子不进入上表：`basis_mom_20`、`inventory_mom_20`、`ls_ratio_z`、`spot_profit_z`。

按 0.65 阈值，22 个里 **4 个合格**（`xsmom_252_21`、`breakout_55`、`carry_ann`、
`vol_scaled_carry`）、14 个不合格、4 个不可得。完整分类见
[`docs/factor_classification.md`](factor_classification.md)。

### 主要发现

1. **本区间最强的三个信号是 12-1 截面动量、波动缩放 carry、carry 本身**。
   `xsmom_252_21`（Sharpe 0.823，回撤仅 -5.55%，换手 0.050）明显好于 3 月截面动量
   `xsmom_63`（0.076）；`vol_scaled_carry`（0.748）和 `carry_ann`（0.712）都指向
   **backwardation 品种跑赢、contango 品种跑输**。
2. **Carry 族内部互相印证**。`carry_ann`（近/次月价格比）与 `roll_return_63`（换月日
   `old/new-1`）用了两套独立构造，Sharpe 分别为 +0.712 和 +0.522，符号与量级一致；
   `ts_slope` 是 carry 的镜像，Sharpe -0.886。四者共同说明本样本的期限结构溢价方向是
   “做多 backwardation”，而不是原仓库 2023–2026 新浪样本里的“做多 contango”。
3. **与原仓库的中国证据大面积反向**。原仓库（2018–2026、新浪单合约、30 流动主力）说
   1–3 月动量是强反转、低波动/短期反转/12-1 为正向、carry 与全球相反；本样本
   （2016–2025、固定 30 品种、RQData 比例复权连续价/真实合约曲线）得到的却是：
   `tsmom_63`/`ema_xover`/`breakout_55` 为正，`lowvol`/`st_reversal_5` 为负，
   `carry_ann` 为正、`ts_slope` 为负。只有 `xsmom_252_21` 的正向、
   `oi_price_confirm_20` 的接近 0 与原仓库的实测一致；`receipt_mom_20` 的 IC− 与原仓库
   的**未实测先验**一致。
4. **这不等于“原仓库错了”**。两个样本的起点、品种池、连续价构造、carry 合约选择都不同；
   原仓库自己也说明其 t 值用 iid 公式高估，HAC 订正后多数因子不再显著。更稳妥的结论是：
   **这些方向在不同样本/品种池上不稳定，方向必须按自己的 universe 和区间重新验证**。
5. **低波动和短期反转在本样本是反向的**。`lowvol` 的 Sharpe -0.568、回撤 -57.0%，
   说明 2016–2025 的高波动品种整体跑赢；`st_reversal_5` -0.409，说明 5 日尺度更接近
   延续而非反转。两者换手不高，但方向与常见先验相反，不能直接拿去做多空。
6. **持仓/情绪类整体偏弱**。`broker_net_chg_5` 为 -0.202（前 20 席净多增加反而对应
   低收益，偏拥挤反向），`virtual_ratio_chg` 虽为正但 IC 为负、换手 0.59，成本吞掉
   大部分收益；`receipt_mom_20` -0.317，方向符合“仓单增加偏空”的先验，但覆盖只有
   45,560 个观测（仓单为零/缺失的日期保留 NA）。

## 6. 解读与限制

- **固定 30 品种池有事后选择偏差**：名单由 2026-08 的流动性筛出，用于 2016-2025 的
  回测；它固定的是品种允许集合，不是每个历史日期都持有 30 个品种。
- **样本与仓库证据不同**：原仓库的 IC 证据主要是 2018-2026、30 个流动主力、新浪连续价；
  本表是 2016-2025、固定 30 品种、RQData 比例复权连续价和真实合约曲线。方向不一致是
  正常的，不能直接说"推翻了原仓库"。
- **单因子、等权、1bp**：没有组合、没有风险预算、没有保证金/整数手数/冲击成本。
  Sharpe 是 `年化净信号收益/年化波动`，不是标准 NAV Sharpe。
- **`signal_scale` 会改变 Sharpe 的绝对水平**。同一 raw 排序在不同 scale 下会产生不同的
  截面权重；本表只用于**同口径横向比较**，不是优化后的业绩。组合前应重新做波动/风险
  归一，而不是直接相加 `signal`。
- **IC 与可交易收益是两件事**：低波动因子可能 IC 很高但多空价差太小；carry 类因子的
  换手和展期成本也可能吞掉收益。
- **数据覆盖**：`broker_net_chg_5` 缺 SC；`receipt_mom_20` 有约 13% 的仓单为零/缺失，
  这些日期保留 `NA`，不填充。

## 7. 复现

```powershell
# 1) 拉取并缓存输入（首次约数分钟；已存在时跳过）
& "$env:USERPROFILE\miniconda3\envs\cta\python.exe" scripts\fetch_cta_alpha_inputs.py --refresh

# 2) 回测全部 18 个可计算因子
& "$env:USERPROFILE\miniconda3\envs\cta\python.exe" scripts\cta_alpha22_test.py --overwrite

# 3) 只跑指定因子
& "$env:USERPROFILE\miniconda3\envs\cta\python.exe" scripts\cta_alpha22_test.py --only tsmom_63 --overwrite
```

结果目录：合格因子在 `results/qualified/<factor>_2016_2025_v1/`，不合格因子在
`results/unqualified/<factor>_2016_2025_v1/`（`config.json`、`overall.csv`、
`by_year.csv`、`by_instrument.csv`）。每个分类目录另有 `summary.csv`。
每份都是独立单因子回测，没有组合净值；`results/cta_alpha22_summary.csv` 只是
18 份 `overall.csv` 的索引，带 `classification` / `result_path` 列；
清单：`results/cta_alpha22_manifest.json`；规格：`results/cta_alpha22_specs.csv`。
