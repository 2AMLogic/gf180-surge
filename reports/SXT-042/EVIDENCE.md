# SXT-042 evidence record — voice leaf: modulation behavior keytrack

Branch: `feature/issue-76` · Issue: #76 (SXT-042) · Date: 2026-09-25

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
48 kHz, block size 32 (`oracle/manifest.json`). Keytrack authority: pinned
`src/common/ModulationSource.h` (`modsources`, `ms_keytrack = 2`) and
`src/common/dsp/SurgeVoice.cpp` (voice ctor modsource init,
`calc_ctrldata` order, `applyModulationToLocalcopy`, `switch_toggled`) —
read at the pinned commit and cited, never copied.

**Citation pin (checked, not asserted).** Both cited files were fetched to a
scratch path outside this repository and their git blob SHA-1s were compared
against the pinned tree before use:
`src/common/dsp/SurgeVoice.cpp` = `e8609681ee9cc4e37c1327d781b7e6cd53bd55bb`
(61,032 bytes) and `src/common/ModulationSource.h` =
`1430e210a397616464f32c1cc4c6af33a2e6a026` (18,119 bytes), both at
`58914e59c608ed4384ba6002e44c3465c58b2e71`. The enum ordering that fixes the
modsource id (`ms_original = 0, ms_velocity, ms_keytrack, …` ⇒ keytrack = 2,
modwheel = 6) and the ctor line `keytrackSource.set_output(0, 0.f);` (vs
`velocitySource.init(0, state.fvel);`) were read from those pinned blobs. No
engine source is copied into this repository.

**Claim discipline.** This record advances (1) *RTL matches the frozen
fixed-point model exactly* (iverilog-simulated; integer equality, 0
mismatches over 26,250-block and 122-block fixtures) and (2) *reported
achieved model-vs-pinned-engine numbers* against [PROPOSED] budgets
(PENDING-FREEZE) on the one carrier for which a committed pinned-engine
render with a live keytrack route exists — those budgets **FAIL**, and a
new bounded finding (F-042-3) records that the reference check on that
carrier cannot discriminate a cutoff-route mutation at all. It establishes
**no** fidelity verdict, **no** preset-support claim (measured supported
delta: **0 presets**, §6), **no** musical-quality claim (no listening
record exists), and **no** FPGA/gf180mcu synthesis, timing, area, power or
hardware-playback claim. `tb_kt.sv` is an iverilog-simulated behavioral
schedule.

**Environment limitation, stated once and honoured throughout.** This work
was executed on a host with **no pinned Surge oracle** (`surgepy` absent,
`ORACLE_SURGE_DIR` unset). No new engine render was produced. Every
reference number below comes from the **committed, sha-pinned,
determinism-gated SXT-025 dry fixture** projected to the fixtures' mono
int16 convention by `tools/kt_reference_from_fixture.py` (§3). Anything
that would have required a new engine render is reported **NOT_RUN**, never
as a pass (§8).

## 1. What was built

| Deliverable | Artifact |
|---|---|
| Frozen keytrack modsource in the model (named word, engine-cited init/refresh order, per-destination route sums, fail-closed route pass) | `model/voice/voice_model.py` (`keytrack_word`, `KEYTRACK_DEST_LIVE/INERT`, `VoiceV2.keytrack_value`, `_apply_voice_routes`) + freeze section in `model/voice/README.md` ("SXT-042 frozen keytrack modsource") |
| Fail-closed fixture extractor + committed sidecar | `model/voice/extract_kt_inputs.py`, `model/voice/bells_kt_inputs.json` |
| Model runner (route table, control-plane trace, RTL stimulus, control switches) | `model/voice/run_kt_model.py` |
| Keytrack control-plane RTL + exactness harness | `rtl/voice/tb_kt.sv`, `tools/compare_kt_rtl_model.py` |
| Reference projection from the committed pinned-engine fixture | `tools/kt_reference_from_fixture.py` |
| Negative controls + two RTL mutants | `tools/kt_negative_controls.py`, `rtl/voice/tb_kt_broken_mutant.sv`, `rtl/voice/tb_kt_shared_mutant.sv` |
| Corpus applicability scan (reach, upper bound) | `tools/kt_applicability_scan.py` |
| Tests (no oracle, no iverilog) | `tests/test_sxt042_keytrack.py` (20 tests) |
| Artifacts | `reports/SXT-042/artifacts/` |
| Coverage ledger registration (`mod:keytrack`: `rtl_vs_model` PASS, `model_vs_reference` **FAIL**, evidence sha-pinned) + regenerated coverage outputs | `reports/coverage-v1/leaf-verification.json`, `reports/coverage-v1/coverage.json` |

