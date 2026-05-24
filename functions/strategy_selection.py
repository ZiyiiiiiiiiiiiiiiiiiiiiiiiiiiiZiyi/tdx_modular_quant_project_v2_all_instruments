# -*- coding: utf-8 -*-
"""
策略选股模块：strategy_selection.py

作用：
    把已经计算好的因子数据，转换成每个调仓周期的选股结果。

输入文件：
    data/processed/tdx_daily_features.parquet

输出文件：
    data/processed/strategy_selection.parquet
    data/reports/strategy_selection_summary.csv

重要说明：
    这个文件只负责“选出哪些标的”。
    它不负责计算组合收益。
    后续组合收益、净值曲线、最大回撤等内容，
    应该放到 backtest_engine.py 里处理。
"""

import pandas as pd

from config import (
    FEATURE_DAILY_PARQUET,
    PROCESSED_DIR,
    REPORT_DIR,
)


def get_rebalance_dates(df, freq="ME"):
    """
    获取调仓日期。

    Parameters
    ----------
    df : pandas.DataFrame
        因子数据表，必须包含 date 字段。
    freq : str
        调仓频率。
        常用设置：
            "ME"    = 每月最后一个交易日调仓
            "QE"    = 每季度最后一个交易日调仓
            "W-FRI" = 每周调仓

    Returns
    -------
    rebalance_dates : pandas.Series
        实际可用的调仓日期。
    """

    # 取出所有交易日期，并按时间排序。
    dates = (
        df[["date"]]
        .drop_duplicates()
        .sort_values("date")
        .copy()
    )

    # 每月最后一个交易日。
    if freq == "ME":
        rebalance_dates = dates.groupby(
            dates["date"].dt.to_period("M")
        )["date"].max()

    # 每季度最后一个交易日。
    elif freq == "QE":
        rebalance_dates = dates.groupby(
            dates["date"].dt.to_period("Q")
        )["date"].max()

    # 每周最后一个交易日。
    # 当前代码没有严格指定周五，只是取该周最后一个有数据的交易日。
    elif freq.startswith("W"):
        rebalance_dates = dates.groupby(
            dates["date"].dt.to_period("W")
        )["date"].max()

    else:
        raise ValueError("不支持的调仓频率。请使用 'ME', 'QE', 或 'W-FRI'。")

    return rebalance_dates.reset_index(drop=True)


def select_instruments_by_score(
    df,
    score_col="score_mom_lowvol",
    top_n=5,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    require_trading=True,
    exclude_abnormal=True,
):
    """
    在每个调仓日期，根据因子分数选择标的。

    Parameters
    ----------
    df : pandas.DataFrame
        因子数据表。
    score_col : str
        用于排序的因子分数字段。
        例如：
            "score_mom_lowvol"
    top_n : int
        每个调仓日期选择多少个标的。
    freq : str
        调仓频率。
        例如：
            "ME"    = 月度调仓
            "QE"    = 季度调仓
            "W-FRI" = 周度调仓
    include_types : tuple or None
        允许进入选股池的标的类型。
        例如：
            ("stock",)
            ("etf_fund",)
            ("stock", "etf_fund")
        如果设置为 None，则不按 instrument_type 过滤。
    start_date : str or None
        策略选股开始日期。
        注意：
            这是策略选股开始日期，不是原始数据读取开始日期。
    end_date : str or None
        策略选股结束日期。
        None 表示使用所有可用日期。
    require_trading : bool
        如果为 True，则只保留 is_trading 为 True 的数据。
    exclude_abnormal : bool
        如果为 True，则剔除 abnormal_jump 为 True 的数据。

    Returns
    -------
    selection : pandas.DataFrame
        策略选股结果。
        主要字段：
            rebalance_date : 调仓日期
            rank           : 当期排名
            symbol         : 标的唯一代码，例如 sh600519 / sz000001
            code           : 六位代码
            market         : 市场，例如 sh / sz / bj
            instrument_type: 标的类型
            score          : 因子分数
            weight         : 等权权重
            close          : 调仓日收盘价
    """

    data = df.copy()

    # 确保 date 是 datetime 格式。
    data["date"] = pd.to_datetime(data["date"])

    # 按策略开始日期过滤。
    if start_date is not None:
        data = data[data["date"] >= pd.to_datetime(start_date)]

    # 按策略结束日期过滤。
    if end_date is not None:
        data = data[data["date"] <= pd.to_datetime(end_date)]

    # 按标的类型过滤。
    # 例如只选 stock / etf_fund。
    if include_types is not None and "instrument_type" in data.columns:
        data = data[data["instrument_type"].isin(include_types)]

    # 如果要求可交易，则只保留 is_trading 为 True 的行。
    if require_trading and "is_trading" in data.columns:
        data = data[data["is_trading"] == True]

    # 如果要求排除异常跳变，则剔除 abnormal_jump 为 True 的行。
    if exclude_abnormal and "abnormal_jump" in data.columns:
        data = data[data["abnormal_jump"] == False]

    # 删除无法排序或无法交易的关键缺失值。
    data = data.dropna(subset=[score_col, "close", "symbol"])

    # 如果过滤后没有数据，直接返回空表。
    if data.empty:
        print("警告：筛选后没有可用于选股的数据。")
        return pd.DataFrame()

    # 获取调仓日期。
    rebalance_dates = get_rebalance_dates(data, freq=freq)

    rows = []

    # 遍历每个调仓日期。
    for reb_date in rebalance_dates:

        # 取该调仓日所有标的数据。
        one_day = data[data["date"] == reb_date].copy()

        if one_day.empty:
            continue

        # 按因子分数从高到低排序。
        one_day = one_day.sort_values(score_col, ascending=False)

        # 选择排名前 top_n 的标的。
        selected = one_day.head(top_n).copy()

        if selected.empty:
            continue

        # 添加调仓日期。
        selected["rebalance_date"] = reb_date

        # 添加排名。
        selected["rank"] = range(1, len(selected) + 1)

        # 统一命名为 score，方便后续回测模块使用。
        selected["score"] = selected[score_col]

        # 简单等权配置。
        selected["weight"] = 1.0 / len(selected)

        # 最终保留字段。
        keep_cols = [
            "rebalance_date",
            "rank",
            "symbol",
            "code",
            "market",
            "instrument_type",
            "score",
            "weight",
            "close",
        ]

        # 防止某些字段不存在导致报错。
        for col in keep_cols:
            if col not in selected.columns:
                selected[col] = pd.NA

        rows.append(selected[keep_cols])

    # 如果没有任何调仓日选出标的，返回空表。
    if not rows:
        print("警告：没有生成任何策略选股结果。")
        return pd.DataFrame()

    # 合并所有调仓日选股结果。
    selection = pd.concat(rows, ignore_index=True)

    # 按调仓日期和排名排序。
    selection = selection.sort_values(["rebalance_date", "rank"])

    return selection

