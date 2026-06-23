"""Browser live monitor for governance backtests."""
from __future__ import annotations

import json
import math
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
        self._start_browser_monitor()

    @property
    def available(self) -> bool:
        return not self._closed and self._proc is not None

    def start_session(self, *, title: str, total_days: int, initial_nav: float) -> None:
        if self._closed:
            return
        self.total_days = max(int(total_days), 1)
        self.initial_nav = max(float(initial_nav), 1e-12)
        self._write_state(
            {
                "command": "session",
                "title": str(title),
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
        nav = float(exposure.get("liquidatable_nav", exposure.get("nominal_nav", 0.0)) or 0.0)
        if nav <= 0:
            return
        if not ((day_index + 1) % self.refresh_every_days == 0 or day_index + 1 >= self.total_days):
            return
        self._write_state(
            {
                "command": "update",
                "date": str(date)[:10],
                "exposure": dict(exposure),
                "day_index": int(day_index),
                "total_days": self.total_days,
                "initial_nav": self.initial_nav,
                "holdings": list(holdings or []),
                "monitor_state": dict(monitor_state or {}),
            }
        )

    def finish(self, message: str | None = None) -> None:
        if self._closed:
            return
        self._write_state(
            {
                "command": "finish",
                "message": message or "Completed. Browser monitor can stay open.",
            }
        )

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
            print("Live governance monitor disabled: browser monitor script is missing.")
            self._closed = True
            return
        state_dir = Path(tempfile.gettempdir()) / "tdx_governance_live_monitor"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = state_dir / f"monitor_state_{os.getpid()}.json"
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", str(script_path), str(self._state_path)],
                cwd=str(Path(__file__).resolve().parents[2]),
            )
            print("Live governance monitor started in external browser mode.")
        except Exception as exc:
            self._proc = None
            self._closed = True
            print(f"Live governance monitor disabled: {exc}")

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
                "Live governance monitor skipped a state update because Windows locked "
                f"the monitor file. Backtest continues. Last error: {last_error}"
            )


def _make_json_safe(value):
    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value
