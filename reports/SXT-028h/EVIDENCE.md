# SXT-028h evidence record — routing form: Scene-B insert FX bus, slots 1-2 (bins1 → bins2): frozen model, exact RTL, per-instance state + lifecycle, oracle-dependent legs BLOCKED (named compute gap)

Branch: `feature/issue-60` · Issue: #60 (SXT-028h) · Parent: #21 (SXT-028) ·
Epic: #3

Engine (external, GPL-3.0-or-later, pinned but not exercised by this leaf
beyond the census/graphs cross-check):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
(`oracle/manifest.json`). Structure authority:
`src/common/SurgeSynthesizer.cpp` `process()` per-scene insert block
(`loadFx()`, `enqueueFXOff()`, `reorderFx()`),
`src/common/SurgeStorage.h` `fxslot_positions`/`fxb_*`,
`src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h`.

**Claim discipline.** This record advances exactly one claim: *the RTL matches
the frozen fixed-point routing/scheduling model exactly* (iverilog;
demonstrated in §2). It establishes **no** model-vs-pinned-engine
reference-agreement number, **no** preset-support claim, **no**
musical-quality claim (no human listening), and **no** FPGA/gf180mcu
synthesis, timing, area, or hardware-playback claim. The per-slot occupant
used to exercise the routing arithmetic is a synthetic TDF2 biquad, not any
concrete Surge FX algorithm — see `model/effects/rf-rf-bins12/README.md`
"Form scope, not algorithm scope". No generic substitute is used under any
support claim; NC-A proves one is bit-exactly distinguishable from the
declared per-instance occupant and labels it ADAPTED.

## 0. Named gaps (recorded, not worked around)

### 0a. Oracle-dependent legs — BLOCKED

The pinned Surge XT engine's `surgepy` Python binding requires a full
C++/JUCE build (`oracle/fetch-and-build.sh`); that build was not available in
the environment that produced this record (dispatch worker, no host-side
oracle checkout; `oracle/manifest.json`'s pinned build path is a macOS path).
Per builder.md's "Long compute has three sanctioned answers", this is recorded
as a named, bounded gap rather than attempted as an unbounded local build or
silently skipped:

- **What IS verified without the oracle** (this record, in full): the frozen
  model itself; RTL-vs-model exactness (16 cases, §2); all 5 required negative
  controls, 13 legs, 0 NOT_RUN (§3); the three named B4-scope carrier presets'
  routing/scheduling metadata — slot occupancy, FX type, `fx_bypass`,
  `fx_disable`, scene mode, stored `return_level` — re-derived from the
  ALREADY-committed, ALREADY-surgepy-derived `corpus/census-v0.1` and
  `corpus/normalized/graphs.jsonl` (SXT-011 outputs), with **zero drift
  asserted between those two independent artifacts** (§4).
- **What is BLOCKED**: any per-slot algorithm-parameter extraction, the
  engine-side per-scene drift determinism gate, any wet-audio reference
  render, and therefore any model-vs-pinned-engine reference-agreement number
  for this leaf's fixtures (`tools/extract_rf_bins12_inputs.py`'s
  `oracle_extraction.ok` is `false` for all three carriers, recorded verbatim
  in `model/effects/fx_inputs/rf-rf-bins12-*.json`, never fabricated).