def run_strategy_selection(
    score_col="score_mom_lowvol",
    top_n=5,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    strategy_name="strategy",
    df_features=None,   # 新增：完整特征数据
    df_selection=None,  # 新增：已生成策略 DataFrame
):
    """
    支持两种用法：
    1. 原有方式：按 score_col 排序生成选股
    2. 多策略方式：直接传 df_selection 保存
    """
    output_path = f"data/processed/{strategy_name}.parquet"

    if df_selection is not None:
        # 如果传入 df_selection，直接保存
        df_selection.to_parquet(output_path, index=False)
        return df_selection
    elif df_features is not None:
        # 原有逻辑：按 score_col 排序生成选股
        df_sel = df_features.copy()
        # 过滤标的类型
        df_sel = df_sel[df_sel['instrument_type'].isin(include_types)]
        # 过滤日期
        if start_date is not None:
            df_sel = df_sel[df_sel['date'] >= pd.to_datetime(start_date)]
        if end_date is not None:
            df_sel = df_sel[df_sel['date'] <= pd.to_datetime(end_date)]
        # 过滤无效/异常收益
        if score_col not in df_sel.columns:
            raise ValueError(f"score_col {score_col} 不存在")
        df_sel = df_sel.sort_values(['date', score_col], ascending=[True, False])
        df_sel['rank'] = df_sel.groupby('date')[score_col].rank(method='first', ascending=False)
        df_sel = df_sel[df_sel['rank'] <= top_n]
        df_sel.to_parquet(output_path, index=False)
        return df_sel
    else:
        raise ValueError("必须提供 df_features 或 df_selection")
        
        
    """
    策略选股主函数。

    作用：
        1. 读取因子数据
        2. 按设定日期、频率、标的类型和因子分数进行选股
        3. 保存选股结果
        4. 保存选股汇总报告

    Parameters
    ----------
    score_col : str
        用于排序的因子字段。
    top_n : int
        每个调仓日期选择多少个标的。
    freq : str
        调仓频率。
    include_types : tuple
        允许进入选股池的标的类型。
    start_date : str or None
        策略选股开始日期。
    end_date : str or None
        策略选股结束日期。

    Returns
    -------
    selection : pandas.DataFrame
        策略选股结果。
    """

    # 读取因子数据。
    df = pd.read_parquet(FEATURE_DAILY_PARQUET)

    # 执行策略选股。
    # 注意：
    #     start_date 和 end_date 必须在这里传进去，
    #     否则 main.py 里设置的策略时间不会生效。
    selection = select_instruments_by_score(
        df=df,
        score_col=score_col,
        top_n=top_n,
        freq=freq,
        include_types=include_types,
        start_date=start_date,
        end_date=end_date,
    )

    # 输出文件路径。
    output_file = PROCESSED_DIR / "strategy_selection.parquet"
    summary_file = REPORT_DIR / "strategy_selection_summary.csv"

    # 保存选股结果。
    selection.to_parquet(output_file, index=False)

    # 如果选股结果为空，也保存空 summary，避免后续流程崩溃。
    if selection.empty:
        summary = pd.DataFrame(
            columns=[
                "rebalance_date",
                "selected_count",
                "avg_score",
                "min_score",
                "max_score",
            ]
        )
    else:
        # 生成每个调仓日的选股汇总。
        summary = (
            selection.groupby("rebalance_date")
            .agg(
                selected_count=("symbol", "count"),
                avg_score=("score", "mean"),
                min_score=("score", "min"),
                max_score=("score", "max"),
            )
            .reset_index()
        )

    # 保存汇总结果。
    summary.to_csv(summary_file, index=False, encoding="utf-8-sig")

    # 打印结果。
    print("已保存策略选股结果：", output_file)
    print("已保存策略选股汇总：", summary_file)
    print("选股结果形状：", selection.shape)

    if not selection.empty:
        print("\n策略选股结果前 20 行：")
        print(selection.head(20))
    else:
        print("\n当前设置下没有选出任何标的。请检查：")
        print("1. start_date / end_date 是否过窄")
        print("2. include_types 是否有对应标的")
        print("3. score_col 是否存在有效数据")
        print("4. READ_LIMIT 是否太小")

    return selection


if __name__ == "__main__":
    run_strategy_selection(
        score_col="score_mom_lowvol",
        top_n=5,
        freq="ME",
        include_types=("stock", "etf_fund"),
        start_date=None,
        end_date=None,
    )