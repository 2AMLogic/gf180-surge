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

Tool versions: P&R, DRC and LVS reports are pinned `klayout-tools==0.8.0`
(`signoff/requirements.txt` via `uvx`). ERC alone is regenerated under
`klayout-tools==0.9.2` (#803), the first release with the gf180mcu
antenna-ratio table (2AMLogic/klayout-tools#4003): a per-check override in
`regen.py` (`ERC_KLT`), not a pin move — `signoff/requirements.txt` stays
0.8.0 and the DRC/LVS/P&R artifacts are unchanged 0.8.0 reports. Refresh only
the ERC reports with `python3 signoff/t1-physical/regen.py --erc-only`
(re-reads each committed `<g>.gds.gz`, rewrites only `erc.report.json.gz` and
the `erc` field of `exit_status.json`); the lowercase failure control with
`--erc-control`.

## Recorded outcomes (as the tools reported them, nothing waived)

| group | P&R | DRC | LVS | ERC (klt 0.9.2, `--pdk gf180mcu`) |
|---|---|---|---|---|
| control_top | ok (route) | clean (was 94045) | match | clean, exit 0; 25884 gates x 5 metals = 129420 levels checked, 0 skipped, all `pass` |
| ext_mem_instr | ok (route) | clean (was 107856) | **mismatch** | clean, exit 0; 17556 gates x 5 metals = 87780 levels checked, 0 skipped, all `pass` |
| wavetable_core | ok (route) | clean (was 19850) | match | clean, exit 0; 513 gates x 5 metals = 2565 levels checked, 0 skipped, all `pass` |

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
The Metal1/Via1 geometry observation above remains ad hoc and is NOT
committed by that probe; it needs its own measurement.

### ERC: re-run under klt 0.9.2 with the gf180mcu antenna table (#803)

The Phase-A `not_checked` was a tool gap, not a missing input: klt 0.8.0 had
no gf180mcu antenna table, so every gate reported `unchecked` with reason
`missing_antenna_pdk` and `"pdk": null`. klt 0.9.2 ships one
(2AMLogic/klayout-tools#4003), and the three committed streams were re-run
(`regen.py --erc-only`, same streams, `--pdk gf180mcu`):

- `erc-supply-spec.json` stackup role names are now the case-sensitive table
  keys `Metal1`..`Metal5` (was `metal1`..`metal5`); the mapping applies to the
  `vias[].between` endpoints and both `ties[].connect_to` values. Layer/
  datatype pairs, label layers, stack order, the `poly` gate role, via
  geometry and the supply/tap declarations are unchanged. The pre-mapping
  lowercase spec is retained as the failure control
  `negative-control/erc-supply-spec-lowercase.json`.
- Recorded outcome (as the tool reports it): all three groups `clean`, exit
  0, `erc_finding_count` 0. Every gate carries exactly one graded level for
  each of `Metal1`..`Metal5` with a table limit (400.0, w/o-diode, from
  gf180mcu-pdk `antenna.rb` rules `ANT.16_i_ANT.2`..`.6` at f6eeac7) and a
  rule source; `coverage.checked` reconciles to exactly the gate/metal pairs
  and `coverage.skipped` is empty. Per metal, checked == gate count (e.g.
  wavetable_core: 513 per metal, 2565 total). The gate role `poly` is
  inapplicable and stays ungraded, as klt intends for stackup[0].
- Antenna-ratio model caveat, inherited from the klt table (not a claim this
  repo can upgrade): the limit compares cumulative connected **area** / gate
  area, while the foundry deck's own ANT rules measure perimeter x
  thickness / gate area; klt does not model protection diodes. A `clean`
  here is the tool's verdict under that approximation.
- `provenance.label_layers` record per-metal label counts; `Metal4` carries
  0 label texts in all three tops (observation, recorded, unexplained --
  klt warns about it on stderr, which the committed JSON does not capture).
- The lowercase control on the same wavetable_core stream and the same klt
  0.9.2 misses every table key: exit 4, `not_checked`, 0 checked, all 2565
  intended metal levels skipped with reason `missing_antenna_limit`
  (committed as `negative-control/erc.report.json.gz` +
  `exit_status.json:erc = 4`). The lookup is by role name verbatim; this is
  the reproducible failure `tests/test_t1_physical_flow.py`'s coverage check
  rejects, alongside a stale 0.8.0-shape `missing_antenna_pdk` report.

DRC/LVS/P&R reports are still 0.8.0 artifacts; the pin did not move (#803
records why: moving it re-attests the item 9 / item 10 envelopes and
regenerates DRC/LVS -- filed separately if wanted). Item 11 remains
`unmet`/`no_evidence` at the manifest level: this is 3 of 11 groups, and the
all-11-groups citation rule in `tests/test_t1_physical_flow.py` is unchanged.

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

**`--rerun` re-test under klt 0.9.2 (#803, wavetable_core, from copies of the
committed reports and a fresh 0.9.2 pair, 2026-11-21).** Both observations
re-checked; the tracking issue is #803 (an issue, not a PR); measured outputs are summarized below, and the upstream DRC filing 2AMLogic/klayout-tools#6986 currently carries only a command with a `<gds>` placeholder and the drift excerpt -- the exact request/input and a fresh report are **not yet attached** there (open item, not claimed done):

- **DRC: still reproduces.** On a *fresh* 0.9.2 DRC report (clean, PDK
  resolved, exit 0), `klt drc --check --rerun` still exits 3 with the only
  drift `provenance.pdk` `fresh: null` -- `--pdk`/`--pdk-root`/`$PDK` on the
  rerun are still ignored. Filed upstream:
  2AMLogic/klayout-tools#6986. Re-running the *committed 0.8.0* report under
  0.9.2 additionally and expectedly drifts on curated-deck content
  (`coverage.deck_layers/deck_scope/inapplicable/rules_skipped/
  unmodeled_rules`, `provenance.deck.content_hash`) and records
  `provenance.klayout_version_mismatch` (0.30.13 resolved vs 0.30.12 tested);
  no verdict-bearing field drifts.
- **LVS: fixed upstream for 0.9.2-generated reports.** klt 0.9.2 echoes a
  `reference_conversion` block (2AMLogic/klayout-tools#4353, PR #4356) and
  `--check --rerun` of a fresh 0.9.2 LVS report now replays the gate-level
  Verilog (measured: `match`, and the rerun agrees on every verdict-bearing
  field). The *committed 0.8.0* reports predate the echo and still exit 1 on
  the SPICE parse (klt's message says so); cheap `--check` remains their
  verification route. Residual on fresh reports: the rerun still exits 3 on
  `provenance.pin_order_sources.0.path` (`$PDK_ROOT`-neutral committed vs
  absolute-home fresh) -- already upstream as
  2AMLogic/klayout-tools#5812.

### Negative control
`negative-control/` holds a one-sliver layout that `klt drc` fails on
`metal2.width.1`, a netlist mutation of `wavetable_core` that `klt lvs`
reports as `mismatch` against the committed stream (`regen.py` there rebuilds
both), and the lowercase ERC supply spec (pre-role-mapping) whose 0.9.2
report skips every intended metal level with `missing_antenna_limit`
(`signoff/t1-physical/regen.py --erc-control` rebuilds it).
`tests/test_t1_physical_flow.py` asserts each fails its targeted check
while the unmutated group stays clean/matching/fully covered.

## What this does not establish

- Coverage is 3 of 11 product groups. `signoff/block-manifest.json` is
  unchanged: items 2/3/4/11 stay uncited (`unmet`) until all 11 groups have
  passing evidence; `tests/test_t1_physical_flow.py` fails on an earlier
  citation. The other 8 groups wait on #537 (Phase B).
- No timing closure, corners, "gf180mcu implementation" claim, or fidelity claim.
