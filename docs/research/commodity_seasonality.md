# 商品期货季节性识别（文献方法重做）

运行 `python scripts/identify_seasonality_papers.py`，读取现有的 `results/commodity_seasonality_2010_2026/daily_returns.csv`、`monthly_returns.csv` 和 `volatility_seasonality/monthly_volatility.csv`。原始行情输入保持不变，原有收益、稳健性、波动率诊断结果由新方法覆盖，并在 `paper_methods/` 留下按论文命名的输出。

## Li 等（2024）：收益率

按每月 1—15 日与其余日期分别累加日对数收益，以配对 t 检验检查半月差异。对月收益按日历月分组，用单因素 ANOVA 与 Kruskal–Wallis 检验月份均值／分布差异。另以截至上年的同月历史均值预测下一年，与截至上年的全月份均值比较，报告样本外 R²。这些是该文识别思路在现有数据上的实现，不声称重现其原始市场、样本或所有策略结果。

主结果：`return_diagnostics.csv` 和 `paper_methods/li_by_product.csv`；半月面板：`paper_methods/li_half_month_panel.csv`。跨品种 p 值使用 BH FDR 校正。

## Kosch 与 Forsberg（2026）：月份回归与 SSA

逐品种逐月拟合“该月 vs 其他 11 个月”的虚拟变量回归，以 Bartlett 核、3 阶 Newey–West 标准误报告月度超额收益及 p 值。SSA 使用连续 120 个月的收益训练窗、36 个月嵌入维度、前 12 个分量重构，并逐月产生下一月预测。缺失月份不填补，所在训练窗不生成预测。

主结果：`robustness/robustness_by_product.csv`（品种×日历月回归）与 `robustness/robustness_by_year.csv`（品种×预测月 SSA）；相同内容见 `paper_methods/`。**稳健低秩 SSA 尚未实现**，因此不能把这组结果称作论文三模型完整复现。月份回归的 FDR q 值针对所有可检验的品种×月份组合。

## 数据口径与解释

收益仍来自“前一交易日选定的真实主力合约，在同一合约上计算的结算价日收益”；跨合约换月不直接相除。月收益要求有效日覆盖率至少 80%，首尾不完整月份已在输入中排除。显著的月份差异、正的样本外 R² 和可交易盈利是三个不同问题。
