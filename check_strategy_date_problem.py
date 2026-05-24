import pandas as pd


FEATURE_FILE = r"F:\通信达量化\tdx_modular_quant_project_v2_all_instruments\data\processed\tdx_daily_features.parquet"

df = pd.read_parquet(FEATURE_FILE)

df["date"] = pd.to_datetime(df["date"])

print("全部数据日期范围：")
print(df["date"].min(), "to", df["date"].max())

print("\n每个月总行数：")
monthly_total = df.groupby(df["date"].dt.to_period("M")).size()
print(monthly_total.tail(20))


# =========================
# 检查 score_mom_lowvol 是否有效
# =========================

score_col = "score_mom_lowvol"

valid_score = df.dropna(subset=[score_col, "close", "symbol"]).copy()

print("\n有有效 score 的日期范围：")
print(valid_score["date"].min(), "to", valid_score["date"].max())

print("\n每个月有效 score 行数：")
monthly_score = valid_score.groupby(valid_score["date"].dt.to_period("M")).size()
print(monthly_score.tail(20))


# =========================
# 检查策略筛选条件之后的数据
# =========================

eligible = df.copy()

eligible = eligible[eligible["instrument_type"].isin(["stock", "etf_fund"])]
eligible = eligible[eligible["is_trading"] == True]
eligible = eligible[eligible["abnormal_jump"] == False]
eligible = eligible.dropna(subset=[score_col, "close", "symbol"])

print("\n策略可选数据日期范围：")
print(eligible["date"].min(), "to", eligible["date"].max())

print("\n每个月策略可选行数：")
monthly_eligible = eligible.groupby(eligible["date"].dt.to_period("M")).size()
print(monthly_eligible.tail(20))


# =========================
# 看 2025-10 之后到底剩了什么
# =========================

after = df[df["date"] >= "2025-10-01"].copy()

print("\n2025-10 之后原始 feature 行数：", len(after))
print("2025-10 之后标的数量：", after["symbol"].nunique())

print("\n2025-10 之后 instrument_type：")
print(after["instrument_type"].value_counts())

print("\n2025-10 之后 is_trading：")
print(after["is_trading"].value_counts(dropna=False))

print("\n2025-10 之后 abnormal_jump：")
print(after["abnormal_jump"].value_counts(dropna=False))

print("\n2025-10 之后 score 缺失数量：")
print(after[score_col].isna().sum(), "/", len(after))

print("\n2025-10 之后每个标的最后日期：")
print(
    after.groupby("symbol")["date"]
    .max()
    .sort_values()
    .tail(30)
)