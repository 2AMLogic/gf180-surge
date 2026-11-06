# T1 item 1 (design sources) — synthesizability record (#537)

Status: **PARTIAL — item 1 is NOT claimed `met`.** `klt synthesize` exits 0 for
10 of 11 `product` groups; 1 is NO_VERDICT; and for 6 of the 10 the report covers
only the control skeleton, not the datapath (see "Observability caveat").
`signoff/block-manifest.json` deliberately cites nothing
(`tests/test_t1_item1_synthesis.py` fails if it cites item 1 while any group is
BLOCKED).

Route (operator ruling r6-q23, 2026-11-05): the 8 groups the native Yosys front
end cannot read are requested with `sv_frontend: "sv2v"` (pinned sv2v 0.0.13;
claim wording "RTL as written, converted by pinned sv2v 0.0.13") **and
`defines: {"SYNTHESIS": null}`** (#572; sv2v does not define it by itself, and
klt only adds `-D SYNTHESIS` to the later Yosys read). The 3 groups that pass
natively **keep the native route** (their committed reports are unchanged; no
uniform-route claim is made).

#572 edits RTL, but only simulation-only constructs: the runtime-overflow
`$fatal`s (and `logical4_core`'s `string` ROM-path plusarg init, whose
synthesis branch reads the same two default hex files by literal path) sit under
`` `ifndef SYNTHESIS ``. Simulation behavior is unchanged: the assertions stay
active (live control: a core with `REG_LIM` shrunk trips the `$fatal` under
`iverilog` and runs clean with `-DSYNTHESIS`), `+SINROM`/`+OMCROM` still work,
and RTL-vs-frozen-model exactness is unchanged (`compare_rtl_model_aw4` and
`compare_rtl_model_rf_{global2,global34,ains34,bins12,send34}` PASS; the reverb1
runner is NOT_RUN on this host — its temp dir is a hardcoded macOS path).

| Group | Route | `klt synthesize` | Notes |
|---|---|---|---|
| control_top | native | PASS | 3 inferred latches reported (`structural` in report) |
| ext_mem_instr | native | PASS | |
| wavetable_core | native | PASS | 33 `undriven_wire` warnings in report |
| reverb1_core | sv2v | PASS | 36290 instances; real datapath (external-memory ports) |
| rf_ains34_core, rf_bins12_core, rf_global2_core, rf_global34_core, rf_send34_core | sv2v | PASS, **datapath not exercised** | 84–96 instances: control skeleton only (see below) |
| logical4_core | sv2v | PASS, **datapath not exercised** | 176 instances; same cause |
| galactic_core | sv2v | NO_VERDICT | sv2v converts; Yosys exceeded klt's fixed 300 s limit (no klt option to raise it) and was killed (not a proof of non-synthesizability); see `galactic_core/RECORD.md` (#579) |

**Observability caveat.** In `logical4_core` and the five `rf_*` cores the only
output port is `block_done`; the result buffers (`out_l`/`out_r`/`glob_out`...)
are internal and read hierarchically by the testbench. Yosys therefore removes
the biquad/arithmetic datapath as unobservable, and the 84–176-instance reports
describe the sequencer only. These exit-0 results show the RTL is *accepted*
by the flow; they are **not** evidence about datapath area, timing or
synthesizability. Exposing the results needs an interface change (functional
RTL/model scope), tracked in #580.

**galactic_core cause (diagnosed, #572).** sv2v converts it (838 lines). Yosys
`synth` expands the 32-sample block into ~272k generic cells; ~24 s in, the
generic `abc` pass starts and was still running after >14 min of CPU (killed by
hand). klt's 300 s limit (`DEFAULT_YOSYS_TIMEOUT_S`) is an internal klt default,
not a request field, so a larger budget is a klt/tool change, not a repo
change (follow-up #579). `failure.txt` stays a NO_VERDICT (timeout), never a pass.

Pins: `pdk-pin.json`. Regenerate: `python3 signoff/t1-item1/regen.py [group...]`.
`inventory.partial.json` + `item1.partial.envelope.json` (unchanged) attest only the 3
natively synthesized groups (`klt signoff --attest 1`, pass; `--check` clean). The
freshness check (`klt synthesize --check`) compares source and liberty hashes;
the netlist-to-report hash is checked by the test. Report `netlist_path` fields
name the removed `out/` scratch directory.

Not proved: P&R, timing, DRC/LVS, RTL-vs-netlist equivalence, fidelity.
