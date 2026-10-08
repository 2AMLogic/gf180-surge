# SXT-307 evidence record — LP 24 dB full-engine tap (serves #101 F-038-1)

Issue: #307 · Date: 2026-10-08 · Decision record: `decision-records/0019-lp24-full-engine-tap.md`
(PROPOSED). Engine pin (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, submodules per
`oracle/manifest.json`, tree clean before patching.

**Claim discipline.** This record establishes only that an observation tap for the
LP 24 dB filter unit exists, builds, is rejected when absent (neutrality on the one
deterministic control is **STALE**: quantized-WAV equality only, raw-sample
re-derivation NOT_RUN; see §2), and what the native control plane looks like relative to the
committed SXT-038 case plans. It establishes **no** model-vs-reference agreement,
**no** full-engine fidelity, **no** preset coverage, **no** musical quality and **no**
FPGA/gf180mcu or hardware claim. #101 is not closed by it.

## 1. Execution route and provenance (acceptance 1)

- Route: #307 option 1 (agent decision on the issue): author and validate on an
  accessible external host — this Linux x86_64 dispatch worker, in a private
  directory outside the repository. No artifact is published or distributed.
- Patch script sha256 `c1709a5f06b5d953c541ae92bfc6a141b0a88aa81e3d7e20e62536b5963ccb37`;
  generated header `src/common/sxt307_tap.h` sha256
  `255bb339eb536ef43dfe11b40ecaea270624d6ad84e736a96c442dc684ef4e1a`; tap branch
  commit `754d13c5a630c9f2a4daecbcfab30b6f223bf749` (single commit on the pin;
  engine version string `1.4.sxt307-tap.754d13c5a`, baseline `1.4.HEAD.58914e59c`).
- Toolchain/runtime, `.so` hashes, tap-stream hashes, and a note on how JUCE's
  configure-time X11/ALSA headers were supplied without touching host paths:
  `artifacts/tap-build-provenance.json`. Python is 3.13.16 (not the SXT-010 3.11
  runtime): this affects the binding only, not engine DSP, but it is a recorded
  difference. Engine runs at 48 kHz (block 32; filter 96 kHz oversampled).
- Baseline oracle drift refusal is unchanged (`oracle/fetch-and-build.sh` untouched;
  the patch script refuses unless HEAD equals the pin and the tree is clean).

## 2. Neutrality (acceptance 3) — STALE: quantized-WAV equality only; raw re-derivation NOT_RUN

**Qualification (review of head 71e2ff3).** The table below records equality of
*clipped, int16-quantized WAVs*, not exact DSP neutrality: distinct engine outputs
(sub-LSB differences, values beyond full scale) can share a WAV digest. The tool now
decides neutrality on a digest of the raw engine samples (pre-clip, pre-quantization,
with dtype/shape retained) and refuses to qualify a reference when it FAILs or when the
deterministic control does not PASS. The control has **not** been re-rendered with the
raw digest (the external tap/base builds are not available to this change), so the
status of neutrality below is **NOT_RUN / STALE**, not PASS. The WAV digests are kept
as diagnostics only.


Run: `tools/render_lp24_tap_reference.py --case all` (`artifacts/cases/*.json`).

| render (factory `Basses/Bass 3`, scene A unit 0 = `fut_lp24`, seq-notes-repeated-v1) | WAV sha256 |
|---|---|
| patched, tap on | `b98154935094f4c7f6b5b759f94e9ac0a8dc0a5790d1c96621462d8d0e71fd44` |
| patched, tap off (env unset) | same |
| patched, tap off, repeat | same |
| unpatched build of the same pin/host/toolchain/runtime | same |

All four WAVs are identical (quantized WAVs only; see the qualification above) — previously recorded as PASS (control `neutrality-control-bass3`). The tap
stream for this render is non-empty (hashes in the provenance file), i.e. the
identity is not a vacuous no-op.

All eleven SXT-038 carrier renders are **engine-nondeterministic** on this build
(two untapped same-build renders differ), so neutrality on those carriers is
**NO_VERDICT** by the DR-0005 rule — it is not asserted from the control.
Cross-platform render differences prove nothing either way and are not used.

## 3. Availability against the unchanged cases (acceptance 4) — BLOCKED for all 11

The unchanged runner `model/voice/filter_lp24/run_filter_leg.py` was offered, for
each case, (a) all carrier-unit tap instances concatenated in voice order and (b)
the longest single instance, with the unchanged case file and `case_plan.py`.

| case | plan blocks | tapped instances (scene+unit match) | blocks / instance | runner (concat) | engine deterministic | neutrality | availability |
|---|---|---|---|---|---|---|---|
| brass | 1944 | 9 | 2246 | plan has 1944 blocks, bundle has 20214 | no | NO_VERDICT | BLOCKED |
| chords-clean | 1944 | 9 | 307 | plan has 1944 blocks, bundle has 2763 | no | NO_VERDICT | BLOCKED |
| chords-std | 1944 | 4 | 348,1848 | plan has 1944 blocks, bundle has 4392 | no | NO_VERDICT | BLOCKED |
| edges-cut-hi | 384 | 9 | 307 | plan has 384 blocks, bundle has 2763 | no | NO_VERDICT | BLOCKED |
| edges-cut-lo | 384 | 9 | 307 | plan has 384 blocks, bundle has 2763 | no | NO_VERDICT | BLOCKED |
| edges-reso1 | 384 | 9 | 307 | plan has 384 blocks, bundle has 2763 | no | NO_VERDICT | BLOCKED |
| edges-toggle | 768 | 9 | 307 | plan has 768 blocks, bundle has 2763 | no | NO_VERDICT | BLOCKED |
| edges | 1944 | 9 | 307 | plan has 1944 blocks, bundle has 2763 | no | NO_VERDICT | BLOCKED |
| major7mk2 | 1944 | 9 | 521 | plan has 1944 blocks, bundle has 4689 | no | NO_VERDICT | BLOCKED |
| phase1-substd | 384 | 9 | 319 | plan has 384 blocks, bundle has 2871 | no | NO_VERDICT | BLOCKED |
| phase1 | 1944 | 9 | 319 | plan has 1944 blocks, bundle has 2871 | no | NO_VERDICT | BLOCKED |

Every offer was REFUSED at the **first** gate (block count). Reading: the committed
plans fix a per-segment length, a *declared FEG fixture trajectory* and a stimulus
taken from SXT-037 bundles; a native render yields voice lifetimes set by the
sequence and the preset's own envelopes. **The later gates — control-word equality,
subtype/reset flags, sample-count, stimulus equality — were NOT_RUN** (the runner
stops at the first mismatch), so this record makes no statement about them, and none
of the following is established: that native cutoff/resonance equal the plan words,
that subtypes/clamp edges/resonance-1.0/the mid-render toggle are reproduced.
Per the issue: the affected #101 requirements stay **BLOCKED**; nothing was trimmed,
re-labelled or rewritten to pass, and the submodule harness was not substituted.
Resolving this needs a #101 contract decision (native-plan case variants or a native
control-plane/stimulus comparison); it is not made here.

