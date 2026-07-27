"""Read-only browser dashboard for an already-running SCAP console log."""
from __future__ import annotations

import argparse
import ctypes
import html
import json
import re
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROGRESS_PATTERN = re.compile(
    r"(?P<percent>[0-9.]+)% \((?P<current>\d+)/(?P<total>\d+)\)"
    r" \| Elapsed: (?P<elapsed>.*?)"
    r" \| Remaining: (?P<remaining>.*?)"
    r" \| Date: (?P<date>[0-9-]+)"
    r" \| NAV: (?P<nav>[0-9,]+)"
    r" \| Holdings: (?P<holdings>\d+)"
)

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SCAP-V1 长窗进度</title>
<style>
body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#0f1715;color:#e7f0ec;margin:0}
main{max-width:900px;margin:36px auto;padding:24px}.card{background:#18231f;border:1px solid #30453d;border-radius:14px;padding:24px}
h1{font-size:23px;margin:0 0 8px}.muted{color:#91a49d}.bar{height:18px;background:#293832;border-radius:12px;overflow:hidden;margin:24px 0 10px}
#fill{height:100%;background:#56bd91;width:0;transition:width .4s}.pct{font-size:34px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}.item{background:#111b18;border-radius:10px;padding:14px}
.label{color:#91a49d;font-size:12px}.value{font-size:18px;margin-top:6px;word-break:break-word}
#health.ok{color:#71d6a8}#health.stale{color:#f2b56b}#health.done{color:#9fb2ff}
@media(max-width:700px){.grid{grid-template-columns:1fr 1fr}main{margin:0;padding:14px}}
</style></head><body><main><div class="card">
<h1>SCAP-V1：2025-01 至 2026-05</h1><div class="muted">只读监控，不会修改或停止回测</div>
<div class="bar"><div id="fill"></div></div><div class="pct" id="percent">--</div>
<div class="grid">
<div class="item"><div class="label">运行状态</div><div class="value" id="health">--</div></div>
<div class="item"><div class="label">交易日进度</div><div class="value" id="count">--</div></div>
<div class="item"><div class="label">预计剩余</div><div class="value" id="eta">--</div></div>
<div class="item"><div class="label">已运行</div><div class="value" id="elapsed">--</div></div>
<div class="item"><div class="label">最新日期</div><div class="value" id="date">--</div></div>
<div class="item"><div class="label">NAV / 持仓</div><div class="value" id="account">--</div></div>
<div class="item"><div class="label">日志最后更新</div><div class="value" id="updated">--</div></div>
<div class="item"><div class="label">主进程 PID</div><div class="value" id="pid">--</div></div>
<div class="item"><div class="label">错误日志</div><div class="value" id="error">--</div></div>
</div></div></main>
<script>
async function poll(){try{const r=await fetch('/api/status?x='+Date.now(),{cache:'no-store'});const s=await r.json();
const p=Number(s.percent||0);document.getElementById('fill').style.width=p+'%';document.getElementById('percent').textContent=p.toFixed(1)+'%';
document.getElementById('count').textContent=s.current+' / '+s.total;document.getElementById('eta').textContent=s.remaining;
document.getElementById('elapsed').textContent=s.elapsed;document.getElementById('date').textContent=s.date;
document.getElementById('account').textContent='¥'+s.nav+' / '+s.holdings+'只';document.getElementById('updated').textContent=s.log_updated;
document.getElementById('pid').textContent=s.pid;document.getElementById('error').textContent=s.error_bytes===0?'无错误输出':s.error_bytes+' bytes';
const h=document.getElementById('health');h.textContent=s.health_text;h.className=s.health_class;
}catch(e){const h=document.getElementById('health');h.textContent='网页读取失败：'+e;h.className='stale'}setTimeout(poll,3000)}poll();
</script></body></html>"""


def process_exists(pid: int) -> bool:
    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information, False, int(pid)
    )
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def read_status(log_path: Path, error_path: Path, pid: int) -> dict:
    text = log_path.read_text(encoding="utf-8-sig", errors="replace") if log_path.exists() else ""
    matches = list(PROGRESS_PATTERN.finditer(text))
    latest = matches[-1].groupdict() if matches else {
        "percent": "0", "current": "0", "total": "0", "elapsed": "--",
        "remaining": "--", "date": "--", "nav": "--", "holdings": "--",
    }
    modified = log_path.stat().st_mtime if log_path.exists() else 0.0
    age = max(time.time() - modified, 0.0)
    alive = process_exists(pid)
    current = int(latest.get("current", 0) or 0)
    total = int(latest.get("total", 0) or 0)
    progress_complete = total > 0 and current >= total
    if progress_complete:
        health_text, health_class = "运行完成，请读取正式结果", "done"
        alive = False
    elif not alive:
        health_text, health_class = "主进程已结束，请检查退出码", "done"
    elif age > 900:
        health_text, health_class = f"运行中，但日志已{int(age // 60)}分钟未刷新", "stale"
    else:
        health_text, health_class = "运行中，日志持续更新", "ok"
    return {
        **latest,
        "pid": pid,
        "alive": alive,
        "health_text": health_text,
        "health_class": health_class,
        "log_updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(modified)) if modified else "--",
        "log_age_seconds": age,
        "error_bytes": error_path.stat().st_size if error_path.exists() else 0,
    }


def pick_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--error-log", required=True, type=Path)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--endpoint", required=True, type=Path)
    args = parser.parse_args()
    port = pick_port()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/status"):
                body = json.dumps(read_status(args.log, args.error_log, args.pid), ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path in {"/", "/index.html"}:
                body = PAGE.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    args.endpoint.write_text(
        json.dumps({"url": f"http://127.0.0.1:{port}/", "pid": args.pid}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(html.escape(f"http://127.0.0.1:{port}/"), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
