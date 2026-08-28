# 国内期货 CTA Research Framework

本项目以 Ricequant RQSDK 为基础设施，目标链路是：

`RQData → Alpha → Portfolio/Risk → Target Position → RQAlpha Plus → P&L/NAV → Validation`

Ricequant 负责行情与合约数据，以及正式回测中的订单、撮合、持仓、手续费、保证金、逐日盯市、账户和 NAV。本项目只实现研究逻辑：因子、预测、组合与风险分配、目标仓位、快速研究回测，以及与正式回测结果的验证和归因。

不实现自研通用撮合、期货账户、保证金记账、完整 OMS、Broker API、数据库服务、Web 服务、Docker 或分布式基础设施。

## 当前状态

- 当前增量冻结版本：`backtest-v1.1.0`。它以 `backtest-v1.0.1` 为核心基线，新增 OI-confirmed Trend、三因子教学脚本和关键中文业务注释；不改变 Phase 1–7 的数据、Portfolio、Formal 或 Golden 接口。
- Phase 0 已完成：Python 3.11 独立 Conda 环境、RQData 连通性，以及 RQAlpha Plus 单合约一手期货冒烟回测均已验证。
- M1 架构清理已完成：旧的 Contract Master 快照、Contract Selector、Parquet 存储和相关脚本/测试已从源码中移除。
- Phase 1 已完成：六个最小 RQData 查询接口、标准 DataFrame schema 和本地 Parquet cache 已验证。
- Phase 2 已完成：point-in-time research universe、真实合约/curve snapshot、官方 dominant/roll map，以及 Signal/Trade/Curve Contract 角色已明确。
- Phase 3 已完成：统一 factor table，以及可人工复算的 60 日 Trend 和真实 near/main 合约 Carry baseline 已验证。
- Phase 4 已完成：显式 execution lag 的 Fast Research Backtest、基础 diagnostics、year/instrument breakdown、薄 parameter surface 和本地可复现摘要已验证。
- Phase 5 已完成：滚动波动率、固定策略聚合、透明约束、diagonal risk scale、真实 Trade Contract、整数目标手数、margin sanity 和 capacity diagnostics 已验证。
- Phase 6 已完成：Phase 5 Target Position 可由薄 adapter 直接送入 RQAlpha Plus，日频 `order_to`、原生期货账户/撮合/费用/NAV、结果持久化和轻量 loader 已验证。
- Target Position 之前的投资决策属于本项目；Target Position 之后的订单、成交、正式账户和 NAV 以 RQAlpha 原生结果为准。
- `data/` 中的旧快照和本地 RQAlpha 结果仅作为本机验证资料保留，已整体排除在 Git 之外，不再是新架构的依赖。

当前最小目录：

```text
china_cta/
  data/
    rqdata_adapter.py  # 当前阶段所需的薄 RQData 查询接口
    cache.py           # 参数哈希 Parquet + JSON metadata
    contracts.py       # Phase 2 合约、universe、curve 与 roll 语义
  factors/
    schema.py       # 统一 factor table 与极简 signal scaling
    trend.py        # 60 交易期连续价 Trend baseline
    carry.py        # 真实 near/main 合约 Carry baseline
    oi_confirmed_trend.py  # 价格趋势 × 正向 OI 变化的教学研究因子
  research/
    fast_backtest.py  # 向量化 signal/forward-return 对齐与研究诊断
  portfolio/
    volatility.py   # PIT rolling close-to-close volatility
    allocation.py   # 约束、diagonal risk、真实合约与整数目标手数
  formal_backtest/
    adapter.py     # Target schedule → run_func / order_to
    results.py     # RQAlpha 原生结果的轻量读取
  validation/       # 对账、归因和稳健性（后续阶段）
scripts/
  check_rqdata.py
  smoke_rqalpha_futures.py
  walkthrough_three_factor_pipeline.py  # Trend/Carry/OI → Portfolio → 一个月 Formal 教学链路
tests/
config/
```

## Phase 1 数据接口

