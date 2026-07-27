"""Static Web contract for SCAP identity, funnel, exits, and reason history."""
from pathlib import Path


root = Path(__file__).resolve().parent
sources = "\n".join(
    [
        (root / "functions/decision_council/live_monitor_dashboard.py").read_text(
            encoding="utf-8"
        ),
        (root / "functions/decision_council/live_monitor_web.py").read_text(
            encoding="utf-8"
        ),
    ]
)
for required in (
    "raw_signal_count",
    "structural_feasible_count",
    "cash_feasible_count",
    "slot_feasible_count",
    "optimizer_selected_entry_count",
    "scap_exit_stage",
    "scap_loss_stop",
    "runtime_identity_hash",
    "loss_containment_exit",
    "reason_history",
):
    assert required in sources, required
print("[PASS] SCAP Web identity/funnel/reason contract")
