# SXT-028h frozen fixed-point model — routing form: Scene-B insert FX bus, slots 1-2 (`model/effects/rf-rf-bins12/`)

Frozen reference for the SXT-028h RTL (`rtl/effects/rf-rf-bins12/`). The RTL
must match this model **exactly** (integer equality of every output sample and
every per-instance checkpoint; `tools/compare_rtl_model_rf_bins12.py`).
Model-vs-pinned-engine agreement is a SEPARATE claim; it is **not exercised**
by this leaf (no oracle-dependent reference-agreement number is reported —
see `reports/SXT-028h/EVIDENCE.md` §0).

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  (`oracle/manifest.json`).
- Structure authority (CITED, nothing copied):
  - `src/common/SurgeSynthesizer.cpp` `process()` — the per-scene INSERT
    block: scene B's own stereo bus (`sceneout[1][0]`, `sceneout[1][1]`)
    processed IN PLACE through its insert slots in slot order, with the
    scene's own ring/live flag (`sc_state[1]`) threaded forward through each
    slot's `process_ringout(L, R, indata) -> bool` return value; the per-slot
    "loaded" gate (`fx[fxslot_bins1] != nullptr`) and the `fx_disable`
    bitmask gate; `loadFx()` (per-slot reload → fresh instance),
    `enqueueFXOff()` (slot off), `reorderFx()` (slot-content permutation).
  - `src/common/SurgeStorage.h` — `fxslot_positions`
    (`fxslot_bins1 = 2`, `fxslot_bins2 = 3`), `fxb_*` bypass enum,
    `n_fx_slots = 16` (`fx_disable` bit width).
  - `src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h` —
    instance construction/suspend per slot (`fx[v] == nullptr` ⇔ slot
    unoccupied; modeled as `InsertSlotInstance.occupied`).
- **In-repo re-derivation of the slot indices** (no live oracle needed):
  `tools/export_normalized_graphs.py`'s `FX_ROLES` and every record of
  `corpus/normalized/graphs.jsonl` carry the pinned engine's slot order by
  patch `fx[]` index — role `bins1` at index 2, `bins2` at index 3. Asserted
  by `tests/test_sxt028h.py::test_slot_indices_agree_with_the_committed_corpus_role_table`.

## Bypass-mode partition (declared contract)

| stage | runs in `fx_bypass` modes | pinned by |
|---|---|---|
| **scene inserts (this leaf)** | `all_fx`, `no_sends`, `scene_fx_only` (skipped only in `no_fx`) | **declared here** — see the caveat below |
| global bus | `all_fx`, `no_sends` | landed sibling leaf `model/effects/rf-rf-global2/` |
| sends | `all_fx` | send-form leaves (`rf-send*`), not this leaf |

**Caveat (honest scope of the citation).** The environment that froze this
model had no oracle checkout, so the pinned `process()` text could not be
re-read here. The slot indices above ARE re-derived from a committed in-repo
artifact; the insert stage's bypass-mode set is the one structural fact stated
as this leaf's **declared contract** rather than as a verified read. It is
recorded as a named re-verification item in `reports/SXT-028h/EVIDENCE.md` §0
and is the complement of the sibling leaf's already-landed global set under
the same enum (`no_sends` removes sends only; `scene_fx_only` keeps exactly
this stage; `no_fx` removes everything).

## Form scope, not algorithm scope

