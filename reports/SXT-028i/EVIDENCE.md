# SXT-028i evidence record — routing form: Scene-A insert FX bus, slots 3-4 (ains3 → ains4, extended rack half): frozen model, exact RTL, per-instance state + lifecycle, oracle-dependent legs BLOCKED (named compute gap)

Branch: `feature/issue-61` · Issue: #61 (SXT-028i) · Parent: #21 (SXT-028) ·
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
concrete Surge FX algorithm — see `model/effects/rf-rf-ains34/README.md`
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
  model itself; RTL-vs-model exactness (18 cases, §2); all 5 required negative
  controls, 14 legs, 0 NOT_RUN, 3 of them live RTL mutants (§3); the five
  B4-scope carrier presets' routing/scheduling metadata — slot occupancy, FX
  type, `fx_bypass`, `fx_disable`, scene mode, stored `return_level` —
  re-derived from the ALREADY-committed, ALREADY-surgepy-derived
  `corpus/census-v0.1` and `corpus/normalized/graphs.jsonl` (SXT-011 outputs),
  with **zero drift asserted between those two independent artifacts** (§4).
- **What is BLOCKED**: any per-slot algorithm-parameter extraction, the
  engine-side per-scene drift determinism gate, any wet-audio reference
  render, and therefore any model-vs-pinned-engine reference-agreement number
  for this leaf's fixtures (`tools/extract_rf_ains34_inputs.py`'s
  `oracle_extraction.ok` is `false` for all five carriers, recorded verbatim
  in `model/effects/fx_inputs/rf-rf-ains34-*.json`, never fabricated).
