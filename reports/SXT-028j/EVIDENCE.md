# SXT-028j evidence record — routing form: Global FX slots 3-4 (global3 → global4, extended rack half): frozen model, exact RTL, per-instance state + lifecycle, oracle-dependent legs BLOCKED (named compute gap)

Branch: `feature/issue-62` · Issue: #62 (SXT-028j) · Parent: #21 (SXT-028) ·
Epic: #3

Engine (external, GPL-3.0-or-later, pinned but not exercised by this leaf
beyond the census/graphs cross-check):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
(`oracle/manifest.json`). Structure authority:
`src/common/SurgeSynthesizer.cpp` `process()` "apply global effects" block
(`loadFx()`, `enqueueFXOff()`, `reorderFx()`),
`src/common/SurgeStorage.h` `fxslot_positions`/`fxb_*`,
`src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h`.

**Claim discipline.** This record advances exactly one claim: *the RTL
matches the frozen fixed-point routing/scheduling model exactly* (iverilog;
demonstrated in §2). It establishes **no** model-vs-pinned-engine
reference-agreement number, **no** preset-support claim, **no**
musical-quality claim (no human listening), and **no** FPGA/gf180mcu
synthesis, timing, area, or hardware-playback claim. The per-slot occupant
used to exercise the routing arithmetic is a synthetic TDF2 biquad, not any
concrete Surge FX algorithm — see
`model/effects/rf-rf-global34/README.md` "Form scope, not algorithm scope".
No generic substitute is used under any support claim; NC-A proves one is
bit-exactly distinguishable from the declared per-instance occupant and
labels it ADAPTED.

## 0. Named gaps (recorded, not worked around)

### 0a. Oracle-dependent legs — BLOCKED

The pinned Surge XT engine's `surgepy` Python binding requires a full
C++/JUCE build (`oracle/fetch-and-build.sh`); that build was not available
in the environment that produced this record (dispatch worker, no host-side
oracle checkout; `oracle/manifest.json`'s pinned build path is a macOS
path). The probe is **measured, not asserted** —
`tools/rf_global34_oracle_status.py` actually attempts the checkout lookup
and the `import surgepy`, and writes what it found to
`artifacts/oracle-status.json` (`oracle_status: "UNAVAILABLE"`,
`surgepy_importable: false`, `engine_dir_present: false`). Per builder.md's
"Long compute has three sanctioned answers", this is recorded as a named,
bounded gap rather than attempted as an unbounded local build or silently
skipped:

- **What IS verified without the oracle** (this record, in full): the frozen
  model itself; RTL-vs-model exactness (18 cases, §2); all 5 required
  negative controls, 15 legs, 0 NOT_RUN (§3); five corpus carriers'
  routing/scheduling metadata — slot occupancy, FX type and Airwindows
  sub-algorithm, `fx_bypass`, `fx_disable`, upstream chain context, stored
  `return_level` — re-derived from the ALREADY-committed,
  ALREADY-surgepy-derived `corpus/census-v0.1` and
  `corpus/normalized/graphs.jsonl` (SXT-011 outputs), with **zero drift
  asserted between those two independent artifacts** (§4); and a
  corpus-wide occupancy scan for this routing form's shapes (§6, coverage
  only).
- **What is BLOCKED**: this leaf's Fixtures plan calls for **new** reference
  fixtures (no SXT-014 ablation carrier exists for this routing form), so
  per-slot algorithm-parameter extraction, the original / per-slot-bypass /
  all-off-dry renders, the engine-side per-scene drift determinism gate, and
  therefore any model-vs-pinned-engine reference-agreement number are all
  **NOT_RUN**. Recorded per leg in `artifacts/oracle-status.json` and as a
  refusal transcript in `artifacts/render-refusals.txt`;
  `tools/extract_rf_global34_inputs.py`'s `oracle_extraction.ok` is `false`
  for all five carriers, written verbatim into
  `model/effects/fx_inputs/rf-rf-global34-*.json`, never fabricated.
