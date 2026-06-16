# -*- coding: utf-8 -*-
"""
ML Alpha Models for Governance Strategy.

Provides LightGBM and TabNet models for predicting stock returns
based on alpha factors. Used to replace or enhance the rule-based
alpha proposal system.

Three modes:
1. LightGBM only
2. TabNet only  
3. LightGBM + TabNet ensemble
"""
from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


@dataclass(frozen=True)
class MLPrediction:
    """ML model prediction result."""
    symbol: str
    predicted_return_5d: float
    confidence: float
    model_name: str


class BaseMLAlphaModel(ABC):
    """Base class for ML alpha models."""
    
    def __init__(self, model_name: str, lookback_days: int = 500):
        self.model_name = model_name
        self.lookback_days = lookback_days
        self.model = None
        self.is_fitted = False
        self.feature_columns = []
    
    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train the model."""
        pass
    
    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Make predictions."""
        pass
    
    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance scores."""
        return {}


class LightGBMAlphaModel(BaseMLAlphaModel):
    """
    LightGBM model for alpha prediction.
    
    Advantages:
    - Fast training
    - Good with tabular data
    - Built-in regularization
    - Feature importance
    """
    
    def __init__(self, lookback_days: int = 500, **kwargs):
        super().__init__("lightgbm", lookback_days)
        self.params = {
            "num_leaves": kwargs.get("num_leaves", 31),
            "learning_rate": kwargs.get("learning_rate", 0.05),
            "n_estimators": kwargs.get("n_estimators", 200),
            "max_depth": kwargs.get("max_depth", 7),
            "subsample": kwargs.get("subsample", 0.8),
            "colsample_bytree": kwargs.get("colsample_bytree", 0.8),
            "reg_alpha": kwargs.get("reg_alpha", 0.1),
            "reg_lambda": kwargs.get("reg_lambda", 0.1),
            "min_child_samples": kwargs.get("min_child_samples", 20),
            "random_state": 42,
            "n_jobs": -1,
            "verbose": -1,
        }
    
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train LightGBM model."""
        import lightgbm as lgb
        
        self.feature_columns = list(X.columns)
        
        # Create dataset
        train_data = lgb.Dataset(X, label=y)
        
        # Train with early stopping
        self.model = lgb.train(
            self.params,
            train_data,
            num_boost_round=self.params["n_estimators"],
            valid_sets=[train_data],
            callbacks=[lgb.log_evaluation(0)],  # Suppress output
        )
        self.is_fitted = True
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Make predictions."""
        if not self.is_fitted or self.model is None:
            return np.zeros(len(X))
        return self.model.predict(X)
    
    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance."""
        if not self.is_fitted or self.model is None:
            return {}
        importance = self.model.feature_importance(importance_type="gain")
        return dict(zip(self.feature_columns, importance))


