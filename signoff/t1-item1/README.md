# T1 item 1 (design sources) — synthesizability record (#537)

Status: **PARTIAL — 3 of 11 `product` groups PASS, 8 BLOCKED (sv2v route
tried for all 8, none synthesizes).** Item 1 is **not** claimed `met`;
`signoff/block-manifest.json` deliberately cites nothing
(`tests/test_t1_item1_synthesis.py` fails if it cites item 1 while any group is
BLOCKED).

Route (operator ruling r6-q23, 2026-11-05): the 8 groups the native Yosys front
end cannot read are requested with `sv_frontend: "sv2v"` (pinned sv2v 0.0.13;
claim wording "RTL as written, converted by pinned sv2v 0.0.13"). The 3 groups
that pass natively **keep the native route** (their committed reports are
unchanged; no uniform-route claim is made). RTL is untouched.

| Group | Route | Status | Blocking construct (`failure.txt`) |
|---|---|---|---|
| control_top | native | PASS | 3 inferred latches reported (`structural` in report) |
| ext_mem_instr | native | PASS | |
| wavetable_core | native | PASS | 33 `undriven_wire` warnings in report |
| reverb1_core, rf_ains34_core, rf_bins12_core, rf_global2_core, rf_global34_core, rf_send34_core | sv2v | BLOCKED | sv2v converts, then Yosys: ``System task `$finish' outside initial block is unsupported`` (sv2v lowers the RTL's runtime-overflow `$fatal` assertions inside functions/always blocks) |
| logical4_core | sv2v | BLOCKED | sv2v converts, then Yosys syntax error: `string` variables with initializers (`sin_path`/`omc_path`) feeding `$readmemh` |
| galactic_core | sv2v | NO_VERDICT | sv2v converts; Yosys exceeded klt's fixed 300 s limit (no klt option to raise it) and was killed (not a proof of non-synthesizability); see `galactic_core/RECORD.md` (#579) |

Remaining blockers are RTL simulation-only constructs (assertions, string-path
ROM init) and one runtime limit, not the front end. Fixing them needs an RTL
decision (separate issue) or a longer synthesis budget; neither is done here.
The yosys-slang fallback named in the ruling is a worker-spec change and is not
attempted.

Pins: `pdk-pin.json`. Regenerate: `python3 signoff/t1-item1/regen.py [group...]`.
`inventory.partial.json` + `item1.partial.envelope.json` (unchanged) attest only the 3
natively synthesized groups (`klt signoff --attest 1`, pass; `--check` clean). The
freshness check (`klt synthesize --check`) compares source and liberty hashes;
the netlist-to-report hash is checked by the test. Report `netlist_path` fields
name the removed `out/` scratch directory.

Not proved: P&R, timing, DRC/LVS, RTL-vs-netlist equivalence, fidelity.
