# 0004: Wavetable asset boundary + mip halfband constants (SXT-026)

- **Status**: PROPOSED — pending owner ratification
- **Date**: 2026-09-21
- **Decided by**: Loom builder agent implementing PR (SXT-026, issue #19),
  under the governance authority of issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25)
  and `docs/REUSE-AUDIT.md` ("Standing rules"); interim until the owner
  ratifies or amends it
- **Consumed by**: #19 (SXT-026), the wavetable asset compiler
  (`compiler/assets/wavetable.py`), the frozen wavetable model
  (`model/oscillators/wavetable/wt_model.py`), and their RTL consumer

## Context

SXT-026 adds wavetable assets and playback. Two licensing questions arise.

**(1) The `.wt` asset payloads.** A compiled patch image references
wavetable assets (`graph.wavetable_assets` → `res: [[path, sha256], ...]`,
resolved by the SXT-011 exporter from the pinned tree
`resources/data/wavetables*`). The payloads are GPL-distributed material
(bundled Surge XT factory wavetables; some third-party). `AGENTS.md`: keep
GPL/Surge-derived material in the external pinned oracle. The 2AMLogic
convention of this repository is Apache-2.0. This project has made **no
distribution-license determination** for a future chip product.

**(2) The mip-map halfband filter.** `Wavetable::MipMapWT()`
(`src/common/dsp/Wavetable.cpp`, pinned at
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
GPL-3.0-or-later) builds the anti-aliased mip levels of a wavetable with a
63-tap halfband lowpass, `hrfilter[63]` — opaque designed constants with no
construction formula in the pinned tree (the same class as 0002's twelve
halfband coefficients and 0003's sixty-four delay-time constants). The
frozen fixed-point model must reproduce the engine's mip construction to
stay inside any credible error budget at the mips above level 0.

Record **0002** requires: "Any future adoption of further opaque engine
constants must extend this record (or add a successor) before merge."
Record **0003** repeats the requirement. This record is that successor for
the wavetable-slice constants, and simultaneously settles the repository
boundary for the `.wt` payloads themselves.

## Decision (interim)

1. **`.wt` payloads stay external.** The repository stores only identity
   (SHA-256 + size + path), dimensions, mip/AA structure, required
   interpolation modes, and residency classification — emitted by
   `compiler/assets/wavetable.py` as `derived.wavetable_asset_manifests`
   into the patch image when compiled with `--asset-root`. A compile-time
   hash mismatch between the external file and the graph's resolved record
   **aborts** the build (exit 2). The model and RTL derive their table
   words **at run time** from the external tree (hash-verified first);
   no `.wt` payload, frame-level table dump, or derived table hex is
   committed to this repository. CI's in-repo guard asserts no `vawt`
   payload exists anywhere in the tree.
2. **`hrfilter[63]` is quoted as data** (file-level provenance: source file
   `src/common/dsp/Wavetable.cpp`, engine pin `58914e59c608ed4384ba6002e44c3465c58b2e71`,
   license GPL-3.0-or-later) in `model/oscillators/wavetable/wt_model.py`,
   used only to rebuild the wavetable's own anti-aliasing mips exactly as
   the pinned engine does. No engine *code* is copied: `MipMapWT()`,
   `BuildWT()`, and the oscillator are re-implemented from the pinned
   source and cited. These 63 values join 0002's twelve halfband
   coefficients and 0003's sixty-four delay-time constants as the only
   engine data constants reproduced in this repository; any further opaque
   engine constant still requires extending this record or adding a
   successor **before merge**.
3. **Flag into the open distribution-license determination.** If the chip
   product ships wavetable assets (in flash) or the mip halfband constants
   (in ROM/firmware), that distribution question (#25 / `AGENTS.md`: no
   determination made) must be answered with these items visibly on the
   list of GPL-derived content in the artifact. This record does not answer
   it. Note for the determination: factory `.wt` payloads are
   GPL-distributed assets; third-party wavetable banks may carry their own
   terms and need per-asset review before any product redistribution.

## Alternatives considered

- **Copy the `.wt` payloads into the repository** — rejected outright:
  GPL-distributed assets in an Apache-2.0 repository without a
  distribution determination; also unnecessary, since identity hashes give
  the same build-time verification.
- **Quote the embedded tables as hex in-repo** — rejected: the payloads
  stay external per (1); derived table words are generated at run time.
- **Re-derive `hrfilter[63]` from a formula** — rejected: no construction
  formula exists in the pinned tree (checked numerically against windowed
  sinc families); any re-derivation would be a different (wrong) model.
- **Skip mip levels ≥ 1 in the model** — rejected: the engine builds and
  uses them; dropping them would be an adapted (wrong) oscillator, and the
  issue explicitly requires mip/AA behavior.

## Consequences

- SXT-026 can merge with the manifest boundary and the quoted mip filter
  in place; the model README records the provenance adjacent to the
  constants.
- The record is **PROPOSED**: the owner may ratify or amend (e.g., by
  preferring external table derivation for CI) before merge; until then it
  is the recorded interim choice, not an owner ruling.
- No fidelity, preset-support, musical-quality, or distribution-license
  conclusion is established by this record; it is a repository-content
  boundary decision only.
