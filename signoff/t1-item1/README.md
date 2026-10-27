# T1 item 1 (design sources) — synthesizability record (#537)

Status: **PARTIAL — 3 of 11 `product` groups PASS, 8 BLOCKED.** Item 1 is
**not** claimed `met`; `signoff/block-manifest.json` deliberately cites nothing
(`tests/test_t1_item1_synthesis.py` fails if it cites item 1 while any group is
BLOCKED).

| Group | Status | Note |
|---|---|---|
| control_top | PASS | 3 inferred latches reported (`structural` in report) |
| ext_mem_instr | PASS | |
| wavetable_core | PASS | 33 `undriven_wire` warnings in report |
| reverb1_core, logical4_core, galactic_core, rf_bins12_core, rf_global2_core, rf_global34_core, rf_send34_core | BLOCKED | native Yosys frontend: syntax error on unpacked-array port `[N]` (`failure.txt`) |
| rf_ains34_core | BLOCKED | native Yosys frontend: `$fatal` unresolved |

The blocker is the tool/RTL dialect gap (no `yosys-slang`/`sv2v` on the worker),
not only #473/#475. Fixing it needs a worker-spec change or an RTL decision;
neither is done here. RTL is untouched.

Pins: `pdk-pin.json`. Regenerate: `python3 signoff/t1-item1/regen.py [group...]`.
`inventory.partial.json` + `item1.partial.envelope.json` attest only the 3
synthesized groups (`klt signoff --attest 1`, pass; `--check` clean). The
freshness check (`klt synthesize --check`) compares source and liberty hashes;
the netlist-to-report hash is checked by the test. Report `netlist_path` fields
name the removed `out/` scratch directory.

Not proved: P&R, timing, DRC/LVS, RTL-vs-netlist equivalence, fidelity.
