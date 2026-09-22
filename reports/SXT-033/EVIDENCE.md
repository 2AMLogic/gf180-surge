# SXT-033 evidence record — voice leaf, oscillator family: Classic (beyond Attacky)

Branch: `loom/leaf-67-classic` · Issue: #67 (SXT-033) · Date: 2026-09-22

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, mono (L+R)/2 evidence bus. Classic-family
authority: pinned `src/common/dsp/oscillators/ClassicOscillator.cpp/.h`,
`OscillatorBase.h` (prepare_unison), sst-basic-blocks
`OscillatorDriftUnisonCharacter.h` (UnisonSetup / CharacterFilter),
`SurgeStorage.cpp` init_tables, `SurgeVoice.cpp` (mono/stereo osc call, pfg,
megapan), `Parameter.cpp` (param ranges) — read and cited, never copied.

**Claim discipline.** This record advances exactly two of the three claims:
(1) *RTL matches the frozen fixed-point model exactly* (iverilog-simulated;
integer equality, demonstrated over five canonical runs), and (2) *the model
reproduces the pinned reference within [PROPOSED] budgets* — measured
per carrier class, PENDING-FREEZE, with bounded findings recorded (§4). It
establishes **no** preset-support claim (coverage delta = zero promotions,
§6), **no** musical-quality claim (no human listening has occurred), and
**no** FPGA/gf180mcu synthesis, timing, area, or hardware-playback claim.
The RTL is an iverilog-simulated behavioral schedule, not synthesis-closed.

## 0. Scope and carriers

The leaf extends the landed SXT-022 Attacky configuration (shape 0, sub mix
1, sync 0, unison 1) to the Classic family's declared parameter classes, as
observed in the 94 recovery-basis presets' committed normalized graphs
(shape −1..1 · widths 0.019..0.910 · sub 0..1 · sync 0.57..28.6 in 21 slots
· unison 2..16 in 64 slots · spread 0..0.2) — no new algorithm: the same
frozen 4-state impulse machine, plus the engine's hard-sync restart branch
and per-unison-voice machinery, both declared classes. Engine-declared
ranges read at the pin (`ct_percent_bipolar`, `ct_percent`, `ct_syncpitch`
[0,60], `ct_oscspread` [0,1] with `get_extended`=12f, `ct_osccount` [1,16]).

| Carrier (all in the recovery-basis list) | Modeled slot (post-override) | Classes exercised |
|---|---|---|
| `Argitoth/Rhythms/Edges Rhythm.fxp` (issue carrier) | osc 2 (index 1) | sub mix = 0.0 (main path; `dc_uni`/`t_inv` live), Warm character, scene pan −0.2625 (mono pan law) |
| `Emu/Plucks/Horn Ring Boops.fxp` (issue carrier) | osc 2 (index 1) | unison 6, spread 0.163, Neutral character |
| `Lopyt/Soundscapes/Tentacles.fxp` | osc 3 (index 2) | hard sync 28.607 semitones (syncstate restart machine) |
| `Basses/Crush Bass.fxp` | osc 1 (index 0) | unison **16** (ceiling), shape −0.754, width 0.347, sub mix 0.362 partial |

Every reference render runs the DECLARED fixture configuration
(`model/oscillators/classic/fixture_config.py`, readback-verified): other
mixer paths (oscs/noise/ring modulators) muted, both filter units + FX +
waveshaper + scene lowcut off, `fbc` pinned to fc_serial1 (the mono voice
path: `SurgeVoice` calls the oscillator with `stereo = (fbc == fc_wide)`),
FM switch off, scene mode Single, retrigger ON, drift 0. These are test
configurations, never adapted presets, never coverage.

## 1. Acceptance mapping (issue #67)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order documented | **PASS** | `model/oscillators/classic/README.md` (freeze doc: classes, Q formats, per-convolute op order, declared deviations, fail-closed refusals); model `classic_model.py` shares the frozen SXT-022 tables/Q discipline by import |
| 2 | Model-vs-pinned-engine dry-render budgets on the carrier fixtures | **PASS/PENDING-FREEZE (achieved numbers recorded, not tuned)** | §3 matrix: 10 budget JSONs (4 carriers × coverage/repeated). No bound is frozen; misses are recorded as findings (§4), not widened |
| 3 | RTL-vs-model exact at declared checkpoints | **PASS** | §2: five canonical integer-equality runs (4 carriers + smoke config), 687,451 state fields, 346,432 osc samples, 790,272 mono samples, zero mismatches; `exact-*.json` |
| 4 | Cycle/state costs recorded vs SXT-016 probes / SXT-015 accounting | **PASS (recorded; divergence note)** | §5: measured model-side qmul (MAC) counts of the frozen schedule with the iverilog tb counter as cross-check, re-measured at the branch tip during the post-freeze re-verification; reconciled against `probe_osc__classic_blit__ph24__a24__m32__onchip` exactly as SXT-022 did (probe = osc kernel alone at declared assumptions; this measurement = integrated mono slice). Planning numbers, not technology claims |
| 5 | Negative controls must demonstrably fail | **PASS (all three fail as designed)** | `negative-control.txt`: (a) single-constant RTL mutant FAILS exactness (95 mismatches from block 0); (b) submode-confusion substitution (Attacky-class arithmetic, unison forced 1) FAILS the reference-budget check on both unison carriers, strictly worse than the declared-class model; (c) out-of-class preset (House Of Chords — Classic only in scene B) REFUSED by the fail-closed extractor, exit 2 |

