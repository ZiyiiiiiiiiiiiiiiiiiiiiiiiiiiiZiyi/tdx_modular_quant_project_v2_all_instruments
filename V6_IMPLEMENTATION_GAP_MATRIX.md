# V6 Implementation Gap Matrix

| Area | Current state | Required action | Verification |
|---|---|---|---|
| Data gate | Exploratory disclosures exist | Add objective `data_verified` gate and watermark | `verify_v6_core.py` |
| PIT index pool | Builder exists; coverage not fully verified | Require CSI300/CSI500/CSI A500 effective-date coverage | data integrity report |
| Signal contract | P0 contract exists | Add event/version/reference fields and timestamp assertions | `verify_position_management_p0.py` |
| Independent events | Partial event data only | Add cooldown-based event IDs and density report | `verify_v6_core.py` |
| Labels | Generic future returns | Add mature cost-after event label contract | `verify_v6_core.py` |
| Win probability | Beta mean with weak prior | Add configurable prior and one-sided lower bound | `verify_v6_core.py` |
| Cold start | Could create positive probability/position | Force neutral probability and zero formal position | P0 verification |
| Payoff ratio | Weighted raw averages | Add fixed 10% trimmed estimates and [1,3] clipping | `verify_v6_core.py` |
| Kelly | Implemented | Use lower-bound probability and 5% single-stock cap | P0 verification |
| Holding robustness | Basic hold/trim/exit | Preserve out-of-pool hold and graded exits | P0 verification |
| Government layer | Existing council and industrial pipeline | Keep portfolio-only authority; do not rewrite Kelly | governance verifications |
| Formal admission | Manual states exist | Produce binary PASS/FAIL; failed data gate blocks all strategies | `verify_v6_core.py` |
| Reporting | Equity, dashboard, heatmaps exist | Apply research watermark while data gate fails | `verify_v6_core.py` |
| External data | stock_ai has provider dependency | Keep provider interpreter separate and disclose mismatch | environment report |

Formal completion is blocked until verified external PIT data and benchmark artifacts pass the objective gates. Code completion must not change failed gates to PASS without evidence.
