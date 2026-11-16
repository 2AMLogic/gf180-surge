# T1 item 1 — the six #580 cores after the result ports were exposed

Scope: `logical4_core` and `rf_{ains34,bins12,global2,global34,send34}_core`
(tracker #580, parent #537). `galactic_core` has its own record
(`galactic_core/RECORD.md`, #579/#641/#657) and is not covered here.

Verdict: **no group in this set is datapath synthesizability evidence.**
Five are NO_VERDICT (Yosys killed at a 1800 s budget); `rf_ains34_core` exits 0
but its netlist has no datapath, for the reason in its own section below.
Item 1 therefore stays unclaimed in `signoff/block-manifest.json`, and none of
these six groups is in `inventory.partial.json`.

Not PASS, not FAIL. A timeout is a budget outcome, never a proof of
non-synthesizability; a constant-folded netlist is not a proof of area either.

## What moved since #586

#586 promoted `out_l`/`out_r` (and `glob_out` where present) to top-level
output ports on all six cores, which is what the issue asked for: the earlier
84–176-instance reports described the sequencer only, because the result arrays
were internal and read hierarchically by the testbench, so Yosys pruned the
datapath as unobservable.

It left the regen acceptance criterion unmet for five of the six, parked on
klt's then-fixed 300 s Yosys limit. That limit is now the request field
`yosys_timeout_s` (klayout-tools#5412), and this record re-runs those five at
1800 s.

| Field | Value |
|---|---|
| Request | each group's `request.json` (`sv_frontend: "sv2v"`, sv2v 0.0.13, `defines: {SYNTHESIS}` per the item-1 route, `yosys_timeout_s: 1800`) |
| klt | **`0.9.2` — a tagged release**, run from a throwaway `uvx --from klayout-tools==0.9.2 klt` environment. The host-wide klt was not modified. |
| Yosys | 0.67+post (`b8e7da6f`), as recorded in each netlist/report |
| Yosys budget | 1800.0 s per group (klt's cap is 3600 s; its default is still 300 s) |
| Date | 2026-11-14 |

**This retires the "unreleased build" caveat `galactic_core/RECORD.md` carries.**
#579 could only raise the budget under a git-rev pin (`0.9.2.dev890+gd9bc3681`),
because no tag carried `yosys_timeout_s`; `v0.9.2` (tagged 2026-11-14, 140
commits after that merge) does. `signoff/requirements.txt` still pins
`klayout-tools==0.8.0`, which does **not** accept the field — a klt without it
rejects a request that declares one rather than silently synthesizing at 300 s,
so the five `request.json` files here are only reproducible under a klt >= the
#5412 merge.

## The five NO_VERDICT groups, measured

All five were killed at the budget inside the **same** Yosys step — `synth`'s
generic ABC pass, at `4.22.1 Extracting gate netlist of module '<top>' to
'<abc-temp-dir>/input.blif'`. The script's later `abc -liberty`, `stat` and
`write_verilog` never ran, so for each there is no instance count, no area and
no netlist. Progress excerpts are each group's `timeout-progress.txt`.

| Group | cells entering OPT_MERGE | dedup removed | last OPT_CLEAN removed | derived cells reaching ABC |
|---|---|---|---|---|
| `logical4_core` | 2 964 796 | 766 919 | 209 991 cells / 430 760 wires | ~1 987 886 |
| `rf_send34_core` | 626 714 | 149 384 | 101 124 cells / 23 827 wires | ~376 206 |
| `rf_global34_core` | 296 130 | 6 880 | 39 100 cells / 14 277 wires | ~250 150 |
| `rf_bins12_core` | 296 122 | 6 878 | 39 100 cells / 14 271 wires | ~250 144 |
| `rf_global2_core` | 295 465 | 6 875 | 39 100 cells / 14 258 wires | ~249 490 |

The first three columns are klt-recorded log lines. The last column is a
**derived** figure, not a klt-reported one: OPT_DFF runs between the dedup and
the OPT_CLEAN it subtracts, so treat it as an order of magnitude.

### How this differs from galactic_core

Same step, different obstacle. `galactic_core`'s two timed-out logs each carry
**20** `Couldn't topologically sort cells, optimizing module galactic_core may
take a longer time` warnings and ABC breaking combinational loops one signal at
a time (`$abcloop$…`) when the budget expires — the untraced observation #657
exists to explain.

All five logs here contain **zero** of both: zero `Couldn't topologically sort
cells`, zero `Breaking loop using new signal`. So this set is not blocked on
galactic's unsortable-cells pathology. What these five present is size alone,
at the same order of magnitude galactic reaches (271 908 cells after dedup) and
in `logical4_core`'s case roughly 7x past it.

### What this record does NOT establish

- **Not the cause.** Nothing here isolates what makes these designs expensive.
  The cell counts are measured; any attribution is not.
- In particular, it makes **no** claim that the cost comes from the width of
  the products. The construct is present and citable — `rf_global34_core.sv:253`
  carries `144'(c3) * op0`, a 144x144 signed multiply whose 32-bit coefficient
  operand is widened to 144 bits, and `logical4_core.sv:199` declares
  `logic signed [191:0] w0, w1, w2` — but #641 **refuted** exactly that
  hypothesis for `galactic_core`: narrowing every product, sum and saturation to
  the narrowest integer-exact width moved its cells after dedup only from
  271 908 to 270 383 and did not change the outcome. Treat width narrowing here
  as an untested candidate, not as the known fix.
- **Not a budget conclusion.** Raising the budget again is not the next step,
  on budget arithmetic alone: klt caps `yosys_timeout_s` at 3600 s, only 2x what
  already failed, and nothing in these logs suggests the pass was close to
  finishing.

## rf_ains34_core — exits 0, and is still not datapath evidence

`rf_ains34_core` is the one group of the six whose `klt synthesize` exits 0
(`report.json`, 7467 instances, `area_um2` 248870.7648, critical path 9493.86 ps
from `abc_stime`). **None of those numbers describe its datapath**, and the
area and timing figures in particular must not be cited.

The reason is in the RTL, not in the tool: `rf_ains34_core` has **no input
ports at all**. Its module header (`rtl/effects/rf-rf-ains34/rf_ains34_core.sv:50`)
declares six ports — `clk`, `state_reset`, `start_block`, `block_done`, and the
two result arrays #586 added. Everything else its siblings carry as ports —
`cfg_fx_bypass`, `cfg_fx_disable`, `cfg_slot{3,4}_occupied`,
`cfg_slot{3,4}_reload`, `cfg_slot{3,4}_c[5]`, `in_l[32]`, `in_r[32]`, `sc_in`,
and the `sc_out` result bit — is a plain internal `logic` declaration, poked
hierarchically by the testbench (`tb_rf_ains34.sv:93-107`,
`core.cfg_fx_bypass = …`, `core.in_l[i] = …`). This predates #580: #586 only
added the two output arrays (commit `2b48c2b`).

This is the same defect the issue was filed about, applied to the other end of
the module. With its inputs undriven, Yosys constant-folds the arithmetic away,
and the committed netlist's whole cell census is:

| count | cell | what it is |
|---|---|---|
| 3054 | `tiel` | tie-low constants |
| 2058 | `dffq_1` | flip-flops — 2048 of them are `out_l`+`out_r`, plus ~10 FSM bits |
| 2054 | `and2_1` | the `out_l <= in_l` gating path |
| 193 | `buf_1` | buffers |
| 108 | 24 other types | incl. exactly 2 `mux2_1` |

There is no adder, no multiplier and no coefficient path in it. For comparison,
`reverb1_core` — the one sv2v-route group with a real datapath — is 36 290
instances and keeps all of its input ports.

**Two separate checks miss this, and both are worth knowing about:**

- `tests/test_t1_item1_synthesis.py::test_committed_netlists_expose_result_ports`
  passes it. That control asks only whether an output other than `block_done`
  exists; `out_l`/`out_r` are outputs, so a netlist with no inputs and no
  arithmetic satisfies it. The control is sound for the failure it was written
  for (#580's `block_done`-only netlists) and blind to this one.
- `tools/compare_rtl_model_rf_ains34.py` is **PASS**, live-re-run for this
  record on 2026-11-14 (18 cases, every output word and checkpoint
  integer-exact, `status: "PASS"`). It is a *simulation* harness and drives the
  core hierarchically, so it exercises the full datapath whether or not that
  datapath has any way into the module. **An exactness PASS does not imply the
  synthesized netlist contains the datapath** — the two claims are independent,
  and this group is the live demonstration of the gap.

Fixing this means promoting the rest of `rf_ains34_core`'s interface to real
ports and connecting `tb_rf_ains34.sv` to them, then regenerating — at which
point its synthesis cost is expected to land in the same range as its four
`rf_*` siblings above, i.e. NO_VERDICT at this budget. It also means
strengthening the netlist control so an exit-0 record that has lost its
declared input ports fails, which obliges re-attesting the item 9 envelope
(`tests/` is content-hashed by `signoff/t1-item9-inventory.json`) in the same
change. Neither is done here.

## Reproduce

Never with the host klt — use a throwaway pinned environment:

```
KLT='uvx --from klayout-tools==0.9.2 klt' \
  python3 signoff/t1-item1/regen.py logical4_core rf_bins12_core rf_global2_core \
                                     rf_global34_core rf_send34_core
```

Run at most two groups concurrently on a shared fleet host, one `regen.py`
invocation per job (it is sequential within a process). Each timed-out group
costs the full 1800 s budget.

**klt leaves the `yosys-abc` child alive when it kills Yosys on a timeout.**
Observed on every one of the five runs: the `yosys` process goes away at the
budget and its `yosys-abc` child is reparented and keeps burning a core. Check
for and kill orphans after a timed-out run (`ps -eo pid,ppid,etimes,comm |
grep yosys-abc`); leaving them is what the long-running-compute rule forbids.

## The cost driver: pre-ABC operator census (#695, 2026-11-16)

**Diagnostic probe, NOT item-1 evidence.** This section attributes the cell
counts that kill the 1800 s runs above to named constructs. It produces no
instance count, no area, no netlist and no `met` claim; the verdicts above
(ALL five NO_VERDICT) are unchanged by it. Per-group records with the exact
command lines and full inventories: `<group>/census.md`.

All five groups were also re-run through `regen.py` at the same 1800 s budget
on 2026-11-16 under the same pinned klt 0.9.2: every one exited 1 at the
budget again (NO_VERDICT), and the refreshed records reproduced the committed
ones byte-for-byte except the machine-local worktree path inside klt's
timeout message — the negative control for any "cost reduced" claim.

Method: each group's RTL is converted by the same pinned sv2v (v0.0.13,
`--define=SYNTHESIS`) and read by the same Yosys (0.67+post, `b8e7da6f`) that
klt invokes; `synth` is sliced at its labels (`-run :coarse`, then
`coarse:fine`) so the inventory is captured before `fine`'s techmap, and the
"ABC-entry" state (synth's fine section minus its internal `abc`) is
reproduced exactly — the probe's counts match the committed records' derived
column within its approximation (250,149 vs ~250,150; 250,143 vs ~250,144;
249,489 vs ~249,490; 376,213 vs ~376,206; 1,987,837 vs ~1,987,886).
In-context ablation (delete a cell class from the netlist, tie its outputs
to 0, re-run the same probe) splits the gate count per construct. Standalone
cost calibration, same probe, single-construct modules:

| construct | cells |
|---|---|
| signed 32×32→64 product | 7,171 |
| signed 82×32→115 product | 16,868 |
| signed 144×32→144 product | 24,672 |
| signed 192×192→192 product | 111,542 |
| signed 192/192→64 division | 309,692 |
| 806×32 ROM, 2 async read ports (`$readmemh` init) | 6,756 |

(These reproduce the curation's multiply calibration within 0.3 %: 24,406 and
111,284 were measured after a full `synth`; this table stops before `abc`.)

### What the census found, per group

| group | pre-synth `$mul` | products at fine-entry (post-coarse) | ABC-entry cells (probe) | ablation |
|---|---|---|---|---|
| `rf_global34_core` | 16× 32×32, 12× 144×32, 8× 144×144 | **20 `$macc_v2`, none wider than 32×32 / 82×32** | 250,149 | removing the 20 products leaves 6,498 (97.4 % arithmetic) |
| `rf_bins12_core` | identical | identical | 250,143 | (identical inventory) |
| `rf_global2_core` | identical | identical | 249,489 | (identical inventory) |
| `rf_send34_core` | 12× 32×32, 24× 144×32, 8× 144×144 | 32 `$macc_v2`: 28 narrow, **4 unreduced 144×32** | 376,213 | removing the 32 products leaves 19,355 (94.9 % arithmetic) |
| `logical4_core` | 68× 32×32, 2× 64×64, **44× 192×192** | 46 products: 36 reduced, **10 unreduced 192-wide**; + 1 `$div`, 2 ROMs | 1,987,837 | removing all 59 `$macc_v2` leaves 469; removing the 1 `$div` leaves 1,307,842 (divider+consumers = 34.2 %) |

### The widening hypothesis is measured-refuted for the `rf_*` cores

`rf_global34_core.sv:253`'s `144'(c3) * op0` — the construct the Prerequisites
table named — **never reaches ABC as a wide multiply** in any of the three
`biquad` cores: Yosys's own coarse passes (`wreduce`/`alumacc`) narrow every
product to its integer-exact width (32×32, 82×32) before `fine`. This is the
measured transfer of #641's `galactic_core` refutation to the `rf_*` shape,
exactly as the curation predicted. For `rf_send34_core` the residue is 4
unreduced 144×32 products (≤99k standalone upside, 26 % of the group) —
bounded below any verdict change. Width narrowing buys nothing here.

For `logical4_core` the hypothesis is **confirmed but not decisive**: the
declared-192-bit `mulr`/`rndsh` ports (`logical4_core.sv:153/159`) and inline
`192'(...)` casts keep 10 of 46 products at full width into ABC (~1.1M-cell
class standalone), and the same discipline keeps a 192/96-bit mux fabric
alive. But narrowing them cannot change the outcome: the three 20-product
`rf_*` cores, whose products are already fully narrow, still die in the same
`abc -fast` step at ~250k cells inside the same 1800 s budget, and a fully
narrowed `logical4_core` would keep ≥46 products plus the divider (34.2 % of
the design in context) and both ROMs — at or above that scale. No RTL edit is
made from this census.

### Attribution

The cell counts are the arithmetic itself, not decode or control overhead:
97.4 % (`rf_global34_core`), 94.9 % (`rf_send34_core`) and 99.98 %
(`logical4_core`) of each design's ABC-entry cells compute with or from the
multiply/accumulator outputs; the pure decode/FSM shell is 6,498 / 19,355 /
469 cells. The irreducible drivers are the **multiply-site count** (10 per
`biquad_step` body × 2 call sites; 32 sites in `rf_send34_core`; 46 products
in `logical4_core`), **call-site inlining** of `automatic` tasks/functions,
`logical4_core`'s two language-operator 192-bit divisions
(`logical4_core.sv:387/426`, flagged by that file's own COST NOTE), and its
two 806×32 async-ROM read structures (~2×6.7k cells). Reducing any of these
changes the schedule or the per-instance structure the frozen model defines:
a contract question (SXT-017), recorded for `#554`. Raising the budget stays
ruled out on the arithmetic in the Prerequisites section.

## Not proved by anything in this directory

P&R, timing closure, DRC/LVS, RTL-vs-netlist equivalence, fidelity to the
pinned Surge reference, or that item 1 is met.
