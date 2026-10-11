# 0020 — Effect-input paired observation method for the settle-boundary audit (#372)

- **Status:** RECORDED — method and adapter only. Live oracle runs are
  **NOT_RUN** (see Evidence status). No contract revision, no budget change.
- **Date:** 2026-10-11
- **Issue:** [#372](https://github.com/2AMLogic/gf180-surge/issues/372)
  (parent audit [#318](https://github.com/2AMLogic/gf180-surge/issues/318);
  budget gate [#12](https://github.com/2AMLogic/gf180-surge/issues/12))
- **Builds on:** [0005](0005-oracle-tap-instrumentation.md) (observation-only
  external tap class)

## Problem

For SXT-023 Delay/EQ, Chorus and Reverb 2 the #318 invariance A/A_early differ
because the synth output feeding the effect also moves during the silent
settle (`CONFOUNDED_SYNTH_SIDE`). The failure control forbids choosing the
pre-roll that scores better, so no re-run of the wet-bus-only method can give
a verdict.

## Decision

1. **Observe, per effect instance, the paired input/output.** An external,
   observation-only tap (DR-0005 class) records for every block from
   initialisation through settle, note sequence and tail: block index, phase
   (`init|settle|audio|tail`), a hash of the effect input and of the effect
   output (both stereo channels), whether the effect's process call ran, and
   whether the input was bit-silent; plus build identity and instance
   identity (slot, scene, chain position, effect type, channels). Schema
   `sxt372-effect-tap-v1`, validated by
   `tools/audit_effect_settle_boundaries.py` (`validate_tap_observation`).
2. **Licence boundary.** The tap is a patch of the GPL pinned engine
   (`58914e59c608ed4384ba6002e44c3465c58b2e71`). Following DR-0005 it, its
   generating script and the patched tree stay **external**; this repository
   commits only method prose, the patch/source **hashes** and an acquisition
   recipe. Committing a derived patch here would need a separate visible
   licence decision. No maintainer-only source is a required input: the
   recipe is public pinned checkout + external patch script. The recipe
   itself (script hash, build command) is **not yet recorded** (see below).
3. **Build identity.** Pin engine commit, every submodule, patch sha256,
   compiler/runtime/platform and 48 kHz in the oracle `BUILDINFO.json`
   (`effect_tap.patch_sha256`). A vanilla prebuilt is refused as an
   observation build (`tap_availability`).
4. **Neutrality (same environment, both bit-identical):** tap-on vs tap-off
   in the patched build; and patched-off vs unpatched
   (`validate_tap_neutrality`). Any difference refuses the whole bundle.
5. **Inference rule** (written before C is graded, never reads C or any
   score; `infer_effect_boundary`):
   - A0 repeatable and neutrality PASS required.
   - settle input must be observed silent;
   - the audio-window effect input must be identical across settle lengths
     {2, 375, ...}; otherwise **NO_VERDICT `INPUT_DIFFERS`**. The native
     signal path is *not* altered to force equal inputs; controlled replay
     would be a separate diagnostic with its own equivalence check;
   - identical output and no settle processing: **ZERO** (state scope);
     identical output after processing silence: **ZERO_OUTPUT_ONLY** (output
     invariance only; internal state not proven);
   - differing output with identical input and settle processing:
     **NONZERO** (boundary = fixture settle);
   - settle lengths 2 and 375 must both be observed, so early convergence is
     distinguishable from no advancement (else NOT_MEASURED).
6. **Leg separation.** Leg E is recorded beside A0/A/A_early/B/C
   (`row["E_effect_input_observation"]`); it never edits the legacy decision,
   old C numbers or comparator definitions. New results go to a distinct
   output directory; historical records (source revision of the committed
   table, e.g. Delay/EQ runner pre-roll 240 then, 375 now) stay baselines.
7. **Escalation.** A committed PASS that moves under a RESOLVED leg-E verdict
   is routed to #12 with both numbers, per #318.

## Evidence status

| Item | Status |
|---|---|
| Method, schema, fail-closed validation, adapter, unit tests | PASS (`tests/test_effect_settle_boundaries.py`, synthetic fixtures only) |
| External tap patch build + acquisition recipe + hashes | NOT_RUN (not authored; this worker has no oracle) |
| Tap-on/off and patched-off/unpatched neutrality, live | NOT_RUN |
| Leg E on Delay dexie/metallic, EQ fm_bass_1, Chorus, Reverb 2 rows | NOT_RUN |
| NC-C wrong-boundary controls on resolved sensitive rows | NOT_RUN |
| #12 routing of moved PASS | NOT_RUN (nothing moved; nothing measured) |

Unit tests establish rule and refusal behaviour only; they establish no
boundary, fidelity or support claim.
