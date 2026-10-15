# SXT-028d evidence record — routing form: Global FX slot 2 (second
concurrent global-FX instance): frozen model, exact RTL, per-instance
state, oracle-dependent legs BLOCKED (named compute gap)

Branch: `feature/issue-56` · Issue: #56 (SXT-028d) · Parent: #21 (SXT-028)

Engine (external, GPL-3.0-or-later, pinned but not exercised by this leaf
beyond the census/graphs cross-check): `surge-synthesizer/surge@
58914e59c608ed4384ba6002e44c3465c58b2e71` (`oracle/manifest.json`).
Structure authority: `src/common/SurgeSynthesizer.cpp` `process()` "apply
global effects" block, `src/common/SurgeStorage.h` `fxslot_positions`/`fxb_*`,
`src/common/dsp/effects/SurgeSSTFXAdapter.h` + `SurgeEffect.h`.

**Claim discipline.** This record advances exactly one claim: *the RTL
matches the frozen fixed-point routing/scheduling model exactly*
(iverilog; demonstrated below). It establishes **no** model-vs-pinned-
engine reference-agreement number, **no** preset-support claim, **no**
musical-quality claim (no human listening), **no** FPGA/gf180mcu synthesis,
timing, area, or hardware-playback claim. The per-slot occupant used to
exercise the routing arithmetic is a synthetic TDF2 biquad, not any
concrete Surge FX algorithm — see `model/effects/rf-rf-global2/README.md`
"Form scope, not algorithm scope". No generic substitute is used under any
support claim; NC-A proves one is bit-exactly distinguishable from the
declared per-instance occupant.

## 0. Named compute gap: oracle-dependent legs BLOCKED

The pinned Surge XT engine's `surgepy` Python binding requires a full
C++/JUCE build (`oracle/fetch-and-build.sh`); that build was not available
in the environment that produced this record (dispatch worker, no host-side
oracle checkout; `oracle/manifest.json`'s pinned build path is a macOS
path). Per builder.md's "Long compute has three sanctioned answers", this is
recorded here as a named, bounded gap rather than attempted as an
unbounded local build or silently skipped:

- **What IS verified without the oracle** (this record, in full): the
  frozen model itself; RTL-vs-model exactness (10 cases, §2); all 5
  required negative controls (§3); the three named B4-scope carrier
  presets' routing/scheduling metadata — slot occupancy, FX type name,
  `fx_bypass`/`fx_disable` — re-derived from the ALREADY-committed,
  ALREADY-surgepy-derived `corpus/census-v0.1` and
  `corpus/normalized/graphs.jsonl` (SXT-011 outputs; no live oracle call
  needed for this step) (§4).
- **What is BLOCKED**: any per-slot algorithm-parameter extraction, any
  wet-audio reference render, and therefore any model-vs-pinned-engine
  reference-agreement number for this leaf's fixtures
  (`tools/extract_rf_global2_inputs.py`'s `oracle_extraction.ok` is
  `false` for all three carriers, recorded verbatim in
  `model/effects/fx_inputs/rf-rf-global2-*.json`, never fabricated).
