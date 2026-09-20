# 0002: Halfband decimator coefficient constants (SXT-022)

- **Status**: ratified
- **Date**: 2026-09-20
- **Decided by**: Loom builder agent implementing issue #15 (SXT-022), under
  the governance authority of issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25)
  and `docs/REUSE-AUDIT.md` ("Standing rules")
- **Consumed by**: #15 (SXT-022, first dry voice slice)

## Context

The frozen fixed-point model and the SXT-022 RTL slice must reproduce the
pinned engine's scene output, which includes the per-scene decimator
`sst::filters::HalfRate::HalfRateFilter(M=6, steep)` (`libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h`,
submodule pin `e92d93a92beabde03fa4ab767b285fa21c6608d6` in
`oracle/manifest.json`). Unlike the oscillator sinc table — which the model
recomputes from the pinned *construction formulas* in
`sst-basic-blocks/tables/SincTableProvider.h` — the halfband's twelve
allpass coefficients are opaque designed constants with no construction
formula in the pinned tree:

```
a_coefficients[6] = {0.036681502163648017f, 0.2746317593794541f,
                     0.56109896978791948f,  0.769741833862266f,
                     0.8922608180038789f,   0.962094548378084f};
b_coefficients[6] = {0.13654762463195771f, 0.42313861743656667f,
                     0.6775400499741616f,  0.839889624849638f,
                     0.9315419599631839f,  0.9878163707328971f};
```

`AGENTS.md` requires a visible license decision record before any
GPL-/Surge-derived constant, table, or asset is reproduced in this
Apache-2.0 repository. This record is that decision.

## Decision

1. The twelve scalar coefficients above are **quoted as data** into
   `model/voice/voice_model.py` (`HALFBAND_A`, `HALFBAND_B`), with file-level
   provenance (source file, submodule commit, license) stated adjacent to the
   constants. They are quantized once to the model's Q10.21 word format
   (`HALFBAND_A_Q`, `HALFBAND_B_Q`) and streamed to the RTL through
   `init.hex`; the RTL carries no independent copy.
2. No Surge/SST *code* is copied: the decimator's control flow is
   re-implemented from the pinned structure (two 6-stage allpass cascades
   per channel; `y[n] = x[n-2] + a*(x[n] - y[n-2])`; decimated output
   `(A[2n] + B[2n+1]) * 0.5`), cited in the model and RTL headers.
3. These twelve numbers are the **only** engine data constants reproduced in
   this repository by SXT-022. Everything else numeric (sinc table, pitch /
   envelope-rate / dB tables) is recomputed from cited formulas.

## Consequences

- The model-vs-reference error budget does not need to absorb a
  re-derived-coefficient term, because the exact reference constants are used.
- If SXT-016/023 later re-derives the word lengths (SXT-017 trigger 5), the
  quantization of these constants changes only in `voice_model.py` and the
  generated `init.hex`; the quoted doubles stay the single source of truth.
- Any future adoption of further opaque engine constants must extend this
  record (or add a successor) before merge.
