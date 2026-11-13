# T1 item 1 (design sources) — synthesizability record (#537)

Status: **PARTIAL — item 1 is NOT claimed `met`.** `klt synthesize` exits 0 for
5 of 11 `product` groups; 6 are NO_VERDICT (klt 300 s Yosys timeout; see
"Result ports exposed (#580)"). `signoff/block-manifest.json` deliberately cites
nothing (`tests/test_t1_item1_synthesis.py` fails if it cites item 1 while any
group is BLOCKED).

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
| rf_ains34_core | sv2v | PASS | 7467 instances; `out_l`/`out_r` are outputs (#580) |
| rf_bins12_core, rf_global2_core, rf_global34_core, rf_send34_core, logical4_core | sv2v | NO_VERDICT | klt 300 s Yosys timeout once the datapath is observable (#580); see below |
| galactic_core | sv2v | NO_VERDICT | sv2v converts; Yosys was killed at a **1800 s** budget (`request.yosys_timeout_s`, klt `0.9.2.dev890+gd9bc36811ddd` — an unreleased rev pin, not a tagged release), having reached only the generic ABC pass. Not a proof of non-synthesizability, and this run does not establish the cause. Restructure filed as #641 (narrow the 128-bit arithmetic; suspected, unverified); see `galactic_core/RECORD.md` (#579) |

**Result ports exposed (#580).** The six cores (`logical4_core`, `rf_{ains34,
bins12,global2,global34,send34}_core`) previously had `block_done` as their only
output, so Yosys pruned the datapath and the earlier 84–176-instance reports
described the sequencer only. `out_l`/`out_r` (and `glob_out` where present) are
now top-level output ports, same widths and semantics, no arithmetic change.
Re-run: the six `compare_rtl_model_*` tools still PASS (integer-exact). Lint
waivers were rebased over the line shifts (6 now-ports `UNUSEDSIGNAL` waivers
removed; 700 remain, no new diagnostics). With the datapath real, `rf_ains34_core`
synthesizes (7467 instances, area 248870.8 um2 as reported by klt — synthesis
only) and the other five exceed klt's fixed 300 s Yosys limit like
`galactic_core` below. Their old sequencer-only reports/netlists were removed
(they must not be read as datapath evidence; see git history); `failure.txt`
records the timeout as NO_VERDICT, not a pass. A larger budget is now a
request field (`yosys_timeout_s`, klayout-tools#5412), but **no tagged klt
release carries it** and these five groups have not been re-run with it — only
`galactic_core` was (#579), and it timed out at 6x the budget anyway.
`tests/test_t1_item1_synthesis.py` has a negative control that fails on a
netlist whose only output is `block_done`.

**galactic_core obstacle (observed #572, re-measured #579; cause not
established).** sv2v converts it (838 lines). Yosys `synth` reaches ~272k
generic cells and the generic `abc` pass does not finish. The 300 s limit was
an internal klt default; it is now the request field `yosys_timeout_s`
(klayout-tools#5412).

#579 raised it to **1800 s** under a throwaway `uvx` klt pinned to
`d9bc36811ddd` (unreleased; the latest klt tag `v0.9.1` does not carry the
field, and `signoff/requirements.txt` still pins `klayout-tools==0.8.0`). It
**still timed out** — so the verdict stays NO_VERDICT. What the run records is
observation, not a cause: it died inside `synth`'s generic ABC pass at
`4.22.1 Extracting gate netlist ... to input.blif`, with Yosys reporting
`Couldn't topologically sort cells` 20 times and ABC still breaking
combinational loops when the budget expired
(`galactic_core/timeout-progress.txt`). Nothing in it diagnoses *why* the
design is expensive, and in particular it does not show a combinational unroll
of the 32-sample block — the RTL has none, being already a sequential
per-sample FSM. Raising the budget again is not the next step (klt caps it at
3600 s, only 2x what failed — a budget argument, not a mechanism); the
restructure is, filed as **#641**, now scoped to narrowing the 128-bit
arithmetic, a cause that is suspected and unverified. `failure.txt` stays a
NO_VERDICT (timeout), never a pass.

Pins: `pdk-pin.json`. Regenerate: `python3 signoff/t1-item1/regen.py [group...]`.
`inventory.partial.json` + `item1.partial.envelope.json` attest 4 of 11 groups:
the 3 native groups plus `reverb1_core` (sv2v, real datapath). Not attested: the 6
skeleton-only groups (#580) and `galactic_core` (#579); attesting a netlist that
omits the datapath would present sequencer-only output as item-1 evidence.
`klt signoff --attest 1` passes 12/12 (run on this host, klt 0.9.2.dev33).
Each freshness check is `klt synthesize --check ... --netlist <committed netlist>`:
report `netlist_path` fields name the removed `out/` scratch directory, so without
`--netlist` the check reports `netlist_sha256` as `drifted` (the earlier 3-group
envelope fails live for that reason; this change fixes it). Re-attest with
`klt signoff --attest 1 --inventory signoff/t1-item1/inventory.partial.json -o signoff/t1-item1/item1.partial.envelope.json`.
`klt signoff --check` applies only to `--manifest`/`--fleet`, not to an attest
envelope; the live re-derivation is the attest run itself.

Not proved: P&R, timing, DRC/LVS, RTL-vs-netlist equivalence, fidelity.
