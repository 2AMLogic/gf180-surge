# galactic_core — synthesizability record (#641, after #579; tracker #572, parent #537)

Verdict: **NO_VERDICT** (unchanged). Not PASS, not FAIL.

`rtl/effects/aw-49/galactic_core.sv` was restructured as #641 asked — every
product, sum and saturation narrowed to the smallest width that is still
integer-exact, with the FSM schedule untouched — and `klt synthesize` was
re-run at the same 1800 s Yosys budget. **It still timed out, in the same
pass, with the same structural warnings.** A timeout is a budget outcome,
never a proof of non-synthesizability and never a pass.

| Field | Value |
|---|---|
| Request | `request.json` (`sv_frontend: "sv2v"`, sv2v 0.0.13, `defines: {SYNTHESIS}` per the item-1 route, `yosys_timeout_s: 1800`) — byte-identical to the #579 request |
| RTL | `rtl/effects/aw-49/galactic_core.sv` after the #641 narrowing, sha256 `87e0dd009c590f21913a8add0c5e1d54dc5606daa596e7278b26ef585b0c8a5b` (was `7b64384c…e4c4`) |
| klt | `0.9.2.dev890+gd9bc36811ddd` — a **throwaway `uvx` environment** pinned to git rev `d9bc36811ddd11fcf9c60d3a9275858296db8b44` of `2AMLogic/klayout-tools` (the merge of klayout-tools#5413 for #5412), the same pin #579 used. **Not a tagged release**; the host-wide klt was not used or modified. |
| Yosys budget | **1800.0 s**, from the request's `yosys_timeout_s` (klt cap 3600 s, default 300 s) |
| Outcome | Yosys killed at the budget (`failure.txt`); exit status 1 |
| Progress reached | `timeout-progress.txt`. Identical to #579's: `synth` got through TECHMAP and the fast OPT passes and died inside its **generic ABC pass**, at step `4.22.1 Extracting gate netlist of module '\galactic_core' to '<abc-temp-dir>/input.blif'` (line 645). `abc -liberty`, `stat` and `write_verilog` never ran, so there is still **no instance count, no area and no netlist**. |

## What the narrowing changed, measured

Two measurements, both on the same `sv2v -DSYNTHESIS` → Yosys route the
request uses. Neither is a verdict; both are progress evidence.

**Coarse cells, before TECHMAP** (`read_verilog; hierarchy -top galactic_core;
proc; opt_expr; opt_clean; memory_collect; stat -width`, run in a `/tmp`
scratch directory on the `sv2v` output of each revision):

| | #579 RTL (128-bit) | #641 RTL (narrowed) |
|---|---|---|
| coarse cells | 1301 | **1301** |
| wire bits | 48397 | **37201** |
| multipliers | 11 × `$mul_128` | **9 × `$mul_64` + 2 × `$mul_66`** |
| adders | 60 × `$add_128`, 62 × `$add_32` | **49 × `$add_38`, 10 × `$add_66`, 1 × `$add_64`, 62 × `$add_32`** |
| subtractors | 26 × `$sub_128`, 18 × `$sub_32` | **24 × `$sub_38`, 2 × `$sub_34`, 18 × `$sub_32`** |
| comparators | 31 × `$gt_128`, 31 × `$lt_128` | **31 × `$gt_38`, 31 × `$lt_38`** |

So the narrowing did what it claimed: the same 1301 operators, none of them
128 bits wide any more, and 23 % fewer wire bits. The same figures come out
of the `sv2v` output klt itself produced for this run, which grew 838 → 869
lines (the new width helper functions).

**Generic cells, inside `synth`** (both runs' `timeout-progress.txt`):

| | #579 | #641 | Δ |
|---|---|---|---|
| cells entering OPT_MERGE after TECHMAP | 394184 | 369383 | −6.3 % |
| removed by OPT_MERGE (dedup) | 122276 | 99000 | |
| cells after dedup | 271908 | **270383** | **−0.6 %** |
| removed by the following OPT_CLEAN | 153496 cells, 20968 wires | 151342 cells, 15295 wires | |
| `Couldn't topologically sort cells` | 20 | **20** | 0 |
| last step reached | `4.22.1` blif extraction | **`4.22.1` blif extraction** | same |
| outcome at 1800 s | killed | **killed** | same |

## The suspected cause is refuted as the dominant cost

#641 named a suspected, unverified cause: that eleven 128×128 multipliers and
~150 other 128-bit operators account for the generic cell count, and that
narrowing them would let `synth` finish. That hypothesis is now **measured and
refuted** as the dominant cost. The arithmetic really was narrowed — the coarse
netlist proves it — and the design still arrives at the ABC pass with 270383
generic cells instead of 271908, dies in the same sub-step, and reports the
same 20 unsortable-cell warnings.

What the log points at instead is unchanged from #579 and is **not** the
operand widths: ABC is still breaking combinational loops one signal at a time
when the budget expires, and the signals it names are the same three sites —

* `\wcount` (the combinational `counts[…]` read mux that drives `em_addr`)
  into `maccmap` full-adder bits, e.g.
  `Breaking loop using new signal $abcloop$587375: \wcount [11] -> $auto$maccmap.cc:114:fulladd$23239.t2 [11]`;
* the `counts` memory read mux;
* the `adv_idx` memory-write data.

These read as *false* combinational loops through the memory read/write ports,
not as arithmetic width. **This record does not establish that**, and it does
not establish any cause at all: it establishes only that narrowing the
arithmetic is not sufficient, and that the obstacle survives it unchanged.
Escalated as **#657** rather than widened here, per #641's stop condition.

Reproduce (never the host klt):

```
KLT='uvx --from "git+https://github.com/2AMLogic/klayout-tools.git@d9bc36811ddd11fcf9c60d3a9275858296db8b44" klt' \
  python3 signoff/t1-item1/regen.py galactic_core
```

Raising the budget again remains **not** the next step, on the same budget
arithmetic as before: klt's cap is 3600 s, only 2× what has now failed twice,
and the run is not close to finishing — it has not emitted a single mapped
gate.

## Fidelity is unaffected: the narrowed RTL is still integer-exact

The narrowing is a width change only. `tools/compare_rtl_model_aw49.py` was
re-run against the unchanged frozen model
(`model/effects/aw-49/galactic_model.py`, frozen revision `569bff13…c5c0cd`,
**not** edited): **PASS**, all four cases integer-exact, three mutant controls
CONTROL-OK (`reports/sxt-028a/rtl-exactness.json`). The per-block cycle count
and the order and content of every `em_*` transaction are unchanged; the
transaction-log sha256 of `prs-128b-smoke`, `dual-instance-64b` and
`prs-128b-reset48` is byte-identical to the previously committed record. See
`reports/sxt-028a/EVIDENCE.md` for the `canonical-temple-512b` hash, which
moved for an unrelated reason recorded there (a stale committed record, not
this change).

That is a different claim from this file's. RTL-vs-frozen-model exactness says
nothing about synthesizability, and this record says nothing about fidelity.

## Failure controls run for this record

1. **The comparison observes the narrowed datapath.** A third mutant control
   was added in the same change: `smul()`, the core's exact 32×32→64 signed
   product, truncated to a 32-bit product. It **FAILS** the exactness
   comparison (`mutant-narrow-product`, CONTROL-OK). Without it, a comparison
   that passed could not be read as evidence about the widths at all.
2. **The two pre-existing mutants still apply and still fail.**
   `mutant-regen-halved`'s needle was re-spelled for the new source
   (`rndmul(fb, cfg_regen, 31)`); `mutant-shared-memory-dual` is unchanged.
   Both CONTROL-OK.
3. **The budget is not silently ignored**, re-confirmed from #579: a klt
   without klayout-tools#5412 refuses this `request.json`
   (`unknown field 'yosys_timeout_s'`), and the pinned klt rejects an over-cap
   value (`must be … <= 3600 (seconds); got 3700`). Not re-run for this record;
   the request bytes and the klt pin are unchanged from the run that did.
4. **The datapath-pruning control (#580) now covers this group.**
   `galactic_core` was added to `OBSERVABLE_GROUPS` in
   `tests/test_t1_item1_synthesis.py`, so if this group ever does produce a
   netlist, one whose only output is `block_done` fails the test. It is inert
   while the group is NO_VERDICT (no netlist to check), which is the state it
   is in.

## Coverage, kept separate from agreement

This record is one group's synthesizability attempt. **Not** proved here:
synthesizability of `galactic_core`, P&R, timing, DRC/LVS, RTL-vs-netlist
equivalence, or fidelity to the pinned Surge reference. `galactic_core`
remains unattested in `signoff/t1-item1/inventory.partial.json`, which this
change does not touch.
