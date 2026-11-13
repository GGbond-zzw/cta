# 现货—期货基差季节性（Brooks 等，2013）

此项识别需要可与期货结算价比较的现货价格。已检查本机 `C:\Users\ct\.rqalpha\bundle` 和 `CTA/Mikuang_data/.rqalpha/bundle`：其中 `futures.h5` 包含真实期货合约及 88/99/888/889 等合成连续序列，不含全商品现货价格；`indexes.h5` 是指数行情。项目设计文件 `docs/factor_v2_design.md` 也已明确将全品种现货—期货因子暂缓，因为 RQData 没有统一的全商品现货序列。旧的交割月曲线残差检验与论文中的现货—期货基差不同；不要把 `results/all_commodity_curves/curve_seasonality/` 下的旧文件当作 Brooks 方法结果。

米筐官方 [Spot 文档](https://www.ricequant.com/doc/rqdata/python/spot-goods) 和 [通用 API 文档](https://www.ricequant.com/doc/rqdata/python/generic-api) 目前明确列出的 Spot 为上海黄金交易所黄金、铂金、白银现货合约，并未提供覆盖本项目 86 个商品期货品种的通用现货行情。`rqdata-python` 技能初始化在本机 `cta` 环境返回授权配置无效，当前无法调用 RQData 查询实际 Spot 合约列表。因此 Brooks 方法本轮没有可计算的全品种现货基差结果。

2026-10-14 再核查：本机 RQAlpha-Plus 许可证显示“现货日级别（基础版）”已开启，但这不等同于独立 RQData 的连接配置；`rqdatac.init()` 检查仍返回 `username/password/addr or uri expected`。执行 `rqsdk download-data --sample` 后，样例 bundle 可解包，但文件列表依旧无现货日线文件。该独立样例目录检查后已删除，未触碰原有 bundle。官方 `rqsdk update-data --base` 会使用 RQDatac 连接及流量，目前不应把它视为绕过 RQData 授权的方法。

随后也在项目独立目录完成了 `rqsdk download-data`（不带 `--sample`）并核对解包后的顶层文件和 `h5/` 子目录；仍无现货日线文件。该下载目录同样已删除，未改变现有研究输入或原有 bundle。

如果之后取得具体品种的可比现货 CSV，可运行：

```powershell
C:\Users\ct\miniconda3\envs\cta\python.exe scripts/identify_seasonality_papers.py --spot-csv <现货CSV完整路径>
```

默认列名为 `trading_date`、`underlying_symbol`、`spot_price`，可分别通过 `--spot-date-col`、`--spot-symbol-col`、`--spot-price-col` 指定。现货与期货价格必须采用相同计价单位和商品规格。脚本按交易日及品种匹配已有快照，从有成交量与持仓量的合约中选择最接近 6 个月与 12 个月期限的真实合约；每月保留最后一个可匹配交易日。计算 `log(期货结算价/现货价)`，分别按日历月检验两种期限基差的月份差异，并做同月均值的样本外预测比较。输出位于 `results/commodity_seasonality_2010_2026/paper_methods/brooks_*.csv`。

该实现尚不包含原文的预测回归、风险溢价分析和结构断点估计；目前只复现其基差季节性识别及 6／12 月期限对照思路。6／12 月期限通过最近可交易合约近似，不保证恰好整六个月或整一年。
