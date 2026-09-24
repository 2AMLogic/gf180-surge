# SXT-034 evidence record — voice leaf: unison stack topology (>1 voice)

Branch: `loom/leaf-68-unison` · Issue: #68 (SXT-034) · Date: 2026-09-22

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).
Renders and simulations for this record were produced on the pinned-oracle
host `~/oracle/surge` (Ubuntu, iverilog 11.0, python 3.11); the RTL harness
was made iverilog-11-compatible for this host (task-return restructure;
trace proven byte-identical).

**Claim discipline.** This record advances exactly two of the three claims:
(1) *the RTL matches the frozen fixed-point unison model exactly* at every
declared checkpoint, and (2) *model-vs-pinned-reference numbers are
recorded* on the unison fixtures against [PROPOSED] budgets
(PENDING-FREEZE), with bounded misses that are **not tuned away**. It
establishes **no** fidelity verdict (budgets are proposals; the freeze is
#12/#17), **no** preset-support claim (see §5: no real corpus preset is
renderable inside this leaf's topology; the 92-preset recovery attribution
needs the whole leaf stack), **no** musical-quality claim, and **no**
FPGA/gf180mcu synthesis, timing, area, or hardware-playback claim.

## 1. Frozen model and freeze doc

`model/voice/voice_model.py` extended with the unison stack; freeze doc
`model/voice/README.md` §"SXT-034 unison stack extension" (word lengths
unchanged from SXT-022 — Q10.21 samples/coefs, Q2.29 envelopes, Q13.18
pitchmult_inv — plus the unison constants and op order above). Pinned
structure citations: `ClassicOscillator.cpp` (init / prepare_unison /
convolute / process_block), `OscillatorCommonFunctions.h`, `sst-basic-blocks
OscillatorDriftUnisonCharacter.h` (UnisonSetup attenuation / detune
bias-offset / pan law), `SurgeVoice.cpp:1044` (the osc `stereo` flag is
`is_wide = (fbc == fc_wide)` — unison pan spread is inert in serial-1),
`SurgeStorage.h` (MAX_UNISON=16).

**Uni=1 regression (bit-identity with the landed slice):** after the
refactor, the uni-1 model render of `seq-notes-repeated-v1` is
byte-identical to the committed SXT-022 artifact
(`reports/sxt-022/artifacts/model-seq-notes-repeated-v1.wav`, sha256
`6a73bb9adeb81602b3d25829319a8d29839e1f8ec24705ae152bdb225b097f6d`), and
re-verified after every later model change. The uni=1 path multiplies by
`out_attenuation = 1.0` exactly (bit-identity mechanism).

## 2. Fixtures (declared-override pattern; no real corpus uni>1 preset exists)

A fail-closed scan of all 3,561 normalized graphs for the SXT-022 voice
gates with Classic osc uni≥2 returns **no renderable preset** (3 near-misses
blocked by K35/SVF filters, waveshaper, lowcut, or split scenes — committed
per-preset in `artifacts/carriers-not-renderable.json`). The unison
mechanism is therefore validated on **declared overrides** (SXT-012 pattern,
`fixtures/diagnose_variation.py` precedent) of the census-verified
`Basses/Attacky.fxp` carrier: the oscillator unison-voices parameter set via
the official host parameter path (`setParamVal`), read back and recorded
(`model/voice/extract_uni_inputs.py`); everything else stays at the
preset's own normalized state. Overrides are **test configuration** — never
an adapted preset, never a coverage claim.

| fixture | carrier | declared override | sequence | frames | determinism class |
|---|---|---|---|---|---|
| uni1-regress | Attacky.fxp | none (uni=1 no-op) | seq-notes-repeated-v1 | 196,800 | bit-identical ×3 |
| uni2-cov | Attacky.fxp | uni=2 (readback 2) | seq-notes-coverage-v1 | 273,600 | bit-identical ×3 |
| uni2-poly | Attacky.fxp | uni=2 (readback 2) | seq-poly-8-v1 | 177,600 | bit-identical ×3 |
| uni4-rep | Attacky.fxp | uni=4 (readback 4) | seq-notes-repeated-v1 | 196,800 | bit-identical ×3 |
| uni16-smoke | Attacky.fxp | uni=16 (readback 16) | sxt034-smoke-v1 (leaf-local) | 16,800 | bit-identical ×3 |
| uni4-mech | Attacky.fxp | uni=4 + retrigger OFF | sxt034-uni-mech-v1 (leaf-local) | 28,800 | quantified variation (see §6) |