## 4. Failure controls (acceptance 5)

- **NC-E (control-word tamper, scratch copy).** A submodule-harness `edges` bundle was
  generated in scratch space (`SXT038_ORACLE_DIR` outside the repo) as a positive
  control: the unchanged runner ACCEPTS it. Block 17's cutoff was then raised by 1 in
  memory: **REFUSED** — `block 17: control words differ (1.637497008,0.773648024) vs
  (0.6374970078468323,0.7736480236053467)`. (This exercises the same fail-closed check
  as `tools/lp24_negative_controls.py` NC-E; that tool itself needs committed
  `bundle-*` artifacts that are not in this checkout and was not run to completion.)
- **Baseline-only build offered as the tap.** `ORACLE_TAP_SURGEPY_DIR` pointed at the
  unpatched module: **REFUSED** — `engine version '1.4.HEAD.58914e59c' is not the
  SXT-307 tap build` (exit 1). A patched build that emits no LP24 records is likewise
  refused (non-empty coefficient stream required); that second path is implemented
  but not separately exercised here.

## 5. What remains unproved

Model-vs-reference agreement on any native LP24 render; neutrality on the eleven
carrier presets; that a native control plane can match an unchanged case; stimulus
equivalence; `fc_wide` right-channel (units 2/3) bundle conversion beyond sharing the
left unit's coefficient record; cross-host reproducibility; everything audible or
hardware-related. Adapter statuses: build PASS, neutrality control STALE (quantized-WAV equality only; raw re-derivation NOT_RUN), carrier
neutrality NO_VERDICT (11), availability BLOCKED (11), model comparison NOT_RUN.
