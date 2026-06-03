# Governance P0-P1.5 Rules Baseline

This revision is an exploratory rules baseline. It is designed to make
accounting, execution, and turnover behavior auditable before ML safety models
or bandit policies are admitted.

## Implemented Boundaries

- Missing daily quotes use the last known nominal close. They never become
  zero-price marks. Stale marks are disclosed and receive a configurable
  liquidatable-NAV haircut after five business days.
- Available corporate actions are applied with an explicit
  `exploratory_action_date_fallback` mode. The current BaoStock artifact lacks
  verified announcement, record, and payment timestamps, so results remain
  exploratory.
- Normal portfolio meetings occur weekly. Safety review remains daily.
- Entry rank is frozen at `20`; hold rank is frozen at `100`; the minimum
  holding period is `5` trading days.
- Normal turnover budget is `5%` per meeting day and ordinary order deltas are
  adjusted by `25%`. Safety, hard qualification, and alpha-collapse exits keep
  their exception path.
- Tradable proposals are restricted to stocks and ETF funds with at least
  `1,000,000` daily and rolling-20-day amount.
- Execution costs include an uncalibrated square-root participation proxy.
  The proxy must be validated against VWAP or higher-resolution execution data
  before formal use.

The rank thresholds are temporary frozen values. After execution-cost
calibration they should be replaced by an endogenous no-trade region.

## New Outputs

- `governance_account_audit_ledger.csv`
- `governance_corporate_action_ledger.csv`
- `governance_performance_risk.png`
- `governance_model_reputation_scores.png`
- `governance_safety_forced_deleveraging_points.png`

`governance_account_audit_ledger.csv` must report zero reconciliation error on
every date before longer backtests are interpreted.

## Local Verification

```powershell
& "E:\ForANACONDA\python.exe" verify_governance_p0_p1_5.py
& "E:\ForANACONDA\python.exe" verify_decision_council_phase_one.py
& "E:\ForANACONDA\python.exe" verify_decision_council_stress.py
```

Running `main.py` without arguments still executes the complete restartable
workflow. The new P0-P1.5 verification stage is included automatically.