All five retrigger-on reference renders are **bit-identical across 3 fresh
engine instances** (`artifacts/reference-*.json`, `render_sha256` arrays) —
unison alone adds no engine RNG. The uni1 render is sha-identical to the
SXT-012 harness render of the same preset on this host (`e86f79af…`),
proving the override harness byte-faithful; it differs from the committed
SXT-022 macOS-host reference WAV by max 1 LSB / 867 samples — the known
cross-host float-environment boundary (fixtures/README.md: hosts re-run
rather than assume equality). The int16-model comparisons below use this
host's references throughout; no reference switching.

## 3. RTL-vs-frozen-model exactness (integer equality) — PASS

`tools/compare_rtl_model.py` (extended: per-unison-voice `U` checkpoint
lines, per-creation init-draw table in the control plane). iverilog,
integer equality, zero mismatches everywhere:

| fixture | checkpoints | state fields | osc samples | mono samples | mismatches |
|---|---|---|---|---|---|
| uni1-regress | 403 | 13,299 | 25,792 | 196,800 | **0** |
| uni2-cov | 467 | 18,213 | 29,888 | 273,600 | **0** |
| uni2-poly | 616 | 24,024 | 39,424 | 177,600 | **0** |
| uni4-rep | 403 | 20,553 | 25,792 | 196,800 | **0** |
| uni16-smoke | 101 | 12,423 | 6,464 | 16,800 | **0** |
| uni4-mech (non-retrigger draws) | 104 | 5,304 | 6,656 | 28,800 | **0** |

Per-voice checkpoints cover every unison voice's impulse state (oscstate,
state, last_level, pwidth, pwidth2, dc_uni) at the SXT-022 checkpoint
blocks, plus the shared oscillator output block and every mono sample.
(`artifacts/exactness-*.json`.)

## 4. Model-vs-reference budgets (PENDING-FREEZE; recorded, not tuned)

Comparator `tools/compare_audio_reference.py` (dry policy, no
normalization, no time-warping; shift-0 primary). Proposed bounds are the
SXT-022 placeholders (max_abs ≤ 3500 LSB, rms ≥ −46 dBFS, corr ≥ 0.98):

| fixture | max_abs LSB | rms dBFS | corr | best_shift | vs proposals |
|---|---|---|---|---|---|
| uni1-regress | 2,321 | −33.3 | 0.9874 | −4 | **PASS all three** (identical to the landed SXT-022 metrics) |
| uni2-cov | 22,767 | −18.5 | 0.9624 | −27 | FAIL max, corr |
| uni2-poly | 65,534 | −8.4 | 0.9548 | −1 | FAIL max, corr |
| uni4-rep | 27,455 | −15.1 | 0.9822 | −25 | FAIL max |
| uni16-smoke | 36,240 | −9.7 | 0.8678 | −17 | FAIL max, corr |

(`artifacts/uni1-rep.json`, `uni2-cov.json`, `uni2-poly.json`,
`uni4-rep.json`, `uni16-smoke.json`.)

**Bounded finding (recorded, escalation routed):** the SXT-022 [PROPOSED]
budgets were derived from the unison-1 slice and do not hold at uni>1. The
misses are the declared deviation classes compounding across N detuned
voices — float32 phase-pipeline vs exact-integer `ipos` per voice
(sub-sample impulse jitter at different detune rates → beat-phase
differences the max metric cannot absorb), `mech::rcp` vs exact `qdiv` in
each voice's DC path (now active: Attacky sub mix 0 → `dc_uni ≠ 0`), and
fixed-word quantization — not a topology error (the uni1 regression is
bit-identical, and RTL-vs-model is exact at every unison). rms passes all
proposals at every unison; spectral corr passes at uni4. Per AGENTS.md and
the leaf's stop/escalate clause this is **not** resolved here by weakening
or tuning: it is routed to the SXT-013/#12 freeze together with SXT-026's
deep-mip finding — either the freeze sets unison-class budgets or
justifies tighter model numerics. No budget was changed to pass.

