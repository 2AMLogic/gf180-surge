# SXT-028b frozen fixed-point model — Conditioner (`model/effects/type-conditioner/`)

Frozen reference for the SXT-028b RTL (`rtl/effects/type-conditioner/`).
The RTL must match this model **exactly** (integer equality on every output
sample and every declared checkpoint; `tools/compare_rtl_model_conditioner.py`).
Agreement with the pinned Surge engine is a **separate** claim under
[PROPOSED], unfrozen budgets. It is **BLOCKED** on the authoring host because
no oracle checkout or surgepy is available there (`reports/SXT-028b/EVIDENCE.md`).

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, block size 32 (`oracle/manifest.json`).
- Structure authority: the files below were read at the pinned commits
  (fetched from `raw.githubusercontent.com`, 2026-09-25). Nothing was
  copied; the model re-derives the formulas.
  - `src/common/dsp/effects/ConditionerEffect.{h,cpp}`
  - `src/common/dsp/Effect.{h,cpp}`: ringout
  - `src/common/SurgeSynthesizer.cpp` and `SurgeSynthesizerIO.cpp`: FX lifecycle
  - `src/common/Parameter.cpp`: control-type ranges
  - `src/common/dsp/vembertech/lipol.h`
  - sst-filters `BiquadFilter.h` @ `e92d93a9`
  - sst-basic-blocks `MidSide.h` @ `a32b8aec`

## Citation correction

The issue title and scope line come from `tools/generate_effect_leaves.py`
and say "gate/compressor/LFO … shared LFO". The pinned source has **no gate
and no LFO**. The entry point is `process(dataL, dataR)`. The declared
`lipol<float,true> a_rate, r_rate` members are never referenced. The actual
algorithm, all per 32-sample block, is:

1. `setvars`: bass peaking EQ at the fixed `calc_omega(-2.5)` and treble
   peaking EQ at the fixed `calc_omega(4.75)`. Both use `coeff_peakEQ(ω, 2, dB)`;
   only the gain is a parameter. The side high-pass is
   `coeff_HP(calc_omega(hpwidth/12), 0.4)`. All three are lagged
   `BiquadFilter`s (`d_lp = 0.004`).
2. The bass and treble bands run stereo in series, each unless deactivated.
3. The lipol targets are:
   - `ampL/R = db_to_linear(-threshold) · 0.5 · clamp1bp(1 ∓ balance)`
   - `width = clamp1bp(width)`
   - `postamp = db_to_linear(gain)`
4. M/S encode (`M = ½(L+R)`, `S = ½(L−R)`). The side HP runs on S only
   (mono `process_block`, channel-0 registers). S is multiplied by the
   width ramp, then decoded (`L = M+S`, `R = M−S`), then multiplied by
   ampL and ampR.
5. The 128-sample look-ahead limiter runs per sample:
   - Read the delayed sample at `bufpos` and the **fixed leaf `lamax[126]`**.
   - Compute `la = max(1, sqrt(2·la))`.
   - Attack one-pole, then release one-pole, with the second clamped up to
     the first.
   - `gain = rcp(filtered_lamax2)`.
   - Store the current sample and its `max(|L|,|R|)²` at `bufpos`.
   - Output `gain · delayed`, then advance `bufpos`.
6. The `postamp` ramp multiplies the output.

There is no dry/wet mix: the output is always fully processed.

**Dead reduction tree.** The engine also builds a 7-level max tree in
`lamax[128..254]` every sample, but nothing reads it. The detector reads
the fixed slot 126, which is a leaf. So the detector sees one sample in
every 128 (the one written at `bufpos == 126`) and holds it for 128
samples. The model implements exactly that. `tests/test_sxt028b.py` shows
that a burst anywhere else in the cycle never reduces gain.
`tools/conditioner_negative_controls.py` NC-7 shows that a "sensible"
windowed-max detector fails exactness.

## Lifecycle, ring-out and tails (engine semantics reproduced)

| Engine path | Source | Model | RTL flag |
|---|---|---|---|
| patch load | `loadFx(false, true)` re-spawns every FX, then `init()` | `initialize()`: fresh state; biquad `first_run` starts coefficients instantly; lipols start at 0 | `FRESH` |
| `stopSound()` or FX preset reload | `fx->suspend()` → `init()` | `suspend()`: clears the ring, leaves, `bufpos`, envelope and gain. It does **not** clear biquad registers or lags (no `BiquadFilter::suspend()` call), the lipol ramps, or the ringout counter. | `SUSPEND` |
| input present or silent | `Effect::process_ringout` (ringout starts at 10,000,000) | `process_ringout(in, present)` | — |
| ring-out expired | `process_only_control()` | Output equals input unchanged. The envelope takes 32 steps with `la = 1` and `gain = 1/x`. No ring, lipol, or biquad activity. | `CONTROL_ONLY` |

