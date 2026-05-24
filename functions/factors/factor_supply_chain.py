import pandas as pd

def compute_factor(df, n=5):
    '''
    产业链景气度模拟: 板块均值涨幅
    '''
    df = df.copy()
    # 假设 symbol 前2位是板块，可按板块分组计算平均涨幅
    df['sector'] = df['symbol'].str[:2]
    df['supply_chain'] = df.groupby('sector')['close'].pct_change(n).transform('mean')
    return df[['date','symbol','supply_chain']]
