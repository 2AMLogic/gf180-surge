# rf_global2_core — pre-ABC operator census (#695)

**Diagnostic probe, NOT item-1 evidence.** No instance count, no area, no
netlist, no `met` claim comes from this file. This group's committed verdict
is the 1800 s timeout record beside this file (NO_VERDICT), produced by
`klt synthesize` via `regen.py`; this census only attributes the cell count
that kills that run (#695).

Method, tool versions (sv2v v0.0.13, Yosys 0.67+post `b8e7da6f`), probe
pipeline, calibration table and ablation protocol: see
`../rf_global34_core/census.md` — the three 20-multiply `rf_*` cores are
censused with the identical pipeline, one design at a time, sequentially. The
invocations here substitute this group's paths and `-top rf_global2_core`.

## Measured census (this group)

**Pre-synth operator inventory** (post `hierarchy` + `proc`): 2005 cells.
`$mul` shapes — identical to `rf_global34_core` cell-for-cell:

| $mul shape (A×B→Y) | count | named construct |
|---|---|---|
| 144×32→144 | 12 | `144'(out_l[kk]) * c{0,1,2}` × 2 channel halves × 2 `biquad_step` call sites |
| 144×144→144 | 8 | `144'(c{3,4}) * op{0,1}` — widened-coefficient feedback products (`rf_global2_core.sv`, `biquad_step`) |
| 32×32→32 | 16 | 32-bit coefficient/control arithmetic |

Pre-synth add/subtract inventory (identical to `rf_global34_core`): 20
`$add_144`, 16 `$add_32`, 8 `$sub_144`, 16 `$sub_32`, 8 `$neg_33`, 2 `$add_6`.

**Fine-entry product inventory** (post full coarse section): 339 cells,
**20 product `$macc_v2`**, shapes `NPRODUCTS,A,B,C,Y`:

| shape | count |
|---|---|
| (32, 32, C=0, Y=64) | 4 |
| (32, 32, C=80, Y=81) | 8 |
| (82, 32, C=115, Y=115) | 8 |

Identical to `rf_global34_core`'s inventory. **No 144-bit product operand
survives coarse** — the widening construct does not reach ABC; every product
is reduced by Yosys's own coarse passes to its integer-exact width
(#641's refutation transfers; measured here directly).

**ABC-entry gate cells (probe-measured): 249,489** — the committed 1800 s
record derives ~249,490 for the same point; the two agree within the
derivation's approximation.

## Attribution

Same as `rf_global34_core` (whose in-context ablation removes 97.4 % of the
design with the 20 products): this group's cost is the arithmetic of the 20
narrow products and their consumers, not a width problem. This is the group
the #695 body quoted (`rf_global34_core.sv:253`'s `144'(c3) * op0` construct
is this core's shape too); its census shows that construct never reaches ABC
as a wide multiply. Reducing the multiply-site count is a schedule/contract
question (SXT-017, `#554`), not a width edit.
