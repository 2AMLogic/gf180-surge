# 0014: Distortion SSE quad-waveshaper constant inventory (SXT-028e-sse)

- **Status:** PROPOSED — pending owner ratification
- **Date:** 2026-09-26
- **Decided by:** Loom builder agent implementing leaf
  [#121](https://github.com/2AMLogic/gf180-surge/issues/121) (SXT-028e-sse),
  under the governance authority of issue
  [#25](https://github.com/2AMLogic/gf180-surge/issues/25) and
  `docs/REUSE-AUDIT.md`; interim until the owner ratifies or amends it
- **Consumed by:** #121 (SXT-028e-sse), `model/effects/type-distortion-sse/`,
  `rtl/effects/type-distortion-sse/`
- **Discharges:** [0012](0012-distortion-halfband-and-waveshaper-tables.md)
  "Consequences" clause 3 — *"Adopting the SSE quad-waveshaper branch (FX
  models 3..7) will require its own inventory pass: several of those shapers
  carry designed constants of their own."* This is that pass.
- **Extends:** [0002](0002-halfband-coefficients.md) (ratified) clause 1 —
  quoted engine constants are streamed to the RTL, never duplicated there
- **Related:** [0003](0003-reverb1-delay-time-tables.md),
  [0007](0007-chorus-constant-inventory.md),
  [0008](0008-sine-wave-remap-table.md) (constant-inventory pattern)

## Context

The SXT-028e-sse frozen fixed-point model reproduces the `useSSEShaper`
branch of `DistortionEffect::process`
(`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
GPL-3.0-or-later) and the five `GetQuadWaveshaper` entries reachable from
`FXWaveShapers[3..7]`
(`libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce`,
GPL-3.0-or-later):

| FX model | `WaveshaperType` | `GetQuadWaveshaper` entry | Source file |
|---|---|---|---|
| 3 | `wst_sine` | `SINUS_SSE2<false>` | `Effects.h` |
| 4 | `wst_digital` | `DIGI_SSE2` | `Effects.h` |
| 5 | `wst_ojd` | `OJD` | `Saturators.h` |
| 6 | `wst_fwrectify` | `ADAA_FULL_WAVE` | `Rectifiers.h` + `ADAA.h` |
| 7 | `wst_fuzzsoft` | `TableEval<FuzzTable<1>, 1024, TANH>` | `WaveshaperLUT.h` + `Fuzzes.h` + `Saturators.h` + `DCBlocker.h` |

Their constants fall into **three** classes, and only one of them is the
DR-0002/DR-0012(a) "quoted opaque data" class.

### (a) Designed scalars — opaque, quoted (11 values)

These have no construction formula anywhere in the pinned tree. They are
design choices written as literals, so they must be quoted as data or not
used at all.

```
OJD (Saturators.h)
  breakpoints            -1.7f, 1.1f, -0.3f, 0.9f
  branch denominators    1.f / (4 * (1 - 0.3f))      // = 0.35714287f
                         1.f / (4 * (1 - 0.9f))      // = 2.4999995f
TANH (Saturators.h)
  rational approximant   y = x * (27 + x*x) / (27 + 9*x*x)   // 9, 27
ADAA (ADAA.h)
  antiderivative tolerance   tolF = 0.0001            // double -> set1_ps
dcBlock (DCBlocker.h)
  one-pole DC blocker pole   0.9999f
```

Note the two OJD denominators are written with a **float32** `1 - 0.9f`,
which is `0.100000024f`, not `0.1`; the quoted value is therefore
`2.4999995`, not `2.5`. Quoting the *expression* rather than a rounded
decimal is load-bearing.

### (b) Structural scalars — not engine data (6 values)

`1.0`, `0.5`, `256.0`, `512.0`, `0.0625`, and `WS_PM1_LUT`'s `N/2` = `512`
and `N-1` = `1023`. These are the arithmetic shape of the index mapping
(a power-of-two scale and the LUT's own size), not designed coefficients.
Nothing is adopted by reproducing them.

### (c) Tables — formula-derived, NOT quoted (2 rows, 2049 words)

**`wst_sine` (1024 words).** Built by
`sst::waveshapers::WaveshaperTables::WaveshaperTables()` from the closed
form `(float)std::sin((double)((double)i - 512.0) * M_PI / 512.0)`. Same
class as DR-0012 clause (b).

**`FuzzTable<1>` (1025 words).** Built by
`LUTBase<1024, FuzzTable<1>>` from
`xadj = x * (1 - range) + dist(gen)`, with `range = 0.1`, a function-static
`portable_minstd_rand(2112)` and a function-static
`std::uniform_real_distribution<float>(-range, range)`.

This one needs care. The pinned header **deliberately** de-typedefs
`std::minstd_rand` into an explicit
`linear_congruential_engine<uint_fast32_t, 48271, 0, 2147483647>`, with the
comment *"to make the fuzzes the same on all platforms and compiler
choices, since the spec gives leeway as to what to choose"*. That pins the
engine — but **not** `std::uniform_real_distribution`, which the C++
standard also leaves implementation-defined. So the "construction formula"
is only complete once the distribution's reduction is pinned too.

It is. For `float` (24 mantissa digits) over this engine's range, both
major standard libraries collapse `generate_canonical` to a **single** draw
and the identical three float operations:

```
u_k    = float(lcg_k - 1) / 2147483648.0f
draw_k = u_k * (b - a) + a
```

(libstdc++: `__b = 24`, `__log2r = 31`, `__m = 1`,
`__tmp = float(2147483646.0L) = 2147483648.0f`. libc++: `__logR = 30`,
`__k = 1`, `__base = float(2147483645) + 1 = 2147483648.0f`.)

## Decision (interim)

1. **(a) Quoted constants.** The eleven designed scalars above are **quoted
   as data** into `model/effects/type-distortion-sse/quad_shapers.py`, with
   file-level provenance (source file, submodule commit, license) stated
   adjacent to them. They are quantized once to Q24.43 (`SHAPER_INIT_WORDS`)
   and **streamed to the RTL through the testbench init file** (INITFILE
   indices 16..26) — the RTL carries no independent copy, exactly as DR-0002
   clause 1 requires and as DR-0012 clause 1 already does for the twelve
   halfband coefficients. Together with DR-0002's twelve and DR-0012's
   twelve, these eleven are the only engine data constants reproduced in
   this repository by the voice and Distortion slices.
2. **(b) Re-derived tables.** The `wst_sine` and `FuzzTable<1>` rows are
   **recomputed** from the pinned construction formulas in
   `model/effects/type-distortion-sse/sse_tables.py`, in the same
   double/float32 sequence the engine uses, and quantized once to Q2.29. No
   table data is copied. The generated ROM
   (`rtl/effects/type-distortion-sse/ws_sse_q29.hex`, 2049 words) is a build
   product of that generator
   (`tools/gen_distortion_sse_rom.py`);
   `tests/test_sxt028e_sse.py::test_ws_rom_matches_generator` asserts the
   committed ROM matches the generator byte for byte, so it can never drift
   into being an independent copy of engine data.
3. **The `FuzzTable<1>` re-derivation claim is discharged BY BUILD, not by
   assertion.** `tools/check_fuzz_table_rederivation.py` writes a
   ~20-line C++ probe containing only the pinned header's own expression
   (to a temporary directory; **never** committed), compiles it, and
   compares all 1025 float32 bit patterns against the Python generator's
   pre-quantization values. Result at the time of this record: **MATCH,
   1025/1025, 0 mismatches** (g++ 13.3.0 / libstdc++;
   `reports/SXT-028e-sse/artifacts/fuzz-table-rederivation.json`). If that
   check ever reports MISMATCH, clause 2 is false for that row and the row
   must be re-classified as quoted data by amending this record — the check
   is a live guard on a licensing-relevant claim.
4. **(b) Structural scalars stay in the RTL.** The six power-of-two /
   LUT-size constants of class (b) are `localparam`s in
   `rtl/effects/type-distortion-sse/tb_distortion_sse.sv`. They are not
   engine data and streaming them would only obscure the inventory.
5. **No Surge/SST code is copied.** Every shaper is re-implemented from the
   pinned structure and cited in the model and RTL headers. The SIMD
   formulation is *not* reproduced: `quad_shapers.py` DD-1 records that only
   two of the four lanes carry signal and that all operations are lane-wise.
6. **`rcp_ps` is NOT adopted as a constant or as an algorithm.** The pinned
   `DIGI_SSE2` and `TANH` call the SSE reciprocal *estimate*, whose result
   is implementation-defined (and differs between x86 and simde-on-ARM,
   which is what the pinned arm64 evidence host runs). The frozen model uses
   the **exact** reciprocal and declares the difference as a bounded
   model-vs-reference term (`quad_shapers.py` DD-2, finding F-028e-sse-1),
   routed to SXT-017 (#12). No constant is adopted to emulate it.

## Consequences

- The model-vs-reference error budget for FX models 4 and 7 must absorb the
  `rcp_ps`-estimate term (relative error up to ~1.5·2⁻¹² ≈ 3.7e-4) on top of
  the ordinary quantization terms. That is an input to SXT-017 (#12), not a
  decision made here.
- FX model 6's ADAA `init` mask is **indeterminate in the engine**
  (`DistortionEffect::init()` zeroes `wsState.R[i]` but not `wsState.init`,
  and `QuadWaveshaperState` has no constructor). This record does not decide
  that; `quad_shapers.py` DD-3 freezes it to "first sample" and bounds the
  consequence to the single first oversampled sample after each reset
  (finding F-028e-sse-2).
- The `FuzzTable<1>` validation leg is currently libstdc++-only. Re-running
  `tools/check_fuzz_table_rederivation.py` on the pinned arm64 macOS /
  libc++ oracle host is a named follow-up; until then the libc++ equivalence
  is **UNVERIFIED-BY-BUILD**, derived by reading its `generate_canonical`.
- If SXT-016/023 re-derives the word lengths (SXT-017 trigger 5), the
  quantization of the eleven quoted scalars changes only in
  `quad_shapers.py` and the generated init file; the quoted float32
  expressions stay the single source of truth.
- Any future adoption of further opaque engine constants must extend this
  record or add a successor before merge.

## What this record does NOT decide

No distribution-license determination for Surge-derived material has been
made by this repository (`CLAUDE.md` / `AGENTS.md`). This record authorizes
the eleven scalars as *quoted data with provenance* and classifies the two
table rows as *re-derived*; it makes no claim about redistribution of the
pinned engine, its presets, or its assets. It establishes no fidelity,
preset-support, cost or musical-quality claim.
