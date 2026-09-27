# SXT-028d frozen fixed-point model — routing form: Global FX slot 2 (`model/effects/rf-rf-global2/`)

Frozen reference for the SXT-028d RTL (`rtl/effects/rf-rf-global2/`). The RTL
must match this model **exactly** (integer equality of every output sample
and every per-instance checkpoint; `tools/compare_rtl_model_rf_global2.py`).
Model-vs-pinned-engine agreement is a SEPARATE claim; see "What this leaf
does NOT claim" below — it is **not exercised** by this leaf (no oracle-
dependent reference-agreement number is reported here; see
`reports/SXT-028d/EVIDENCE.md`).

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  (`oracle/manifest.json`).
- Structure authority (READ + cited; nothing copied):
  - `src/common/SurgeSynthesizer.cpp` `process()` — the "apply global
    effects" block: `fx_bypass` gating (`fxb_all_fx`/`fxb_no_sends` apply;
    `fxb_scene_fx_only`/`fxb_no_fx` skip), the `fx_disable` per-slot
    bitmask gate, and the in-place SERIES chaining
    `glob = fx[v]->process_ringout(output[0], output[1], glob)` across
    `{fxslot_global1, fxslot_global2, fxslot_global3, fxslot_global4}`
    (this leaf models exactly the `global1`→`global2` segment named by its
    `roles: [global2]` scope).
  - `src/common/SurgeStorage.h` — `fxslot_positions` (`fxslot_global1 = 6`,
    `fxslot_global2 = 7`), `fxb_*` bypass enum, `n_fx_slots = 16`
    (`fx_disable` bit width).
  - `src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h` —
    instance construction/suspend per slot (`fx[v] == nullptr` ⇔ slot
    unoccupied; modeled as `GlobalSlotInstance.occupied`).

## Form scope, not algorithm scope

This leaf's claim is the **routing/bus wiring, slot-order scheduling,
`fx_bypass`/`fx_disable` gating, and per-instance-state isolation** of
hosting two concurrently-active global-FX slot instances on the master
output bus — "algorithm behavior stays with the per-algorithm leaves" (issue
#56 scope note; `AGENTS.md`). The per-slot occupant exercised here is a
**synthetic TDF2 biquad primitive** (the same Direct-Form-II-Transposed
recurrence every landed leaf's biquad stage already uses — Reverb1's
instant-coefficient `biq_stage`, Delay/Chorus's per-sample-lag `Biquad`),
driven by arbitrary control-plane coefficients, **not** derived from any
concrete Surge FX class's parameters. It exists only to give the routing
claim a real, per-instance-stateful arithmetic path to verify order-
sensitivity, state isolation, and ring-out propagation against.

**What this leaf does NOT claim**: no specific Surge FX algorithm's
fidelity; no preset-support claim; no model-vs-pinned-engine reference-
agreement number (the routing/scheduling metadata for the three named B4-
scope carrier presets IS verified — see `fx_inputs/rf-rf-global2-*.json` —
but the pinned oracle build was unavailable in the environment that produced
this record, so per-slot algorithm-parameter extraction and any wet-audio
reference render are refused, not fabricated; `reports/SXT-028d/EVIDENCE.md`
records this as a named, bounded gap, per builder.md's "Long compute has
three sanctioned answers").

## Frozen word formats (this leaf)

| Domain | Format | Notes |
|---|---|---|
| master bus audio words | **Q10.21** signed 32-bit | matches the Delay/EQ/Chorus bus scale |
| biquad coefficients | **Q3.29** signed 32-bit | block-constant (instant); NO per-sample lag |
| biquad TDF2 accumulator | **80-bit signed** | Reverb1 `REG_LIM` precedent: headroom for adversarial negative-control coefficients without a stability argument |

Arithmetic rules (FROZEN, self-contained in `rf_global2_model.py` — mirrors
`model/effects/qmath.py`'s round-half-up/saturating conventions without
mutating its shared format registry; `reverb1_fixed.py` precedent for a
leaf-local kernel): exact products, round-half-up
`(p + 2**(s-1)) >> s`, saturating; no floating point at audio run time.

## Schedule (mirrors `SurgeSynthesizer::process()`'s "apply global effects" block)

```
if fx_bypass in {ALL_FX, NO_SENDS}:
    glob = glob_in                      # upstream ring/live flag (OUT of scope: scene/send routing)
    for (slot, bit) in (slot1, GLOBAL1), (slot2, GLOBAL2):
        if slot.occupied and not fx_disable_bit(bit):
            (bus, glob) = slot.process_ringout(bus, glob)
else:
    bus unchanged; ring state NOT touched
```

`process_ringout(l, r, indata)`: while `indata` is true, process every
sample and report ringing == true (this occupant declares **no extended
tail** of its own — a tail-bearing occupant's own ring decision is algorithm-
leaf scope); otherwise pass the bus through untouched and report
not-ringing.

## Per-instance state

One `GlobalSlotInstance` holds one `BiquadInstance` (4 accumulator words:
`reg0`/`reg1` × {L, R}) plus its own `occupied` flag. Two configured global
slots (`RoutingState.slot1`, `RoutingState.slot2`) are two disjoint
`GlobalSlotInstance` objects — no accumulator state is ever shared between
them, even though both run through the SAME arithmetic kernel class
(`BiquadInstance.process_sample`): shared arithmetic, independent state
(`AGENTS.md`; issue #56 "Per-instance state" acceptance item; negative
control NC-D in `tools/rf_global2_negative_controls.py` demonstrates a
pooled-state mutant failing the dual-instance-independence check).

## Declared control-plane boundary (model → RTL)

Per block: `fx_bypass` (2-bit mode), `fx_disable` (16-bit mask, engine bit
layout), each slot's `occupied` flag and 5 biquad coefficients (Q3.29), and
the upstream `glob_in` ring/live flag (OUT of this leaf's scope — scene/send
routing is other `rf-*` leaves' scope; supplied here as synthetic per-block
stimulus). The RTL computes everything audio-rate: the TDF2 recurrence, the
bypass/disable gate, and the series ring-out threading.

## Declared scope omissions (fail-closed)

- `global3`/`global4` (SXT-028's `rf-global34` leaf) — this leaf models
  exactly the pinned-source `roles: [global2]` scope.
- Per-sample coefficient smoothing/ramping into the occupant (algorithm-leaf
  scope).
- Any concrete Surge FX algorithm's own tail generation — see "Form scope"
  above.
- Per-slot algorithm parameter values and any wet-audio reference render —
  requires the pinned oracle build (surgepy), unavailable in the environment
  that produced this record; refused, not fabricated
  (`tools/extract_rf_global2_inputs.py`, `reports/SXT-028d/artifacts/
  extract-refusals.txt`).

## Files

- `rf_global2_model.py` — the frozen model (`RoutingState`, `GlobalSlotInstance`,
  `BiquadInstance`; `model_revision()` frozen-revision pin consumed by the
  RTL comparator — a stale harness refuses to report PASS)

## Reproduce

```sh
python3 tools/extract_rf_global2_inputs.py                    # carrier metadata (census+graphs; oracle attempt honestly refused if unbuilt)
python3 tools/compare_rtl_model_rf_global2.py                  # RTL-vs-model exactness (iverilog)
python3 tools/rf_global2_negative_controls.py                  # 5 required negative controls (model-side)
```
