"""Browser live monitor for governance backtests."""
from __future__ import annotations

import json
import math
import numbers
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class GovernanceLiveMonitor:
    """Write live backtest state to a browser dashboard process."""

    def __init__(
        self,
        *,
        total_days: int,
        initial_nav: float,
        refresh_every_days: int = 1,
        max_chart_points: int = 1200,
        max_holdings: int = 16,
    ):
        self.total_days = max(int(total_days), 1)
        self.initial_nav = max(float(initial_nav), 1e-12)
        self.refresh_every_days = max(int(refresh_every_days), 1)
        self.max_holdings = max(int(max_holdings), 3)
        self.max_chart_points = max(int(max_chart_points), 100)
        self._closed = False
        self._proc = None
        self._state_path = None
        self._write_failures = 0
        self._write_counter = 0
        self._run_id = ""
        self._title = ""
        self._last_day_index = -1
        self._chart_history: list[dict] = []
        self._last_update_payload: dict = {}
        self._start_browser_monitor()

    @property
    def available(self) -> bool:
        return not self._closed and self._proc is not None and self._proc.poll() is None

    def start_session(self, *, title: str, total_days: int, initial_nav: float) -> None:
        if self._closed:
            return
        self._ensure_monitor_process()
        self._run_id = f"{os.getpid()}_{time.time_ns()}_{id(self)}"
        self._title = str(title)
        self._last_day_index = -1
        self._chart_history = []
        self._last_update_payload = {}
        self.total_days = max(int(total_days), 1)
        self.initial_nav = max(float(initial_nav), 1e-12)
        self._write_state(
            {
                "command": "session",
                "run_id": self._run_id,
                "title": self._title,
                "total_days": self.total_days,
                "initial_nav": self.initial_nav,
                "max_chart_points": self.max_chart_points,
                "max_holdings": self.max_holdings,
            }
        )

    def update(
        self,
        *,
        date,
        exposure: dict,
        day_index: int,
        holdings: list[dict] | None = None,
        monitor_state: dict | None = None,
    ) -> None:
        if self._closed:
            return
        self._ensure_monitor_process()
        nav = float(exposure.get("liquidatable_nav", exposure.get("nominal_nav", 0.0)) or 0.0)
        if nav <= 0:
            return
        if not ((day_index + 1) % self.refresh_every_days == 0 or day_index + 1 >= self.total_days):
            return
        self._last_day_index = max(self._last_day_index, int(day_index))
        progress_pct = min((self._last_day_index + 1) / max(self.total_days, 1) * 100.0, 100.0)
        monitor_values = dict(monitor_state or {})
        chart_point = {
            "date": str(date)[:10],
            "day_index": int(day_index),
            "nav": nav,
            "account_net_value": monitor_values.get("account_net_value"),
            "benchmark_nav": monitor_values.get("benchmark_nav"),
            "excess_net_value": monitor_values.get("excess_net_value"),
            "cash": exposure.get("cash"),
            "invested_value": exposure.get("invested_value"),
            "actual_exposure": exposure.get("actual_exposure", monitor_values.get("actual_exposure")),
        }
        if self._chart_history and self._chart_history[-1].get("day_index") == int(day_index):
            self._chart_history[-1] = chart_point
        else:
            self._chart_history.append(chart_point)
        self._chart_history = self._chart_history[-self.max_chart_points :]
        update_payload = {
                "command": "update",
                "run_id": self._run_id,
                "title": self._title,
                "date": str(date)[:10],
                "exposure": dict(exposure),
                "day_index": int(day_index),
                "total_days": self.total_days,
                "progress_pct": progress_pct,
                "initial_nav": self.initial_nav,
                "holdings": list(holdings or []),
                "monitor_state": monitor_values,
                "chart_history": list(self._chart_history),
            }
        self._last_update_payload = update_payload
        self._write_state(update_payload)

    def report_stage(self, *, step: str, message: str = "", detail: str = "", progress_pct: float = 0.0) -> None:
        if self._closed:
            return
        self._ensure_monitor_process()
        if str(step or "") in {"run_backtest", "process_date", "date_complete"}:
            return
        if not self._run_id:
            self._run_id = f"{os.getpid()}_{time.time_ns()}_{id(self)}"
        bounded_progress = min(max(float(progress_pct or 0.0), 0.0), 100.0)
        stage_payload = dict(self._last_update_payload)
        stage_payload.update(
            {
                "command": "stage",
                "run_id": self._run_id,
                "title": self._title,
                "step": str(step),
                "message": str(message),
                "detail": str(detail),
                "progress_pct": bounded_progress,
                "total_days": self.total_days,
                "initial_nav": self.initial_nav,
            }
        )
        self._write_state(stage_payload)

    def finish(self, message: str | None = None) -> None:
        if self._closed:
            return
        completed_days = max(self._last_day_index + 1, 0)
        progress_pct = min(completed_days / max(self.total_days, 1) * 100.0, 100.0)
        finish_payload = dict(self._last_update_payload)
        finish_payload.update(
            {
                "command": "finish",
                "run_id": self._run_id,
                "title": self._title,
                "day_index": self._last_day_index,
                "total_days": self.total_days,
                "progress_pct": progress_pct,
                "completed": completed_days >= self.total_days,
                "message": message or "回测完成。窗口会保持打开，关闭浏览器标签即可。",
                "chart_history": list(self._chart_history),
            }
        )
        self._write_state(finish_payload)

    def hide(self) -> None:
        # Browser tabs are user-controlled. Kept for compatibility with old callers.
        return

    def show(self) -> None:
        # Browser tabs are user-controlled. Kept for compatibility with old callers.
        return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._write_state({"command": "close"})
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def _start_browser_monitor(self) -> None:
        script_path = Path(__file__).with_name("live_monitor_web.py")
        if not script_path.exists():
            print("治理实时监控已禁用：浏览器监控脚本不存在。")
            self._closed = True
            return
        state_dir = Path(tempfile.gettempdir()) / "tdx_governance_live_monitor"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = state_dir / f"monitor_state_{os.getpid()}.json"
        self._close_existing_monitor_process()
        # Clear the previous session's close command before the new monitor's
        # shutdown watcher starts. Otherwise the new process can exit instantly.
        self._prime_state_for_new_monitor()
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", str(script_path), str(self._state_path)],
                cwd=str(Path(__file__).resolve().parents[2]),
            )
            print("治理实时监控已在外部浏览器模式启动。")
        except Exception as exc:
            self._proc = None
            self._closed = True
            print(f"治理实时监控已禁用：{exc}")

    def _prime_state_for_new_monitor(self) -> None:
        if self._state_path is None:
            return
        self._write_state(
            {
                "command": "idle",
                "run_id": self._run_id,
                "message": "monitor process starting",
                "total_days": self.total_days,
                "initial_nav": self.initial_nav,
            }
        )

    def _ensure_monitor_process(self) -> None:
        if self._closed or self._state_path is None:
            return
        if self._proc is not None and self._proc.poll() is None:
            return
        script_path = Path(__file__).with_name("live_monitor_web.py")
        if not script_path.exists():
            self._closed = True
            return
        self._proc = None
        self._prime_state_for_new_monitor()
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", str(script_path), str(self._state_path)],
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except Exception as exc:
            self._proc = None
            if self._write_failures in {0, 1, 5, 25}:
                print(f"Governance live monitor restart failed: {exc}", flush=True)

    def _write_state(self, payload: dict) -> None:
        if self._state_path is None:
            return
        self._write_counter += 1
        safe_payload = _make_json_safe(payload)
        tmp_path = self._state_path.with_name(
            f"{self._state_path.stem}_{os.getpid()}_{self._write_counter}.tmp"
        )
        last_error = None
        for attempt in range(8):
            try:
                with tmp_path.open("w", encoding="utf-8") as handle:
                    json.dump(safe_payload, handle, ensure_ascii=False)
                os.replace(tmp_path, self._state_path)
                self._write_failures = 0
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.03 * (attempt + 1))
            except OSError as exc:
                last_error = exc
                time.sleep(0.03 * (attempt + 1))
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        self._write_failures += 1
        if self._write_failures in {1, 5, 25}:
            print(
                "治理实时监控跳过了一次状态更新，因为 Windows 锁定了监控文件。"
                f"回测会继续运行。最后错误：{last_error}"
            )

    def _close_existing_monitor_process(self) -> None:
        """Ask any previous monitor for this parent process to exit before launching a new one."""
        if self._state_path is None or not self._state_path.exists():
            return
        tmp_path = self._state_path.with_name(f"{self._state_path.stem}_{os.getpid()}_close.tmp")
        try:
            tmp_path.write_text(json.dumps({"command": "close"}), encoding="utf-8")
            os.replace(tmp_path, self._state_path)
            time.sleep(0.8)
        except Exception:
            pass
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass


def _make_json_safe(value):
    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, Path):
        return str(value)
    text_value = str(value)
    if text_value in {"<NA>", "NaT", "nan", "NaN", "None"}:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return _make_json_safe(value.item())
        except Exception:
            pass
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        text = str(value)
        if text in {"<NA>", "NaT", "nan", "NaN", "None"}:
            return None
        return text
