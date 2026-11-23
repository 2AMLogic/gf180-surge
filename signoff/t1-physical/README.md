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

Not established: why the router skipped these four pins. They are all from
larger inverter masters, and they are 100 % of the `clkinv_12`, `clkinv_16`
and `inv_8` instances in this block -- but "all are the larger inverter
masters" is incomplete as a pattern: `inv_12` and `clkinv_8` are also larger
inverter masters and are unaffected. The per-master instance counts are in
the committed probe record below, as data, not as a cause. No flow setting
was identified from this evidence that fixes it, and a speculative ~40 minute
re-run was not made, so `regen.py` is unchanged and the mismatch stays a
recorded failing LVS check.

The connectivity half of that measurement is committed and re-runnable (as of
2026-11-14): `python3 signoff/t1-physical/open_pin_probe.py <group>` re-runs
`klt extract` on the committed stream with the pinned `klayout-tools`
(`signoff/requirements.txt`, via `uvx`; minutes per group, one group at a
time, `$PDK_ROOT` set for pin directions) and rewrites the committed record
`<group>/open_pin_probe.json`, present for `ext_mem_instr` and, as the
negative control, `control_top`. The records carry the exact argv, the
uncompressed stream hash, the tool version and the pinned liberty identity;
the test in `tests/test_t1_physical_flow.py` re-binds them to the streams.
Each record's corroboration block annotates the P&R report's
`def_net_names.single_pin_markers` with the tie-cell output subset tally
(`tiel`/`ZN` + `tieh`/`Z`) computed from its own findings (#747): the marker
number equals exactly that subset (ext_mem_instr 44+2=46, control_top
37+1=38), not `single_pin_nets`, and the open input pins are not in it --
still a cheap corroboration only, not a substitute signal, with no cause
claim. `python3 signoff/t1-physical/open_pin_probe.py --rederive <group>`
recomputes that block alone from the committed findings, without
re-extracting.
The Metal1/Via1 geometry half now has its own committed, re-runnable
measurement (#804 step 1): `python3 signoff/t1-physical/pin_geometry_probe.py
<group>` (pinned `klayout-tools` klayout module, LEF pin geometry resolved
under `$PDK_ROOT` and recorded by revision + content hash, never by host
path) rewrites `<group>/pin_geometry_probe.json`, present for
`ext_mem_instr` and, as the negative control, `control_top`; the tests in
`tests/test_t1_physical_flow.py` re-bind both to their streams and to the
connectivity records. Measured (record, not cause claim): for the wide
inverter masters the LEF `I` pin is two RECTs while the GDS label sits on
the second only, and the first rect is M1-disconnected from the labelled
cluster in the flattened stream, joining it only through the cell's
transistor gates; all four open inputs are instances whose router Via1
access landed on that unlabelled first rect (`clkinv_12_1`, `clkinv_16_0`,
`inv_8_0`) or whose M2 stub dead-ends (`clkinv_12_0`), while every
non-isolated instance's access via landed on the labelled cluster.
`control_top` places `inv_8` too, and it is not isolated there, so the
master identity alone does not decide the open; where the router drops
the access via does. On the failing four, three pins also sit under an
M4 PDN strap (the fourth's nearest strap centre is 1.4 um away), which
motivates the trial order below.

#### Bounded P&R trials (#804 steps 2-3)

`python3 signoff/t1-physical/trial.py <group> <slug> --set leaf=value`
runs one bounded trial: it builds the group request exactly as
`regen.build_request` does, overlays ONE leaf, then runs place-and-route,
DRC, LVS and both probes inside `trials/<group>/<slug>/` (never the
committed group directories), recording commands, exit codes, wall times
and the baseline-relative request diff in `run.json`. The archived
`pnr-scripts/pnr_*_floorplan.tcl` proves the changed leaf reached the
generated flow -- the first trial's leaf never did. The tests in
`tests/test_t1_physical_flow.py` re-bind every recorded trial to its own
bytes and pin each recorded outcome.

Two trial records exist (cap: three evidence-backed, one ~40-70 minute
run at a time; only the second consumed a slot):

1. `placement-density-0p45` -- **invalid placebo, no slot consumed**:
   klayout-tools 0.8.0 has no request-level placement density (the
   generated `global_placement -density 0.6` is a module constant; a
   request field appears only in 0.9.x, klayout-tools #4716) and unknown
   top-level keys are silently ignored, so the run was a baseline replica
   that tested no setting. Its driver was killed by a builder-step exit
   after the route stage; recorded as the replica it was.
2. `m4-strap-offset-0p0` -- `power.straps[1].offset_um` 22.4 -> 0.0 (one
   leaf; the Metal4 `add_pdn_stripe ... -offset {0.0}` line in the
   archived floorplan TCL is the knob reaching pdngen). Complete run,
   P&R exit 0 in 54 min. **Not a fix.** The open-input SET moved:
   `clkinv_12_1` and `clkinv_16_0` inputs now connect, but `inv_12_0` --
   open in no baseline record -- lost its input; 3 opens remain
   (`clkinv_12_0`, `inv_12_0`, `inv_8_0`, same 21090 inputs examined),
   LVS got worse (31 errors: 24 topology, 7 net.split; the unmatched
   layout instances now also name eight `buf_4` cells), DRC stays clean.
   Read as evidence, not a cause claim: the M4 strap phase locally
   perturbs WHICH inputs the router leaves open without removing any --
   consistent with the geometry record (opens land where the access via
   lands on the unlabelled LEF rect), and ruling out "an M4 strap over
   the pin is the cause" as stated. `regen.py` is unchanged (offset
   stays 22.4); the failing-check record above is retained.

Also preserved: the m4 trial's own first attempt (`interrupted-attempt/`),
killed by a builder-step exit after its route stage completed (its
generated TCLs and route metrics show the same one-leaf flow), re-run
here from byte-identical request bytes. The trial retains each OpenROAD
invocation's metadata, stdout and stderr as individual files under
`openroad-logs/<invocation-id>/` so the provenance audit can inspect them
directly. These include one floorplan invocation that exited 1 during an
aborted first launch of the re-run with a mis-set `PDK_ROOT`
(`aborted-first-launch-pnr.failure.txt`), superseded by the successful
run minutes later. One more evidence-backed trial
remains unspent in this pass (builder-step compute budget); the next
candidate from the same measurement family is the Metal5 strap offset
(`power.straps[2].offset_um` 44.8 -> 0.0). The placement-density knob
stays unavailable until the pinned tool moves (klayout-tools #4716).
Both trials' run records are attached to klayout-tools #6905. Item 4
stays `unmet`: `ext_mem_instr` LVS stays a recorded failing check.

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
