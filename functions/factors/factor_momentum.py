import pandas as pd

def compute_factor(df, n=5):
    '''
    动量因子: 过去 n 日收益率
    df: DataFrame, columns=['date','symbol','close']
    '''
    df = df.copy()
    df['momentum'] = df.groupby('symbol')['close'].pct_change(n)
    return df[['date','symbol','momentum']]
