# -*- coding: utf-8 -*-
"""
Single PDCA Governance Run for 2022-2024 with all alpha models.
Output to dated folder to preserve previous results.
Auto-launches progress popup window.
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


class ProgressGUI:
    """GUI window showing progress bar and status."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PDCA Governance Backtest")
        self.root.geometry("600x280")
        self.root.resizable(False, False)
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.root.winfo_screenheight() // 2) - (280 // 2)
        self.root.geometry(f"600x280+{x}+{y}")
        
        # Title
        title_label = tk.Label(self.root, text="PDCA Governance Backtest", font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        # Date range
        self.date_label = tk.Label(self.root, text=f"Date Range: {START_DATE} -> {END_DATE}", font=("Arial", 10))
        self.date_label.pack()
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100, length=560)
        self.progress_bar.pack(pady=10, padx=20)
        
        # Progress text
        self.progress_label = tk.Label(self.root, text="0%", font=("Arial", 12))
        self.progress_label.pack()
        
        # Status info
        self.status_label = tk.Label(self.root, text="Initializing...", font=("Arial", 10))
        self.status_label.pack(pady=5)
        
        # Time info
        self.time_label = tk.Label(self.root, text="Elapsed: 0:00:00 | Remaining: calculating...", font=("Arial", 10))
        self.time_label.pack()
        
        # Details
        self.details_label = tk.Label(self.root, text="", font=("Arial", 9), fg="gray")
        self.details_label.pack(pady=5)
        
        # State
        self.cancelled = False
        self.start_time = None
        
        # Bind close button
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def on_close(self):
        """Handle window close."""
        self.cancelled = True
        self.root.destroy()
    
    def update_progress(self, current, total, status="", details=""):
        """Update progress bar and labels."""
        if self.cancelled:
            return
        
        if self.start_time is None:
            self.start_time = time.time()
        
        # Calculate progress
        progress = (current / total) * 100 if total > 0 else 0
        self.progress_var.set(progress)
        
        # Update labels
        self.progress_label.config(text=f"{progress:.1f}%")
        self.status_label.config(text=status)
        self.details_label.config(text=details)
        
        # Calculate time
        elapsed = time.time() - self.start_time
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        
        if current > 0:
            avg_time = elapsed / current
            remaining = avg_time * (total - current)
            remaining_str = str(timedelta(seconds=int(remaining)))
        else:
            remaining_str = "calculating..."
        
        self.time_label.config(text=f"Elapsed: {elapsed_str} | Remaining: {remaining_str}")
        
        # Update window
        self.root.update_idletasks()
    
    def close(self):
        """Close the window."""
        try:
            self.root.destroy()
        except:
            pass


def run_backtest(gui):
    """Run the backtest in a separate thread."""
    try:
        import pandas as pd
        import numpy as np
        from config import (
            ENABLE_MARKET_REGIME_POLICY,
            FEATURE_DAILY_PARQUET,
            GOVERNANCE_INITIAL_CASH,
            RESULT_DIR,
            SAFETY_PROXY_MODE,
        )
        from functions.decision_council.runner import GovernanceBacktestRunner
        
        # Dated output folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = RESULT_DIR / f"pdca_governance_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load features
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
        ]
        cols = [c for c in needed if c in schema.names]
        features = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=cols)
        
        # Get total days
        dates = pd.Index(features["date"].drop_duplicates().sort_values())
        dates = dates[(dates >= pd.Timestamp(START_DATE)) & (dates <= pd.Timestamp(END_DATE))]
        total_days = len(dates)
        
        gui.root.after(0, lambda: gui.update_progress(0, total_days, "Starting backtest...", f"Processing {total_days} trading days"))
        
        # Create runner
        runner = GovernanceBacktestRunner(
            features,
            initial_cash=GOVERNANCE_INITIAL_CASH,
            safety_proxy_mode=SAFETY_PROXY_MODE,
            output_dir=output_dir,
            enable_reputation=True,
            enable_sector_cap=False,
            enable_safety_agent=True,
            enable_market_regime_policy=ENABLE_MARKET_REGIME_POLICY,
        )
        
        # Run with progress updates
        for day_index, date in enumerate(dates):
            if gui.cancelled:
                gui.root.after(0, lambda: gui.update_progress(day_index, total_days, "Cancelled", "User cancelled the backtest"))
                return
            
            # Run one day
            runner.step(date, day_index)
            
            # Update progress every day
            date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
            nav = runner.exposure_rows[-1].get("nominal_nav", 0) if runner.exposure_rows else 0
            holding_count = len(runner.positions)
            
            gui.root.after(0, lambda d=date_str, n=nav, h=holding_count, i=day_index: 
                          gui.update_progress(i + 1, total_days, f"Processing: {d}", f"NAV: {n:,.0f} | Holdings: {h}"))
        
        if not gui.cancelled:
            # Save results
            gui.root.after(0, lambda: gui.update_progress(total_days, total_days, "Saving results...", "Writing output files..."))
            runner._save()
            
            # Compute metrics
            daily_path = output_dir / "governance_daily_result.csv"
            
            metrics = {}
            
            if daily_path.exists():
                data = pd.read_csv(daily_path)
                if not data.empty:
                    data["date"] = pd.to_datetime(data["date"])
                    nav = pd.to_numeric(data["nominal_nav"], errors="coerce").dropna()
                    if len(nav) >= 10:
                        nav = nav / float(nav.iloc[0])
                        daily_ret = nav.pct_change().fillna(0.0)
                        total_return = float(nav.iloc[-1] - 1)
                        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0
                        win_rate = float((daily_ret > 0).mean())
                        metrics = {"total_return": total_return, "sharpe": sharpe, "win_rate": win_rate}
            
            # Show completion message
            msg = f"Complete! Return: {metrics.get('total_return', 0):.2%} | Sharpe: {metrics.get('sharpe', 0):.3f}"
            gui.root.after(0, lambda: gui.update_progress(total_days, total_days, msg, f"Saved to: {output_dir}"))
            
            # Keep window open
            while not gui.cancelled:
                time.sleep(1)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_message = f"Error: {str(e)}"
        gui.root.after(0, lambda msg=error_message: gui.update_progress(0, 100, msg, "Check console for details"))


def main():
    # Create GUI
    gui = ProgressGUI()
    
    # Start backtest in separate thread
    thread = threading.Thread(target=run_backtest, args=(gui,), daemon=True)
    thread.start()
    
    # Run GUI (blocks until window is closed)
    gui.root.mainloop()


if __name__ == "__main__":
    main()