`RQDataAdapter` 只提供当前研究需要的薄查询方法。Phase 1 的六个接口是：

- `get_trading_calendar(start, end)`：官方交易日历。
- `get_future_instruments(date=None)`：指定日期可交易期货及 instrument master 字段。
- `get_instrument_details(ids)`：合约乘数、到期日、交易所、品种、最新静态保证金率和 tick size 等详情；历史保证金仍以 trading parameters 为准。
- `get_bars(ids, start, end, frequency="1d", fields=None)`：真实合约日线或分钟线；不复权。
- `get_dominant_map(symbols, start, end, rule=0, rank=1)`：RQData 主力/次主力实际合约映射。
- `get_trading_parameters(ids, start, end)`：原样保留保证金、手续费和限仓等供应商字段及单位。

Phase 2–3 仅增加三个 RQData 已有能力的薄封装：

- `get_future_contracts(product, date)`：指定历史日期真实、可交易的月份合约，沿用 RQData 到期月排序。
- `get_dominant_price(...)`：官方主力连续行情；只允许用于 Signal/Research，禁止用于现金 P&L、结算或账户估值。
- `get_roll_yield(...)`：官方期货展期收益率；Phase 3 只把 `near_main` 结果用作 Carry 验收基准，不替代本项目保留 near/main 合约明细的计算结果。

日线固定以 `trading_date, order_book_id` 开头。分钟线固定同时保留自然时间 `datetime` 和期货交易日 `trading_date`，不会把夜盘自然日期当作交易日。

默认 cache 目录为项目相对路径 `data/cache/rqdata/`，可通过构造 `RQDataConfig(cache_dir=...)` 或本机环境变量 `CTA_RQDATA_CACHE_DIR` 修改，也可传入 `cache_dir=None` 禁用。每个缓存项由请求参数哈希命名，包含 Parquet 数据以及记录请求参数、UTC 拉取时间和 rqdatac 版本的 JSON metadata；许可证和连接 URI 不会写入缓存。

