# 0008: Sine wave_remap streaming-migration table (SXT-040)

- **Status**: PROPOSED — pending owner ratification
- **Date**: 2026-09-24
- **Decided by**: Loom implementer agent correcting judge findings on PR
  #92 (SXT-040, issue #74), under the governance authority of issue
  [#25](https://github.com/2AMLogic/gf180-surge/issues/25) and
  `docs/REUSE-AUDIT.md` ("Standing rules")
- **Consumed by**: #74 (SXT-040, Sine oscillator family leaf)

## Context

`model/oscillators/sine/README.md` ("Finding: sine-shape streaming
migrations") transcribes, and the SXT-040 frozen model implements, the
sine shape-id migration the pinned engine applies when loading older
patches:

```
int wave_remap[] = {0, 8, 9, 10, 1, 11, 4, 12, 13, 2, 3, 5, 6, 7,
                    14, 15, 16, 17, 18, 19};
```

Provenance (pinned engine, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
`src/common/dsp/oscillators/SineOscillator.cpp`, function
`SineOscillator::handleStreamingMismatches`, the
`streamingRevision <= 12` block (array declared at line 1201 of that file
at the pin; whole-file sha256
`c2860449988f9e9ddab03e7cd98d6e9b0b154ec2fae4d81dd301c23e8168a830`).
The table is an opaque designed mapping with no construction formula in
the pinned tree: it maps the 20 legacy sine shape ids onto the
post-expansion shape ids so older patches keep pointing at the intended
waveform, with a range check that resets any value ≥ 20 to shape 0. In
this repository it realizes the leaf's declared normalized-authority
semantics (raw `.fxp` shape values are pre-migration; only the
post-`load_xml`, post-migration value is used), exercised by the
committed carriers and by the shape-migration negative control.

`AGENTS.md` requires a visible license decision record before any
GPL-/Surge-derived table is reproduced in this Apache-2.0 repository.
The SXT-040 evidence record initially claimed "no source/tables/assets
copied" while the README transcribed this table — a discrepancy found by
judge review of PR #92. This record is that decision; it corrects the
EVIDENCE §8 claim visibly rather than leaving it silent. The project has
not made a distribution-license determination (per `AGENTS.md`).

## Decision

1. The 20 integers above are **quoted as data** in
   `model/oscillators/sine/README.md` (the freeze documentation) and
   implemented in `model/oscillators/sine/sine_model.py`, with the
   provenance stated in this record and cited in the README. No Surge/SST
   *code* is copied: the migration's control flow (range check, reset,
   remap) is re-implemented and cited.
2. Adoption is **with attribution** (this record + the README citation)
   and **PROPOSED, pending owner ratification**. Ratification of this
   record (or its successor) must precede any distribution decision that
   relies on it.
3. This is the only Surge-derived data table introduced by SXT-040. The
   SXT-040 EVIDENCE licensing section (§8) is corrected to cite this
   record instead of claiming nothing was copied.

## Consequences

- The model reproduces the pinned engine's legacy-shape loading semantics
  exactly; the shape-migration negative control (a raw pre-migration
  value must FAIL the reference-budget check) stays meaningful.
- If the owner rejects the adoption, the fallback is re-deriving the
  mapping from the engine's observable load behavior (render-level
  identification of each legacy shape), which would weaken the migration
  finding to a measured approximation and require re-running the SXT-040
  budget matrix before merge.
- Any further opaque engine constants adopted by SXT-040 or successor
  sine leaves must extend this record (or add a successor) before merge.
