import pandas as pd

def compute_factor(df, n=5):
    '''
    特大单/大单净买入: 成交量大于均值倍数
    '''
    df = df.copy()
    df['large_orders'] = df['volume'] / df.groupby('symbol')['volume'].transform(lambda x: x.rolling(n).mean())
    return df[['date','symbol','large_orders']]
