# 原生账户口径清单（以本地 china-cta 为基准）

> 用途：本地项目把所有"对外结果层"改成 RQAlpha 原生期货账户后，把口径固定下来，
> 供另一台电脑逐条对齐。**本文只写口径，不写策略研究结论。**

## 0. 一句话结论

同一个策略（四因子、各 25% 资金、60 日滚动 20% 波动目标），研究代理层给出
**夏普 1.584 / 年化波动 19.2%**，换成 5000 万原生期货账户后只能做到
**夏普 1.350 / 实现波动 20.0%**：研究层的 1.58 到原生账户的 1.35，差的不是信号，
而是整数手数、50% 保证金预算、25% 成交量上限、1 跳滑点和逐笔手续费。
保证金预算按**当日权益**的 50% 计算（2026-11 修正，此前误用初始资金 5000 万）。

## 1. 结果层：RQAlpha 原生期货账户

| 项目 | 本地取值 |
| --- | --- |
| 引擎 | `rqalpha` 6.3.0（纯 Python；`rqalpha_plus` 只需要它的 `run_func`，本地用 `from rqalpha import run_func` 代替，避免 Windows 应用控制策略拦截未签名的 `daybar*.pyd`） |
| 账户 | `base.accounts = {"future": 50_000_000}`，单账户、日频 |
| 撮合 | `matching_type="current_bar"`、`execution_timing` 通过在 `open_auction` 回调里下单实现"T 日收盘信号 → T+1 集合竞价开盘成交" |
| 代码 | `china_cta/formal_backtest/native_account.py`、`scripts/70_native_backtest.py` |

## 2. 资金与手数

| 口径 | 取值 | 实现位置 |
| --- | --- | --- |
| 初始资金 C0 | **50,000,000**（初始入金，之后账户权益按市值复利） | `NativeAccountConfig.initial_capital` |
| 名义敞口 | `E(t) × 杠杆 × Σ_sleeve(0.25 × signal / 当日该 sleeve 品种数)`，`E(t)` = 当日开盘前的账户权益 | `build_target_exposures` |
| 手数 | 每日开盘用**当次权益**算：`q = trunc(E(t) × 敞口 / (结算价 × 合约乘数))`，**朝零取整** | `plan_day_targets` |
| 保证金预算 | 组合保证金 ≤ **50% × E(t)**；超出时全部手数按 `budget/total_margin` **同比例缩**后再 `trunc` | `plan_day_targets` |
| 结算价口径 | 用信号日 T 的真实合约 `settlement` 算手数与保证金，T+1 开盘成交、收盘盯市 | 同上 |
| 保证金基准 | `margin_basis="live_equity"`。2026-11 之前误用固定 `50% × C0`，权益复利后敞口相对缩水，实现波动从 2016 的 25% 一路衰减到 2023 的 5.3%；改为按权益后波动稳定在 17%–24% | `NativeAccountConfig.margin_basis` |

## 3. 滑点：1 跳

`mod.sys_simulation = {"slippage_model": "TickSizeSlippage", "slippage": 1}`
——`TickSizeSlippage` 的 `slippage` 参数就是跳数，`tick_size` 取自 bundle 的 instrument，
买价 `+1 tick`、卖价 `-1 tick`，再被涨跌停约束。

**注意（本机实现的关键坑）**：`rqalpha` 的 `BaseMatcher._get_execution_price` 在
`open_auction=True` 时直接返回 deal price，**完全跳过滑点模型**；也就是说只配
`TickSizeSlippage` 时，开盘竞价成交价就是裸开盘价，1 跳滑点不生效。
本地做法是在 `native_account._install_opening_slippage()` 里替换
`DefaultBarMatcher._open_auction_deal_price_decider`，把 1 跳直接烘进 deal price
（tick_size 由 bundle 的 `future_info.json` 按品种传入，不依赖 env 查询）。
验证：`attribution_reconciliation.csv` 的残差从"恰好等于滑点金额"变为 −1.2e-05 元。
另一台电脑若用原生 `rqalpha_plus` + `_install_opening_slippage` 同样要打这个补丁；
忘了打的话，报告的夏普会虚高约 0.12（本机实测 pass2 由 1.3532 虚高到 1.4706）。

## 4. 成本：原生逐笔手续费

| 口径 | 取值 |
| --- | --- |
| 手续费 | `mod.sys_transaction_cost.futures_commission_multiplier = 1`（×1 交易所费率） |
| 费率来源 | bundle 的 `future_info.json`：`commission_type`（by_volume/by_money）、`open_commission_ratio`、`close_commission_ratio`、`close_commission_today_ratio` |
| 保证金率 | 同一文件的 `margin_rate`，`base.margin_multiplier = 1` |
| 实测 | 2016-2026 共 2593 个交易日、67,282 笔成交，**累计手续费 745 万元 ≈ 每年 72 万 ≈ 年化 1.45% × C0** |

