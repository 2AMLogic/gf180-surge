# galactic_core — synthesizability record (#641, after #579; tracker #572, parent #537)

Verdict: **NO_VERDICT** (unchanged). Not PASS, not FAIL. The 2026-11-16
#657 section below traces and removes the unsortable-cells / ABC
combinational-loop condition and re-runs at the same budget: the loop
reports are gone, the outcome is not.

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

---

# #657 (2026-11-16): the unsortable-cells / ABC loop condition traced, removed, and refuted as the dominant cost

Verdict after this change: still **NO_VERDICT** for synthesizability. The
third 1800 s run — on RTL whose loop reports are **all gone** — was killed in
the same sub-step. So the memory-mapping hypothesis this issue suspected is
**confirmed for the loop reports** (they are the memory mapping; removing it
removes every report) and **refuted as the dominant ABC cost** (the run still
times out without them). A timeout is a budget outcome, never a pass.

## The probe (hand-run Yosys diagnostic, not a klt verdict)

Tools, on this host, in a `/tmp` scratch directory, run once sequentially:
`sv2v` v0.0.13 and `Yosys 0.67+post (git sha1 b8e7da6f40ae8f552c116bf6c359b07c6533e159)`
— the same 0.67 series the committed klt log drives (`timeout-progress.txt`
names `.cache/yosys-0.67/…/techmap.v`), so the probe is representative. The
sv2v conversion used klt's own invocation shape:

```
sv2v --incdir=rtl/effects/aw-49 --define=SYNTHESIS \
     -w /tmp/probe-657/galactic_core_sv2v.v rtl/effects/aw-49/galactic_core.sv
```

Two `scc` readings around the `MEMORY_MAP` boundary (`-all_cell_types` on the
first one, because `scc` otherwise skips `$mem` cells and could not see a
memory-port cycle; `-run :fine` stops before `MEMORY_MAP`):

```
yosys -p "read_verilog -D SYNTHESIS /tmp/probe-657/galactic_core_sv2v.v;
          hierarchy -check -top galactic_core;
          synth -top galactic_core -run :fine;
          tee -o /tmp/probe-657/scc-before.txt scc -all_cell_types -nofeedback;
          memory_map; opt -full;
          tee -o /tmp/probe-657/scc-after.txt scc -nofeedback;
          check"
```

Whole probe: 6.5 s. Results on the pre-#657 RTL (the #641 bytes):

- **Before `MEMORY_MAP`** (`scc -all_cell_types -nofeedback`): **5 SCCs**.
  The largest threads the `counts` `$mem` cell itself, the `advance`
  ternaries (`sv2v` line 631), `memory_share` write-consolidation cells and
  the `wcount` procmuxes; the other four run through `$ff` slice cells
  (`st`/`k`/`ln`/advance counter feedback). Neither kind is a source-level
  combinational loop: `counts`/`adv_idx` are written only under
  non-blocking assignment on a clock edge, and `scc` treats a `$mem` cell's
  write→read ports and an FF's Q→D as plain graph edges. Graph artifacts of
  the sequential boundaries — but the `$mem`-threaded SCC is the smoke.
- **After `MEMORY_MAP` + `opt -full`** (`scc -nofeedback`): **1 SCC of
  purely combinational cells**, and `check` reports **8 "found logic loop"**
  warnings — real netlist loops, not graph artifacts. The loop trace closes
  through exactly the three sites the timed-out ABC logs name: the
  `counts` read mux (`$memory\counts$rdmux…`) output feeds the `advance`
  adder/comparison chain (`sv2v:631` ALU cells), whose carry feeds
  `opt_share`'s activation logic (`$eq`/`$reduce_or` over the memory
  write-enable conditions), which feeds the counts read-**address** select
  back into the same read mux. All **20** `Couldn't topologically sort`
  warnings of the klt runs reproduce in this 6.5 s probe log.

## Where the cycles are, and the RTL change

The cycles are **the memory mapping of `counts`/`adv_idx`**: both arrays
infer as `$mem` cells from variable-indexed access, and
`memory_map` + the opt passes turn their write-enable/address logic and the
`advance` write-data path into one combinational tangle ABC must break one
signal at a time. Read from source there is no cycle; created by
`MEMORY_MAP`, there is.

