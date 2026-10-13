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
   observation build (`tap_availability`). Every observation's build
   (`engine_commit`, `submodules_sha256` = the digest of
   `oracle/manifest.json` `submodules`, `patch_sha256`) must equal the
   oracle's tap identity, so it is also equal across settle lengths;
   otherwise the bundle is refused.
4. **Expected identity is the audit's, not the bundle's.** The expected
   instances (slot, scene, chain position, effect type, 2 channels) come
   from the audit inventory (`RUNNERS` carrier chain; Reverb 2: the
   committed sidecar `reverb2_slots`), and the audio/tail block counts come
   from the committed sidecar render (`expected_tap_instances`,
   `expected_tap_blocks`). All are mandatory. A bundle that carries
   `expect` or `repeatable` is refused. Every inventory instance must be
   observed (e.g. both Delay slots of `metallic`), each inferred separately.
5. **Neutrality (same environment, both bit-identical):** tap-on vs tap-off
   in the patched build; and patched-off vs unpatched
   (`validate_tap_neutrality`). The record must name its build (equal to the
   oracle tap identity) and its environment (platform, machine), and every
   observation must carry that same build and environment. Any difference
   refuses the bundle or yields NO_VERDICT.
6. **Repeatability source and its limit.** "Repeatable" is this audit's own
   A0 leg (wet-bus repeatability in fresh instances, measured on the
   tap-capable oracle that ran the audit); no bundle field supplies it. It
   is accepted only for a capture whose environment (platform, machine)
   equals the host that measured A0; otherwise NO_VERDICT (unverifiable).
   A0 is **not** a repeatability measurement of the tap capture itself;
   for the capture the method relies on neutrality (tap-on = tap-off) only.
7. **Inference rule** (written before C is graded, never reads C or any
   score; `infer_effect_boundary`):
   - A0 repeatable and neutrality PASS required.
   - settle input must be bit-silent, checked on the data: every settle
     input hash must equal the silent-block hash (sha256 of
     32 frames x 2 channels of zero float32); `in_silent` must agree with
     the hash on every block;
   - the effect input must be identical across settle lengths
     {2, 375, ...} over every graded window (audio **and** tail); otherwise
     **NO_VERDICT `INPUT_DIFFERS`**. The native signal path is *not* altered
     to force equal inputs; controlled replay would be a separate diagnostic
     with its own equivalence check;
   - identical audio+tail output and no settle processing: **ZERO** (state
     scope); identical output after processing silence:
     **ZERO_OUTPUT_ONLY** (output invariance only; internal state not
     proven);
   - differing output with identical input and settle processing:
     **NONZERO** (boundary = fixture settle);
   - settle lengths 2 and 375 must both be observed, so early convergence is
     distinguishable from no advancement (else NOT_MEASURED).
8. **Leg separation.** Leg E is recorded beside A0/A/A_early/B/C
   (`row["E_effect_input_observation"]`); it never edits the legacy decision,
   old C numbers or comparator definitions. New results go to a distinct
   output directory; historical records (source revision of the committed
   table, e.g. Delay/EQ runner pre-roll 240 then, 375 now) stay baselines.
9. **Escalation.** A committed PASS that moves under a RESOLVED leg-E verdict
   is routed to #12 with both numbers, per #318.

## Evidence status

| Item | Status |
|---|---|
| Unit tests of the rule and of the refusals they exercise (wrong/missing block, order, truncation, malformed hash, unknown phase, missing init, wrong slot/scene/effect/channels/chain position, wrong engine/rate/patch/submodule digest, tap disabled, missing environment, missing expectation key, self-attested `expect`/`repeatable`, missing or extra instance, wrong-tap observations, neutrality failure or build/environment mismatch, A0 absent/failed or from another environment, non-silent settle, `in_silent` contradicting its hash, audio- or tail-window input difference) | PASS (`tests/test_effect_settle_boundaries.py`, synthetic fixtures + committed sidecars for the inventory only). Refusals not listed here are not claimed tested. |
| External tap patch build + acquisition recipe + hashes | NOT_RUN (not authored; this worker has no oracle) |
| Tap-on/off and patched-off/unpatched neutrality, live | NOT_RUN |
| Leg E on Delay dexie/metallic, EQ fm_bass_1, Chorus, Reverb 2 rows | NOT_RUN |
| NC-C wrong-boundary controls on resolved sensitive rows | NOT_RUN |
| #12 routing of moved PASS | NOT_RUN (nothing moved; nothing measured) |

Unit tests establish rule and refusal behaviour only; they establish no
boundary, fidelity or support claim.
