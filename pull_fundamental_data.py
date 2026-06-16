# -*- coding: utf-8 -*-
"""
Pull fundamental financial data from akshare and compute fundamental factors.
Saves to parquet for integration with existing features.

Factors computed:
1. pe_percentile: PE ratio percentile (relative to history)
2. pb_percentile: PB ratio percentile (relative to history)
3. roe_rank: ROE rank (cross-sectional)
4. revenue_growth: Revenue growth rate
5. debt_ratio: Asset-liability ratio
6. eps_stability: EPS stability (lower = more stable)
"""
import sys
import time
import random
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# Output paths
OUTPUT_DIR = PROJECT_DIR / "data" / "processed"
FUNDAMENTAL_PARQUET = OUTPUT_DIR / "fundamental_factors.parquet"


def get_stock_list():
    """Get all A-share stock codes."""
    import akshare as ak
    stock_info = ak.stock_info_a_code_name()
    # Filter for main board stocks (6-digit codes)
    stocks = stock_info[stock_info['code'].str.len() == 6].copy()
    stocks = stocks[stocks['code'].str.match(r'^[036]\d{5}$')]
    return stocks['code'].tolist()


def pull_single_stock_financial(symbol: str) -> dict:
    """Pull financial data for a single stock."""
    import akshare as ak
    
    result = {
        'symbol': symbol,
        'eps': None,
        'bvps': None,
        'roe': None,
        'revenue': None,
        'net_profit': None,
        'debt_ratio': None,
        'data_date': None,
    }
    
    try:
        # Pull financial indicators
        fin = ak.stock_financial_analysis_indicator(symbol=symbol, start_year='2020')
        if len(fin) > 0:
            latest = fin.iloc[0]
            result['eps'] = _safe_float(latest.get('摊薄每股收益(元)'))
            result['bvps'] = _safe_float(latest.get('每股净资产_调整后(元)'))
            result['roe'] = _safe_float(latest.get('净资产收益率_摊薄(%)'))
            result['debt_ratio'] = _safe_float(latest.get('资产负债率'))
            result['data_date'] = str(latest.get('日期', ''))
    except Exception as e:
        pass
    
    try:
        # Pull income statement for revenue
        income = ak.stock_financial_report_sina(stock=symbol, symbol='利润表')
        if len(income) > 0:
            latest = income.iloc[0]
            result['revenue'] = _safe_float(latest.get('营业总收入'))
            result['net_profit'] = _safe_float(latest.get('净利润'))
    except Exception as e:
        pass
    
    return result


def _safe_float(val):
    """Safely convert value to float."""
    if val is None or pd.isna(val):
        return None
    try:
        if isinstance(val, str):
            val = val.replace(',', '').replace('万', 'e4').replace('亿', 'e8')
        return float(val)
    except:
        return None


