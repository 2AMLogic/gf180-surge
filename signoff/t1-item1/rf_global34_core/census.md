# rf_global34_core — pre-ABC operator census (#695)

**Diagnostic probe, NOT item-1 evidence.** No instance count, no area, no
netlist, no `met` claim comes from this file. Every item-1 verdict comes from
`klt synthesize` via `regen.py`; this group's committed verdict is the 1800 s
timeout record beside this file (NO_VERDICT). The census exists to attribute
the cell count that kills that run to named constructs (#695).

## Method and tool versions

Probes run from a worktree whose root is the repo root (so `logical4_core`'s
synthesis-branch `$readmemh` literal paths would resolve; this group has no
`$readmemh`). Sequential, one design at a time; scratch under `/tmp`, nothing
machine-local committed.

- sv2v **v0.0.13** (`sv2v --version`), the same pinned converter `regen.py`'s
  request route uses (`sv_frontend: "sv2v"`, `defines: {SYNTHESIS}`).
- Yosys **0.67+post** (git sha1 `b8e7da6f40ae8f552c116bf6c359b07c6533e159`),
  the same binary klt invokes.

```
sv2v --incdir=rtl/effects/rf-rf-global34 --define=SYNTHESIS \
     -w <scratch>/rf_global34_core_sv2v.v rtl/effects/rf-rf-global34/rf_global34_core.sv

# census: the same read/hierarchy prefix klt uses, then synth sliced at labels
yosys -p "read_verilog -D SYNTHESIS <scratch>/rf_global34_core_sv2v.v; \
          hierarchy -check -top rf_global34_core; proc; \
          stat -width -json; write_json <scratch>/g34_pre.json; \
          synth -top rf_global34_core -run :coarse; stat -width -json; \
          synth -top rf_global34_core -run coarse:fine; write_json <scratch>/g34_fine.json"

# ABC-entry probe: synth's fine section minus its internal `abc`
yosys -p "read_json <scratch>/g34_fine.json; opt -fast -full; memory_map; \
          opt -full; techmap; opt -fast; stat"
```

`synth`'s sections are `begin:` / `coarse:` / `fine:` (with `abc` inside
`fine`); `-run :coarse` stops before the coarse section, `coarse:fine` runs
just it, and the fine prefix without `abc` reproduces the design state klt's
1800 s run reached when it was killed inside `synth`'s generic `abc -fast`
(`4.22.1 Extracting gate netlist ... to input.blif`).

Ablation variants: cells of one class are deleted from the fine-entry JSON
(the Yosys JSON netlist) with their output bits tied to constant 0; the same
ABC-entry probe then constant-propagates the change. Deltas are in-context
and include consumers that fold away.

## Measured census

**Pre-synth operator inventory** (post `hierarchy` + `proc`): 2043 cells,
including exactly the multiply sites the biquad arithmetic textually implies —
10 sites in `biquad_step` × 2 call sites (`slot` 3/4), each inlined:

| $mul shape (A×B→Y) | count | named construct |
|---|---|---|
| 144×32→144 | 12 | `144'(out_l[kk]) * c{0,1,2}` — 3 per channel half × 2 halves × 2 call sites |
| 144×144→144 | 8 | `144'(c{3,4}) * op{0,1}` — the widened-coefficient feedback products (`rf_global34_core.sv:253/254` and R twins), 2 per half × 2 halves × 2 call sites |
| 32×32→32 | 16 | 32-bit coefficient/control arithmetic (8 per body × 2 call sites) |

Pre-synth add/subtract inventory: 20 `$add_144`, 16 `$add_32`, 8 `$sub_144`,
16 `$sub_32`, 8 `$neg_33`, 2 `$add_6` — the 144-bit adds are the product
accumulations, folded into the same `$macc_v2` cells by coarse (`alumacc`).

Wide (≥256-bit) pre-synth cells: the 1024-bit flattened block arrays
(`out_l[32]`/`out_r[32]`, 32-bit words → 1024-bit vectors): 12 `$shiftx_1024`
(indexed reads `out_l[kk]`), 8 `$shift_1024`, 14 `$mux`, plus bit-parallel
`$and/$or/$not/$dff`.

**Fine-entry product inventory** (post full coarse section, i.e. exactly what
reaches `fine`/techmap→ABC): 373 cells, **20 product `$macc_v2`** (alumacc's
multiply+accumulator cells; `NPRODUCTS,A,B,C,Y` port widths):

| shape | count | what it says |
|---|---|---|
| (32, 32, C=0, Y=64) | 4 | product reduced 144×32→**32×32** by coarse opt (`wreduce` saw the narrow operand) |
| (32, 32, C=80, Y=81) | 8 | product reduced to **32×32**, folded with its 80-bit state add-in |
| (82, 32, C=115, Y=115) | 8 | the `144'(c3/c4) * op0/op1` products: operand `op` reduced 144→**82** bits (its true integer-exact width), coefficient to **32** |

**No 144-bit product operand survives coarse.** The widening construct named
in #695 — `144'(c3) * op0` as a "144×144 signed multiply" — does not reach
ABC: Yosys's own coarse passes (`wreduce`/`alumacc`) narrow every product to
its integer-exact widths (32×32, 82×32) exactly as `#641` found for
`galactic_core`. This is the measured transfer of #641's refutation to the
`rf_*` biquad shape.

Wide (≥256-bit) fine-entry cells: 20 — 4 `$mux`(1024), 5 `$shift`(1024),
2 `$shiftx`(1024), 2 `$dffe`(1024), 2 `$and`, 4 `$or`, 1 `$not` — the
1024-bit array decode/write fabric.

**ABC-entry gate cells (probe-measured): 250,149.** The committed 1800 s
record derives ~250,150 for the same point by subtracting klt-reported dedup
and OPT_CLEAN counts — the two agree within the derivation's approximation
(the klt log's OPT_MERGE total, 6881 removed, matches the probe's 6881; probe
input goes through one JSON round-trip).

## Ablation (in-context attribution of the 250,149 cells)

| variant | ABC-entry cells | delta vs baseline | share |
|---|---|---|---|
| baseline | 250,149 | — | — |
| all 20 product `$macc_v2` removed, outputs tied 0 | **6,498** | −243,651 | **97.4 %** is arithmetic computing with/from the products |
| all 20 wide (≥256-bit) cells removed, outputs tied 0 | 108 | −250,041 | ripple control: removing the 1024-bit array *data source* collapses the same arithmetic; the decode itself is inside the 6,498 residue, not a separate driver |

**Standalone cost calibration** (same ABC-entry probe on single-construct
modules; table in `../RECORD.md`): the 12 narrow products alone cost
12×7,171 + the 8 (82,32) products 8×16,868 = **220,996 cells standalone
(≈ 88 % of the group's total)**, before any consumer logic.

## Attribution

The ~250k cells that kill `klt synthesize` here are, to within a ~2.6 %
decode/FSM residue (6,498 cells), the arithmetic of the 20 products and the
logic consuming their results. The products are **already narrow** — the
widening hypothesis is measured-refuted for this group (and its two
near-identical siblings `rf_bins12_core`/`rf_global2_core`, whose censuses are
identical cell-for-cell through coarse). What remains irreducible by width is
the **count** of multiply sites: 10 per `biquad_step` body, inlined per call
site by the task mechanism, each ~7k–17k gate cells at these shapes. Reducing
that count means changing the schedule or the per-instance state plumbing the
frozen model defines — a contract question (SXT-017, `#554`), not a width
edit.
