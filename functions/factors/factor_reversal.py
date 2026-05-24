import pandas as pd

def compute_factor(df, n=5):
    '''
    短期反转因子: -过去 n 日收益率
    '''
    df = df.copy()
    df['reversal'] = -df.groupby('symbol')['close'].pct_change(n)
    return df[['date','symbol','reversal']]
