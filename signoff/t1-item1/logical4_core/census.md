# logical4_core — pre-ABC operator census (#695)

**Diagnostic probe, NOT item-1 evidence.** No instance count, no area, no
netlist, no `met` claim comes from this file. This group's committed verdict
is the 1800 s timeout record beside this file (NO_VERDICT), produced by
`klt synthesize` via `regen.py`; this census only attributes the cell count
that kills that run (#695).

Method, tool versions (sv2v v0.0.13, Yosys 0.67+post `b8e7da6f`), probe
pipeline, calibration table and ablation protocol: see
`../rf_global34_core/census.md`. Invocations here substitute this group's
paths and `-top logical4_core`, run from the repo root (this core's
synthesis-branch `$readmemh` reads `rtl/effects/aw-4/sin_q31.hex` /
`omc_q31.hex` by literal relative path — the same resolution klt's run uses).

## Measured census (this group)

**Pre-synth operator inventory** (post `hierarchy` + `proc`): 11,020 cells.
`$mul` shapes — the curation's textual enumeration (33 effective 192-bit
multiplies) undercounts; the design carries **44** 192×192 products:

| $mul shape (A×B→Y) | count | named construct |
|---|---|---|
| 192×192→192 | 44 | every product is computed through `mulr`/`rndsh` — `function automatic signed [191:0]` (`logical4_core.sv:153/159`) — or inline `192'(...) * 192'(...)`, so each is declared full-width regardless of its operands' true widths |
| 32×32→32 | 68 | 32-bit coefficient/control arithmetic |
| 64×64→64 | 2 | `tbl()` interpolation products |

Pre-synth add/subtract inventory: 78 `$add_192`, 147 `$add_32`, 4 `$add_64`,
4 `$add_96`, 18 `$sub_32`, 5 `$sub_96`, 4 `$sub_64`, 2 `$sub_192`, 7
`$neg_192` — the 192-bit adds are the product accumulations and rounding
bias adds inside `rndsh`, folded into `$macc_v2`/`$alu` cells by coarse.

Plus the two 806×40-bit `$readmemh` ROM tables (`sin_rom`, `omc_rom`:
806 words × 31–32 bits, 2 async read ports each) and the language-operator
divisions in `S_DIVP`/`S_DIVN` (`logical4_core.sv:387/426`,
`invq = 64'((w0 + 192'(divop >>> 1)) / 192'(divop))`) — the COST NOTE in the
file header itself flags these as schedule debt.

**Fine-entry inventory** (post full coarse section): 1478 cells — 805 `$mux`
(mostly 96/64-bit; 49 at 192-bit), 46 product `$macc_v2` + 13 adder-chain
`$macc_v2`, 1 `$div`, 2 `$mem_v2` (the ROMs), 74 `$alu`, 140 `$eq`, 75
`$reduce_and`, 38 `$pmux` (24 ≥256-bit). Product shapes `NPRODUCTS,A,B,C,Y`:

| shape | count | note |
|---|---|---|
| (**192**, 97, C=192, Y=192) | **8** | **not reduced** — full-width products survive coarse |
| (**192**, 96, C=131, Y=131) | **1** | not reduced |
| (**192**, 97, C=87, Y=87) | **1** | not reduced |
| 96–98 × 44–96 | 22 | reduced (wreduce saw through 34 of the 44 declared-192 products) |
| 64×64, 41×27, 32×2/3 | 14 | reduced |

So the declared-192-bit helper-port discipline (`mulr`/`rndsh` and the inline
`192'(...)` casts) is **confirmed visible at ABC**: 10 of 46 products reach
`fine` carrying a 192-bit operand, unlike the `rf_*` cores where zero wide
operands survive. This is exactly the split the #695 curation predicted
between the two shapes.

**ABC-entry gate cells (probe-measured): 1,987,837** — the committed 1800 s
record derives ~1,987,886; the two agree within the derivation's
approximation (the klt log's OPT_MERGE total, 766,919 removed, matches the
probe's 766,548 within 0.05 %).

## Ablation (in-context attribution of the 1,987,837 cells)

| variant | ABC-entry cells | delta vs baseline | what it removes |
|---|---|---|---|
| baseline | 1,987,837 | — | — |
| all 59 `$macc_v2` (46 products + 13 adder chains) removed, outputs tied 0 | **469** | −1,987,368 | 99.98 % of the design is arithmetic computing with/from the macc outputs — the FSM/decode shell alone is 469 cells |
| the 10 unreduced 192-wide products removed, outputs tied 0 | **92,015** | −1,895,822 | these 10 and everything that folds downstream of them (their results feed the divider operands, `calc_pos`, the ROM interpolation, the state updates — the cascade includes the divider and both ROM read muxes) |
| the 1 `$div` removed, output tied 0 | **1,307,842** | −679,995 | the divider and its consumers: **34.2 %** of the design (standalone calibration for a 192-bit divider: 309,692 cells — 15.6 %; the extra is its operand muxing and result chain) |

Read the ablation deltas as removal cascades, not disjoint partitions: the
10 wide products sit upstream of the divider, so their ablation subsumes the
divider's share.

**Standalone cost calibration** (same ABC-entry probe, table in
`../RECORD.md`): one 192×192→192 product = 111,542 cells; the 10 surviving
wide products alone are therefore ~1.1M-cell-class constructs standalone.

## Attribution, and why no restructure follows from this census

The cost has three named drivers:

1. **The declared-192-bit multiply discipline** — 10 unreduced 192-wide
   products (~1.1M-cell-class standalone), plus the 192-bit-wide mux fabric
   it keeps alive (560× `$mux_96`, 118× `$mux_64`, 49× `$mux_192` at
   fine-entry, carrying the same 192-bit scratch words `w0/w1/w2`).
2. **The two language-operator 192-bit divisions** (merged by opt to 1
   `$div`): 34.2 % of the design in context, ≥15.6 % standalone.
3. **The multiply-site count** — 46 products reach ABC; the narrowed ones are
   still 7k–17k gate cells each, and the 806×32×2-port ROM read muxes add
   ~2×6.7k.

Narrowing the declared widths (the #695-sanctioned candidate) addresses only
driver 1. Its ceiling is bounded by the group's own evidence: the three
20-product `rf_*` cores, whose products are *already fully narrow*, still die
in the same `abc -fast` step at ~250k ABC-entry cells within the same 1800 s
budget. A fully-narrowed `logical4_core` would keep ≥46 narrowed products
plus the divider and both ROMs — at or above the ~250k scale that already
fails — so the census supports no claim that a width edit reaches `exit 0`
under the capped budget. The irreducible remainder (site count × call-site
inlining, the divisions, the async-ROM read structure) is the schedule the
frozen model defines: a contract question (SXT-017), recorded for `#554`.
No RTL edit is made from this census.
