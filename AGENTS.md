# AGENTS

## 项目概览

这是一个基于通达信本地 `.day` 日线文件的 A 股量化研究项目，目标是把“原始行情读取 -> 数据清洗 -> 因子生成 -> 选股 -> 回测 -> 结果导出”串成一套本地可运行流程。

项目当前已经不只是最初的单策略版本，源码主流程已经演进为“多策略批量生成和批量回测”模式，同时保留了一些早期单策略接口和输出文件。因此阅读和修改时，要区分“当前主干逻辑”和“遗留兼容逻辑”。

## 代码根目录

- `main.py`
  - 项目总入口。
  - 负责控制 6 个步骤是否执行。
  - 当前主流程会先生成特征，再一次性生成多套策略，并分别保存选股结果和回测结果。
- `config.py`
  - 全局配置入口。
  - 负责通达信目录、项目目录、数据范围、市场范围、标的类型、输出路径等配置。
- `functions/`
  - 所有核心功能模块。
- `functions/factors/`
  - 独立因子函数集合。
  - 当前只有 `factor_ml.py` 明确接入主流程，其余多数更像预留/占位模块。
- `data/`
  - 中间数据和报表输出目录。
- `results/`
  - 回测输出目录。
- `test.py`
  - 一个偏手工性质的回测测试脚本，不是标准测试框架。
- `check_strategy_date_problem.py`
  - 用来排查策略日期范围/有效样本问题的辅助脚本。
- `README.md`、`介绍.txt`
  - 旧版项目说明，整体思路仍然有参考价值，但与当前多策略实现并不完全一致。

## 数据来源与基础假设

- 默认通达信安装目录：`F:\tongxinda`
- 原始数据目录：
  - `F:\tongxinda\vipdoc\sh\lday`
  - `F:\tongxinda\vipdoc\sz\lday`
  - `F:\tongxinda\vipdoc\bj\lday`
- 原始文件格式：通达信 `.day`
- 读取字段：
  - `date`
  - `market`
  - `code`
  - `symbol`
  - `instrument_type`
  - `open`
  - `high`
  - `low`
  - `close`
  - `amount`
  - `volume`

项目内部以 `symbol` 作为更稳妥的唯一标识，例如：

- `sh600519`
- `sz000001`
- `bj430047`

不要只用 6 位 `code`，否则跨市场会冲突。

## 当前配置现状

`config.py` 当前关键配置如下：

- `TDX_DIR = F:\tongxinda`
- `PROJECT_DIR = F:\通信达量化\tdx_modular_quant_project_v2_all_instruments`
- `START_DATE = "2018-01-01"`
- `END_DATE = None`
- `INCLUDE_MARKETS = ("sh", "sz", "bj")`
- `INCLUDE_INSTRUMENT_TYPES = ("stock", "etf_fund", "index", "bond", "convertible_bond", "b_share", "unknown")`
- `READ_LIMIT = 20`
- `ABNORMAL_RETURN_THRESHOLD = 0.20`

这说明当前仓库里的中间产物，大概率是基于“小样本调试配置”跑出来的，而不是全量市场结果。

## 目录与文件职责

### `data/processed/`

中间数据主目录，当前可见文件包括：

- `tdx_daily_raw.parquet`
  - 从 `.day` 直接转换后的原始日线表。
- `tdx_daily_clean.parquet`
  - 清洗并加质量标记后的日线表。
- `tdx_daily_features.parquet`
  - 加入价量因子后的特征总表。
- `strategy_selection.parquet`
  - 旧版单策略选股结果文件，部分视图脚本仍然依赖它。
- `{strategy_name}.parquet`
  - 当前多策略版本的各策略选股结果。
  - 现有策略文件包括：
    - `momentum.parquet`
    - `reversal.parquet`
    - `low_vol.parquet`
    - `volume_extreme.parquet`
    - `ma_break.parquet`
    - `kline_shape.parquet`
    - `mom_lowvol.parquet`
    - `ml_elasticnet.parquet`
    - `ml_xgboost.parquet`
    - `ml_lightgbm.parquet`
    - `event_factor.parquet`
    - `alternative_factor.parquet`

### `data/reports/`

偏人工检查和汇总用途：

