import pandas as pd

def compute_factor(df, n=5):
    '''
    财报超预期模拟因子: 用过去 n 日收盘收益异常值模拟
    '''
    df = df.copy()
    df['earnings_surprise'] = df.groupby('symbol')['close'].pct_change(n).apply(lambda x: x if abs(x)>0.05 else 0)
    return df[['date','symbol','earnings_surprise']]