## 5. 撮合约束

| 约束 | 取值 |
| --- | --- |
| 成交量上限 | `volume_limit=True`、`volume_percent=0.25`（上一已完成交易日成交量的 25%） |
| 涨跌停 | `price_limit=True`、`inactive_limit=True` |
| 强平 | `forced_liquidation=True` |
| 结算价类型 | `futures_settlement_price_type="close"` |

## 6. 未改动的部分（策略本体，别动）

1. 四个 sleeve 与最优参数（`results/tuning/qualified4_300/*/best_params.json`）。
2. 每个 sleeve 占 25% 资金、sleeve 内按当日品种数等权分摊。
3. 60 日滚动波动目标 20%、杠杆上限 10 倍、无前视（`shift(1)`）。
4. 因子信号本身（`signal = clip(raw_factor / signal_scale, -1, 1)`）。

## 7. 记账与统计差异（重要）

- 研究代理层：日收益 = 开盘(t+1) → 开盘(t+2) 的等权品种收益。
- 原生账户：按 **结算价逐日盯市**，`total_value` 的日变化 = 结算价对结算价。
  两者相差"一天"的相位（同一笔 P&L 记在不同日期），因此**不要按日对齐两条曲线**，
  只能比较区间累计与夏普；本地实测两条日收益序列的相关系数在 `shift(-1)` 下为 0.82。
- 夏普：`mean(r)/std(r, ddof=1) × sqrt(252)`，无风险利率 0；年化收益 `(1+总收益)^(252/N)-1`；
  最大回撤含区间前一日基准。

## 8. 实测结果（本地，2016-01-04..2026-09-04，2593 个交易日）

| 版本 | 夏普 | 年化 | 波动 | 最大回撤 |
| --- | --- | --- | --- | --- |
| 原生 pass1（研究杠杆原样进入账户） | 1.3500 | 26.31% | 18.59% | −25.73% |
| **原生 pass2（波动校准 ×1.076）** | **1.3498** | **28.39%** | **20.01%** | **−27.45%** |

pass2 的三段（用户口径）：

| 区间 | 交易日 | 夏普 | 年化 | 波动 | 最大回撤 |
| --- | --- | --- | --- | --- | --- |
| 训练 2016-01-04..2021-12-31 | 1460 | 1.9125 | 42.38% | 19.47% | −18.91% |
| 验证 2022-01-04..2024-12-31 | 725 | 0.3989 | 5.94% | 18.98% | −27.45% |
| 测试 2025-01-02..2026-09-04 | 406 | 1.0831 | 25.31% | 23.36% | −25.81% |

单因子账户（全区间夏普 / 训练 / 验证 / 测试）：
`fixed_maturity_carry_90_180d` 1.0950 / 1.3655 / 0.4841 / 0.8841、
`xsmom_252_21` 0.9703 / 1.2363 / 0.0336 / 1.3715、
`historical_skewness_252d` 0.8156 / 1.1329 / 0.4535 / 0.1776、
`oi_participation_trend_60d` 0.7087 / 0.8353 / 0.4678 / 0.5970。
（这一组单因子数字来自固定 C0 的旧跑法，保证金口径修正后尚未重跑单因子账户；
组合层数字见上表。）

注意：原生路径的可回测终点由 RQAlpha bundle 决定，本机 bundle 止于 **2026-09-04**（研究输入止于 2026-10-30），所以原生结果比研究结果短两个月。

记账：本地配置 `futures_settlement_price_type="close"`，账户按**收盘价**盯市；
归因同样用收盘价，`attribution_reconciliation.csv` 的残差是 −1.2e-05 元（约 2e-13×C0）。
第 5 节的"结算价"只用于**算手数和保证金**，不用于盯市。

约束实测（按当日权益）：`gross/equity` 中位 2.9、`margin/equity` 中位 26%–37%
（分年最高 47.9%，**从未触及 50% 上限**）、每日持仓 27 个合约。
保证金预算现在是"上限而非约束"——敞口由研究层杠杆决定，保证金占用是结果。

→ 实现波动 **20.01%**，与 20% 目标一致（此前固定 C0 的跑法因为敞口相对缩水只能做到 13.19%）。

## 8.1 摩擦成本分解（原生实测，2016-01-04..2026-09-04）

