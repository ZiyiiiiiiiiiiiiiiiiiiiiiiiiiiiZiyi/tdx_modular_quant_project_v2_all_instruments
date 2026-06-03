# Research Governance

## Two Research Tracks

This project keeps two explicit tracks:

- `exploratory_after_p0_engine`: engineering and research iteration. Results may use incomplete data, but limitations must be disclosed.
- `formal`: controlled comparison. Results are eligible only after PIT data, execution, account, tax, benchmark, review, golden-test, and reproducibility gates pass.

Exploratory results must not be advertised as a formal ranking or as an optimal strategy. A failed formal gate does not stop exploratory engineering; it blocks formal claims and records the reason.

## Roles And Independence

The roles are researcher, strategy developer, data owner, backtest-engine owner, independent reviewer, statistical reviewer, governance owner, and optional external adviser.

The governance owner has veto power over formal release and must not be the strategy owner. A reviewer must not approve a strategy they developed. A statistical reviewer with a conflict of interest must be marked `limited_independence` and reviewed by the governance owner or an independent reviewer.

For a small team, cross-review by a technical owner without a direct interest is allowed, but the result must be marked `limited_independence`. If no external independent review is completed for six consecutive months, or within twelve months after the first formal-candidate submission, the maximum status is `formal_candidate_limited`. Extensions require a recorded governance-owner reason.

## Test Lock

Test results must not be repeatedly consumed. Failed tests must be recorded. A candidate modified after a locked test is `formal_contaminated`; it must be replaced by a new candidate or idea before a new formal attempt.

## Manual Audit

Manual audit must not be self-review. Formal release requires a signed or timestamped governance-owner or independent-reviewer record tied to the reproducibility manifest hash.

## Current Local-Data Scope

Local TDX `.day` bars are sufficient for an honest exploratory track, but they do not prove PIT corporate actions, PIT universe membership, PIT industry classification, investable benchmarks, or independent review. Until those sources and reviews are attached, the runnable fallback is `exploratory_after_p0_engine` with explicit formal block reasons.
