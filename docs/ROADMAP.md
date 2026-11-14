# gf180-surge roadmap

A hardware canary for a Surge XT subset synthesis engine on the gf180mcu open
PDK: RTL that must match a frozen fixed-point model exactly, a model graded
against the pinned Surge engine, and physical-flow evidence graded by `klt signoff`.

Status as of 2026-11-13, `main` @ `7de0a780`.

A reading aid only: it establishes no fidelity, synthesis, hardware or
preset-quality claim. Labels and PR states are as read on 2026-11-13.

## Where it stands

**Fidelity and coverage (backlog DAG, `docs/dag.json`, rendered in the README).**
26 nodes: 14 PASS, 11 BLOCKED, 1 IN PROGRESS.

- PASS on committed evidence under `reports/`: native oracle, patch graphs,
  render fixtures, resource accounting, cost probes, patch-image compiler,
  timed control, first dry voice slice, Reverb1, leaf generation, effect
  expansion and the coverage publication. Seven pass with a recorded
  prerequisite waiver.
- `reports/coverage-v1/README.md` is the headline: of 3,561 corpus entries,
  **0 supported**, 164 adapted, 1,132 unsupported, 2,265 unresolved. No
  complete-wet integration record is PASS and no listening record exists.
- BLOCKED: the profile freeze (#12), Delay and EQ (#16), and the nodes for
  favorites, effects contribution, one complete wet preset, wavetable, FPGA
  and gf180 qualification.

**T1 evidence (`signoff/block-manifest.signoff.json`, tracker #497).**
`klt signoff` reads 2 of 11 items `met`:

| Item | State | Evidence or blocker |
|---|---|---|
| 1 Design sources | unmet, partial | `signoff/t1-item1/README.md`: 5 of 11 product groups synthesize, 4 attested; 6 are NO_VERDICT (#580, #641) |
| 2 Layout, 3 DRC, 4 LVS | unmet, partial | `signoff/t1-physical/README.md`: 3 of 11 groups routed; DRC clean on the curated deck for all 3; LVS match on 2, mismatch on `ext_mem_instr` |
| 5 Corner verification, 6 statistical, 8 characterization | unmet | need the frozen profile (#12) |
| 7 Post-layout verification | unmet | needs routed netlists for all groups |
| 9 Testbenches shipped | **met** | `signoff/t1-item9-attestation.json` |
| 10 Repo hygiene | **met** | `signoff/item-10.attestation.json` |
| 11 Power delivery | unmet | ERC reads `not_checked`: klt 0.8.0 has no gf180mcu antenna table |

Merged since 2026-11-08: evidence-tool consolidation (#603 to #665) and the
`galactic_core` synthesis measurement (#642).

## Now

1. **Narrow `galactic_core` arithmetic** (#641, PR #661 in review). Done when
   `rtl/effects/aw-49/galactic_core.sv` has no 128-bit operator, stays exact
   against the frozen model, and its `RECORD.md` records the re-run outcome.
2. **Regenerate the two drifted `tb_voice.sv` negative controls** (#622, PR
   #636, changes requested). Done when both mutants are single-line, the
   generator `--check` passes, and item 9 is re-attested.
3. **Finish the claimed harness and evidence-tool work** (#631 PR #652, #634
   PR #656, #649 PR #658, #654 PR #664, #653, #667). Done per issue: all leaf
   harnesses on `run_leaf_comparison`; one table-parametrized reporting
   battery; `attested_inventories` counts derived by a test;
   `ablation_delta.py --out` no longer writes into `reports/sxt-014/`.
4. **Re-grade the four STALE SXT-034 `spectral_corr` artifacts** (#167). Done
   when each carries `spectral_corr_definition` or is recorded as not
   reproducible, and the STALE rows leave the ledger. Needs the pinned oracle.
5. **Make two RTL runners portable** (no issue; seed 1).
   `tools/run_reverb_rtl.py` and `tools/compare_rtl_model_aw49.py` pass a
   hardcoded per-user macOS directory to `tempfile.mkdtemp`. Done when both
   use the default temp directory, a test refuses a literal temp path in
   `tools/`, and item 9 is re-attested.
6. **Correct the README's T1 section** (no issue; seed 2). It says one
   envelope is cited and ten items are unmet; the verdict of record cites
   items 9 and 10. Done when the text matches the report and item 10 is
   re-attested (the README is in `signoff/hygiene-inventory.json`).
7. **Commit the `ext_mem_instr` open-pin probe** (no issue; seed 3). The four
   unconnected `I` pins behind the LVS mismatch were found by an ad hoc
   extraction that is not in the tree. Done when a script reproduces the four
   pin-to-net findings from the committed stream and a test binds its output.
8. **Re-run the five 300 s NO_VERDICT groups at a larger Yosys budget** (#580:
   `logical4_core`, `rf_{bins12,global2,global34,send34}_core`), by the #642
   method (`yosys_timeout_s`, klayout-tools#5412). Done when each group has a
   netlist and report, or a NO_VERDICT record at the stated budget. No tagged
   klt release carries the field, and #580 still carries a blocked label.

## Next

- **Attest `rf_ains34_core` for item 1** (5 of 11). It synthesizes with a
  real datapath but `inventory.partial.json` lists four groups. After #475
  (PR #514, blocked) settles that core's ports.
- **Trace the `galactic_core` combinational-loop obstacle** (#657), after
  #641. Done when a measurement names what makes the generic ABC pass
  unaffordable, or a bounded refutation is recorded.
- **Physical flow for `reverb1_core`** (#554), then the other seven groups
  (#587), each after its item 1 netlist. Items 2, 3, 4 and 11 are cited only
  when all 11 groups have evidence.
- **Fix or explain the `ext_mem_instr` router opens**, after Now item 7. Done
  when LVS reads `match`, or the cause is recorded with an upstream report.
- **Effect-input observation** (#372, PR #445 blocked; then #444, #318). Done
  when Delay/EQ, Chorus and Reverb 2 have a settle-boundary verdict.
- **Carrier reproducibility under decision record 0019** (#382 with PR #446
  parked; #381; then #310). Done when the Novuo one-factor transcript and the
  one-command census are committed.
- **Approve or decline** proposals #669 and #663; triage #660, #666, #668, #670.

## Later

- **Freeze profile v1** (#12). First: does Delay acceptance (#16) close, so
  cost closure can be re-run? Gates T1 items 5, 6 and 8.
- **One complete wet preset, and the first `supported` entry.** First: which
  preset path has every leaf verified once budgets are frozen?
- **Corner timing and post-layout verification** (T1 items 5, 7). First: do
  all 11 groups route, and against which frozen constraints?
- **FPGA qualification** (#304), then gf180 qualification (#24). First: when is hardware available?

## Blocked and waiting

- **Maintainer decisions:** #16 (review and decision-record ratification
  remain; no Builder work is left per its 2026-11-02 note), #554, #565, #635,
  #426, #172, and the parked PRs #446, #445 and #514.
- **Oracle host or tap builds:** #94, #101, #135, #150, #155, #270, #305,
  #307, #308, #317. **Hardware access:** #304.
- **Upstream klayout-tools:** a tagged release carrying `yosys_timeout_s`; a
  gf180mcu antenna table for `klt erc`; the `klt drc --rerun` and `klt lvs
  --rerun` gaps that `signoff/t1-physical/README.md` records for upstream
  report.

Dispatchable today: Now items 4 to 7 (5 to 7 need an issue filed first).
Items 1 to 3 are already claimed; item 8 needs its label cleared.

## Not planned

- Counting a preset with a substituted generic effect as supported; sibling
  DSP as a reference (the only DSP oracle is the pinned Surge engine).
- Copying Surge-derived code, tables or assets without a license decision
  record; a distribution-license determination; volume production.
