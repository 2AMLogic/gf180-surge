# SXT-012 evidence record — render fixtures

Branch: `loom/sxt-012-render-fixtures` · Issue: #7 (SXT-012) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
surgepy build `1.4.HEAD.58914e59c`, 48 kHz, compiled block size 32, tempo 120
(`oracle/manifest.json` runtime block; `fixtures/manifest.json` `engine` block).

Tooling commit at render time: `9bab0e8` ("SXT-012: versioned event-sequence library +
render harness (pinned inputs)"), `pinned_inputs_clean: true` recorded in every sidecar
and in `fixtures/manifest.json.generated_by`.

**Claim discipline.** This record and everything under `fixtures/` establishes
*reference-vs-reference* behavior of the pinned engine under the documented harness:
fixture coverage, wet/dry captures, metadata integrity, and render-to-render
repeatability or characterized variation. It establishes **no** fidelity claim
(nothing is compared to our model/RTL), **no** preset-support claim, and **no**
musical-quality claim (no listening record exists).

## Deliverables

| Deliverable | Artifact |
|---|---|
| Versioned event-sequence library | `fixtures/sequences/seq-*.json` (10 sequences, ids `seq-*-v1`), schema + policies in `fixtures/README.md`, provenance generator `fixtures/sequences/generate_sequences.py` |
| Render harness | `fixtures/render_fixture.py` (reset/quantization/tail/dry policies in its docstring and `fixtures/README.md`) |
| Wet + diagnostic dry renders | `fixtures/audio/<preset>/<seq>-{wet,dry}.wav` — 30 fixtures, 60 WAVs, 25,548,240 bytes (24.4 MiB) committed |
| Per-fixture metadata | `fixtures/audio/<preset>/<seq>.json` sidecars + aggregate `fixtures/manifest.json` (hashes of sequences, presets, WAVs, engine + tool identity, policies) |
| Repeatability report | `reports/sxt-012/repeatability.json` (3 fresh-instance renders per bus per fixture) |
| Variation mechanism diagnostic | `reports/sxt-012/variation-mechanism.json`, produced by `fixtures/diagnose_variation.py` |
| Negative controls | `reports/sxt-012/negative-controls.txt` + perturbation sequences `reports/sxt-012/nc-*.json` |
| Comparator | `fixtures/verify_fixtures.py` (integrity pass: 30/30 fixtures, 11 checks each) |

Pilot presets (factory bank, all Single-scene, census-blob verified at every load):
`Basses/Sub 4.fxp` (Sine, 0 FX — the SXT-010 capture preset), `Leads/Koala 2.fxp`
(Classic, 1× Delay), `Basses/Behemoth.fxp` (Classic, 1× Reverb1).

## Acceptance checklist (issue #7)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Fixtures span low/mid/high registers, soft/medium/hard velocity, short/long holds, releases, repeated notes, declared polyphony | **PASS** (with a recorded caveat) | `seq-notes-coverage-v1` (registers C2/C4/C6 × velocities 30/70/120, 200 ms holds, releases with gaps), `seq-notes-holds-v1` (short vs long 1200 ms holds, release velocity 100), `seq-notes-repeated-v1` (fast + moderate same-pitch repeats), `seq-poly-8-v1` (8 simultaneous voices — the declared fixture polyphony target, plan §3). All rendered for all 3 presets (wet+dry). Caveat (bounded finding, not silently dropped): on these three presets velocity does not map to audio (`vca_velsense = 0.0` on all; vel 70 vs 127 renders bit-identically — `negative-controls.txt` NC0). The fixtures deliver the velocity dimension into the engine; audible velocity coverage requires a velocity-routed preset in a future fixture expansion. |
| 2 | Tempo changes, sustain, bend, mod wheel, pressure, and macro sweeps included where a preset relies on them | **PASS** for sustain/bend/wheel/pressure/macro; **NO_VERDICT for tempo-change rendering** | Sequences exist and rendered: `seq-sustain-pedal-v1`, `seq-pitchbend-v1`, `seq-modwheel-v1`, `seq-pressure-v1`, `seq-macro-sweep-v1` (macros 1/2 via default CC 41/42). **Tempo limitation:** `surgepy` exposes no transport-tempo setter (engine `time_data` is not bound; only patch-load tempo is honored), so `seq-tempo-change-v1` records its 120→90→150 BPM events but the renderer cannot apply them mid-render; the committed render runs at the pinned 120 BPM and the sidecars record `tempo_events_applied: 0`, `tempo_events_renderable: false`. The sequence library is harness-ready for a tempo-capable renderer; declaring tempo-synced behavior covered would be false and is not done. |
| 3 | Wet output plus diagnostic dry/stems; no per-render peak normalization or time warping | **PASS** for wet+dry; **NOT_RUN** for per-voice/per-stage stems | Every fixture has a WET render (unmodified patch, all stored effects active — the product reference) and a DRY render: identical fresh instance, but all 16 FX-slot `type` parameters set to `fxt_off` via `setParamVal` before settle; read-back verified `Off` (`dry_fx_bypass_verified: true` in every sidecar); nothing else differs. Zero-FX preset sanity: all Sub 4 wet and dry renders are bit-identical (bypass provably perturbs nothing); FX presets differ wet-vs-dry (e.g. Koala repeated notes max\|Δ\| ≈ 0.24). Raw renders: mono (L+R)/2 int16, hard clip to [-1,1] (0 clipped samples across all 60 WAVs), **no normalization, no time warping, no fades**. Per-voice/per-stage stems beyond this dry bus: surgepy has no per-voice tap — NOT_RUN, not approximated. Stereo: the committed bus is mono per the deliverable; stereo-field diagnostics are future work. |
| 4 | Repeat runs under the pinned environment are bit-identical, or variation is quantified and recorded | **PASS** — both branches of the rule, per class | 3 fresh-instance renders per bus per fixture (`repeatability.json`): **20/30 fixtures bit-identical on both buses** (all Sub 4 + all Behemoth fixtures). **10/30 with quantified variation** (all Koala 2 fixtures): max\|Δ\| 0.258–0.306 across renders, relative max diff 1.58–1.86 × peak (full decorrelation). Mechanism diagnosed (`variation-mechanism.json`): the engine seeds its audio RNG from wall-clock time (`RNGGen`, `SurgeStorage.h:2130-2139`, no seed API, none exposed by surgepy) and free-running oscillator phase consumes `rand_01()` at voice start when the stored `retrigger` flag is off (`ClassicOscillator.cpp:238`, `SineOscillator.cpp:122`). Attribution control: Koala 2 unmodified varies, with `retrigger` forced on (diagnostic adaptation, never used for committed fixtures) 3 renders are bit-identical; Behemoth/Sub 4 identical under both conditions. **Reference-vs-reference only** — this says nothing about model-vs-reference agreement. |
| 5 | Negative control: perturbing event timing or a controller value must produce a detectably different fixture | **PASS** — demonstrated, with the granularity boundary characterized | `negative-controls.txt`, deterministic fixture `sub4__seq-sustain-pedal-v1` (committed sha `bf9bad26…`): controller-value perturbation (pedal CC64 127→0) → `6f091a7d…` **detected**; timing perturbation +1 sample of a block-aligned onset → `ea49fcea…` **detected**; two onsets inside the same engine block (t=1 vs t=2) → **bit-identical**, demonstrating the documented 32-sample scheduling-granularity ceiling (comparator cannot, and must not, distinguish sub-block timing through this harness). Metadata-hash tamper → comparator **REFUSED exit 2** (`sidecar_agrees_wet_hash` failure); single flipped WAV byte → **REFUSED exit 2** (`wet_sha256_matches` failure); restored tree → **ALL CHECKS PASS exit 0**. Velocity-value perturbation: not detectable on the pilot presets because the presets ignore velocity (NC0 characterization above) — a fixture-set limitation, recorded, not a comparator failure. |

## Scheduling granularity (documented limitation)

Event times in the library are exact integer samples at 48 kHz. The engine
consumes events only at compiled block starts (32 samples ≈ 0.667 ms); the
harness dispatches each event before the first block whose start is ≥ `t`
(never early, ≤ 31 samples late). Sub-block timing is **not representable**
through `processMultiBlock`. The sequence files stay sample-accurate so a
future sample-accurate harness can render the same library without a format
change; comparing renders from this harness at sub-block precision is invalid.

## Escalations (issue stop/escalate condition)

1. **Free-phase preset class.** Presets whose stored oscillators free-run at
   voice start (retrigger off) vary between fresh engine instances by initial
   phase (quantified above; relative max diff > 1.5 × peak — fully
   decorrelated waveforms). This class cannot pass any raw-waveform bit or
   sample budget. Escalated to the fidelity-policy milestone (SXT-013): the
   declared error budgets must specify phase-agnostic comparison methods for
   this class (onset-aligned spectral/level/envelope comparisons), and any
   bit-exactness claim must be restricted to presets/configurations that are
   deterministic under the pinned engine (e.g. retrigger-on, or a visible
   contract revision if retrigger forcing is ever adopted as an adaptation).
2. **Tempo rendering.** A tempo-capable harness (surge-testrunner path or a
   binding extension upstream of SXT-014) is required before tempo-dependent
   fixture renders can qualify. Until then, tempo-synced LFO/FX behavior is
   NOT covered by any fixture and no claim may rely on it.

## Licensing / provenance

Everything under `fixtures/` and `reports/sxt-012/` is original to this
repository (Apache-2.0 per `LICENSE`). The harness imports the externally
pinned GPL engine at runtime only; no Surge source, tables, presets, or
assets are copied into this repository. The committed WAVs are this project's
own renders of loaded presets, not redistributed upstream content. Method
reference (fixture/corpus + repeatability discipline) was taken from the
sibling project's published specs per the issue's "reusable substrate" notes;
no sibling code was copied (adapt, attribute, pin — REUSE-AUDIT respected).

## Explicitly NOT established by this work

- Any model-vs-reference or RTL-vs-model agreement (none exists yet to test).
- Any preset support/coverage claim; census numbers remain inventory only.
- Any fidelity, quality, or musical usefulness claim (no listening record).
- Stereo-field behavior, long-tail (> 2.5 s) decay, tempo-synced behavior,
  per-voice stems, polyphony beyond 8 voices, MPE, alternate tunings — all
  out of the pilot scope and unrendered.
- Byte-exact reproduction on hosts other than the recorded environment
  (`oracle/manifest.json` `environment` block); other hosts must re-run.
