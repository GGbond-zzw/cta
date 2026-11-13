# 月份回归与 SSA 结果说明

此前的年内月份置换检验结果已由 `scripts/identify_seasonality_papers.py` 覆盖。`robustness_by_product.csv` 现在是 Kosch 与 Forsberg（2026）式的品种×日历月回归结果；`robustness_by_year.csv` 现在是逐月 SSA 样本外预测结果。不要用旧列名或旧阈值解释这些文件。

回归列 `month_excess_return` 是该月收益相对其余月份平均收益的差，`hac_p` 为 Newey–West p 值，`hac_q` 为跨全部品种×月份的 BH FDR 校正值。SSA 文件保存 `actual`、`ssa_forecast`、`baseline_forecast`，供直接评估预测误差。缺失月份导致训练窗不完整时不生成预测。

实现未包含论文的稳健低秩 SSA、组合构建、交易成本和 bootstrap 绩效检验。当前文件只回答识别与预测问题。