API 口径以 [RQData 通用 API](https://www.ricequant.com/doc/rqdata/python/generic-api) 和 [RQData 期货 API](https://www.ricequant.com/doc/rqdata/python/futures-mod) 为准。

## Phase 2 合约语义

`china_cta.data.contracts` 使用普通函数和 DataFrame，不建立合约对象图：

- `get_research_universe(adapter, date, ...)`：从 `all_instruments(type="Future", date=date)` 构造历史时点品种池。默认只要求当时存在真实可交易合约；可显式设置最小上市历史、成交量和持仓量阈值。
- `get_contract_snapshot(adapter, product, date)`：保留当时所有真实可交易合约，即使个别合约当天行情字段缺失也不填充。
- `get_curve_snapshot(adapter, product, date)`：从 contract snapshot 选出有明确价格的真实月份合约，按 `maturity_date` 排序。
- `get_dominant_contract(...)` / `get_roll_map(...)`：直接采用 RQData `rule=0, rank=1`，roll map 仅比较相邻交易日映射，不自行平滑 P&L。
- `get_contract_roles(...)`：用 `ContractRoles` 明确区分 Signal Contract、Trade Contract、Curve Contracts。v1 中 Signal 与 Trade 都映射到同一个官方主力真实合约，但字段和用途保持分离。
- `get_signal_continuous_price(...)`：只返回研究连续价，并附 `usage=signal_research_only`、`cash_pnl_allowed=False` metadata。
- `get_trading_parameter_availability()`：标记盘前、盘后和交易所相关字段；盘后手续费字段不得用于当日决策。

Phase 2 DataFrame contracts：

```text
research_universe:
  trading_date, instrument, eligible, reason

contract_snapshot / curve_snapshot:
  trading_date, underlying_symbol, order_book_id, maturity_date,
  days_to_maturity, price, price_field, volume, open_interest,
  dominant_rank, has_bar

roll_map:
  trading_date, underlying_symbol, dominant_order_book_id,
  previous_dominant_order_book_id, changed
```

`price` 明确来自调用参数指定的 `settlement`（默认）或 `close`；不做价格补齐。日线 price/volume/open_interest 和启用后的流动性 universe 均为收盘后数据，只能用于下一决策时点，不能用于当日盘中决策。品种上市历史来自完整 instrument master 中 `listed_date <= trading_date` 的真实合约，不会把未来上市品种放入历史 universe。`instruments()` 的最新 margin/trading hours 等字段不作为历史动态信息；历史 margin、fee、limit 始终查询 `get_trading_parameters`。

## Phase 3 因子语义

原 Phase 3 baseline Trend/Carry 与后续教学因子 OI-confirmed Trend 的内部输入不同，但都输出同一个最小表：

```text
trading_date, instrument, factor_name, raw_factor, signal
```

- `trading_date`：产生该研究信号的信息日/决策日；当前两个 baseline 都使用该日收盘后数据。
- `instrument`：期货品种，例如 `RB`、`CU`、`IF`，不是月份合约。
- `factor_name`：唯一规格名；当前为 `trend_60d` 或 `carry_near_main`。
- `raw_factor`：保持可解释定义的原始统计量。
- `signal`：方向和强度，正值表示 long bias，负值表示 short bias；它不是仓位、手数、风险敞口或预期收益率。

所有 factor table 都先与 Phase 2 的 point-in-time eligible universe 做日期/品种内连接；不为尚未上市或当日不合格品种生成信号，也不为完整 panel 填值。统一的首版映射为：

```text
signal = clip(raw_factor / 0.20, -1, 1)
```

`0.20` 是清晰可配置的默认尺度，不是优化结果。它只统一正负方向和大致强度，不改变两个 raw factor 的经济定义。

### Trend baseline

`trend_60d` 使用 RQData 官方主力连续收盘价，固定 `adjust_type="pre"`、`adjust_method="prev_close_ratio"`：

```text
raw_factor(t) = adjusted_close(t) / adjusted_close(t-60) - 1
```

这里的 60 是价格序列中的 60 个交易期差，因此需要 61 个完整且为正的观测。窗口不足或窗口内有缺失/非正价格时保留 `NA`，不插值、不前向填充。连续价仅用于 Signal/Research，不能用于现金 P&L、账户估值或真实成交价格；比例复权用于降低主力切换造成的机械价格跳跃。

### Carry baseline

`carry_near_main` 只使用同一历史日期实际存在的真实月份合约及其 `settlement`：

- `far/main`：RQData `rule=0, rank=1` 主力真实合约。
- `near`：到期日在主力之前、尚未到期的最早真实合约。
- `maturity_gap_days`：两个实际到期日之间的自然日数。

```text
raw_factor = (near_settlement / main_settlement - 1)
             * 365 / maturity_gap_days
```

正值表示近月相对主力远月更贵，对应 backwardation/long bias。若没有唯一主力、没有合格 near、到期日差异常、价格缺失或价格非正，则保留 `NA`；不外推、不拟合 curve，也不使用连续价格。该定义与 RQData 商品期货 `get_roll_yield(type="near_main", rule=0)` 的年化口径做真实数据交叉验证；股指期货不强行套用此商品 Carry baseline。

### OI-confirmed Trend 教学因子

`oi_confirmed_trend_20d` 使用 ratio-adjusted 主力连续收盘价和主力连续 OI：

```text
price_return = close(t) / close(t-20) - 1
oi_change = OI(t) / OI(t-20) - 1
raw_factor = price_return * max(oi_change, 0)
signal = clip(raw_factor / 0.02, -1, 1)
```

OI 只确认趋势强度：持仓下降把确认降为 0，不反转价格方向。若 20 日窗口内 RQData rule-0/rank-1 主力发生切换，因子返回 `NA`，避免把合约迁移造成的 OI 跳变误认为资金流。该因子用于展示新 Alpha 如何复用五列接口和同一 Portfolio/Formal 链路，不改变原 Trend/Carry baseline。

### 可用时点

两个 baseline 的 metadata 都明确：`information_date=trading_date`、`signal_available_at=after_close_of_trading_date`、`earliest_trade_at=next_trading_session`。即 `close(t)` 或 `settlement(t)` 产生的信号不能假设在同一个收盘价成交。Phase 3 不模拟交易，也不把 signal 转换为 position。

## Phase 4 Fast Research Backtest

`china_cta.research.fast_backtest` 直接接受 Phase 3 五列 factor table、Phase 2 的 ratio-adjusted research continuous price 和同日期 PIT universe。Trend 与 Carry 使用同一个函数，不需要在 backtest 中加入 factor-specific 分支。

### 时间对齐与 Research Return

`execution_lag` 是必填正整数，不存在隐藏默认值。v1 固定一段连续价收益期：

```text
signal_date = t（收盘后信号才可用）
execution_lag = 1
return_start = t 后第 1 个连续价观测日
return_end = return_start 后第 1 个连续价观测日
realization_date = return_end

research_forward_return = close(return_end) / close(return_start) - 1
research_exposure = signal
gross_signal_return = research_exposure * research_forward_return
```

因此 lag=1 不会把 signal(t) 乘到 `close(t-1) → close(t)` 或假设在 `close(t)` 成交。连续价必须带有 `usage=signal_research_only`、`cash_pnl_allowed=False`、`adjust_type=pre`、`adjust_method=prev_close_ratio`；结果继续标记 `research_only=True`，不得解释为真实合约现金 P&L。缺失 signal、price 或未来 return 不填充，保留 `NA`。

明细输出：

```text
signal_date, instrument, factor_name, raw_factor, signal,
execution_lag, return_start, return_end, realization_date,
research_exposure, research_forward_return, gross_signal_return,
turnover_proxy, cost_rate, rough_cost, net_signal_return
```

### Turnover、Cost 与 Metrics

Research turnover proxy 定义为同品种相邻研究 exposure 的绝对变化，首次 exposure 从 0 开始：

```text
turnover_proxy = abs(exposure_t - exposure_t_minus_1)
rough_cost = turnover_proxy * cost_rate
```

`cost_rate` 默认为 0，可显式设置；它只是 sensitivity assumption，不代表交易所/券商手续费、平今规则或 market impact。

缺失 signal 当期保持 `NA`，不产生 exposure、return 或 turnover；下一次重新出现可用 signal 时，turnover proxy 按从 0 重新建立 research exposure 计算，不前向延续旧 signal。

Overall 诊断先按 `realization_date` 对当日可用品种 signal return 做简单均值，再输出累计 gross/net signal return、年化均值、年化波动、Sharpe 和最大回撤；同时保留平均 turnover proxy、rough cost，以及适用时的 cross-sectional IC、Rank IC、long-short return。该简单均值只是 Alpha 诊断聚合，不是 Phase 5 Portfolio Construction。Breakdown 使用 realization year 和 instrument。当前稳定数据契约没有可靠 PIT sector metadata，因此 sector breakdown 明确 deferred。

### Parameter Surface 与本地结果

`run_parameter_surface` 只遍历研究员显式给出的参数集合及 factor-builder，例如 `lookback=[40, 60, 80]`；返回 overall/year/instrument 三张比较表，不排序、不选优、不自动扩张 grid。

`save_research_run` 在 `results/<run_name>/` 保存：

- `config.json`：factor、normalization、PIT universe、execution lag、return definition、日期、cost、parameter grid 和输入指纹。
- `overall.csv`、`by_year.csv`、`by_instrument.csv`。
- 参数测试存在时，额外保存三张 `parameter_surface_*.csv`。

`results/` 整体被 Git ignore；不保存大明细、不使用数据库，也不记录机器当前时间。相同输入与相同配置会产生相同 DataFrame 和输入指纹。RQFactor adapter 当前 deferred：基础 IC/Rank IC 已能透明计算，引入可选依赖不会改善 Fast Research 核心正确性。

## Phase 5 Portfolio & Risk v1

`china_cta.portfolio` 直接消费 Phase 3 的五列 factor table。`signal` 不会再次做 clipping、tanh、z-score 或 rank normalization；它也不会被解释为 position。一个或多个 factor 使用显式 `strategy_weights` 形成可追溯贡献表。

### 波动率与风险权重

波动率输入是 Phase 2 `pre + prev_close_ratio` 的 research continuous close，仅用于风险估计：

```text
simple_return(t) = close(t) / close(t-1) - 1
raw_volatility(t) = rolling_sample_std(simple_return) * sqrt(annualization_factor)
vol_forecast(t) = max(raw_volatility(t), explicit_volatility_floor)

strategy_risk_contribution = strategy_weight * signal / vol_forecast
aggregated_risk = sum(strategy_risk_contribution)
```

缺失价格不填充；历史不足、零或负 raw volatility 均为 unavailable。vol floor 只保护正但过小的有效预测。缺失 strategy 不重新归一化其余权重，避免因为数据缺失悄悄改变组合语义。

约束固定按下列顺序执行，并在 diagnostics 中保留每一步 pre/post/scale：

```text
aggregated inverse-vol risk
→ instrument clip
→ sector gross proportional scale
→ industrial-chain gross proportional scale
→ diagonal portfolio risk scale
```

diagonal v1 定义为：

```text
estimated_portfolio_risk = sqrt(sum((weight_i * vol_i) ** 2))
portfolio_scale_factor = portfolio_vol_target / estimated_portfolio_risk
post_scale_exposure = constrained_exposure * portfolio_scale_factor
```

当前没有足以证明 covariance framework 必要的稳定 strategy sleeves，因此不实现 covariance、shrinkage、PSD repair、HRP 或优化器。

### 分类、真实合约与时间语义

`config/product_classification_v1.yaml` 是版本化风险分组，不是 RQData PIT 行业数据，也不决定历史 universe。v1 只含已人工确认的 RB、CU、IF；启用 sector/chain cap 时，未知品种会明确报缺失，不会落入隐含 `Other`。

信号日 `t` 使用截至该日收盘的 signal、continuous close、真实 Trade Contract settlement、volume 和 OI。Target Position 在下一交易日 `t+1` 生效：

```text
signal information date       = close of t
Trade Contract                = RQData rule=0/rank=1 dominant for t+1
trade price for sizing        = that real contract's settlement on t
margin parameters             = direction-specific pre-open values for t+1
portfolio decision finalized  = pre-open of t+1
earliest execution            = trading session t+1
```

因此没有用 `t+1` 价格计算可在 `t+1` 执行的目标。若 dominant、真实价格、乘数或所需方向保证金率不可用，该品种不产生 target，并在 diagnostics 写明 reason；不会偷偷改选其他合约。

### 资本、保证金与整数手数

完整单位链为：

```text
target_notional = initial_capital * post_scale_exposure
contract_notional = settlement_t * contract_multiplier
pre_margin_quantity_float = target_notional / contract_notional

estimated_margin_pre = abs(target_notional) * directional_margin_ratio
margin_limit = initial_capital * max_margin_fraction
margin_scale = min(1, margin_limit / total_estimated_margin_pre)

target_quantity = trunc_toward_zero(
    pre_margin_quantity_float * margin_scale
)
```

margin scale 是同一目标日的整体比例缩放，只是投资决策 sanity check；它不冻结现金、不处理逐日盯市、拒单或账户权益。正式 margin/accounting 留给 RQAlpha Plus。

正式 Target Position 只含：

```text
trading_date, order_book_id, target_quantity, source_tag
```

这里的 `trading_date` 明确表示 **target effective date / earliest execution
trading date**，不是 factor/signal information date。对收盘后生成的 `t` 日
signal，正式 target table 的 `trading_date` 为下一交易日 `t+1`。

另外返回：

- `contributions`：逐 factor 的原始 signal、显式权重、vol 和 inverse-vol contribution。
- `diagnostics`：所有约束、portfolio scale、真实合约、价格、乘数、margin 与整数化计算链。
- `metadata`：全部会改变手数的配置、公式、时点语义和输入指纹。

`abs(target_quantity) / daily_volume` 与 `abs(target_quantity) / open_interest` 只作 capacity diagnostics，不改变手数、不选合约，也不是容量优化。

## Phase 6 RQAlpha Plus Formal Backtest

正式输入直接使用 Phase 5 schema：

```text
trading_date, order_book_id, target_quantity, source_tag
```

`trading_date` 仍表示 target effective date / earliest execution trading date，
不是 signal information date。Phase 6 不再 shift 日期，不重新计算 Alpha、组合、
Trade Contract 或手数。每个出现的 `trading_date` 是完整目标快照；先前目标合约若在
新快照中消失，adapter 将其解释为目标 0，以完成旧合约退出。

日频 v1 使用 `init + handle_bar`：`init` 校验并设置所有真实期货合约池，
`handle_bar(t)` 只读取 `t` 的预生成目标并调用：

```text
order_to(actual_contract, target_quantity)
```

默认显式配置 `frequency=1d`、`matching_type=current_bar`。订单在目标日的日 bar
回调提交并按 RQAlpha 日频规则撮合；adapter 不读取该 bar 形成投资决策，因此没有
额外一天 lag，也没有用当日 bar 重算目标。v1 不实现分钟或 tick。

`FormalBacktestConfig` 显式记录初始资金、bundle、日期、撮合、成交量比例、涨跌停、
无成交量限制、内置滑点、历史期货交易参数、结算价类型、手续费与保证金倍率。
`futures_time_series_trading_parameters=True` 是 Phase 6 必需条件。

每次运行在忽略 Git 的 `results/formal_backtest/<fingerprint>/` 保存：

- RQAlpha `sys_analyser` 原生 pickle；
- RQAlpha 原生 CSV report；
- adapter metadata、目标提交记录和 `order_to` Order 状态。

轻量 loader 只暴露 `portfolio`、`future_account`、`future_positions`、`trades`、
`orders`、`transaction_costs` 与 metadata。它不重算 NAV、MTM、保证金或账户；
RQAlpha `sys_analyser` 始终是正式 source of truth。`orders` 保留 status、message、
filled/unfilled quantity，供后续 reconciliation 使用。

## Phase 7 Golden Reconciliation 与 v1 使用路径

新研究员不需要编写新的回测引擎。v1 的最短操作路径是：

1. 在 VS Code 选择下文固定的 `cta` 解释器，并确认 RQSDK license 可用。
2. 用 `RQDataAdapter` / `china_cta.data.contracts` 拉取 PIT universe、连续研究价和真实 curve。
3. 提交标准 Factor table：

   ```text
   trading_date, instrument, factor_name, raw_factor, signal
   ```

4. 用 `run_fast_research_backtest` 快速判断 Alpha 是否值得进入正式回测；其连续价收益、turnover 和累计收益都只是 research diagnostics。
5. 用 `construct_target_positions` 把一个或多个标准 signal 转换为正式 Target Position：

   ```text
   trading_date, order_book_id, target_quantity, source_tag
   ```

6. 用 `run_formal_backtest` 原样消费 Target Position；RQAlpha Plus 原生处理订单、撮合、手续费、保证金、逐日盯市、账户和 NAV。
7. 从返回值或 `results/formal_backtest/<fingerprint>/` 查看原生 `portfolio`、`future_account`、`future_positions`、`trades`、订单状态和 report。不要用 Fast Research 累计收益替代正式 NAV。

`china_cta.validation.reconcile_close_based_mtm` 只服务于小型 Golden 案例：在日频
`current_bar`、`futures_settlement_price_type=close`、零滑点配置下复算：

```text
manual position P&L
= previous-close signed position
  * (close_t - close_t_minus_1)
  * contract multiplier

manual daily P&L
= manual position P&L
  + RQAlpha native trading P&L
  - RQAlpha native transaction cost
```

它不计算或替代正式 margin、MTM、account 或 NAV。Golden A/B 分别证明 long/short
方向；C 验证 `+1 → 0 → -1 → 0`；D 验证 `AG1606 → AG1612` 换月；F 使用真实历史
bar 验证涨停拒单、零成交量取消和成交量比例取消。固定回归规格位于
`config/golden_backtest_v1.json`，仅是一条小、快、可解释的 regression baseline，
不是策略业绩声明。如果版本、bundle 或结果变化，必须先解释差异，不能直接更新
expected values。

### Look-ahead Checklist

- **Signal lag**：Phase 3 的 `trading_date=t` 使用 t 日收盘后信息，最早只能用于下一交易时段；Phase 4 以显式 `execution_lag` 对齐 forward research return。
- **Target date**：Phase 5 输出的 `trading_date=t+1` 已是 target effective / earliest execution date；Phase 6 不把它当 signal date，也不再次 shift。
- **Formal callback**：日频 `handle_bar(t)` 只读取预生成的 t 日 Target Position。adapter 不用当前 bar 重算 signal、dominant、权重或手数；`current_bar` 只由 RQAlpha matcher 用作 t 日收盘成交假设。
- **`history_bars` visibility**：RQAlpha 官方日频口径下，`before_trading(t)` 最多看到 t-1 日线，`handle_bar(t)` 可看到 t 日线。当前 adapter 不调用 `history_bars` 做投资决策，因此不会把 handle-bar 可见的 t 日数据反向写入 t 日目标。
- **Dominant map**：Phase 2/5 对真实 Trade Contract 的选择按历史日期调用 RQData `rule=0, rank=1`，不使用今天的 dominant 反填历史。
- **Trading parameters**：Phase 5 只用历史可用字段做 margin sanity；Phase 6 强制 `futures_time_series_trading_parameters=True`，正式手续费、保证金和账户限制由 RQAlpha 原生处理。
- **Night session**：Phase 6 v1 只有日频，没有分钟/tick 或自定义夜盘执行窗口；若未来进入分钟回测，必须另行锁定 next-bar/下一可交易窗口语义。

相关行为口径见 [RQAlpha Plus 下单接口](https://www.ricequant.com/doc/rqalpha-plus/api/order-api)、[回测配置](https://www.ricequant.com/doc/rqalpha-plus/api/config)、[数据可见性](https://www.ricequant.com/doc/rqalpha-plus/api/data-api) 和 [结果对象](https://www.ricequant.com/doc/rqalpha-plus/api/types)。

### v1 已知限制

- 日频 Target Position 每个合约/交易日只有一个完整目标快照，不能表达同一天先开仓、随后又归零的两个盘中决策。因此 Golden E 已验证普通 `OPEN/CLOSE` 手续费；显式日内 `CLOSE_TODAY` 留作书面限制。没有切换到 `buy_open/sell_close` 状态机。
- `order_to` 的本机实现能够按实际昨仓/今仓选择 `CLOSE/CLOSE_TODAY`，但当前 v1 没有分钟级 Target schedule 来稳定制造同日平今 Golden case。
- RQAlpha analyser 的逐日账户表将部分费用/P&L 显示到 4 位小数，trade 记录保留更高精度；Golden expected summary 分别按各自原生精度核对，不硬编码调平。
- Golden baseline 固定在 rqalpha 6.3.0、rqalpha-plus 4.5.0、rqdatac 3.6.3 和本机 Phase 0 futures bundle。供应商版本或数据修订可能造成有理由的 regression。
- Phase 7 不增加 tick、容量/冲击模型、自研 OMS、撮合、期货账户、MTM 或 NAV。

## 环境

项目解释器固定为：

```text
C:\Users\Dayuan Shen\.conda\envs\cta\python.exe
```

VS Code 的项目级 `.vscode/settings.json` 已选择该解释器。不需要修改全局 PATH；即使 PowerShell 的执行策略阻止 `conda-hook.ps1`，也可直接使用解释器完整路径。

基础环境可由 `environment.yml` 重建：

```powershell
& "D:\software\anaconda\Scripts\conda.exe" env create -f environment.yml
```

`RQAlpha Plus` 和 `RQFactor` 是许可证组件，不写入公共 pip 依赖列表。获得许可证并设置本机环境变量后，在 `cta` 环境内通过 RQSDK 安装：

```powershell
& "C:\Users\Dayuan Shen\.conda\envs\cta\Scripts\rqsdk.exe" license
& "C:\Users\Dayuan Shen\.conda\envs\cta\Scripts\rqsdk.exe" install rqalpha_plus
& "C:\Users\Dayuan Shen\.conda\envs\cta\Scripts\rqsdk.exe" install rqfactor
```

许可证和 RQData 配置只保存在本机环境变量中，不得写入源码、YAML、日志或 Git。

## 验证命令

以下命令均可直接粘贴到 VS Code 的 PowerShell Terminal：

```powershell
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" check_environment.py
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest -q
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" scripts\check_rqdata.py
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" scripts\smoke_rqalpha_futures.py
```

默认 pytest 不访问网络。需要用有效许可证执行 Phase 1 的 RB/CU/IF 与夜盘真实数据验收时：

```powershell
$env:RUN_RQDATA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_rqdata_phase1_integration.py -q
```

Phase 2 的历史 universe、RB/CU/IF/AG curve、dominant/roll 与连续价验收：

```powershell
$env:RUN_RQDATA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_contracts_integration.py -q
```

Phase 3 的 RB/CU/IF 60 日 Trend、RB/CU Carry、手工公式和 RQData 官方 `near_main` 基准验收：

```powershell
$env:RUN_RQDATA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_factors_integration.py -q
```

Phase 4 的 execution lag、RB/CU/IF Trend、RB/CU Carry、连续价 PIT reconciliation 和 40/60/80 parameter surface 验收：

```powershell
$env:RUN_RQDATA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_fast_backtest_integration.py -q
```

Phase 5 的 RB/CU/IF volatility、Trend/Carry 聚合、下一交易日 Trade Contract、历史 margin、整数手数与未来数据扰动验收：

```powershell
$env:RUN_RQDATA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_portfolio_integration.py -q
```

Phase 6 的日频 Target schedule、long/flat/short/flat、历史期货参数、原生结果与重复运行验收：

```powershell
$env:RUN_RQALPHA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_formal_backtest_integration.py -q
```

Phase 7 的 Golden A–F、逐日 MTM 对账和冻结回归（只需要 RQAlpha license）：

```powershell
$env:RUN_RQALPHA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_golden_reconciliation_integration.py -q
```

同一文件中的 Trend+Carry → Portfolio → Formal 小型全链路测试还需要开启 RQData integration：

```powershell
$env:RUN_RQALPHA_INTEGRATION = "1"
$env:RUN_RQDATA_INTEGRATION = "1"
& "C:\Users\Dayuan Shen\.conda\envs\cta\python.exe" -m pytest tests\test_golden_reconciliation_integration.py -q
```

`check_rqdata.py` 会读取最近一个已完成交易日的 RB 主力合约日线。`smoke_rqalpha_futures.py` 使用本机 `data/rqalpha_bundle_futures_smoke/` 中已验证的期货 bundle，对 `AG1612` 做一手日频正式回测，并检查成交与 NAV 输出。

该本地 bundle 只验证了期货数据；因基础数据更新时 RQData 流量耗尽，里面的股票和指数文件不得用于研究。正式研究开始前，应按实际日期范围准备有效的 RQAlpha Plus 数据。

## 当前停止边界

Phase 7 到此为止。v1 的 Golden reconciliation、look-ahead checklist 和固定 regression baseline 已建立；`backtest-v1.1.0` 只增加研究因子、教学脚本与中文注释，没有开始 Phase 8+ 或改变既有回测架构。
