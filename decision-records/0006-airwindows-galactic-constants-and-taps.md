# 0006: Airwindows "Galactic" delay-length constants and oracle tap instrumentation (SXT-028a)

- **Status:** PROPOSED — pending owner ratification
- **Date:** 2026-09-22
- **Decided by:** Loom builder agent implementing leaf #53 (SXT-028a),
  under the governance authority of issue [#25](https://github.com/2AMLogic/gf180-surge/issues/25)
  and `docs/REUSE-AUDIT.md`; interim until the owner ratifies or amends it
- **Consumed by:** #53 (SXT-028a), PR (leaf branch `loom/leaf-53-galactic`)
- **Extends:** 0003 (quoted designed constants, DR-0003 pattern); follows
  0005 (oracle tap instrumentation method)

## Context

The SXT-028a frozen fixed-point model and RTL reproduce the pinned engine's
Airwindows algorithm id 49 ("Galactic",
`libs/airwindows/src/GalacticProc.cpp` at
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
declared license GPL-3.0-or-later). Two governance questions arise that no
existing record covers.

**(a) Quoted designed integers.** `processReplacing()` scales twelve delay
lines with the literal multipliers `3407, 1823, 859, 331, 4801, 2909, 1153,
461, 7607, 4217, 2269, 1597` (samples at size 1) plus `delayM = 256` for the
vibrato predelay. These are opaque designed integers with no construction
formula in the pinned tree — the same class as the sixty-four reverb1
delay-time table values of record **0003** ("quoted as data with file-level
provenance and a license decision record"), and unlike the formula-derived
coefficient constants, which the model re-derives from the cited source.

**(b) Oracle tap instrumentation.** No surgepy API exposes an effect slot's
internal signals. Three quantities are required for the slot-boundary
reference comparison and are not derivable from patch state:

1. the adapter-boundary input/output float blocks of the Airwindows slot
   (`AirWindowsEffect::process`'s `dataL/dataR`/`outL/outR`);
2. the Galactic constructor's random seeds `fpdL/fpdR` — drawn from the C
   `rand()` stream that `SurgeSynthesizer`'s constructor seeds with
   `srand((unsigned)time(nullptr))`, i.e. **wall-clock dependent**;
3. the per-sample vibrato phase `vibM` — its advance uses the adapter's
   *lagged* float parameter (OnePoleLag ramping from 0 at load), so the
   early trajectory is not reproducible from static parameters.

Record **0005** (SXT-037) established the method: instrument the pinned
tree externally on the oracle host on a single-commit branch, keep the patch
script and patched tree off-repo, pin their hashes here, and enforce a
DSP-neutrality gate. This record is the SXT-028a successor under 0005.

## Decision (interim)

1. **(a) Quoted constants.** The twelve delay-length multipliers and
   `delayM = 256` are transcribed as cited data in
   `model/effects/aw-49/galactic_model.py` with file-level provenance in the
   module docstring and model README (source file, engine pin, license).
   No Airwindows *code* is committed: the structure is re-implemented from
   the pinned source and cited. Flagged into the open
   distribution-license determination (#25 / `AGENTS.md`: no determination
   made): if the chip product ships these constants in ROM/firmware, that
   question must be answered with these constants visibly on the list of
   GPL-derived content.
2. **(b) Tap instrumentation.** The pinned engine tree is instrumented on
   the oracle host on branch `sxt028a-tap` (single commit `962503f3e` on top
   of the pin, verified by the patch script):
   - a read-only tap sink (`src/common/sxt028a_tap.h`) enabled only when
     `SXT028A_TAP_DIR` is set;
   - a dump call in `AirWindowsEffect::process` (adapter-boundary in/out
     blocks, slot index, streamed algorithm id);
   - a dump call in the `Galactic` constructor (`fpdL/fpdR`) and in
     `Galactic::processReplacing` (per-sample `vibM/oldfpd/countM/iirAL/
     iirBL/countI/fbAL/fbAR` — the control-plane capture and the
     internal-state verification data).
   The tap is observation-only: it changes no arithmetic, branch, or data
   path.
3. **Neutrality gate, adapted for nondeterministic fixtures.** 0005's
   bit-identical taps-on/off gate assumed a deterministic carrier. Every
   SXT-028a carrier is *conditioned-on-tap* class (scene drift > 0 and/or
   the wall-clock-seeded aw49 vibrato — measured: 3 fresh instances give
   pairwise RMS deltas ~2e-2 against signal RMS 3.7e-2, and the all-off dry
   bus is itself non-identical). The gate is therefore run on a PROBE: a
   deterministic carrier (first candidate passing a 2x bit-identical
   self-check) with an injected AW-49 insert (Modulation 0 → frozen
   vibrato) rendered taps-off x2 (must be identical), then taps-on vs
   taps-off (must be identical), plus a cross-build check against the
   pre-existing build-py311 tree. The structural side is pinned: the
   `sxt028a-tap` branch is a single-commit diff touching only the tap
   header and the three guarded dump calls. The probe is infrastructure
   only — it is never a fixture and supports no preset claim.

## Record hashes (oracle host)

- patch script `~/oracle/sxt028a_tap_patch.py`: pinned on the oracle host
  next to the script (written by the leaf agent; the applied result is
  reproduced by the pinned branch commit below);
- generated header `src/common/sxt028a_tap.h` (in the external tree):
  sha256 `d4c8426b2743ec0a52d683ea7aa08a3317a458f51caa859c9e857603432cb27d`
  (final revision, before the galstate extension — the extension is part of
  the same pinned branch commit);
- the resulting engine build is pinned by the version string the engine
  reports: `1.4.sxt028a-tap.962503f3e` (branch `sxt028a-tap`, single commit
  `962503f3e` on top of the engine pin `58914e59c608ed4384ba6002e44c3465c58b2e71`).

## Consequences

- The SXT-028a reference leg compares the leaf model against the engine at
  the exact slot boundary (adapter in/out), keeping the leaf scoped to "one
  algorithm per leaf" even though every carrier also has unlanded sibling
  FX (complete-wet renders refused, fail-closed).
- Evidence renders are reproducible only on the oracle host with the
  `build-py311-aw49` build of the `sxt028a-tap` branch;
  `tools/render_aw49_reference.py` fails closed (exit 3) elsewhere; the
  non-canonical fixture npz artifacts are oracle-host-resident with sha256
  pinned in their sidecars (0005 precedent).
- The wall-clock-seeded vibrato randomization is a REPEATABILITY finding for
  SXT-013/SXT-012: presets with an active AW-49 Modulation > 0 (and any
  preset whose voices use free-run drift) are not in the bit-identical
  repeatability class. This is recorded per fixture and in EVIDENCE.md; it
  gates nothing here.
- The record is **PROPOSED**: the owner may ratify or amend (e.g. to
  oracle-loaded constants per 0003's option (b)) before merge.
- This record establishes no fidelity, preset-support, musical-quality, or
  distribution-license conclusion; it is a repository-content boundary and
  instrumentation-method decision only.
