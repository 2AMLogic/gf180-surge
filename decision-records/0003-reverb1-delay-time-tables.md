# 0003: Reverb1 DELAY_TIME_TABLES constants (SXT-024)

- **Status**: PROPOSED — pending owner ratification
- **Date**: 2026-09-20
- **Decided by**: Loom builder agent remediating PR #43 (SXT-024 Reverb1),
  under the governance authority of issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25)
  and `docs/REUSE-AUDIT.md` ("Standing rules"); interim until the owner
  ratifies or amends it
- **Consumed by**: #17 (SXT-024, Reverb1 effect slice), PR #43

## Context

The SXT-024 frozen fixed-point model and RTL reproduce the pinned engine's
Reverb1 effect (`sst-effects`, submodule pin
`adcac6950292dacc529651093e7ece2d1c8c0d4b` in `oracle/manifest.json`,
declared license GPL-3.0-or-later). Its `include/sst/effects/Reverb1.h`
`loadpreset()` selects the sixteen composite-tap delay-line lengths from one
of four 16-entry tables indexed by the effect's `shape` parameter, scaled by
`2*roomsize`. These 64 integers (8.8-fixed "256ths of a sample" counter
values) are **opaque designed constants with no construction formula** in the
pinned tree — the same class as the twelve halfband coefficients of record
0002, unlike the oscillator sinc / pitch / dB tables, which the model
recomputes from cited construction formulas.

PR #43 transcribes all 64 values into `model/effects/reverb1/coefficient_plane.py`
(`DELAY_TIME_TABLES`), with file-level provenance (source file, submodule
commit, license) in the module docstring, the model README, and EVIDENCE §9.
The judge review of PR #43 independently verified all 64 values match the
pinned source exactly and that the structure is otherwise original (cited,
not copied). Provenance alone, however, does not satisfy `AGENTS.md`:
"copying Surge-derived code, tables, or assets into this repository requires
a visible license decision record before merge." Record **0002**
(SXT-022 halfband coefficients) explicitly scoped its quoted-constants
decision to those twelve scalars and requires: *"Any future adoption of
further opaque engine constants must extend this record (or add a successor)
before merge."* No successor existed when PR #43 was reviewed; this record is
that successor. `AGENTS.md` also records that **this project has made no
distribution-license determination** for a future chip product.

## Decision options

1. **(a) Quoted facts, in-repo, flagged.** The 64 constants are transcribed
   as cited data (source file, commit, license stated adjacent to them),
   kept in this repository, and explicitly carried into the still-open
   distribution-license determination for the chip product (#25 /
   `AGENTS.md`). Rationale: they are small non-executable numeric facts
   (counter init values), required at control-rate coefficient-build time so
   the frozen model and RTL test bench remain self-contained and
   re-derivable without an oracle fetch; the GPL boundary in this repository
   has always been a repository-content rule, not a distribution ruling
   (0001, "License status of this repository").
2. **(b) External tables, oracle-loaded.** The tables stay in the pinned
   external tree and are loaded at model/RTL build time from the oracle.
   Rejected for now: it would couple the frozen control plane and the CI
   test path to oracle availability, blur the RTL-vs-model input contract
   (the quantized coefficients are model outputs, not runtime data), and
   buy nothing for the repository-content question, which remains open
   either way until the distribution-license determination.

## Decision (interim)

Adopt **(a)**, on the 0002 pattern and strictly scoped:

1. The 64 integers in `DELAY_TIME_TABLES` (`model/effects/reverb1/
   coefficient_plane.py`) are **quoted as data** with file-level provenance
   (source file `include/sst/effects/Reverb1.h`, submodule pin
   `adcac6950292dacc529651093e7ece2d1c8c0d4b`, license
   GPL-3.0-or-later) stated adjacent to the constants. No Surge/SST *code*
   is copied: `loadpreset()`, `update_rtime()`, and `processBlock()`
   structure is re-implemented from the pinned source and cited.
2. **Flag into the open distribution-license determination:** if the chip
   product ships these constants in ROM/firmware, that distribution question
   (#25 / `AGENTS.md`: no determination made) must be answered with these
   constants visibly on the list of GPL-derived content in the artifact.
   This record does not answer it.
3. These 64 values join 0002's twelve halfband coefficients as the only
   engine data constants reproduced in this repository. Any further opaque
   engine constant requires extending this record or adding a successor
   **before merge** (0002's standing requirement, now jointly owned).

## Alternatives considered

- **Option (b) (oracle-loaded)** — see above; rejected for now, may be
  revisited in #25 if the distribution determination or a policy change
  favors external loading.
- **Re-derive the constants from a formula** — rejected: there is no
  construction formula in the pinned tree; any re-derivation would be a
  different (wrong) model, not the pinned reference.
- **Substitute a generic reverb without these tables** — rejected outright:
  an adapted effect does not count toward original-preset coverage
  (`AGENTS.md`, negative control NC-A in `reports/sxt-024/` proves a generic
  Schroeder reverb fails the reference budgets).

## Consequences

- PR #43's merge blocker 2 is satisfied: the transcription now has a visible
  license decision record (this file) per `AGENTS.md` and 0002's
  successor-record requirement.
- The record is **PROPOSED**: the owner may ratify it, or amend it (e.g. to
  option (b)) before merge; until ratification it is the recorded interim
  choice, not an owner ruling.
- The model-vs-reference error budget continues to absorb no
  re-derivation term for these constants (exact reference values are used),
  as with 0002.
- This record establishes no fidelity, preset-support, musical-quality, or
  distribution-license conclusion; it is a repository-content boundary
  decision only.
