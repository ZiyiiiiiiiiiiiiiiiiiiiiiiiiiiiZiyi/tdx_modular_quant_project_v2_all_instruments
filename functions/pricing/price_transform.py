# -*- coding: utf-8 -*-
import pandas as pd


def nominal_to_forward_adjusted(price_series, factor_series):
    prices = pd.to_numeric(price_series, errors="coerce")
    factors = pd.to_numeric(factor_series, errors="coerce")
    return prices * factors


def forward_adjusted_to_nominal(price_series, factor_series):
    prices = pd.to_numeric(price_series, errors="coerce")
    factors = pd.to_numeric(factor_series, errors="coerce").replace(0, pd.NA)
    return prices / factors
