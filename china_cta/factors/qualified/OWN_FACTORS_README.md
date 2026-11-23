# 新加入的两个自有冻结因子

已追加到本目录的BUILDERS，原四个builder保留。统一因子名单现为十一项，原默认回测参数保持原配置；存放在qualified目录及注册可调用不表示自动获得统计显著性或自动加入原九因子组合。

## 调用

```python
from china_cta.factors.qualified import BUILDERS

inputs = dict(continuous_prices=prices, universe=universe,
              contract_snapshots=snapshots, dominant_map=dominant)
carry = BUILDERS['our_close_carry_smooth5'](inputs)
transformer = BUILDERS['our_reg35_transformer'](inputs)
```

返回trading_date、instrument、factor_name、raw_factor、signal五列。信号收盘后可得，最早下一交易日首个交易时段开盘执行，包括夜盘。信号不等于手数，按原组合和原生账户流程转换。

## 输入

- universe：完整官方交易日×品种网格，字段trading_date、instrument、eligible；不合格日期标False，保留预热历史。
- dominant_map：trading_date、product、dominant_order_book_id，为当日可知的真实主力。
- contract_snapshots：trading_date、order_book_id、underlying_symbol、maturity_date、close，为真实合约收盘价。可用price但必须逐行注明price_field=close。不能把结算价冒充close。
- continuous_prices：trading_date、underlying_symbol、open、high、low、close、volume、open_interest、total_turnover；OHLC同一prev_close_ratio前复权尺度，开盘由真实主力open/close×连续close还原。volume、OI、amount为真实主力未复权数据。仅用于信号，现金盈亏用真实合约。

## 公式与冻结参数

**our_close_carry_smooth5：五日平滑收盘Carry。** 当日主力作为远月；选择到期早于主力、尚未到期且到期最早的真实合约作为近月。C=(近月close/主力close-1)×365/到期自然日差。raw_factor=最近5个完整交易日C的均值。S0=clip(raw_factor/0.05,-1,1)；abs(S0)<0.05时信号归零。正值做多，负值做空。价格不填补，窗口不完整则省略该行；缺失交易日不能被跳过拼窗。

**our_reg35_transformer：三种子正则Transformer。** 每日用过去60个交易日的79个冻结特征及79个缺失标志，输出三个冻结网络tanh预测的均值。79个原始特征包括raw_close_carry。各自训练期均值/标准差标准化，截断±5，缺失特征为零并加标志；没有填补价格。需要120日有效收盘价预热。隐藏宽度32、注意力头4、层数2、前馈64、dropout0.35，eval推理关闭dropout。种子171117/171118/171119。5日未来收益排序为训练目标，但信号每天更新，不强制持有5日。未再次训练或调参。

完整特征顺序、架构、各模型训练轮数、SHA256在reg35_transformer/assets/reg35_transformer/manifest.json；三份seed*.pt须一起提交，合计338889字节。推理模块不依赖本地results或根目录研究脚本。普通Carry不需要torch；Transformer可通过项目额外依赖安装：pip install -e ".[transformer]"。CPU float32支持推理，历史基准使用CUDA bfloat16，跨设备可能有轻微数值差。

## 校验及边界

原目录迁移校验：2016—2026历史Carry63958条、Transformer70164条，最大信号差异均为0。源项目另通过独立wheel打包测试，包含模型资产。

在本项目根目录，使用已安装依赖的Python运行：python -m unittest discover -s tests -p test_own_frozen_factors.py -v。

模型2016—2021年表现属于训练期回放，后续历史也已经查看。上一轮2026固定池回看历史有事后选样偏差，同事原始快照及全精度参数缺失；十一项消融差异区间均包含零，不能将迁移一致等同于无过拟合或保证实盘盈利。调用方负责数据PIT和实际发布时间。

本轮只本地放置、追加builder和模型分发配置，没有git初始化、commit或push。默认九因子组合不会自动变成十一因子；需要显式选择新builder，并传入上述数据。
