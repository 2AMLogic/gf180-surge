# SXT-028j evidence record — routing form: Global FX slots 3-4 (global3 → global4, extended rack half): frozen model, exact RTL, per-instance state + lifecycle, oracle legs run on the prebuilt oracle (original carriers REFUSED as source-nonrepeatable; agreement NOT_RUN)

Branch: `feature/issue-62` · Issue: #62 (SXT-028j) · Parent: #21 (SXT-028) ·
Epic: #3

Engine (external, GPL-3.0-or-later; pinned; exercised by the #150 oracle
legs in §0a/§0b, read-only):
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

### 0a. Oracle-dependent legs — RAN on the prebuilt pinned oracle (issue #150); original-carrier agreement NOT_RUN

Re-run on 2026-10-18 on a linux-x86_64 dispatch worker with the pinned
prebuilt oracle (`oracle/fetch-and-build.sh --prebuilt`, per-user install,
provenance mode `manifest_prebuilt_artifact`, engine
`1.4.HEAD.58914e59c`, pin `58914e59…`). `artifacts/oracle-status.json` now
reads `oracle_status: "AVAILABLE"`, every leg `RUNNABLE` with `ran: true`
(`tools/rf_global34_oracle_status.py`, which now loads surgepy through the
harness's sanctioned loader instead of a bare `import`). What each leg
actually produced:

- **extract-slot-params — RAN, 5/5 carriers.**
  `tools/extract_rf_global34_inputs.py` read global3/global4 parameter
  vectors from the native post-`loadPatch` state, cross-checked every value,
  the fx-type vector, `fx_bypass`/`fx_disable` and `return_level` against
  `corpus/normalized/graphs.jsonl` (0 disagreements), and ran the shared
  engine-side per-scene drift gate (**PASS**, drift 0.0 in every voicing
  scene, all 5). Records: `model/effects/fx_inputs/rf-rf-global34-*.json`
  (`oracle_extraction.live`); every oracle-free field is byte-for-byte what it
  was. This is an extraction/eligibility result, not agreement.
- **render — RAN; every original carrier REFUSED.** All 5 carriers x both
  sequences (`seq-notes-coverage-v1`, `seq-poly-8-v1`) = **10/10 pairs fail
  the exact 3x bit-identity gate** (3 distinct buffers each). The **first
  diverging bus is the ALL-OFF dry bus in all 10**, i.e. the voice path,
  upstream of every effect slot — so this is not a global3/global4 property
  and it is not the drift gate (which passed). Under
  `decision-records/0019-source-nondeterministic-carrier-policy.md` (policy
  #310) a source-nonrepeatable preset is **REFUSED as an original carrier**:
  the gate is not softened, nothing is seeded/conditioned/tolerance-compared,
  no carrier is silently substituted, and the five stay
  *unsupported-pending*. Per-bus sha256s: `model-vs-reference.json`
  `carrier_determinism_gate`; transcript: `artifacts/render-refusals.txt`.
  Consequently **no original-carrier reference fixture was committed.**
- **model-render / reference-compare — original carriers: NOT_RUN
  (BLOCKED).** With no repeatable original carrier there is no wet reference
  to compare the model against. The affected dependency is blocked on a
  carrier drawn from the reproducibility census (#381); the budgets were not
  widened and not frozen (freeze stays gated on SXT-017, #12).
- **Diagnostic routing probe (NOT a carrier, no coverage).**
  `tools/render_rf_global34_reference.py` also renders a *diagnostic
  adaptation* — the repeatable factory voice `Basses/Sub 4.fxp` with
  global3 = Distortion and global4 = Delay set by override — under the same
  policies (fresh instance per bus, 3x bit-identical gate: **passes**), 12
  buses per sequence (`reports/SXT-028j/fixtures/diag-sub-4__*.json`;
  manifests with per-bus sha256 are committed, the WAVs are regenerable
  scratch). Per decision-record invariant 4 this is diagnostic/adapted input
  and never counts toward original-preset coverage. What it establishes
  (engine routing semantics; exact float-buffer equality between engine
  buses, both sequences):
  - `fx_bypass = No FX` ≡ the all-slots-off dry bus; `Scene FX only` ≡ the
    inserts-only bus (global stage and sends skipped); `No sends` runs the
    global stage (≠ the stage-off bus) and skips the sends (≡ sends-off bus).
  - The frozen model's stage-active prediction (driven by the engine's own
    stage-input bus) **agrees with the engine in all 4 configs x 2
    sequences**; two live negative controls (wrong bypass partition: Scene
    FX only runs the stage; bypass ignored) **disagree with the engine, as
    required** — a control that agreed would be broken.
  - Model-vs-engine *waveform* (max/rms/corr, tail gate) was **measured**
    against the [PROPOSED] budgets for completeness and **FAILS** them
    (mono max |Δ| 9.4e5 / 9.1e5 LSB, rms −16.4 / −13.8 dBFS, spectral corr
    0.52 / 0.68; tail gate FAIL). That is the expected consequence of the
    declared scope — the model's occupant is a synthetic biquad, not
    Distortion/Delay — so it is recorded with
    `agreement_claim: NO_VERDICT, reason: occupant_not_modeled`, not as
    fidelity evidence in either direction. Concrete-occupant agreement
    belongs to the algorithm leaves.
- **fx_disable gate (bits 14|15) — engine probe BLOCKED.** surgepy's
  `setParamVal` on the int `fx_disable` parameter reads back `-2147483648`
  for every value written, so the bits cannot be forced on the engine. The
  only carrier with them set natively (`Bassoon.fxp`) is source-nonrepeatable.
  The model's bits-14/15 gate therefore stays a declared contract here
  (engine bit layout re-derived from the corpus, §0b).
- **Reference budgets** [PROPOSED, not frozen] remain **NOT_RUN** for original
  carriers — not PASS and not FAIL.

### 0b. Two structural facts: re-verified against the pinned source (#150 items 2–3)

Source re-read at the pin
(`surge-synthesizer/surge@58914e59…`, `src/common/SurgeSynthesizer.cpp`,
fetched read-only for reading; nothing copied into this repository):

- **Contract #1 — CONFIRMED against the pin.** `process()` runs
  `processControl()` first, then the insert block (`fx_bypass != fxb_no_fx`),
  then the send block (`fx_bypass == fxb_all_fx`), then the global block:
  `if ((fx_bypass == fxb_all_fx) || (fx_bypass == fxb_no_sends))` iterates
  `{fxslot_global1..4}`, skipping a slot that is null or has its
  `fx_disable` bit set, chaining `process_ringout` in place. So the global
  stage runs in exactly `{ALL_FX, NO_SENDS}` and not in `{SCENE_FX_ONLY,
  NO_FX}`; the per-slot `fx_disable` gate is as modeled. This was inherited
  from `rf-rf-global2`, never re-read there; it is now read, and the
  diagnostic probe in §0a reproduces it on the running engine. The corpus
  still cannot discriminate it (0 of 3,561 presets).
- **Contract #2 — CONFIRMED against the pin.** `enqueueFXOff()` writes
  `fxsync[which].type = fxt_off`, clears its user data and sets
  `load_fx_needed`. `processControl()` (called at the top of `process()`,
  before any FX stage) calls `loadFx()` when `load_fx_needed`, which does
  `fx[s].reset()` for the slot. The queue therefore drains at the
  control-rate pass **preceding the block**, which is the model's and RTL's
  declared contract. Empirically, on the diagnostic probe: with the global4
  type written to Off before block 600 (both sequences), the engine output
  first departs from the unmodified render **at block 600** and from block
  600 on is bit-identical to the slot-off-from-start render. (The binding's
  type write and `enqueueFXOff()` both set `load_fx_needed` and drain at the
  same `processControl()` site; the test exercised the binding's write, the
  source read covers `enqueueFXOff()` itself.)
- **No correction was needed**, so the frozen model, the RTL and
  `rtl-exactness.json` are untouched (the model revision pin is unchanged;
  `tools/compare_rtl_model_rf_global34.py --assert-model-revision <stale>`
  still refuses, covered by the existing negative control).

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
| Model ↔ pinned engine vs [PROPOSED] budgets, original carriers | **NOT_RUN** (all 5 carriers REFUSED by the 3x gate; §0a) | `model-vs-reference.json` `carrier_determinism_gate` |
| Model ↔ engine routing agreement (diagnostic host, not a carrier) | **PASS** (4 configs x 2 sequences exact; 2 live controls fail as required) | `model-vs-reference.json` |
| Model ↔ engine waveform on the diagnostic host | **NO_VERDICT** (measured FAIL vs budgets; occupant not modeled, §0a) | `model-vs-reference.json` |
| Oracle probe / live extraction | **AVAILABLE**, every leg RUNNABLE and run; extraction 5/5, drift gate PASS | `artifacts/oracle-status.json`, `fx_inputs/*.json` |
| Declared contracts #1/#2 (§0b) | **CONFIRMED** against the pin (source read + diagnostic probe) | §0b |
| `fx_disable` bits 14\|15 on the engine | **BLOCKED** (binding cannot set the parameter) | §0a |
| Negative controls live | **5/5 CONTROL-OK** (15 legs, 0 NOT_RUN; 3 are live RTL mutants) | `negative-controls/negative-controls.json` |
| Per-instance state (dual-slot) | **PASS** (model NC-D + live RTL shared-state mutant fails, incl. the same-FX-class case) | `negative-controls.json`, `rtl-exactness.json` |
| Instance lifecycle (patch change mid-tail, slot off, panic/reset) | **PASS** (3 dedicated RTL cases + model tests) | `rtl-exactness.json` §2, `tests/test_sxt028j.py` |
| Declared tail span rendered | **PASS** (6 silent-input blocks, all carrying nonzero audio) | `rtl-exactness.json` (`tail-span-silent-input`) |
| Dropped-tail render | **FAILS the tail check, as required** | `negative-controls.json` NC-B |
| Seam with the landed global1→global2 segment | **PASS** (model-level 4-slot composition, 4 independent histories) | `tests/test_sxt028j.py::test_seam_composes_with_the_landed_global12_segment` |
| Carrier routing/scheduling metadata | **PASS** (5/5, census+graphs cross-checked, drift 0) | `model/effects/fx_inputs/rf-rf-global34-*.json` |
| Complete-wet preset renders / new reference fixtures (original carriers) | **REFUSED** (10/10 carrier x sequence pairs source-nonrepeatable; none committed) | §0a, `artifacts/render-refusals.txt` |
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

*FX-type comparison note (issue #154).* The census CSV names an FX through the
census parser's own static table (`FrequencyShifter`, `RingModulator`) while
the normalized graph uses the engine's live display name (`Freq Shift`,
`Ring Mod`). A name-vs-name comparison refuses on **spelling** for those
types. The cross-check therefore maps the graph's stored type **ids** through
the census's own committed `FX` table and compares in that one naming
authority (`tools/_census_graphs_common.py`, shared by all four routing-form
extractors) — a strictly *content*-level comparison, with no invented alias
list; the engine display names are recorded alongside as context
(`cross_check.engine_display_names_context`). None of this leaf's carriers
uses a divergent-spelling type, so **no verdict in the table below moved** —
the regenerated records differ from the previous ones only by the two added
context fields. `test_cross_check_compares_fx_type_content_not_spelling` pins
the divergent pairs as clean; `test_extraction_refuses_injected_drift` pins
that a genuinely different — or unmappable — FX type id still refuses.

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

Per-slot algorithm parameter values were extracted live in the #150 re-run
(§0a): each record's `oracle_extraction.live` carries the global3/global4
parameter vectors (cross-checked against `graphs.jsonl`) and the engine-side
drift gate. On a host without the oracle the same field records
`ok: false` with the reason, and the oracle-free fields above are unchanged.

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
(§5), with no external-memory requirement of its own. The #150 re-run
discharged the two declared-contract re-verification items (§0b, both
confirmed against the pin; no correction) and ran the oracle legs (§0a). What
remains routed onward: model-vs-engine agreement on an **original** carrier —
blocked because all five carriers are source-nonrepeatable (policy #310,
decision record 0019) and a replacement must come from the reproducibility
census (#381); the engine-side `fx_disable` bit probe (the binding cannot set
the parameter); and the observation that the issue's named carriers do not
reach the dual-instance shape (§0c). The [PROPOSED] reference budgets remain
unfrozen, gated on SXT-017 (#12); no budget was widened.

## Reproduce

```sh
# oracle legs (host with the pinned oracle; exports from
# `oracle/fetch-and-build.sh --prebuilt`; run under $ORACLE_PYTHON)
$ORACLE_PYTHON -I tools/extract_rf_global34_inputs.py
$ORACLE_PYTHON -I tools/render_rf_global34_reference.py
$ORACLE_PYTHON -I tools/rf_global34_oracle_status.py
python3 tools/rf_global34_state_cost.py
python3 tools/compare_rtl_model_rf_global34.py --out reports/SXT-028j/rtl-exactness.json
python3 tools/rf_global34_negative_controls.py
python3 -m pytest tests/test_sxt028j.py -q
```
