# GPL-boundary register

Table-level inventory of every third-party-derived constant table or constant
held in this repository, with its upstream file, pinned revision, upstream
licence, decision record and provenance citation. Governance issue
[#25](https://github.com/2AMLogic/gf180-surge/issues/25) (operator ruling of
2026-10-02, item 2); implemented by issue #370.

This register is an **inventory only**. It decides nothing, moves no constant,
and is not a distribution-licence determination (`AGENTS.md`: none has been
made). The operator's position is that GPL-derived constants in this public
repository are acceptable for now, cited with provenance (option (a) of
[record 0003](0003-reverb1-delay-time-tables.md), the
[0002](0002-halfband-coefficients.md) precedent); if the work is productized
the GPL-derived parts get a clean-room reimplementation, or GPL licensing is
considered then. This register is the complete list such a clean-room effort
would start from. It is an operator business decision, not legal advice, and
productization reopens it.

## How this relates to the other provenance sources

- `decision-records/provenance.json` stays the **file-level** provenance
  source. This register is the **table-level** view and does not replace it.
- Neither source is assumed complete. `python3 tools/check_provenance.py`
  cross-checks them (rules `register-*`) and the cases where they disagree are
  recorded here, not hidden: see "Provenance exceptions" (material a decision
  record classifies as quoted data but that has no manifest row) and the
  `licence reconciled` and `provenance incomplete` statuses.
