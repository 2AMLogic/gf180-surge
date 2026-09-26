# SXT-028j frozen fixed-point model — routing form: Global FX slots 3-4 (`model/effects/rf-rf-global34/`)

Frozen reference for the SXT-028j RTL (`rtl/effects/rf-rf-global34/`). The
RTL must match this model **exactly** (integer equality of every output
sample and every per-instance checkpoint;
`tools/compare_rtl_model_rf_global34.py`). Model-vs-pinned-engine agreement
is a SEPARATE claim and is **not exercised** by this leaf — no
oracle-dependent reference-agreement number is reported here; see
`reports/SXT-028j/EVIDENCE.md` §0.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  (`oracle/manifest.json`).
- Structure authority (cited, nothing copied):
  - `src/common/SurgeSynthesizer.cpp` `process()` — the "apply global
    effects" block: the summed master bus processed **in place** through
    `{fxslot_global1, fxslot_global2, fxslot_global3, fxslot_global4}` in
    slot order, with the ring/live flag threaded forward through each slot's
    `process_ringout(L, R, indata) -> bool` return value, under the
    `fx_bypass` gate and the `fx_disable` per-slot bitmask gate; instance
    lifecycle via `loadFx()` / `enqueueFXOff()` / `reorderFx()`.
  - `src/common/SurgeStorage.h` — `fxslot_positions` (**global3 = 14,
    global4 = 15**), the `fxb_*` bypass enum, `n_fx_slots = 16`.
  - `src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h` —
    instance construction/suspend per slot (`fx[v] == nullptr` ⇔ slot
    unoccupied; modeled as `GlobalSlotInstance.occupied`).
- **In-repo re-derivation of the slot indices** (no live oracle needed):
  every one of the 3,561 records in `corpus/normalized/graphs.jsonl` carries
  the pinned engine's slot order by patch `fx[]` index — role `global3` at
  index 14, `global4` at index 15. Asserted by
  `tests/test_sxt028j.py::test_slot_indices_agree_with_the_committed_corpus_role_table`
  and re-checked per carrier by `tools/extract_rf_global34_inputs.py`
  (`slot_index_check`, a refusal on disagreement).

## Where this segment sits in the chain (declared seam)

