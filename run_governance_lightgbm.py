# -*- coding: utf-8 -*-
"""
Governance + LightGBM Version
Reuses GovernanceBacktestRunner with ML alpha model injected as a single alpha column.
Output to dated folder to preserve previous results.
"""
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

START_DATE = "2022-01-01"
END_DATE = "2024-12-31"
MODEL_TYPE = "lightgbm"


class ProgressGUI:
    """GUI window showing progress bar and status."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Governance + {MODEL_TYPE.upper()} Backtest")
        self.root.geometry("600x280")
        self.root.resizable(False, False)
        
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.root.winfo_screenheight() // 2) - (280 // 2)
        self.root.geometry(f"600x280+{x}+{y}")
        
        title_label = tk.Label(self.root, text=f"Governance + {MODEL_TYPE.upper()}", font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        self.date_label = tk.Label(self.root, text=f"Date Range: {START_DATE} -> {END_DATE}", font=("Arial", 10))
        self.date_label.pack()
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100, length=560)
        self.progress_bar.pack(pady=10, padx=20)
        
        self.progress_label = tk.Label(self.root, text="0%", font=("Arial", 12))
        self.progress_label.pack()
        
        self.status_label = tk.Label(self.root, text="Initializing...", font=("Arial", 10))
        self.status_label.pack(pady=5)
        
        self.time_label = tk.Label(self.root, text="Elapsed: 0:00:00 | Remaining: calculating...", font=("Arial", 10))
        self.time_label.pack()
        
        self.details_label = tk.Label(self.root, text="", font=("Arial", 9), fg="gray")
        self.details_label.pack(pady=5)
        
        self.cancelled = False
        self.start_time = None
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def on_close(self):
        self.cancelled = True
        self.root.destroy()
    
    def update_progress(self, current, total, status="", details=""):
        if self.cancelled:
            return
        
        if self.start_time is None:
            self.start_time = time.time()
        
        progress = (current / total) * 100 if total > 0 else 0
        self.progress_var.set(progress)
        self.progress_label.config(text=f"{progress:.1f}%")
        self.status_label.config(text=status)
        self.details_label.config(text=details)
        
        elapsed = time.time() - self.start_time
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        
        if current > 0:
            avg_time = elapsed / current
            remaining = avg_time * (total - current)
            remaining_str = str(timedelta(seconds=int(remaining)))
        else:
            remaining_str = "calculating..."
        
        self.time_label.config(text=f"Elapsed: {elapsed_str} | Remaining: {remaining_str}")
        self.root.update_idletasks()


def run_backtest(gui):
    """Run the backtest in a separate thread."""
    try:
        import numpy as np
        import pandas as pd
        from config import (
            FEATURE_DAILY_PARQUET,
            GOVERNANCE_INITIAL_CASH,
            GOVERNANCE_ALPHA_MODELS,
            RESULT_DIR,
            SAFETY_PROXY_MODE,
            ENABLE_MARKET_REGIME_POLICY,
        )
        from functions.decision_council.runner import GovernanceBacktestRunner
        from functions.decision_council.ml_alpha_models import (
            LightGBMAlphaModel,
            ML_FEATURE_COLUMNS,
            prepare_ml_features,
        )
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = RESULT_DIR / f"governance_{MODEL_TYPE}_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        gui.root.after(0, lambda: gui.update_progress(0, 100, "Loading features...", "Reading parquet file..."))
        
        import pyarrow.parquet as pq
        schema = pq.read_schema(FEATURE_DAILY_PARQUET)
        needed = [
            "date", "symbol", "instrument_type", "close", "close_nominal",
            "open", "open_nominal", "amount", "amount_ma20",
            "is_trading", "abnormal_jump", "rough_limit_up", "rough_limit_down",
            "volatility_20", "ret_5", "ret_20",
            "sector_parent", "sector_parent_heat",
            "score_mom_lowvol", "close_to_ma20",
            "score_macd_trend", "score_mean_reversion", "score_rsi_reversal",
            "score_turtle_breakout", "score_alpha_hedge", "score_event_driven",
            "score_grid_trading", "score_eod_close_strength", "score_limit_up_follow",
            "score_macd_cross", "score_ma_cross", "score_price_volume_breakout",
            "score_consecutive_decline_rebound", "score_holiday_effect",
            "score_kdj_oversold_cross", "score_low_volume_pullback",
            "future_ret_5",
        ]
        cols = [c for c in needed if c in schema.names]
        features = pd.read_parquet(
            FEATURE_DAILY_PARQUET,
            columns=cols,
            filters=[
                ("date", ">=", pd.Timestamp(START_DATE)),
                ("date", "<=", pd.Timestamp(END_DATE)),
            ],
        )
        
        dates = pd.Index(features["date"].drop_duplicates().sort_values())
        dates = dates[(dates >= pd.Timestamp(START_DATE)) & (dates <= pd.Timestamp(END_DATE))]
        total_days = len(dates)
        
        gui.root.after(0, lambda: gui.update_progress(0, total_days, "Training LightGBM...", f"Processing {total_days} trading days"))
        
        ml_model = LightGBMAlphaModel(lookback_days=500)
        available_features = [c for c in ML_FEATURE_COLUMNS if c in features.columns]
        
        # Pre-compute ML scores for all dates
        gui.root.after(0, lambda: gui.update_progress(0, total_days, "Pre-computing ML scores...", "This may take a few minutes"))
        
        features["score_ml_alpha"] = np.zeros(len(features), dtype=np.float32)
        for day_index, date in enumerate(dates):
            if gui.cancelled:
                return
            
            daily = features[features["date"] == pd.Timestamp(date)].copy()
            if daily.empty:
                continue
            
            # Train model periodically
            if day_index % 21 == 0:
                train_start = max(0, day_index - 500)
                train_dates = dates[train_start:day_index]
                train_data = features[features["date"].isin(train_dates)]
                
                if len(train_data) > 240:
                    X_train, y_train = prepare_ml_features(train_data, available_features)
                    ml_model.fit(X_train, y_train)
            
            # Predict
            if ml_model.is_fitted:
                X_daily, _ = prepare_ml_features(daily, available_features)
                predictions = ml_model.predict(X_daily)
                mask = features["date"] == pd.Timestamp(date)
                features.loc[mask, "score_ml_alpha"] = predictions.astype(np.float32)
            
            if day_index % 50 == 0:
                gui.root.after(0, lambda i=day_index: gui.update_progress(i, total_days, "Pre-computing ML scores...", f"Day {i}/{total_days}"))
        
        # Add ml_alpha to alpha models list
        ml_alpha_models = tuple(dict.fromkeys(GOVERNANCE_ALPHA_MODELS + ("ml_alpha",)))
        
        gui.root.after(0, lambda: gui.update_progress(0, total_days, "Running governance backtest...", f"Using {len(ml_alpha_models)} alpha models"))
        
        # Create runner with ML alpha model included
        runner = GovernanceBacktestRunner(
            features,
            initial_cash=GOVERNANCE_INITIAL_CASH,
            safety_proxy_mode=SAFETY_PROXY_MODE,
            output_dir=output_dir,
            enable_reputation=True,
            enable_sector_cap=False,
            enable_safety_agent=True,
            enable_market_regime_policy=ENABLE_MARKET_REGIME_POLICY,
            alpha_models=ml_alpha_models,
            prepared_features=True,  # Features already prepared
        )
        
        # Run backtest
        for day_index, date in enumerate(dates):
            if gui.cancelled:
                break
            
            runner.step(date, day_index)
            
            date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
            nav = runner.exposure_rows[-1].get("nominal_nav", 0) if runner.exposure_rows else 0
            holding_count = len(runner.positions)
            
            gui.root.after(0, lambda d=date_str, n=nav, h=holding_count, i=day_index:
                          gui.update_progress(i + 1, total_days, f"Processing: {d}", f"NAV: {n:,.0f} | Holdings: {h}"))
        
        if not gui.cancelled:
            gui.root.after(0, lambda: gui.update_progress(total_days, total_days, "Saving results...", "Writing output files..."))
            runner._save()
            
            # Compute metrics
            from functions.decision_council.ml_metrics import compute_all_metrics, save_metrics_json, format_metrics_report
            
            metrics = compute_all_metrics(output_dir, start_date=START_DATE, end_date=END_DATE)
            save_metrics_json(metrics, output_dir / "run_summary.json")
            
            report = format_metrics_report(metrics, f"Governance + {MODEL_TYPE.upper()}")
            print(report)
            
            ret = metrics.get("total_return", 0)
            sharpe = metrics.get("sharpe", 0)
            calmar = metrics.get("calmar", 0)
            sortino = metrics.get("sortino", 0)
            max_dd = metrics.get("max_drawdown", 0)
            win_rate = metrics.get("win_rate", 0)
            pbo = metrics.get("pbo", np.nan)
            
            pbo_str = f"{pbo:.1%}" if not np.isnan(pbo) else "N/A"
            msg = f"Return: {ret:.2%} | Sharpe: {sharpe:.3f} | Calmar: {calmar:.3f} | MaxDD: {max_dd:.2%}"
            details = f"Sortino: {sortino:.3f} | Win Rate: {win_rate:.1%} | PBO: {pbo_str} | Saved to: {output_dir}"
            gui.root.after(0, lambda: gui.update_progress(total_days, total_days, msg, details))
            
            while not gui.cancelled:
                time.sleep(1)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_message = f"Error: {str(e)}"
        gui.root.after(0, lambda msg=error_message: gui.update_progress(0, 100, msg, "Check console for details"))


def main():
    gui = ProgressGUI()
    thread = threading.Thread(target=run_backtest, args=(gui,), daemon=True)
    thread.start()
    gui.root.mainloop()


if __name__ == "__main__":
    main()
