# SXT-028l evidence record — routing form: Send buses 3-4 (send3 / send4, extended rack half): frozen model, exact RTL, per-instance state + lifecycle, oracle-dependent legs NOT_RUN and the fixture freeze BLOCKED on the SXT-017 send-level data gap (#12)

Branch: `feature/issue-64` · Issue: #64 (SXT-028l) · Parent: #21 (SXT-028) ·
Epic: #3

Engine (external, GPL-3.0-or-later, pinned but not exercised by this leaf
beyond the census/graphs cross-check):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
(`oracle/manifest.json`). Structure authority:
`src/common/SurgeSynthesizer.cpp` `process()` send-FX block (`loadFx()`,
`enqueueFXOff()`, `reorderFx()`), `src/common/SurgeStorage.h`
`fxslot_positions` / `n_send_slots` / `fxb_*`,
`src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h`.

**Claim discipline.** This record advances exactly one claim: *the RTL
matches the frozen fixed-point routing/scheduling model exactly* (iverilog;
demonstrated in §2). It establishes **no** model-vs-pinned-engine
reference-agreement number, **no** preset-support claim, **no**
musical-quality claim (no human listening), and **no** FPGA/gf180mcu
synthesis, timing, area, or hardware-playback claim. The per-slot occupant
used to exercise the routing arithmetic is a synthetic TDF2 biquad, not any
concrete Surge FX algorithm — see `model/effects/rf-rf-send34/README.md`
"Form scope, not algorithm scope". No generic substitute is used under any
support claim; NC-A proves one is bit-exactly distinguishable from the
declared per-instance occupant and labels it ADAPTED.