- **Reference budgets** [PROPOSED, not frozen] are therefore **NOT_RUN** for
  this leaf — not PASS and not FAIL. Freeze in any case is gated on SXT-017
  (#12) per the issue's own Acceptance section.

### 0b. One structural fact is a declared contract, not a verified read

The same missing oracle checkout means the pinned `process()` source text
could not be re-read while writing this leaf. Consequences, stated exactly:

- **Re-derived in-repo (verified here)**: the slot indices
  `fxslot_bins1 = 2`, `fxslot_bins2 = 3` (and `global1/2 = 6/7`) — every
  record of `corpus/normalized/graphs.jsonl` and
  `tools/export_normalized_graphs.py`'s `FX_ROLES` carry the pinned engine's
  slot order by patch `fx[]` index. Asserted by
  `tests/test_sxt028h.py::test_slot_indices_agree_with_the_committed_corpus_role_table`.
- **Declared contract (NOT re-read from the pinned source here)**: the
  insert stage's bypass-mode set — it runs in `fxb_all_fx`, `fxb_no_sends`
  and `fxb_scene_fx_only`, and is skipped only in `fxb_no_fx`. This is the
  complement, under the same enum, of the GLOBAL set (`all_fx`, `no_sends`)
  already pinned by the landed sibling leaf `model/effects/rf-rf-global2/`.
  **Re-verification item**: re-read the `process()` insert block against the
  pin the first time an oracle checkout is available, and correct the frozen
  model + RTL together if the partition differs. Nothing else in this leaf
  depends on it (the gate is one comparison; the schedule, lifecycle and
  per-instance-state claims are independent of which modes enter the block).
  Recorded here rather than presented as a verified citation.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (16 cases, 6,912 output samples + 108 checkpoints, 0 mismatches) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (oracle unavailable; §0a) | — |
| Negative controls live | **5/5 CONTROL-OK** (13 legs, 0 NOT_RUN; 2 are live RTL mutants) | `negative-controls/negative-controls.json` |
| Per-instance state (dual-slot) | **PASS** (model-level NC-D + live RTL shared-state mutant fails + RTL cases with both slots occupied) | `negative-controls.json`, `rtl-exactness.json` |
| Instance lifecycle (patch change mid-tail, slot off, panic/reset) | **PASS** (3 dedicated RTL cases + model tests) | `rtl-exactness.json` §2, `tests/test_sxt028h.py` |
| Declared tail span rendered | **PASS** (6 silent-input blocks, all carrying nonzero audio) | `rtl-exactness.json` (`tail-span-silent-input`) |
| Dropped-tail render | **FAILS the tail check, as required** | `negative-controls.json` NC-B |
| Carrier routing/scheduling metadata | **PASS** (3/3, census+graphs cross-checked, drift 0) | `model/effects/fx_inputs/rf-rf-bins12-*.json` |
| Complete-wet preset renders | **NOT_RUN** (oracle unavailable) | §0a |
| External-memory traffic | **PASS** (this leaf's own contribution: 0 words/sample; aggregate `[PENDING-SXT-016]`) | `artifacts/state-cost.json` |
| Newly-enabled presets | **0** (no support claim follows from this record) | §6 |
| Musical quality / listening | **NOT_RUN** (no listening record; #9 remains BLOCKED-on-human) | — |

## 1. Frozen model

`model/effects/rf-rf-bins12/rf_bins12_model.py` + `README.md`. Models scene
B's insert schedule: the control-rate instance-lifecycle pass (runs in every
bypass mode, as the engine's load/unload path does), the `fx_bypass` gate
(skip only in `no_fx`), the `fx_disable` per-slot bitmask gate (engine bit
layout, bits 2/3), and the in-place SERIES chaining of `process_ringout`
across two `InsertSlotInstance` objects (slot1/bins1, slot2/bins2), each
owning one independent `BiquadInstance` (TDF2, Q3.29 coefficients, 80-bit
accumulator). `model_revision()` pins the frozen file's sha256 for the
stale-harness control (§3, NC-E) and is echoed by the RTL comparator
(`rtl-exactness.json`).

Word formats (frozen): scene-bus audio **Q10.21 s32**, coefficients **Q3.29
s32**, TDF2 accumulator **80-bit signed**; exact products, round-half-up,
saturating; no floating point at audio run time.

Lifecycle (frozen, identical in model and RTL): slot off → that instance
released; occupancy rising or a `reload` pulse → FRESH instance for **that
slot only** (its registers cleared, the sibling's history and the scene ring
flag untouched); occupancy steady without reload → coefficients adopted with
state kept; `panic_reset()` / `state_reset` → both instances cleared and the
ring memory dropped, patch still loaded.

## 2. RTL-vs-model exactness

`rtl/effects/rf-rf-bins12/{rf_bins12_core.sv, tb_rf_bins12.sv}`, compared via
`tools/compare_rtl_model_rf_bins12.py` (iverilog; INTEGER EQUALITY of every
output sample and every per-instance checkpoint — both slots' TDF2 registers
plus the scene ring flag). The single harness is both the dual-instance bench
(each checkpoint line dumps slot1's and slot2's registers separately) and the
negative-control bench (§3 drives the mutants through the same stimulus path).

| Case | Blocks | Exercises |
|---|---|---|
| `both-slots-all-fx` | 6 | baseline: both slots occupied, `fx_bypass = ALL_FX` |
| `both-slots-no-sends` | 6 | `fx_bypass = NO_SENDS` (insert stage still runs) |
| `both-slots-scene-fx-only` | 6 | `fx_bypass = SCENE_FX_ONLY` — **insert-specific**: this stage RUNS where the global bus is skipped |
| `bypass-no-fx-skips-block` | 6 | `fx_bypass = NO_FX`: bus and ring flag pass through, no state advanced |
| `slot1-disabled-bit2` | 6 | `fx_disable` bit 2 set: bins1 skipped, bins2 still runs |
| `slot2-disabled-bit3` | 6 | `fx_disable` bit 3 set: bins2 skipped, bins1 still runs |
| `slot2-unoccupied-bins1-only` | 6 | single-instance shape (matches `Shore.fxp` / `Acoordion Basses.fxp`) |
| `slot1-unoccupied-bins2-only` | 6 | the complementary single-instance shape |
| `scene-not-live-passthrough` | 6 | `sc_in = false` throughout: neither slot ever processes |
| `scene-live-goes-false-mid-run` | 6 | scene ring flag true→false across blocks (ring cutoff) |
| `tail-span-silent-input` | 8 | 2 signal blocks + **6 blocks of SILENT input** while the scene stays live: the occupant's arithmetic tail must keep being rendered (all 8 blocks carry nonzero output) |
| `slot1-reload-mid-tail` | 8 | `loadFx()` on bins1 at block 3 mid-tail: bins1's history clears, bins2's continues |
| `slot2-off-mid-tail` | 8 | `enqueueFXOff()` on bins2 at block 3: its history is released, the stage no-ops |
| `panic-reset-mid-tail` | 8 | `state_reset` before block 4: BOTH instances clear, ring memory drops |
| `saturating-full-scale` | 4 | near-full-scale input through a high-gain occupant: the `sat32` audio-output saturation path (137/256 samples saturate) |
| `random-control-stream` | 12 | bypass mode, disable mask, occupancy, reload pulses and the scene-live flag all randomized per block |

**Result: 16/16 exact, 0 mismatches, 6,912 output samples + 108 per-instance
checkpoints compared.** Full record: `rtl-exactness.json` (`status: "PASS"`).

The comparator refuses to report PASS against a stale frozen model:
`--assert-model-revision <hex>` exits 2 with `status: "REFUSED"` when the
pinned revision does not match the live model file (§3, NC-E leg 2 invokes
exactly that path).

## 3. Negative controls (all 5 required; `tools/rf_bins12_negative_controls.py`)

Every control reports per-leg status; a leg that could not run would be
recorded `NOT_RUN` and never counted as a demonstrated failure. In this
environment **0 legs were NOT_RUN** (iverilog present).

| Control | Targets | Legs | Verdict |
|---|---|---|---|
| **NC-A** generic substitute (pass-through + fixed gain in bins2) | per-instance-state faithfulness / coverage eligibility | output bit-exactness (4/4 blocks differ); per-instance state (substitute keeps no history) | **CONTROL-OK** — labeled `ADAPTED`, `counts_toward_original_preset_coverage: false` |
| **NC-B** dropped tail (2 of 8 declared blocks rendered) | declared tail-span coverage | dropped region demonstrably carries audio (6/6 dropped blocks nonzero, Σ\|x\| = 2,174,983); coverage check fails; final per-instance checkpoint differs | **CONTROL-OK** |
| **NC-C** wrong order (bins1/bins2 permutation) | order-sensitive equality | model, saturating pair (380/384 samples differ, max Δ = 159,567,573); model, purely linear pair (79/512 differ, max Δ = 1 — see caveat); **live RTL mutant** `-DNC_SWAP_ORDER` (59 output + 6 checkpoint mismatches of 384 samples / 6 checkpoints compared) | **CONTROL-OK** |
| **NC-D** shared state (both slots pooled into one history) | dual-instance independence | model pooled mutant (6/6 blocks differ, pooled checkpoint halves become identical); **live RTL mutant** `-DNC_SHARED_STATE` (199 output + 6 checkpoint mismatches of 384 samples / 6 checkpoints compared) | **CONTROL-OK** |
| **NC-E** stale stub (frozen-revision pin) | stale-harness refusal | `revision_pin_ok()` rejects a mutated pin; the real comparator invoked with a stale pin exits 2 with `status: "REFUSED"` | **CONTROL-OK** |

**5/5 CONTROL-OK** (a control that passes its target check would be a broken
control, per issue #60's own framing). Full record:
`negative-controls/negative-controls.json` (`status: "PASS"`), transcript in
`negative-controls/negative-controls.txt`. The two live RTL mutants are
`rtl/effects/rf-rf-bins12/rf_bins12_mutants.sv`, compiled INSTEAD of the real
core and driven through the production testbench; compiled with no defect
selected the file refuses to simulate (`$fatal`), so it cannot silently become
a passing "control".

**Honest caveat on NC-C (recorded, not hidden).** Two LTI biquads in series
*commute* in exact arithmetic, so permuting this leaf's synthetic linear
occupants is detectable only through fixed-point rounding — 79 of 512 samples
differ, by 1 LSB. Integer-exact equality (this leaf's actual acceptance check)
does flag it, and with an intermediate stage that saturates the same
permutation diverges grossly (max Δ ≈ 1.6e8). The engine's real insert
occupants are not LTI, so real slot permutations are far more visible; but the
*strength* of this leaf's order control is bounded by its synthetic occupant,
and that bound is stated here rather than implied away. It does not affect the
RTL-vs-model exactness claim.

## 4. Carrier routing/scheduling metadata (oracle-independent, zero-drift)

`tools/extract_rf_bins12_inputs.py` re-verifies the census blob sha1
(`corpus/census-v0.1/results/per-preset.csv`), cross-checks
`corpus/normalized/graphs.jsonl` (already surgepy-derived and committed;
SXT-011), and **asserts zero drift between those two independent artifacts**
on every field both carry (blob sha1, stored revision, scene mode,
`fx_bypass`, `fx_disable`, non-off FX slot count, non-off FX type set). Any
disagreement is a refusal, not a silently preferred source
(`tests/test_sxt028h.py::test_extraction_refuses_injected_drift` injects drift
and requires the refusal).

| Preset | bins1 | bins2 | `fx_bypass` | `fx_disable` | Scene mode | Dual-instance concurrent? |
|---|---|---|---|---|---|---|
| `A.Liv/Leads/Novuo.fxp` | EQ (on) | Chorus (on) | All FX | 0 | Dual | **yes** |
| `Aleksey Zhehanov/Keys/Acoordion Basses.fxp` | EQ (on) | Off | All FX | 0 | Key Split | no (single-instance) |
| `Altenberg/FX/Shore.fxp` | Reverb 2 (on) | Off | All FX | 0 | Dual | no (single-instance) |

3/3 census blob + graphs cross-checks PASS, drift count 0, 0 refusals
(`artifacts/extract-refusals.txt` empty). `Novuo.fxp` genuinely exercises the
two-concurrent-insert-instance shape this leaf claims — and does it with two
*different* FX classes in the two slots, which is exactly the
"shared arithmetic, independent per-instance state" case; the other two
exercise the complementary single-occupied-slot shape (RTL cases
`slot2-unoccupied-bins1-only` / `slot1-unoccupied-bins2-only`). All three are
multi-scene patches, so scene B is instantiated at all
(`scene_context.scene_b_instantiated`); a Single-scene patch's bins slots
would be unreachable and is recorded as such rather than assumed.

Per-slot algorithm parameter values are NOT extracted (§0a — oracle
unavailable); each record carries `oracle_extraction.ok: false` with the
reason. Stored per-slot `return_level` is recorded but explicitly **not
consumed** by the insert path (`return_level_consumed_by_insert_path: false`)
— return/send-level semantics belong to the send-form (`rf-send*`) leaves.

## 5. External-memory traffic

`artifacts/state-cost.json`: this leaf's own contribution (the routing /
scheduling / lifecycle logic plus its synthetic register-only occupant kernel)
is **0 external-memory words/sample**; on-chip small state is 663 bits
(2 × 321 per-instance bits + 21 shared routing/lifecycle control bits). The
AGGREGATE estimate for a concrete preset also depends on whichever algorithm
leaf's occupant actually lands in bins1/bins2 (EQ + Chorus for `Novuo.fxp`,
Reverb 2 for `Shore.fxp`), which is that leaf's own SXT-015/016 accounting,
not invented here — **`[PENDING-SXT-016]`** per the issue text. Long
delay/reverb-class buffers belong in external WRITABLE memory; flash is not
writable delay memory (AGENTS.md) — not applicable to this leaf's own
register-only contribution.

## 6. Newly enabled presets

**0.** This record establishes no preset-support claim (§0a); the issue's own
`newly_enabled` accounting
(`reports/sxt-028/leaves/SXT-028h/newly-enabled.json`, FX-scope-only and
explicitly "NOT a support claim") is unaffected by this leaf landing.
Coverage remains reported separately from agreement: this leaf's coverage
contribution to the FX-routing axis is the bins1/bins2 insert form; its
agreement contribution is exactly the RTL↔model exactness claim in §2 and
nothing else.

## 7. Stop/escalate status

The issue's stop condition ("if the effect cannot be bounded in state/cost
under the shared instance schedule, record the finding and route to SXT-017")
was **not** triggered: this form's state is bounded and small (§5), with no
external-memory requirement of its own. Two items are routed onward rather
than closed here: the oracle-dependent reference legs (§0a, blocked on an
oracle build) and the bypass-partition re-verification item (§0b). The
[PROPOSED] reference budgets remain unfrozen, gated on SXT-017 (#12).

## Reproduce

```sh
python3 tools/extract_rf_bins12_inputs.py
python3 tools/compare_rtl_model_rf_bins12.py --out reports/SXT-028h/rtl-exactness.json
python3 tools/rf_bins12_negative_controls.py
python3 -m pytest tests/test_sxt028h.py -q
```
