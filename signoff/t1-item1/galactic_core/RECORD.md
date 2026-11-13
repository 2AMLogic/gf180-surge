# galactic_core — synthesizability record (#579, tracker #572, parent #537)

Verdict: **NO_VERDICT** (unchanged). Not PASS, not FAIL.

The 300 s budget this record was previously blocked on has been raised and the
run re-made. It still timed out, so the verdict does not move: a timeout is a
budget outcome, never a proof of non-synthesizability and never a pass.

| Field | Value |
|---|---|
| Request | `request.json` (`sv_frontend: "sv2v"`, sv2v 0.0.13, `defines: {SYNTHESIS}` per the item-1 route, `yosys_timeout_s: 1800`) |
| klt | `0.9.2.dev890+gd9bc36811ddd` — a **throwaway `uvx` environment** pinned to git rev `d9bc36811ddd11fcf9c60d3a9275858296db8b44` of `2AMLogic/klayout-tools` (the merge of klayout-tools#5413 for #5412). **Not a tagged release**: the latest klt tag is `v0.9.1`, 890 commits behind that merge, and `signoff/requirements.txt` still pins `klayout-tools==0.8.0`. The host-wide klt was not modified. |
| Yosys budget | **1800.0 s** (30 min), from the request's `yosys_timeout_s`; klt's cap is 3600 s and its default is still 300 s |
| Outcome | Yosys killed at the budget (`failure.txt`); exit status 1; wall clock 1804 s for the whole `klt synthesize` call |
| Progress reached | `timeout-progress.txt` (distilled from the Yosys log klt writes beside the executed script). `synth` got through TECHMAP and the fast OPT passes and died inside its **generic ABC pass**, at step `4.22.1 Extracting gate netlist of module '\galactic_core' to '<abc-temp-dir>/input.blif'` (line 675). The script's later `abc -liberty`, `stat` and `write_verilog` never ran, so there is no instance count, no area, and no netlist. |
| Cell count reached | 394184 generic cells entering OPT_MERGE after TECHMAP (line 591); dedup removed 122276, leaving 271908 (lines 659, 662); the following OPT_CLEAN removed 153496 unused cells and 20968 unused wires (line 668). So of order 1.2e5 cells reached the generic ABC pass — a derived figure (OPT_DFF runs between the two counts), not a klt-reported number. 271908 is the klt-recorded count that matches the issue's manual "~272k generic cells". |

## What the raised budget bought

Reproduce with the pinned klt (never the host one):

```
KLT='uvx --from "git+https://github.com/2AMLogic/klayout-tools.git@d9bc36811ddd11fcf9c60d3a9275858296db8b44" klt' \
  python3 signoff/t1-item1/regen.py galactic_core
```

Six times the budget (300 s -> 1800 s) did **not** change the outcome, and the
log says why: the cost is not a slow-but-finishing mapping, it is ABC's gate
extraction over a design Yosys cannot order. The excerpt records, 20 times,
`Couldn't topologically sort cells, optimizing module galactic_core may take a
longer time`, and ABC then breaks combinational loops one signal at a time
(`Breaking loop using new signal $abcloop$...`) across `maccmap` full-adder
carries, a `counts` memory read mux, and the `adv_idx` memory-write data — it
was still emitting those when the budget expired. (The `$abcloop$` numbers are
Yosys's global autoidx counter, not a loop count; the log is truncated
mid-emission, so the number of loops broken is not established here.)

That is a structural property of the 32-sample block unrolled combinationally,
not a budget that was merely a little too small. Raising the budget again is
therefore **not** the next step: klt's own cap is 3600 s, only 2x what already
failed, and nothing in this log suggests the pass was close to finishing.

## Decision

- Longer-budget re-run: **DONE, and it is exhausted as an approach.** The
  budget is now a request field (klayout-tools#5412), it was raised to 1800 s,
  and the run still timed out.
- Next step is the **restructure** the 2026-11-13 decision named as the
  evidence-gated fallback: a sequential sample loop instead of a combinational
  32-sample unroll. Filed as **#641**. That is an RTL change to a `product`
  file and is **not** made here.
- `rtl/effects/aw-49/galactic_core.sv` is **not** in the byte-frozen registry
  (`docs/byte-frozen-sources.{md,json}`; re-checked live for this record,
  sha256 `7b64384cb02d052fbd6499428375cdc21f3a4af7c6f982f4ef94e661cb18e4c4`).
  It is still referenced by `rtl/lint_manifest.json`, `rtl/lint_waivers.json`,
  `tools/compare_rtl_model_aw49.py`, `reports/sxt-028a/EVIDENCE.md` and
  `reports/rtl-lint/EVIDENCE.md`; #641 names each as a record to re-derive.

## Failure controls run for this record

Both are cheap and both must hold, or the budget above would be decoration:

1. **The budget is not silently ignored.** The pre-fix host klt
   (`0.9.2.dev885+ge4c446bd91f2`, 5 commits behind `d9bc368`) refuses this very
   `request.json`: `unknown field 'yosys_timeout_s' -- this klt does not
   recognise it`. So a 300 s run cannot be mistaken for a 1800 s one.
2. **The budget is validated, not merely accepted.** The pinned klt rejects an
   over-cap value: `request.yosys_timeout_s must be a finite number > 0 and
   <= 3600 (seconds); got 3700`.

## Coverage, kept separate from agreement

This record is one group's synthesizability attempt. Not proved here:
synthesizability of `galactic_core`, P&R, timing, DRC/LVS, RTL-vs-netlist
equivalence, RTL-vs-frozen-model exactness, or fidelity to the pinned Surge
reference. `galactic_core` remains unattested in
`signoff/t1-item1/inventory.partial.json`.
