# SXT-040 evidence record — voice leaf, oscillator family: Sine

Branch: `loom/leaf-74-sine` · Issue: #74 (SXT-040) · Date: 2026-09-23

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, mono (L+R)/2 evidence bus. Sine-family
authority: pinned `src/common/dsp/oscillators/SineOscillator.cpp/.h`,
`OscillatorBase.h` (pitch_to_omega), sst-basic-blocks `dsp/Lag.h`
(SurgeLag), `QuadratureOscillators.h` (SurgeQuadrOsc), `FastMath.h`
(fastsin/fastcos/clampToPiRange), `OscillatorDriftUnisonCharacter.h`
(UnisonSetup linear pan law, CharacterFilter), sst-filters `BiquadFilter.h`
(coeff_HP/coeff_LP2B identity guards, TDF2), `ADSRModulationSource.h`
(attack shapes 0/1/2, decay shapes 0/1/2), `SurgeVoice.cpp` (mono osc path,
osclevels/pfg staging, routefilter) — read and cited, never copied.

**Claim discipline.** This record advances exactly two of the three claims:
(1) *RTL matches the frozen fixed-point model exactly* (iverilog-simulated;
integer equality, demonstrated over three canonical runs + two smoke
configurations), and (2) *the model reproduces the pinned reference within
[PROPOSED] budgets* — measured per carrier, PENDING-FREEZE, with bounded
findings recorded (§4). It establishes **no** preset-support claim (§6),
**no** musical-quality claim (no human listening has occurred), and **no**
FPGA/gf180mcu synthesis, timing, area, or hardware-playback claim. The RTL
is an iverilog-simulated behavioral schedule, not synthesis-closed.

## 0. Scope and carriers

The leaf extends the landed SXT-026a Sine slice (legacy path, FMmode 0,
shape 0, unison 1, retrigger) to the family's submode selector and unison
machinery: all 32 shape modes, both behaviors (fmlegacy 0 legacy / 1
modern incl. the feedback and omega-ramp machinery), unison 1..16 with the
linear pan law (mono-inert), the lowcut/highcut biquads and the character
filter, per-instance state (phase / lastvalue / quadrature r,i /
playingramp / lags / firstblock / omegaPrior per voice), and the pinned
streaming-mismatch shape-remap semantics (normalized authority only).
Observed submode inventory: 2,223 Sine slots in the committed graphs —
shapes 0..31 (except 3/5/7/22), behaviors 0 (590) / 1 (1,633), unison
1..16.

| Carrier (all in the recovery-basis list) | Modeled slot (post-override) | Classes exercised |
|---|---|---|
| `Bluelight/Pads/Bad News.fxp` (issue carrier) | osc 3 (index 2) | legacy behavior, shape 0, unison 1, Warm character, d_s 0/a_s 1 |
| `Lopyt/Soundscapes/Tentacles.fxp` | osc 1 (index 0) | modern behavior, shape 8, unison 4, detune 0.034, instant attack, d_s 1 |
| `Nick Moritz/Keys/Popcorn 2K.fxp` | osc 1 (index 0) | legacy behavior, shape 0, unison 1, hot scene (reference saturates) |

Every reference render runs the DECLARED fixture configuration
(`model/oscillators/sine/fixture_config.py`, readback-verified): other
mixer paths muted, both filter units + FX + waveshaper + scene lowcut off,
fbc pinned to fc_serial1 (mono voice path) **and the modeled slot's output
route pinned to 1** (presets storing route 2 enter the bus via the F2-mix
B path with gain min(1, 1+filter_balance) — Bad News stores route_o3 = 2
with balance −0.684; measured 3.0× — outside the declared slice), FM off,
scene mode Single, retrigger ON, drift 0. These are test configurations,
never adapted presets, never coverage.

**Carrier selection is fail-closed, and it is the leaf's main bounded
finding (F-040-1):** of the issue's 38 recovery-basis presets, only these
three pass the declared applicability gate. Every other Sine carrier named
or implied by the slate carries live modulation into machinery this slice
does not model — typically velocity→Amp EG Attack/Decay (Mystery 4, Go
Carefully, Disturbances, Fragile 4, Autumn 2), keytrack/LFO→modeled-slot
Feedback/Pitch/Volume (Alone, Planet Surge), LFO→Pan (Shipping, Alone,
Go Carefully), LFO→scene Pitch (Winter Feelings, Chiff 4) — plus the
mono-playmode presets (Mort Snare pm=1, Arp 2 pm=2). The extractor refuses
each with exit 2 (committed transcript, Part D). Alone and Mystery 4 were
temporarily extracted as carriers during the session and were DEMOTED to
refusal controls before any budget number was used; their renders and
budget rows are deleted from the artifact set and none of their numbers
are evidence.

