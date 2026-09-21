# SXT-023 EQ — frozen model notes (`model/effects/eq/`)

Frozen reference: `eq_model.py` (one `ParametricEQ3BandEffect` instance).

## Frozen constants (pinned, cited)

| Constant | Value | Source |
|---|---|---|
| coefficient refresh | every 8th block (`slowrate = 8`) | `Effect.h:138`, `ParametricEQ3BandEffect.cpp` |
| band prototype | `coeff_peakEQ(ω, BW, gain)` = `coeff_orfanidisEQ(ω, BW, dbToLinear(g), dbToLinear(g/2), 1)` | `BiquadFilter.h:398-402, 405-460` |
| ω | `2π·440·noteToPitchIgnoringTuning(freq)·srInv` | `BiquadFilter.h:204-209` |
| BW floor | max(BW, 0.0001) | `BiquadFilter.h minBW` |
| unity case | `|G − G0| ≤ 1e-5` → identity biquad | `coeff_orfanidisEQ` |
| per-sample coefficient lag | v = 0.996·v + 0.004·target (double in engine; Q24.43 here) | `BiquadFilter.h` `vlag` |
| band deactivation | `if (!p[eq3_gainN].deactivated) band.process_block(...)` | `ParametricEQ3BandEffect.cpp:92-97` |
| output gain | `db_to_linear(eq3_gain)` lipol ramp × both channels | `process():99-100` |
| mix | `fade_2_blocks_inplace(dry, wet)` | `process():102-103` |
| TDF2 | op = in·b0 + r0; r0 = in·b1 − a1·op + r1; r1 = in·b2 − a2·op (double in engine; Q24.43 here) | `BiquadFilter.h:598-632` |

## Frozen schedule

Per block: if `bi == 0`, refresh the three coefficient targets from the
current parameters; `bi = (bi+1) & 7`. Bands in series (skipping
deactivated). Output gain ramp × band output. Mix crossfade dry/wet.
Copy-in/copy-out semantics (the dry input is preserved for the fade).

## Frozen deviations (model vs engine, budgeted not frozen)

* Q24.43 coefficients/lags/state vs engine double: ≤1e-13 relative class.
* `calc_omega` re-derived in double (via the exact `2^(x/12)` identity
  validated against the engine — see EVIDENCE.md) vs engine float32 table
  lerp: ≤1 ulp class.
* Band output rounding round-half-up to Q10.21 vs engine double→float
  round-to-nearest-even: ≤1 LSB class.

Achieved (fm_bass_1, all bands active, gain +4.11 dB): model-vs-engine
rms 1.0 LSB, max 7.8 LSB, spectral corr 1.000 — the EQ slice is at the
quantization floor.
