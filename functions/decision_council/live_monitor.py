"""Low-memory Tkinter monitor for governance backtests."""
from __future__ import annotations

import math
import time
from collections import deque


class GovernanceLiveMonitor:
    """Render compact live metrics without retaining backtest data frames."""

    def __init__(
        self,
        *,
        total_days: int,
        initial_nav: float,
        refresh_every_days: int = 5,
        min_refresh_seconds: float = 0.25,
        max_chart_points: int = 1200,
    ):
        self.total_days = max(int(total_days), 1)
        self.initial_nav = max(float(initial_nav), 1e-12)
        self.refresh_every_days = max(int(refresh_every_days), 1)
        self.min_refresh_seconds = max(float(min_refresh_seconds), 0.05)
        self._dates = deque(maxlen=max(int(max_chart_points), 100))
        self._net_values = deque(maxlen=self._dates.maxlen)
        self._drawdowns = deque(maxlen=self._dates.maxlen)
        self._returns = deque(maxlen=self._dates.maxlen)
        self._peak_nav = self.initial_nav
        self._max_drawdown = 0.0
        self._previous_nav = None
        self._last_refresh = 0.0
        self._closed = False
        self._root = None
        self._canvas = None
        self._metric_labels = {}
        self._status_var = None
        self._progress_var = None
        self._create_window()

    @property
    def available(self) -> bool:
        return self._root is not None and not self._closed

    def _create_window(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk

            root = tk.Tk()
            root.title("治理回测实时监控 - 低内存模式")
            root.geometry("920x650")
            root.minsize(760, 520)
            root.configure(bg="#f3efe4")
            root.protocol("WM_DELETE_WINDOW", self.close)

            header = tk.Frame(root, bg="#173f35", padx=18, pady=14)
            header.pack(fill="x")
            tk.Label(
                header,
                text="GOVERNANCE LIVE",
                bg="#173f35",
                fg="#f7d774",
                font=("Microsoft YaHei UI", 18, "bold"),
            ).pack(side="left")
            self._status_var = tk.StringVar(value="正在初始化...")
            tk.Label(
                header,
                textvariable=self._status_var,
                bg="#173f35",
                fg="#f7f3e8",
                font=("Microsoft YaHei UI", 10),
            ).pack(side="right")

            metrics = tk.Frame(root, bg="#f3efe4", padx=14, pady=10)
            metrics.pack(fill="x")
            metric_names = (
                ("total_return", "累计收益"),
                ("current_drawdown", "当前回撤"),
                ("max_drawdown", "最大回撤"),
                ("sharpe", "年化 Sharpe"),
                ("annual_volatility", "年化波动"),
                ("nav", "当前净值"),
                ("cash", "现金"),
                ("holdings", "持仓数"),
            )
            for index, (key, title) in enumerate(metric_names):
                card = tk.Frame(metrics, bg="#fffdf7", padx=10, pady=7, highlightthickness=1, highlightbackground="#d6cfbd")
                card.grid(row=index // 4, column=index % 4, padx=4, pady=4, sticky="nsew")
                tk.Label(card, text=title, bg="#fffdf7", fg="#6c675d", font=("Microsoft YaHei UI", 9)).pack()
                label = tk.Label(card, text="--", bg="#fffdf7", fg="#173f35", font=("Consolas", 13, "bold"))
                label.pack()
                self._metric_labels[key] = label
            for column in range(4):
                metrics.grid_columnconfigure(column, weight=1)

            self._canvas = tk.Canvas(root, bg="#fffdf7", highlightthickness=1, highlightbackground="#d6cfbd")
            self._canvas.pack(fill="both", expand=True, padx=18, pady=(2, 10))
            self._progress_var = tk.DoubleVar(value=0.0)
            ttk.Progressbar(root, variable=self._progress_var, maximum=100.0).pack(fill="x", padx=18, pady=(0, 14))
            self._root = root
            root.update_idletasks()
            root.update()
        except Exception as exc:
            self._root = None
            print(f"Live governance monitor disabled: {exc}")

    def update(self, *, date, exposure: dict, day_index: int) -> None:
        if not self.available:
            return
        nav = float(exposure.get("liquidatable_nav", exposure.get("nominal_nav", 0.0)) or 0.0)
        if nav <= 0:
            return
        self._peak_nav = max(self._peak_nav, nav)
        drawdown = nav / self._peak_nav - 1.0
        self._max_drawdown = min(self._max_drawdown, drawdown)
        if self._previous_nav is not None and self._previous_nav > 0:
            self._returns.append(nav / self._previous_nav - 1.0)
        self._previous_nav = nav
        self._dates.append(str(date)[:10])
        self._net_values.append(nav / self.initial_nav)
        self._drawdowns.append(drawdown)

        now = time.monotonic()
        is_last = day_index + 1 >= self.total_days
        if not is_last and (day_index + 1) % self.refresh_every_days and now - self._last_refresh < self.min_refresh_seconds:
            return
        self._last_refresh = now
        total_return = nav / self.initial_nav - 1.0
        annual_volatility, sharpe = self._risk_metrics()
        self._set_metric("total_return", _percent(total_return), total_return)
        self._set_metric("current_drawdown", _percent(drawdown), drawdown)
        self._set_metric("max_drawdown", _percent(self._max_drawdown), self._max_drawdown)
        self._set_metric("sharpe", _number(sharpe), sharpe)
        self._set_metric("annual_volatility", _percent(annual_volatility), -annual_volatility)
        self._set_metric("nav", f"{nav / self.initial_nav:.4f}", total_return)
        self._set_metric("cash", f"{float(exposure.get('cash', 0.0) or 0.0):,.0f}", 0.0)
        self._set_metric("holdings", str(int(exposure.get("holding_count", 0) or 0)), 0.0)
        progress = min((day_index + 1) / self.total_days * 100.0, 100.0)
        self._progress_var.set(progress)
        self._status_var.set(f"{self._dates[-1]}  |  {day_index + 1}/{self.total_days}  |  {progress:.1f}%")
        self._draw_chart()
        try:
            self._root.update_idletasks()
            self._root.update()
        except Exception:
            self.close()

    def _risk_metrics(self) -> tuple[float, float]:
        count = len(self._returns)
        if count < 2:
            return 0.0, float("nan")
        mean_return = sum(self._returns) / count
        variance = sum((value - mean_return) ** 2 for value in self._returns) / count
        daily_volatility = math.sqrt(max(variance, 0.0))
        annual_volatility = daily_volatility * math.sqrt(252.0)
        sharpe = mean_return / daily_volatility * math.sqrt(252.0) if daily_volatility > 1e-12 else float("nan")
        return annual_volatility, sharpe

    def _set_metric(self, key: str, text: str, direction: float) -> None:
        label = self._metric_labels[key]
        color = "#147a54" if direction > 0 else "#b3403a" if direction < 0 else "#173f35"
        label.configure(text=text, fg=color)

    def _draw_chart(self) -> None:
        canvas = self._canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 220)
        left, right, top, bottom = 52, width - 18, 20, height - 30
        split = top + int((bottom - top) * 0.62)
        canvas.create_text(left, top, text="净值", anchor="nw", fill="#6c675d", font=("Microsoft YaHei UI", 9))
        canvas.create_text(left, split + 8, text="回撤", anchor="nw", fill="#6c675d", font=("Microsoft YaHei UI", 9))
        canvas.create_line(left, split, right, split, fill="#d6cfbd")
        self._draw_series(self._net_values, left, right, top + 22, split - 12, "#147a54", baseline=1.0)
        self._draw_series(self._drawdowns, left, right, split + 28, bottom, "#b3403a", baseline=0.0)

    def _draw_series(self, values, left, right, top, bottom, color, *, baseline):
        items = list(values)
        if not items:
            return
        minimum = min(min(items), baseline)
        maximum = max(max(items), baseline)
        padding = max((maximum - minimum) * 0.08, 0.005)
        minimum -= padding
        maximum += padding
        span = max(maximum - minimum, 1e-12)
        count = len(items)
        points = []
        for index, value in enumerate(items):
            x = left if count == 1 else left + (right - left) * index / (count - 1)
            y = bottom - (value - minimum) / span * (bottom - top)
            points.extend((x, y))
        baseline_y = bottom - (baseline - minimum) / span * (bottom - top)
        self._canvas.create_line(left, baseline_y, right, baseline_y, fill="#bdb6a5", dash=(3, 3))
        if len(points) >= 4:
            self._canvas.create_line(*points, fill=color, width=2, smooth=False)
        else:
            self._canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill=color, outline="")
        self._canvas.create_text(right, top, text=f"{maximum:.2%}", anchor="ne", fill="#8b8578", font=("Consolas", 8))
        self._canvas.create_text(right, bottom, text=f"{minimum:.2%}", anchor="se", fill="#8b8578", font=("Consolas", 8))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._root is not None:
            try:
                self._root.destroy()
            except Exception:
                pass
        self._root = None


def _percent(value: float) -> str:
    return "--" if not math.isfinite(value) else f"{value:.2%}"


def _number(value: float) -> str:
    return "--" if not math.isfinite(value) else f"{value:.2f}"