**What is new in this leaf.** The four landed routing leaves (`rf-rf-global2`
#56, `rf-rf-bins12` #60, `rf-rf-ains34` #61, `rf-rf-global34` #62) all model a
**series** insert pair. A send bus is a different routing kind: two
**parallel** buses *formed from* the scene buses through per-scene send
levels and *mixed back into* the main bus through per-slot return levels.
Five facts follow that have no counterpart in the series forms, and each is
exercised in §2: the send stage runs in `fxb_all_fx` **only**; an unoccupied
or disabled send slot **contributes nothing** (it is not a pass-through); the
form carries a **gain plane** (3 words per bus); each bus has its **own**
`sendused` ring flag; and **both scenes** feed every bus (scene B only when
instantiated).

## 0. Named gaps (recorded, not worked around)

### 0a. Oracle-dependent legs — NOT_RUN; fixture freeze additionally BLOCKED on #12

The pinned Surge XT engine's `surgepy` Python binding requires a full
C++/JUCE build (`oracle/fetch-and-build.sh`); that build was not available in
the environment that produced this record (dispatch worker, no host-side
oracle checkout; `oracle/manifest.json`'s pinned build path is a macOS path).
The probe is **measured, not asserted** — `tools/rf_send34_oracle_status.py`
actually attempts the checkout lookup and the `import surgepy`, and writes
what it found to `artifacts/oracle-status.json` (`oracle_status:
"UNAVAILABLE"`, `surgepy_importable: false`, `engine_dir_present: false`).

- **What IS verified without the oracle** (this record, in full): the frozen
  model itself; RTL-vs-model exactness (20 cases, §2); all 5 required
  negative controls plus 1 additional send-form control, 19 legs, 0 NOT_RUN
  (§3); six corpus carriers' routing/scheduling metadata — slot occupancy, FX
  type, `fx_bypass`, `fx_disable`, scene mode / scene-B instantiation, base-half
  context, stored `return_level` — re-derived from the ALREADY-committed,
  ALREADY-surgepy-derived `corpus/census-v0.1` and
  `corpus/normalized/graphs.jsonl` (SXT-011 outputs), with **zero drift
  asserted between those two independent artifacts** (§4); and a corpus-wide
  occupancy scan for this routing form's shapes (§6, coverage only).
- **What is NOT_RUN**: this leaf's Fixtures plan calls for **new** reference
  fixtures (no SXT-014 ablation carrier exists for this routing form), so
  per-slot algorithm-parameter extraction, the original / per-slot-bypass /
  all-off-dry renders, the engine-side per-scene drift determinism gate, and
  therefore any model-vs-pinned-engine reference-agreement number are all
  **NOT_RUN**. Recorded per leg in `artifacts/oracle-status.json` and as a
  refusal transcript in `artifacts/render-refusals.txt`;
  `tools/extract_rf_send34_inputs.py`'s `oracle_extraction.ok` is `false` for
  all six carriers, written verbatim into
  `model/effects/fx_inputs/rf-rf-send34-*.json`, never fabricated.
- **What is BLOCKED (a second, independent gate)**: see §0b below — an
  available oracle would **not** by itself unblock this routing form's
  fixture freeze.
- **Reference budgets** [PROPOSED, not frozen] are therefore **NOT_RUN** for
  this leaf — not PASS and not FAIL. Freeze in any case is gated on SXT-017
  (#12) per the issue's own Acceptance section.

### 0b. The SXT-011 send-level data gap — BLOCKED on #12 (this leaf's own blocker)

The engine has four send buses, but a `.fxp` stores only **two** per-scene
send levels and the surgepy binding exposes only `send_level[0..1]`
(`corpus/normalized/README.md` "Send levels 3/4";
`corpus/normalized/schema.json` `scene.send`). Buses 3/4 therefore run at
**loader defaults** for every committed corpus preset. The issue's own body
flags this and routes it to SXT-017; #12's 2026-09-25 curation comment
absorbs it and states that #64 waits on that decision, not the reverse.

This leaf does not pre-empt the decision and does not invent a default:

- The gap is **re-verified mechanically**, not quoted:
  `artifacts/send-level-gap.json` scans all **3,561** presets / **7,122**
  scene records and finds every one carrying exactly **two** send levels
  (histogram `{"2": 7122}`), never four. If a future corpus ever carried
  four, `tools/extract_rf_send34_inputs.py::send_level_check` **REFUSES**
  rather than reinterpreting (live control:
  `tests/test_sxt028l.py::test_extraction_refuses_a_corpus_that_closes_the_gap`).
- Every carrier record carries `send_level_gap.send3_send4_levels_stored:
  null` with the reason and `blocking_issue: "#12"`. The two *exposed* levels
  (buses 1/2) are recorded as context only.
- In the frozen model and the RTL, the per-scene send gains for buses 3/4 are
  **control-plane stimulus**, never corpus-derived.
- `return_level` **is** stored and **is** exported (`graphs.jsonl` `fx[].rl`),
  and — unlike the insert/global forms — this routing form really consumes
  it. It is extracted per carrier, including the real-corpus return-muted
  shape (§4).
- `artifacts/oracle-status.json` records the send-level loader-default probe
  as **BLOCKED** (not NOT_RUN) and states both fixture-freeze gates
  explicitly: `oracle_build: UNAVAILABLE`, `sxt017_send_level_data_gap:
  BLOCKED (#12)`.

**The RTL-vs-frozen-model exactness claim (§2) does not depend on this gap
being closed**, because the gain words are control-plane inputs to both the
model and the RTL.

### 0c. Structural facts that are declared contracts, not fresh verified reads

No oracle checkout means the pinned `process()` source text could not be
re-read while writing this leaf. Consequences, stated exactly:

- **Re-derived in-repo (verified here)**: the slot indices
  `fxslot_send3 = 12`, `fxslot_send4 = 13` (and `send1/2 = 4/5`). Every one
  of the **3,561** records in `corpus/normalized/graphs.jsonl` carries the
  pinned engine's slot order by patch `fx[]` index, and
  `tests/test_sxt028l.py::test_slot_indices_agree_with_the_committed_corpus_role_table`
  checks **all** of them. The extractor re-checks the same table per carrier
  (`slot_index_check`) and REFUSES on disagreement.
- **Declared contract #1 — the send-stage routing itself** (bus formation
  from both scenes' `send_level`, in-place `process_ringout`, mix back
  through `return_level`, `fx_bypass == fxb_all_fx` only, per-slot
  `fx_disable & (1<<slot)`). Taken from the committed SXT-011 artifact
  `corpus/normalized/README.md` ("FX slot roles and processing order"),
  written against the pin and the authority for
  `corpus/normalized/schema.json`'s own role description. That is an in-repo
  re-derivation, **not** a fresh read of `process()`.
  Consistency note: the whole corpus contains **0** presets with a
  non-`All FX` `fx_bypass` and an occupied send3/send4
  (`artifacts/corpus-occupancy.json`), so no committed corpus carrier
  discriminates the bypass partition either way.
- **Declared contract #2 — the gain mapping** `gain = level**3`
  (`amp_to_linear` cubed), taken from the landed SXT-024 Reverb1 send path
  (`tools/compare_reverb_model.py` "send_gain = amp_to_linear(send_level)^3",
  `tools/run_reverb_rtl.py`, `tools/render_reverb_reference.py`,
  `reports/sxt-024/EVIDENCE.md`). Applied **at control rate only**
  (`gain_from_level()`); the audio path in both the model and the RTL
  consumes the resulting Q1.30 integer, so this contract sits **outside** the
  exactness claim.
- **Declared contract #3 — what happens when a bus runs but `sendused` is
  false**: the occupant passes the formed bus through untouched (no state
  advances) and the bus is still mixed back through its return gain. In the
  engine's own use `sendused` false means nothing was mixed *into* the bus,
  so this adds silence; the contract is pinned explicitly (RTL case
  `sendused-false-passthrough`) rather than left implicit.
- **Declared contract #4 — the occupant's ring-out policy**: this occupant
  reports ringing exactly while `sendused` is true. The identical
  simplification all four landed routing leaves declared; a tail-bearing
  occupant's own `process_ringout` return policy is algorithm-leaf scope.
- **Declared contract #5 — the engine-side queue-drain timing of
  `enqueueFXOff()`**. This leaf's lifecycle applies slot-off at the
  control-rate pass preceding a block. The model and the RTL match each other
  exactly on that contract (claim 1 unaffected); whether the engine's own
  queue drains at the same boundary is unverified here.
- **Re-verification item** (contracts #1 and #3–#5): re-read the `process()`
  send block and the FX-off queue against the pin the first time an oracle
  checkout is available, and correct the frozen model + RTL together if any
  differs. Contract #2 is re-verifiable independently of an oracle by
  re-reading the landed SXT-024 record.

### 0d. Two design choices that BOUND this leaf's controls

Stated here rather than implied away (full detail in §3):

1. Both accumulations in this form (the scene sum that forms a bus, the
   return mix into the main bus) use **one wide accumulator, one rounding,
   one saturation**, so they are **order-independent by construction**
   (verified: `test_scene_accumulation_is_order_independent_by_construction`,
   `test_return_mix_is_order_independent_by_construction`). The wrong-order
   control therefore attacks slot-content-vs-bus-gain, **not** summation
   order.
2. With **byte-identical** occupant coefficients, a slot-content permutation
   degenerates to a pure **relabeling** of the two register sets: the audio
   is unchanged and only the per-instance **checkpoint** catches it —
   measured, not assumed (NC-C leg 4: 6 mismatches, all checkpoints, 0 audio
   mismatches of 384 main-bus + 768 wet samples). This is precisely why this
   leaf's exactness check compares per-instance checkpoints and not only
   audio.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (20 cases, 8,448 main-bus samples + 16,896 per-bus wet samples + 132 checkpoints, 0 mismatches) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (oracle unavailable; §0a) | `artifacts/oracle-status.json` |
| Reference-fixture freeze for this routing form | **BLOCKED** (SXT-011 send-level gap → SXT-017 decision, #12; §0b) | `artifacts/send-level-gap.json`, `artifacts/oracle-status.json` |
| Negative controls live | **6/6 CONTROL-OK** (19 legs, 0 NOT_RUN; 6 are live RTL mutants) | `negative-controls/negative-controls.json` |
| Per-instance state (dual-bus) | **PASS** (model NC-D + live RTL shared-state mutant fails, incl. the same-FX-class case) | `negative-controls.json`, `rtl-exactness.json` |
| Instance lifecycle (patch change mid-tail, slot off, panic/reset) | **PASS** (3 dedicated RTL cases + model tests) | `rtl-exactness.json` §2, `tests/test_sxt028l.py` |
| Declared tail span rendered | **PASS** (6 silent-scene blocks, all carrying nonzero wet audio) | `rtl-exactness.json` (`tail-span-silent-scenes`) |
| Dropped-tail render | **FAILS the tail check, as required** (model truncation + live RTL tail-killing mutant) | `negative-controls.json` NC-B |
| Gain-plane placement (send-form specific) | **PASS** (misplaced gains FAIL, model-side and in live RTL) | `negative-controls.json` NC-F |
| Composition with the landed routing leaves | **PASS** (ains34 + bins12 → this leaf → global34; 8 independent histories) | `tests/test_sxt028l.py::test_composes_with_the_landed_insert_and_global_routing_leaves` |
| Carrier routing/scheduling metadata | **PASS** (6/6, census+graphs cross-checked, drift 0) | `model/effects/fx_inputs/rf-rf-send34-*.json` |
| Complete-wet preset renders / new reference fixtures | **NOT_RUN** (oracle unavailable) + **BLOCKED** (#12) | §0a/§0b, `artifacts/render-refusals.txt` |
| External-memory traffic | **PASS** (this leaf's own contribution: 0 words/sample; aggregate `[PENDING-SXT-016]`) | `artifacts/state-cost.json` |
| Newly-enabled presets | **0** (no support claim follows from this record) | §6 |
| Musical quality / listening | **NOT_RUN** (no listening record; #9 remains BLOCKED-on-human) | — |

## 1. Frozen model

`model/effects/rf-rf-send34/rf_send34_model.py` + `README.md`. Models the
send-FX block for slots 12/13: the control-rate instance-lifecycle pass (runs
in every bypass mode, as the engine's load/unload path does), the gain-plane
pass, the `fx_bypass` gate (**`ALL_FX` only**), the `fx_disable` per-slot
bitmask gate (engine bit layout, bits **12/13**), the per-bus formation from
both scene buses, the in-place `process_ringout` on each bus through its own
`SendSlotInstance`, and the return mix into the main bus. `model_revision()`
pins the frozen file's sha256 for the stale-harness control (§3, NC-E) and is
echoed by the RTL comparator (`rtl-exactness.json`) and the state-cost
record.

Word formats (frozen): bus audio **Q10.21 s32**, biquad coefficients
**Q3.29 s32**, send/return gains **Q1.30 s32** (new in this leaf), TDF2
accumulator **80-bit signed**; exact products, round-half-up, saturating; no
floating point at audio run time. With both buses off the return mix
reproduces the main bus **bit-exactly**
(`test_main_bus_passes_through_bit_exactly`).

**Declared seams.** (a) `send1`/`send2` are the *base half* of the same send
rack. They are **not upstream** of this leaf — the buses are parallel — they
are co-tenants of the same main bus, so their returns are part of this leaf's
`main_l`/`main_r` stimulus. No `rf-send12`-class leaf exists in this
repository yet; the seam is declared in the model (`BASE_HALF_ROLES`) and
asserted conditionally by
`test_declared_seam_with_a_future_send12_base_half`, so the absence is
explicit rather than forgotten. (b) The *scene* buses arriving here are what
the insert chains left, and this leaf's main-bus output feeds the global
chain;
`test_composes_with_the_landed_insert_and_global_routing_leaves` composes the
landed `rf-rf-ains34` + `rf-rf-bins12` → **this leaf** → `rf-rf-global34`,
checks the five routing forms agree on the shared slot table and word
formats, and checks that all **eight** slot instances end with eight distinct
histories. Nothing about the other leaves is re-claimed here; the scene sum
used to build the main bus is declared **stimulus**, not a modeled stage.

Lifecycle (frozen, identical in model and RTL): slot off → that instance
released and its bus contributes nothing; occupancy rising or a `reload`
pulse → FRESH instance for **that slot only** (its registers cleared, the
sibling's history, the bus gain plane and the other bus's ring memory
untouched); occupancy steady without reload → coefficients adopted with state
kept; `panic_reset()` / `state_reset` → both instances cleared and both
buses' ring memory dropped, patch and gain plane unchanged.

## 2. RTL-vs-model exactness

`rtl/effects/rf-rf-send34/{rf_send34_core.sv, tb_rf_send34.sv}`, compared via
`tools/compare_rtl_model_rf_send34.py` (iverilog; INTEGER EQUALITY of every
main-bus output sample, every per-bus wet sample, and every per-instance
checkpoint — both buses' TDF2 registers plus both ring flags). The single
harness is both the dual-instance bench (each checkpoint line dumps send3's
and send4's registers separately, and each block dumps the two buses' wet
taps separately) and the negative-control bench (§3 drives the mutants
through the same stimulus path).

| Case | Blocks | Exercises |
|---|---|---|
| `both-buses-all-fx` | 6 | baseline: both buses occupied, `fx_bypass = ALL_FX` |
| `bypass-no-sends-skips-stage` | 6 | **send-specific**: `NO_SENDS` removes exactly this stage, where the insert and global stages still run |
| `bypass-scene-fx-only-skips-stage` | 6 | `SCENE_FX_ONLY`: stage skipped |
| `bypass-no-fx-skips-stage` | 6 | `NO_FX`: main bus passes through, no bus formed, no state advanced |
| `bus3-disabled-bit12` | 6 | `fx_disable` bit 12 set: bus 3 discarded, bus 4 still returns |
| `bus4-disabled-bit13` | 6 | `fx_disable` bit 13 set |
| `both-buses-disabled-corpus-mask` | 6 | **real-corpus shape** (`Closeout Sale @ Electro Percussion Warehouse.fxp`, `fx_disable = 13107`): both occupied, both disabled |
| `bus4-unoccupied-send3-only` | 6 | the `Trance`/`Dystopia` carrier shape (send3 only) |
| `bus3-unoccupied-send4-only` | 6 | the complementary single-instance shape |
| `same-class-dual-occupants` | 6 | **real-corpus shape** (`Strynth.fxp`: Nimbus in BOTH buses) — identical coefficients on distinct gain planes; the final histories must still differ |
| `scene-b-inactive-single-mode` | 6 | Single scene mode: scene B is never instantiated, only scene A feeds the buses (all three issue-named carriers) |
| `zero-return-level-both-buses` | 6 | **real-corpus shape** (`Random Bass FX.fxp`, `return_level = 0.0` on both): buses run and their state advances, but they return silence |
| `sendused-false-passthrough` | 6 | `sendused` false on both buses: formed bus passes through, no state advances (declared contract #3) |
| `sendused3-goes-false-mid-run` | 6 | one bus's ring flag drops mid-run while the other keeps going |
| `tail-span-silent-scenes` | 8 | 2 signal blocks + **6 blocks with the SCENE buses silent** while `sendused` stays true: the occupants' arithmetic tails must keep being rendered and mixed back (all 8 blocks carry nonzero wet output) |
| `bus3-reload-mid-tail` | 8 | `loadFx()` on send3 at block 3 mid-tail: send3's history clears, send4's continues, the gain plane is untouched |
| `bus4-off-mid-tail` | 8 | `enqueueFXOff()` on send4 at block 3: its history is released and its bus stops contributing entirely |
| `panic-reset-mid-tail` | 8 | `state_reset` before block 4: BOTH instances clear, both ring flags drop |
| `saturating-full-scale` | 4 | near-full-scale input, high-gain occupant, near-unity gains: the `sat32` paths in **both** bus formation and the return mix |
| `random-control-stream` | 12 | bypass mode, disable mask, scene-B activity, occupancy, reload pulses, **the whole gain plane** and both `sendused` flags randomized per block |

**Result: 20/20 exact, 0 mismatches — 8,448 main-bus output samples +
16,896 per-bus wet samples + 132 per-instance checkpoints compared.** Full
record: `rtl-exactness.json` (`status: "PASS"`).

The comparator refuses to report PASS against a stale frozen model:
`--assert-model-revision <hex>` exits 2 with `status: "REFUSED"` when the
pinned revision does not match the live model file (§3, NC-E leg 2 invokes
exactly that path).

## 3. Negative controls (all 5 required + 1 additional; `tools/rf_send34_negative_controls.py`)

Every control reports per-leg status; a leg that could not run would be
recorded `NOT_RUN` and never counted as a demonstrated failure. In this
environment **0 legs were NOT_RUN** (iverilog present).

| Control | Targets | Legs | Verdict |
|---|---|---|---|
| **NC-A** generic substitute (pass-through + fixed gain on send bus 4) | per-instance-state faithfulness / coverage eligibility | main-bus output bit-exactness (4/4 blocks differ); per-instance state (substitute keeps no history) | **CONTROL-OK** — labeled `ADAPTED`, `counts_toward_original_preset_coverage: false` |
| **NC-B** dropped tail (2 of 8 declared blocks rendered) + live RTL stage-skip-on-silence | declared tail-span coverage | dropped region demonstrably carries audio (6/6 dropped blocks nonzero on the wet taps, Σ\|x\| = 3,750,850); coverage check fails; final checkpoint differs; **live RTL mutant** `-DNC_TAIL_KILL` (1,157 mismatches incl. all 6 tail checkpoints) which the non-silent baseline case does **not** catch (0 mismatches) | **CONTROL-OK** |
| **NC-C** wrong order (send3/send4 slot-content permutation) | order-sensitive equality of the parallel send rack | model, distinct occupants (384/384 samples differ, max Δ = 321,969, checkpoints differ); model, **same FX class with different parameter values** (382/384 differ, max Δ = 755); **live RTL mutant** `-DNC_SWAP_ORDER` (1,158 mismatches); **live RTL mutant, byte-identical coefficients** (6 mismatches — **all checkpoints, zero audio**, see the bound below) | **CONTROL-OK** |
| **NC-D** shared state (both buses pooled into one history) | dual-instance independence | model pooled mutant, distinct occupants (6/6 blocks differ; pooled checkpoint halves become identical); model pooled mutant, **SAME-class occupants** (6/6 blocks differ); **live RTL mutant** `-DNC_SHARED_STATE` (561 mismatches); **live RTL mutant on the same-class case** (619 mismatches) | **CONTROL-OK** |
| **NC-E** stale stub (frozen-revision pin) | stale-harness refusal | `revision_pin_ok()` rejects a mutated pin; the real comparator invoked with a stale pin exits 2 with `status: "REFUSED"` | **CONTROL-OK** |
| **NC-F** gain placement *(ADDITIONAL — not one of the five the issue names)* | the send form's own routing-gain plane | model swap of bus 3's scene-A send gain with its return gain (384/384 samples differ); **live RTL mutant** `-DNC_GAIN_SWAP` (1,158 mismatches) | **CONTROL-OK** |

**6/6 CONTROL-OK, 19/19 legs** (a control that passes its target check would
be a broken control, per issue #64's own framing). Full record:
`negative-controls/negative-controls.json` (`status: "PASS"`), transcript in
`negative-controls/negative-controls.txt`. The live RTL mutants are
`rtl/effects/rf-rf-send34/rf_send34_mutants.sv`, compiled INSTEAD of the real
core and driven through the production testbench; compiled with no defect
selected the file refuses to simulate (`$fatal`), so it cannot silently
become a passing "control".

**Why NC-F exists.** The five controls the issue names were written for the
series routing forms. The send form's whole novelty is its gain plane — three
words per bus, in two distinct places in the signal path — and none of the
five attacks it: a gain-placement error preserves order, per-instance state,
tails and the revision pin. NC-F is therefore added rather than assumed
covered. It is labeled as an addition everywhere it appears and does not
displace any required control.

**Why NC-D is run twice.** The corpus contains the hardest case for the
per-instance-state rule: `Exquis MPE/Strings/Strynth.fxp` hosts Nimbus in
**both** send3 and send4 (7 corpus presets host the same class in both).
Identical arithmetic in both buses is exactly where a pooled-state
implementation is most likely to slip through, so both the model leg and the
live RTL leg are repeated on the `same-class-dual-occupants` case. Both still
fail as required, and the correctly-isolated rack's two histories remain
distinct (`rtl-exactness.json`,
`same-class-dual-occupants.dual_instance.final_histories_differ`).

**Honest bounds on NC-C (recorded, not hidden).**
1. The return mix is **order-independent by construction** (one wide
   accumulator, one rounding, one saturation — §0d), so this control cannot
   and does not claim to detect a reordered summation. What it detects is the
   *slot-content* permutation: which occupant sits on which bus, against that
   bus's own send and return gains. Both the model legs and the live RTL
   mutant attack exactly that.
2. Permuting two buses whose occupant **content and gain plane** are both
   identical is the identity map (verified in the control's `recorded_bound`).
   With identical *content* but distinct gains it is still an identity at the
   bus in the RTL mutant's form (register relabeling) and is caught **only by
   the per-instance checkpoint** — 6 mismatches, all checkpoints, 0 of 1,152
   audio words. The control therefore reports its force honestly: audio-level
   detection needs occupants that differ (which is the real-corpus case, e.g.
   `Batbrass.fxp`: Distortion on send3, Phaser on send4), and checkpoint-level
   detection covers the rest.

Neither bound affects the RTL-vs-model exactness claim.

## 4. Carrier routing/scheduling metadata (oracle-independent, zero-drift)

`tools/extract_rf_send34_inputs.py` re-verifies the census blob sha1
(`corpus/census-v0.1/results/per-preset.csv`), cross-checks
`corpus/normalized/graphs.jsonl` (already surgepy-derived and committed;
SXT-011), re-derives this leaf's slot indices from the corpus role table
itself, records the SXT-011 send-level gap (§0b), and **asserts zero drift
between those two independent artifacts** on every field both carry (blob
sha1, stored revision, scene mode, `fx_bypass`, `fx_disable`, non-off FX slot
count, non-off FX type set). Any disagreement is a refusal, not a silently
preferred source (`tests/test_sxt028l.py::test_extraction_refuses_injected_drift`
injects census drift, a changed FX type id, a blob-sha mismatch and a
corrupted slot-index table, and requires a refusal for each).

*FX-type comparison note.* The census CSV names an FX through the census
parser's own static table (`FrequencyShifter`, `RingModulator`) while the
normalized graph uses the engine's live display name (`Freq Shift`,
`Ring Mod`). A name-vs-name comparison would refuse on **spelling** for two of
the six carriers. The cross-check therefore maps the graph's stored type
**ids** through the census's own committed `FX` table and compares in that one
naming authority — a strictly *content*-level comparison, with no invented
alias list; the engine display names are recorded alongside as context
(`cross_check.engine_display_names_context`). A genuinely different FX in a
slot still refuses (asserted).

| Preset | Source | send3 | send4 | scene mode | `fx_disable` | base half send1/2 | Shape |
|---|---|---|---|---|---|---|---|
| `Exquis MPE/Basses/Trance.fxp` | issue-named | Chorus (on, `rl` 1.0) | Off | Single | 0 | 1 active | send3 only |
| `Exquis MPE/Brass/Batbrass.fxp` | issue-named | Distortion (on, `rl` 1.0) | Phaser (on, `rl` 1.0) | Single | 0 | 2 active | **dual-instance** |
| `Exquis MPE/FX/Dystopia.fxp` | issue-named | Reverb 2 (on, `rl` 1.0) | Off | Single | 0 | 2 active | send3 only |
| `Exquis MPE/Strings/Strynth.fxp` | added (shape) | Nimbus (on, `rl` 1.0) | Nimbus (on, `rl` 1.0) | **Dual** | 0 | 2 active | **same class in both buses; scene B feeds them** |
| `Kinsey Dulcet/Percussion/Closeout Sale @ Electro Percussion Warehouse.fxp` | added (shape) | Spring Reverb (on, **disabled**) | Nimbus (on, **disabled**) | Single | **13107** (bits 12\|13) | 2 active | **both disabled** |
| `Slowboat/FX/Random Bass FX.fxp` | added (shape) | Reverb 2 (on, **`rl` 0.0**) | Nimbus (on, **`rl` 0.0**) | Single | 72 | 2 active | **return muted on both** |

6/6 census blob + graphs cross-checks PASS, drift count 0, 0 refusals
(`artifacts/extract-refusals.txt` empty). Unlike the sibling global-rack leaf,
**the issue's own named carriers do reach the dual-instance shape** here
(`Batbrass.fxp`); the three additions cover the same-class, both-disabled and
return-muted shapes, are recorded as additions (`carrier_source`) and are
never presented as issue-named carriers. Every carrier's stored per-slot
`return_level` is recorded with
`return_level_consumed_by_send_path: true` — the opposite of the
insert/global leaves, where the same field is recorded but explicitly not
consumed.

Per-slot algorithm parameter values are NOT extracted (§0a — oracle
unavailable); each record carries `oracle_extraction.ok: false` with the
reason. Per-scene send levels for buses 3/4 are NOT extracted and NOT
invented (§0b — the SXT-011 gap, `send_level_gap.send3_send4_levels_stored:
null`).

## 5. External-memory traffic

`artifacts/state-cost.json`, **derived** from the frozen model's declared word
widths (`tools/rf_send34_state_cost.py`) rather than hand-counted, and pinned
to `model_revision()` so it cannot go stale silently:

- This leaf's own contribution is **0 external-memory words/sample** and 0
  external writable words. Its synthetic occupant kernel is register-only and
  the send buses themselves are per-block scratch, not history; the frozen
  model's per-slot `ext_reads`/`ext_writes` counters stay at 0 (asserted by
  `tests/test_sxt028l.py`).
- On-chip small state, on the same accounting the landed sibling routing
  leaves used (histories + occupancy + routing-control bits): **663 bits**
  (2 × 321 per-instance + 21 shared) — the same order as `rf-rf-global2`'s
  661, `rf-rf-global34`'s 661 and `rf-rf-bins12`'s 663, as expected for the
  same instance shape on two more slots.
- **Plus this form's own gain plane: +192 bits** (2 buses × 3 × Q1.30),
  reported **separately** rather than folded into the comparable number,
  because the series forms have no counterpart to it. Counting the per-slot
  coefficient registers, the gain plane and the block FSM gives **1,186 bits
  (149 bytes)**.
- The AGGREGATE estimate for a concrete preset also depends on whichever
  algorithm leaf's occupant actually lands in send3/send4 — and the corpus
  really does put long-buffer classes there (Reverb 2, Nimbus, Spring Reverb,
  Delay across the six carriers) — which is that leaf's own SXT-015/016
  accounting, not invented here: **`[PENDING-SXT-016]`** per the issue text.
- Long delay/reverb-class buffers belong in external WRITABLE memory; flash
  is not writable delay memory (AGENTS.md). Not applicable to this leaf's own
  register-only contribution, but it **is** the live question for the
  concrete occupants the corpus puts on these buses — routed to SXT-015/016,
  not answered here.

## 6. Coverage (reported separately from agreement)

`artifacts/corpus-occupancy.json` inventories which of the 3,561 committed
corpus presets exercise this routing form's shapes. **Coverage accounting
only — not a support claim and not an agreement number.**

| Shape | Presets |
|---|---|
| `send3` occupied | 78 |
| `send4` occupied | 29 |
| both occupied (the dual-instance shape) | 25 |
| both occupied with the SAME FX class | 7 |
| `fx_disable` bit 12 set | 8 |
| `fx_disable` bit 13 set | 4 |
| both bits 12 and 13 set | 1 |
| an occupied bus with `return_level` 0.0 | 3 |
| non-Single scene mode with a send3/4 occupant | 28 |
| non-`All FX` `fx_bypass` with a send3/4 occupant | **0** |

The last row is why §0c's bypass-partition contract cannot be discriminated
by any committed corpus carrier: no preset in the corpus combines a
non-default `fx_bypass` with an occupied extended send bus.

### Newly enabled presets

**0.** This record establishes no preset-support claim (§0a/§0b); the issue's
own `newly_enabled` accounting
(`reports/sxt-028/leaves/SXT-028l/newly-enabled.json`, FX-scope-only and
explicitly "NOT a support claim") is unaffected by this leaf landing. This
leaf's coverage contribution to the FX-routing axis is the send3/send4
extended-rack form; its agreement contribution is exactly the RTL↔model
exactness claim in §2 and nothing else.

## 7. Stop/escalate status

The issue's stop condition ("if the effect cannot be bounded in state/cost
under the shared instance schedule, record the finding and route to SXT-017")
was **not** triggered: this form's state is bounded and small (§5), with no
external-memory requirement of its own. Four items are routed onward rather
than closed here:

1. **The SXT-011 send-level data gap → #12 (SXT-017)** (§0b). This is the
   issue's own named blocker and it remains open: reference fixtures for this
   routing form cannot be frozen until the loader-default send-level
   semantics are probed and a data-gap policy is decided. Recorded with a
   mechanical corpus-wide re-verification and a live refusal control; nothing
   was guessed and no acceptance item was weakened to route around it.
2. **The oracle-dependent reference legs** (§0a, blocked on an oracle build).
3. **The declared-contract re-verification items** (§0c: the send-stage
   routing text, the `sendused`-false contract, the occupant ring-out policy,
   the FX-off queue timing).
4. **The ext-mem aggregate** for concrete occupants on these buses
   (`[PENDING-SXT-016]`, §5) — this leaf's own contribution is 0.

The [PROPOSED] reference budgets remain unfrozen, gated on SXT-017 (#12).

## Reproduce

```sh
python3 tools/extract_rf_send34_inputs.py
python3 tools/rf_send34_oracle_status.py
python3 tools/rf_send34_state_cost.py
python3 tools/compare_rtl_model_rf_send34.py --out reports/SXT-028l/rtl-exactness.json
python3 tools/rf_send34_negative_controls.py
python3 -m pytest tests/test_sxt028l.py -q
```