- `failed_codes.csv`
- `instrument_info.csv`
- `abnormal_return_rows.csv`
- `data_quality_summary.csv`
- `strategy_selection_summary.csv`
- `strategy_selection_view.csv`
- `strategy_selection_view.xlsx`

### `results/`

回测输出目录。当前仓库中已经有多策略历史输出，命名风格分两类：

- 旧命名：
  - `backtest_daily_result.csv`
  - `backtest_metrics.csv`
  - `backtest_holdings.csv`
  - `equity_curve.png`
- 多策略命名：
  - `backtest_daily_result_{strategy}.csv/.parquet`
  - `backtest_metrics_{strategy}.csv`
  - `backtest_holdings_{strategy}.csv`
  - `equity_curve_{strategy}.png`
- 还有另一套命名：
  - `{strategy}_daily_result.*`
  - `{strategy}_metrics.csv`
  - `{strategy}_holdings.csv`
  - `{strategy}_equity_curve.png`

这说明结果命名在项目演进过程中发生过变化，后续整理时最好统一。

## 主流程

`main.py` 当前流程开关：

- `RUN_STEP_1_CONVERT_TDX`
- `RUN_STEP_2_CLEAN_DATA`
- `RUN_STEP_3_FEATURES`
- `RUN_STEP_4_STRATEGY_SELECTION`
- `RUN_STEP_5_VIEW_SELECTION`
- `RUN_STEP_6_BACKTEST`

默认全部为 `True`。

标准执行链路：

1. `convert_tdx_daily(limit=READ_LIMIT)`
2. `clean_daily_data()`
3. `generate_daily_features_multi()`
4. `generate_multi_strategies(df_features, top_n=STRATEGY_TOP_N)`
5. 对每个策略分别调用 `run_strategy_selection(...)`
6. 查看选股结果
7. 对每个策略分别调用 `run_backtest(...)`

## 详细模块说明

### 1. `functions/tdx_day_file_reader.py`

负责底层 `.day` 文件读取。

核心函数：

- `classify_tdx_instrument(market, code)`
  - 按代码前缀粗分类：
    - `stock`
    - `etf_fund`
    - `index`
    - `bond`
    - `convertible_bond`
    - `b_share`
    - `unknown`
- `collect_tdx_day_files(...)`
  - 从 `vipdoc/<market>/lday` 收集符合条件的 `.day` 文件。
- `read_tdx_day_file(...)`
  - 逐个解析二进制记录，生成单标的日线表。

### 2. `functions/convert_tdx_daily.py`

负责把本地 `.day` 文件批量转成 Parquet。

输入：

- 通达信本地 `.day`

输出：

- `data/processed/tdx_daily_raw.parquet`
- `data/reports/failed_codes.csv`

说明：

- 会打印选中的标的数和前 20 个标的。
- `limit` 一般用于开发调试。

### 3. `functions/clean_daily_data.py`

负责基础清洗和质量标记。

处理内容：

- `date` 转 `datetime`
- `code` 统一为 6 位字符串
- `open/high/low/close/amount/volume` 转数值
- 删除关键字段缺失行
- 去重 `symbol + date`
- 按 `START_DATE` / `END_DATE` 截断
- 调用 `quality_checks.py` 增加质量字段

输出：

- `data/processed/tdx_daily_clean.parquet`

### 4. `functions/quality_checks.py`

负责质量标记和质量报表。

新增字段：

- `valid_price`
- `valid_volume`
- `raw_ret`
- `abnormal_jump`
- `rough_limit_up`
- `rough_limit_down`
- `is_trading`

报表输出：

- `instrument_info.csv`
- `abnormal_return_rows.csv`
- `data_quality_summary.csv`

### 5. `functions/feature_engineering.py`

这是当前特征主模块，函数名已经是多策略版本：

- `generate_daily_features_multi()`
- `select_instruments_by_score(...)`
- `generate_multi_strategies(df, top_n)`

当前直接在这个文件中生成的因子主要是价量技术因子：

- 收益类：
  - `ret_1`
  - `ret_5`
  - `ret_10`
  - `ret_20`
  - `ret_60`
- 均线类：
  - `ma_5`
  - `ma_10`
  - `ma_20`
  - `ma_60`
  - `ma_120`
  - `volume_ma_5`
  - `volume_ma_10`
  - `volume_ma_20`
  - `volume_ma_60`
  - `volume_ma_120`
  - `close_to_ma20`
  - `close_to_ma60`
