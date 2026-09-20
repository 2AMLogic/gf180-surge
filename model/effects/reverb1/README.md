# SXT-024 Reverb1 — frozen fixed-point model

Issue: #17 (SXT-024) · Model: [`reverb1_fixed.py`](reverb1_fixed.py) ·
Coefficient plane: [`coefficient_plane.py`](coefficient_plane.py) ·
Stability: [`stability_analysis.py`](stability_analysis.py) →
[`reports/sxt-024/stability-analysis.json`](../../reports/sxt-024/stability-analysis.json) ·
Buffers: [`buffer_report.py`](buffer_report.py) →
[`reports/sxt-024/buffer-requirement.json`](../../reports/sxt-024/buffer-requirement.json)

This directory is the FROZEN integer fixed-point model that the RTL-vs-model
EXACTNESS claim (issue #17 acceptance) references. Structure (never code) is
cited from the pinned GPL-3.0-or-later sources; see "Provenance" below.

## Frozen word lengths

| Format | Use | Definition |
|---|---|---|
| `s24` | audio I/O (FX-block input words) | signed 24-bit, Q1.23 |
| `s32i` | internal signal and external storage words | **Q4.28 in 32-bit containers**: sign + 3 integer headroom bits + 28 fraction bits (range ±8, LSB 2⁻²⁸) |
| `c31` | unit-range coefficients (`delay_fb`, `damp`, `1-damp`, pan gains) | Q1.31 |
| `c30` | ±2-range coefficients (`mix`, `1-mix`, `width_s`) | Q2.30 |
| `c29` | ±4-range coefficients (biquad `b0,b1,b2,a1,a2`) | Q3.29 |
| `reg80` | biquad TDF2 state | 80-bit signed, products at 2⁻⁵⁷, frozen bound \|reg\| < 2⁷⁹ (asserted) |
| `int` | `delay_time[16]` (8.8 fixed "256ths of a sample"), `pdtime`, `delay_pos` | integers per the pinned source |

**Headroom is load-bearing.** The composite loop value
`fbw = -(Σ out_tap)/8 + predelay` reaches ±3 and tap writes reach
±4·max(delay_fb) at coherent summation; the pinned engine carries these in
float without clipping. A no-headroom format (Q1.31) saturates the loop —
measured −7 dB error (see NC-D and the stability report). The 28 fraction
bits keep quiet-tail quantization ~32× below the 24-bit audio LSB; a pure
24-bit state grid measures ~48 dB worse on long tails (measured; the
SXT-016 "~15 guard bits" figure applies to that audio-sized grid, see
below).

## Frozen rounding rule

```
rnd_f(x)  = (x + (1 << (f-1))) >>> f      round-half-up, floor-biased
                                          (arithmetic shift, matches SV >>>)
sat32(x)  = clamp(x, -2^31, 2^31-1)
f         = a_frac + b_frac - dst_frac    for every multiply feeding a
                                          stored word:
                                            c31 × Q4.28 → Q4.28 (f = 31)
                                            c30 × Q4.28 → Q4.28 (f = 30)
                                            c29 × Q4.28 → 2^-57 acc (f = 29)
```

Intermediates are exact integers (Python unbounded ints in the model; ≥128-bit
containers in the RTL). The model asserts every stored word stays inside its
frozen width (`assert_width=True`). I/O conversion: in `s24 → s32i` exact
`<< 5`; out `s32i → s24` = `rnd_5` then saturate (`to_s24`) — the FX-block
boundary itself stays unclamped, matching the pinned engine's send/return sum.

## Frozen op order (one 32-sample block; cites Reverb1.h `processBlock`)

Per sample `k`, with `dt[t] = delay_time[t] >>> 8` and all buffer indices
mod 32768:

1. **Tap damping** — 16 external reads, one contiguous 16-word row burst:
   `dp = (delay_pos - dt[t]) & 32767`;
   `out_tap[t] = sat32(rnd_31(damp·out_tap[t] + (1-damp)·delay[(dp<<4)+t]))`
2. **Feedback** — 1 external read:
   `fbsum = Σ out_tap` (exact); `fbw = -(fbsum >>> 3) + predelay[(delay_pos - pdtime)]`
   (`ca = -2/16 = -1/8` exact)
3. **Advance + predelay write** — 1 external write:
   `delay_pos = (delay_pos+1) & 32767`;
   `predelay[delay_pos] = (inL + inR) >>> 1` (0.5·(L+R) exact floor)
4. **Tap writes + pan sums** — 16 external writes, one 16-word row burst:
   `delay[(delay_pos<<4)+t] = sat32(rnd_31(delay_fb[t]·(fbw + out_tap[t])))`;
   `wetL += sat32(rnd_31(pan_L[t]·out_tap[t]))` (and `wetR` with `pan_R`)

After the 32 samples (block order as pinned):

5. **Biquads** in pinned order `(locut HP, if active) → band1 peak → (hicut
   LP2B, if active)`, TDF2 per channel with c29 coefficients and 2⁻⁵⁷
   accumulators: `op = x·b0 + reg0; reg0' = x·b1 + reg1 - rnd_29(a1·op);
   reg1' = x·b2 - rnd_29(a2·op); y = sat32(rnd_29(op))`
6. **Width** (dB mode, side only — SurgeFXConfig, `widthIsLinear` absent):
   `M = (L+R)>>>1; S = sat32(rnd_30(((L-R)>>>1)·width_s)); L' = sat32(M+S);
   R' = sat32(M-S)`
7. **Mix**: `out = sat32(rnd_30((1-mix)·dry + mix·wet))`, dry widened `<< 5`.

Deviations from the pinned float code (bounded, recorded in the coefficient
plane module doc): float32 `powf`/table interpolation replicated with
numpy float32/float64 (≤1 ulp); the mix/width lipol lags are modeled at their
converged values (all reference renders settle ≥0.25 s before events); block
rate = 32 samples (SurgeFXConfig).

## External memory (long buffers)

Per instance (composite layout, interleaved rows of 16 words):

| Region | Words | Bits |
|---|---|---|
| Composite taps `delay[(pos<<4)+t]`, 16 taps × 32768 | 524,288 | 16,777,216 |
| Predelay line | 32,768 | 1,048,576 |
| **Total external writable** | **557,056** | **17,825,792 (2.125 MiB)** |

External traffic: **16 R + 1 R + 1 W + 16 W = 34 words = 136 B per output
frame** (6.528 MB/s at 48 kHz), reconciled with SXT-015's logical accounting
and SXT-016's `probe_fx_reverb1` rows (which priced 24-bit storage words; the
frozen word is 32-bit, so capacity is +33% while traffic is unchanged — the
buffer report records this supersession without editing committed files).
All processing stays in-chip; flash is never a substitute for this writable
memory. Two Reverb1 slots are two independent instances (never shared state).