- **Declared tail span.** After the last input-present block the engine
  still runs `process()` for `get_ringout_decay() − 1 = 99` blocks
  (3,168 samples, 66 ms). The 100th silent block is control-only.
  `tail_coverage_check()` requires a comparison to cover all 99 tail blocks
  plus that transition block, or it FAILs.
- **What the tail contains.** The look-ahead ring drains real signal
  within the first 4 blocks. The EQ and HP IIR ring-out continues after
  that.
- **Tail-transition finding.** After a control-only period, the ring still
  holds the content from the last processed block. When input resumes, that
  content is emitted first. The model and RTL reproduce this, and it is
  exercised in the RTL lifecycle case.

## Frozen word lengths

| Domain | Format |
|---|---|
| audio samples, look-ahead ring | Q10.21 s32 |
| lipol ramps (ampL, ampR, width, postamp) | Q13.18 s32 |
| biquad coefficients, lags and TDF2 registers; attack/release; squared-peak leaves; envelope trackers; gain | Q24.43 s64 |

Arithmetic follows `qmath.py`: exact products, round-half-up, saturation to
`[-2^(w-1), 2^(w-1)-1]`, and no floating point at audio rate. The
attack/release coefficients come from an **exact IEEE float32 emulation**
of the engine's float chain (`1.0f + 0.9f*x`, `0.001f*am*am`,
`0.0001f*rm*rm`), which a numpy test cross-checks. They are then quantized
to Q24.43 once per block.

## Per-instance state

One `ConditionerState` holds all of the following:

- `band1`, `band2`, `hp`
- 4 lipol ramps
- `delayed[2][128]` and `lamax[128]`
- `bufpos`, `filtered_lamax`, `filtered_lamax2` and `gain`
- the Effect ringout counter
- a position-weighted ring hash (a checkpoint only)

Two slots are two disjoint `ConditionerState` objects. State is never
shared; the pooled-state mutants in both the model and the RTL fail. The
total is 2,444 B per instance, far below the 64 KiB external threshold, so
all of it is **on-chip** state with **zero** external traffic.
State-memory traffic is 3 reads and 3 writes per processed sample
(`reports/SXT-028b/artifacts/buffer-requirement.json`). The aggregate
profile estimate remains `[PENDING-SXT-016]`.

## Control-plane boundary (model → RTL)

The control plane sends 22 words per block per instance:

- attack and release
- the 4 raw lipol targets
- 15 biquad targets
- a flags word: bass/treble/HP on, `CONTROL_ONLY`, `SUSPEND`, `FRESH`

The RTL computes everything at audio rate.

## Declared deviations

These are bounded but **not measured**; the reference leg is BLOCKED.

- Engine float32 audio arithmetic is replaced by the fixed-point formats
  above.
- **`mech::rcp` (SSE approximate reciprocal, ~12-bit) is replaced by an
  exact fixed-point reciprocal.** This is the largest deviation in this
  leaf. Even at unity gain the engine's `rcp(1.0)` need not be exactly 1.0.
  It must be measured, or `rcp` reproduced bit-exactly, before any budget
  for this leaf freezes (SXT-017, #12). `process_only_control()` uses an
  exact `1.f/x` in the engine as well.
- `sqrtf` is replaced by an exact integer square root.
- M/S halving truncates toward zero (≤ ½ LSB).
- `db_to_linear`, `calc_omega` and `coeff_*` are evaluated in double at
  control rate and quantized once.
- `flush_denormal` is not modeled.
- Parameter modulation into this effect is out of scope. The extraction
  tool refuses such presets.

Dead state that is never observable: `a_rate`, `r_rate`, `ef`, `vu[3][2]`,
and the `lamax[128..254]` tree.

## Provenance and licensing

This model is original to this repository (Apache-2.0). No Surge or SST
source, tables, or assets are committed. Every constant is either a cited
literal from the pinned source (`-2.5`, `4.75`, `BW = 2`, `Q = 0.4`,
`0.9f`, `0.001f`, `0.0001f`, `0.5`, `lookahead_bits = 7`, ringout 100 and
10,000,000) or a formula re-derivation. No distribution-license
determination has been made.
