"""Read-only Web viewer for held-stock, per-factor score curves."""
from __future__ import annotations

import argparse
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SCAP持仓逐因子曲线</title>
<style>
:root{--bg:#07111f;--panel:#0f1c2e;--line:#243853;--text:#e8f0fb;--muted:#9fb1c7;--accent:#52d3aa;--warn:#ffbd59}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Microsoft YaHei,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:18px}.head{display:flex;justify-content:space-between;gap:12px;align-items:center}
h1{font-size:22px;margin:0}.sub{color:var(--muted);font-size:13px;margin-top:5px}.controls,.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:14px}
.grid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:10px}label{font-size:12px;color:var(--muted)}
select,button{width:100%;margin-top:5px;background:#13243a;color:var(--text);border:1px solid #355071;border-radius:7px;padding:9px}
button{cursor:pointer;color:#07111f;background:var(--accent);font-weight:700}.factor-list{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:5px;max-height:210px;overflow:auto;margin-top:12px}
.factor{background:#101f32;border-radius:5px;padding:5px;font-size:12px;color:var(--text)}.factor input{vertical-align:middle}
canvas{width:100%;height:430px;background:#0a1626;border-radius:8px}.small canvas{height:260px}.status{color:var(--warn);font-size:12px;margin-top:8px}
@media(max-width:900px){.grid,.factor-list{grid-template-columns:1fr 1fr}}@media(max-width:560px){.grid,.factor-list{grid-template-columns:1fr}}
</style></head>
<body><div class="wrap">
<div class="head"><div><h1>SCAP 持仓股票逐因子评分曲线</h1><div class="sub">只读事后诊断；单因子 predicted_return_5d，不是综合评分，不进入交易决策。</div></div></div>
<div class="controls"><div class="grid">
<div><label>股票</label><select id="symbol"></select></div>
<div><label>指标</label><select id="metric"><option value="predicted_return_5d">因子5日预测收益</option><option value="weighted_factor_score">因子×声誉权重</option><option value="reputation_weight">声誉权重</option><option value="weight_share">组合权重占比</option></select></div>
<div><label>角色过滤</label><select id="role"><option value="">全部角色</option></select></div>
<div><label>快捷选择</label><select id="quick"><option value="top12">波动最大12个</option><option value="all">全部因子</option><option value="none">清空</option></select></div>
<div><label>独立窗口</label><button id="open">打开当前股票新窗口</button></div>
</div><div class="factor-list" id="factors"></div><div class="status" id="status"></div></div>
<div class="panel"><canvas id="factorChart" width="1400" height="430"></canvas></div>
<div class="panel small"><canvas id="holdingChart" width="1400" height="260"></canvas></div>
</div>
<script>
const colors=["#52d3aa","#ffbd59","#69a7ff","#ff718b","#b58cff","#3dd6e5","#b6df57","#ff8f4c","#d8dce7","#ef6fe8","#7edc9b","#9b8cff","#ffd166","#55c1ff","#f78fb3","#c7f464"];
let meta=null;
const $=id=>document.getElementById(id);
const pageParams=new URLSearchParams(location.search);
function apiUrl(path,params=null){const q=new URLSearchParams(params||{});if(pageParams.get("key"))q.set("key",pageParams.get("key"));const text=q.toString();return text?`${path}?${text}`:path}
function selectedFactors(){return [...document.querySelectorAll('#factors input:checked')].map(x=>x.value)}
function draw(canvas,dates,series,title,percent=true){
 const c=$(canvas),x=c.getContext("2d"),W=c.width,H=c.height,p={l:75,r:20,t:40,b:48};x.clearRect(0,0,W,H);x.fillStyle="#0a1626";x.fillRect(0,0,W,H);
 const vals=series.flatMap(s=>s.values.filter(v=>Number.isFinite(v)));if(!vals.length){x.fillStyle="#9fb1c7";x.fillText("无可绘制数据",30,50);return}
 let lo=Math.min(...vals),hi=Math.max(...vals);if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;
 x.strokeStyle="#243853";x.fillStyle="#9fb1c7";x.font="12px Segoe UI";x.textAlign="right";
 for(let i=0;i<=5;i++){const y=p.t+(H-p.t-p.b)*i/5,v=hi-(hi-lo)*i/5;x.beginPath();x.moveTo(p.l,y);x.lineTo(W-p.r,y);x.stroke();x.fillText(percent?(v*100).toFixed(2)+"%":v.toFixed(3),p.l-8,y+4)}
 x.textAlign="center";for(let i=0;i<dates.length;i+=Math.max(1,Math.floor(dates.length/7))){const xx=p.l+(W-p.l-p.r)*i/Math.max(dates.length-1,1);x.fillText(dates[i],xx,H-18)}
 series.forEach((s,k)=>{x.strokeStyle=colors[k%colors.length];x.lineWidth=1.7;x.beginPath();let started=false;s.values.forEach((v,i)=>{if(!Number.isFinite(v)){started=false;return};const xx=p.l+(W-p.l-p.r)*i/Math.max(dates.length-1,1),yy=p.t+(hi-v)/(hi-lo)*(H-p.t-p.b);if(!started){x.moveTo(xx,yy);started=true}else{x.lineTo(xx,yy)}});x.stroke()});
 x.textAlign="left";x.font="bold 14px Segoe UI";x.fillStyle="#e8f0fb";x.fillText(title,p.l,22);
 x.font="11px Segoe UI";series.slice(0,16).forEach((s,k)=>{const col=k%4,row=Math.floor(k/4);x.fillStyle=colors[k%colors.length];x.fillRect(p.l+col*315,p.t+row*17,10,3);x.fillStyle="#c9d5e5";x.fillText(s.name.slice(0,38),p.l+14+col*315,p.t+4+row*17)})
}
async function load(){
 try{
  const response=await fetch(apiUrl('/api/meta'),{cache:'no-store'});
  const payload=await response.json();
  if(response.status===202||payload.status==="pending"){
   $("status").textContent=payload.message||"运行尚未保存完成，逐因子曲线会在保存阶段自动出现。";
   setTimeout(load,2000);return;
  }
  if(!response.ok)throw new Error(payload.message||`HTTP ${response.status}`);
  meta=payload;$("symbol").innerHTML="";$("role").options.length=1;
  meta.symbols.forEach(s=>$("symbol").add(new Option(s,s)));meta.roles.forEach(s=>$("role").add(new Option(s,s)));
  const q=new URLSearchParams(location.search);if(q.get("symbol")&&meta.symbols.includes(q.get("symbol")))$("symbol").value=q.get("symbol");
  renderFactorList();
  if(!meta.symbols.length){
   $("status").textContent="本次窗口没有产生持仓，因此没有可绘制的持仓逐因子曲线；这不是页面故障。";
   draw("factorChart",[],[],"持仓逐因子曲线",true);
   draw("holdingChart",[],[],"持仓收益曲线",true);
   return;
  }
  await refresh();
 }catch(err){
  $("status").textContent=`逐因子数据连接中：${err.message||err}`;
  setTimeout(load,2500);
 }
}
function renderFactorList(){
 const role=$("role").value,all=meta.factors.filter(f=>!role||f.role===role);$("factors").innerHTML=all.map(f=>`<label class="factor"><input type="checkbox" value="${f.name}"> ${f.name} <span style="color:#7890aa">[${f.role||"--"}]</span></label>`).join("");
 applyQuick();
}
function applyQuick(){const mode=$("quick").value,top=new Set((meta.top_by_symbol[$("symbol").value]||[]));document.querySelectorAll('#factors input').forEach(x=>x.checked=mode==="all"||(mode==="top12"&&top.has(x.value)))}
async function refresh(){
 const fs=selectedFactors();$("status").textContent=`载入 ${$("symbol").value}：${fs.length}个因子`;
 const q={symbol:$("symbol").value,metric:$("metric").value,factors:fs.join("|")};const d=await fetch(apiUrl('/api/series',q)).then(r=>r.json());
 draw("factorChart",d.dates,d.series,`${d.symbol} · ${d.metric}`,d.metric!=="reputation_weight"&&d.metric!=="weight_share");
 draw("holdingChart",d.holding_dates,[{name:"持仓未实现收益",values:d.unrealized_return}],`${d.symbol} · 持仓收益曲线`,true);
 $("status").textContent=`${d.symbol}｜${d.dates.length}个交易日｜${d.series.length}条因子曲线｜原始数据完整覆盖`;
}
$("symbol").onchange=()=>{renderFactorList();refresh()};$("metric").onchange=refresh;$("role").onchange=()=>{renderFactorList();refresh()};$("quick").onchange=()=>{applyQuick();refresh()};
$("factors").onchange=refresh;$("open").onclick=()=>window.open('/?symbol='+encodeURIComponent($("symbol").value),'_blank');
load();
</script></body></html>"""


class FactorStore:
    def __init__(self, data_dir: Path):
        self.data = pd.read_csv(
            data_dir / "holding_factor_scores_long.csv",
            low_memory=False,
        )
        self.holdings = pd.read_csv(data_dir / "holding_daily.csv", low_memory=False)
        self.data["date"] = self.data["date"].astype(str)
        self.holdings["date"] = self.holdings["date"].astype(str)
        self.symbols = sorted(self.data["symbol"].dropna().astype(str).unique())
        factor_meta = (
            self.data[["model_name", "factor_role", "factor_module"]]
            .dropna(subset=["model_name"])
            .drop_duplicates("model_name")
            .sort_values("model_name")
        )
        self.factors = [
            {
                "name": str(row.model_name),
                "role": "" if pd.isna(row.factor_role) else str(row.factor_role),
                "module": "" if pd.isna(row.factor_module) else str(row.factor_module),
            }
            for row in factor_meta.itertuples(index=False)
        ]
        self.roles = sorted({row["role"] for row in self.factors if row["role"]})
        self.top_by_symbol = {}
        for symbol, rows in self.data.groupby("symbol"):
            ranked = (
                rows.groupby("model_name")["predicted_return_5d"]
                .std()
                .fillna(0.0)
                .sort_values(ascending=False)
                .head(12)
            )
            self.top_by_symbol[str(symbol)] = [str(value) for value in ranked.index]

    def meta(self) -> dict:
        return {
            "symbols": self.symbols,
            "factors": self.factors,
            "roles": self.roles,
            "top_by_symbol": self.top_by_symbol,
            "contract": "post_run_read_only_no_decision_authority",
        }

    def series(self, symbol: str, metric: str, factors: list[str]) -> dict:
        allowed = {
            "predicted_return_5d",
            "weighted_factor_score",
            "reputation_weight",
            "weight_share",
        }
        if metric not in allowed:
            metric = "predicted_return_5d"
        rows = self.data[self.data["symbol"].astype(str).eq(symbol)].copy()
        if factors:
            rows = rows[rows["model_name"].astype(str).isin(factors)]
        pivot = rows.pivot_table(
            index="date",
            columns="model_name",
            values=metric,
            aggfunc="last",
        ).sort_index()
        dates = [str(value) for value in pivot.index]
        output_series = []
        for column in pivot.columns:
            values = [
                None if pd.isna(value) else float(value)
                for value in pivot[column].tolist()
            ]
            output_series.append({"name": str(column), "values": values})
        held = (
            self.holdings[self.holdings["symbol"].astype(str).eq(symbol)]
            .sort_values("date")
            .drop_duplicates("date", keep="last")
        )
        return {
            "symbol": symbol,
            "metric": metric,
            "dates": dates,
            "series": output_series,
            "holding_dates": held["date"].astype(str).tolist(),
            "unrealized_return": [
                None if pd.isna(value) else float(value)
                for value in pd.to_numeric(held["unrealized_return"], errors="coerce")
            ],
        }


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _pick_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    store = FactorStore(args.data_dir.resolve())
    port = _pick_port()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/meta":
                _json(self, store.meta())
                return
            if parsed.path == "/api/series":
                query = parse_qs(parsed.query)
                default_symbol = store.symbols[0] if store.symbols else ""
                symbol = str(query.get("symbol", [default_symbol])[0])
                metric = str(query.get("metric", ["predicted_return_5d"])[0])
                factors = [
                    item
                    for item in str(query.get("factors", [""])[0]).split("|")
                    if item
                ]
                if not store.symbols:
                    _json(
                        {
                            "message": "本次窗口没有产生持仓，暂无逐因子曲线。",
                            "symbol": "",
                            "metric": metric,
                            "dates": [],
                            "series": [],
                            "holding_dates": [],
                            "unrealized_return": [],
                        }
                    )
                    return
                if symbol not in store.symbols:
                    _json(self, {"message": "unknown symbol"}, status=404)
                    return
                _json(self, store.series(symbol, metric, factors))
                return
            if parsed.path == "/api/health":
                _json(self, {"status": "ok", "port": port, **store.meta()})
                return
            self.send_error(404)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    payload = {"url": f"http://127.0.0.1:{port}/", "port": port}
    if args.state_file:
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        args.state_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
