# T1 physical-flow evidence (#544), Phases A and A2

Per-block gf180mcu physical-flow evidence for the 3 product groups that
synthesize today (`control_top`, `ext_mem_instr`, `wavetable_core`; see
`signoff/t1-item1/README.md`). Pinned tool: `klayout-tools==0.8.0`
(`signoff/requirements.txt`) via `uvx`; regenerate with
`python3 signoff/t1-physical/regen.py [group...]` (sequential; ext_mem_instr
P&R takes roughly 40 minutes).

Per group: `request.json` (place-and-route), routed stream `<g>.gds.gz`, as-built
netlist `<g>.v`, `lvs.request.json`, and `pnr` / `drc` / `lvs` / `erc` reports
(`*.report.json.gz`), plus `exit_status.json`. Large artifacts are gzipped
deterministically; the content hashes inside the reports bind the
**uncompressed** stream. ERC uses `erc-supply-spec.json`, which declares `ties[]`.

## Recorded outcomes (as the tools reported them, nothing waived)

| group | P&R | DRC | LVS | ERC |
|---|---|---|---|---|
| control_top | ok (route) | clean (was 94045) | match | not_checked |
| ext_mem_instr | ok (route) | clean (was 107856) | **mismatch** | not_checked |
| wavetable_core | ok (route) | clean (was 19850) | match | not_checked |

"Clean" is the curated `gf180mcu` deck's verdict (`klt drc`, 0 violations,
nothing skipped); it is not full foundry DRC signoff.

## Triage (#544 Phase A2)

### DRC: flow-configuration artefacts, not layout defects
The Phase A violations came from the `gf180mcu_9t_6M` power preset, two
settings of which conflict with the curated deck. Measured on `wavetable_core`
(19850 violations): the tapcell change alone gave 19096, dropping `split_cuts`
alone gave 19096, both gave 0.

- Tap pitch 100 um (preset) vs the deck's `comp.tap_distance.{nwell,psub}.mv.1`
  limit of 15 um. Set to 30 um.
- pdngen `split_cuts` 0.128 um on the Metal1-Metal4 connect: source of every
  `metal2/3/4.ongrid.1`, `via2/3.ongrid.1` and `via2/3.width.1` hit (the
  `VIA_via2_3_*` cells). Removed; `ongrid` kept.

`regen.py` now writes the preset's strap geometry explicitly (`POWER`) with
those two differences, and all three groups were regenerated with it. The old
counts above come from the Phase A reports. Not a statement about the other
rules: only the curated deck was run.

### LVS: `ext_mem_instr` mismatch is not fixed
The other two groups match. `ext_mem_instr` reports 14 errors (8 topology, 6
`net.split`), unchanged in kind by the power-config change. Named in the report:

- unmatched layout instances `clkinv_12_0`, `clkinv_12_1`, `clkinv_16_0`,
  `inv_8_0`; unmatched reference instances `CLKLOAD1`, `CLKLOAD2`, `CLKLOAD3`,
  `_10285_` (same masters: `clkinv_12` x2, `clkinv_16`, `inv_8`);
- layout nets `VDD`, `VSS`, `$15509`, `$16017`, `$21170`, `$5283` reported as
  split (the reference net's role is divided across several layout nets).

Cause (measured, #544 Phase A3): the detailed router left the input pin of
these four cells unconnected, so they are opens in the layout, not an
extraction artefact. `klt extract` of the committed stream (same deck,
`abstract_cells`) puts each cell's `I` pin on a net with no other pin:
`clkinv_12_0` `$21170`, `clkinv_12_1` `$5283`, `clkinv_16_0` `$16017`,
`inv_8_0` `$15509`. The reference connects `_10285_`'s `I` to `net331` (which
fans out to many gates) and the three `CLKLOAD*` inputs to clock-tree nets.
`clkinv_12_0` is the real logic inverter `_10285_` (its output `$18523` drives
an `aoi22`, `buf_12`, `nor2` and `xnor2`), so the layout has a floating gate
input there; the other three are CTS dummy loads whose output is also
unconnected, which is why they match nothing. In the stream, the Metal1
polygon over the `I` pin of all four has no Via1 touching it, while the
sampled `clkinv_2` cells (which match) have one. The remaining `VDD`/`VSS`/
`$N` `net.split` entries are the same defect seen from the nets. Two other
checks are consistent with this: everything else in the design extracts and
matches (9544 nets), and P&R reports 0 unrouted nets, but its
`partially_routed_net_count` is `null` ("OpenROAD exposes no per-net
connectivity check; only nets with no routed wire at all are counted"), so
an open pin on an otherwise routed net is invisible to it.

Not established: why the router skipped these four pins (all are the larger
inverter masters; `clkinv_1`/`clkinv_2` are fine). No flow setting was
identified from this evidence that fixes it, and a speculative ~40 minute
re-run was not made, so `regen.py` is unchanged and the mismatch stays a
recorded failing LVS check. The extraction and geometry probe were run ad hoc
and are not committed.

### ERC: `not_checked` is a tool gap, not a missing input
Every gate reports `antenna_verdict: unchecked` with reason
`missing_antenna_pdk` and `"pdk": null`. klt 0.8.0 `erc --pdk` has no gf180mcu
antenna table to load, so supplying the supply spec (which already declares
`ties[]`) cannot change this. Item 11 therefore has no `met` ERC verdict; this
is reported as not_checked, never as a pass.

### Reproducibility
Cheap `--check` (re-hash stream, deck and reference against the recorded
hashes, no engine re-run) exits 0 / `match` for `wavetable_core`
`klt drc --check drc.report.json` and, run from the group directory (the
reference path is recorded relative to it), `klt lvs --check lvs.report.json`;
both need the stream gunzipped to the recorded path first.

Full `--rerun` of the DRC re-ran the deck and agreed on every verdict-bearing
field (status, violation count, rule counts, input hash) and still exits 3:
the only drift is `provenance.pdk` (`fresh: null`). That is a klt 0.8.0 gap,
not a layout difference: `--rerun` rebuilds the request from the report and
ignores `--pdk`, `--pdk-root` and `$PDK`, so the PDK is never resolved
(tried all three). LVS `--rerun` is unusable for these reports: klt does not
record `reference.form`, so the gate-level Verilog is re-read as SPICE and
fails to parse (klt's own message says to use cheap mode). Only
`wavetable_core` was checked; report both upstream rather than waiving them.

### Negative control
`negative-control/` holds a one-sliver layout that `klt drc` fails on
`metal2.width.1`, and a netlist mutation of `wavetable_core` that `klt lvs`
reports as `mismatch` against the committed stream (`regen.py` there rebuilds
both). `tests/test_t1_physical_flow.py` asserts each fails its targeted check
while the unmutated group stays clean/matching.

## What this does not establish

- Coverage is 3 of 11 product groups. `signoff/block-manifest.json` is
  unchanged: items 2/3/4/11 stay uncited (`unmet`) until all 11 groups have
  passing evidence; `tests/test_t1_physical_flow.py` fails on an earlier
  citation. The other 8 groups wait on #537 (Phase B).
- No timing closure, corners, "gf180mcu implementation" claim, or fidelity claim.
