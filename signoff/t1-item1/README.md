# T1 item 1 (design sources) — synthesizability record (#537)

Status: **PARTIAL — item 1 is NOT claimed `met`.** `klt synthesize` exits 0 for
5 of 11 `product` groups, but only **4** of those exits are datapath evidence;
6 are NO_VERDICT (Yosys timeout) and the fifth exit-0 group,
`rf_ains34_core`, is a constant-folded shell because its own inputs are not
ports (see "Result ports exposed (#580)"). `signoff/block-manifest.json`
deliberately cites nothing (`tests/test_t1_item1_synthesis.py` fails if it
cites item 1 while any group is BLOCKED).

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
| rf_ains34_core | sv2v | exit 0, **NOT datapath evidence** | 7467 instances, but the core has **no input ports** (they are internal `logic`, poked hierarchically by its testbench), so Yosys constant-folds the datapath: 3054 tie-lows, 2058 flops, 2054 AND2, no adder or multiplier. Its `area_um2`/timing must not be cited (#580); see `RECORD.md` |
| rf_bins12_core, rf_global2_core, rf_global34_core, rf_send34_core, logical4_core | sv2v | NO_VERDICT | Yosys killed at a **1800 s** budget (`request.yosys_timeout_s`, klt **`0.9.2`** — a tagged release), all five inside `synth`'s generic ABC pass at the blif extraction; 0.25M–2.0M cells reach it. No unsortable-cells warnings (unlike `galactic_core`). Cause established 2026-11-16 by the pre-ABC operator census (#695): the cells are the multiply/accumulator arithmetic itself — 94–100 % of each design — with every `rf_*` product already reduced by Yosys to its integer-exact width (widening refuted) and `logical4_core` additionally carrying 10 unreduced 192-wide products and a 34 %-share 192-bit divider; see `RECORD.md` (#580, #695) and each group's `census.md` |
| galactic_core | sv2v | NO_VERDICT | sv2v converts; Yosys was killed at a **1800 s** budget (`request.yosys_timeout_s`, klt `0.9.2.dev890+gd9bc36811ddd` — an unreleased rev pin, not a tagged release), having reached only the generic ABC pass. Not a proof of non-synthesizability. #641 narrowed the 128-bit arithmetic to its integer-exact widths (no schedule or port change; RTL-vs-model still exact) and re-ran at the same budget: **same outcome, same pass, same warnings**, so that suspected cause is now measured and refuted as the dominant cost. #657 then traced the 20 unsortable-cell warnings / 35 ABC loop reports to the `counts`/`adv_idx` memory mapping and removed them (constant-indexed arrays; RTL-vs-model still exact, transaction logs byte-identical): the third 1800 s run carries **zero** loop reports and **still** dies at `4.22.1` — the loops are gone, the obstacle (generic ABC over ~2.8e5 cells) is not, an upstream/tool-pin question per #657's stop condition. See `galactic_core/RECORD.md` (#641, #657) |

**Result ports exposed (#580).** The six cores (`logical4_core`, `rf_{ains34,
bins12,global2,global34,send34}_core`) previously had `block_done` as their only
output, so Yosys pruned the datapath and the earlier 84–176-instance reports
described the sequencer only. `out_l`/`out_r` (and `glob_out` where present) are
now top-level output ports, same widths and semantics, no arithmetic change.
Re-run: the six `compare_rtl_model_*` tools still PASS (integer-exact). Lint
waivers were rebased over the line shifts (6 now-ports `UNUSEDSIGNAL` waivers
removed; 700 remain, no new diagnostics). Their old sequencer-only
reports/netlists were removed (they must not be read as datapath evidence; see
git history); `failure.txt` records a timeout as NO_VERDICT, not a pass.

**That port change was necessary and is not sufficient. Measured 2026-11-14
(`RECORD.md`), the whole set of six is still outside item 1:**

- The five that timed out were re-run at `yosys_timeout_s: 1800` under klt
  **`0.9.2`** — the first *tagged* release carrying klayout-tools#5412, which
  also retires the "unreleased rev pin" caveat #579 had to accept. All five
  were killed again, each inside `synth`'s generic ABC pass at the blif
  extraction, with 0.25M (`rf_global2_core`) to 2.0M (`logical4_core`) cells
  reaching it. Unlike `galactic_core`, none of their logs carries a single
  `Couldn't topologically sort cells` warning, so this is a different obstacle
  from #657's. **The cause is now established (#695, 2026-11-16): a pre-ABC
  operator census per group (`RECORD.md`, each group's `census.md`) shows the
  cells are the multiply/accumulator arithmetic itself — 94–100 % of every
  design — not decode or control overhead.** The `rf_*` products are already
  reduced by Yosys's coarse passes to integer-exact widths (the widening
  hypothesis is measured-refuted there, #641's finding transfers);
  `logical4_core` keeps 10 unreduced 192-wide products (its declared-192-bit
  `mulr`/`rndsh` ports) and a 192-bit divider worth 34 % of the design, but
  narrowing cannot reach `exit 0`: the already-fully-narrow 20-product
  `rf_*` cores still die at ~250k cells in the same `abc -fast` step. The
  irreducible drivers (multiply-site count × call-site inlining, the
  divisions, the async ROMs) are schedule/contract questions (SXT-017,
  recorded for `#554`). Raising the budget again is not the next step (klt
  caps it at 3600 s, 2x what failed), and #641 already refuted the obvious
  width-narrowing hypothesis for `galactic_core`.
- `rf_ains34_core`, the one exit-0 group of the six, is **not** datapath
  evidence after all. Its module header declares only `clk`, `state_reset`,
  `start_block`, `block_done` and the two result arrays; its control plane and
  block inputs (`cfg_*`, `in_l`, `in_r`, `sc_in`) and its `sc_out` bit are
  internal `logic` poked hierarchically by `tb_rf_ains34.sv` — the same defect
  this issue was filed about, at the input end. Yosys therefore constant-folds
  the arithmetic away and the committed netlist is 3054 tie-lows + 2058 flops +
  2054 AND2 with no adder or multiplier. This predates #580 (#586 only added
  the two output arrays). `compare_rtl_model_rf_ains34.py` is nonetheless PASS,
  live-re-run on 2026-11-14 — it is a simulation harness that drives the core
  hierarchically, which is exactly why an exactness PASS cannot be read as
  evidence that the synthesized netlist contains the datapath.

`tests/test_t1_item1_synthesis.py` has a negative control that fails on a
netlist whose only output is `block_done`. It does **not** catch
`rf_ains34_core`: that control asks only for an output other than `block_done`,
and `out_l`/`out_r` satisfy it. Strengthening it to require the declared *input*
ports is tracked separately, because `tests/` is content-hashed by
`signoff/t1-item9-inventory.json` and editing it obliges re-attesting that
envelope in the same change.

**galactic_core obstacle (observed #572, re-measured #579, restructured and
re-measured #641; traced and loop-removed #657).** sv2v converts it (838 lines
before #641, 869 after). Yosys `synth` reaches ~270k generic cells and the
generic `abc` pass does not finish. The 300 s limit was an internal klt
default; it is now the request field `yosys_timeout_s` (klayout-tools#5412).

#579 raised it to **1800 s** under a throwaway `uvx` klt pinned to
`d9bc36811ddd` (unreleased at the time: the latest klt tag was then `v0.9.1`,
which does not carry the field. `v0.9.2`, tagged 2026-11-14, does — the #580
re-runs above used it — and `signoff/requirements.txt` still pins
`klayout-tools==0.8.0`, which does not). It
**still timed out** — verdict NO_VERDICT. It died inside `synth`'s generic ABC
pass at `4.22.1 Extracting gate netlist ... to input.blif`, with Yosys
reporting `Couldn't topologically sort cells` 20 times and ABC still breaking
combinational loops when the budget expired
(`galactic_core/timeout-progress.txt`).

#657 (2026-11-16) traced that condition with a hand-run pre-ABC `scc` probe:
the loops are created by `MEMORY_MAP` from the `counts`/`adv_idx` `$mem`
cells' write-enable/address logic tangled with the `advance` write-data path
— no cycle exists in the source. Making both arrays constant-indexed (plain
registers, no memory inference) removes **all** of it: the third 1800 s run
carries zero unsortable-cell warnings and zero loop reports, and **still**
dies at `4.22.1`. The loops are measured and refuted as the dominant cost;
what remains is generic ABC over ~2.8e5 cells of arithmetic, a
Yosys/ABC-side behaviour the repo cannot change from the RTL — recorded as
an upstream/tool-pin question, not acted on
(`galactic_core/RECORD.md`, #657 section).

**#641 then narrowed the arithmetic and re-ran at the same budget.** The RTL
now carries every product, sum and saturation at the narrowest integer-exact
width (32×32→64, a 66-bit MAC accumulator, a 38-bit saturation domain) with
the FSM schedule, the per-block cycle count and the `em_*` transaction order
untouched, and it is still integer-exact against the frozen model
(`reports/sxt-028a/rtl-exactness.json`, PASS, 3 mutant controls CONTROL-OK).
The coarse netlist confirms the narrowing — 11 `$mul_128` became 9 `$mul_64` +
2 `$mul_66`, no 128-bit operator remains, 23 % fewer wire bits, same 1301
coarse cells — and `synth` still **timed out in the same sub-step**: 394184 →
369383 cells entering OPT_MERGE, 271908 → 270383 after dedup (−0.6 %), the
same 20 unsortable-cell warnings, the same `4.22.1` blif extraction, killed at
1800 s. So the suspected 128-bit-arithmetic cause is **measured and refuted as
the dominant cost**, and the obstacle the log actually names — ABC breaking
combinational loops through `wcount`, the `counts` read mux and the `adv_idx`
memory-write data — survives the narrowing unchanged. That is a new,
untraced observation, escalated as **#657** rather than pursued here. Raising the budget
again is still not the next step (klt caps it at 3600 s, only 2x what has now
failed twice — a budget argument, not a mechanism). `failure.txt` stays a
NO_VERDICT (timeout), never a pass.

Pins: `pdk-pin.json`. Regenerate: `python3 signoff/t1-item1/regen.py [group...]`.
Any group in `regen.py`'s `YOSYS_TIMEOUT_S` table needs a klt that accepts
`yosys_timeout_s`, supplied via `$KLT` — see `RECORD.md` § "Reproduce" and
`galactic_core/RECORD.md`; the host-wide klt is never installed over.
`inventory.partial.json` + `item1.partial.envelope.json` attest 4 of 11 groups:
the 3 native groups plus `reverb1_core` (sv2v, real datapath). Not attested:
the 6 groups of #580 (five have no netlist at all — NO_VERDICT at 1800 s — and
`rf_ains34_core`'s netlist is the input-less shell described above) and
`galactic_core` (#579). Attesting a netlist that omits the datapath would
present constant-folded or sequencer-only output as item-1 evidence.
`rf_ains34_core` exits 0 and is deliberately still **out** of this inventory
for that reason; the inventory's own `description` field says so.
`klt signoff --attest 1` passes 12/12 (re-run 2026-11-14 under a throwaway
`uvx --from klayout-tools==0.9.2 klt`, a tagged release, after this change
edited the inventory's `description`; the envelope's `summary` and check counts
did not move, so `signoff/block-manifest.signoff.json` needed no re-render —
and the manifest does not cite this envelope at all).
Each freshness check is `klt synthesize --check ... --netlist <committed netlist>`:
report `netlist_path` fields name the removed `out/` scratch directory, so without
`--netlist` the check reports `netlist_sha256` as `drifted` (the earlier 3-group
envelope fails live for that reason; this change fixes it). Re-attest with
`klt signoff --attest 1 --inventory signoff/t1-item1/inventory.partial.json -o signoff/t1-item1/item1.partial.envelope.json`.
`klt signoff --check` applies only to `--manifest`/`--fleet`, not to an attest
envelope; the live re-derivation is the attest run itself.

Not proved: P&R, timing, DRC/LVS, RTL-vs-netlist equivalence, fidelity.
