# Industrial Governance P0-P7

## Operating Principle

This project uses a serial, low-memory workflow. It does not start parallel
training jobs. The first production target is an auditable research system,
not an automatically activated ML trader.

Run the complete workflow with:

```powershell
& "E:\ForANACONDA\python.exe" main.py
```

The governance-only industrial build is:

```powershell
& "E:\ForANACONDA\python.exe" run_governance_industrial_pipeline.py
```

The industrial builder scans the feature parquet in Arrow batches and trains
the safety candidate on a daily market-state table. It does not load the full
cross-sectional feature table into memory.

## Institutions

| Institution | Responsibility | Activation rule |
|---|---|---|
| Lower house | Alpha proposals and OOF ranking skill | Liquidity-screened shadow portfolio first |
| Senate | Portfolio construction, caps, liquidity, volatility | Active deterministic rules |
| Safety council | Daily risk veto and exposure caps | Rule agent active; calibrated ML agent candidate only |
| President | Select constrained policy parameters | Rules president active |
| Execution office | T+1, suspension, price limits, costs, impact | Active daily proxy |
| Monitoring committee | Reconciliation, rollback and admission | Active deterministic rules |

`PortfolioConstructionCommittee` is explicit. It translates proposals and
risk caps into candidate weights before the president produces executable
orders.

## Phase Status

| Phase | Implemented code | Remaining formal gate |
|---|---|---|
| P0 | Last-known prices, corporate-action fallback, double NAV, persistent liquidation intent | Verified PIT action timestamps |
| P0.5 | Independent daily `shares * mark_price + cash` reconciliation | Full account and tax review |
| P1 | Weekly normal meetings, entry/hold rank buffer, minimum hold, partial adjustment | Cost-calibrated endogenous no-trade region |
| P1.5 | Square-root participation impact proxy and implementation-shortfall proxy | VWAP or higher-frequency calibration |
| P2 | Explicit model congress catalog and existing strategy adapters | OOF shadow comparison |
| P3 | Serial safety dataset, momentum rebound regime, conditional cost matrix, validation-only isotonic calibration | Calibration stability and reviewer sign-off |
| P4 | Shadow and reputation gates | Minimum 252 shadow days |
| P5 | Bounded LinUCB action contract | Shadow-only; promote only after admission |
| P6 | Sell-only initial transition and deterministic rollback recommendation ledger | Paper trading and operational review |
| P7 | Local model registry, manifest, fingerprints, thresholds and references | External independent review and signed formal manifest |

## Safety Training

Safety training is separate from alpha training. The feature set is:

```text
market_return_1d
market_return_5d
market_return_20d
market_volatility_20d
market_liquidity_stress_ratio
momentum_rebound_regime
```

The split is time ordered:

```text
train -> purge(20) -> validation -> embargo(5) -> frozen_test
```

The model is a regularized logistic baseline. Isotonic calibration is fit only
on validation predictions. The calibrated model remains `candidate` until
shadow testing and manual review pass.

False positive and false negative costs are explicit. The missed-crash weight
uses a bounded ratio:

```text
median_crash_drawdown / median_normal_volatility
```

## Rewards

Rewards are institution specific:

- Alpha models: liquidity-screened OOS Rank IC.
- President: liquidatable NAV return and drawdown penalty.
- Safety council: Brier score and asymmetric conditional error cost.
- Execution office: fees, slippage, market impact and opportunity cost.

This prevents portfolio costs from being deducted twice and avoids crediting
all models with the same account return.

## Bandit Constraints

Bandit actions remain `shadow_only`.

- Each action stays within `+/-20%` of the frozen baseline.
- Each action changes at most one dimension.
- Minimum shadow period is `252` trading days.
- Rollback target is always `rules_based_president`.

## Initial Portfolio Transition

For the first `20` governance days:

- New buys are disabled.
- Safety and hard-qualification exits remain allowed.
- Reputation updates are treated as non-admissible diagnostics.
- The system gradually reduces legacy positions before adopting its own target.

## Outputs

Industrial outputs are written under:

```text
results/decision_council_industrial/
```

Key files:

- `model_congress_catalog.csv`
- `safety_daily_dataset.csv`
- `safety_model.json`
- `safety_calibration.csv`
- `safety_evaluation.csv`
- `bandit_action_contract.csv`
- `model_registry.json`
- `monitoring_rollback_policy.json`
- `initial_portfolio_transition_protocol.json`
- `phase_gate_report.csv`
- `industrial_manifest.json`
- `research_references.csv`

The daily governance backtest additionally writes:

- `governance_account_audit_ledger.csv`
- `governance_rollback_recommendation_ledger.csv`
- `governance_corporate_action_ledger.csv`
- Three PNG diagnostic charts

## Research Basis

- Gârleanu and Pedersen, dynamic trading with transaction costs:
  <https://www.nber.org/papers/w15205>
- Gu, Kelly and Xiu, machine learning in asset pricing:
  <https://www.nber.org/papers/w25398>
- Daniel and Moskowitz, momentum crashes:
  <https://www.nber.org/papers/w20439>
- Bailey et al., probability of backtest overfitting:
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>
- Scikit-learn probability calibration:
  <https://scikit-learn.org/stable/modules/calibration.html>
- Scikit-learn time-series split:
  <https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html>
- MLflow model registry:
  <https://mlflow.org/docs/latest/ml/model-registry/>
- Federal Reserve SR 11-7 model risk management:
  <https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- Stanford CS229:
  <https://cs229.stanford.edu/>
- CFA trade strategy and execution:
  <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/trade-strategy-execution>

## Formal Limitation

Code completion is not the same as formal model admission. Formal claims remain
blocked until PIT external timestamps, investable benchmark review, VWAP impact
calibration, shadow history, tax treatment, and independent manual review are
attached and approved.