**Extend, don't fork.** The #48 plumbing is generalized in place: one route
pass, one keytrack word, reused by both oscillator kinds. Landed fixtures
render **bit-identically** after the extension (sha256-equal against the
committed artifacts): SXT-022 v1 ×3 (`seq-notes-repeated-v1`,
`seq-notes-coverage-v1`, `seq-modwheel-v1`), the same three through the
schema-2 sidecar, SXT-026a bells smoke, and SXT-035 modwheel ×3.

## 2. Frozen scope (full text in `model/voice/README.md`)

* **Word**: `kt = qint((pitch_voice − keytrack_root)/12)`, Q10.21, one
  round-half-up; `pitch_voice = key + 12·scene_octave`. **Per voice
  instance** (one 32-bit word each), never shared.
* **Init/refresh (engine-cited, corrected here — F-042-1)**: the engine's
  voice constructor runs `keytrackSource.set_output(0, 0.f)` *before* its
  `applyModulationToLocalcopy<true>()` and `calc_ctrldata<true>()`, and only
  installs the pitch-derived value at the **end** of a control pass. So a
  voice's FIRST control pass applies keytrack = **0** — unlike velocity,
  which the ctor seeds with `state.fvel`. #48 documented the
  1-control-pass lag but seeded the word with the pitch value. The model now
  matches the cited order.
* **Destination class**: `{308 Filter 1 Cutoff, 309 Filter 1 Resonance,
  310 Filter 1 FEG Mod Amount}` live; `{314, 315, 318}` accepted-inert
  (unit 2 Off); **everything else refused fail-closed**, including
  `298 VCA Gain`, which is the single most common keytrack destination in
  the corpus (144 scene-A rows) and is deliberately outside this leaf.
* **Application**: `param = sat(param + qmul(qint(depth), value))` in `md`
  order over the merged velocity+keytrack row list, into the localcopy
  accumulators.
* **Integer-exact RTL equivalent**: `kt = floor((n·2^20 + 3)/6)`, exact
  because `n·2^21/12` never lands on a rounding tie (proved for the whole
  declared pitch span by `test_keytrack_word_is_never_a_rounding_tie` and
  `test_keytrack_word_integer_exact_rtl_equivalent`).

## 3. Reference fixture and its provenance (no new engine render)

Carrier: **`Rozzer/Bells/Hell's Bells.fxp`** (census blob
`e499f78df5664012717dd2961944502846e28cf7`) — the one preset in the landed
voice class whose **preset content** carries a live keytrack route
(`ms_keytrack → A Filter 1 Cutoff`, raw depth 4.387498 semitones,
normalized 0.03375). Sequence `sxt025-accept-v1` (7 distinct pitches, 4-voice
polyphony, 840,000 frames), which exercises keytrack words 0.0, 1.0, 1.583,
2.0, 2.333, 3.0, 4.0 across voices.

Reference: `reports/sxt-025/fixtures/hells_bells__sxt025-accept-v1-dry.f32.wav`
(sha256 `8399f13d…`, verified at use; 3× bit-identical determinism gate in
its manifest; FX bypassed by `fxt_off` with readback, fresh instance, 0.25 s
settle) → mono int16 by the two documented steps of
`tools/render_leaf48_reference.py` (`0.5·(L+R)` in float32, then
`int(clamp·32767)`), giving
`artifacts/reference-sxt025-accept-v1-bells-dry.wav`
(sha256 `afb3ad51…`, `artifacts/reference-provenance.json`).

