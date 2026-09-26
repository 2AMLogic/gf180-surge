# 0015: Airwindows "Logical" (id 4) quoted constants, and the MIT licence of the vendored `libs/airwindows` subtree (SXT-028k)

- **Status:** PROPOSED — pending owner ratification
- **Date:** 2026-09-26
- **Decided by:** Loom builder agent implementing leaf
  [#63](https://github.com/2AMLogic/gf180-surge/issues/63) (SXT-028k), under
  the governance authority of issue
  [#25](https://github.com/2AMLogic/gf180-surge/issues/25) and
  `docs/REUSE-AUDIT.md`; interim until the owner ratifies or amends it
- **Consumed by:** #63 (SXT-028k), `model/effects/aw-4/`, `rtl/effects/aw-4/`
- **Extends:** [0003](0003-reverb1-delay-time-tables.md) (quoted designed
  constants, the DR-0003 pattern)
- **Refines:** [0006](0006-airwindows-galactic-constants-and-taps.md) — same
  vendored subtree, and this record corrects that record's licence
  characterisation of it (see "Finding", below). It changes no decision 0006
  made and no SXT-028a artifact.
- **Related:** [0007](0007-chorus-constant-inventory.md),
  [0012](0012-distortion-halfband-and-waveshaper-tables.md) (constant
  inventory pattern), [0008](0008-sine-wave-remap-table.md) (derived-table
  pattern)

## Context

The SXT-028k frozen fixed-point model and RTL reproduce the pinned engine's
Airwindows algorithm **id 4, "Logical"**
(`libs/airwindows/src/Logical4Proc.cpp`, `Logical4.{h,cpp}` at
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`),
dispatched through the shared adapter
`src/common/dsp/effects/airwindows/AirWindowsEffect.{h,cpp}`. Three
repository-content questions arise.

### Finding: the vendored `libs/airwindows` subtree is MIT, not GPL

Record 0006 described this same subtree as "declared license
GPL-3.0-or-later". The pinned tree says otherwise, at the subtree root:

- `libs/airwindows/LICENSE` — verbatim MIT License, "Copyright (c) 2018
  Chris Johnson";
- `libs/airwindows/README.md` — "This code is an adapted version of the
  Airwindows plugins <https://github.com/airwindows/airwindows/> … Airwindows
  is released under the MIT license as described in the LICENSE file in this
  directory."

The *combined work* Surge XT distributes is GPL-3.0-or-later, and the
adapter that calls into this subtree
(`src/common/dsp/effects/airwindows/AirWindowsEffect.{h,cpp}`) carries
Surge's GPL header. But the subtree's own files carry the subtree's own
permissive grant, and MIT is inbound-compatible with this repository's
Apache-2.0 convention (`LICENSE`) with attribution retained. That is a
*better* position than 0006 assumed, not a worse one, so nothing built under
0006 is invalidated; 0006's own conservative handling (cite structure, quote
only opaque designed integers, keep the executable engine external) remains
correct and is what this record continues.

This record does **not** make a distribution-licence determination. The
project has made none (`AGENTS.md`), and the GPL-3.0-or-later question is
untouched by this finding for everything that is Surge-authored: the adapter
semantics this leaf depends on (the 12-slot param block, `subblock_factor`,
the `OnePoleLag` parameter smoothing, the streamed-id registry ordering) are
read from GPL-3.0-or-later Surge files and are **cited, never copied**.

### (a) Quoted designed constants — a small, enumerated set

`Logical4::processReplacing` contains opaque designed literals with no
construction formula anywhere in the pinned tree. They cannot be
re-derived; they are quoted as data, with file-level provenance, exactly as
0003 established. The complete inventory quoted by
`model/effects/aw-4/logical4_model.py` is:

| Literal | Role in the pinned algorithm |
|---|---|
| `0.618033988749894848204586` (`fpOld`; `fpNew = 1 - fpOld`) | the "golden ratio!" input/history blend of the ButterComp detector |
| `0.000782`, `0.000819`, `0.000857` | the three stage speed constants |
| `10.0`, `99.0`, `1.0` (attack map) | `attackspeed = 10 / sqrt(C²·99 + 1)` |
| `15.0`, `2.99999` | ratio map `sqrt(B²·15 + 1) − 1` and its clamp |
| `40.0`, `20.0` | the threshold / makeup ±20 dB maps |
| `0.0445556` (`intensity`) | Power-Sag drive |
| `0.003300223685324102874217` (`powerSag`) | Power-Sag compression coupling |
| `2.42` (`depthA/B/C`), `1`/`498` offset clamps | Power-Sag tap depth |
| `0.000001` | Power-Sag accumulator leak |
| `0.5` | Power-Sag clamp floor |
| `1.57079633` | bridge-rectifier domain clamp (π/2 + 3.2e-9 — the pinned literal, **not** π/2) |
| `36.0` | the "+18 dB hard clip on insano inputs" |
| `0.001` | the polarity-detector floor on `inputpos`/`inputneg` |
| `1000` / `499` / `499` | the sag line allocation, mirror offset and `gcount` reload |

That is the whole list. Every other coefficient in the frozen model is
re-derived at run time from a cited formula.

### (b) Derived tables — NOT quoted

The on-chip replacements for the pinned `sin(x)` and `1 − cos(x)` libm calls
are two 806-word Q1.31 tables built in `model/effects/aw-4/tables.py` from
the mathematical functions themselves. The file *is* the construction
formula; regenerating it reproduces every word. This is the
`sinc_table.py` / DR-0007 / DR-0008 class (re-derivation from a cited
formula), not an adoption of designed data. Only the *domain clamp*
`1.57079633` above is quoted.

### (c) No code, and no oracle instrumentation

No Airwindows or Surge source file is copied into this repository. Unlike
0006, this leaf needs **no** tap instrumentation decision: Logical has no
RNG-seeded or wall-clock-dependent state (`Logical4()` initialises every
register deterministically, `fpFlip` starts `true`, and the float
`processReplacing` at this pin performs no dither/noise-shaping), so nothing
about it requires a patched engine. The reference leg is NOT_RUN here purely
because no oracle host is reachable (`reports/SXT-028k/EVIDENCE.md`), and
when it runs it can run against an unmodified pinned build at the adapter
boundary.

## Decision (interim)

1. **Licence of the subtree, recorded.** `libs/airwindows/` at the engine pin
   is **MIT (c) 2018 Chris Johnson**; the Surge adapter around it is
   GPL-3.0-or-later. Both are cited at file level wherever this leaf relies
   on them. 0006's "GPL-3.0-or-later" characterisation of the same subtree is
   superseded by this finding; 0006's decisions stand unchanged.
2. **Quoted constants.** The inventory in (a) is transcribed as cited data in
   `model/effects/aw-4/logical4_model.py`, with file-level provenance in the
   module docstring and in `model/effects/aw-4/README.md` (source file,
   engine pin, licence, copyright holder). The RTL holds **no** independent
   copy of any of them: `rtl/effects/aw-4/logical4_core.sv` receives every
   numeric constant through the streamed control plane (`cfg.hex`), so a
   constant cannot drift between the two sides and the quoted set has exactly
   one home in this repository.
3. **Attribution.** MIT requires the copyright notice and permission notice
   to accompany "copies or substantial portions of the Software". This
   repository copies neither code nor a substantial portion; it quotes an
   enumerated constant list and cites structure. Attribution is nonetheless
   retained in the model docstring, the model README, and this record, which
   is the standard this project applies to every third-party adoption
   (`docs/REUSE-AUDIT.md`).
4. **Derived tables.** The two sin / one-minus-cos ROM images
   (`rtl/effects/aw-4/{sin,omc}_q31.hex`) and their generator are original to
   this repository (Apache-2.0) and are regenerable from `tables.py`; they
   are not third-party adopted data and need no further grant.
5. **Flagged into the open distribution-licence determination.** If the chip
   product ships these constants in ROM/firmware, the question must be
   answered with this list visibly on the inventory — under its actual MIT
   grant, alongside the GPL-derived items 0003/0006/0012/0014 list.

## Consequences

- SXT-028k can state file-level provenance for every constant it holds and
  can show that no Airwindows or Surge code is present in this repository.
- The RTL's "structure only, constants streamed" rule becomes a checkable
  property, and `tests/test_sxt028k.py` checks it (no quoted literal appears
  in the SystemVerilog sources).
- Record 0006's licence line for `libs/airwindows` should be read against
  this record. No SXT-028a evidence, artifact, or verdict changes.
- The record is **PROPOSED**: the owner may ratify or amend (for example, to
  the "load constants from the oracle at build time" option 0003 keeps open)
  before merge.
- This record establishes no fidelity, preset-support, musical-quality, cost,
  or distribution-licence conclusion. It is a repository-content and
  attribution boundary only.