`global3`/`global4` are the **last two** slots of the four-slot global
chain, so the bus samples and the ring flag arriving at `global3` are
whatever the `global1 → global2` segment left. That segment is the
already-landed sibling leaf `model/effects/rf-rf-global2/` (SXT-028d,
issue #56) and is **not** re-claimed here: this leaf takes the upstream bus
and `glob_in` as inputs.

```
master bus ──▶ [global1] ──▶ [global2] ──▶ [global3] ──▶ [global4] ──▶ out
               └── rf-rf-global2 (landed) ┘ └── THIS LEAF (rf-rf-global34) ┘
                        glob flag threaded left → right
```

`tests/test_sxt028j.py::test_seam_composes_with_the_landed_global12_segment`
composes the two landed models into the full four-slot chain and checks that
all **four** slot instances keep independent histories.

## Form scope, not algorithm scope

This leaf's claim is the **routing/bus wiring, slot-order scheduling,
`fx_bypass`/`fx_disable` gating, per-slot instance lifecycle, and
per-instance-state isolation** of hosting two concurrently-active global-FX
instances on the master bus — "algorithm behavior stays with the
per-algorithm leaves" (issue #62 scope note; `AGENTS.md`). The per-slot
occupant exercised here is a **synthetic TDF2 biquad primitive** (the same
Direct-Form-II-Transposed recurrence every landed leaf's biquad stage
already uses — Reverb1's instant-coefficient `biq_stage`, Delay/Chorus's
per-sample-lag `Biquad`, the sibling routing leaves' `BiquadInstance`),
driven by arbitrary control-plane coefficients, **not** derived from any
concrete Surge FX class's parameters. It exists only to give the routing
claim a real, per-instance-stateful, tail-bearing arithmetic path to verify
order-sensitivity, state isolation, lifecycle behavior and tail continuation
against.

**What this leaf does NOT claim**: no specific Surge FX algorithm's
fidelity; no preset-support claim; no musical-quality claim; no
model-vs-pinned-engine reference-agreement number (the routing/scheduling
metadata for five corpus carriers IS verified — see
`fx_inputs/rf-rf-global34-*.json` — but the pinned oracle build was
unavailable in the environment that produced this record, so per-slot
algorithm-parameter extraction and every wet-audio reference render are
refused, not fabricated; `reports/SXT-028j/EVIDENCE.md` records this as a
named, bounded gap).

## Frozen word formats (this leaf)

| Domain | Format | Notes |
|---|---|---|
| master-bus audio words | **Q10.21** signed 32-bit | matches the Delay/EQ/Chorus bus scale |
| biquad coefficients | **Q3.29** signed 32-bit | block-constant (instant); NO per-sample lag |
| biquad TDF2 accumulator | **80-bit signed** | Reverb1 `REG_LIM` precedent: headroom for adversarial negative-control coefficients without a stability argument |

Arithmetic rules (FROZEN, self-contained in `rf_global34_model.py` — mirrors
`model/effects/qmath.py`'s round-half-up/saturating conventions without
mutating its shared format registry): exact products, round-half-up
`(p + 2**(s-1)) >> s`, saturating; no floating point at audio run time.

The file is deliberately self-contained and imports no sibling leaf's
kernel: `model_revision()` (sha256 of the file) is the frozen-revision pin
consumed by the RTL comparator and the stale-harness negative control, so a
sibling leaf's future edit can never change this leaf's frozen behavior
without changing this leaf's own pin.

## Schedule (the tail half of `process()`'s "apply global effects" block)

```
control-rate pass (runs in EVERY bypass mode — the engine's load/unload path
                   is control-rate):
    apply the instance-lifecycle rule to global3 and global4 (below)

audio pass:
if fx_bypass in {ALL_FX, NO_SENDS}:
    glob = glob_in                      # as the global1→global2 segment left it
    for (slot, bit) in (global3, 14), (global4, 15):
        if slot.occupied and not fx_disable_bit(bit):
            (bus, glob) = slot.process_ringout(bus, glob)
else:                                   # SCENE_FX_ONLY, NO_FX
    bus unchanged; the ring flag passes through untouched
```

`process_ringout(l, r, indata)`: while `indata` is true, process every
sample in place and report ringing == true; otherwise pass the bus through
untouched and report not-ringing. This occupant declares **no ring-out
policy of its own** (a tail-bearing occupant's own policy is algorithm-leaf
scope); its **arithmetic** tail — nonzero output after the input goes
silent, straight out of the TDF2 registers — is real and is exactly what the
tail acceptance case and the dropped-tail negative control exercise.

### Bypass-mode partition (inherited, not re-derived here)

The GLOBAL stage runs in `fxb_all_fx` and `fxb_no_sends` only. That set is
taken from the landed sibling GLOBAL leaf
`model/effects/rf-rf-global2/rf_global2_model.py`, which pinned it while
citing the same `process()` block; it is the complement of the INSERT set
(`{all_fx, no_sends, scene_fx_only}`) pinned by
`model/effects/rf-rf-bins12/rf_bins12_model.py`. The pinned source itself
could not be re-read in the environment that froze this model (no oracle
checkout), so this is recorded as a named re-verification item in
`reports/SXT-028j/EVIDENCE.md` §0b rather than presented as a fresh verified
read.

## Instance lifecycle (frozen; identical in model and RTL)

| Control | Effect |
|---|---|
| `occupied` false | instance released (`enqueueFXOff()`): that slot's registers cleared, stage no-ops |
| `occupied` rising, or `reload` pulse | FRESH instance (`loadFx()`): **that slot only** is cleared, new coefficients adopted; the sibling slot's history and the ring flag are untouched |
| `occupied` steady, no `reload` | coefficients adopted **without** clearing state (abrupt parameter change; per-parameter smoothing is algorithm-leaf scope) |
| `panic_reset()` / RTL `state_reset` | both instances cleared and the rack's ring memory dropped; occupancy (the loaded patch) unchanged |

The exact queue-drain timing of the engine's own `enqueueFXOff()` is **not**
verified here (no oracle checkout): this leaf's lifecycle applies slot-off at
the control-rate pass preceding a block, which is a **declared contract** of
the model (matched exactly by the RTL), recorded as such in the EVIDENCE
record's re-verification list.

## Per-instance state

One `GlobalSlotInstance` holds one `BiquadInstance` (4 accumulator words:
`reg0`/`reg1` × {L, R}) plus its own `occupied` flag. The two configured
extended-rack slots (`ExtendedGlobalRack.slot3`, `.slot4`) are two disjoint
`GlobalSlotInstance` objects — no accumulator state is ever shared between
them, even though both run through the SAME arithmetic kernel class
(`BiquadInstance.process_sample`): shared arithmetic, independent state
(`AGENTS.md`; issue #62 "Per-instance state" acceptance item).

This is checked in the case that matters most: the corpus really does host
**the same FX class in both slots** — `John Valentine/Strings/String
Contrabass.fxp` carries Airwindows *Galactic* (sub-algorithm 49) in
`global3` **and** `global4`. Identical arithmetic is exactly where a pooled
implementation hides best, so the RTL case `same-class-dual-occupants` and
the NC-D same-class legs run the controls there too.

## Declared control-plane boundary (model → RTL)

Per block: `fx_bypass` (2-bit mode), `fx_disable` (16-bit mask, engine bit
layout; only bits 14/15 consumed), and per slot `occupied`, `reload` (a
patch-change pulse) and 5 biquad coefficients (Q3.29). The upstream ring/live
flag `glob_in` is supplied as per-block stimulus (computing it is out of
scope — it originates in `sc_state[0] || sc_state[1] || any(sendused)` and is
then modified by the upstream global slots). The RTL computes everything
audio-rate: the TDF2 recurrence, the bypass/disable gates, the lifecycle
clears and the series ring threading.

## Declared scope omissions (fail-closed)

- The `global1 → global2` segment itself (landed sibling leaf
  `model/effects/rf-rf-global2/`), the scene insert buses (`rf-ains*` /
  `rf-bins*`) and the send buses with their `return_level` / per-scene
  `send_level` smoothing (`rf-send*` leaves).
- The master bus's own upstream summation and everything downstream of the
  global chain.
- Per-sample coefficient smoothing/ramping into the occupant
  (algorithm-leaf scope).
- Any concrete Surge FX algorithm's own ring-out **decision** — see
  "Schedule" above.
- The engine-side queue-drain timing of `enqueueFXOff()` — see "Instance
  lifecycle" above.
- Per-slot algorithm parameter values and any wet-audio reference render —
  requires the pinned oracle build (surgepy), unavailable in the environment
  that produced this record; refused, not fabricated
  (`reports/SXT-028j/artifacts/{oracle-status,render-refusals}.*`).

## Files

- `rf_global34_model.py` — the frozen model (`ExtendedGlobalRack`,
  `GlobalSlotInstance`, `BiquadInstance`; `model_revision()` frozen-revision
  pin consumed by the RTL comparator — a stale harness refuses to report
  PASS).

## Reproduce

```sh
python3 tools/extract_rf_global34_inputs.py                                    # carrier metadata + corpus occupancy scan
python3 tools/rf_global34_oracle_status.py                                     # measured oracle probe (NOT_RUN legs)
python3 tools/rf_global34_state_cost.py                                        # derived state/cost inventory
python3 tools/compare_rtl_model_rf_global34.py --out reports/SXT-028j/rtl-exactness.json
python3 tools/rf_global34_negative_controls.py                                 # 5 required negative controls
python3 -m pytest tests/test_sxt028j.py -q
```
