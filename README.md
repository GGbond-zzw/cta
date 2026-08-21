# 国内期货 CTA Research Framework

本项目以 Ricequant RQSDK 为基础设施，目标链路是：

`RQData → Alpha → Portfolio/Risk → Target Position → RQAlpha Plus → P&L/NAV → Validation`

Ricequant 负责行情与合约数据，以及正式回测中的订单、撮合、持仓、手续费、保证金、逐日盯市、账户和 NAV。本项目只实现研究逻辑：因子、预测、组合与风险分配、目标仓位、快速研究回测，以及与正式回测结果的验证和归因。

不实现自研通用撮合、期货账户、保证金记账、完整 OMS、Broker API、数据库服务、Web 服务、Docker 或分布式基础设施。

## 当前状态

- Phase 0 已完成：Python 3.11 独立 Conda 环境、RQData 连通性，以及 RQAlpha Plus 单合约一手期货冒烟回测均已验证。
- M1 架构清理已完成：旧的 Contract Master 快照、Contract Selector、Parquet 存储和相关脚本/测试已从源码中移除。
- Phase 1 已完成：六个最小 RQData 查询接口、标准 DataFrame schema 和本地 Parquet cache 已验证。
- Phase 2 已完成：point-in-time research universe、真实合约/curve snapshot、官方 dominant/roll map，以及 Signal/Trade/Curve Contract 角色已明确。
- Phase 3 已完成：统一 factor table，以及可人工复算的 60 日 Trend 和真实 near/main 合约 Carry baseline 已验证。
- 当前代码产生的是研究信号，不是投资组合权重、目标手数、成交、P&L 或投资建议；这些属于后续阶段。
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
  research/         # 快速研究回测（后续阶段）
  portfolio/        # 组合、风险与目标仓位（后续阶段）
  formal_backtest/  # RQAlpha Plus 对接（后续阶段）
  validation/       # 对账、归因和稳健性（后续阶段）
scripts/
  check_rqdata.py
  smoke_rqalpha_futures.py
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

Trend 与 Carry 的内部输入不同，但都输出同一个最小表：

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

### 可用时点

两个 baseline 的 metadata 都明确：`information_date=trading_date`、`signal_available_at=after_close_of_trading_date`、`earliest_trade_at=next_trading_session`。即 `close(t)` 或 `settlement(t)` 产生的信号不能假设在同一个收盘价成交。Phase 3 不模拟交易，也不把 signal 转换为 position。

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

`check_rqdata.py` 会读取最近一个已完成交易日的 RB 主力合约日线。`smoke_rqalpha_futures.py` 使用本机 `data/rqalpha_bundle_futures_smoke/` 中已验证的期货 bundle，对 `AG1612` 做一手日频正式回测，并检查成交与 NAV 输出。

该本地 bundle 只验证了期货数据；因基础数据更新时 RQData 流量耗尽，里面的股票和指数文件不得用于研究。正式研究开始前，应按实际日期范围准备有效的 RQAlpha Plus 数据。

## 当前停止边界

Phase 3 到此为止。其他 Alpha、Portfolio、Risk、Position Sizing、Research Backtest 和正式回测 adapter 均未实现，未经明确授权不进入 Phase 4。