- **New GPL-derived (or other third-party quoted) material goes into this
  register in the same PR that adds it** (`docs/REUSE-AUDIT.md`, "Adoption
  mechanics"). The checker fails a quoted-constants manifest row that has no
  register row here.

## Inclusion rules

A constant belongs in one of the two register tables when it is **quoted data**:
an opaque designed value or table transcribed from a pinned upstream file, with
no construction formula the repository re-derives. The licence of the
**upstream file the value was taken from** decides the table, not the licence
of the program around it.

| Kind | Where it goes | Reason |
|---|---|---|
| Quoted opaque designed value or table, upstream GPL-3.0-or-later | "GPL-derived register" | what a clean-room effort must replace |
| Quoted value, upstream file MIT (`libs/airwindows`, DR-0015) | "MIT-sourced quoted constants" | MIT constants are **not** GPL-derived; the surrounding Surge adapter is GPL-3.0-or-later and that does not change the licence recorded for the constant |
| Formula-rederived value, structural literal, external-asset identity | "Reviewed exclusions" | nothing is adopted by reproducing it; the exclusion records why |
| Quoted value whose upstream file or revision cannot be established from a record or manifest row | the register table that matches its licence, status `provenance incomplete` | listed, never guessed |

Register rows are per table or constant (symbol), not per file. Derived
artifacts (the quantized `*_Q` words and the generated ROM images) are covered
by the row of the quoted value they were built from, except where a generated
file is itself a committed copy of quoted data (row `G-21`).

## Schema

Every row of the two register tables has exactly these columns, none empty:

`ID | In-repo file | Symbol / table | Upstream file | Pinned revision |
Upstream licence | Decision record | Provenance citation | Status | Notes`

- **Pinned revision**: a full 40-hex commit (the engine pin, or the submodule
  pin from `oracle/manifest.json`), or `incomplete` when the status is
  `provenance incomplete`.
- **Upstream licence**: `GPL-3.0-or-later` or `MIT`.
- **Decision record**: a four-digit record number that exists and is indexed.
- **Provenance citation**: `manifest:<path>` (a `quoted-constants` row of
  `decision-records/provenance.json` for that path, citing the same record and
  the same pinned commit) or `exception:<ID>` (a row of "Provenance
  exceptions" that lists the in-repo file).
- **Status**: `registered`, `provenance incomplete`, or `licence reconciled`
  (the register licence deliberately differs from the manifest row's licence;
  Notes must cite the record that reconciles it).

## GPL-derived register

| ID | In-repo file | Symbol / table | Upstream file | Pinned revision | Upstream licence | Decision record | Provenance citation | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|
| G-01 | model/voice/voice_model.py | HALFBAND_A (6 allpass coefficients, order 12 steep; quantized as HALFBAND_A_Q) | libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h | e92d93a92beabde03fa4ab767b285fa21c6608d6 | GPL-3.0-or-later | 0002 | manifest:model/voice/voice_model.py | registered | no construction formula in the pinned tree |
| G-02 | model/voice/voice_model.py | HALFBAND_B (6 allpass coefficients, order 12 steep; quantized as HALFBAND_B_Q) | libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h | e92d93a92beabde03fa4ab767b285fa21c6608d6 | GPL-3.0-or-later | 0002 | manifest:model/voice/voice_model.py | registered | streamed to the RTL through init words; RTL holds no copy |
| G-03 | model/effects/reverb1/coefficient_plane.py | DELAY_TIME_TABLES (4 x 16 = 64 delay-time integers) | include/sst/effects/Reverb1.h (loadpreset) in sst-effects | adcac6950292dacc529651093e7ece2d1c8c0d4b | GPL-3.0-or-later | 0003 | manifest:model/effects/reverb1/coefficient_plane.py | registered | record 0003 is PROPOSED; option (a) interim |
| G-04 | model/oscillators/wavetable/wt_model.py | HRFILTER_63 (63-tap mip halfband) | src/common/dsp/Wavetable.cpp (hrfilter[63], MipMapWT) | 58914e59c608ed4384ba6002e44c3465c58b2e71 | GPL-3.0-or-later | 0004 | manifest:model/oscillators/wavetable/wt_model.py | registered | wavetable payloads stay external, see X-01 |
| G-05 | model/oscillators/sine/README.md | wave_remap (20-entry streaming-migration table) | src/common/dsp/oscillators/SineOscillator.cpp (handleStreamingMismatches) | 58914e59c608ed4384ba6002e44c3465c58b2e71 | GPL-3.0-or-later | 0008 | manifest:model/oscillators/sine/README.md | registered | model/oscillators/sine/sine_model.py re-implements the control flow and holds no copy of the table (manifest row) |
| G-06 | model/oscillators/sine/README.md | load_xml rev<=27 remap of odd raw shapes 1..7 to 28..31 | SurgePatch::load_xml (file path not stated in any record) | incomplete | GPL-3.0-or-later | 0008 | manifest:model/oscillators/sine/README.md | provenance incomplete | quoted in the README finding; DR-0008 inventories only wave_remap; upstream file and revision are not recorded for this mapping |
| G-07 | model/effects/type-distortion/distortion_model.py | HB_A_SOFT (3 coefficients, HalfRateFilter(3, false)) | libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h | e92d93a92beabde03fa4ab767b285fa21c6608d6 | GPL-3.0-or-later | 0012 | manifest:model/effects/type-distortion/distortion_model.py | registered | quantized as part of HB_COEFFS_Q |
| G-08 | model/effects/type-distortion/distortion_model.py | HB_B_SOFT (3 coefficients, HalfRateFilter(3, false)) | libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h | e92d93a92beabde03fa4ab767b285fa21c6608d6 | GPL-3.0-or-later | 0012 | manifest:model/effects/type-distortion/distortion_model.py | registered | quantized as part of HB_COEFFS_Q |
| G-09 | model/effects/type-distortion/distortion_model.py | HB_A_STEEP (3 coefficients, HalfRateFilter(3, true)) | libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h | e92d93a92beabde03fa4ab767b285fa21c6608d6 | GPL-3.0-or-later | 0012 | manifest:model/effects/type-distortion/distortion_model.py | registered | quantized as part of HB_COEFFS_Q |
| G-10 | model/effects/type-distortion/distortion_model.py | HB_B_STEEP (3 coefficients, HalfRateFilter(3, true)) | libs/sst/sst-filters/include/sst/filters/HalfRateFilter.h | e92d93a92beabde03fa4ab767b285fa21c6608d6 | GPL-3.0-or-later | 0012 | manifest:model/effects/type-distortion/distortion_model.py | registered | quantized as part of HB_COEFFS_Q |
| G-11 | model/effects/type-distortion-sse/quad_shapers.py | OJD_M17_C, OJD_P11_C, OJD_M03_C, OJD_P09_C (OJD breakpoints -1.7f, 1.1f, -0.3f, 0.9f) | include/sst/waveshapers/Saturators.h (OJD) | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | no manifest row names record 0014; see E-1 |
| G-12 | model/effects/type-distortion-sse/quad_shapers.py | OJD_DENLOW_C, OJD_DENHIGH_C (1/(4*(1-0.3f)), 1/(4*(1-0.9f)) as float32) | include/sst/waveshapers/Saturators.h (OJD) | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | the float32 expression, not a rounded decimal, is the quoted value |
| G-13 | model/effects/type-distortion-sse/quad_shapers.py | TANH_9_C, TANH_27_C, TANH_9_S, TANH_27_S (rational approximant constants 9 and 27) | include/sst/waveshapers/Saturators.h (TANH) | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | one upstream pair, held in two word formats; with G-11, G-12, G-14, G-15 this is the 11 streamed init words of record 0014 (SHAPER_INIT_WORDS) |
| G-14 | model/effects/type-distortion-sse/quad_shapers.py | ADAA_TOL_C (antiderivative tolerance 0.0001) | include/sst/waveshapers/ADAA.h | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | upstream double narrowed through set1_ps |
| G-15 | model/effects/type-distortion-sse/quad_shapers.py | DCBLOCK_FAC_C (dcBlock pole 0.9999f) | include/sst/waveshapers/DCBlocker.h | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | inventoried by record 0014 |
| G-16 | model/effects/type-distortion-sse/sse_tables.py | TABLES["fuzz1"] / build_fuzz1_row (FuzzTable<1>, 1025 words) | include/sst/waveshapers/Fuzzes.h and WaveshaperLUT.h (LUTBase<1024, FuzzTable<1>>) | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | classified quoted data by the 2026-10-08 (#135) amendment of record 0014, conservatively, pending the NOT_RUN pinned-host leg; the generator reproduces the values |
| G-17 | rtl/effects/type-distortion-sse/ws_sse_q29.hex | FuzzTable<1> rows of the generated ROM (words 1024..2048 of 2049) | include/sst/waveshapers/Fuzzes.h and WaveshaperLUT.h (LUTBase<1024, FuzzTable<1>>) | dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce | GPL-3.0-or-later | 0014 | exception:E-1 | registered | committed generated ROM, a build product of G-16 and itself a committed copy of the quoted table; the wst_sine rows of the same file are re-derived, see X-06 |
| G-18 | model/effects/type-chorus/chorus_model.py | LP_TIME, LPINV_TIME (float32 0.001f and 1 - 0.001f lag pair) | src/common/dsp/effects/ChorusEffect.h and ChorusEffectImpl.h (ChorusEffect::init) | 58914e59c608ed4384ba6002e44c3465c58b2e71 | GPL-3.0-or-later | 0007 | exception:E-2 | registered | record 0007 classes these as small cited literals kept as cited facts and requires them on the GPL-derived list |
| G-19 | model/effects/type-chorus/chorus_model.py | feedback scale 0.5*amp_to_linear, triangle-LFO shape (2*abs(2*phase-1)-1)*depth, init phases lfophase[i] = i/(voices-1) | src/common/dsp/effects/ChorusEffect.h and ChorusEffectImpl.h (setvars, init) | 58914e59c608ed4384ba6002e44c3465c58b2e71 | GPL-3.0-or-later | 0007 | exception:E-2 | registered | record 0007 writes the init phases as i/3 (four voices); the model docstring writes i/(v-1) |
| G-20 | model/effects/type-chorus/chorus_model.py | lipol 0.25/0.75 smoothing recurrence (applied in the RTL; raw targets here) | src/common/dsp/vembertech/lipol.h (lipol_sse::set_target_smoothed) | 58914e59c608ed4384ba6002e44c3465c58b2e71 | GPL-3.0-or-later | 0007 | exception:E-2 | registered | inventoried by record 0007 |
| G-21 | model/effects/type-chorus/chorus_model.py | HARD_CLIP (hardclip_block bound +-1.0) | Clippers.h hardclip_block in libs/sst/sst-basic-blocks (sub-path elided in the model docstring and in record 0007) | incomplete | GPL-3.0-or-later | 0007 | exception:E-2 | provenance incomplete | the submodule is pinned in oracle/manifest.json (a32b8aec14d661e415bb676bb2e2a0a4da4efc96) but no record states which revision this literal was read at |

## MIT-sourced quoted constants

These are quoted values whose upstream file lies in the vendored
`libs/airwindows` subtree, which carries its own MIT licence (`libs/airwindows/LICENSE`; the holder
and notice are restated in record
[0015](0015-airwindows-logical-quoted-constants.md), "Finding"). They are **not GPL-derived**. The Surge adapter around that subtree
(`AirWindowsEffect.{h,cpp}`) is GPL-3.0-or-later; it is cited for structure and
nothing from it is copied. Attribution is retained in the model docstrings, the
model READMEs and record 0015.

| ID | In-repo file | Symbol / table | Upstream file | Pinned revision | Upstream licence | Decision record | Provenance citation | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|
| M-01 | model/effects/aw-4/logical4_model.py | FP_OLD, FP_NEW (0.618033988749894848204586 and 1 - FP_OLD) | libs/airwindows/src/Logical4Proc.cpp (Logical4::processReplacing) | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | "golden ratio" detector blend |
| M-02 | model/effects/aw-4/logical4_model.py | SPEED_A, SPEED_B, SPEED_C (0.000782, 0.000819, 0.000857) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-03 | model/effects/aw-4/logical4_model.py | ATTACK_BASE, ATTACK_SPAN (10.0, 99.0, 1.0 attack map) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-04 | model/effects/aw-4/logical4_model.py | RATIO_SPAN, RATIO_CLAMP (15.0, 2.99999) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-05 | model/effects/aw-4/logical4_model.py | GAIN_SPAN, GAIN_OFFSET (40.0, 20.0 threshold and makeup maps) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-06 | model/effects/aw-4/logical4_model.py | INTENSITY (0.0445556) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | Power-Sag drive |
| M-07 | model/effects/aw-4/logical4_model.py | POWER_SAG (0.003300223685324102874217) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-08 | model/effects/aw-4/logical4_model.py | SAG_DEPTH (2.42) and the 1 / 498 offset clamps | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-09 | model/effects/aw-4/logical4_model.py | SAG_LEAK (0.000001) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-10 | model/effects/aw-4/logical4_model.py | CLAMP_FLOOR (0.5) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-11 | model/effects/aw-4/logical4_model.py | BR_MAX (1.57079633, bridge-rectifier domain clamp) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | the pinned literal, not pi/2 |
| M-12 | model/effects/aw-4/tables.py | BR_MAX (1.57079633); the sin and 1-cos tables themselves are re-derived, see X-04 | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/tables.py | registered | inventoried by record 0015 |
| M-13 | model/effects/aw-4/logical4_model.py | HARD_CLIP (36.0) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-14 | model/effects/aw-4/logical4_model.py | POS_FLOOR (0.001) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-15 | model/effects/aw-4/logical4_model.py | LINE_WORDS, LINE_MIRROR, GCOUNT_MAX (1000, 499, 499) | libs/airwindows/src/Logical4Proc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0015 | manifest:model/effects/aw-4/logical4_model.py | registered | inventoried by record 0015 |
| M-16 | model/effects/aw-49/galactic_model.py | DELAY_MULT multipliers (3407, 1823, 859, 331, 4801, 2909, 1153, 461, 7607, 4217, 2269, 1597) | libs/airwindows/src/GalacticProc.cpp and Galactic.h | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0006 | manifest:model/effects/aw-49/galactic_model.py | licence reconciled | record 0006 and the manifest row call these GPL-3.0-or-later; record 0015 finds the libs/airwindows subtree is MIT and supersedes that characterisation (0006's decisions stand) |
| M-17 | model/effects/aw-49/galactic_model.py | DELAY_M (256, vibrato predelay) | libs/airwindows/src/GalacticProc.cpp | 58914e59c608ed4384ba6002e44c3465c58b2e71 | MIT | 0006 | manifest:model/effects/aw-49/galactic_model.py | licence reconciled | named by record 0006 decision (a); licence per record 0015 |
| M-18 | model/effects/aw-49/galactic_model.py | DELAY_MULT array sizes (6480, 3660, 1720, 680, 9700, 6000, 2320, 940, 15220, 8460, 4540, 3200) | libs/airwindows/src/Galactic.h (presumed array declarations) | incomplete | MIT | 0006 | manifest:model/effects/aw-49/galactic_model.py | provenance incomplete | licence per record 0015; used by the model as pinned array sizes; record 0006 inventories the multipliers and delayM only, so the source file for these twelve integers is not recorded |
| M-19 | model/effects/aw-49/galactic_model.py | OLD_FPD0 (429496.7295) and OLD_FPD_SCALE (0.0000000000618) | libs/airwindows/src/Galactic.h and GalacticProc.cpp (presumed) | incomplete | MIT | 0006 | manifest:model/effects/aw-49/galactic_model.py | provenance incomplete | licence per record 0015; model comments say "pinned"; not inventoried by record 0006 |

## Provenance exceptions

Material a decision record classifies as quoted data, with no `quoted-constants`
row in `decision-records/provenance.json`. Each exception is **checkable**: the
checker fails if a listed file does not exist, or if a `quoted-constants`
manifest row now covers it (the exception is stale and must be removed and the
register rows re-pointed at `manifest:<path>`).

| ID | In-repo files | Decision record | Reason | Closing action |
|---|---|---|---|---|
| E-1 | model/effects/type-distortion-sse/quad_shapers.py; model/effects/type-distortion-sse/sse_tables.py; rtl/effects/type-distortion-sse/ws_sse_q29.hex | 0014 | record 0014 classifies eleven designed scalars and, after the 2026-10-08 (#135) amendment, the FuzzTable<1> row as quoted data with provenance, but no manifest row names record 0014 and none covers these files | add `quoted-constants` rows for these files (needs the files to corroborate the row; `quad_shapers.py` and `sse_tables.py` are byte-frozen, see `docs/byte-frozen-sources.md`) |
| E-2 | model/effects/type-chorus/chorus_model.py | 0007 | record 0007 keeps the small cited chorus literals in the repository as cited facts and requires them on the GPL-derived list, but no manifest row covers the file | add a `quoted-constants` row for the file (byte-frozen, see `docs/byte-frozen-sources.md`) |

## Reviewed exclusions

Candidates reviewed and **not** registered, with the reason. An exclusion is a
classification for this inventory only; it does not change what the record or
the code claims.

| ID | Decision record | In-repo file | Symbol / table | Classification | Reason |
|---|---|---|---|---|---|
| X-01 | 0004 | compiler/assets/wavetable.py | wavetable asset identity (path, sha256, size, dims) | external-identity | no payload bytes are stored; payloads stay in the external pinned tree and a hash mismatch aborts the build |
| X-02 | 0007 | model/effects/type-chorus/chorus_model.py | sinc table, envelope_rate_linear, note_to_pitch_ignoring_tuning, db_to_linear, coeff_HP / coeff_LP2B at Q = 0.707, voicepan sqrt law | re-derived | re-derived from cited construction formulas (record 0007 finding item 1) |
| X-03 | 0012 | model/effects/type-distortion/ws_tables.py | wst_soft, wst_hard, wst_asym waveshaper rows | re-derived | recomputed from closed-form expressions; the committed ROM is byte-checked against the generator |
| X-04 | 0015 | model/effects/aw-4/tables.py | sin and 1-cos Q1.31 tables (806 words each) | re-derived | built from the mathematical functions; only the domain clamp is quoted, see M-12 |
| X-05 | 0014 | model/effects/type-distortion-sse/quad_shapers.py | structural scalars 1.0, 0.5, 256.0, 512.0, 0.0625, N/2 = 512, N-1 = 1023 | structural | index-mapping shape and LUT size, not designed coefficients (record 0014 class (b)) |
| X-06 | 0014 | model/effects/type-distortion-sse/sse_tables.py | wst_sine row (1024 words) and the matching rows of ws_sse_q29.hex | re-derived | closed form (float)sin((i - 512) * pi / 512); the one row record 0014 still classifies re-derived |
| X-07 | none | model/effects/type-phaser/README.md | phaser constant inventory | no-opaque-constants-claimed | the README asserts no opaque designed constants and no decision record covers the phaser; this register did not independently verify that assertion |
| X-08 | none | model/effects/type-reverb 2/README.md | reverb2 constant inventory | no-opaque-constants-claimed | the README asserts no opaque designed constants and no decision record covers reverb2; this register did not independently verify that assertion |

## Declared limits

- Completeness is bounded by the decision-record inventories plus a targeted
  review of the files they name. The Galactic rows M-18 and M-19 show a record
  can undercount; an unrecorded quoted value elsewhere in `model/` would not be
  found by this register or by the checker. The checker enforces the
  manifest-to-register direction, the register-to-manifest direction, and that
  every decision record that declares quoted data is accounted for here. It
  does not read model source for literals.
- Committed generated evidence that carries quantized copies of quoted values
  (stream files such as `cfg.hex`, init streams and tail fixtures under
  `reports/`) is not enumerated row by row; a clean-room effort regenerates
  them from the model.
- This register states provenance and licence classification as recorded in the
  decision records. It establishes no fidelity, preset-support or
  musical-quality claim and makes no distribution-licence determination.