## 5. Real-preset coverage and recovery attribution (honest delta)

* The issue-named carriers (`Edges Rhythm`, `Bad News`, `King`) are **NOT
  renderable** inside this leaf's topology (Window/FM oscillator families,
  multiple mixer paths, enabled FX, split scenes, fbc≠serial-1) — recorded
  per-carrier with graph evidence in `artifacts/carriers-not-renderable.json`.
  They were not approximated, substituted, or partially counted; no wet or
  adapted render of them is claimed.
* **No real corpus preset is enabled end-to-end by this leaf alone.** The
  unique in-every-other-gate Classic-uni2 presets are blocked by
  filter-family/lowcut/waveshaper features owned by #71, #48, and the
  output-stage scope; `artifacts/carriers-not-renderable.json` carries the
  corpus scan.
* The **92 newly-enabled slate presets / 794 B4-predicted corpus presets**
  in the issue are requirement attribution for unison>1 support across all
  oscillator families + effects. This leaf contributes the topology
  boundary (stack arithmetic, per-instance unison state, MAX_UNISON cap,
  voice-pool multiplication) that those presets require ON TOP of the
  family/integration/effects leaves. Coverage attribution is therefore:
  **0 presets supported by this leaf alone; requirement satisfied for the
  Classic family at the voice-slot level.** No adapted preset counts toward
  anything.

## 6. Non-retrigger init-draw path (mechanism, exactness-only)

`uni4-mech` forces the per-oscillator retrigger OFF (SXT-012 diagnostic
override class) so the engine's free-running init formula
`oscstate[i] = 0.5·rand_01()·ntpi(detune_i)` is exercised. The engine's
`rand_01()` is wall-clock seeded (no seed API) — **no reference-fidelity
claim is possible or made** for this fixture (NOT_RUN against reference).
The model consumes **declared** draw words
(`attacky_uni4_nodraw_inputs.json`), consumed per voice creation in order
(control-plane draw table, ctrl word 31); RTL-vs-model is exact over the
full fixture (§3) including two distinct draw sets.

## 7. Costs (recorded against SXT-015/SXT-016; no technology claim)

Measured op counts of the exact RTL schedule (1 MAC/cycle assumption
A-DSP-1c; behavioral schedule, not cycle-accurate RTL):

| fixture | qmuls | blocks | convolute calls | MAC/48kHz-sample |
|---|---|---|---|---|
| uni1-regress | 7,422,740 | 6,150 | 344 | 37.7 |
| uni2-rep (same sequence) | 7,427,580 | 6,150 | 488 | 37.7 |
| uni2-cov | 10,903,134 | 8,550 | 1,350 | 39.9 |
| uni2-poly (8 slots × 2) | 23,586,144 | 5,550 | 4,259 | 132.9 |
| uni4-rep | 7,443,544 | 6,150 | 964 | 37.8 |
| uni16-smoke | 957,322 | 525 | 902 | 57.0 |
| uni4-mech | 1,620,114 | 900 | 216 | 56.3 |