- 波动类：
  - `volatility_10`
  - `volatility_20`
  - `volatility_60`
- K 线形态：
  - `amplitude`
  - `intraday_ret`
  - `upper_shadow`
  - `lower_shadow`
  - `body_ratio`
- 成交额类：
  - `amount_ma20`
  - `amount_ratio_20`
- 综合分数：
  - `score_mom_lowvol = ret_20 - volatility_20`

当前多策略列表：

- `momentum`
- `reversal`
- `low_vol`
- `volume_extreme`
- `ma_break`
- `kline_shape`
- `mom_lowvol`
- `ml_elasticnet`
- `ml_xgboost`
- `ml_lightgbm`
- `event_factor`
- `alternative_factor`

其中：

- `event_factor`
- `alternative_factor`

目前本质上还是用 `ret_20` 代替的占位策略，不是真正的事件因子/另类因子。

### 6. `functions/factors/`

这个目录下已经拆出一批因子函数文件，例如：

- `factor_momentum.py`
- `factor_reversal.py`
- `factor_volatility.py`
- `factor_low_noise.py`
- `factor_liquidity.py`
- `factor_close_volume_ratio.py`
- `factor_earnings_surprise.py`
- `factor_analyst_update.py`
- `factor_large_orders.py`
- `factor_sentiment.py`
- `factor_social.py`
- `factor_supply_chain.py`
- `factor_ml.py`

但从当前主流程看：

- 主流程并没有系统性地逐个调用这些 `compute_factor(...)`。
- 当前真正接入的是 `factor_ml.py`，它被 `feature_engineering.py` 用来生成 `score_ml`。
- 其他因子文件更像后续扩展接口或样板。

### 7. `functions/strategy_selection.py`

这是“选股结果持久化/兼容逻辑”模块。

核心函数：

- `get_rebalance_dates(df, freq)`
- `select_instruments_by_score(...)`
- `run_strategy_selection(...)`

支持两种用法：

1. 旧方式：给 `df_features + score_col`，现场做排序选股。
2. 新方式：直接传 `df_selection`，保存已有选股结果。

当前 `main.py` 走的是第二种，即：

- 先在 `feature_engineering.py` 里生成策略结果
- 再在这里按策略名保存成 `data/processed/{strategy_name}.parquet`

### 8. `functions/view_strategy_selection.py`

负责查看和导出选股结果。

当前行为：

- 固定读取 `data/processed/strategy_selection.parquet`
- 打印头尾、标的类型分布、最近调仓日结果
- 导出：
  - `strategy_selection_view.xlsx`
  - `strategy_selection_view.csv`

注意：

- 该模块仍然绑定旧文件名 `strategy_selection.parquet`
- 与当前多策略按策略名分别落盘的实现并不完全一致

### 9. `functions/backtest_engine.py`

负责单策略回测和作图。

核心函数：

- `prepare_daily_returns(feature_data)`
- `run_backtest(df_selection, ...)`
- `_plot_equity_curve(...)`

当前回测逻辑特点：

- 按 `rebalance_date` 分组做等权配置
- 单标的权重上限 `max_weight=0.2`
- 收益使用 `ret_1.shift(-1)` 近似下一期收益
- 生成净值、回撤、持仓数、指标和图形

输出：

- `backtest_daily_result_{strategy}.csv`
- `backtest_daily_result_{strategy}.parquet`
- `backtest_metrics_{strategy}.csv`
- `backtest_holdings_{strategy}.csv`
- `equity_curve_{strategy}.png`

### 10. `functions/metrics.py`

负责回测指标计算。

输出指标：

- `start_date`
- `end_date`
- `trading_days`
- `final_net_value`
- `total_return`
- `annual_return`
- `annual_volatility`
- `sharpe`
- `max_drawdown`
- `win_rate`

## 策略参数入口

`main.py` 当前策略相关参数：

- `STRATEGY_SCORE_COL = "score_mom_lowvol"`
- `STRATEGY_TOP_N = 5`
- `STRATEGY_FREQ = "ME"`
- `STRATEGY_START_DATE = "2021-01-01"`
- `STRATEGY_END_DATE = None`
- `STRATEGY_INCLUDE_TYPES = ("stock", "etf_fund")`

