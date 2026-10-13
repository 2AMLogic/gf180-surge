# Work plan

This is a forge workflow snapshot. Issue closure and labels establish no fidelity, preset-quality, or hardware qualification claim.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#368**: LP24 full-engine observation tap, external host route (#307)
- **#397**: SXT-020: reject contradictory/unsupported patch-image versions (#391)

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

- **#150**: SXT-028j follow-up (F-028j-1/2/3): oracle-host reference leg + re-verify the two declared contracts for the global3/global4 routing leaf

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#307**: Oracle infra gap: no DR-0005-class tap patch/build exists for the LP 24 dB (SXT-038/#101) full-engine leg

## In Progress

Issues currently being built (`loom:building`).

- **#135**: SXT-028e-sse follow-up: discharge the FuzzTable<1> re-derivation on the pinned arm64/libc++ oracle host

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#368**: LP24 full-engine observation tap, external host route (#307)
- **#397**: SXT-020: reject contradictory/unsupported patch-image versions (#391)

## Proposed

Issues carrying `loom:curated`.

- **#12**: SXT-017: Freeze profile v1 *(curated)*
- **#16**: SXT-023: Implement Delay and EQ *(curated)*
- **#70**: SXT-036: voice leaf — modulation behavior: velocity *(curated)*
- **#72**: SXT-038: voice leaf — filter algorithm: LP 24 dB *(curated)*
- **#94**: SXT-028c follow-up: pin the tap re-render hash pair for committed reference fixtures *(curated)*
- **#135**: SXT-028e-sse follow-up: discharge the FuzzTable<1> re-derivation on the pinned arm64/libc++ oracle host *(curated)*
- **#155**: SXT-028l follow-up (F-028l-1/2/3): oracle-host reference leg + re-verify the declared send-routing contracts for the send3/send4 leaf *(curated)*
- **#167**: Re-grade the 4 STALE SXT-034 spectral_corr artifacts on the oracle host under the #110 definition *(curated)*
- **#172**: Deduplicate byte-identical evidence artifacts in reports/ (~61 MiB redundant) *(curated)*
- **#270**: Re-grade sxt-028a (oracle host) and SXT-028e-sse (glibc host) spectral_corr artifacts left pre-#110 by #165 *(curated)*
- **#305**: Oracle infra gap: no reachable source/build for sxt028c-tap sibling commit (narrower than #232) *(curated)*
- **#307**: Oracle infra gap: no DR-0005-class tap patch/build exists for the LP 24 dB (SXT-038/#101) full-engine leg *(curated)*
- **#310**: SXT-028f follow-up (F-028f-3): SXT-012 fixture policy for source-nondeterministic presets (39/49 Reverb 2 carriers refused by the 3x render gate) *(curated)*
- **#317**: SXT-028e-sse follow-up (F-028e-sse-1): re-run the Distortion SSE reference leg on the arm64 macOS evidence host (rcp_ps is implementation-defined) *(curated)*
- **#318**: Audit every leaf's run_*_model.py for the silent-pre-roll settle boundary measured in #136 (worth 73 dB on one leaf) *(curated)*
- **#329**: SXT-043 fixture: clear osc-1 p[] modulation routings before Sine override so Digibass reference is valid (follow-up to #311) *(curated)*
- **#391**: SXT-020: reject contradictory binary and JSON patch-image versions *(curated)*

## Proposed (Architect / Hermit)

- **#401**: package.json test/check:ci/check:all scripts exit 0 with no checks run (NOT_RUN reads as PASS) *(architect)*
- **#172**: Deduplicate byte-identical evidence artifacts in reports/ (~61 MiB redundant) *(hermit)*
- **#265**: Remove duplicated sha256(path) helper: 5 copies in tools/ instead of one shared module *(hermit)*
- **#272**: Remove duplicated sha256_file(path) reimplementation: 7 copies already have a canonical oracle_common.sha256_file *(hermit)*
- **#369**: Remove rtl/effects/line_zeros.hex: 2.3 MB of identical zero lines replaceable by an init loop *(hermit)*

## Epics

- **#1**: Epic: E1 — Reference, corpus, and product profile
- **#2**: Epic: E2 — Verified core: first complete wet patch
- **#3**: Epic: E3 — Coverage expansion and hardware qualification

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Operator priority | 1 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 17 |
| Architect / Hermit proposals | 5 |
| Active epics | 3 |
<!-- guide:plan-body:end -->
