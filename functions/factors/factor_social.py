import pandas as pd

def compute_factor(df, n=5):
    '''
    社交热度模拟: 高波动高成交量
    '''
    df = df.copy()
    df['social'] = df.groupby('symbol')['close'].pct_change(n).abs() * df.groupby('symbol')['volume'].pct_change(n)
    return df[['date','symbol','social']]