回测参数：

- `BACKTEST_INITIAL_CASH = 1.0`
- `BACKTEST_RISK_FREE_RATE = 0.0`
- `BACKTEST_SHOW_PLOT = True`

查看参数：

- `EXPORT_SELECTION_EXCEL = True`
- `PRINT_SELECTION_ROWS = 30`

## 调仓频率约定

- `ME`
  - 月末最后一个交易日
- `QE`
  - 季末最后一个交易日
- `W-FRI`
  - 代码中按“周周期最后一个有数据的交易日”处理，不是严格检查周五成交

## 当前仓库反映出的实现状态

从现有代码和产物看，项目目前处于“能跑通、多策略原型已成形、但架构仍混合新旧逻辑”的阶段。

更具体地说：

1. 数据读取、清洗、基础价量因子、选股、回测都已经打通。
2. `main.py` 已切到多策略模式。
3. `view_strategy_selection.py` 仍偏单策略旧接口。
4. `strategy_selection.py` 同时承载新旧两套职责。
5. `results/` 中已经存在多套策略历史输出，说明多策略流程曾被实际执行。
6. `READ_LIMIT = 20` 表明当前仓库更偏开发调试状态，不是全量正式跑数状态。

## 已知局限与维护注意事项

### 1. 回测仍然是简化版

当前没有严肃处理：

- 手续费
- 滑点
- 涨跌停不可成交
- 停牌
- 复权价格
- 更真实的调仓成交价建模

因此现有结果更适合研究原型，不适合作为实盘结论。

### 2. 新旧文件命名并存

仓库里同时存在：

- 单策略旧命名
- 多策略新命名
- 另一套以策略名为前缀的输出

后续如果要继续开发，建议先统一命名规则。

### 3. 多策略与查看模块存在脱节

`main.py` 会按策略分别保存 `data/processed/{strategy_name}.parquet`，但 `view_strategy_selection.py` 仍只读 `strategy_selection.parquet`。这说明“查看/导出”环节还没有完全升级到多策略视角。

### 4. 因子目录与主流程尚未完全统一

`functions/factors/` 已经有不少拆分文件，但主流程里的多数技术因子仍直接写在 `feature_engineering.py` 里。后续如继续扩展，最好决定一种统一风格：

- 要么集中在 `feature_engineering.py`
- 要么全部改成独立 `factor_xxx.py` 再汇总

### 5. ML 因子依赖额外库

`factor_ml.py` 依赖：

- `scikit-learn`
- `xgboost`
- `lightgbm`

如果环境不完整，多策略生成会在 ML 策略阶段失败。

### 6. 代码中保留了一些旧注释/旧说明

根目录说明文档和部分源码注释描述的是早期单策略版本。修改功能前，应优先以当前源码执行路径为准，而不是只看旧文档。

## 建议的阅读顺序

1. `config.py`
2. `main.py`
3. `functions/tdx_day_file_reader.py`
4. `functions/convert_tdx_daily.py`
5. `functions/clean_daily_data.py`
6. `functions/quality_checks.py`
7. `functions/feature_engineering.py`
8. `functions/strategy_selection.py`
9. `functions/backtest_engine.py`
10. `functions/metrics.py`

## 后续修改建议

如果后续继续迭代这个项目，优先级建议如下：

1. 统一单策略/多策略接口与命名。
2. 让 `view_strategy_selection.py` 支持按策略查看。
3. 明确 `factors/` 目录和 `feature_engineering.py` 的职责边界。
4. 为回测补充交易成本、复权、停牌和涨跌停约束。
5. 把 `test.py` 迁移到正式测试结构，至少覆盖主流程关键函数。

## 面向后续代理/开发者的结论

这个仓库不是从零开始的空壳，而是一个已经能跑出实际中间结果和多策略回测结果的量化研究原型。修改时应默认遵守以下判断：

- 入口以 `main.py` 为准。
- 配置以 `config.py` 为准。
- 当前主干是多策略，不是单策略。
- `data/processed/` 和 `results/` 已含历史产物，不要随意据此推断逻辑正确，只能把它们当作“曾经跑通过”的证据。
- 旧文档可参考，但涉及行为判断时，要以源码现状为最终依据。