- **Reference budgets** [PROPOSED, not frozen] are therefore **NOT_RUN** for
  this leaf — not PASS and not FAIL. Freeze in any case is gated on SXT-017
  (#12) per the issue's own Acceptance section.

### 0b. Two structural facts are declared contracts, not verified reads

The same missing oracle checkout means the pinned `process()` source text
could not be re-read while writing this leaf. Consequences, stated exactly:

- **Re-derived in-repo (verified here)**: the slot indices
  `fxslot_global3 = 14`, `fxslot_global4 = 15` (and `global1/2 = 6/7`).
  Every one of the **3,561** records in `corpus/normalized/graphs.jsonl`
  carries the pinned engine's slot order by patch `fx[]` index, and
  `tests/test_sxt028j.py::test_slot_indices_agree_with_the_committed_corpus_role_table`
  checks **all** of them (not just the first), because this leaf owns the
  highest two indices and a truncated `fx[]` list would otherwise go
  unnoticed. The extractor re-checks the same table per carrier
  (`slot_index_check`) and REFUSES on disagreement.
- **Declared contract #1 (NOT re-read from the pinned source here)**: the
  GLOBAL stage's bypass-mode set — it runs in `fxb_all_fx` and
  `fxb_no_sends`, and is skipped in `fxb_scene_fx_only` and `fxb_no_fx`.
  Taken from the landed sibling GLOBAL leaf
  `model/effects/rf-rf-global2/rf_global2_model.py`, which pinned it while
  citing the same `process()` block, and complementary to the INSERT set
  pinned by `model/effects/rf-rf-bins12/rf_bins12_model.py`. Consistency
  note: the whole corpus contains **0** presets with a non-`All FX`
  `fx_bypass` and an occupied global3/global4
  (`artifacts/corpus-occupancy.json`), so no committed corpus carrier
  discriminates the partition either way.
- **Declared contract #2**: the engine-side queue-drain timing of
  `enqueueFXOff()`. This leaf's lifecycle applies slot-off at the
  control-rate pass preceding a block. The model and the RTL match each
  other exactly on that contract (claim 1 is unaffected); whether the
  engine's own queue drains at the same boundary is unverified here.
- **Re-verification item** (both contracts): re-read the `process()` global
  block and the FX-off queue against the pin the first time an oracle
  checkout is available, and correct the frozen model + RTL together if
  either differs. Nothing else in this leaf depends on them (the bypass gate
  is one comparison; the schedule, per-instance-state and tail claims are
  independent of which modes enter the block and of the off-request
  latency).

### 0c. The issue's named carriers do not cover the dual-instance shape

All three B4-scope carriers named by the issue (`Jigsaw.fxp`, `Pixel.fxp`,
`Lazy.fxp`) occupy **global3 only** — `global4` is Off in all three. None of
them exercises the two-concurrent-instance shape this leaf's Acceptance
checklist requires. Rather than weaken the acceptance item, two further
carriers were added from the same committed corpus and verified through the
identical fail-closed path (§4). This finding is asserted by
`tests/test_sxt028j.py::test_issue_named_carriers_do_not_cover_the_dual_instance_shape`
so it cannot silently drift.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (18 cases, 7,680 output samples + 120 checkpoints, 0 mismatches) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (oracle unavailable; §0a) | `artifacts/oracle-status.json` |
| Negative controls live | **5/5 CONTROL-OK** (15 legs, 0 NOT_RUN; 3 are live RTL mutants) | `negative-controls/negative-controls.json` |
| Per-instance state (dual-slot) | **PASS** (model NC-D + live RTL shared-state mutant fails, incl. the same-FX-class case) | `negative-controls.json`, `rtl-exactness.json` |
| Instance lifecycle (patch change mid-tail, slot off, panic/reset) | **PASS** (3 dedicated RTL cases + model tests) | `rtl-exactness.json` §2, `tests/test_sxt028j.py` |
| Declared tail span rendered | **PASS** (6 silent-input blocks, all carrying nonzero audio) | `rtl-exactness.json` (`tail-span-silent-input`) |
| Dropped-tail render | **FAILS the tail check, as required** | `negative-controls.json` NC-B |
| Seam with the landed global1→global2 segment | **PASS** (model-level 4-slot composition, 4 independent histories) | `tests/test_sxt028j.py::test_seam_composes_with_the_landed_global12_segment` |
| Carrier routing/scheduling metadata | **PASS** (5/5, census+graphs cross-checked, drift 0) | `model/effects/fx_inputs/rf-rf-global34-*.json` |
| Complete-wet preset renders / new reference fixtures | **NOT_RUN** (oracle unavailable) | §0a, `artifacts/render-refusals.txt` |
| External-memory traffic | **PASS** (this leaf's own contribution: 0 words/sample; aggregate `[PENDING-SXT-016]`) | `artifacts/state-cost.json` |
| Newly-enabled presets | **0** (no support claim follows from this record) | §6 |
| Musical quality / listening | **NOT_RUN** (no listening record; #9 remains BLOCKED-on-human) | — |

## 1. Frozen model

`model/effects/rf-rf-global34/rf_global34_model.py` + `README.md`. Models
the **tail half** of the "apply global effects" schedule: the control-rate
instance-lifecycle pass (runs in every bypass mode, as the engine's
load/unload path does), the `fx_bypass` gate (run only in
`ALL_FX`/`NO_SENDS`), the `fx_disable` per-slot bitmask gate (engine bit
layout, bits **14/15**), and the in-place SERIES chaining of
`process_ringout` across two `GlobalSlotInstance` objects (slot3/global3,
slot4/global4), each owning one independent `BiquadInstance` (TDF2, Q3.29
coefficients, 80-bit accumulator). `model_revision()` pins the frozen file's
sha256 for the stale-harness control (§3, NC-E) and is echoed by the RTL
comparator (`rtl-exactness.json`) and the state-cost record.

Word formats (frozen): master-bus audio **Q10.21 s32**, coefficients
**Q3.29 s32**, TDF2 accumulator **80-bit signed**; exact products,
round-half-up, saturating; no floating point at audio run time.

**Declared seam.** global3/global4 are the last two slots of the four-slot
global chain, so the bus and ring flag arriving at global3 are whatever the
`global1 → global2` segment left. That segment is the already-landed sibling
leaf `model/effects/rf-rf-global2/` (SXT-028d, #56) and is **not**
re-claimed here; it arrives as this leaf's `in_l`/`in_r`/`glob_in`. The seam
is exercised, not merely asserted:
`test_seam_composes_with_the_landed_global12_segment` composes the two
landed models into the full chain, checks that the two leaves agree on the
shared slot table and on the bus/coefficient word formats, that all **four**
slot instances end with four *distinct* histories, and that the chain is
order-sensitive across the seam.

Lifecycle (frozen, identical in model and RTL): slot off → that instance
released; occupancy rising or a `reload` pulse → FRESH instance for **that
slot only** (its registers cleared, the sibling's history and the ring flag
untouched); occupancy steady without reload → coefficients adopted with
state kept; `panic_reset()` / `state_reset` → both instances cleared and the
ring memory dropped, patch still loaded.

## 2. RTL-vs-model exactness

`rtl/effects/rf-rf-global34/{rf_global34_core.sv, tb_rf_global34.sv}`,
compared via `tools/compare_rtl_model_rf_global34.py` (iverilog; INTEGER
EQUALITY of every output sample and every per-instance checkpoint — both
slots' TDF2 registers plus the ring flag). The single harness is both the
dual-instance bench (each checkpoint line dumps slot3's and slot4's
registers separately) and the negative-control bench (§3 drives the mutants
through the same stimulus path).

| Case | Blocks | Exercises |
|---|---|---|
| `both-slots-all-fx` | 6 | baseline: both slots occupied, `fx_bypass = ALL_FX` |
| `both-slots-no-sends` | 6 | `fx_bypass = NO_SENDS` (global stage still runs) |
| `bypass-scene-fx-only-skips-block` | 6 | `fx_bypass = SCENE_FX_ONLY` — **global-specific**: this stage is SKIPPED where the scene insert bus still runs |
| `bypass-no-fx-skips-block` | 6 | `fx_bypass = NO_FX`: bus and ring flag pass through, no state advanced |
| `slot3-disabled-bit14` | 6 | `fx_disable` bit 14 set: global3 skipped, global4 still runs |
| `slot4-disabled-bit15` | 6 | `fx_disable` bit 15 set: global4 skipped, global3 still runs |
| `both-slots-disabled-bits14-15` | 6 | **real-corpus shape** (`Bassoon.fxp`, `fx_disable = 49152`): both occupied, both disabled |
| `slot4-unoccupied-global3-only` | 6 | the issue-named carriers' shape (`Jigsaw`/`Pixel`/`Lazy`: global3 only) |
| `slot3-unoccupied-global4-only` | 6 | the complementary single-instance shape |
| `same-class-dual-occupants` | 6 | **real-corpus shape** (`String Contrabass.fxp`: Airwindows *Galactic* in BOTH slots) — identical coefficients, and the final histories must still differ |
| `ring-never-true-passthrough` | 6 | `glob_in = false` throughout: neither slot ever processes |
| `ring-goes-false-mid-run` | 6 | ring flag true→false across blocks (ring cutoff) |
| `tail-span-silent-input` | 8 | 2 signal blocks + **6 blocks of SILENT input** while the ring flag stays true: the occupant's arithmetic tail must keep being rendered (all 8 blocks carry nonzero output) |
| `slot3-reload-mid-tail` | 8 | `loadFx()` on global3 at block 3 mid-tail: global3's history clears, global4's continues |
| `slot4-off-mid-tail` | 8 | `enqueueFXOff()` on global4 at block 3: its history is released, the stage no-ops |
| `panic-reset-mid-tail` | 8 | `state_reset` before block 4: BOTH instances clear, ring memory drops |
| `saturating-full-scale` | 4 | near-full-scale input through a high-gain occupant: the `sat32` audio-output saturation path |
| `random-control-stream` | 12 | bypass mode, disable mask, occupancy, reload pulses and the ring flag all randomized per block |

**Result: 18/18 exact, 0 mismatches, 7,680 output samples + 120 per-instance
checkpoints compared.** Full record: `rtl-exactness.json`
(`status: "PASS"`).

The comparator refuses to report PASS against a stale frozen model:
`--assert-model-revision <hex>` exits 2 with `status: "REFUSED"` when the
pinned revision does not match the live model file (§3, NC-E leg 2 invokes
exactly that path).

## 3. Negative controls (all 5 required; `tools/rf_global34_negative_controls.py`)

Every control reports per-leg status; a leg that could not run would be
recorded `NOT_RUN` and never counted as a demonstrated failure. In this
environment **0 legs were NOT_RUN** (iverilog present).

| Control | Targets | Legs | Verdict |
|---|---|---|---|
| **NC-A** generic substitute (pass-through + fixed gain in global4) | per-instance-state faithfulness / coverage eligibility | output bit-exactness (4/4 blocks differ); per-instance state (substitute keeps no history) | **CONTROL-OK** — labeled `ADAPTED`, `counts_toward_original_preset_coverage: false` |
| **NC-B** dropped tail (2 of 8 declared blocks rendered) | declared tail-span coverage | dropped region demonstrably carries audio (6/6 dropped blocks nonzero, Σ\|x\| = 2,174,983); coverage check fails; final per-instance checkpoint differs | **CONTROL-OK** |
| **NC-C** wrong order (global3/global4 permutation) | order-sensitive equality | model, saturating pair (380/384 samples differ, max Δ = 159,567,573); model, purely linear pair (79/512 differ, max Δ = 1 — see caveat); **live RTL mutant** `-DNC_SWAP_ORDER` (65 mismatches incl. all 6 checkpoints, of 384 samples / 6 checkpoints) | **CONTROL-OK** |
| **NC-D** shared state (both slots pooled into one history) | dual-instance independence | model pooled mutant, distinct occupants (6/6 blocks differ; pooled checkpoint halves become identical); model pooled mutant, **SAME-class occupants** (6/6 blocks differ); **live RTL mutant** `-DNC_SHARED_STATE` (205 mismatches / 384 samples); **live RTL mutant on the same-class case** (251 mismatches / 384 samples) | **CONTROL-OK** |
| **NC-E** stale stub (frozen-revision pin) | stale-harness refusal | `revision_pin_ok()` rejects a mutated pin; the real comparator invoked with a stale pin exits 2 with `status: "REFUSED"` | **CONTROL-OK** |

**5/5 CONTROL-OK, 15/15 legs** (a control that passes its target check would
be a broken control, per issue #62's own framing). Full record:
`negative-controls/negative-controls.json` (`status: "PASS"`), transcript in
`negative-controls/negative-controls.txt`. The live RTL mutants are
`rtl/effects/rf-rf-global34/rf_global34_mutants.sv`, compiled INSTEAD of the
real core and driven through the production testbench; compiled with no
defect selected the file refuses to simulate (`$fatal`), so it cannot
silently become a passing "control".

**Why NC-D is run twice.** The issue's shared-state control is about the
per-instance-state rule, and the real corpus contains the hardest case for
it: `String Contrabass.fxp` hosts Airwindows *Galactic* (sub-algorithm 49)
in **both** global3 and global4. Identical arithmetic in both slots is
exactly where a pooled-state implementation is most likely to slip through,
so both the model leg and the live RTL leg are repeated on the
`same-class-dual-occupants` case. Both still fail as required (251 mismatches
in RTL), and the correctly-isolated rack's two histories remain distinct
(`rtl-exactness.json`, `same-class-dual-occupants.dual_instance.final_histories_differ`).

**Honest caveats on NC-C (recorded, not hidden).**
1. Two LTI biquads in series *commute* in exact arithmetic, so permuting
   this leaf's synthetic linear occupants is detectable only through
   fixed-point rounding — 79 of 512 samples differ, by 1 LSB. Integer-exact
   equality (this leaf's actual acceptance check) does flag it, and with an
   intermediate stage that saturates the same permutation diverges grossly
   (max Δ ≈ 1.6e8). The engine's real global occupants are not LTI, so real
   slot permutations are far more visible; but the *strength* of this leaf's
   order control is bounded by its synthetic occupant, and that bound is
   stated here rather than implied away.
2. The issue words this control as "two same-class slots swapped". Permuting
   two slots whose occupant **content** is byte-identical is the identity
   map, so it is unobservable at the bus by construction — recorded in the
   control's `recorded_bound` field and verified there. The control
   therefore uses two same-role slots with *different* occupant content,
   which is the only form in which the check can have force.

Neither caveat affects the RTL-vs-model exactness claim.

## 4. Carrier routing/scheduling metadata (oracle-independent, zero-drift)

`tools/extract_rf_global34_inputs.py` re-verifies the census blob sha1
(`corpus/census-v0.1/results/per-preset.csv`), cross-checks
`corpus/normalized/graphs.jsonl` (already surgepy-derived and committed;
SXT-011), re-derives this leaf's slot indices from the corpus role table
itself, and **asserts zero drift between those two independent artifacts**
on every field both carry (blob sha1, stored revision, scene mode,
`fx_bypass`, `fx_disable`, non-off FX slot count, non-off FX type set). Any
disagreement is a refusal, not a silently preferred source
(`tests/test_sxt028j.py::test_extraction_refuses_injected_drift` injects
census drift, a blob-sha mismatch and a corrupted slot-index table, and
requires a refusal for each).

| Preset | Source | global3 | global4 | `fx_bypass` | `fx_disable` | Upstream global1/2 active | Dual-instance? |
|---|---|---|---|---|---|---|---|
| `Exquis MPE/Basses/Jigsaw.fxp` | issue-named | Conditioner (on) | Off | All FX | 0 | 2 | no |
| `Exquis MPE/Keys/Pixel.fxp` | issue-named | Conditioner (on) | Off | All FX | 0 | 2 | no |
| `Exquis MPE/Pads/Lazy.fxp` | issue-named | Conditioner (on) | Off | All FX | 0 | 2 | no |
| `John Valentine/Strings/String Contrabass.fxp` | added (shape) | Airwindows *Galactic* (on) | Airwindows *Galactic* (on) | All FX | 0 | 2 | **yes, same class** |
| `John Valentine/Winds/Bassoon.fxp` | added (shape) | Reverb 2 (on, **disabled**) | Airwindows (on, **disabled**) | All FX | **49152** (bits 14\|15) | 2 | **yes, both disabled** |

5/5 census blob + graphs cross-checks PASS, drift count 0, 0 refusals
(`artifacts/extract-refusals.txt` empty). The two added carriers are
recorded as additions (`carrier_source`), never presented as issue-named
carriers, and they exist precisely because the issue's own three do not
reach the dual-instance shape (§0c). `Bassoon.fxp` is the real-corpus
instance of this leaf's own per-slot disable gate — both of *this leaf's*
bits, and no others, set in one patch. Every carrier's stored per-slot
`return_level` is recorded but explicitly **not consumed** by the global
path (`return_level_consumed_by_global_path: false`) — return/send-level
semantics belong to the send-form (`rf-send*`) leaves.

Per-slot algorithm parameter values are NOT extracted (§0a — oracle
unavailable); each record carries `oracle_extraction.ok: false` with the
reason.

## 5. External-memory traffic

`artifacts/state-cost.json`, **derived** from the frozen model's declared
word widths (`tools/rf_global34_state_cost.py`) rather than hand-counted,
and pinned to `model_revision()` so it cannot go stale silently:

- This leaf's own contribution is **0 external-memory words/sample** and 0
  external writable words. Its synthetic occupant kernel is register-only;
  the frozen model's per-slot `ext_reads`/`ext_writes` counters stay at 0
  (asserted by `tests/test_sxt028j.py`).
- On-chip small state, on the same accounting the landed sibling routing
  leaves used (histories + occupancy + routing-control bits): **661 bits**
  (2 × 321 per-instance + 19 shared) — identical to `rf-rf-global2`'s 661
  and adjacent to `rf-rf-bins12`'s 663, as expected for the same routing
  form on two more slots. Counting the per-slot coefficient configuration
  registers and the block FSM as well gives **993 bits (125 bytes)**.
- The AGGREGATE estimate for a concrete preset also depends on whichever
  algorithm leaf's occupant actually lands in global3/global4 (Conditioner
  for the three issue-named carriers, Airwindows for `String Contrabass`,
  Reverb 2 + Airwindows for `Bassoon`), which is that leaf's own SXT-015/016
  accounting, not invented here — **`[PENDING-SXT-016]`** per the issue text.
- Long delay/reverb-class buffers belong in external WRITABLE memory; flash
  is not writable delay memory (AGENTS.md) — not applicable to this leaf's
  own register-only contribution.

## 6. Coverage (reported separately from agreement)

`artifacts/corpus-occupancy.json` inventories which of the 3,561 committed
corpus presets exercise this routing form's shapes. **Coverage accounting
only — not a support claim and not an agreement number.**

| Shape | Presets |
|---|---|
| `global3` occupied | 209 |
| `global4` occupied | 57 |
| both occupied (the dual-instance shape) | 36 |
| both occupied with the SAME FX class | 2 |
| `fx_disable` bit 14 set | 30 |
| `fx_disable` bit 15 set | 2 |
| both bits 14 and 15 set | 2 |
| non-`All FX` `fx_bypass` with a global3/4 occupant | **0** |

The last row is why §0b's bypass-partition contract cannot be discriminated
by any committed corpus carrier: no preset in the corpus combines a
non-default `fx_bypass` with an occupied extended-rack slot.

### Newly enabled presets

**0.** This record establishes no preset-support claim (§0a); the issue's own
`newly_enabled` accounting
(`reports/sxt-028/leaves/SXT-028j/newly-enabled.json`, FX-scope-only and
explicitly "NOT a support claim") is unaffected by this leaf landing. This
leaf's coverage contribution to the FX-routing axis is the global3/global4
extended-rack form; its agreement contribution is exactly the RTL↔model
exactness claim in §2 and nothing else.

## 7. Stop/escalate status

The issue's stop condition ("if the effect cannot be bounded in state/cost
under the shared instance schedule, record the finding and route to
SXT-017") was **not** triggered: this form's state is bounded and small
(§5), with no external-memory requirement of its own. Three items are routed
onward rather than closed here: the oracle-dependent reference legs (§0a,
blocked on an oracle build), the two declared-contract re-verification items
(§0b, bypass partition and FX-off queue timing), and the observation that
the issue's named carriers do not reach the dual-instance shape (§0c,
resolved here by adding two verified corpus carriers rather than by
weakening the acceptance item). The [PROPOSED] reference budgets remain
unfrozen, gated on SXT-017 (#12).

## Reproduce

```sh
python3 tools/extract_rf_global34_inputs.py
python3 tools/rf_global34_oracle_status.py
python3 tools/rf_global34_state_cost.py
python3 tools/compare_rtl_model_rf_global34.py --out reports/SXT-028j/rtl-exactness.json
python3 tools/rf_global34_negative_controls.py
python3 -m pytest tests/test_sxt028j.py -q
```
