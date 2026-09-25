# 0012: Distortion halfband coefficients (order 6) and waveshaper table provenance (SXT-028e)

- **Status:** PROPOSED — pending owner ratification
- **Date:** 2026-09-25
- **Decided by:** Loom builder agent implementing leaf [#57](https://github.com/2AMLogic/gf180-surge/issues/57)
  (SXT-028e), under the governance authority of issue
  [#25](https://github.com/2AMLogic/gf180-surge/issues/25) and
  `docs/REUSE-AUDIT.md`; interim until the owner ratifies or amends it
- **Consumed by:** #57 (SXT-028e), `model/effects/type-distortion/`
- **Extends:** [0002](0002-halfband-coefficients.md) (ratified; the
  `HalfRateFilter(M = 6, steep)` coefficient set), whose closing clause
  requires any further opaque engine constant to extend it or add a successor
- **Related:** [0003](0003-reverb1-delay-time-tables.md),
  [0007](0007-chorus-constant-inventory.md) (constant-inventory pattern)

## Context

The SXT-028e frozen fixed-point model reproduces the pinned engine's
`DistortionEffect` (`src/common/dsp/effects/DistortionEffect.{h,cpp}` at
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
GPL-3.0-or-later). Two constant classes arise, and only one of them needs a
license decision.

**(a) Halfband decimator coefficients — opaque, quoted.** The effect runs its
shaper at 4× and decimates with two `sst::filters::HalfRate::HalfRateFilter`
instances constructed as `hr_a(3, false)` and `hr_b(3, true)`
(`DistortionEffect.cpp:32`). With `M = 3` the filter's `load_coefficients()`
takes its `order == 6` branches, which are **different constants from the
`order == 12, steep` set already covered by DR-0002**:

```
hr_a = HalfRateFilter(3, false)   // "softer slopes", rejection 80 dB
a_coefficients[3] = {0.06029739095712437f, 0.4125907203610563f,
                     0.7727156537429234f};
b_coefficients[3] = {0.21597144456092948f, 0.6043586264658363f,
                     0.9238861386532906f};

hr_b = HalfRateFilter(3, true)    // "steep", rejection 51 dB
a_coefficients[3] = {0.1271414136264853f, 0.6528245886369117f,
                     0.9176942834328115f};
b_coefficients[3] = {0.40056789819445626f, 0.8204163891923343f,
                     0.9763114515836773f};
```

Source: `libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h` at
submodule pin `e92d93a92beabde03fa4ab767b285fa21c6608d6`
(`oracle/manifest.json`), license GPL-3.0-or-later. Like the DR-0002 set,
these are **designed elliptic-halfband allpass coefficients with no
construction formula in the pinned tree**, so they cannot be re-derived; they
must be quoted as data or not used at all.

**(b) Waveshaper tables — formula-derived, NOT quoted.** The three FX
waveshaper rows reachable from this effect's non-SSE branch (`wst_soft`,
`wst_hard`, `wst_asym`) are built by
`sst::waveshapers::WaveshaperTables::WaveshaperTables()`
(`libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce`) from
explicit closed-form expressions (`tanh(x)`,
`sign(x)·tanh(|x|^5)^0.2`, `shafted_tanh(x + 0.5) − shafted_tanh(0.5)` over
`x = (i − 512)/32`). This is the `sinc_table.py` / DR-0007 class of constant:
a **re-derivation from a cited construction formula**, not the adoption of
opaque data.

## Decision (interim)

1. **(a) Quoted constants.** The twelve order-6 halfband allpass coefficients
   above are **quoted as data** into
   `model/effects/type-distortion/distortion_model.py`
   (`HB_A_SOFT`, `HB_B_SOFT`, `HB_A_STEEP`, `HB_B_STEEP`), with file-level
   provenance (source file, submodule commit, license) stated adjacent to
   them. They are quantized once to Q24.43 (`HB_COEFFS_Q`) and **streamed to
   the RTL through the testbench init file** — the RTL carries no independent
   copy, exactly as DR-0002 clause 1 requires. These twelve values plus the
   DR-0002 twelve are the only engine data constants reproduced in this
   repository by the voice and Distortion slices.
2. **(b) Re-derived tables.** The three waveshaper rows are **recomputed**
   from the pinned construction formulas in
   `model/effects/type-distortion/ws_tables.py`, in the same
   double-then-float32 sequence the engine uses, and quantized once to Q2.29.
   No table data is copied. The generated ROM
   (`rtl/effects/type-distortion/ws_q29.hex`) is a build product of that
   generator; `tests/test_sxt028e.py` asserts the committed ROM matches the
   generator byte for byte, so the ROM can never drift into being an
   independent copy of engine data.
3. **No Surge/SST code is copied.** The decimator's control flow is
   re-implemented from the pinned structure — two 3-stage allpass cascades
   per channel, `y[n] = x[n−2] + a·(x[n] − y[n−2])`, decimated output
   `(B[2n] + A[2n+1])·0.5` — and cited in the model and RTL headers.
4. **Branch-assignment note (load-bearing).** The pinned
   `set_coefficients` places `cA` in SIMD lanes 0/2 and `cB` in lanes 1/3
   (`va[i] = set_ps(cB[i], cA[i], cB[i], cA[i])`), and the reconstruction
   broadcasts lane 1 at the even sample and adds lane 0 of the odd sample.
   The decimated output is therefore `(B[2n] + A[2n+1])·0.5`, matching the
   original `output = (filter_a.process(input) + oldout)·0.5` comment the
   pinned header preserves. Swapping the two branches destroys the halfband
   stopband (measured: 80 dB rejection at 0.3·fs becomes 3.5 dB). This
   record fixes the assignment so a future reader cannot "tidy" it.

## Consequences

- The model-vs-reference error budget does not need to absorb a
  re-derived-coefficient term for the decimator: the exact reference
  constants are used.
- If SXT-016/023 re-derives the word lengths (SXT-017 trigger 5), the
  quantization of these constants changes only in `distortion_model.py` and
  the generated init file; the quoted doubles stay the single source of
  truth.
- Adopting the SSE quad-waveshaper branch (FX models 3..7) will require its
  own inventory pass: several of those shapers carry designed constants of
  their own. That branch is REFUSED by this leaf (fail-closed), so no such
  adoption happens here.
- Any future adoption of further opaque engine constants must extend this
  record or add a successor before merge.

## What this record does NOT decide

No distribution-license determination for Surge-derived material has been
made by this repository (`CLAUDE.md` / `AGENTS.md`). This record authorizes
the twelve scalars as *quoted data with provenance*; it makes no claim about
redistribution of the pinned engine, its presets, or its assets.