## 1. Acceptance mapping (issue #74)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model with word lengths + op order documented | **PASS** | `model/oscillators/sine/README.md` (freeze doc: classes, Q formats, per-block op order for both behaviors, 11 declared deviations, migration finding); model `sine_model.py` shares the frozen SXT-022 Q discipline and imports the frozen SXT-033 AEG |
| 2 | Model-vs-pinned-engine dry-render budgets on the carrier fixtures | **PASS/PENDING-FREEZE (achieved numbers recorded, not tuned)** | §3 matrix: 6 budget JSONs (3 carriers × coverage/repeated). No bound is frozen; misses are recorded as findings (§4), not widened |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | §2: three canonical integer-equality runs + two smoke configurations (incl. legacy-unison-9), 689,505 state fields, 468,672 osc samples, 596,544 mono samples, zero mismatches; `exact-*.json` |
| 4 | Cycle/state costs recorded vs SXT-016 probes / SXT-015 accounting | **PASS (recorded; divergence note)** | §5: measured model-side qmul (MAC) counts per canonical render; probe rows are per-kernel planning numbers at declared assumptions (same recorded-divergence treatment as SXT-022/SXT-033) |
| 5 | Negative controls must demonstrably fail | **PASS (all fail as designed)** | `negative-control.txt` + NC jsons: (a) single-constant RTL mutant FAILS exactness (97 mismatches from block 0); (b) wrong-family substitution (Classic arithmetic) FAILS the budget check on badnews; (c) shape-migration confusion (raw pre-migration shape) FAILS the budget check on tentacles; (d) four out-of-class presets REFUSED exit 2 (playmode × 2, live voice routes × 2) |

## 2. RTL-vs-frozen-model exactness (integer equality)