The change: every variable subscript on the two arrays is replaced by an
explicit `case (ln[1:0])` decode with constant indices (`wcount`'s read, the
three `em_addr` `adv_idx` reads, the three ADV states' writes), so Yosys
infers the 12 + 4 words as plain registers. Ports, FSM schedule, per-block
cycle count and `em_*` transaction order are untouched. The same probe on
the new bytes: `scc -all_cell_types` before `MEMORY_MAP` reports **16 SCCs,
every one through `$ff` slices** (counter feedback, no `$mem` threading);
after `MEMORY_MAP`, **0 SCCs**; `check` reports **0 logic loops**; the probe
log carries **0** unsortable-cell warnings. The 15 `$mem_v2` cells that
remain in the coarse netlist are all `proc_rom` constant-table ROMs
(`do_switch` cells), not the state arrays.

## Synthesis at the same budget, on the changed RTL

`python3 signoff/t1-item1/regen.py galactic_core` under the same pinned klt
as #579/#641 (`0.9.2.dev890+gd9bc36811ddd`, throwaway `uvx` environment,
never the host klt), `request.json` byte-identical to both prior runs,
`yosys_timeout_s` 1800. Outcome: **killed at the budget again, in the same
sub-step** (`4.22.1` blif extraction, `exit_status.txt` = 1, `failure.txt`
records the timeout). `abc -liberty` and `stat` never ran, so there is still
no instance count and `galactic_core` stays unattested. The run's orphaned
`yosys-abc` child was killed afterwards (the #580/#695 edge case).

| | #579 (128-bit RTL) | #641 (narrowed) | #657 (constant-indexed) |
|---|---|---|---|
| cells entering OPT_MERGE after TECHMAP (first hash count) | 394184 | 369383 | 375737 |
| removed by OPT_MERGE (dedup) | 122276 | 99000 | 98643 |
| cells after dedup | 271908 | 270383 | 277094 |
| removed by the following OPT_CLEAN | 153496 cells, 20968 wires | 151342 cells, 15295 wires | 152272 cells, 18218 wires |
| `Couldn't topologically sort cells` | 20 | 20 | **0** |
| `Breaking loop` reports before truncation | 35 | 35 | **0** |
| last step reached | `4.22.1` blif extraction | `4.22.1` blif extraction | `4.22.1` blif extraction |
| outcome at 1800 s | killed | killed | killed |

Coarse cells before TECHMAP (`read_verilog; hierarchy -top galactic_core;
proc; opt_expr; opt_clean; memory_collect; stat -width` on the new `sv2v`
output): **1611** cells / **42511** wire bits, multipliers still
9 × `$mul_64` + 2 × `$mul_66` — was 1301 / 37201 in #641. The +310 cells and
+5310 wire bits are the explicit case-decode muxes that replace the memory
representation (the mux logic was always there; it is now built by the
frontend instead of by `memory_map`), not datapath growth.

## What this establishes, and what it escalates

1. **The loop reports were the memory mapping** (outcome (a), measured):
   a change that removes memory inference removes all 20 unsortable-cell
   warnings and all 35 `$abcloop` reports, at the same budget, with the
   request bytes unchanged.
2. **The loops were not the dominant ABC cost** (outcome (b), the
   #641-style refutation): without a single loop report, `synth` still dies
   at the same step with a slightly *higher* generic cell count (277094 vs
   270383). The remaining obstacle is the generic ABC mapping of ~2.8e5
   cells of arithmetic — a Yosys/ABC behaviour this repository cannot change
   from the RTL side. Per the issue's stop condition that is an
   upstream/tool-pin question (klayout-tools / Yosys / ABC version or
   script), recorded here and in #657, not acted on. Raising
   `yosys_timeout_s` stays rejected for the same budget arithmetic as
   before: no run has emitted a single mapped gate.
3. **Fidelity is unaffected**: `tools/compare_rtl_model_aw49.py` re-run under
   the CI-pinned numpy 2.4.2 — **PASS**, all four cases integer-exact,
   **four** mutant controls CONTROL-OK
   (`reports/sxt-028a/rtl-exactness.json`), and all four real-case
   `txn_log_sha256` values are byte-identical to the previously committed
   record: the change moves no transaction. The fourth control,
   `mutant-wrong-counter-map`, was added in this change and is shown
   **FAILING** (wiring the stage-2 `adv_idx[0]` capture to the stage-1
   counter must break the comparison, and does); `mutant-narrow-product`
   still fails. The RTL lint baseline was re-keyed for the moved lines —
   same 101 `galactic_core` entries, rule+message+count multiset identical,
   total unchanged at 703 (`reports/rtl-lint/EVIDENCE.md`, #657 update).

This file records synthesizability progress only. It establishes nothing
about P&R, timing, area, RTL-vs-netlist equivalence, or fidelity.

Reproduce (never the host klt):

```
KLT='uvx --from "git+https://github.com/2AMLogic/klayout-tools.git@d9bc36811ddd11fcf9c60d3a9275858296db8b44" klt' \
  python3 signoff/t1-item1/regen.py galactic_core
```

The probe is a hand-run diagnostic: it is not a `klt synthesize` verdict and
does not replace one; every item-1 verdict still comes from `regen.py`
under the pinned klt.
