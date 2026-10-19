# Work plan

This is a forge workflow snapshot. Issue closure and labels establish no fidelity, preset-quality, or hardware qualification claim.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#437**: Add static Verilator RTL lint gate and RTL classification manifest (#434)
- **#499**: ci: gate committed klt signoff T1 verdict with byte-compare workflow

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#150**: SXT-028j follow-up (F-028j-1/2/3): oracle-host reference leg + re-verify the two declared contracts for the global3/global4 routing leaf
- **#381**: SXT-012 follow-up (#310): implement the one-command carrier reproducibility census per decision record 0019
- **#434**: Add static RTL lint gate (Verilator) and classify product vs sim-only/mutant RTL

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#372**: Settle-boundary audit: input-only effect tap so Delay/EQ, Chorus and Reverb 2 get a verdict (split from #318)
- **#382**: SXT-012 follow-up (#310): one-factor voice-path diagnostic for the Novuo Reverb 2 carrier (ALL-OFF dry bus)

## In Progress

Issues currently being built (`loom:building`).

- **#498**: T1: commit a klt signoff block manifest and gate its verdict in CI

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#437**: Add static Verilator RTL lint gate and RTL classification manifest (#434)
- **#499**: ci: gate committed klt signoff T1 verdict with byte-compare workflow

## Proposed

Issues carrying `loom:curated`.

- **#12**: SXT-017: Freeze profile v1 *(curated)*
- **#16**: SXT-023: Implement Delay and EQ *(curated)*
- **#25**: SXT-019: Reuse substrate adoption decision *(curated)*
- **#70**: SXT-036: voice leaf — modulation behavior: velocity *(curated)*
- **#72**: SXT-038: voice leaf — filter algorithm: LP 24 dB *(curated)*
- **#94**: SXT-028c follow-up: pin the tap re-render hash pair for committed reference fixtures *(curated)*
- **#135**: SXT-028e-sse follow-up: discharge the FuzzTable<1> re-derivation on the pinned arm64/libc++ oracle host *(curated)*
- **#155**: SXT-028l follow-up (F-028l-1/2/3): oracle-host reference leg + re-verify the declared send-routing contracts for the send3/send4 leaf *(curated)*
- **#270**: Re-grade sxt-028a (oracle host) and SXT-028e-sse (glibc host) spectral_corr artifacts left pre-#110 by #165 *(curated)*
- **#305**: Oracle infra gap: no reachable source/build for sxt028c-tap sibling commit (narrower than #232) *(curated)*
- **#307**: Oracle infra gap: no DR-0005-class tap patch/build exists for the LP 24 dB (SXT-038/#101) full-engine leg *(curated)*
- **#310**: SXT-028f follow-up (F-028f-3): SXT-012 fixture policy for source-nondeterministic presets (39/49 Reverb 2 carriers refused by the 3x render gate) *(curated)*
- **#317**: SXT-028e-sse follow-up (F-028e-sse-1): re-run the Distortion SSE reference leg on the arm64 macOS evidence host (rcp_ps is implementation-defined) *(curated)*
- **#318**: Audit every leaf's run_*_model.py for the silent-pre-roll settle boundary measured in #136 (worth 73 dB on one leaf) *(curated)*
- **#331**: SXT-028h/028d/028g: six declared render carriers fail the engine-side per-scene drift gate (measured by #322) — screen drift-0 replacements or record bounded gaps *(curated)*
- **#372**: Settle-boundary audit: input-only effect tap so Delay/EQ, Chorus and Reverb 2 get a verdict (split from #318) *(curated)*
- **#381**: SXT-012 follow-up (#310): implement the one-command carrier reproducibility census per decision record 0019 *(curated)*
- **#382**: SXT-012 follow-up (#310): one-factor voice-path diagnostic for the Novuo Reverb 2 carrier (ALL-OFF dry bus) *(curated)*
- **#426**: SXT-028g: screen same-shape drift-zero Phaser carriers *(curated)*
- **#434**: Add static RTL lint gate (Verilator) and classify product vs sim-only/mutant RTL *(curated)*
- **#473**: RTL: logical4_core has 3 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN) *(curated)*
- **#497**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#498**: T1: commit a klt signoff block manifest and gate its verdict in CI *(curated)*

## Proposed (Architect / Hermit)

- **#172**: Deduplicate byte-identical evidence artifacts in reports/ (~61 MiB redundant) *(hermit)*
- **#369**: Remove rtl/effects/line_zeros.hex: 2.3 MB of identical zero lines replaceable by an init loop *(hermit)*
- **#493**: Consolidate duplicated census_blob / git_blob_sha1 helpers (19 + 13 private copies) into a shared module *(hermit)*
- **#495**: Consolidate duplicated fixture_config override/readback code (classic, sine) *(hermit)*

## Epics

- **#1**: Epic: E1 — Reference, corpus, and product profile
- **#2**: Epic: E2 — Verified core: first complete wet patch
- **#3**: Epic: E3 — Coverage expansion and hardware qualification
- **#331**: SXT-028h/028d/028g: six declared render carriers fail the engine-side per-scene drift gate (measured by #322) — screen drift-0 replacements or record bounded gaps

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Very important | 0 |
| Important | 3 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 2 |
| Curated | 23 |
| Architect / Hermit proposals | 4 |
| Active epics | 4 |
<!-- guide:plan-body:end -->
