# factor_ml.py
import pandas as pd
from sklearn.linear_model import ElasticNet
import xgboost as xgb
import lightgbm as lgb

def compute_factor(df_factors, target_col=None, model_type='elasticnet'):
    """
    ML 综合因子: 根据 model_type 生成 score_ml
    df_factors: DataFrame, 包含因子列
    target_col: 可选, 拟合目标列
    model_type: 'elasticnet', 'xgboost', 'lightgbm'
    """
    df = df_factors.copy()
    factor_cols = [col for col in df.select_dtypes(include=[float, int]).columns if col not in ['date', 'symbol']]
    X = df[factor_cols].fillna(0)

    if target_col is None:
        y = df['momentum'] if 'momentum' in df.columns else X.mean(axis=1)
    else:
        y = df[target_col].fillna(0)

    if model_type == 'elasticnet':
        model = ElasticNet()
        model.fit(X, y)
        df['score_ml'] = model.predict(X)
    elif model_type == 'xgboost':
        model = xgb.XGBRegressor(objective='reg:squarederror', n_estimators=100)
        model.fit(X, y)
        df['score_ml'] = model.predict(X)
    elif model_type == 'lightgbm':
        model = lgb.LGBMRegressor(n_estimators=100)
        model.fit(X, y)
        df['score_ml'] = model.predict(X)
    else:
        raise ValueError("model_type must be 'elasticnet', 'xgboost', or 'lightgbm'")

    return df[['date','symbol','score_ml']]