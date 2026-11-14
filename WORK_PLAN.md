# Work plan

This is a forge workflow snapshot. Issue closure and labels establish no fidelity, preset-quality, or hardware qualification claim.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#16**: SXT-023: Implement Delay and EQ
- **#381**: SXT-012 follow-up (#310): implement the one-command carrier reproducibility census per decision record 0019
- **#382**: SXT-012 follow-up (#310): one-factor voice-path diagnostic for the Novuo Reverb 2 carrier (ALL-OFF dry bus)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#167**: Re-grade the 4 STALE SXT-034 spectral_corr artifacts on the oracle host under the #110 definition
- **#382**: SXT-012 follow-up (#310): one-factor voice-path diagnostic for the Novuo Reverb 2 carrier (ALL-OFF dry bus)

## In Progress

Issues currently being built (`loom:building`).

- **#372**: Settle-boundary audit: input-only effect tap so Delay/EQ, Chorus and Reverb 2 get a verdict (split from #318)
- **#475**: RTL: rf_ains34_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **#622**: Regenerate the two drifted tb_voice.sv negative controls and re-derive the T1 item 9 attestation
- **#623**: Fold the three remaining mutant generators onto the shared make_rtl_mutants table (two are byte-attested)
- **#631**: Remove the private build_and_run/main copies in compare_vel_rtl_model.py and compare_pm_rtl_model.py: last two leaf harnesses off the shared run_leaf_comparison path
- **#634**: Remove the five copy-pasted per-leaf RTL harness-reporting test files: fold onto one table-parametrized battery
- **#640**: Remove the nine private copies of the oracle event dispatcher: they silently drop event types rf.dispatch forwards, and one rendered a committed SXT-041 reference
- **#641**: galactic_core: narrow the 128-bit arithmetic so klt synthesize reaches a verdict (NO_VERDICT survives a 1800 s Yosys budget)
- **#649**: docs/byte-frozen-sources.json attested_inventories counts are stale and nothing re-derives them
- **#654**: ablation_delta.py --out <elsewhere> still overwrites the committed reports/sxt-014/ablation-summary.json

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#661**: refactor(rtl): carry galactic_core's arithmetic at integer-exact widths, not 128 bits

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#12**: SXT-017: Freeze profile v1 *(curated)*
- **#16**: SXT-023: Implement Delay and EQ *(curated)*
- **#70**: SXT-036: voice leaf — modulation behavior: velocity *(curated)*
- **#72**: SXT-038: voice leaf — filter algorithm: LP 24 dB *(curated)*
- **#94**: SXT-028c follow-up: pin the tap re-render hash pair for committed reference fixtures *(curated)*
- **#107**: Champion: Merge-Risk Hold Digest *(curated)*
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
- **#475**: RTL: rf_ains34_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN) *(curated)*
- **#497**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#554**: T1 items 2/3/4/11 Phase B: gf180mcu physical flow for the 8 groups blocked on #537 *(curated)*
- **#565**: Rebuild the DR-0006 tap-patched oracle builds (sxt028a-tap, sxt028c-tap) from source with a recorded identity *(curated)*
- **#580**: T1 item 1: logical4_core and rf_* cores expose only block_done, so synthesis removes the datapath *(curated)*
- **#622**: Regenerate the two drifted tb_voice.sv negative controls and re-derive the T1 item 9 attestation *(curated)*
- **#623**: Fold the three remaining mutant generators onto the shared make_rtl_mutants table (two are byte-attested) *(curated)*
- **#641**: galactic_core: narrow the 128-bit arithmetic so klt synthesize reaches a verdict (NO_VERDICT survives a 1800 s Yosys budget) *(curated)*
- **#649**: docs/byte-frozen-sources.json attested_inventories counts are stale and nothing re-derives them *(curated)*
- **#654**: ablation_delta.py --out <elsewhere> still overwrites the committed reports/sxt-014/ablation-summary.json *(curated)*

## Proposed (Architect / Hermit)

- **#635**: Remove never-instantiated fx_line_ext.sv: the SXT-023 'external-memory model' is dead and has drifted from the inline arrays the bench uses *(hermit)*
- **#653**: Remove or finish the fake engine stability leg in compare_lp12_model.py: engine_state_peak_lsb is the model peak under another name *(hermit)*

## Epics

- **#1**: Epic: E1 — Reference, corpus, and product profile
- **#2**: Epic: E2 — Verified core: first complete wet patch
- **#3**: Epic: E3 — Coverage expansion and hardware qualification
- **#331**: SXT-028h/028d/028g: six declared render carriers fail the engine-side per-scene drift gate (measured by #322) — screen drift-0 replacements or record bounded gaps

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 3 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 10 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 0 |
| Curated | 28 |
| Architect / Hermit proposals | 2 |
| Active epics | 4 |
<!-- guide:plan-body:end -->