**Divergences recorded, not reconciled away:** (a) the unison multiplication
lands on the OSCILLATOR stage only — the per-voice-slot filter chain,
mixer, and decimator are unison-invariant (engine structure: unison lives
inside the oscillator; one oscbuffer pair per oscillator is SHARED), so
MAC/sample at fixed polyphony is nearly flat in unison while convolute
calls scale ~N at low pitches (impulse counts are pitch- and
detune-rate-dependent; voice phase residuals carry across blocks);
(b) uni2-cov's qmul count is +14k over SXT-022's uni-1 coverage number —
the explicit attenuation multiply (identity at uni=1) plus voice-2
convolutions; (c) SXT-015's `osc_state_bytes_per_unison` = 512 B/voice
(placeholder-v0) vs this slice's measured 24 B/voice impulse scalars +
70 B/voice shared-buffer share at uni=16 — the placeholder stays the
planning number (conservative), the measurement is the SXT-016 refinement
input; (d) uni2-poly confirms the worst-case multiplication direction
(16 unison-osc instances over 8 slots → 132.9 MAC/sample integrated) but is
an integrated-slice number, not comparable to SXT-016's osc-only kernel
probes (same non-comparability note as SXT-022 §4).

State (per voice slot, as scheduled): shared impulse buffers 8,960 bits +
slot scalars 160 bits + per-voice 192 bits × N (uni=16: 4,032 bits/slot
total impulse machinery) + control-plane words.

## 8. Negative controls (live; committed transcript)

`artifacts/negative-control.txt` — five controls, each demonstrably fails
the check it targets:

| control | mutation | targeted check | outcome |
|---|---|---|---|
| NC-1 unison-collapsed (issue-required) | model config: stack forced to 1 voice vs the uni2 reference | reference-budget | **FAIL** (max 11,743 / corr 0.9554); differential vs true model max 18,238 LSB |
| NC-2 detune-zeroed | model config: spread forced 0 | reference-budget | **FAIL** (max 12,717 / corr 0.9676); differential vs true model max 20,883 LSB |
| NC-3 beyond-limit | uni=17 input | load-time cap | **exit 1**, "unison 17 outside 1..MAX_UNISON(16): explicitly rejected (no clamp)", no render |
| NC-4 voice-count mutant | `voice_uni_mutant.sv`: fill loop `uni_n`→1 (single line) | RTL-vs-model exactness | **FAIL**, 105 mismatches from block 0 |
| NC-5 rounding (legacy) | `voice_broken_mutant.sv` qmul bias <<20→<<19 | RTL-vs-model exactness | **FAIL**, 98 mismatches |