**Cross-validation of the projection** (why it is the right reference): the
landed SXT-026a §4 canonical dry comparison reported max|Δ| 16,960 LSB,
RMS Δ −27.87 dBFS, spectral corr 0.9205 against an oracle render that was
**never committed**. The projection reproduces 16,721 / −27.855 / 0.9207
with the model at this branch. The model side is proved drift-free (the
bells smoke render is byte-identical to the committed SXT-026a artifact),
so the residual ~1.4 % on max|Δ| is unattributed between (a) model drift on
paths the 122-block smoke does not reach and (b) a harness difference
between the SXT-025 fixture renderer and `render_leaf48_reference.py`.
**Recorded as F-042-4, not reconciled** — resolving it needs an oracle host.

## 4. Acceptance mapping (issue #76)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model with word lengths + op order (`model/voice/` conventions) | **PASS** | `model/voice/README.md` §"SXT-042 frozen keytrack modsource": Q10.21 word, engine-cited init/refresh order, destination class, md-order saturating route application, integer-exact RTL equivalent, declared omissions. Implementation in `voice_model.py`; landed renders bit-identical (§1). |
| 2 | Model-vs-pinned-engine dry-render budgets on the carrier fixtures (PENDING-FREEZE; achieved numbers recorded, not tuned) | **DONE — budgets FAILED (bounded findings F-042-3/F-48a → SXT-013/#12)**; the issue's three named carriers: **NOT_RUN / refused** | `artifacts/audio-nc-baseline.json`: max|Δ| **16,721 LSB** (budget 3,500), RMS Δ **−27.855 dBFS** (budget −46), spectral corr **0.9207** (budget 0.98), best_shift 32 → FAIL. Windowed: RMS 1,915.4 LSB over the kt≠0 note windows, 2,719.4 over the kt=0 windows. The three carriers named in the issue body are refused by the applicability scan for keytrack-specific reasons (§6), so no budget number exists for them (NOT_RUN, not a pass). |
| 3 | RTL-vs-model exact at declared checkpoints (integer equality) | **PASS (0 mismatches)** | `tools/compare_kt_rtl_model.py` + `rtl/voice/tb_kt.sv`: `sxt025-accept-v1` 26,250 blocks / **30,021 voice checkpoints / 240,168 fields / 0 mismatches**; synthetic class-cover fixture (all three live destinations) same counts, 0 mismatches; `leaf48-smoke-bells-v1` 122 blocks / 302 / 2,416 / 0. Checkpoints per running voice per block: `kt_word`, the three per-destination keytrack route sums, and `mod_cutoff`/`mod_reso`/`mod_envmod`/`mod_vca_db` after the full pass. |
| 4 | Cycle/state costs vs SXT-016 probes and SXT-015 | **PASS (recorded; divergence named)** | `artifacts/costs.txt`: 180,126 qmul / 840,000 samples = **0.214 MAC per 48 kHz sample** (one qmul per md route row per running voice-block; 0.286 on the 8-row synthetic fixture) — ~0.5 % of the 37.7–41.3 MAC/sample voice datapath. The keytrack word itself costs one integer divide-by-6 of a shifted key difference: no multiply, no table. State: 1×32-bit word per voice + a 3-word-per-route constant ROM; no history. **Divergence**: SXT-016 has no per-modsource evaluation probe row (the leaf's own cost note said `[ESTIMATE] pending SXT-016 refinement`); these are offered as refinement input, not reconciled. |
| 5 | **Negative control (must demonstrably fail)**: routing-zeroed (per destination class) and source-swap (modwheel in place of this source), both FAILing the reference-budget check; committed transcript | **PASS on the letter, with an explicit honesty qualifier** | `artifacts/negative-control.txt`, `negative-controls.json`. Both required controls **FAIL** the reference-budget check and **provably change the render**; three of the counted controls do **not** degrade any metric relative to the unmutated model on this carrier and are labelled **NON-DISCRIMINATING** in the transcript and JSON rather than counted as evidence of sensitivity (F-042-3). Two controls are discriminating, two RTL mutants fail integer equality, two destinations' controls are provably degenerate on this preset and are carried in the exactness domain instead. Full table in §5. |

## 5. Negative controls (transcript: `artifacts/negative-control.txt`)

Reference retained unmodified; only the model is mutated (AGENTS.md bypass
rule). Baseline row: max 16,721 / RMS −27.86 dBFS / spec 0.9207 / windowed
kt≠0 RMS 1,915.4.

| Control | Result | Verdict |
|---|---|---|
| **C1 routing-zeroed → F1 Cutoff** (depth→0) | max 16,330 / RMS −28.49 / spec 0.9250 / wRMS 1,728.7 → FAILs the budget check, render provably changed, **degrades nothing** | FAIL (required) but **NON-DISCRIMINATING** — recorded, not counted as sensitivity |
| C1 routing-zeroed → F1 Reso / F1 FEG-Mod | render **bit-identical** (the preset carries no such route) | **DEGENERATE — explicitly not counted**; carried by C8 instead |
| **C2 shared-instead-of-per-instance** (one global keytrack word rewritten at every note-on) | max 17,038 / RMS −27.70 / spec 0.92074 / wRMS 1,963.5 — **degrades max, RMS, spectral and the windowed kt metric** | **FAIL + DISCRIMINATING** (the AGENTS.md per-instance control) |
| **C3 source-swap → velocity** | max 16,455 / RMS −28.25 / spec 0.9270 / wRMS 1,786.0 | FAIL, **NON-DISCRIMINATING** |
| **C3 source-swap → modwheel** (the swap the issue names) | byte-identical to the C1 zeroed render (**proved by sha equality**): a Sine-class fixture admits no CC event, so the modwheel is identically 0 | FAIL, **degenerate-to-zeroed**, disclosed |
| **C4 keytrack-root dropped** (`pitch/12`) | max 20,723 / RMS −26.07 / spec 0.8775 / wRMS 2,429.4 — degrades every metric | **FAIL + DISCRIMINATING** |
| P5 lag probe (refresh before the pass) | **bit-identical** (expected: pitch is constant per voice, so the declared lag is unobservable in this class) | PROBE, passes as inert; not a control |
| P6 control-validity probe (zero the **velocity** route into the same destination, 5.8× the keytrack depth) | max 15,300 / RMS −29.33 / spec 0.8916 / wRMS 1,578.3 | PROBE — see F-042-3 |
| C7 out-of-class refusal: keytrack → 'A Pan' (265) | runner exit **2**, destination named | PASS |
| C7 carrier refusals (Alone, Autumn 2, Disturbances) | all refused with keytrack-specific reasons (§6) | PASS |
| C8 exactness-domain controls on the synthetic class-cover fixture (zero reso / zero feg-mod) | both **change the render** (model-vs-model only; no reference claim) | PASS |
| **C9 RTL mutant — rounding** (`+3` bias dropped ⇒ truncate) | **FAIL**, 50 mismatches, first `block 6750 slot 4 kt_word: model=3320491 rtl=3320490` | PASS (control fails as required) |
| **C9 RTL mutant — shared word** (one word for all slots) | **FAIL**, 42 mismatches, first `block 1688 slot 3 kt_word: model=4194304 rtl=0` | PASS |

### F-042-3 (bounded finding): the reference-budget check cannot discriminate a cutoff-route mutation on this carrier

Removing the keytrack→cutoff route makes the model **closer** to the pinned
render — in every kt≠0 note window, not only in aggregate (per-window RMS
deltas −195.5, −139.6, −142.9, −224.6, −337.3, −113.1 LSB; kt=0 windows
unchanged to the LSB, as they must be). The control-validity probe P6 shows
the same thing for the **velocity** route into the same destination, whose
depth is 5.8× larger (max 15,300, RMS −29.33). So the effect is **not
keytrack-specific**: on this carrier the landed SXT-026a residual (F-48a:
transient quantization error at bell attacks, RMS ≈ 1,326 LSB against a
12,582 LSB reference peak) is larger than the audio effect of the entire
cutoff-modulation path and partially cancels it.

Two readings remain open and are **not** resolved here: (a) the modeled
keytrack contribution is wrong in a way #48's velocity-route evidence could
not expose, or (b) F-48a compensates a correct contribution. The
discriminating experiment is an **oracle A/B**: render the same preset
twice on the pinned engine with the keytrack depth set to 0 via the host
modulation API and compare the engine Δ to the model Δ. That requires an
oracle host — **NOT_RUN** here, filed as a follow-up and routed to
SXT-013/#12. Nothing was tuned to make a number look better, and no control
was reclassified to make the leaf pass.

## 6. Applicability boundary and coverage delta (measured)

`tools/kt_applicability_scan.py`, `artifacts/applicability-scan.json`
(committed normalized graphs only; an **upper bound**, never a support
claim — the authoritative gate is `InputsV2` over an engine-readback
sidecar, and support additionally needs #12 and the wet path):

* 3,561 presets scanned; **802** route `ms_keytrack` in scene A.
* Top keytrack destinations corpus-wide: **A VCA Gain 144**, A Filter 2
  Cutoff 111, **A Filter 1 Cutoff 106**, A Amp EG Decay 80, A Volume 79,
  A Osc 3 Unison Detune 74, A Pan 63, … — i.e. the frozen class covers a
  minority of real keytrack usage, and the commonest destination of all
  (VCA Gain) is deliberately outside it.
* Presets whose whole route table is inside this leaf's class: **3**.
* Of those, presets that also pass the graph-visible voice-class screen:
  **1** — `Rozzer/Bells/Hell's Bells.fxp`, i.e. the carrier the landed
  SXT-026a leaf already models.

**Supported-preset delta from this leaf: 0.** Of the issue's 34
recovery-basis presets, **0** are in class. All three carriers named in the
issue body are refused, for keytrack-specific reasons (they route keytrack
into oscillator parameters this leaf does not model):

* `Inigo Kennedy/Atmospheres/Alone.fxp` — keytrack → A Osc 1 Feedback (226),
  A Osc 1 Low Cut (228), A Osc 3 Width (250), A Osc 3 Unison Detune (254), …
* `…/Autumn 2.fxp` — keytrack → A Osc 1 Skew Vertical, A Osc 1 Formant,
  A Osc 3 Feedback, A Osc 3 Unison Detune, …
* `…/Disturbances.fxp` — keytrack → A Osc 1 Width, A Osc 3 Skew Vertical,
  A Osc 3 Unison Detune, plus a scene route to Filter 2 Cutoff.

The leaf is registered in the machine-readable ledger
(`reports/coverage-v1/leaf-verification.json`, key `mod:keytrack`) with
`rtl_vs_model` **PASS** and `model_vs_reference` **FAIL**, and
`reports/coverage-v1/coverage.json` was regenerated by
`tools/publish_coverage.py` from the committed inputs: the leaf shows
`support_ready: false`, and the headline totals are **unchanged**
(supported 0, adapted 165, unsupported 1,132, unresolved 2,264;
`per-preset.csv` byte-identical). Registering this leaf promotes no preset.

This matches, with keytrack-specific reasons and an independent method, the
SXT-035 observation that `Alone.fxp` is refused end-to-end. The issue's
"34 newly-enabled / 310 corpus B4-predicted" figures are **requirement
attribution only** (the issue marks their essentiality UNVERIFIED); no
preset becomes supported by this work, and no adapted preset is counted.

## 7. Findings (recorded, bounded)

* **F-042-1 — keytrack modsource initial value (model corrected).** The
  engine seeds `ms_keytrack` with 0 in the voice constructor and installs
  the pitch-derived value only at the end of a control pass; #48 seeded it
  with the pitch value. Corrected here with the citation. On this class the
  correction is **render-inert** (keytrack reaches filter parameters only,
  which the constructor pass does not propagate) — verified byte-identical,
  so it changes no landed number while making the freeze match the engine.
  It becomes observable as soon as keytrack routes to a ctor-pass-visible
  word (e.g. VCA Gain — outside this leaf's class).
* **F-042-2 — silent route drop on the classic kind (fixed).** The
  classic-kind branch of `VoiceV2._calc_ctrldata` never ran the voice-route
  pass, so a classic-kind fixture carrying velocity/keytrack routes would
  have dropped them silently. Both kinds now run one route pass, and the
  route pass itself refuses unknown destinations instead of ignoring them.
  No landed fixture carried such a route (all landed renders bit-identical),
  and no classic-kind keytrack carrier is renderable today, so the fixed
  path is **exactness-verified only** (no reference render exercises it).
* **F-042-3** — see §5 (reference check non-discriminating on this carrier).
* **F-042-4** — see §3 (1.4 % max|Δ| residual between the projected
  reference and the uncommitted SXT-026a oracle render; unattributed).

## 8. NOT_RUN (no pinned oracle on this host — never reported as a pass)

* Any **new** engine render: the oracle A/B for F-042-3; a runtime-added
  keytrack route to Filter 1 Resonance / FEG Mod (so those two live
  destinations have **exactness evidence only**, on the declared synthetic
  fixture, and **no** reference number); reference renders for the issue's
  three named carriers (also refused on class grounds).
* `extract_kt_inputs.py`'s engine-readback mode: the committed sidecar was
  produced with `--allow-offline-provenance` and records
  `provenance_mode: "offline-committed-state"` plus
  `engine.readback: "NOT_RUN…"`. Without that flag the extractor **refuses**
  (exit 2) rather than guessing. Its offline provenance is four independent
  committed records cross-checked against each other (census blob, graphs
  row + `sha`, the #48 schema-2 sidecar's `graph_echo`, and the SXT-025
  fixture manifest).

## 9. Reproduce

```bash
python3 model/voice/extract_kt_inputs.py --allow-offline-provenance
python3 tools/kt_reference_from_fixture.py \
  --out reports/SXT-042/artifacts/reference-sxt025-accept-v1-bells-dry.wav \
  --json reports/SXT-042/artifacts/reference-provenance.json
python3 model/voice/run_kt_model.py \
  --sequence model/integration/sequences/sxt025-accept-v1.json \
  --out-dir /tmp/sxt042/run-canonical
python3 model/voice/run_kt_model.py --synthetic-routes \
  --sequence model/integration/sequences/sxt025-accept-v1.json \
  --out-dir /tmp/sxt042/run-synthetic
python3 tools/compare_kt_rtl_model.py --run-dir /tmp/sxt042/run-canonical \
  --out reports/SXT-042/artifacts/exactness-kt-sxt025-accept-v1.json
python3 tools/compare_kt_rtl_model.py --run-dir /tmp/sxt042/run-synthetic \
  --out reports/SXT-042/artifacts/exactness-kt-synthetic-class-cover.json
python3 model/voice/run_kt_model.py --sequence leaf48-smoke-bells-v1 \
  --out-dir /tmp/sxt042/run-smoke
python3 tools/compare_kt_rtl_model.py --run-dir /tmp/sxt042/run-smoke \
  --out reports/SXT-042/artifacts/exactness-kt-leaf48-smoke-bells-v1.json
python3 tools/kt_negative_controls.py \
  --artifacts reports/SXT-042/artifacts --work /tmp/sxt042-controls \
  --synthetic-run-dir /tmp/sxt042/run-synthetic \
  --reference reports/SXT-042/artifacts/reference-sxt025-accept-v1-bells-dry.wav
python3 -m pytest tests/test_sxt042_keytrack.py -q     # 20 passed
```

**Re-verification actually run on this branch** (after fast-forwarding onto
`origin/main` `644a02d`, which had landed the shared comparator's wet-path
tail gate (#93/#99) and the `rms_diff_dbfs` polarity audit (#95/#98) — the
tail gate does not apply to these dry comparisons and the polarity fix was
already in the base this work was built on):

* every command above re-run end to end from a clean scratch directory —
  the regenerated sidecar (`bells_kt_inputs.json`), reference projection
  (sha256 `afb3ad51…`), canonical model render (sha256 `3d4f3fd4…`) and all
  three exactness JSONs are **byte-identical** to the committed artifacts;
* the negative-control transcript reproduces line for line apart from its
  timestamp and scratch paths (`overall: ALL CONTROLS FAIL THEIR CHECK`,
  exit 0), including the identical baseline row (max 16,721 / −27.86 dBFS /
  0.9207) and the same three NON-DISCRIMINATING labels;
* the two RTL mutants still FAIL integer equality (50 and 42 mismatches) and
  the unmutated `tb_kt.sv` still PASSes with 0 mismatches;
* the §1 no-drift claim re-checked directly, not inherited: all nine landed
  renders regenerated in this tree are **byte-identical** (`cmp`) to their
  committed artifacts — `run_model.py` v1 ×3 and through the schema-2 sidecar
  ×3 vs `reports/sxt-022/artifacts/model-<seq>.wav`, `run_mw_model.py` ×3 vs
  `reports/sxt-035/artifacts/model-<seq>.wav` (sequences
  `seq-notes-repeated-v1`, `seq-notes-coverage-v1`, `seq-modwheel-v1`); the
  SXT-026a bells smoke identity is asserted by
  `tests/test_sxt042_keytrack.py::test_runner_render_is_byte_identical_to_the_landed_model`;
* full suite: `python3 -m pytest tests -q` → **230 passed, 13 skipped**
  (the skips are the pre-existing oracle-absent skips, not new); CI-equivalent
  checks also run green here: `tools/check_census_consistency.py`,
  `tools/compile_backlog_dag.py --check`, `python3 -m compileall`, and
  `tools/coverage_negative_controls.py` (all coverage staleness/refusal
  controls still fail as designed after the ledger entry was added).

The 26,250-block model renders take ~66 s each; `tb_kt.sv` elaborates and
runs in ~2 s under `iverilog -g2012`. Model renders are deterministic
(re-running reproduces the committed `model-…-bells-dry.wav` sha256).

## 10. Licensing / provenance

Everything under `model/voice/`, `rtl/voice/`, `tools/kt_*.py`,
`tools/compare_kt_rtl_model.py`, `tests/test_sxt042_keytrack.py` and
`reports/SXT-042/` is original to this repository (Apache-2.0 per
`LICENSE`). The pinned GPL engine source was **read** at the pinned commit
(fetched to a scratch path outside the repository) and is cited by file and
construct; no Surge source, tables, presets or assets are copied into this
repository. Method (fail-closed extraction, exactness harness, negative
controls, evidence shape) follows the landed SXT-022 / SXT-026a / SXT-032 /
SXT-035 conventions.

## 11. Explicitly NOT established by this work

* Any fidelity, preset-support or preset-quality claim (budgets FAIL and are
  not frozen; supported delta 0; no listening record).
* Keytrack behaviour at destinations outside {F1 Cutoff, F1 Reso, F1
  FEG-Mod} — notably VCA Gain, pan, volume, oscillator parameters, EG times,
  LFO amplitudes and FX, which together account for most corpus keytrack
  usage.
* Keytrack under pitch bend, portamento, MPE or non-standard tuning (all of
  which would make the declared 1-control-pass lag observable), in scene B,
  or as a modulation destination.
* That the modeled keytrack contribution improves agreement with the pinned
  engine (F-042-3 says the opposite is measured on this carrier, cause
  unresolved).
* Any FPGA/gf180mcu synthesis, place-and-route, timing, power, area or
  hardware-playback result.
