# rf_send34_core — pre-ABC operator census (#695)

**Diagnostic probe, NOT item-1 evidence.** No instance count, no area, no
netlist, no `met` claim comes from this file. This group's committed verdict
is the 1800 s timeout record beside this file (NO_VERDICT), produced by
`klt synthesize` via `regen.py`; this census only attributes the cell count
that kills that run (#695).

Method, tool versions (sv2v v0.0.13, Yosys 0.67+post `b8e7da6f`), probe
pipeline, calibration table and ablation protocol: see
`../rf_global34_core/census.md`. The invocations here substitute this group's
paths and `-top rf_send34_core`.

## Measured census (this group)

**Pre-synth operator inventory** (post `hierarchy` + `proc`): 16,957 cells —
5–8× the other `rf_*` groups' ~2,000, from a much larger block/state fabric
(260 wide `$pmux` from the `bus_step`/`sum_step` branch decode at 1024+ bits).
`$mul` shapes:

| $mul shape (A×B→Y) | count | named construct |
|---|---|---|
| 144×32→144 | 24 | `144'(out×c)` products in `bus_step` (14 sites × 2 call sites) and `sum_step` (4 sites), less 32-bit ones below |
| 144×144→144 | 8 | the widened-coefficient feedback products |
| 32×32→32 | 12 | 32-bit coefficient/control arithmetic |

Pre-synth add/subtract inventory: 34 `$add_144`, 12 `$add_32`, 8 `$sub_144`,
12 `$sub_32`, 4 `$neg_33`, 3 `$add_6`.

**Fine-entry product inventory** (post full coarse section): 1539 cells,
**32 product `$macc_v2`** (the curation's textual enumeration — 14×2 + 4×1 =
32 sites — matches this post-coarse count exactly; 12 of the 44 pre-synth
`$mul` cells are folded by coarse opt before `fine`). Shapes
`NPRODUCTS,A,B,C,Y`:

| shape | count | note |
|---|---|---|
| (32, 32, C∈{0,64,80,85,165}, Y 64–86) | 20 | products reduced to **32×32** |
| (81, 32, C=114, Y=114) | 8 | feedback products: operand reduced 144→**81** bits |
| (144, 32, C∈{62,144}, Y=144) | **4** | **not reduced** — genuine 144-bit operand products survive to ABC (in `sum_step`'s wide-accumulator arithmetic) |

So 28 of 32 products are already at integer-exact narrow widths; 4 keep a
144-bit operand (a ≤4×24,672 ≈ 99k-cell standalone upside from narrowing
them — 26 % of the group, bounded below by the ablation ripple; not a rescue,
see the budget arithmetic in `../RECORD.md`).

**ABC-entry gate cells (probe-measured): 376,213** — the committed 1800 s
record derives ~376,206; the two agree within the derivation's approximation.

## Ablation (in-context attribution of the 376,213 cells)

| variant | ABC-entry cells | delta vs baseline | share |
|---|---|---|---|
| baseline | 376,213 | — | — |
| all 32 product `$macc_v2` removed, outputs tied 0 | **19,355** | −356,858 | **94.9 %** is arithmetic computing with/from the products |

## Attribution

Same shape as `rf_global34_core`: the design is ~95 % product-and-consumer
arithmetic; the 32 multiply sites (inlined per call site, ~14.8k gate cells
each on average at these shapes) are the cost, not their width — 28 of 32
products are already narrow and the 4 surviving 144×32 products are a bounded
≤26 % upside that cannot change the verdict class (the 20-product groups die
at ~250k cells; this group has 32 sites plus a larger fabric). Reducing the
multiply-site count is a schedule/contract question (SXT-017, `#554`), not a
width edit.