| 项目 | 累计 | 占 C0 | 每年（10.29 年） |
| --- | --- | --- | --- |
| 毛收益 | 70,533 万元 | 1,410.7% | 约 43% 的起始权益 |
| 手续费（逐笔原生） | 2,382 万元 | 47.6% | — |
| 1 跳滑点 | 7,712 万元 | 154.2% | — |
| **净收益** | 60,433 万元 | 1,208.7% | 28.39%（CAGR） |

摩擦合计 10,094 万元 = **毛收益的 14.3%**；
换算成年化约为**当年平均权益的 1.8%（手续费）+ 5.8%（滑点）**。
主要原因不是手续费贵，而是**日频全量再平衡 + 3 倍左右的名义敞口**把年换手推到很高，
而滑点按每笔成交的名义额 × 1 跳计价。
若想提高净收益，最有效的手段是降换手（隔日/三日再平衡、加信号死区），
但这属于策略改动，本次未做。

逐年明细见 `by_year_by_book.csv`，分品种见 `by_instrument_by_book.csv`，
逐笔成交见 `trades.csv`（67k+ 笔，含手续费与成交价）。



## 8.2 保证金口径修正的影响（2026-11）

| 年度 | 固定 50M 的波动 | 按权益的波动 | 固定 50M 夏普 | 按权益夏普 |
| --- | --- | --- | --- | --- |
| 2016 | 25.4% | 12.9% | 1.01 | 0.92 |
| 2019 | 10.0% | 18.1% | 1.36 | 1.62 |
| 2022 | 8.3% | 20.7% | 1.09 | 1.04 |
| 2023 | 5.3% | 16.9% | 0.22 | 0.11 |
| 2024 | 6.3% | 19.1% | 0.06 | −0.02 |
| 2025 | 7.3% | 24.1% | 1.24 | 1.36 |

全区间：倍率 5.74 → **13.09**，年化 18.51% → **28.39%**，夏普 1.3532 → **1.3498**，
最大回撤 −15.05% → **−27.45%**。夏普基本不变而收益与回撤同时放大，符合"同一策略、
更高且稳定的敞口"的预期。对比图见 `results/final_4f_native_vol20_dyn/margin_basis_comparison.png`。

## 9. 复现命令

```bash
# 1) 研究输入（需要 RQData；本机用 WSL）
bash scripts/11_setup_linux_env.sh          # 一次性
wsl_fetch.sh scripts/10_fetch_research_inputs.py --start 2016-01-01 --end 2026-11-01 --refresh

# 2) 参数调优（可选，结果已在 results/tuning/qualified4_300）
python scripts/30_tune_factors.py --trials 300

# 3) 原生账户回测
python scripts/70_native_backtest.py \
  --start 2016-01-04 --end 2026-10-30 \
  --capital 50000000 --margin-budget 0.50 \
  --slippage-ticks 1 --volume-percent 0.25 \
  --vol-target 0.20 --out-dir results/final_4f_native_vol20
```

产物：`daily_equity.csv`、`daily_equity_pass1.csv`、`trades.csv`、`target_positions.csv`、
`daily_risk.csv`、`vol_calibration.csv`、`research_overlay.csv`、`config.json`。

## 10. 另一台电脑需要改的地方（逐条）

1. 结果层换成 RQAlpha 原生期货账户，`accounts={"future": 5e7}`，日频、`current_bar` 撮合。
2. 成交时点：T 日收盘出信号，T+1 **集合竞价开盘**成交（`open_auction` 回调里 `order_to`）。
3. 资金口径：C0 固定 5000 万，不随权益复利。
4. 手数：`trunc(名义 / (结算价 × 乘数))`，朝零取整。
5. 保证金：组合保证金 ≤ 50% × C0，超出同比例缩手数（不是拒绝下单）。
6. 滑点：1 跳（`TickSizeSlippage(1)`，买加卖减，受涨跌停约束）。
7. 成本：原生逐笔手续费 ×1，费率与保证金率都取 bundle 的 `future_info.json`，
   `margin_multiplier=1`、`futures_commission_multiplier=1`。
8. 撮合约束：成交量上限 25%、涨跌停、强平、`futures_settlement_price_type="close"`。
9. 波动目标：20%（60 日窗、`shift(1)`、上限 10 倍），并**在原生层重新校准一次**
   （本地校准因子 2.370，因为原生摩擦会让实现波动低于研究代理）。
10. 统计口径：结算价盯市、`std(ddof=1)`、`× sqrt(252)`、回撤含前一日基准。

## 11. 已知偏差

- 主力合约按当日持仓量最大选取，与 RQData 的平滑规则在换月日有约 3.5% 的差异。
- 复盘用 `settlement` 定价，若对方用 `close` 盯市，日收益会有细微差异。
- 55 天以内的波动校准样本不足，前 60 个交易日杠杆按 1 倍处理。
