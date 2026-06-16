import json, sys
sys.path.insert(0, r'F:\通信达量化\tdx_modular_quant_project_v2_all_instruments')
import numpy as np
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(r'F:\通信达量化\tdx_modular_quant_project_v2_all_instruments\results\pdca_governance_cycles')
all_cycles = []
for i in range(1, 11):
    path = OUTPUT_DIR / f'cycle_{i:02d}' / 'pdca_cycle.json'
    if path.exists():
        with open(path, encoding='utf-8') as f:
            all_cycles.append(json.load(f))

lines = [
    '# PDCA Governance Research Report',
    '',
    f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
    f'Cycles: {len(all_cycles)}',
    '',
    '## Cycle Results',
    '',
    '| Cycle | Window | Return | Sharpe | Calmar | Sortino | Max DD | Win Rate | Accuracy |',
    '|-------|--------|--------|--------|--------|---------|--------|----------|----------|',
]

returns, sharpes, calmars, sortinos, drawdowns, win_rates, accuracies = [], [], [], [], [], [], []
for c in all_cycles:
    m = c.get('metrics', {})
    a = c.get('accuracy', {})
    if not m:
        lines.append(f"| {c['cycle']} | {c['start_date']} -> {c['end_date']} | FAILED | - | - | - | - | - | - |")
        continue
    ret = m.get('total_return', 0)
    sh = m.get('sharpe', 0)
    cal = m.get('calmar', 0)
    sor = m.get('sortino', 0)
    dd = m.get('max_drawdown', 0)
    wr = m.get('win_rate', 0)
    acc = a.get('overall_accuracy', 0)
    returns.append(ret)
    sharpes.append(sh)
    calmars.append(cal)
    sortinos.append(sor)
    drawdowns.append(dd)
    win_rates.append(wr)
    accuracies.append(acc)
    lines.append(f"| {c['cycle']} | {c['start_date']} -> {c['end_date']} | {ret:.2%} | {sh:.3f} | {cal:.3f} | {sor:.3f} | {dd:.2%} | {wr:.1%} | {acc:.1%} |")

lines.extend(['', '## Recommendations', ''])
for c in all_cycles:
    lines.append(f"- Cycle {c['cycle']} ({c['start_date']} -> {c['end_date']}): {c.get('recommendation', 'N/A')}")

if returns:
    lines.extend(['', '## Aggregate Statistics', '', '| Metric | Mean | Std | Min | Max |', '|--------|------|-----|-----|-----|'])
    for name, arr in [('Return', returns), ('Sharpe', sharpes), ('Calmar', calmars), ('Sortino', sortinos), ('Max DD', drawdowns), ('Win Rate', win_rates), ('Accuracy', accuracies)]:
        lines.append(f'| {name} | {np.mean(arr):.3f} | {np.std(arr):.3f} | {np.min(arr):.3f} | {np.max(arr):.3f} |')

    lines.extend(['', '## Conclusions', ''])
    mean_acc = np.mean(accuracies)
    mean_sharpe = np.mean(sharpes)
    mean_dd = np.mean(drawdowns)
    mean_calmar = np.mean(calmars)
    mean_sortino = np.mean(sortinos)

    lines.append(f"- Average accuracy: {mean_acc:.1%}")
    lines.append(f"- Average Sharpe: {mean_sharpe:.3f}")
    lines.append(f"- Average Calmar: {mean_calmar:.3f}")
    lines.append(f"- Average Sortino: {mean_sortino:.3f}")
    lines.append(f"- Average max drawdown: {mean_dd:.2%}")
    lines.append(f"- Cycles with positive return: {sum(1 for r in returns if r > 0)}/{len(returns)}")
    lines.append(f"- Cycles with accuracy > 50%: {sum(1 for a in accuracies if a > 0.5)}/{len(accuracies)}")

report = '\n'.join(lines)
(OUTPUT_DIR / 'pdca_governance_final_report.md').write_text(report, encoding='utf-8')
print(report)
