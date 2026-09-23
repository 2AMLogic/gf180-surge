# 0007: Chorus constant inventory — no opaque designed constants (SXT-028c)

- **Status:** PROPOSED — pending owner ratification
- **Date:** 2026-09-23
- **Decided by:** Loom builder agent implementing leaf #55 (SXT-028c),
  under the governance authority of issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25)
  and `docs/REUSE-AUDIT.md`; interim until the owner ratifies or amends it
- **Consumed by:** #55 (SXT-028c), PR (branch `loom/leaf-55-chorus`)
- **Extends:** 0003 (quoted designed constants pattern) and 0006
  (Airwindows constants + oracle tap instrumentation); records the
  SXT-028c successor finding required by 0003 §Decision(3) / 0006

## Context

Records **0002** (halfband coefficients), **0003** (Reverb1 delay-time
tables), and **0006** (Galactic delay-length multipliers) quoted engine
data constants into this repository — each time under the standing rule
that "any further opaque engine constant requires extending this record
(or adding a successor) before merge." The SXT-028c frozen model
(`model/effects/type-chorus/chorus_model.py`) reproduces the pinned
engine's Chorus (`src/common/dsp/effects/ChorusEffect{,Impl}.h` at
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
GPL-3.0-or-later) and was audited for the same constant class.

## Finding

The Chorus contains **no opaque designed constants** — nothing of the
0002/0003/0006 class (no tables, no designed integers without a
construction formula). Every constant is either:

1. **Formula-derived** (re-derived in this repository from the cited
   pinned construction, double precision, quantized once):
   the sinc interpolation table (shared
   `model/effects/delay/sinc_table.py`; `SurgeStorage::sinctable1X` is
   `SurgeSincTableProvider`'s table), `envelope_rate_linear`,
   `note_to_pitch_ignoring_tuning`, `db_to_linear`, the biquad
   `coeff_HP`/`coeff_LP2B` builds at Q = 0.707, and the voicepan sqrt law
   `sqrt(0.5 ∓ 0.5·x)·(1/√v)`;
2. **Small cited algorithmic literals** (quoted as data with provenance in
   the model docstring): the time-lag smoothing float32 pair
   (`0.001f`, `1 − 0.001f`, `ChorusEffect::init`), the feedback scale
   `0.5·amp_to_linear(f)` (`setvars`), the triangle-LFO shape
   `(2·|2φ−1| − 1)·depth` (`setvars`), the `0.25/0.75` lipol smoothing
   (`lipol_sse::set_target_smoothed`), the hardclip bound ±1.0
   (`Clippers.h::hardclip_block`), and the init phases `lfophase[i] = i/3`
   (`init`).

## Decision (interim)

1. No quoted table or designed-integer set is adopted for this leaf;
   consequently no quota of GPL-derived data constants is added by
   SXT-028c beyond the small cited literals above, which stay in the
   repository as cited facts under the 0003/0006 repository-content rule.
2. The standing rule continues: any **future** adoption of opaque engine
   constants must extend 0002/0003/0006 or add a successor record **before
   merge**.
3. Flagged into the open distribution-license determination (#25 /
   `AGENTS.md`: no determination made): if the chip product ships these
   literals in ROM/firmware, that question must be answered with them
   visibly on the list of GPL-derived content. This record does not answer
   it.

## Consequences

- The SXT-028c model needs no oracle fetch to re-derive its constants;
  the model and RTL remain self-contained.
- The oracle tap instrumentation used during this leaf (branch
  `sxt028c-tap`, single commit `21056f915` on the pin, tap header sha256
  `556581c6…`) follows DR-0005/DR-0006 method: observation-only,
  single-commit branch on the oracle host, patch script and patched tree
  off-repo, DSP-neutrality shown by bit-identical tapped rendering
  (fixture sha256 match). No new instrumentation policy is created.
- The record is **PROPOSED**: the owner may ratify or amend before merge.
- This record establishes no fidelity, preset-support, musical-quality, or
  distribution-license conclusion; it is a repository-content boundary
  decision only.
