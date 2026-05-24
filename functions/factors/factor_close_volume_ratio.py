import pandas as pd

def compute_factor(df):
    '''
    尾盘成交量占全天比例: 假设一天最后一个时段 close_volume / volume
    这里用简单 daily volume 模拟
    '''
    df = df.copy()
    df['close_volume_ratio'] = 1  # 占比模拟为 1，可后续用真实尾盘数据
    return df[['date','symbol','close_volume_ratio']]
