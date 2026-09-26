# SXT-028l frozen fixed-point model — routing form: Send buses 3-4 (`model/effects/rf-rf-send34/`)

Frozen reference for the SXT-028l RTL (`rtl/effects/rf-rf-send34/`). The RTL
must match this model **exactly** (integer equality of every main-bus output
sample, every per-bus wet sample and every per-instance checkpoint;
`tools/compare_rtl_model_rf_send34.py`). Model-vs-pinned-engine agreement is
a SEPARATE claim and is **not exercised** by this leaf — no oracle-dependent
reference-agreement number is reported here; see
`reports/SXT-028l/EVIDENCE.md` §0.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  (`oracle/manifest.json`).
- Structure authority (cited, nothing copied):
  - `src/common/SurgeSynthesizer.cpp` `process()` — the send-FX block:
    `fxsendout[s]` accumulated from each scene's post-insert output scaled by
    that scene's `send_level[s]`, processed in place by the send slot's
    effect through `process_ringout(L, R, sendused[s]) -> bool`, and mixed
    into the main output scaled by the slot's `return_level`, under the
    `fx_bypass` gate and the `fx_disable` per-slot bitmask gate; instance
    lifecycle via `loadFx()` / `enqueueFXOff()` / `reorderFx()`.
  - `src/common/SurgeStorage.h` — `fxslot_positions` (**send3 = 12,
    send4 = 13**; send1/2 = 4/5), `n_send_slots = 4`, the `fxb_*` bypass
    enum, `n_fx_slots = 16`.
  - `src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h` —
    instance construction/suspend per slot (`fx[v] == nullptr` ⇔ slot
    unoccupied; modeled as `SendSlotInstance.occupied`).
- **In-repo re-derivation of the slot indices** (no live oracle needed):
  every one of the 3,561 records in `corpus/normalized/graphs.jsonl` carries
  the pinned engine's slot order by patch `fx[]` index — role `send3` at
  index 12, `send4` at index 13. Asserted by
  `tests/test_sxt028l.py::test_slot_indices_agree_with_the_committed_corpus_role_table`
  and re-checked per carrier by `tools/extract_rf_send34_inputs.py`
  (`slot_index_check`, a refusal on disagreement).