`tools/compare_sine_rtl_model.py` compiles `rtl/oscillators/sine/
tb_sine.sv` with iverilog and requires INTEGER EQUALITY of: the envelope
state machine, the per-unison-voice state (legacy: quadrature r/i/dr/di +
playingramp; modern: Q3.28 phase, lastvalue[2], omegaPrior), the shared
lags (FB/FM), the applyFilter TDF2 registers, the character-filter state,
every 64-sample oscillator output block at every declared checkpoint
(blocks 0, 1, every 64th, every released voice's block), and every 48 kHz
output sample.

| Canonical run (full `seq-notes-repeated-v1`) | checkpoints | state fields | voice-checks | osc samples | mono samples | verdict |
|---|---|---|---|---|---|---|
| badnews (legacy, shape 0, uni 1) | 403 | 38,285 | 403 | 25,792 | 196,800 | **PASS** |
| tentacles (modern, shape 8, uni 4) | 403 | 32,240 | 1,612 | 25,792 | 196,800 | **PASS** |
| popcorn2k (legacy, uni 1, poly overlap) | 6,499 | 617,405 | 6,499 | 415,936 | 196,800 | **PASS** |
| smoke config (modern, shape 8, uni 4; 96 blocks) | 9 | 720 | 36 | 576 | 3,072 | **PASS** |
| smoke config (legacy, shape 0, uni 9; 96 blocks) | 9 | 855 | 81 | 576 | 3,072 | **PASS** |
| **total** | **7,323** | **689,505** | **8,631** | **468,672** | **596,544** | zero mismatches |

The committed mutant (`sine_broken_mutant.sv`, qmul bias `<<20`→`<<19`)
FAILS the same comparison on the badnews canonical run (97 mismatches from
block 0, `exact-mutant-badnews.json`) while the clean RTL passes.

## 3. Model-vs-reference budgets (PENDING-FREEZE, measured)

Comparator: `tools/compare_audio_reference.py` (dry policy; no
normalization, no time-warping; shift-0 primary). Proposed SXT-022 bounds
(max ≤ 3500 LSB · rms ≥ −46 dBFS · spectral corr ≥ 0.98) are placeholders;
nothing is frozen. Reference renders are committed with sidecars
(determinism: 3 fresh-instance repeats bit-identical per fixture).

| Fixture | max LSB | rms dBFS | corr | shift | ref peak LSB | ref clipped | proposed max/rms/corr |
|---|---|---|---|---|---|---|---|
| badnews / coverage | 210 | −61.7 | 0.9298 | 0 | 3,635 | 0 | ✓/✓/✗ |
| badnews / repeated | 62 | −71.0 | 0.9456 | 0 | 3,635 | 0 | ✓/✓/✗ |
| tentacles / coverage | 3,458 | −26.4 | 0.9381 | 0 | 11,383 | 0 | ✓/✗/✗ |
| tentacles / repeated | 3,164 | −27.9 | 0.9731 | 0 | 11,394 | 0 | ✓/✗/✗ |
| popcorn2k / coverage | 1,789 | −47.5 | 0.9606 | 0 | 32,767 | 1,817 | ✓/✓/✗ |
| popcorn2k / repeated | 888 | −49.2 | 0.9789 | 0 | 32,767 | 886 | ✓/✓/✗ |

All six rows pass the proposed max bound; four pass the rms bound; no row
passes the spectral-corr proposal. The corr misses are the two recorded
classes below — no number was tuned.

**Tool note (rms flag, found by PR #92 judge review).**
`tools/compare_audio_reference.py` originally tested the rms residual with
an inverted comparison (`>=` instead of `<=`; the residual is
lower-is-better), so machine rms verdicts in JSONs generated before
2026-09-24 are polarity-flipped. The flag was fixed in this commit and all
eight SXT-040 budget/NC JSONs were regenerated with the corrected tool;
the regenerated machine verdicts match the hand marks above on all six
rows. Historical artifacts of other leaves generated with the inverted
flag are outside this leaf's scope and are routed as a follow-up to the
tool owner (SXT-022 lineage).

**Row note (badnews / coverage, F-040-5).** The model WAV first committed
for this row was a mis-copied artifact (byte-identical to the tentacles
repeated render; see F-040-5), and the budget JSON regenerated from it
faithfully measured the wrong bytes, contradicting this row. The
full-length render was regenerated from the committed inputs in the fix
commit; the measured numbers above are unchanged from the originally
recorded row (210 / −61.7 / 0.9298) and are now machine-verified from the
committed 273,600-frame artifact.

## 4. Bounded findings (recorded, not absorbed)

**F-040-1 — recovery-slate applicability (carrier selection).** 35 of the
38 recovery-basis presets are refused by the declared gate (mono/mono-ST
playmodes; live velocity/keytrack/LFO routes into Amp EG, Pan, Osc
Pitch/Feedback/Volume/Drift; unison-count garbage slots). The refused
presets need the modulation leaves (velocity/AEG-time, LFO→pan/pitch/
volume/feedback destinations) before they can be fixture-verified — this
is requirement attribution for later leaves, not a coverage claim now. Two
presets (Alone, Mystery 4) were briefly carried before the voice-route
gate landed; they were demoted and their artifacts deleted (§0).

**F-040-2 — spectral-corr at low render levels (quantization-cap class;
same as SXT-033 finding 2).** badnews peaks at 3,635 LSB (11% FS): at
native int16 levels the ±1-LSB render quantization caps log-spectral
correlation ≈ 0.93–0.95 regardless of the (excellent) sample agreement —
max 62–210 LSB and rms −62/−71 dBFS are at the render floor. popcorn2k
saturates its reference (peaks at FS, 886–1,817 clipped samples) and
corr 0.979 — a clipping-race residual at the hard-clip.

**F-040-3 — detuned-unison decorrelation (F-033-1 class).** tentacles
(uni 4, detune 0.034): corr 0.94–0.97, rms −26/−28 dBFS. The engine's
legacy quadrature recurrence is float32 per voice; detuned stacks wander
against the model's exact Q10.21 rotation. The modern path narrows the
double phase to float32 at the fastsin input (declared deviation 4) — a
much smaller term, but the uni>1 beat phase remains hypersensitive over
multi-second pads. No unison>1 legacy corpus fixture exists inside the
declared gate (F-040-1); the class is exactness-covered by the synthetic
legacy-unison-9 smoke configuration and budget-covered only by tentacles'
modern uni-4 rows. Resolution (float32 pipelines vs comparison
methodology) belongs to the #12 freeze owner, as recorded for SXT-026/
SXT-033.

**F-040-4 — exposure gaps (recorded, fail-closed otherwise).**
`deform_type` on the sine feedback param (fb_mode) is not observable
through surgepy; corpus-reachable states are fb_mode 0 (load_xml defaults
type_1 = 0; save_xml writes 0; no UI writer), and the fb_mode-1 blend
machinery is implemented but unexercised by fixtures. The osc
lowcut/highcut `deactivated` flags are likewise unobservable; the model
runs the biquads from param values (the engine skips them when
deactivated) — at every carrier's values (−60/70) the pinned ω>π identity
guards make both sides identical; a carrier with mid-range cut values
would need the flag resolved first (recorded for the #12 freeze owner).

**F-040-5 — committed-artifact integrity incident (badnews coverage model
WAV); found by judge review of PR #92.** The WAV first committed as
`artifacts/model-badnews-seq-notes-coverage-v1.wav` (commit `e40fd51`) is
byte-identical to `artifacts/model-tentacles-seq-notes-repeated-v1.wav`
(sha256 `3a74f9bd…`): a wrong-file mis-copy at artifact-collection time,
196,800 frames against the 273,600-frame (8,550-block) coverage reference.
The committed budget JSON for the row faithfully measured the wrong bytes
(max 12,772 LSB / rms −19.35 dBFS / corr 0.245 — all three proposed bounds
failing) and so contradicted the hand-recorded §3 row. Correction (this
commit): the full-length render was regenerated from the committed inputs
(`model/oscillators/sine/run_model.py`, `inputs/badnews.json` ×
`seq-notes-coverage-v1`; 8,550 blocks / 273,600 frames), the WAV replaced,
and the row re-measured with the corrected comparator: 210 LSB / −61.7
dBFS / corr 0.9298 at shift 0 — reproducing the originally recorded §3 row
exactly; the row passes the max and rms proposals and misses only the
standing corr class (F-040-2). No number was tuned in either direction;
the incident itself is the finding. Process gap recorded: the
artifact-collection step had no render-from-source identity check, and the
committed budget JSON had never been cross-checked against its row in this
record; re-verification (§7) now regenerates from inputs and compares.

**Environment note.** The shared box's primary oracle tree had drifted
off-pin again (surgepy self-reported `1.4.sxt037-tap`); all extraction
and rendering used the pinned rebuild `~/oracle/surge-pin` (commit
verified `58914e59c`, surgepy `1.4.HEAD.58914e59c`), which was verified to
reproduce a committed SXT-033 reference render byte-identically (sha256
`2665f3de…` re-measured) before any oracle use.

## 5. Costs (planning numbers, not technology claims)

Measured model-side qmul (MAC) counts of the frozen schedule, full
`seq-notes-repeated-v1` (`tools/count_sine_model_qmuls.py`: every
`vm.qmul` call of the model render; 1 MAC/cycle assumed, A-DSP-1c). The
iverilog tb's `qmul()` counter is the RTL-stimulus cross-check.

| Run | model qmul (MAC) | MAC / mono sample |
|---|---|---|
| badnews (legacy, uni 1) | 7,784,694 | 39.6 |
| tentacles (modern, shape 8, uni 4) | 9,031,974 | 45.9 |
| popcorn2k (legacy, uni 1, poly overlap) | 15,249,630 | 77.5 |

State: per-voice sine state is small (legacy: 4×32-bit quad words + ramp;
modern: phase + 2 lastvalues + omegaPrior), shared per slot: buffers,
biquad/char states, lags ≈ a few hundred bits + the unison arrays —
within the SXT-016 probe's on-chip assumption. The SXT-016 probe rows
(`probe_osc__sine_table__ph24__a24__m32__onchip`: 1,118,400 cyc/frame;
`probe_osc__sine_poly_fastmath__ph24`: 1,598,400) remain the per-kernel
planning reference at their declared per-sample-table assumptions; the
measured counts above are the integrated mono slice under the frozen
schedule (same recorded-divergence treatment as SXT-022/SXT-033). The
modern path's fastsin/fastcos exact-integer evaluation is a declared
audio-rate division exception to A-ALU-2 (SXT-026a rule; the RTL implements
it as a wide behavioral divider). Non-MAC ops are reported as normalized op
counts only; no timing/clock claim of any kind.

## 6. Coverage delta (honest)

**Zero presets are promoted to supported by this leaf**, and none of the
headline statuses in `reports/coverage-v1/` change: every recovery-basis
preset still needs unlanded features beyond the Sine oscillator class
(35/38 are refused by this leaf's own gate per F-040-1 — live modulation,
mono playmodes; the rest need scene-B graphs, active FX, non-LP12 filters
or the fidelity freeze), the voice gate still runs through the SXT-022
attacky-slice (`voice_leaf_key`), and the fidelity-budget freeze (#12) is
open. What the leaf adds is the verified Sine-family arithmetic — model,
RTL, and reference budgets per declared class — that the family-wide
coverage work builds on. Ledger: `osc:Sine` landed (rtl_vs_model PASS,
model_vs_reference PARTIAL — PENDING-FREEZE with §4 findings) in
`reports/coverage-v1/leaf-verification.json` with an evidence hash pin.
Reference-verified fixture paths (test configurations): the three carriers
above; alone/mystery4/mortsnare/arp2 are recorded as refused-out-of-scope,
not verified.

## 7. Reproducibility

```sh
python3 tools/run_sxt040_checks.py            # steps 1-3 (committed control set is oracle-free: see note)
python3 -m pytest tests/test_sxt040_sine.py
```

Step 1 re-runs the three canonical RTL exactness runs + mutant control in
a scratch root (stimulus hex never committed); step 2 regenerates the
budget matrix from the committed reference renders; step 3 the three
negative controls. Oracle note: the committed control set — including the
four out-of-class refusals, which reject at the committed-graphs level
before any engine is loaded — runs without the pinned oracle (re-verified
at this fix's tip with no `ORACLE_SURGE_DIR` set: runner exit 0); the
extractor itself is oracle-gated for any carrier that passes the gate
(post-gate extraction loads the pinned engine). Environment: 48 kHz;
engine pin above; iverilog (13 tested); python 3.11+ (model renders are
pure integer Python; local dev used 3.14). Reference-dependent budget
checks are NOT pytest cases — a skipped/absent environment never reports
a pass.

**Correction at this branch's tip (PR #92 judge review).** The originally
recorded re-verification claimed the budget matrix "reproduces the §3
numbers"; that was false for the badnews/coverage row: the committed model
WAV for that row was a mis-copied artifact (F-040-5), and the machine row
regenerated from it (max 12,772 / rms −19.35 / corr 0.245) contradicted
the recorded row. In this fix commit the full-length render was
regenerated from the committed inputs and replaces the wrong artifact, the
comparator's inverted rms flag was fixed, and all eight budget/NC JSONs
were regenerated. The regenerated matrix reproduces the §3 numbers on all
six rows (badnews/coverage: 210 / −61.7 / 0.9298 at shift 0), machine
verdicts now match the hand marks, and all controls fail as required. The
pytest suite passes at the tip.

## 8. Licensing / provenance

Everything under `model/oscillators/sine/`, `rtl/oscillators/sine/`,
`tools/*sxt040*`, `tests/test_sxt040_sine.py` and `reports/SXT-040/` is
original to this repository (Apache-2.0 per `LICENSE`), with one quoted
exception now carrying a visible license decision record: the 20-entry
sine wave_remap streaming-migration table transcribed in
`model/oscillators/sine/README.md` is quoted as data from the pinned
GPL-3.0-or-later `src/common/dsp/oscillators/SineOscillator.cpp`
(`handleStreamingMismatches`, `streamingRevision <= 12` block) — see
DR-0008 (`decision-records/0008-sine-wave-remap-table.md`, PROPOSED
pending owner ratification). Apart from that table, the pinned GPL
engine was imported at runtime only; structure facts are cited from the
pinned tree, no other source/tables/assets copied (the fastsin/fastcos Pade
rational is re-derived from the pinned construction formulas, SXT-026a
discipline; the shape-mode arithmetic is re-derived from the pinned SSE
formulas). Reference WAVs are this project's own renders of loaded
presets. Method only (no code) follows the landed SXT-022/SXT-026/SXT-033
leaf patterns.

## 9. Explicitly NOT established by this work

* Any preset-support or preset-quality claim; the fixture configurations
  are test configurations and count toward nothing.
* Any fidelity verdict: all §3 numbers are PENDING-FREEZE; §4 findings are
  owned by #12.
* Stereo-field behavior (is_wide path, unison pan placement), scene-B
  graphs, FM-modulated Sine slots (fm_3to2to1 modern), absolute-detune
  mode, drift ≠ 0, fb_mode 1 — all declared refusals or unexercised
  machinery, none established against the engine.
* Legacy unison > 1 model-vs-engine agreement (no in-gate corpus fixture;
  exactness covered on the synthetic smoke configuration only).
* Any gf180mcu/FPGA synthesis, place-and-route, timing, power, area, or
  hardware playback result.
