# 国内期货 CTA Research Framework

本项目以 Ricequant RQSDK 为基础设施，目标链路是：

`RQData → Alpha → Portfolio/Risk → Target Position → RQAlpha Plus → P&L/NAV → Validation`

Ricequant 负责行情与合约数据，以及正式回测中的订单、撮合、持仓、手续费、保证金、逐日盯市、账户和 NAV。本项目只实现研究逻辑：因子、预测、组合与风险分配、目标仓位、快速研究回测，以及与正式回测结果的验证和归因。

不实现自研通用撮合、期货账户、保证金记账、完整 OMS、Broker API、数据库服务、Web 服务、Docker 或分布式基础设施。

## 当前状态

- Phase 0 已完成：Python 3.11 独立 Conda 环境、RQData 连通性，以及 RQAlpha Plus 单合约一手期货冒烟回测均已验证。
- M1 架构清理已完成：旧的 Contract Master 快照、Contract Selector、Parquet 存储和相关脚本/测试已从源码中移除。
- Phase 1 已完成：六个最小 RQData 查询接口、标准 DataFrame schema 和本地 Parquet cache 已验证。
- Phase 2 尚未开始；当前代码不定义 Signal/Trade/Curve Contract，也不会产生交易信号或投资建议。
- `data/` 中的旧快照和本地 RQAlpha 结果仅作为本机验证资料保留，已整体排除在 Git 之外，不再是新架构的依赖。

当前最小目录：

```text
china_cta/
  data/
    rqdata_adapter.py  # Phase 1 的六个 RQData 查询接口
    cache.py           # 参数哈希 Parquet + JSON metadata
  factors/          # Factor / Alpha（待 Phase 1）
  research/         # 快速研究回测（待 Phase 1）
  portfolio/        # 组合、风险与目标仓位（待 Phase 1）
  formal_backtest/  # RQAlpha Plus 对接（待 Phase 1）
  validation/       # 对账、归因和稳健性（待 Phase 1）
scripts/
  check_rqdata.py
  smoke_rqalpha_futures.py
tests/
config/
```

## Phase 1 数据接口

`RQDataAdapter` 只提供当前研究需要的六个公开方法：

- `get_trading_calendar(start, end)`：官方交易日历。
- `get_future_instruments(date=None)`：指定日期可交易期货及 instrument master 字段。
- `get_instrument_details(ids)`：合约乘数、到期日、交易所、品种、最新静态保证金率和 tick size 等详情；历史保证金仍以 trading parameters 为准。
- `get_bars(ids, start, end, frequency="1d", fields=None)`：真实合约日线或分钟线；不复权。
- `get_dominant_map(symbols, start, end, rule=0, rank=1)`：RQData 主力/次主力实际合约映射。
- `get_trading_parameters(ids, start, end)`：原样保留保证金、手续费和限仓等供应商字段及单位。

日线固定以 `trading_date, order_book_id` 开头。分钟线固定同时保留自然时间 `datetime` 和期货交易日 `trading_date`，不会把夜盘自然日期当作交易日。

默认 cache 目录为项目相对路径 `data/cache/rqdata/`，可通过构造 `RQDataConfig(cache_dir=...)` 或本机环境变量 `CTA_RQDATA_CACHE_DIR` 修改，也可传入 `cache_dir=None` 禁用。每个缓存项由请求参数哈希命名，包含 Parquet 数据以及记录请求参数、UTC 拉取时间和 rqdatac 版本的 JSON metadata；许可证和连接 URI 不会写入缓存。

API 口径以 [RQData 通用 API](https://www.ricequant.com/doc/rqdata/python/generic-api) 和 [RQData 期货 API](https://www.ricequant.com/doc/rqdata/python/futures-mod) 为准。

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

`check_rqdata.py` 会读取最近一个已完成交易日的 RB 主力合约日线。`smoke_rqalpha_futures.py` 使用本机 `data/rqalpha_bundle_futures_smoke/` 中已验证的期货 bundle，对 `AG1612` 做一手日频正式回测，并检查成交与 NAV 输出。

该本地 bundle 只验证了期货数据；因基础数据更新时 RQData 流量耗尽，里面的股票和指数文件不得用于研究。正式研究开始前，应按实际日期范围准备有效的 RQAlpha Plus 数据。

## 当前停止边界

Phase 1 到此为止。Contract / Universe / Curve Representation 属于 Phase 2，未经明确授权不实现；Alpha、Portfolio、Research Backtest 和正式回测同样不属于当前数据层。
