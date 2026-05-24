import pandas as pd

def compute_factor(df, n=10):
    '''
    信息平稳/冷门股因子: 过去 n 日波动率低且成交量小
    '''
    df = df.copy()
    df['ret'] = df.groupby('symbol')['close'].pct_change()
    df['vol'] = df.groupby('symbol')['ret'].rolling(n).std().reset_index(level=0,drop=True)
    df['vol_ma'] = df.groupby('symbol')['volume'].rolling(n).mean().reset_index(level=0,drop=True)
    df['low_noise'] = (1 / (1 + df['vol'])) * (1 / (1 + df['vol_ma']))
    return df[['date','symbol','low_noise']]
