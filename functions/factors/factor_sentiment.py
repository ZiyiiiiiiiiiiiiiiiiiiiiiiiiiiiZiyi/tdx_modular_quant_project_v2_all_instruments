import pandas as pd

def compute_factor(df, n=5):
    '''
    新闻/舆情模拟: 用成交量异常或收益率异常
    '''
    df = df.copy()
    df['sentiment'] = df.groupby('symbol')['volume'].pct_change(n) * df.groupby('symbol')['close'].pct_change(n)
    return df[['date','symbol','sentiment']]
