# Fidelity policy — DRAFT v0.1 (NOT FROZEN)

Issue: #8 (SXT-013) · Plan: `docs/surge-xt-chip-plan-v0.1-2026-09-20.md` §2, §5
Status: **DRAFT** — every tolerance below is a
**[PROPOSED-TO-BE-FROZEN-AT-PILOT]** placeholder. Nothing in this file is
binding. The frozen successor of this document will be
`contracts/fidelity-policy-v1.md`; freezing is gated on the 32-preset pilot
listening set completing (issue #8 acceptance) and is explicitly **BLOCKED on
human listening** as of this draft.

Claim discipline (AGENTS.md): this policy governs three separable claims that
must never be inferred from one another — (1) RTL equals the frozen
fixed-point model exactly; (2) the model reproduces the pinned Surge reference
within the declared budgets below; (3) the instrument sounds good. Numeric
tests never establish (3); listening records do. Nothing in this file
establishes any of the three yet.

Reference pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
48 kHz, via the SXT-012 fixture harness (`fixtures/render_fixture.py`,
`fixtures/manifest.json`). All comparisons are against the same pinned
reference for every preset under test — the reference engine is never
switched per patch.

---

## 1. Per-status definitions (from plan §2, verbatim meaning)

Each corpus preset receives exactly **one** headline status:

| Status | Required meaning | Counts toward favorites coverage? |
|---|---|---|
| **Supported** | Original normalized patch graph and resources fit; complete wet output and agreed performance tests pass this fidelity contract. | Yes |
| **Adapted** | Useful variant with specific disclosed edits, such as a replaced reverb, reduced unison, removed layer, or rescaled modulation. | **No** |
| **Unsupported** | Required behavior or resources are missing, or fidelity fails. Machine-readable reasons required. | No |
| **Unresolved** | Loader, analysis, or evaluation incomplete. Remains in the original denominator. | No |

Rules:

1. **Original-presets rule.** A preset counts as supported only with its
   original effect placement, order, stereo behavior, modulation, and tails.
   A preset whose reverb (or any other effect) was substituted with a
   convenient generic is **adapted**, never supported.
2. **Adaptations are disclosed edits**, enumerated per preset (what changed,
   why, and the measured effect); an undisclosed edit is a finding, not an
   adaptation.
3. **Unresolved stays in the denominator.** Evaluation failures (renderer
   limits, analysis gaps such as MSEG/Formula contents not exposed by
   surgepy, listening not yet performed) leave the preset unresolved; they
   are never silently reclassified.
4. **Per-instance effect state is part of the graph**: two Delay slots are
   two delay histories even when arithmetic is shared. Sharing state across
   instances is an adaptation (or a fidelity failure if undisclosed).
5. Denominators are reported separately for the favorites set, all factory
   presets, and all contributor presets (plan §2: the curated target must not
   hide general coverage).

## 2. Measurement suite

All measurements run on SXT-012 fixtures (versioned sequences, block-level
event scheduling, documented 32-sample granularity) or successor sequence
versions; ad-hoc unversioned renders are not evidence. Each area below lists
what is measured and the pass rule; numeric limits are placeholders until the
pilot freeze.

### 2.1 Pitch / timing / gain

- **Pitch.** Steady-state fundamental per note across low/mid/high registers
  (C2/C4/C6 in the v1 library) vs the reference render. Measures: f0 error in
  cents after onset-aligned windows. Free-phase presets use the
  phase-agnostic method of §2.5. Budget: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.
- **Timing.** Event-to-output latency and envelope/onset offsets in samples,
  within the documented 32-sample scheduling granularity (sub-block offsets
  are not measurable through the surgepy harness and are out of scope until
  a sample-accurate harness exists). Budget: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.
- **Gain.** Broadband level (RMS and peak) ratios model-vs-reference per
  fixture, plus clipped-sample counts. Raw levels, never normalized (§3).
  Budget: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.

### 2.2 Envelope / modulation

- ADSR-aligned level envelopes vs reference (attack/decay/slope/release
  landmarks); release tails after note-off and after sustain-pedal release.
- LFO/step-sequencer/macro/mod-wheel/pressure routings exercised through the
  fixture sequences (`seq-modwheel-v1`, `seq-pressure-v1`,
  `seq-macro-sweep-v1`, pitch bend `seq-pitchbend-v1`); depth and rate
  compared in the modulation domain, not only audibly.
- An apparently-zero level that is reachable by modulation is treated as
  live (plan §3); presets relying on such routes are not "simplified".
  Budgets: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.

### 2.3 Spectral / aliasing

- Spectral difference vs reference on steady-state and swept material;
  identified aliased components vs the reference's own aliasing behavior
  (the reference's character is the target, including where it aliases).
- Wavetable presets: interpolation/morph behavior at pitch extremes and
  during morph modulation. Budgets: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.

### 2.4 Filter / feedback stability

- Filter cutoff/resonance tracking vs reference across the fixture register
  sweep; self-oscillation onset where the reference exhibits it.
- Feedback paths (filter feedback, delay/reverb feedback) under long renders:
  divergence onset, bound, and settle behavior; no runaway where the
  reference is stable, no premature damping where the reference sustains.
  Budgets: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.

### 2.5 Stereo / effect decay (wet path)

- **Stereo.** Inter-channel correlation, width, and per-channel level vs the
  reference wet render. The committed SXT-012 bus is mono; stereo fixtures
  are a prerequisite for this section — until they exist, stereo measures are
  NOT_RUN, never assumed-pass.
- **Effect decay / tails.** Decay time-to-threshold, tail energy envelope,
  and tail stereo vs reference, rendered with tails long enough for the
  preset's stored settings (per-sequence `tail_s` bumps in new sequence
  versions, never edits of committed renders).
- **Free-phase presets** (stored retrigger off; engine consumes `rand_01()`
  at voice start — SXT-012 escalation): raw waveform subtraction is NOT
  required and MUST NOT be the pass rule; onset-aligned envelope/level and
  spectral comparisons are the method. Phase-exact claims are restricted to
  presets that are bit-reproducible under the pinned engine.
- Budgets: **[PROPOSED-TO-BE-FROZEN-AT-PILOT]**.

### 2.6 What cannot be required

- No raw waveform-subtraction pass across uncontrolled noise, free-running
  phases, or nonlinear trajectories (plan §5).
- Conversely, no perceptual-similarity argument may excuse dropped events, a
  fixed-point/RTL mismatch, or a substituted effect (§1 rules 1–2).

## 3. Level-correct measurement rules

1. **No per-clip normalization, ever, for acceptance.** Renders are compared
   at native levels; per-render peak/RMS scaling hides gain and drive errors
   and is forbidden in any measurement that feeds a status decision.
2. **Dry-unless-effect rule** (AGENTS.md): comparison renders are dry unless
   the case under test is an effect or wet path. Bypass tests must retain the
   unmodified wet reference.
3. No time-warping, no fades, no reference switching per patch. Alignment is
   onset/event based with the declared jitter bound (§2.1).
4. Diagnostic level-matching exists ONLY inside supplementary blind listening
   (§4) and is recorded per stimulus; it never feeds measurements.
5. Clipping is data: hard-clip counts are reported per render; a model that
   clips where the reference does not fails §2.1 gain, not a tolerance.

## 4. Listening procedure

- **Acceptance ratings** are taken **unblinded and level-correct**
  (mode `open` in `tools/listening_session.py`): stimuli at native levels,
  identities visible. This is the mode the favorites acceptance uses.
- **Blind level-matched listening MAY supplement** (mode `blind`, optional
  `--level-match`): randomized A/B order, RMS pair-matching, unblinding
  recorded after rating. It can flag disagreements for investigation; it
  MUST NOT replace level-correct measurements (plan §5) and MUST NOT be the
  sole basis of any status.
- Sessions are recorded as structured JSON in
  `decisions/listening-sessions/` (schema in the harness; one file per
  session; operator, mode, level treatment, stimulus hashes, and per-candidate
  ratings and notes are mandatory). Machine dry-runs are marked
  `DRY_RUN_NOT_HUMAN_LISTENING` and are never listening evidence.
- Performance intent is preserved: listening uses the same versioned
  sequences (registers, velocities, holds, controls) as the measurements, so
  a "good sound" verdict cannot smuggle in a different performance than the
  one measured.

## 5. Negative controls (must demonstrably fail what they target)

1. **Generic-reverb substitution** under a would-be support claim must FAIL
   the contract or be classed **adapted** (§1 rule 1) — never supported.
2. Wrong effect order / placement (e.g., swapped insert and send roles) must
   be detected by the §2.5 wet-path suite.
3. Per-instance state violations (two Delay slots sharing one history) must
   be detected by a double-delay fixture.
4. A silently dropped tail (render truncated before decay completes) must
   fail §2.5 decay, not pass by truncated-window comparison.
5. Level-matched normalization leaking into measurements must be detectable:
   measurement artifacts record input hashes; a normalized input must not
   verify against raw renders.
6. Determinism controls: same inputs → byte-identical candidate slates;
   census-hash tampering must refuse the run
   (`reports/sxt-013/negative-controls.txt`).

## 6. Freeze procedure (how this draft becomes policy v1)

1. Complete the 32-preset pilot listening set (issue #8 acceptance item 1)
   using this harness and policy draft; the pilot establishes the evaluation
   process and exercises every §2 measurement on real presets.
2. Replace every **[PROPOSED-TO-BE-FROZEN-AT-PILOT]** placeholder with a
   measured, justified budget; any budget the pilot cannot justify stays
   named as unresolved rather than invented.
3. Record the freeze as a versioned contract
   (`contracts/fidelity-policy-v1.md`) with the pilot evidence linked;
   changes after freeze are new versions, never in-place edits.
4. Freezing is BLOCKED until (1) is done by a human listener. The pilot does
   not substitute for the 256-preset goal (issue #8, plan §2).
