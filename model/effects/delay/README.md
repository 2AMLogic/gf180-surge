# SXT-023 Delay — frozen model notes (`model/effects/delay/`)

Frozen reference: `delay_model.py` (one Delay instance; two instances = two
`DelayState` objects — never shared). sinc table: `sinc_table.py`.

## Frozen constants (pinned, cited)

| Constant | Value | Source (pinned tree) |
|---|---|---|
| max_delay_length | 1<<18 = 262,144 samples | `Delay.h:200` |
| line allocation | 2 × (262,144 + 12) words Q10.21 | `Delay.h:203` (+ FIRipol_N guard) |
| FIRipol_M / FIRipol_N | 256 / 12 | `SincTableProvider.h` |
| sinc table 1X cutoff | 0.85, symmetric Blackman × sincf | `SincTableProvider.h` ctor (formula re-derived, not copied) |
| time-lag lp | 0.0001f and lpinv = 1−lp **in float32** | `Lag.h` `SurgeLag<float,true>`; the pair sums to 1+7.46e-11 — reproduced quantized (the engine's lag drifts; Q24.43 with this pair tracks it) |
| biquad lag d | 0.004 / 0.996 per sample | `BiquadFilter.h` `d_lp`, `d_lpinv` (double) |
| LFO pole | ca = 0.99f | `Delay.h:286` |
| softclip | x − 4/27·x³ on [−1.5, 1.5] | `Clippers.h` `softclip_ps` |
| lp/hp Q | 0.707 literal | `Delay.h:314-315` |
| read offset | `rp = (wpos − i_dtime + k) − FIRipol_N` | `Delay.h:354-355` (**FIRipol_N = 12**, not the 6-sample FIRoffset of `setvars`) |
| tap phase | `clamp((int)(256·(i_dtime+1−v)), 0, 255)` | `Delay.h:357-362` |
| feedback gain | amp_to_linear(f) = f³, extend 2f−1 bipolar | `Delay.h:183-188, 252-265` |
| width | side × dbToLinear(w), mid intact | `WidthProvider.h` (dB branch) |

## Frozen schedule

Per block: control pass (targets; LFO advance BEFORE the time targets;
first-block instantize), then per sample: lag steps → `i_dtime` clamp
[32, 262,131] → sinc phase → 12-tap stereo line read → block: fb_sign
negation → softclip (deform 1) → highcut LP2B → lowcut HP → trixpan write
buffer → feedback MAC → crossfeed MAC (crossed) → line write → width (side
only) → mix crossfade. `wpos = (wpos+32) & (2^18−1)`.

## Declared deviations (model vs engine, budgeted not frozen)

* Q24.43 lag/coefficients vs engine float32 lag + double biquad: sub-ulp
  class, EXCEPT the float32-grid staircase of `timeL.v` at long delays
  (ulp = 2^-9 samples at 24,000): the tap phase selection jitters ±1/256
  sample between model and engine — the dominant model-vs-reference
  deviation class at long delays (see EVIDENCE.md).
* lfophase accumulated in Q24.43 vs engine double; LFOval one-pole in Q24.43
  vs engine float32 — sub-phase-step class.
* sinc table in Q2.29 (double-derived) vs engine float32 table — ≤1 LSB/tap.
* `note_to_pitch_ignoring_tuning` / `envelope_rate_linear` / `db_to_linear`
  re-derived in double from the cited table formulas vs engine float32
  table lerp — ≤1 ulp class.
* biquad output rounding round-half-up vs engine double→float
  round-to-nearest-even — ≤1 LSB class.

## Reproduce

```sh
python3 model/effects/run_fx_model.py --slug dexie    # tempo-synced case
python3 tools/compare_rtl_model_fx.py --slug dexie    # RTL exactness
```
