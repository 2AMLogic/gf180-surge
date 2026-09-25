# 0009: Pinned-kernel reference harness for the SXT-039 filter leaf

- **Status**: PROPOSED — pending owner ratification
- **Date**: 2026-09-25
- **Decided by**: Loom implementer agent on issue
  [#73](https://github.com/2AMLogic/gf180-surge/issues/73) (SXT-039, LP
  Legacy Ladder filter leaf), under the governance authority of issue
  [#25](https://github.com/2AMLogic/gf180-surge/issues/25) and
  `docs/REUSE-AUDIT.md` ("Standing rules")
- **Consumed by**: #73 (SXT-039); the method is reusable by later filter
  leaves that hit the same exposure gap

## Context

The voice filter is an internal per-voice stage with no surgepy exposure, so a
filter leaf cannot obtain filter-stage reference evidence through the Python
bindings. DR-0005 solved this for SXT-037 with **oracle tap instrumentation**:
a patched build of the pinned engine, on the oracle host, dumping each filter
unit's input/output and coefficient plane.

That path was unavailable to this leaf: the machine dispatched for #73 is a
shared dispatch worker with **no pinned engine checkout and no surgepy build**
(and building the full engine there is neither sanctioned nor reproducible —
see the worker's own host rules). Two options remained: record the whole
model-vs-reference leg NOT_RUN, or obtain reference evidence for the algorithm
itself from the pinned code that implements it.

The LP Legacy Ladder algorithm lives entirely in two pinned submodules —
`libs/sst/sst-filters` (`Coeff_LP4L`, `FromDirect`, `LPMOOGquad`) and
`libs/sst/sst-basic-blocks` (`softclip8_ps`) — both header-only. They can be
compiled standalone, at the exact pinned commits, and driven with the fixture's
own control plane and input samples.

## Decision

1. `tools/render_lpmoog_reference.py` **generates, builds and runs a harness
   outside this repository** that links the pinned sst-filters /
   sst-basic-blocks headers at the commits pinned in `oracle/manifest.json`
   (`sst-filters@e92d93a9`, `sst-basic-blocks@a32b8aec`), and renders the
   leaf's reference streams.
2. **No GPL-derived code enters this repository.** The harness source is
   original glue (it calls the pinned API and copies no pinned
   implementation), but because it `#include`s GPL-3.0-or-later headers the
   generated `.cpp` and its binary are written to a work directory **outside**
   the repository tree; the tool refuses (exit 3) to write inside it, and
   neither the source file nor the binary is ever committed. What is committed
   is the rendered reference DATA and the harness source's sha256 — exactly the
   disposition DR-0005 chose for the tap bundles.
3. **The pins are enforced, not assumed**: the tool sha256-verifies every
   pinned header it compiles against before building (exit 3 on any mismatch),
   and records those hashes plus the harness source hash in
   `reports/SXT-039/artifacts/reference-index.json`.
4. The harness reproduces the engine's own call sequence for the filter stage
   (cited from `SurgeVoice.cpp`): the float32 `cutoffA` arithmetic, `MakeCoeffs`,
   `updateState`, the per-voice register restore, 64 kernel calls, the register
   and coefficient read-back, and the `memset` + `CM.Reset()` reset path. Its
   tuning provider reproduces `SurgeStorage::note_to_pitch_ignoring_tuning`
   from the pinned **table construction formulas**, so the coefficient input
   matches what the engine's own provider computes at standard 12-TET.
5. **Scope of the resulting claim is bounded and must be stated wherever the
   numbers are used**: this is a *pinned-kernel* reference, not the full
   engine. It covers the algorithm, its four subtypes, the coefficient plane,
   the register semantics and the cutoff control arithmetic. It does **not**
   cover the engine-integrated leg — a real carrier render through the whole
   voice path with the engine's own signal and its own filter-EG trajectory —
   which stays NOT_RUN and is routed as a follow-up needing an oracle host with
   the DR-0005 tap.

## Alternatives rejected

- **Build the full pinned engine on the dispatch worker**: not sanctioned by
  the worker's host rules (shared 8-core box, modest builds only), needs system
  packages the worker may not install, and produces an unpinnable one-off build.
- **Declare the whole reference leg NOT_RUN**: would have shipped a leaf with
  no model-vs-reference evidence at all, when the algorithm's own pinned
  implementation was available and pinnable.
- **Substitute a hand-written float "reference" model**: rejected on
  principle — the only DSP oracle is the pinned Surge code (AGENTS.md).
- **Reuse the SXT-037 tap bundles' OUTPUT column**: that is a different
  algorithm (LP 12 dB). Only their INPUT column is reused, as stimulus, and
  the evidence record says so.

## Consequences

- The leaf reports achieved model-vs-reference numbers at the filter-stage
  boundary without an oracle host, and those numbers are re-verifiable from
  committed data (`tools/run_sxt039_checks.py`) on any machine.
- Every artifact carries `leg: L2-kernel …` naming what the reference is, so
  the number can never be read as full-engine agreement.
- A pin bump (engine or submodule) invalidates the committed references by
  construction: the sha256 gate fails closed and the streams must be
  re-rendered.
- The engine-integrated leg remains an open requirement for this leaf's
  eventual support claim; it is recorded NOT_RUN in
  `reports/SXT-039/EVIDENCE.md` and filed as a follow-up issue.