- **In-repo re-derivation of the send-stage routing** (also oracle-free): the
  committed SXT-011 artifact `corpus/normalized/README.md` ("FX slot roles
  and processing order") states the pinned engine's order as "A1→A4 and B1→B4
  insert chains, scene sum, send buses S1..S4 (each sums
  `scene[0].send_level[k]` and `scene[1].send_level[k]`, applied when
  `fx_bypass==fxb_all_fx`, scaled by the slot's `return_level`), then G1→G4
  on the main output", with per-slot disable `fx_disable & (1<<slot)`. That
  in-repo text, written against the pin, is this leaf's routing contract; it
  is **not** a fresh read of `process()` (no oracle checkout was available).
  Recorded as a named re-verification item in
  `reports/SXT-028l/EVIDENCE.md` §0b.

## This is a PARALLEL routing form (what is new here)

Every routing-form leaf landed before this one (`rf-rf-global2`,
`rf-rf-bins12`, `rf-rf-ains34`, `rf-rf-global34`) models a **series** insert
pair: one bus threaded in place through two slots. A send bus is different in
kind — two independent buses that are *formed from* the scene buses and
*mixed back into* the main bus:

```
scene A out ──┬─ × send_gain[A][3] ─┐
              │                     ├─▶ [send bus 3] ─▶ send3 FX ─┐ × return_gain[3] ─┐
scene B out ──┼─ × send_gain[B][3] ─┘                             │                   │
              │                                                   │                   ├─▶ main out
              ├─ × send_gain[A][4] ─┐                             │                   │
              └─ × send_gain[B][4] ─┤                             │                   │
                                    ├─▶ [send bus 4] ─▶ send4 FX ─┘ × return_gain[4] ─┤
main bus in ────────────────────────┴───────────────────────────────────────────────  ┘
```

Consequences this leaf owns, none of which exist in the series forms:

| Fact | Series insert/global forms | This send form |
|---|---|---|
| Bypass modes the stage runs in | insert `{all_fx, no_sends, scene_fx_only}`; global `{all_fx, no_sends}` | **`{all_fx}` only** — the strictest partition in the engine (`fxb_no_sends` means exactly "remove this stage") |
| A slot that is unoccupied or disabled | passes its audio through | **contributes nothing**; its bus is discarded |
| Gain plane | none | **3 words per bus**: per-scene send gains (A, B) + return gain |
| Ring flag | one flag threaded slot → slot | **one `sendused` flag per bus**, independent |
| Scene coupling | one scene's own bus | **both scenes** feed every bus (scene B only when instantiated) |
| Upstream/downstream | strictly ordered | the two buses are **peers**; only the main-bus mix couples them |

## The SXT-011 send-level data gap (this leaf's fixture-freeze blocker)

The engine has four send buses, but a `.fxp` stores only **two** per-scene
send levels and the surgepy binding exposes only `send_level[0..1]`
(`corpus/normalized/README.md` "Send levels 3/4";
`corpus/normalized/schema.json` `scene.send`). Buses 3/4 therefore run at
**loader defaults** for every one of the 3,561 committed corpus presets, and
no in-repo artifact carries a value for them. This leaf does not invent one:

- `send_gain_a` / `send_gain_b` are **control-plane stimulus** in the model
  and the RTL, never derived from a corpus record.
- `tools/extract_rf_send34_inputs.py` emits `send_level_gap` with
  `send3_send4_levels_stored: null` for every carrier, and re-verifies the
  gap mechanically across the whole corpus
  (`reports/SXT-028l/artifacts/send-level-gap.json`: 7,122 scene records,
  **all** carrying exactly two send levels, never four). If that ever stops
  being true the extractor **refuses** rather than reinterpreting.
- `return_level` **is** stored per slot and **is** exported by SXT-011
  (`graphs.jsonl` `fx[].rl`), so it is extracted per carrier — and unlike
  the insert/global forms, this routing form really does consume it.
- Freezing reference fixtures for this form needs an engine-behavior probe of
  the loader default **and** an SXT-017 data-gap policy decision (**#12**).
  This leaf does not pre-empt that decision. The RTL-vs-frozen-model
  exactness claim does not depend on it.

## Form scope, not algorithm scope

This leaf's claim is the **send-bus formation and return wiring, the per-bus
schedule, `fx_bypass`/`fx_disable` gating, the per-slot instance lifecycle,
and per-instance-state isolation** of hosting two concurrently-active
send-FX instances — "algorithm behavior stays with the per-algorithm leaves"
(issue #64 scope note; `AGENTS.md`). The per-slot occupant exercised here is
a **synthetic TDF2 biquad primitive** (the same Direct-Form-II-Transposed
recurrence every landed leaf's biquad stage already uses — Reverb1's
instant-coefficient `biq_stage`, Delay/Chorus's per-sample-lag `Biquad`, the
sibling routing leaves' `BiquadInstance`), driven by arbitrary control-plane
coefficients, **not** derived from any concrete Surge FX class's parameters.
It exists only to give the routing claim a real, per-instance-stateful,
tail-bearing arithmetic path to verify gain placement, state isolation,
lifecycle behavior and tail continuation against.

**What this leaf does NOT claim**: no specific Surge FX algorithm's fidelity;
no preset-support claim; no musical-quality claim; no model-vs-pinned-engine
reference-agreement number (the routing/scheduling metadata for six corpus
carriers IS verified — see `fx_inputs/rf-rf-send34-*.json` — but the pinned
oracle build was unavailable in the environment that produced this record, so
per-slot algorithm-parameter extraction and every wet-audio reference render
are refused, not fabricated; `reports/SXT-028l/EVIDENCE.md` records this as a
named, bounded gap).

## Frozen word formats (this leaf)

| Domain | Format | Notes |
|---|---|---|
| bus audio words | **Q10.21** signed 32-bit | matches the Delay/EQ/Chorus bus scale and all four landed routing leaves |
| biquad coefficients | **Q3.29** signed 32-bit | block-constant (instant); NO per-sample lag |
| send / return gains | **Q1.30** signed 32-bit | **new in this leaf**; block-constant, one word per (scene, bus) send gain and one per bus return gain |
| biquad TDF2 accumulator | **80-bit signed** | Reverb1 `REG_LIM` precedent: headroom for adversarial negative-control coefficients without a stability argument |

Arithmetic rules (FROZEN, self-contained in `rf_send34_model.py` — mirrors
`model/effects/qmath.py`'s round-half-up/saturating conventions without
mutating its shared format registry): exact products, round-half-up
`(p + 2**(s-1)) >> s`, saturating; no floating point at audio run time.

**One rounding per mix, twice.** Bus formation accumulates both scenes'
contributions at full width and reduces **once**; the return mix accumulates
`main_in << G_FRAC` plus every running bus's `wet × return_gain` at full
width and reduces **once**. Both sums are therefore *order-independent by
construction* — a deliberate, declared design choice that also **bounds this
leaf's wrong-order control**: for a parallel form the observable permutation
axis is slot-content-vs-bus-gain, not summation order
(`reports/SXT-028l/EVIDENCE.md` §3). With both buses off the return mix
reduces to `main_out == main_in` **exactly**
(`tests/test_sxt028l.py::test_main_bus_passes_through_bit_exactly`).

**Gain mapping is control-rate only.** `gain_from_level(level)` applies
`gain = level**3` — the `amp_to_linear`-cubed semantic already pinned in-repo
by the landed SXT-024 Reverb1 send path (`tools/compare_reverb_model.py`,
`tools/run_reverb_rtl.py`, `reports/sxt-024/EVIDENCE.md`) — and quantizes to
Q1.30. The audio path (model and RTL alike) consumes only the resulting
integer word, so the mapping is **outside** the RTL-vs-model exactness claim
and is recorded as a declared contract in `reports/SXT-028l/EVIDENCE.md` §0b.

The file is deliberately self-contained and imports no sibling leaf's kernel:
`model_revision()` (sha256 of the file) is the frozen-revision pin consumed
by the RTL comparator and the stale-harness negative control, so a sibling
leaf's future edit can never change this leaf's frozen behavior without
changing this leaf's own pin.

## Schedule (the send-FX block for slots 12/13)

```
control-rate pass (runs in EVERY bypass mode — the engine's load/unload path
                   is control-rate):
    apply the instance-lifecycle rule to send3 and send4 (below)
    apply the bus gain plane (send_gain_a, send_gain_b, return_gain per bus)

audio pass:
if fx_bypass == ALL_FX:
    for (slot, bit, levels, sendused) in (send3, 12, levels3, send_in3),
                                         (send4, 13, levels4, send_in4):
        if slot.occupied and not fx_disable_bit(bit):
            bus = scene_a × send_gain_a  (+ scene_b × send_gain_b if scene B)
            (bus, ring) = slot.process_ringout(bus, sendused)
            main += bus × return_gain
else:                                   # NO_SENDS, SCENE_FX_ONLY, NO_FX
    main unchanged; no bus is formed, no instance state advances, and
    neither bus reports ringing
```

`process_ringout(l, r, indata)`: while `indata` (this bus's `sendused`) is
true, process every sample in place and report ringing == true; otherwise
pass the bus through untouched and report not-ringing. This occupant declares
**no ring-out policy of its own** — the same simplification all four landed
routing leaves declared (a tail-bearing occupant's own policy is
algorithm-leaf scope). Its **arithmetic** tail — nonzero output after the
scene buses go silent, straight out of the TDF2 registers — is real and is
exactly what the tail acceptance case and the dropped-tail negative controls
exercise.

## Instance lifecycle (frozen; identical in model and RTL)

| Control | Effect |
|---|---|
| `occupied` false | instance released (`enqueueFXOff()`): that slot's registers cleared, that bus contributes nothing to the main bus |
| `occupied` rising, or `reload` pulse | FRESH instance (`loadFx()`): **that slot only** is cleared, new coefficients adopted; the sibling slot's history, **the bus gain plane** and the other bus's ring memory are untouched |
| `occupied` steady, no `reload` | coefficients adopted **without** clearing state (abrupt parameter change; per-parameter smoothing is algorithm-leaf scope) |
| `panic_reset()` / RTL `state_reset` | both instances cleared and both buses' ring memory dropped; occupancy (the loaded patch) and the gain plane unchanged |

The exact queue-drain timing of the engine's own `enqueueFXOff()` is **not**
verified here (no oracle checkout): this leaf's lifecycle applies slot-off at
the control-rate pass preceding a block, which is a **declared contract** of
the model (matched exactly by the RTL), recorded as such in the EVIDENCE
record's re-verification list.

## Per-instance state

One `SendSlotInstance` holds one `BiquadInstance` (4 accumulator words:
`reg0`/`reg1` × {L, R}) plus its own `occupied` flag. The two configured send
slots (`ExtendedSendRack.slot3`, `.slot4`) are two disjoint
`SendSlotInstance` objects — no accumulator state is ever shared between
them, even though both run through the SAME arithmetic kernel class
(`BiquadInstance.process_sample`): shared arithmetic, independent state
(`AGENTS.md`; issue #64 "Per-instance state" acceptance item).

This is checked in the case that matters most: the corpus really does host
**the same FX class in both buses** — `Exquis MPE/Strings/Strynth.fxp`
carries Nimbus in `send3` **and** `send4` (7 corpus presets do this at all).
Identical arithmetic is exactly where a pooled implementation hides best, so
the RTL case `same-class-dual-occupants` and the NC-D same-class legs run the
controls there too.

The per-bus **gain plane is bus state, not occupant state**: a `loadFx()`
replaces the occupant and clears its history but never disturbs the bus's
send/return levels
(`tests/test_sxt028l.py::test_reload_does_not_disturb_the_bus_gain_plane`).

## Declared control-plane boundary (model → RTL)

Per block: `fx_bypass` (2-bit mode), `fx_disable` (16-bit mask, engine bit
layout; only bits 12/13 consumed), `scene_b_active`, and per bus `occupied`,
`reload` (a patch-change pulse), 5 biquad coefficients (Q3.29) and 3 gain
words (Q1.30). The two `sendused` flags and the scene/main buses are
per-block audio-plane stimulus (computing them is out of scope). The RTL
computes everything audio-rate: the bus formation, the TDF2 recurrence, the
return mix, the bypass/disable gates and the lifecycle clears.

## Declared scope omissions (fail-closed)

- The `send1`/`send2` **base half** of the same send rack (a sibling
  `rf-send12`-class leaf's scope; **not landed in this repository** — its
  returns are simply part of the `main_l`/`main_r` stimulus), the scene
  insert chains (`rf-rf-ains34`, `rf-rf-bins12` landed) and the global chain
  (`rf-rf-global2`, `rf-rf-global34` landed).
- The scene sum itself and everything downstream of the send returns.
- Per-scene `send_level` and per-slot `return_level` **smoothing** (the
  engine ramps these per block; this leaf consumes block-constant gain
  words — same family of omission as the block-constant biquad
  coefficients).
- Per-sample coefficient smoothing/ramping into the occupant (algorithm-leaf
  scope).
- Any concrete Surge FX algorithm's own ring-out **decision** — see
  "Schedule" above.
- The engine-side queue-drain timing of `enqueueFXOff()` — see "Instance
  lifecycle" above.
- Per-slot algorithm parameter values and any wet-audio reference render —
  requires the pinned oracle build (surgepy), unavailable in the environment
  that produced this record; refused, not fabricated
  (`reports/SXT-028l/artifacts/{oracle-status,render-refusals}.*`).
- The loader-default per-scene send levels for buses 3/4 — the SXT-011
  exposure gap above; **BLOCKED on #12**, not guessed.

## Files

- `rf_send34_model.py` — the frozen model (`ExtendedSendRack`,
  `SendSlotInstance`, `SendBusLevels`, `BiquadInstance`; `model_revision()`
  frozen-revision pin consumed by the RTL comparator — a stale harness
  refuses to report PASS).

## Reproduce

```sh
python3 tools/extract_rf_send34_inputs.py                                     # carrier metadata + occupancy + send-level gap scan
python3 tools/rf_send34_oracle_status.py                                      # measured oracle probe (NOT_RUN / BLOCKED legs)
python3 tools/rf_send34_state_cost.py                                         # derived state/cost inventory
python3 tools/compare_rtl_model_rf_send34.py --out reports/SXT-028l/rtl-exactness.json
python3 tools/rf_send34_negative_controls.py                                  # 5 required + 1 additional negative control
python3 -m pytest tests/test_sxt028l.py -q
```
