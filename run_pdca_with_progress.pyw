# -*- coding: utf-8 -*-
"""
PDCA Governance Run with GUI Progress Window.
Double-click to run - shows a popup with progress bar and time estimation.
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


class ProgressGUI:
    """GUI window showing progress bar and status."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PDCA Governance Backtest")
        self.root.geometry("600x300")
        self.root.resizable(False, False)
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.root.winfo_screenheight() // 2) - (300 // 2)
        self.root.geometry(f"600x300+{x}+{y}")
        
        # Title
        title_label = tk.Label(self.root, text="PDCA Governance Backtest", font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        # Status frame
        status_frame = tk.Frame(self.root)
        status_frame.pack(pady=5, padx=20, fill="x")
        
        # Date range
        self.date_label = tk.Label(status_frame, text="Date Range: 2022-01-01 -> 2024-12-31", font=("Arial", 10))
        self.date_label.pack(anchor="w")
        
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
        
        # Control buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)
        
        self.cancel_button = tk.Button(button_frame, text="Cancel", command=self.cancel, width=10)
        self.cancel_button.pack(side="left", padx=5)
        
        # State
        self.cancelled = False
        self.start_time = None
        self.total_steps = 0
        self.current_step = 0
    
    def update_progress(self, current, total, status="", details=""):
        """Update progress bar and labels."""
        self.current_step = current
        self.total_steps = total
        
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
    
    def cancel(self):
        """Cancel the backtest."""
        self.cancelled = True
        self.status_label.config(text="Cancelling...")
        self.root.update_idletasks()
    
    def close(self):
        """Close the window."""
        self.root.destroy()
    
    def run(self):
        """Start the GUI main loop."""
        self.root.mainloop()


def run_backtest(gui):
    """Run the backtest in a separate thread."""
    try:
        import pandas as pd
        from config import (
            ENABLE_MARKET_REGIME_POLICY,
            FEATURE_DAILY_PARQUET,
            GOVERNANCE_ALPHA_CANDIDATE_LIMIT,
            GOVERNANCE_ALPHA_MODELS,
            GOVERNANCE_INITIAL_CASH,
            RESULT_DIR,
            SAFETY_PROXY_MODE,
        )
        from functions.decision_council.runner import GovernanceBacktestRunner, ProgressTracker
        
        # Dated output folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = RESULT_DIR / f"pdca_governance_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        start_date = "2022-01-01"
        end_date = "2024-12-31"
        
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
        
        gui.root.after(0, lambda: gui.update_progress(0, 100, "Features loaded", f"{len(features)} rows, {len(features.columns)} columns"))
        
        # Get total days
        dates = pd.Index(features["date"].drop_duplicates().sort_values())
        dates = dates[(dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))]
        total_days = len(dates)
        
        # Run backtest with custom progress callback
        gui.root.after(0, lambda: gui.update_progress(0, total_days, "Starting backtest...", f"Processing {total_days} trading days"))
        
        # Create runner
        runner = GovernanceBacktestRunner(
            features,
            initial_cash=GOVERNANCE_INITIAL_CASH,
            safety_proxy_mode=SAFETY_PROXY_MODE,
            output_dir=output_dir,
            enable_reputation=True,
            enable_sector_cap=True,
            enable_safety_agent=True,
            enable_market_regime_policy=ENABLE_MARKET_REGIME_POLICY,
        )
        
        # Run with progress updates
        for day_index, date in enumerate(dates):
            if gui.cancelled:
                gui.root.after(0, lambda: gui.update_progress(day_index, total_days, "Cancelled", "User cancelled the backtest"))
                break
            
            # Run one day
            runner.step(date, day_index)
            
            # Update progress
            date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
            nav = runner.exposure_rows[-1].get("nominal_nav", 0) if runner.exposure_rows else 0
            holding_count = len(runner.positions)
            
            gui.root.after(0, lambda d=date_str, n=nav, h=holding_count, i=day_index: 
                          gui.update_progress(i + 1, total_days, f"Processing: {d}", f"NAV: {n:,.0f} | Holdings: {h}"))
        
        if not gui.cancelled:
            # Save results
            gui.root.after(0, lambda: gui.update_progress(total_days, total_days, "Saving results...", "Writing output files..."))
            runner._save()
            
            gui.root.after(0, lambda: gui.update_progress(total_days, total_days, "Complete!", f"Results saved to: {output_dir}"))
            
            # Keep window open for 5 seconds then close
            time.sleep(5)
            gui.root.after(0, gui.close)
    
    except Exception as e:
        gui.root.after(0, lambda: gui.update_progress(0, 100, f"Error: {str(e)}", "Check error log for details"))
        import traceback
        traceback.print_exc()


def main():
    # Create GUI
    gui = ProgressGUI()
    
    # Start backtest in separate thread
    thread = threading.Thread(target=run_backtest, args=(gui,), daemon=True)
    thread.start()
    
    # Run GUI
    gui.run()


if __name__ == "__main__":
    main()