def compute_fundamental_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Compute fundamental factors from raw financial data."""
    
    # PE = Price / EPS
    df['pe'] = df['close'] / df['eps'].replace(0, np.nan)
    df['pe'] = df['pe'].clip(-1000, 1000)  # Cap extreme values
    
    # PB = Price / BVPS
    df['pb'] = df['close'] / df['bvps'].replace(0, np.nan)
    df['pb'] = df['pb'].clip(-1000, 1000)
    
    # PE Percentile (within each date)
    df['pe_percentile'] = df.groupby('date')['pe'].rank(pct=True)
    
    # PB Percentile (within each date)
    df['pb_percentile'] = df.groupby('date')['pb'].rank(pct=True)
    
    # ROE Rank (within each date)
    df['roe_rank'] = df.groupby('date')['roe'].rank(pct=True)
    
    # Revenue Growth (year-over-year, using quarterly data)
    df['revenue_growth'] = df.groupby('symbol')['revenue'].pct_change(4)  # 4 quarters
    
    # Debt Ratio (already a percentage)
    df['debt_ratio_normalized'] = df['debt_ratio'] / 100.0
    
    # EPS Stability (rolling std / mean over 4 quarters)
    df['eps_stability'] = df.groupby('symbol')['eps'].transform(
        lambda x: x.rolling(4, min_periods=2).std() / x.rolling(4, min_periods=2).mean().abs()
    )
    
    # Value Score (lower PE + lower PB = better value)
    df['value_score'] = (1 - df['pe_percentile']) * 0.5 + (1 - df['pb_percentile']) * 0.5
    
    # Quality Score (higher ROE + lower debt = better quality)
    df['quality_score'] = df['roe_rank'] * 0.6 + (1 - df['debt_ratio_normalized'].clip(0, 1)) * 0.4
    
    # Growth Score (higher revenue growth = better)
    df['growth_score'] = df['revenue_growth'].clip(-1, 5).rank(pct=True)
    
    # Composite Fundamental Score
    df['score_fundamental'] = (
        df['value_score'] * 0.3 +
        df['quality_score'] * 0.4 +
        df['growth_score'] * 0.3
    )
    
    return df


def main():
    print("=" * 80)
    print("FUNDAMENTAL DATA PULLING & FACTOR COMPUTATION")
    print("=" * 80)
    
    # Step 1: Get stock list
    print("\n[1/4] Getting stock list...")
    stocks = get_stock_list()
    print(f"  Found {len(stocks)} stocks")
    
    # Step 2: Pull financial data
    print("\n[2/4] Pulling financial data (this will take ~3 hours)...")
    print("  Using random delay 1-3s to prevent blocking...")
    
    results = []
    start_time = time.time()
    
    for i, stock in enumerate(stocks):
        try:
            # Random delay to prevent blocking
            delay = random.uniform(1, 2)
            time.sleep(delay)
            
            data = pull_single_stock_financial(stock)
            results.append(data)
            
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                eta = (elapsed / (i + 1)) * (len(stocks) - i - 1)
                print(f"  [{i+1}/{len(stocks)}] ETA: {eta/60:.1f} min")
                
                # Save intermediate results
                if (i + 1) % 1000 == 0:
                    pd.DataFrame(results).to_parquet(
                        OUTPUT_DIR / f"fundamental_raw_{i+1}.parquet", index=False
                    )
                    print(f"  Saved intermediate results")
                    
        except KeyboardInterrupt:
            print("\n  Interrupted! Saving partial results...")
            break
        except Exception as e:
            print(f"  Error on {stock}: {str(e)[:50]}")
            continue
    
    # Save raw results
    raw_df = pd.DataFrame(results)
    raw_df.to_parquet(OUTPUT_DIR / "fundamental_raw.parquet", index=False)
    print(f"\n  Saved {len(raw_df)} stocks to fundamental_raw.parquet")
    
    # Step 3: Merge with existing features
    print("\n[3/4] Merging with existing features...")
    
    # Load existing features
    features = pd.read_parquet(OUTPUT_DIR / "tdx_daily_features.parquet")
    print(f"  Loaded {len(features)} rows from tdx_daily_features.parquet")
    
    # Get unique dates and symbols
    dates = features['date'].unique()
    symbols = features['symbol'].unique()
    
    # Create a mapping from symbol to financial data
    symbol_fin = raw_df.set_index('symbol').to_dict('index')
    
    # For each row in features, add financial data
    # Note: Financial data is quarterly, so we use the latest available
    financial_rows = []
    
    for date in dates:
        for symbol in symbols:
            if symbol in symbol_fin:
                fin = symbol_fin[symbol]
                financial_rows.append({
                    'date': date,
                    'symbol': symbol,
                    'eps': fin.get('eps'),
                    'bvps': fin.get('bvps'),
                    'roe': fin.get('roe'),
                    'revenue': fin.get('revenue'),
                    'net_profit': fin.get('net_profit'),
                    'debt_ratio': fin.get('debt_ratio'),
                })
    
    fin_df = pd.DataFrame(financial_rows)
    
    # Merge with features
    features = features.merge(fin_df, on=['date', 'symbol'], how='left')
    
    # Step 4: Compute factors
    print("\n[4/4] Computing fundamental factors...")
    features = compute_fundamental_factors(features)
    
    # Save updated features
    features.to_parquet(OUTPUT_DIR / "tdx_daily_features.parquet", index=False)
    print(f"\n  Saved updated features to tdx_daily_features.parquet")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Stocks processed: {len(raw_df)}")
    print(f"New columns added:")
    print(f"  - pe, pb, roe, revenue, net_profit, debt_ratio")
    print(f"  - pe_percentile, pb_percentile, roe_rank")
    print(f"  - revenue_growth, debt_ratio_normalized, eps_stability")
    print(f"  - value_score, quality_score, growth_score")
    print(f"  - score_fundamental (composite)")
    print(f"\nTotal columns: {len(features.columns)}")


if __name__ == "__main__":
    main()
