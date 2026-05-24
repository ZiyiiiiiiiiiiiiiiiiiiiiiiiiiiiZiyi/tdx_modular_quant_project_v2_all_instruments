# -*- coding: utf-8 -*-
"""
你之后主要改这两个文件：

config.py      # 改路径、日期、读取数量
main.py        # 控制运行哪些步骤

比如第一次测试用：

READ_LIMIT = 50

确认没问题后，改成：

READ_LIMIT = None

就是全量读取。

main.py 里可以控制流程：

RUN_STEP_1_CONVERT_TDX = True
RUN_STEP_2_CLEAN_DATA = True
RUN_STEP_3_FEATURES = True

如果你已经转换过通达信数据，只想重新生成因子，就改成：

RUN_STEP_1_CONVERT_TDX = False
RUN_STEP_2_CLEAN_DATA = False
RUN_STEP_3_FEATURES = True

现在这版已经把通达信 .day 能直接处理的基础行情先模块化了，包括：

open, high, low, close, amount, volume
数据清洗
异常收益检查
交易有效性标记
基础 K 线特征
均线特征
收益率特征
波动率特征
简单动量-低波因子

你提到的复权、资金流、龙虎榜、大宗交易、财务数据这些，我放在了：

functions/external_schema.py
"""

"""
因子应该放在哪里？
1. 技术因子：放在 feature_engineering.py

比如这些：

动量
反转
均线
波动率
成交量变化
成交额变化
K线形态
突破
换手代理
涨跌停特征

都应该放在：

functions/feature_engineering.py

因为它们是从行情数据直接算出来的。

比如：

df["ret_20"] = ...
df["volatility_20"] = ...
df["ma_60"] = ...
df["amount_ratio_20"] = ...

这些就是因子。

2. 外部数据因子：先放在单独模块，清洗后再合并

比如你说的：

大小资金拆分
板块资金流向
北向资金
龙虎榜
大宗交易
基本面财务数据
复权因子

这些不建议直接塞进 feature_engineering.py。
它们应该先有自己的模块，比如：

functions/external_data_loader.py
functions/fund_flow_features.py
functions/fundamental_features.py
functions/event_features.py
functions/adjust_price.py

然后统一合并到主数据里。

也就是说：

外部原始数据
↓
外部数据清洗
↓
标准化成 date + symbol
↓
合并到 daily_features
↓
生成最终因子表
"""
# -*- coding: utf-8 -*-
"""
Main controller file.

Run this file in Spyder or command line.
"""

# -*- coding: utf-8 -*-
"""
主控制文件：main.py

运行方式：
    可以在 Spyder 里直接运行本文件。
    也可以在命令行中运行：
        python main.py

一键流程：
    1. 读取通达信本地日线数据
    2. 清洗日线数据
    3. 生成因子特征
    4. 执行策略选股
    5. 导出并查看策略选股结果
"""
from functions.backtest_engine import run_backtest
from functions.convert_tdx_daily import convert_tdx_daily
from functions.clean_daily_data import clean_daily_data
from functions.feature_engineering import generate_daily_features_multi as generate_daily_features
from functions.feature_engineering import generate_multi_strategies
from functions.strategy_selection import run_strategy_selection
from functions.view_strategy_selection import view_strategy_selection
from functions.report_utils import print_project_status

from config import READ_LIMIT


# =========================
# 1. 流程开关设置
# =========================
# 如果想完整运行整个流程：
#     全部设置为 True
#
# 如果只想重新运行策略选股：
#     前三步设置为 False
#     第四步和第五步设置为 True
#
# 注意：
#     第一步读取通达信数据可能比较耗时。
#     如果数据已经读取过，不需要每次都重新跑。

RUN_STEP_1_CONVERT_TDX = True
RUN_STEP_2_CLEAN_DATA = True
RUN_STEP_3_FEATURES = True
RUN_STEP_4_STRATEGY_SELECTION = True
RUN_STEP_5_VIEW_SELECTION = True
RUN_STEP_6_BACKTEST = True

# =========================
# 2. 策略选股参数设置
# =========================

# 用哪个因子作为排序分数。
# 当前使用的是“20日动量 - 20日波动率”的简单测试因子。
STRATEGY_SCORE_COL = "score_mom_lowvol"

# 每个调仓日期选择多少个标的。
STRATEGY_TOP_N = 5

# 调仓频率：
#     "ME"    = 每月最后一个交易日调仓
#     "QE"    = 每季度最后一个交易日调仓
#     "W-FRI" = 每周调仓
STRATEGY_FREQ = "ME"

# 策略选股开始日期。
# 注意：这个控制的是“策略开始选股日期”，不是原始数据读取日期。
STRATEGY_START_DATE = "2021-01-01"

