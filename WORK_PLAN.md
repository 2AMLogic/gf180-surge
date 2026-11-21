# Work plan

This is a forge workflow snapshot. Issue closure and labels establish no fidelity, preset-quality, or hardware qualification claim.

<!-- guide:plan-body:start -->
_Generated: 2026-11-21T02:44:20Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#16**: SXT-023: Implement Delay and EQ *(held)*

## Important

`loom:important`; taken before unlabelled work.

- **#381**: SXT-012 follow-up (#310): implement the one-command carrier reproducibility census per decision record 0019 *(held)*
- **#382**: SXT-012 follow-up (#310): one-factor voice-path diagnostic for the Novuo Reverb 2 carrier (ALL-OFF dry bus) *(held)*
- **#802**: T1 item 1: re-measure the six NO_VERDICT synthesis groups with the yosys-abc handshake wedge excluded (every log stops at the wedge's signature line; no in-run CPU reading exists)

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#802**: T1 item 1: re-measure the six NO_VERDICT synthesis groups with the yosys-abc handshake wedge excluded (every log stops at the wedge's signature line; no in-run CPU reading exists)

## In Progress

Issues currently being built (`loom:building`).

- **#372**: Settle-boundary audit: input-only effect tap so Delay/EQ, Chorus and Reverb 2 get a verdict (split from #318)
- **#475**: RTL: rf_ains34_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **#634**: Remove the five copy-pasted per-leaf RTL harness-reporting test files: fold onto one table-parametrized battery
- **#803**: T1 item 11: re-run ERC for the three routed groups under klt 0.9.2, which has the gf180mcu antenna table (0.8.0 pin reports not_checked)
- **#804**: T1 item 4: close the ext_mem_instr LVS mismatch (four input pins the router left open) with a bounded P&R iteration

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#12**: SXT-017: Freeze profile v1 *(curated)* *(held)*
- **#16**: SXT-023: Implement Delay and EQ *(curated)* *(held)*
- **#70**: SXT-036: voice leaf — modulation behavior: velocity *(curated)*
- **#72**: SXT-038: voice leaf — filter algorithm: LP 24 dB *(curated)* *(held)*
- **#94**: SXT-028c follow-up: pin the tap re-render hash pair for committed reference fixtures *(curated)* *(held)*
- **#107**: Champion: Merge-Risk Hold Digest *(curated)* *(held)*
- **#135**: SXT-028e-sse follow-up: discharge the FuzzTable<1> re-derivation on the pinned arm64/libc++ oracle host *(curated)* *(held)*
- **#155**: SXT-028l follow-up (F-028l-1/2/3): oracle-host reference leg + re-verify the declared send-routing contracts for the send3/send4 leaf *(curated)* *(held)*
- **#270**: Re-grade sxt-028a (oracle host) and SXT-028e-sse (glibc host) spectral_corr artifacts left pre-#110 by #165 *(curated)* *(held)*
- **#305**: Oracle infra gap: no reachable source/build for sxt028c-tap sibling commit (narrower than #232) *(curated)* *(held)*
- **#307**: Oracle infra gap: no DR-0005-class tap patch/build exists for the LP 24 dB (SXT-038/#101) full-engine leg *(curated)* *(held)*
- **#310**: SXT-028f follow-up (F-028f-3): SXT-012 fixture policy for source-nondeterministic presets (39/49 Reverb 2 carriers refused by the 3x render gate) *(curated)* *(held)*
- **#317**: SXT-028e-sse follow-up (F-028e-sse-1): re-run the Distortion SSE reference leg on the arm64 macOS evidence host (rcp_ps is implementation-defined) *(curated)* *(held)*
- **#318**: Audit every leaf's run_*_model.py for the silent-pre-roll settle boundary measured in #136 (worth 73 dB on one leaf) *(curated)* *(held)*
- **#331**: SXT-028h/028d/028g: six declared render carriers fail the engine-side per-scene drift gate (measured by #322) — screen drift-0 replacements or record bounded gaps *(curated)*
- **#372**: Settle-boundary audit: input-only effect tap so Delay/EQ, Chorus and Reverb 2 get a verdict (split from #318) *(curated)*
- **#381**: SXT-012 follow-up (#310): implement the one-command carrier reproducibility census per decision record 0019 *(curated)* *(held)*
- **#382**: SXT-012 follow-up (#310): one-factor voice-path diagnostic for the Novuo Reverb 2 carrier (ALL-OFF dry bus) *(curated)* *(held)*
- **#475**: RTL: rf_ains34_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN) *(curated)*
- **#497**: Track the gap to T1 (klayout-tools design-evidence-tiers.md) *(curated)*
- **#554**: T1 items 2/3/4/11 Phase B: gf180mcu physical flow for the 8 groups blocked on #537 *(curated)* *(held)*
- **#565**: Rebuild the DR-0006 tap-patched oracle builds (sxt028a-tap, sxt028c-tap) from source with a recorded identity *(curated)* *(held)*
- **#580**: T1 item 1: logical4_core and rf_* cores expose only block_done, so synthesis removes the datapath *(curated)* *(held)*
- **#802**: T1 item 1: re-measure the six NO_VERDICT synthesis groups with the yosys-abc handshake wedge excluded (every log stops at the wedge's signature line; no in-run CPU reading exists) *(curated)*
- **#803**: T1 item 11: re-run ERC for the three routed groups under klt 0.9.2, which has the gf180mcu antenna table (0.8.0 pin reports not_checked) *(curated)*
- **#804**: T1 item 4: close the ext_mem_instr LVS mismatch (four input pins the router left open) with a bounded P&R iteration *(curated)*

## Proposed (Architect / Hermit)

- **#635**: Remove never-instantiated fx_line_ext.sv: the SXT-023 'external-memory model' is dead and has drifted from the inline arrays the bench uses *(hermit)* *(held)*

## Epics

- **#1**: Epic: E1 — Reference, corpus, and product profile *(held)*
- **#2**: Epic: E2 — Verified core: first complete wet patch *(held)*
- **#3**: Epic: E3 — Coverage expansion and hardware qualification *(held)*
- **#331**: SXT-028h/028d/028g: six declared render carriers fail the engine-side per-scene drift gate (measured by #322) — screen drift-0 replacements or record bounded gaps

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 3 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 1 |
| In Progress (`loom:building`) | 5 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 26 |
| Architect / Hermit proposals | 1 |
| Active epics | 4 |
<!-- guide:plan-body:end -->
