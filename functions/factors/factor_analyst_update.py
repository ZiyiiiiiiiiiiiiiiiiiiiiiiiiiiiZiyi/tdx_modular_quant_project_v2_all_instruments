import pandas as pd

def compute_factor(df, n=5):
    '''
    分析师调整模拟因子: 用成交量突变作为近似
    '''
    df = df.copy()
    df['analyst_update'] = df.groupby('symbol')['volume'].pct_change(n).apply(lambda x: x if abs(x)>0.5 else 0)
    return df[['date','symbol','analyst_update']]