Honest caveat (also in the transcript): with the current [PROPOSED] budgets
the reference-budget check itself is not yet discriminating at uni>1 — the
true model also misses the max/corr proposals (§4 finding). The budget
freeze (#12) must set unison-class budgets under which NC-1/NC-2 fail while
the true model passes; until then the exactness controls (NC-3/4/5) are the
hard gates and NC-1/NC-2 demonstrate the required "must FAIL" behavior of
the live check.

## 9. What remains unproved

* No fidelity verdict: §4 budgets are unfrozen proposals; misses are a
  bounded finding owned by #12, not accepted performance.
* No preset-support or preset-quality claim: no real corpus preset renders
  end-to-end in this slice (§5); no listening record exists; essentiality
  of the 92-preset slate remains UNVERIFIED (#8/#9).
* Non-Classic unison (Window/FM/Wavetable families at uni>1), fc_wide pan
  spread (stereo bus), scene-width paths, drift ≠ 0, detune modulation,
  sync, and FM are outside this leaf; the wt leaf (SXT-026) separately
  covers the WaveTable family's unison at uni≤16.
* No FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback; all cost numbers are simulated op counts under named
  assumptions.
* `Snare Tight.fxp` / census-parser caveat untouched (SXT-011 resolved it
  natively; not exercised here).

## Licensing / provenance

Everything under `model/voice/`, `rtl/voice/`, `tools/compare_*.py`, and
`reports/SXT-034/` is original to this repository (Apache-2.0 per
`LICENSE`). The pinned GPL engine was imported at runtime only (external
oracle host); no Surge source, tables, presets, or payloads were copied.
All unison structure facts are cited (file + line in the freeze doc);
numeric tables are the SXT-022 ones (provenance there) — no new third-party
constants were adopted, so no new license decision record is required.
Reference WAVs in `artifacts/` are this project's own renders under the
declared test configuration, not redistributed upstream content.

## 10. Post-rebase re-verification on the merged tree (2026-09-23)

The branch was rebased onto main `1800409` — which landed SXT-026a/voice
generality (#86), SXT-033/classic slice (#87), SXT-035/modwheel (#89) and
SXT-028a/Galactic (#90) after this leaf's original rebase — and the merged
model+RTL (a new frozen artifact) was re-evidenced end-to-end. The semantic
overlap resolutions are freeze-doc decisions recorded in
`model/voice/README.md` §"Composition with SXT-026a (voice generality) and
SXT-033 (classic slice) on the merged model" (per-voice `t`/`t_inv` vs the
SXT-033 sync machine = same freeze decision under the sync≠0 refusal;
drift refused at 0 on all sides; the SXT-033 12000× pitch-helper finding is
LIVE at uni>1, kept un-absorbed and co-routed to #12; the merged init-word
map: v1 0..39, SXT-026a appendix 40..77, SXT-034 unison appendix 78..127,
draw table 128+, ctrl word 31 = draw_set_index).

All numbers below were regenerated on the pinned-oracle host against the
MERGED tree (head `18f5c58` at rerun time); committed artifacts were
replaced where counts changed and left untouched where identical:

* **uni=1 byte-identity holds**: the merged model render of
  `seq-notes-repeated-v1` is still sha256
  `6a73bb9adeb81602b3d25829319a8d29839e1f8ec24705ae152bdb225b097f6d`
  (identical to the SXT-022 artifact), re-verified after the final merge
  fix. Mechanism unchanged: `out_attenuation = 1.0` exactly, detune 0,
  inert fractional term.
* **Six-fixture RTL==model exactness: PASS, 0 mismatches** on the merged
  tb/model (`artifacts/exactness-*.json`, updated). Per-checkpoint state
  fields increased by exactly +2 (the SXT-026a `f4_r0`/`f4_r1` T-line
  fields) — e.g. uni1-regress 13,299 → 14,105 = 403 checkpoints × 2;
  checkpoints/osc/mono counts unchanged.
* **References unchanged**: all five retrigger reference renders re-rendered
  bit-identically ×3 (`render_sha256` arrays equal to the committed record
  — e.g. uni1 `fe383e58…`, uni2-cov `67623e48…`); the pinned engine is
  untouched by the merge.
* **Budget metrics reproduce exactly** (max_abs / corr / best_shift
  identical to §4 on all five fixtures; rms equal to float precision).
  uni1 passes all proposals; uni>1 misses stand as recorded — the §4
  bounded finding is unchanged and now ALSO names the SXT-033 pitch-helper
  finding as a candidate contributor (README composition §3).
* **Negative controls NC-1..5 reproduce** (`artifacts/negative-control.txt`
  post-rebase appendix): FAIL / FAIL / exit-1 / 105 / 98.
* **Full pytest on the merged tree: 131 passed, 12 skipped, 0 failed**
  (`ORACLE_SURGE_DIR` set; skips are main-inherited optional-oracle gates —
  the one suite regression found during the rebase, an `InputsV2.__init__`
  body accidentally nested under a helper method, was fixed in-commit and
  is covered by the SXT-026a suite).
* **Coverage rerun**: `publish_coverage.py` regenerates the committed
  `per-preset.csv` + `coverage.json` byte-for-byte; headline statuses
  unchanged; **0 presets supported** (supported_set count 0, note
  unchanged).
* **#67/SXT-033 evidence intact on the merged model**: `tools/run_sxt033_checks.py`
  → **OVERALL PASS** (classic RTL-vs-model exactness PASS; rounding-style
  mutant FAILs as required; submode-confusion NCs FAIL as required;
  out-of-class extraction REFUSED; budget matrix regenerated from committed
  renders agreeing with the committed JSONs to float-ULP noise ≤1e-15 in
  `spectral_corr` — committed files left untouched).

The merged-state claims remain exactly the two of §"Claim discipline": RTL
matches the frozen unison model exactly; model-vs-reference numbers are
recorded against [PROPOSED] budgets with bounded misses. No fidelity
verdict, no preset-support claim, no synthesis/hardware claim is added by
the rebase.
