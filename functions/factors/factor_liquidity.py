import pandas as pd

def compute_factor(df, n=20):
    '''
    换手率/成交量因子: 成交量均值
    '''
    df = df.copy()
    df['volume_ma'] = df.groupby('symbol')['volume'].rolling(n).mean().reset_index(level=0,drop=True)
    return df[['date','symbol','volume_ma']]