This leaf's claim is the **scene-B insert bus wiring, the bins1 → bins2
slot-order schedule, `fx_bypass`/`fx_disable` gating, the per-slot instance
lifecycle, and per-instance-state isolation** of hosting two
concurrently-active insert instances on one scene bus — "algorithm behavior
stays with the per-algorithm leaves" (issue #60 scope note; `AGENTS.md`). The
per-slot occupant exercised here is a **synthetic TDF2 biquad primitive** (the
same Direct-Form-II-Transposed recurrence every landed leaf's biquad stage
already uses — Reverb1's instant-coefficient `biq_stage`, Delay/Chorus's
per-sample-lag `Biquad`, the sibling routing leaf's `BiquadInstance`), driven
by arbitrary control-plane coefficients, **not** derived from any concrete
Surge FX class's parameters. It exists only to give the routing claim a real,
per-instance-stateful, tail-bearing arithmetic path to verify
order-sensitivity, state isolation, lifecycle behavior and tail continuation
against.

**What this leaf does NOT claim**: no specific Surge FX algorithm's fidelity;
no preset-support claim; no musical-quality claim; no FPGA/gf180mcu synthesis,
timing or area claim; no model-vs-pinned-engine reference-agreement number
(the routing/scheduling metadata for the three named B4-scope carrier presets
IS verified — see `fx_inputs/rf-rf-bins12-*.json` — but the pinned oracle
build was unavailable in the environment that produced this record, so
per-slot algorithm-parameter extraction and any wet-audio reference render are
refused, not fabricated).

## Frozen word formats (this leaf)

| Domain | Format | Notes |
|---|---|---|
| scene-bus audio words | **Q10.21** signed 32-bit | matches the Delay/EQ/Chorus bus scale |
| biquad coefficients | **Q3.29** signed 32-bit | block-constant (instant); NO per-sample lag |
| biquad TDF2 accumulator | **80-bit signed** | Reverb1 `REG_LIM` precedent: headroom for adversarial negative-control coefficients without a stability argument |

Arithmetic rules (FROZEN, self-contained in `rf_bins12_model.py` — mirrors
`model/effects/qmath.py`'s round-half-up/saturating conventions without
mutating its shared format registry; `reverb1_fixed.py` and
`rf_global2_model.py` precedent for a leaf-local kernel): exact products,
round-half-up `(p + 2**(s−1)) >> s`, saturating; no floating point at audio
run time.

The file is deliberately **self-contained** (it does not import the sibling
routing leaf's kernel): `model_revision()` is the sha256 of this exact file
and is the pin consumed by the RTL comparator and the stale-harness negative
control, so a sibling leaf's future edit can never change this leaf's frozen
behavior without changing this leaf's own pin.

## Schedule (mirrors `SurgeSynthesizer::process()`'s per-scene insert block, scene B)

```
apply_control(...)                      # control-rate, runs in EVERY bypass mode
if fx_bypass != NO_FX:                  # {ALL_FX, NO_SENDS, SCENE_FX_ONLY}
    sc = sc_in                          # scene-B live/ringing flag (OUT of scope upstream)
    for (slot, bit) in (bins1, 2), (bins2, 3):
        if slot.occupied and not fx_disable_bit(bit):
            (bus, sc) = slot.process_ringout(bus, sc)
else:
    bus unchanged; the ring flag passes through untouched
```

`process_ringout(l, r, indata)`: while `indata` is true, process every sample
in place and report ringing == true; otherwise pass the bus through untouched
and report not-ringing. The occupant declares no ring-out *policy* of its own
(algorithm-leaf scope), but its **arithmetic tail** — nonzero output after the
input goes silent, straight out of the TDF2 registers — is real and is what
the tail acceptance case (`tail-span-silent-input`) and the dropped-tail
negative control exercise.

## Instance lifecycle (frozen; identical in model and RTL)

| control | engine counterpart | effect |
|---|---|---|
| `occupied` false | `enqueueFXOff()` / instance released | that slot's registers cleared, stage no-ops |
| `occupied` rising, or `reload` pulse | `loadFx()` → fresh instance | **that slot only**: registers cleared, new coefficients adopted; the sibling slot's history and the scene ring flag are untouched (a patch change mid-tail does not silence the other slot's tail) |
| `occupied` steady, no `reload` | parameter change | coefficients adopted, state kept (abrupt — per-parameter smoothing is algorithm-leaf scope) |
| `panic_reset()` / RTL `state_reset` | all-notes-off / suspend | both instances cleared, ring memory dropped; the loaded patch (occupancy) is NOT changed |

## Per-instance state

One `InsertSlotInstance` holds one `BiquadInstance` (4 accumulator words:
`reg0`/`reg1` × {L, R}) plus its own `occupied` flag. The two configured
insert slots (`SceneBInsertBus.slot1` = bins1, `.slot2` = bins2) are two
disjoint objects — no accumulator state is ever shared between them, even
though both run through the SAME arithmetic kernel class
(`BiquadInstance.process_sample`): shared arithmetic, independent state
(`AGENTS.md`; issue #60 "Per-instance state" acceptance item). Negative
control NC-D (`tools/rf_bins12_negative_controls.py`) demonstrates a
pooled-state mutant failing the dual-instance check, model-side AND as a live
RTL mutant (`rtl/effects/rf-rf-bins12/rf_bins12_mutants.sv
-DNC_SHARED_STATE`).

## Declared control-plane boundary (model → RTL)

Per block: `fx_bypass` (2-bit mode), `fx_disable` (16-bit mask, engine bit
layout; only bits 2/3 consumed), per slot `occupied` + `reload` + 5 biquad
coefficients (Q3.29), and the upstream `sc_in` scene-B live/ringing flag (OUT
of this leaf's scope — voice/scene activity belongs to the voice-stage leaves;
supplied here as synthetic per-block stimulus). The RTL computes everything
audio-rate: the TDF2 recurrence, the bypass/disable gate, the lifecycle edge
detection and the series ring-out threading.

## Declared scope omissions (fail-closed)

- `bins3`/`bins4`, the scene-A insert bus (`rf-ains*`), the send buses and
  `return_level` / per-scene `send_level` smoothing (`rf-send*` leaves), and
  the global bus (`rf-global*`, landed as `rf-rf-global2`). This leaf models
  exactly the pinned-source `roles: [bins1, bins2]` scope. `return_level` is
  recorded per carrier slot in `fx_inputs/*.json` but is explicitly **not
  consumed** here.
- The scene-B bus's downstream summation into the master bus, and the
  scene-mode logic deciding whether scene B is instantiated at all (Single vs
  Dual/Key Split/Channel Split) — recorded per carrier as
  `scene_context.scene_b_instantiated`, not modeled.
- Per-sample coefficient smoothing/ramping into the occupant (algorithm-leaf
  scope).
- Any concrete Surge FX algorithm's own ring-out decision policy or tail
  generation — see "Form scope" above.
- Per-slot algorithm parameter values and any wet-audio reference render —
  requires the pinned oracle build (surgepy), unavailable in the environment
  that produced this record; refused, not fabricated
  (`tools/extract_rf_bins12_inputs.py`,
  `reports/SXT-028h/artifacts/extract-refusals.txt`).

## Files

- `rf_bins12_model.py` — the frozen model (`SceneBInsertBus`,
  `InsertSlotInstance`, `BiquadInstance`; `model_revision()` frozen-revision
  pin consumed by the RTL comparator — a stale harness refuses to report PASS)

## Reproduce

```sh
python3 tools/extract_rf_bins12_inputs.py                 # carrier metadata (census+graphs, zero-drift asserted; oracle attempt honestly refused if unbuilt)
python3 tools/compare_rtl_model_rf_bins12.py              # RTL-vs-model exactness (iverilog)
python3 tools/rf_bins12_negative_controls.py              # 5 required negative controls (model + live RTL mutants)
python3 -m pytest tests/test_sxt028h.py -q
```