## 2. RTL-vs-frozen-model exactness (integer equality)

`tools/compare_classic_rtl_model.py` compiles `rtl/oscillators/classic/
tb_classic.sv` (plus the shared sinc ROM hex from the model) with iverilog
and requires INTEGER EQUALITY of: the envelope state machine, the
per-unison-voice impulse state (oscstate, syncstate, state, last_level,
pwidth, pwidth2, dc_uni — all 16 voice entries per slot), the shared
extraction/character stage (dc, osc_out, osc_out2, bufpos, hpf_prev, lag
words), every 64-sample oscillator output block at every declared
checkpoint (blocks 0, 1, every 64th, every released voice's block), and
every 48 kHz output sample.

| Canonical run (full `seq-notes-repeated-v1`) | checkpoints | state fields | voice-checks | osc samples | mono samples | verdict |
|---|---|---|---|---|---|---|
| edges (uni1, sub0) | 2,731 | 346,837 | 2,731 | 174,784 | 196,800 | **PASS** |
| horn (uni6) | 1,867 | 237,109 | 11,202 | 119,488 | 196,800 | **PASS** |
| tentacles (sync 28.6) | 403 | 51,181 | 403 | 25,792 | 196,800 | **PASS** |
| crush (uni16) | 403 | 51,181 | 6,448 | 25,792 | 196,800 | **PASS** |
| smoke config (uni4, sync 12.5, shape −1, d_s 1, r_s 2; 96 blocks) | 9 | 1,143 | 36 | 576 | 3,072 | **PASS** |

| **total** | **5,413** | **687,451** | **20,820** | **346,432** | **790,272** | zero mismatches |

The committed mutant (`classic_broken_mutant.sv`, qmul bias `<<20`→`<<19`)
FAILS the same comparison on the edges canonical run (95 mismatches from
block 0, `exact-mutant-edges.json`) while the clean RTL passes — the
rounding constant is live in every fixture.

## 3. Model-vs-reference budgets (PENDING-FREEZE, measured)

Comparator: `tools/compare_audio_reference.py` (dry policy; no
normalization, no time-warping; shift-0 primary). Proposed SXT-022 bounds
(max ≤ 3500 LSB · rms ≤ −46 dBFS · spectral corr ≥ 0.98) are placeholders;
nothing is frozen. Reference renders are committed with sidecars
(determinism: 3 fresh-instance repeats bit-identical per fixture).

| Fixture | max LSB | rms dBFS | corr | shift | ref peak LSB | ref clipped |
|---|---|---|---|---|---|---|
| edges / coverage | 90 | −74.7 | 0.9635 | 0 | 468 | 0 |
| edges / repeated | 54 | −79.4 | 0.9728 | 0 | 414 | 0 |
| horn / coverage | 10,189 | −32.9 | 0.7018 | −23 | 9,093 | 0 |
| horn / repeated | 3,801 | −34.7 | 0.8035 | −1 | 9,608 | 0 |
| tentacles / coverage | 239 | −61.2 | 0.9668 | 0 | 473 | 0 |
| tentacles / repeated | 77 | −66.1 | 0.9723 | 0 | 357 | 0 |
| crush / coverage | 65,534 | −12.9 | 0.9876 | −1 | 32,767 | 17,637 |
| crush / repeated | 22,759 | −23.3 | 0.9944 | −2 | 32,767 | 17,637 |

Two reporting artifacts of the shared comparator/policy, recorded rather
than tuned around: (1) the comparator evaluates the rms proposal as a floor
(`rms ≥ −46`), so quieter-is-better residuals more than 46 dB down (edges,
tentacles) print as proposal misses — under the proposal's stated intent
("residual RMS at least this far below FS") those rows PASS; numbers are
reported unmodified. (2) edges/tentacles reference renders peak at
≈350–470 LSB (≈1.3% FS): at native int16 levels the ±1 LSB render
quantization dominates the log-spectral correlation, which caps corr ≈
0.96–0.97 regardless of the (excellent) sample agreement.

## 4. Bounded findings (recorded, not absorbed)

**F-033-1 — detuned-unison agreement class.** With per-voice detune active
(horn uni6, corr 0.70–0.80) the model and the engine decorrelate faster
than the sub-only/sync classes. Discriminating experiments: with spread 0
the six-voice render matches the one-voice render identically (corr 0.9302
both, machinery exact); the divergence grows within a note and resets on
retrigger. Mechanism verified against the pinned source: the engine's
per-voice `oscstate` accumulation and `ipos` formation are float32
(`ClassicOscillator.cpp` convolute), so six independently-jittered impulse
streams shift the inter-voice beat pattern; the frozen model is
exact-integer by contract. Same class as the SXT-026 deep-mip finding.
Resolution (float32 phase pipeline vs declared comparison methodology)
belongs to the #12 freeze owner, not this leaf.

**F-033-2 — landed SXT-022 pitch-helper fractional term.**
`voice_model.ntpi_tuningctr`/`ntpi_ignoring_tuning` interpolate the
fractional semitone with `2^(idx/1000)`; the pinned construction is
`table_two_to_the_minus[i] = 2^(−i/12/1000)` (`SurgeStorage.cpp`
init_tables) — 12000× steeper and sign-flipped. INERT in the SXT-022
Attacky slice (the argument is identically 0 there) but LIVE in any detune
or sync class: with the landed helper, detuned voices render ±0.163
semitone spread as ≈±2 semitones and asymmetric clusters (measured before
the fix). The frozen SXT-022 files are untouched; the corrected pinned
construction is used here (`classic_model.ntpi_tuningctr`, unit-tested)
and the SXT-022 artifact is routed to #12/#48 for a visible contract
revision. This finding was found BY the budget checks and fixed BEFORE the
§3 numbers were taken — no budget was widened to absorb it.

**F-033-3 — Pluck 2 Pad Demon Sad applicability.** A recovery-basis preset
whose scene-A graph carries live modulation routings (velocity → AEG
release, LFO amplitude chains, Osc 3 mod amounts) outside the declared
model boundary. Budget numbers taken before the gate showed a delayed-onset
reference the model cannot reproduce — the preset was DEMOTED from the
carrier set, the extractor now REFUSES presets with non-inert scene-A
routings (fail-closed; only destinations provably inert under the declared
overrides — filter/waveshaper parameters, FM depth with the FM switch off —
are accepted), and `inputs/pluck.json` was removed. Its earlier numbers are
not used as evidence. All other carriers have zero out-of-slice routes.

**Environment note.** The shared remote box's pinned oracle tree was moved
off-pin and its surgepy binary truncated by concurrent work mid-session;
the pinned commit `58914e59c` was rebuilt in a separate worktree
(`~/oracle/surge-pin`, build `build-sxt033`) and verified to reproduce the
committed reference renders byte-identically (sha256
`e19a21ca…` re-measured post-rebuild) before any further oracle use. All
committed reference artifacts carry engine identity in their sidecars.

## 5. Costs (planning numbers, not technology claims)

Measured MAC counts of the frozen schedule, full `seq-notes-repeated-v1`
(tool `tools/count_classic_model_qmuls.py`: every `voice_model.qmul` call
of the model render — the model is the schedule's specification and each
qmul is one multiply of the declared Q discipline; 1 MAC/cycle assumed,
A-DSP-1c). The iverilog tb's own `qmul()` counter is the RTL-stimulus
cross-check; it undercounts by a structural amount only (the tb inlines
the per-tap `term*gain` product outside its `qmul()` function — values
are still integer-equal, which is what the exactness claim covers).

| Run | model qmul (MAC) | MAC / mono sample | tb qmul() cross-check |
|---|---|---|---|
| edges (uni1, sub0) | 7,493,250 | 38.1 | 7,464,408 |
| tentacles (uni1 + sync 28.6) | 6,547,258 | 33.3 | 6,532,384 |
| horn (uni6) | 7,053,087 | 35.8 | 7,029,384 |
| crush (uni16, ceiling) | 6,249,033 | 31.8 | 6,237,144 |

The counts are nearly flat in unison: the frozen impulse machine injects
its sinc taps per impulse EVENT (per voice cycle) and advances per-voice
phase/rate state in shift-add arithmetic, so the unison multiplier lands
on impulse-event rate, per-voice state words, and ROM/lookup lanes, not
on per-sample MAC lanes. State: per-slot impulse buffers 2×140×32 b +
16 voices × 7 words + shared stages ≈ **11.9 kbit/slot at uni1**,
**≈21.9 kbit/slot at uni16** (16×(2×64b phase + 5×32b) dominates) — within
the probe's `osc_state_bytes_per_unison` order.

Recorded divergence: the pre-freeze session's earlier cost figures
(8,441,175 edges / 47.9M horn / 121.3M crush, scaling with unison) could
not be reproduced from any committed artifact; they were unison-scaled
projections, not measurements of the frozen schedule. They are superseded
by the measured counts above, found during the post-freeze
re-verification and recorded here rather than absorbed. The SXT-016 probe
rows (`probe_osc__classic_blit__ph24__a24__m32__onchip`: 8,438,400
cyc/frame naive; 1,525,440 lp variant) remain the per-kernel planning
reference at their declared per-sample-tap assumptions — the same
recorded-divergence treatment as SXT-022. Non-MAC ops are reported as
normalized op counts only; no timing/clock claim of any kind.

## 6. Coverage delta (honest)

**Zero presets are promoted to supported by this leaf**, and none of the
headline statuses in `reports/coverage-v1/` change: every one of the 94
recovery-basis presets needs unlanded features beyond the Classic
oscillator class (scene-B graphs in 90/94, active FX in 90/94, non-LP12
filter graphs, FM targets, waveshaper, split-scene), the voice gate still
runs through the SXT-022 attacky-slice (`voice_leaf_key`), and the
fidelity-budget freeze (#12) is open. What the leaf adds is the verified
oscillator-family arithmetic — model, RTL, and reference budgets per
declared parameter class — that #48's voice-slice generalization builds on.
Ledger: `osc:Classic` landed (rtl_vs_model PASS, model_vs_reference
PARTIAL — PENDING-FREEZE with §4 findings) in
`reports/coverage-v1/leaf-verification.json` with an evidence hash pin.
Reference-verified fixture paths (test configurations): the four carriers
above; House Of Chords (an issue carrier) is recorded as refused-out-of-
scope (scene-B), not verified.

## 7. Reproducibility

```sh
python3 tools/run_sxt033_checks.py            # steps 1–4 (oracle for 4)
python3 -m pytest tests/test_sxt033_classic.py
```

Step 1 re-runs the five canonical RTL exactness runs + mutant control in a
scratch root (stimulus hex never committed); step 2 regenerates the budget
matrix from the committed reference renders (no oracle needed); step 3 the
submode-confusion control; step 4 the out-of-class refusal. Environment:
48 kHz; engine pin above; iverilog 13; python 3.11+ (model renders are pure
integer Python). Oracle-dependent tests skip as NOT_RUN when the oracle is
absent — a skipped test is never a pass.

**Post-freeze re-verification (this branch's tip).** After the freeze doc
landed, every committed artifact was regenerated from the committed tree
on the pinned reference box and checked against the committed copies: all
five canonical RTL runs PASS with checkpoint/field/voice/sample counts
identical to §2; the mutant control FAILS identically (95 mismatches,
block 0); all four model renders are byte-identical to the committed WAVs
(sha256 re-measured); both submode-confusion controls reproduce the
committed numbers exactly (crush max 33,294 / corr 0.9684; horn 7,097 /
0.7571 — both FAIL the budget check as required); the out-of-class
refusal reproduces (exit 2, same message). §5's cost table was corrected
to measured values during this re-verification; nothing else moved.

## 8. Licensing / provenance

Everything under `model/oscillators/classic/`, `rtl/oscillators/classic/`,
`tools/*sxt033*`, `tests/test_sxt033_classic.py` and `reports/SXT-033/` is
original to this repository (Apache-2.0 per `LICENSE`). The pinned GPL
engine was imported at runtime only; structure facts are cited from the
pinned tree, no source/tables/assets copied (the sinc tables are rebuilt
from the pinned construction formulas, SXT-022 discipline). Reference WAVs
are this project's own renders of loaded presets. Method only (no code)
follows the landed SXT-022/SXT-026 leaf patterns.

## 9. Explicitly NOT established by this work

* Any preset-support or preset-quality claim; the four fixture
  configurations are test configurations and count toward nothing.
* Any fidelity verdict: all §3 numbers are PENDING-FREEZE; §4 findings are
  owned by #12.
* Stereo-field behavior (is_wide path, unison pan law), scene-B graphs,
  FM-modulated Classic slots, absolute-detune mode, drift ≠ 0 — all
  declared refusals, none exercised.
* Any gf180mcu/FPGA synthesis, place-and-route, timing, power, area, or
  hardware playback result.