## Fixed-point stability (summary; full data in the stability report)

- Loop model (conservative, zero-latency): `M = D(I − J/8)`; spectral radius
  ρ < 1 over the whole shape × roomsize × decay grid; worst reachable
  ρ = 0.9966 (shape 1, room 0.25, decay 6.0).
- SXT-016 reconciliation: that probe's "~15-bit guard band" was computed for
  a 24-bit-audio-sized state grid at max decay (24+15 = 39 bits). This
  analysis CONFIRMS the ρ<1 condition and the loop model, and shows the
  frozen Q4.28 word provides the equivalent protection through a finer grid
  (2⁻²⁸ LSB) plus integer headroom: **4 guard bits vs the Q4.28 state LSB**
  at the worst reachable decay/room (noise-gain analysis), i.e. the frozen
  32-bit word choice covers the guard requirement.
- Empirical worst case: 140 s excitation at every shape, max decay, max
  room: peak internal state 354,444,106 (16.5% of s32i headroom), tails
  decay to silence, no energy growth.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). STRUCTURE is read and
cited — never copied — from the pinned external GPL-3.0-or-later tree:
`sst-effects` `include/sst/effects/Reverb1.h`
(`loadpreset`, `update_rtime`, `processBlock`, `initialize`) via
`surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
`src/common/dsp/effects/Reverb1Effect.cpp`; coefficient formulas from
`sst-filters` `BiquadFilter.h` and `SurgeStorage`/`DSPUtils.h` as cited in
[`coefficient_plane.py`](coefficient_plane.py). The 16×4 `delay_time` tables
are transcribed as cited structural constants (file/table-level provenance in
the module docstring). No Surge source, tables, or assets are committed
beyond those cited constants; no distribution-license determination has been
made for Surge-derived material.