# 策略选股结束日期。
# None 表示使用所有可用日期。
STRATEGY_END_DATE = None


# 策略允许选择的标的类型。
# 常用设置：
#     ("stock",)              只选股票
#     ("etf_fund",)           只选 ETF / 场内基金
#     ("stock", "etf_fund")   股票 + ETF
#
# 当前设置：股票 + ETF
STRATEGY_INCLUDE_TYPES = (
    "stock",
    "etf_fund",
)


# =========================
# 3. 选股结果查看设置
# =========================

# 是否导出 Excel 文件，方便人工查看。
EXPORT_SELECTION_EXCEL = True

# 在 Spyder 控制台里打印多少行选股结果。
PRINT_SELECTION_ROWS = 30

# =========================
# 4. 回测参数设置
# =========================

# 初始净值。
# 第一版用 1.0 即可，代表从净值 1 开始。
BACKTEST_INITIAL_CASH = 1.0

# 年化无风险利率。
# 第一版可以先设为 0。
BACKTEST_RISK_FREE_RATE = 0.0
# 是否在 Spyder 右侧 Plots 窗口直接显示回测图。
BACKTEST_SHOW_PLOT = True

def main():
    """
    主函数。

    按照上面的开关设置，依次执行：
        1. 数据读取
        2. 数据清洗
        3. 因子生成
        4. 策略选股
        5. 结果导出与查看
    """

    # 打印当前项目配置。
    print_project_status()

    # =========================
    # Step 1：读取通达信本地数据
    # =========================
    if RUN_STEP_1_CONVERT_TDX:
        print("\n========== STEP 1：读取通达信日线数据 ==========")
        convert_tdx_daily(limit=READ_LIMIT)

    # =========================
    # Step 2：清洗基础行情数据
    # =========================
    if RUN_STEP_2_CLEAN_DATA:
        print("\n========== STEP 2：清洗日线数据 ==========")
        clean_daily_data()

    # =========================
    # Step 3：生成技术因子
    # =========================
    if RUN_STEP_3_FEATURES:
        print("\n========== STEP 3：生成因子特征 ==========")
        df_features = generate_daily_features()  # 返回 DataFrame 以便多策略使用

    # =========================
    # Step 4：根据因子进行策略选股
    # =========================
    if RUN_STEP_4_STRATEGY_SELECTION:
        print("\n========== STEP 4：执行策略选股 ==========")
        # 调用多策略生成函数，传入 top_n
        strategies = generate_multi_strategies(df_features, top_n=STRATEGY_TOP_N)

        # 循环保存每个策略的选股结果
        for name, df_sel in strategies.items():
            run_strategy_selection(
                df_features=df_features,
                df_selection=df_sel,
                score_col=None,  # 单因子排序已在 df_sel 内部处理
                top_n=STRATEGY_TOP_N,
                freq=STRATEGY_FREQ,
                include_types=STRATEGY_INCLUDE_TYPES,
                start_date=STRATEGY_START_DATE,
                end_date=STRATEGY_END_DATE,
                strategy_name=name
                )
    # =========================
    # Step 5：查看并导出策略选股结果
    # =========================
    if RUN_STEP_5_VIEW_SELECTION:
        print("\n========== STEP 5：查看策略选股结果 ==========")
        view_strategy_selection(
            export_excel=EXPORT_SELECTION_EXCEL,
            print_rows=PRINT_SELECTION_ROWS,
        )
    # =========================
    
    # Step 6：执行回测
    """
    打开 data/reports/strategy_selection_view.xlsx，查看每期选股结果。
    打开 results/equity_curve.png，确认回测净值曲线和回撤。
    """
    # =========================
    if RUN_STEP_6_BACKTEST:
        print("\n========== STEP 6：执行回测 ==========")
    
    for name, df_sel in strategies.items():
        print(f"\n========== 回测策略: {name} ==========")
        run_backtest(
            df_selection=df_sel,                   # 单策略选股表
            initial_cash=BACKTEST_INITIAL_CASH,
            risk_free_rate=BACKTEST_RISK_FREE_RATE,
            show_plot=BACKTEST_SHOW_PLOT,
            strategy_name=name                      # 用策略名称区分文件
        )
    print("\n全部选定步骤已完成。")
    """
    你现在去这里看 Excel：
    
    F:\通信达量化\tdx_modular_quant_project_v2_all_instruments\data\reports\strategy_selection_view.xlsx
    
    还有 CSV：
    
    F:\通信达量化\tdx_modular_quant_project_v2_all_instruments\data\reports\strategy_selection_view.csv
    
    正式程序用的数据表在这里：
    
    F:\通信达量化\tdx_modular_quant_project_v2_all_instruments\data\processed\strategy_selection.parquet
    """
if __name__ == "__main__":
    main()