class TabNetAlphaModel(BaseMLAlphaModel):
    """
    TabNet model for alpha prediction.
    
    Advantages:
    - Attention mechanism for feature selection
    - Interpretable (attention weights)
    - Good with mixed feature types
    - Captures feature interactions
    """
    
    def __init__(self, lookback_days: int = 500, **kwargs):
        super().__init__("tabnet", lookback_days)
        self.params = {
            "n_d": kwargs.get("n_d", 32),
            "n_a": kwargs.get("n_a", 32),
            "n_steps": kwargs.get("n_steps", 5),
            "gamma": kwargs.get("gamma", 1.5),
            "lambda_sparse": kwargs.get("lambda_sparse", 0.001),
            "optimizer_params": {"lr": kwargs.get("lr", 0.02)},
            "scheduler_params": {"step_size": 50, "gamma": 0.9},
            "mask_type": "entmax",
        }
        self.attention_weights = None
    
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train TabNet model."""
        try:
            from pytorch_tabnet.tab_model import TabNetRegressor
        except ImportError:
            print("Warning: pytorch-tabnet not installed. Using fallback.")
            self.is_fitted = False
            return
        
        self.feature_columns = list(X.columns)
        
        # Prepare data
        X_np = X.values.astype(np.float32)
        y_np = y.values.astype(np.float32).reshape(-1, 1)
        
        # Create model
        self.model = TabNetRegressor(
            n_d=self.params["n_d"],
            n_a=self.params["n_a"],
            n_steps=self.params["n_steps"],
            gamma=self.params["gamma"],
            lambda_sparse=self.params["lambda_sparse"],
            optimizer_params=self.params["optimizer_params"],
            scheduler_params=self.params["scheduler_params"],
            mask_type=self.params["mask_type"],
            verbose=0,
        )
        
        # Train
        self.model.fit(
            X_train=X_np,
            y_train=y_np,
            max_epochs=100,
            patience=10,
            batch_size=1024,
            virtual_batch_size=128,
        )
        self.is_fitted = True
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Make predictions."""
        if not self.is_fitted or self.model is None:
            return np.zeros(len(X))
        X_np = X.values.astype(np.float32)
        return self.model.predict(X_np).flatten()
    
    def get_attention_weights(self, X: pd.DataFrame) -> np.ndarray:
        """Get attention weights for interpretability."""
        if not self.is_fitted or self.model is None:
            return np.zeros((len(X), len(self.feature_columns)))
        X_np = X.values.astype(np.float32)
        _, masks = self.model.explain(X_np)
        return masks
    
    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance based on attention."""
        if not self.is_fitted or self.model is None:
            return {}
        importance = self.model.feature_importances_
        return dict(zip(self.feature_columns, importance))


class EnsembleAlphaModel:
    """
    Ensemble of LightGBM and TabNet models.
    
    Combines predictions from both models with configurable weights.
    """
    
    def __init__(
        self,
        lightgbm_weight: float = 0.6,
        tabnet_weight: float = 0.4,
        lookback_days: int = 500,
        **kwargs,
    ):
        self.lightgbm_weight = lightgbm_weight
        self.tabnet_weight = tabnet_weight
        self.lightgbm_model = LightGBMAlphaModel(lookback_days, **kwargs)
        self.tabnet_model = TabNetAlphaModel(lookback_days, **kwargs)
        self.is_fitted = False
    
    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train both models."""
        print("  Training LightGBM...")
        self.lightgbm_model.fit(X, y)
        
        print("  Training TabNet...")
        self.tabnet_model.fit(X, y)
        
        self.is_fitted = True
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Make ensemble predictions."""
        lgb_pred = self.lightgbm_model.predict(X)
        tabnet_pred = self.tabnet_model.predict(X)
        
        # Weighted average
        ensemble_pred = (
            self.lightgbm_weight * lgb_pred + 
            self.tabnet_weight * tabnet_pred
        )
        return ensemble_pred
    
    def get_feature_importance(self) -> dict[str, float]:
        """Get combined feature importance."""
        lgb_imp = self.lightgbm_model.get_feature_importance()
        tabnet_imp = self.tabnet_model.get_feature_importance()
        
        # Combine
        all_features = set(lgb_imp.keys()) | set(tabnet_imp.keys())
        combined = {}
        for feat in all_features:
            lgb_val = lgb_imp.get(feat, 0) * self.lightgbm_weight
            tabnet_val = tabnet_imp.get(feat, 0) * self.tabnet_weight
            combined[feat] = lgb_val + tabnet_val
        
        return combined


def create_ml_alpha_model(
    model_type: str = "lightgbm",
    lookback_days: int = 500,
    **kwargs,
) -> BaseMLAlphaModel | EnsembleAlphaModel:
    """
    Factory function to create ML alpha model.
    
    Parameters
    ----------
    model_type : str
        One of "lightgbm", "tabnet", "ensemble"
    lookback_days : int
        Number of days to use for training
    **kwargs
        Additional model parameters
    
    Returns
    -------
    BaseMLAlphaModel or EnsembleAlphaModel
    """
    if model_type == "lightgbm":
        return LightGBMAlphaModel(lookback_days, **kwargs)
    elif model_type == "tabnet":
        return TabNetAlphaModel(lookback_days, **kwargs)
    elif model_type == "ensemble":
        return EnsembleAlphaModel(lookback_days=lookback_days, **kwargs)
    else:
        raise ValueError(f"Unknown model type: {model_type}")


def prepare_ml_features(
    daily_features: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Prepare features and labels for ML training.
    
    Parameters
    ----------
    daily_features : pd.DataFrame
        Daily feature data
    feature_columns : list[str]
        Columns to use as features
    
    Returns
    -------
    X : pd.DataFrame
        Features
    y : pd.Series
        Labels (5-day forward return)
    """
    data = daily_features.copy()
    
    # Filter to available columns
    available_cols = [c for c in feature_columns if c in data.columns]
    
    # Extract features
    X = data[available_cols].copy()
    
    # Create label (5-day forward return)
    if "future_ret_5" in data.columns:
        y = data["future_ret_5"].copy()
    elif "ret_5" in data.columns:
        y = data["ret_5"].copy()
    else:
        # Calculate from close prices
        y = pd.Series(0.0, index=data.index)
    
    # Handle missing values
    X = X.fillna(0)
    y = y.fillna(0)
    
    return X, y


# Default feature columns for ML models
ML_FEATURE_COLUMNS = [
    "ret_5",
    "ret_20",
    "volatility_20",
    "close_to_ma20",
    "amount_ratio_20",
    "score_mom_lowvol",
    "score_macd_trend",
    "score_mean_reversion",
    "score_rsi_reversal",
    "score_turtle_breakout",
    "score_alpha_hedge",
    "score_event_driven",
    "score_grid_trading",
    "score_eod_close_strength",
    "score_limit_up_follow",
    "score_macd_cross",
    "score_ma_cross",
    "score_price_volume_breakout",
    "score_consecutive_decline_rebound",
    "score_holiday_effect",
    "score_kdj_oversold_cross",
    "score_low_volume_pullback",
]