- **Reference budgets** [PROPOSED, not frozen] are therefore **NOT_RUN** for
  this leaf — not PASS and not FAIL. Freeze in any case is gated on SXT-017
  (#12) per the issue's own Acceptance section.

### 0b. Two structural facts are declared contracts, not verified reads

The same missing oracle checkout means the pinned `process()` source text
could not be re-read while writing this leaf. Consequences, stated exactly:

- **Re-derived in-repo (verified here)**: the slot indices
  `fxslot_ains3 = 8`, `fxslot_ains4 = 9`, each slot's `fx_disable` bit being
  its own slot index, and the surrounding role table (`ains1/ains2 = 0/1`,
  `bins1/bins2 = 2/3`, `global1/global2 = 6/7`) — every record of
  `corpus/normalized/graphs.jsonl` and `tools/export_normalized_graphs.py`'s
  `FX_ROLES` carry the pinned engine's slot order by patch `fx[]` index.
  Asserted by
  `tests/test_sxt028i.py::test_slot_indices_agree_with_the_committed_corpus_role_table`.
- **Declared contract #1 (NOT re-read from the pinned source here)**: the
  insert stage's bypass-mode set — it runs in `fxb_all_fx`, `fxb_no_sends`
  and `fxb_scene_fx_only`, and is skipped only in `fxb_no_fx`. This is the
  same insert-stage partition the landed sibling insert leaf
  `model/effects/rf-rf-bins12/` declared for scene B's half of the same
  `process()` block, and the complement — under the same enum — of the GLOBAL
  set (`all_fx`, `no_sends`) pinned by the landed sibling leaf
  `model/effects/rf-rf-global2/`. **Consistency with a sibling leaf's
  declaration is not verification**: sibling evidence never transfers
  (AGENTS.md).
- **Declared contract #2 (NOT re-read from the pinned source here)**: that
  the scene-A chain order is `ains1 → ains2 → ains3 → ains4`, i.e. the
  extended half runs *after* the base half and `ains3` runs before `ains4`
  within it. Only the **intra-pair** order is an axis of this leaf's own
  acceptance (NC-C attacks exactly that permutation); the base-vs-extended
  composition order is out of this leaf's scope — the base half is a sibling
  `rf-ains12`-class leaf's scope, and this leaf takes the bus and ring flag
  arriving at `ains3` as per-block stimulus (`extended_half_position` in each
  carrier record shows whether the base half is occupied, without modeling
  it).
- **Re-verification item** (both contracts): re-read the `process()` insert
  block against the pin the first time an oracle checkout is available, and
  correct the frozen model + RTL together if either differs. Nothing else in
  this leaf depends on them (contract #1 is one comparison; contract #2 fixes
  only what the per-block stimulus means, not the arithmetic) — the schedule,
  lifecycle and per-instance-state claims are independent of both.

### 0c. The issue-named carriers do not exercise this leaf's dual-instance shape

The issue's Fixtures plan names three carriers — `Jigsaw.fxp`,
`Resurrection.fxp`, `Pixel.fxp`. **All three occupy exactly one** of
`ains3`/`ains4` (§4), so none of them exercises the concurrent
two-instance shape or the routing-level disable gate this leaf claims. Rather
than assert the dual-instance case on a preset that does not contain it, two
further carriers were added **from this leaf's own B4-scope candidate list**
(`reports/sxt-028/leaves/SXT-028i/newly-enabled.json`, sha-verified — the
extractor REFUSES any preset outside that list, see
`tests/test_sxt028i.py::test_extraction_refuses_a_preset_outside_this_leafs_b4_scope`):
`Sand Storm.fxp` (both slots occupied, two different FX classes) and
`Brass Ensemble.fxp` (both slots occupied with `fx_disable = 256`, i.e. bit 8
= `ains3` disabled). The three named carriers are retained unchanged. This is
an addition to the fixtures plan, not a substitution, and it is recorded here
rather than left implicit.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (18 cases, 7,680 output samples + 120 checkpoints, 0 mismatches) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (oracle unavailable; §0a) | — |
| Negative controls live | **5/5 CONTROL-OK** (14 legs, 0 NOT_RUN; 3 are live RTL mutants) | `negative-controls/negative-controls.json` |
| Per-instance state (dual-slot) | **PASS** (model-level NC-D + live RTL shared-state mutant fails + RTL cases with both slots occupied) | `negative-controls.json`, `rtl-exactness.json` |
| Instance lifecycle (patch change mid-tail, slot off, panic/reset) | **PASS** (3 dedicated RTL cases + model tests) | `rtl-exactness.json` §2, `tests/test_sxt028i.py` |
| Declared tail span rendered | **PASS** (6 silent-input blocks, all carrying nonzero audio) | `rtl-exactness.json` (`tail-span-silent-input`) |
| Dropped-tail render | **FAILS the tail check, as required** (model truncation + a live RTL tail-killing mutant) | `negative-controls.json` NC-B |
| `fx_disable` bit layout at the extended-rack positions 8/9 | **PASS** (per-bit RTL cases + an all-other-bits-set control case) | `rtl-exactness.json`, `tests/test_sxt028i.py` |
| Carrier routing/scheduling metadata | **PASS** (5/5, census+graphs cross-checked, drift 0, B4-scope gate enforced) | `model/effects/fx_inputs/rf-rf-ains34-*.json` |
| Complete-wet preset renders | **NOT_RUN** (oracle unavailable) | §0a |
| External-memory traffic | **PASS** (this leaf's own contribution: 0 words/sample; aggregate `[PENDING-SXT-016]`) | `artifacts/state-cost.json` |
| Newly-enabled presets | **0** (no support claim follows from this record) | §6 |
| Musical quality / listening | **NOT_RUN** (no listening record; #9 remains BLOCKED-on-human) | — |

## 1. Frozen model

`model/effects/rf-rf-ains34/rf_ains34_model.py` + `README.md`. Models the
EXTENDED half of scene A's insert schedule: the control-rate
instance-lifecycle pass (runs in every bypass mode, as the engine's
load/unload path does), the `fx_bypass` gate (skip only in `no_fx`), the
`fx_disable` per-slot bitmask gate (engine bit layout, **bits 8/9**), and the
in-place SERIES chaining of `process_ringout` across two
`InsertSlotInstance` objects (slot3/ains3, slot4/ains4), each owning one
independent `BiquadInstance` (TDF2, Q3.29 coefficients, 80-bit accumulator).
`model_revision()` pins the frozen file's sha256 for the stale-harness control
(§3, NC-E) and is echoed by the RTL comparator (`rtl-exactness.json`).

Word formats (frozen): scene-bus audio **Q10.21 s32**, coefficients **Q3.29
s32**, TDF2 accumulator **80-bit signed**; exact products, round-half-up,
saturating; no floating point at audio run time. Identical in family to the
two landed routing leaves so the three forms are directly comparable, in a
self-contained file so neither can change the other's frozen behavior.

Lifecycle (frozen, identical in model and RTL): slot off → that instance
released; occupancy rising or a `reload` pulse → FRESH instance for **that
slot only** (its registers cleared, the sibling's history and the scene ring
flag untouched); occupancy steady without reload → coefficients adopted with
state kept; `panic_reset()` / `state_reset` → both instances cleared and the
ring memory dropped, patch still loaded.

Boundary: the audio and ring flag entering `ains3` come from the ains1/ains2
base half, which this leaf does not model (§0b, contract #2); they are
per-block stimulus.

## 2. RTL-vs-model exactness

`rtl/effects/rf-rf-ains34/{rf_ains34_core.sv, tb_rf_ains34.sv}`, compared via
`tools/compare_rtl_model_rf_ains34.py` (iverilog 13.0; INTEGER EQUALITY of
every output sample and every per-instance checkpoint — both slots' TDF2
registers plus the scene ring flag). The single harness is both the
dual-instance bench (each checkpoint line dumps ains3's and ains4's registers
separately) and the negative-control bench (§3 drives the mutants through the
same stimulus path).

| Case | Blocks | Exercises |
|---|---|---|
| `both-slots-all-fx` | 6 | baseline: both slots occupied, `fx_bypass = ALL_FX` |
| `both-slots-no-sends` | 6 | `fx_bypass = NO_SENDS` (insert stage still runs) |
| `both-slots-scene-fx-only` | 6 | `fx_bypass = SCENE_FX_ONLY` — **insert-specific**: this stage RUNS where the global bus is skipped |
| `bypass-no-fx-skips-block` | 6 | `fx_bypass = NO_FX`: bus and ring flag pass through, no state advanced |
| `ains3-disabled-bit8` | 6 | `fx_disable` bit **8** set: ains3 skipped, ains4 still runs — the real `Brass Ensemble.fxp` shape (`fx_disable = 256`) |
| `ains4-disabled-bit9` | 6 | `fx_disable` bit **9** set: ains4 skipped, ains3 still runs |
| `both-disabled-bits8and9` | 6 | both extended-half bits set while both slots are occupied: pure pass-through (the `Brassy Pad.fxp` / `Eww Gross.fxp` shape) |
| `other-slot-disable-bits-do-not-gate` | 6 | **bit-layout control**: all 14 OTHER slot bits set at once must leave this bus completely ungated |
| `ains4-unoccupied-ains3-only` | 6 | single-instance shape (matches `Pixel.fxp`) |
| `ains3-unoccupied-ains4-only` | 6 | the complementary single-instance shape (matches `Jigsaw.fxp` / `Resurrection.fxp`) |
| `scene-not-live-passthrough` | 6 | `sc_in = false` throughout: neither slot ever processes |
| `scene-live-goes-false-mid-run` | 6 | scene ring flag true→false across blocks (ring cutoff) |
| `tail-span-silent-input` | 8 | 2 signal blocks + **6 blocks of SILENT input** while the scene stays live: the occupant's arithmetic tail must keep being rendered (all 8 blocks carry nonzero output; tail-block Σ\|x\| decays 1,183,900 → 12,522) |
| `slot3-reload-mid-tail` | 8 | `loadFx()` on ains3 at block 3 mid-tail: ains3's registers go to 0 while **ains4's do not** (109, 243 at that checkpoint) — block 3's remaining 24,026 of output energy comes from ains4's surviving history alone, which is the per-instance-isolation behavior; blocks 4-7 are then silent |
| `slot4-off-mid-tail` | 8 | `enqueueFXOff()` on ains4 at block 3: its history is released, the stage no-ops, and ains3's own tail keeps being rendered through block 7 (8/8 blocks nonzero) |
| `panic-reset-mid-tail` | 8 | `state_reset` before block 4: BOTH instances clear, ring memory drops — blocks 0-3 ring, blocks 4-7 are silent |
| `saturating-full-scale` | 4 | near-full-scale input through a high-gain occupant: the `sat32` audio-output saturation path (141/256 samples saturate) |
| `random-control-stream` | 12 | bypass mode, disable mask (including the all-other-bits mask), occupancy, reload pulses and the scene-live flag all randomized per block |

**Result: 18/18 exact, 0 mismatches, 7,680 output samples + 120 per-instance
checkpoints compared.** Full record: `rtl-exactness.json` (`status: "PASS"`).

The comparator refuses to report PASS against a stale frozen model:
`--assert-model-revision <hex>` exits 2 with `status: "REFUSED"` when the
pinned revision does not match the live model file (§3, NC-E leg 2 invokes
exactly that path).

**Anti-vacuity guard (agreement is not enough on its own).** Integer equality
between two silently-zero traces would also read "exact", so every case entry
in `rtl-exactness.json` records `nonzero_output_blocks`, and
`tests/test_sxt028i.py::test_rtl_exactness_record_is_not_vacuous` asserts the
expected value **per case**: 16 of the 18 cases carry audio in every block,
and the two lifecycle cases (`slot3-reload-mid-tail`, `panic-reset-mid-tail`)
carry audio in exactly 4 of 8 — their post-event silence *is* the acceptance
behavior and is asserted positively rather than tolerated. A silent-stub
model/RTL pair cannot satisfy this record.

## 3. Negative controls (all 5 required; `tools/rf_ains34_negative_controls.py`)

Every control reports per-leg status; a leg that could not run would be
recorded `NOT_RUN` and never counted as a demonstrated failure. In this
environment **0 legs were NOT_RUN** (iverilog present).

| Control | Targets | Legs | Verdict |
|---|---|---|---|
| **NC-A** generic substitute (pass-through + fixed gain in ains4) | per-instance-state faithfulness / coverage eligibility | output bit-exactness (4/4 blocks differ); per-instance state (substitute keeps no history) | **CONTROL-OK** — labeled `ADAPTED`, `counts_toward_original_preset_coverage: false` |
| **NC-B** dropped tail (2 of 8 declared blocks rendered; **plus a live RTL mutant**) | declared tail-span coverage | dropped region demonstrably carries audio (6/6 dropped blocks nonzero, Σ\|x\| = 2,132,555); coverage check fails; final per-instance checkpoint differs; **live RTL mutant** `-DNC_TAIL_KILL` (390 mismatch records, incl. 6 checkpoints, of 512 samples / 8 checkpoints) | **CONTROL-OK** |
| **NC-C** wrong order (ains3/ains4 permutation) | order-sensitive equality | model, saturating pair (380/384 samples differ, max Δ = 159,567,573); model, purely linear pair (101/512 differ, max Δ = 1 — see caveat); **live RTL mutant** `-DNC_SWAP_ORDER` (61 mismatch records, incl. 6 checkpoints, of 384 samples / 6 checkpoints) | **CONTROL-OK** |
| **NC-D** shared state (both slots pooled into one history) | dual-instance independence | model pooled mutant (6/6 blocks differ, pooled checkpoint halves become identical); **live RTL mutant** `-DNC_SHARED_STATE` (209 mismatch records, incl. 6 checkpoints, of 384 samples / 6 checkpoints) | **CONTROL-OK** |
| **NC-E** stale stub (frozen-revision pin) | stale-harness refusal | `revision_pin_ok()` rejects a mutated pin; the real comparator invoked with a stale pin exits 2 with `status: "REFUSED"` | **CONTROL-OK** |

**5/5 CONTROL-OK** (a control that passes its target check would be a broken
control, per issue #61's own framing). Full record:
`negative-controls/negative-controls.json` (`status: "PASS"`), transcript in
`negative-controls/negative-controls.txt`. The three live RTL mutants are
`rtl/effects/rf-rf-ains34/rf_ains34_mutants.sv`, compiled INSTEAD of the real
core and driven through the production testbench; compiled with no defect
selected the file refuses to simulate (`$fatal`), so it cannot silently become
a passing "control".

**The tail case is load-bearing, and that is measured, not asserted.** The
`-DNC_TAIL_KILL` mutant skips the insert stage whenever the incoming block is
all-zero — a plausible "nothing to do on silence" optimisation that drops the
occupant's arithmetic tail and freezes its registers. Run against the
non-silent baseline case (`both-slots-all-fx`) it produces **0 mismatches of
384 samples**: the baseline case cannot see it at all. Run against
`tail-span-silent-input` it produces **390 mismatch records of 512 samples**.
That asymmetry is recorded in the control's own metrics
(`undetected_case_mismatches`) and asserted by
`tests/test_sxt028i.py::test_tail_control_has_a_live_rtl_leg_the_baseline_case_misses`,
so a future change that made the baseline catch it would flag this paragraph
as stale rather than silently invalidate it.

**Honest caveat on NC-C (recorded, not hidden).** Two LTI biquads in series
*commute* in exact arithmetic, so permuting this leaf's synthetic linear
occupants is detectable only through fixed-point rounding — 101 of 512 samples
differ, by 1 LSB. Integer-exact equality (this leaf's actual acceptance check)
does flag it, and with an intermediate stage that saturates the same
permutation diverges grossly (max Δ ≈ 1.6e8). The engine's real insert
occupants are not LTI, so real slot permutations are far more visible; but the
*strength* of this leaf's order control is bounded by its synthetic occupant,
and that bound is stated here rather than implied away. It does not affect the
RTL-vs-model exactness claim.

## 4. Carrier routing/scheduling metadata (oracle-independent, zero-drift)

`tools/extract_rf_ains34_inputs.py` re-verifies the census blob sha1
(`corpus/census-v0.1/results/per-preset.csv`), re-verifies that the carrier is
one of this leaf's own declared B4-scope candidates
(`reports/sxt-028/leaves/SXT-028i/newly-enabled.json`, sha included),
cross-checks `corpus/normalized/graphs.jsonl` (already surgepy-derived and
committed; SXT-011), and **asserts zero drift between those two independent
artifacts** on every field both carry (blob sha1, stored revision, scene mode,
`fx_bypass`, `fx_disable`, non-off FX slot count, non-off FX type set). Any
disagreement is a refusal, not a silently preferred source
(`tests/test_sxt028i.py::test_extraction_refuses_injected_drift` injects drift
and requires the refusal; a second test requires the refusal of a
perfectly-clean preset that is simply outside this leaf's B4 scope).

| Preset | ains3 | ains4 | `fx_bypass` | `fx_disable` | Scene mode | Dual-instance concurrent? | Carrier source |
|---|---|---|---|---|---|---|---|
| `Exquis MPE/Basses/Jigsaw.fxp` | Off | Phaser (on) | All FX | 0 | Single | no (single-instance) | named by issue |
| `Exquis MPE/Basses/Resurrection.fxp` | Off | EQ (on) | All FX | 0 | Single | no (single-instance) | named by issue |
| `Exquis MPE/Keys/Pixel.fxp` | EQ (on) | Off | All FX | 0 | Single | no (single-instance) | named by issue |
| `Exquis MPE/Keys/Sand Storm.fxp` | Reverb 1 (on) | EQ (on) | All FX | 0 | Single | **yes** | added (§0c) |
| `Lopyt/Brass/Brass Ensemble.fxp` | Reverb 2 (on, **disabled** bit 8) | EQ (on) | All FX | 256 | Single | **yes** (occupancy) | added (§0c) |

5/5 census blob + B4-scope + graphs cross-checks PASS, drift count 0, 0
refusals (`artifacts/extract-refusals.txt` empty). `Sand Storm.fxp` genuinely
exercises the two-concurrent-insert-instance shape this leaf claims — and does
it with two *different* FX classes in the two slots, which is exactly the
"shared arithmetic, independent per-instance state" case.
`Brass Ensemble.fxp` is the real-preset instance of the routing-level disable
gate (both slots loaded, `ains3` disabled by bit 8 — RTL case
`ains3-disabled-bit8`). The three issue-named carriers exercise the
complementary single-occupied-slot shapes (RTL cases
`ains4-unoccupied-ains3-only` / `ains3-unoccupied-ains4-only`).

All five are reachable without qualification: scene A is instantiated in every
scene mode (`scene_context.scene_a_instantiated`), unlike the sibling scene-B
leaf, whose slots are unreachable in a Single-scene patch.

**Coverage context (reported separately from agreement, and NOT a support
claim).** Of this leaf's 55 declared B4-scope candidate presets, 18 occupy
both `ains3` and `ains4` concurrently, 23 occupy `ains3` only, 14 occupy
`ains4` only, and 16 have at least one extended-half `fx_disable` bit set.
Across the whole normalized corpus (3,561 presets), 128 occupy both, 104
`ains3` only and 45 `ains4` only. These are inventory counts derived from
committed corpus artifacts; they establish no support claim for any preset
(AGENTS.md; the census is an inventory aid).

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
leaf's occupant actually lands in ains3/ains4 (Reverb 1 + EQ for
`Sand Storm.fxp`, Reverb 2 + EQ for `Brass Ensemble.fxp`, Phaser for
`Jigsaw.fxp`), which is that leaf's own SXT-015/016 accounting, not invented
here — **`[PENDING-SXT-016]`** per the issue text. Long delay/reverb-class
buffers belong in external WRITABLE memory; flash is not writable delay
memory (AGENTS.md) — not applicable to this leaf's own register-only
contribution.

The figure is numerically identical to the sibling `rf-rf-bins12` leaf's
because the two insert halves are structurally identical; it was re-derived
from THIS leaf's own frozen model and RTL, not transferred from that leaf
(sibling evidence never transfers — AGENTS.md).

## 6. Newly enabled presets

**0.** This record establishes no preset-support claim (§0a); the issue's own
`newly_enabled` accounting
(`reports/sxt-028/leaves/SXT-028i/newly-enabled.json`, FX-scope-only and
explicitly "NOT a support claim") is unaffected by this leaf landing.
Coverage remains reported separately from agreement: this leaf's coverage
contribution to the FX-routing axis is the ains3/ains4 extended-half insert
form; its agreement contribution is exactly the RTL↔model exactness claim in
§2 and nothing else.

## 7. Stop/escalate status

The issue's stop condition ("if the effect cannot be bounded in state/cost
under the shared instance schedule, record the finding and route to SXT-017")
was **not** triggered: this form's state is bounded and small (§5), with no
external-memory requirement of its own. Three items are routed onward rather
than closed here: the oracle-dependent reference legs (§0a, blocked on an
oracle build), the two bypass-partition / chain-order re-verification items
(§0b), and the base half of this same scene-A chain (`ains1`/`ains2`), which a
sibling `rf-ains12`-class leaf owns. The [PROPOSED] reference budgets remain
unfrozen, gated on SXT-017 (#12).

## Reproduce

```sh
python3 tools/extract_rf_ains34_inputs.py
python3 tools/compare_rtl_model_rf_ains34.py --out reports/SXT-028i/rtl-exactness.json
python3 tools/rf_ains34_negative_controls.py
python3 -m pytest tests/test_sxt028i.py -q
```
