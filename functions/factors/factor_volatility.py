import pandas as pd
import numpy as np

def compute_factor(df, n=10):
    '''
    历史波动率: 过去 n 日收益率标准差
    '''
    df = df.copy()
    df['ret'] = df.groupby('symbol')['close'].pct_change()
    df['volatility'] = df.groupby('symbol')['ret'].rolling(n).std().reset_index(level=0,drop=True)
    return df[['date','symbol','volatility']]