- **Reference budgets** [PROPOSED, not frozen] are therefore **NOT_RUN**
  for this leaf, not PASS and not FAIL. Freeze in any case is gated on
  SXT-017 (#12) per the issue's own Acceptance section.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (10 cases) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **NOT_RUN** (oracle unavailable; §0) | — |
| Negative controls live | **5/5 CONTROL-OK** | `negative-controls/negative-controls.json` |
| Per-instance state (dual-slot) | **PASS** (model-level NC-D + RTL cases w/ both slots occupied) | `negative-controls.json`, `rtl-exactness.json` |
| Carrier routing/scheduling metadata | **PASS** (3/3, census+graphs cross-checked) | `model/effects/fx_inputs/rf-rf-global2-*.json` |
| Complete-wet preset renders | **NOT_RUN** (oracle unavailable) | §0 |
| External-memory traffic | **PASS** (this leaf's own contribution: 0 words/sample; aggregate PENDING-SXT-016) | `artifacts/state-cost.json` |
| Newly-enabled presets | **0** (no support claim follows from this record) | this record |

## 1. Frozen model

`model/effects/rf-rf-global2/rf_global2_model.py` + `README.md`. Models the
"apply global effects" schedule exactly: `fx_bypass` gate (ALL_FX/NO_SENDS
apply; SCENE_FX_ONLY/NO_FX skip), the `fx_disable` per-slot bitmask gate
(engine bit layout, bits 6/7), and the in-place SERIES chaining of
`process_ringout` across two `GlobalSlotInstance` objects (slot1/global1,
slot2/global2), each owning one independent `BiquadInstance` (TDF2, Q3.29
coefficients, 80-bit accumulator). `model_revision()` pins the frozen file's
sha256 for the stale-stub control (§3, NC-E) and is echoed by the RTL
comparator (`rtl-exactness.json`).

## 2. RTL-vs-model exactness

`rtl/effects/rf-rf-global2/{rf_global2_core.sv, tb_rf_global2.sv}`,
compared via `tools/compare_rtl_model_rf_global2.py` (iverilog; INTEGER
EQUALITY of every output sample and every per-instance checkpoint — both
slots' TDF2 registers plus the ring-out flag). 10 declared cases, 6 blocks
each (384 output samples + 6 checkpoints per case):

| Case | Exercises |
|---|---|
| `both-slots-all-fx` | baseline: both slots occupied, `fx_bypass = ALL_FX` |
| `both-slots-no-sends` | `fx_bypass = NO_SENDS` (also applies, per source) |
| `bypass-scene-fx-only-skips-block` | `fx_bypass = SCENE_FX_ONLY` (bus passes through unmodified) |
| `bypass-no-fx-skips-block` | `fx_bypass = NO_FX` (bus passes through unmodified) |
| `slot1-disabled-bit6` | `fx_disable` bit 6 set: slot1 skipped, slot2 still runs |
| `slot2-disabled-bit7` | `fx_disable` bit 7 set: slot2 skipped, slot1 still runs |
| `slot1-unoccupied-single-instance` | slot1 `occupied = false` (matches the `Rounded.fxp` carrier's single-instance shape) |
| `glob-never-true-passthrough` | `glob_in = false` throughout: neither slot ever processes |
| `glob-goes-false-mid-run` | `glob_in` transitions true→false across blocks (ring-out cutoff) |
| `mid-run-state-reset` | `state_reset` pulse before block 3: both slots' registers clear |

**Result: 10/10 exact, 0 mismatches, 3,840 output samples + 60 checkpoint
fields compared.** Full record: `rtl-exactness.json` (`status: "PASS"`).

**Bug found and fixed during this leaf's own construction** (documented
here per the project's evidence-retention norm, not swept under a passing
result): the first RTL draft called the 32-bit-SATURATING `rndsat32` helper
for the TDF2 feedback term inside the register recurrence (`nr0`/`nr1`),
which is correct only for reducing an already-accumulator-scale value down
to the final `s32` audio output (as Reverb1's own `wet_l`/`wet_r`/mix stage
does) — used on the *feedback* term it silently truncated the ~2^50-scale
accumulator to 32 bits, corrupting every register after the first sample
whenever both slots were driven with real (non-degenerate) coefficients and
more than one nonzero sample. A dedicated wide (144-bit, non-saturating)
`rndshift` helper was added for the accumulator-scale reduction, mirroring
Reverb1's own inline (non-`rndsat32`) shift for its `bregs` recurrence; the
comparator's own multi-sample, both-slots-occupied cases caught it
immediately (single-impulse and single-slot cases had passed spuriously by
coincidence — the affected filter happened to decay back near zero by the
end of a still-mostly-zero block regardless of the bug). No case in
`rtl-exactness.json` above reflects the buggy version; the file was
regenerated after the fix.

## 3. Negative controls (all 5 required; `tools/rf_global2_negative_controls.py`)

| Control | Targets | Verdict |
|---|---|---|
| NC-A generic substitute | per-instance-state faithfulness | CONTROL-OK — a pass-through+fixed-gain stand-in FAILS bit-exact reproduction |
| NC-B dropped tail | declared ring-out span coverage | CONTROL-OK — a render truncated to half the declared span FAILS the coverage/checkpoint check |
| NC-C wrong order | order-sensitive series composition | CONTROL-OK — swapping the global1/global2 coefficient assignment changes the output |
| NC-D shared state | dual-instance independence | CONTROL-OK — pooling both slots into one `BiquadInstance` diverges from the correctly-isolated reference |
| NC-E stale stub | frozen-revision pin | CONTROL-OK — a corrupted revision word is refused, never reported PASS |

**5/5 CONTROL-OK** (a control that passes would be a broken control, per
issue #56's own framing). Full record:
`negative-controls/negative-controls.json` (`status: "PASS"`).

## 4. Carrier routing/scheduling metadata (oracle-independent)

`tools/extract_rf_global2_inputs.py` re-verifies the census blob sha1
(`corpus/census-v0.1/results/per-preset.csv`) and cross-checks
`corpus/normalized/graphs.jsonl` (already surgepy-derived and committed;
SXT-011) for the three B4-scope carriers named in the issue text:

| Preset | global1 | global2 | `fx_bypass` | `fx_disable` | Dual-instance concurrent? |
|---|---|---|---|---|---|
| `Ancient FM.fxp` | Airwindows (on) | Chorus (on) | All FX | 0 | **yes** |
| `Piercing.fxp` | Chorus (on) | Conditioner (on) | All FX | 0 | **yes** |
| `Rounded.fxp` | Off | Airwindows (on) | All FX | 0 | no (single-instance) |

3/3 census blob + graphs cross-checks PASS (0 refusals;
`artifacts/extract-refusals.txt` empty). `Ancient FM.fxp` and `Piercing.fxp`
both genuinely exercise the two-concurrent-global-slot routing shape this
leaf claims; `Rounded.fxp` exercises the complementary single-occupied-slot
shape (covered by RTL case `slot1-unoccupied-single-instance`). Per-slot
algorithm parameter values are NOT extracted (§0 — oracle unavailable); the
JSON records `oracle_extraction.ok: false` with the reason, never a
fabricated value.

## 5. External-memory traffic

`artifacts/state-cost.json`: this leaf's own contribution (the routing/
scheduling wiring plus its synthetic register-only occupant kernel) is 0
external-memory words/sample. The AGGREGATE estimate for a concrete preset
also depends on whichever algorithm leaf's occupant actually lands in
global1/global2 (Delay/Reverb1/Chorus/Conditioner/Airwindows/etc.), which
is that leaf's own SXT-015/016 accounting, not invented here —
`[PENDING-SXT-016]` per the issue text.

## 6. Newly enabled presets

**0.** This record establishes no preset-support claim (§0); the issue's
own `newly_enabled` accounting (`reports/sxt-028/leaves/SXT-028d/
newly-enabled.json`, FX-scope-only, explicitly "NOT a support claim") is
unaffected by this leaf landing.

## 7. Same-shape drift-0 carrier screen (#425, part of #331)

Live on the pinned oracle (`reports/SXT-028d/artifacts/carrier-drift-screen.json`,
produced by `tools/screen_rf_global2_carriers.py` on the #423 helper;
manifest-pinned prebuilt artifact `d2cc7029...f571`, Surge
`58914e59c608ed4384ba6002e44c3465c58b2e71`, CPython 3.11.16, 48 kHz; engine
provenance verified before any `loadPatch`). Nothing was rendered.

Shape predicates (declared before screening; each original satisfies its own;
FX class is NOT part of the shape): global1/global2 occupancy as below,
`fx_bypass == All FX`, `fx_disable == 0`, Single scene mode, scene A active.

| Original | Shape | Candidates enumerated / screened / refused | Drift PASS / FAIL | Original re-measured | Selected addition (rule in the record) |
|---|---|---|---|---|---|
| `Ancient FM.fxp` | g1 on, g2 on | 490 / 490 / 0 | 370 / 120 | A = 0.092024997 -> FAIL, non-render-eligible | `Altenberg/Pads/Dark Pulse.fxp` |
| `Rounded.fxp` | g1 off, g2 on | 86 / 86 / 0 | 45 / 41 | A = 0.152826995 -> FAIL, non-render-eligible | `Cybersoda/Keys/Noisy.fxp` |

Coverage (screened/denominator) is reported separately from the drift verdict;
the per-shape `drift_gate_status` is FAIL because originals (and many
candidates) fail, which is the finding, not an error. The reproduced original
failures match the historical SXT-028l numbers but are fresh measurements.
Selected candidates are labeled additions, ranked by rule (original's global
slot FX types matched, then corpus path); the originals stay in the record as
non-render-eligible. `Piercing.fxp` is unaffected (drift 0) and stays declared.
The extractor (`tools/extract_rf_global2_inputs.py`) now runs the same per-scene
drift gate live per declared carrier and records `render_eligibility` in
`model/effects/fx_inputs/rf-rf-global2-*.json`; without the oracle it reports
NOT_RUN and preserves a prior committed live record.

What this does NOT establish: drift 0 is necessary, never sufficient (other
engine RNG paths, #310, only an empirical repeated render catches); no wet
fidelity, preset support, audio repeatability, RTL exactness, or musical
usefulness follows; the selected additions have not been rendered (the render
leg stays gated by #12 and its own gates). `oracle_extraction.ok: true` in the
fx_inputs means only that surgepy was importable; per-slot parameter
extraction remains algorithm-leaf scope and was not exercised.

## Reproduce

```sh
python3 tools/extract_rf_global2_inputs.py
python3 tools/compare_rtl_model_rf_global2.py --out reports/SXT-028d/rtl-exactness.json
python3 tools/rf_global2_negative_controls.py
# under the pinned oracle interpreter (oracle/README.md "Prebuilt oracle"):
$ORACLE_PYTHON tools/screen_rf_global2_carriers.py
python3 -m pytest tests/test_sxt028d.py -q
```
