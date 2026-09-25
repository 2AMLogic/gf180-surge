# SXT-028c evidence record — Chorus (ChorusEffect<4>): frozen fixed model,
# exact RTL, per-instance state, shared delay-semantics dependency noted

Branch: `loom/leaf-55-chorus` · Issue: #55 (SXT-028c) · Parent: #21
(SXT-028) · Date: 2026-09-23

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).
Algorithm authority: pinned `src/common/dsp/effects/ChorusEffect.h` +
`ChorusEffectImpl.h` (the engine instantiates `ChorusEffect<4>`,
`Effect.cpp:86`). The issue's pinned-source pointer
(`libs/sst/sst-effects@adcac695.../include/sst/effects/Chorus.h`) is an
**EMPTY header at that pin** — the native `ChorusEffect` is what the pinned
loader instantiates for `fxt_chorus4` and is the structure authority read by
this leaf (read + cited, nothing copied; the deviation from the issue text
is recorded here). Shared machinery (lipol_sse ramp, OnePoleLag time lags,
sst-filters BiquadFilter TDF2, hardclip, MidSide width, sinc table) is the
same family the landed Delay/EQ models cite;
`SurgeStorage::sinctable1X` IS `SurgeSincTableProvider`'s table, so
`model/effects/delay/sinc_table.py` is reused unchanged.

**Claim discipline.** This record advances: (1) *RTL matches the frozen
fixed-point model exactly* (iverilog; demonstrated), and (2) *the model
reproduces the pinned reference within [PROPOSED] budgets on the fixture
presets* (measured, PENDING-FREEZE). It establishes **no** preset-support
claim, **no** musical-quality claim (no human listening), **no**
FPGA/gf180mcu synthesis, timing, area, or hardware-playback claim, and it
**freezes no budget**. No generic substitute is used under any support
claim — NC-A proves the reference budgets reject one.

## 0. SXT-017 dependency (explicit, not resolved here)

Per the issue's marker: **Chorus shares Delay's LFO-modulated delay-line
semantics.** The chorus delay-time target is
`samplerate * n2p(12*t) * (1 + lfoout)` — the LFO term is *multiplicative*
on the whole delay time (Delay's is additive ±LFOval), so the open SXT-023
delay-budget finding (LFO term presence in the delay-time path;
`reports/sxt-023/delay-budget-diagnosis.md`) applies to the Chorus delay-
time path too. **No Chorus reference budget may freeze before SXT-017
(#12) decides**, coordinating with #16. All reference verdicts below are
therefore PENDING-FREEZE by construction, regardless of achieved numbers.

Measured finding for the freeze: on this leaf's fixtures the achieved
model-vs-engine residuals sit at the **fixed-vs-float quantization floor
class** (−79 to −106 dBFS RMS; max ≤ 1,230 LSB Q10.21) *with* the LFO
active — i.e. the delay-slice's LFO-presence miss did NOT reproduce at
Chorus operating points. This is an input to #16/#12, not a resolution of
either.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact | **PASS** (5 cases; 3 mutants CONTROL-OK) | `rtl-exactness.json` |
| Model ↔ pinned engine vs [PROPOSED] budgets | **6/6 PASS (PENDING-FREEZE; freeze gated on #12/#16)** | `artifacts/compare-*.json` |
| Negative controls live | **6/6 CONTROL-OK** (model-side) + 3 RTL mutants | `negative-controls/`, `rtl-exactness.json` |
| Complete-wet preset renders | 3 carried out (all-active classes landed); issue-named presets refused | §1 |
| Newly-enabled presets supported | **0** (honest delta; see §7) | this record |

## 1. Fixtures, applicability boundary (fail-closed), refusals

Determinism screen (graphs: drift == 0, non-muted osc retrigger on, fx_bypass
= all-FX, fx_disable == 0, no FX-destination modulation routes) over the 331
B4-scope candidates left 18 full-chain-feasible deterministic presets; the
render-level 3× bit-identical gate then REFUSED two of them, so the leaf
carries three carriers × two SXT-012 sequences:

| Preset | Chorus slot | Chain | Complete-wet? |
|---|---|---|---|
| `patches_factory/Basses/FM Combo.fxp` (issue carrier) | ains2 | eq ains1 → chorus ains2 | yes (rendered) |
| `patches_3rdparty/Luna/MPE/FM Twang 2.fxp` | ains1 | chorus only | yes (rendered) |
| `patches_3rdparty/Giana Brotherz/FX/Alien Appears.fxp` | global2 | reverb1 global1 → chorus global2 | yes (rendered) |

Refusals retained as evidence (never silently dropped):

* **Issue-named presets:** `Novuo.fxp` and `Ancient FM.fxp` REFUSED at
  extraction (drift ≠ 0 — not in the bit-identical determinism class);
  `Piercing.fxp` REFUSED (active Conditioner = unlanded sibling class,
  SXT-028b). Transcript: `artifacts/extract-refusals.txt`.
* `Melon.fxp` and `Drone Bee.fxp` passed the graphs screen but FAILED the
  3× render determinism gate (engine-level nondeterminism the normalized
  graph does not expose; Drone Bee already in its all-off DRY bus) — no
  fixture committed. Transcript: `artifacts/render-refusals.txt`.
* `Scrooz Loop`, `V. K. 5`, `Polished Cheese` et al. — drift ≠ 0 (static
  screen); not extracted.
* **Static screen ≠ render gate:** Melon/Drone Bee demonstrate that the
  graphs-level determinism screen cannot replace the render gate. Recorded
  for SXT-012/SXT-013 methodology.
* Every wet fixture carries a committed all-off DRY bus (3× bit-identical,
  FX-type read-back verified Off) — the comparison drives the model with
  the dry bus and compares against the wet bus; the bypass tests retain
  the unmodified wet reference (AGENTS.md).

Comparability: both SXT-012 sequences (seq-notes-coverage-v1,
seq-poly-8-v1); no normalization, no time-warping, no reference switching;
native levels; identical tails (2.5 s) between wet and dry.

## 2. Frozen fixed-point model

`model/effects/type-chorus/chorus_model.py` (+ freeze doc
`model/effects/type-chorus/README.md`). Frozen words: audio/line Q10.21
s32; sinc Q2.29 (shared `delay/sinc_table.py`); gain ramps + voicepan
Q13.18; biquad/lag/lfophase Q24.43. Per-sample schedule mirrors the pinned
`ChorusEffect<4>::process` order exactly: per-voice lag process →
i_dtime/rp/sinc-phase → 12-tap sinc read of the MONO line (**UNMASKED** —
reads cross into the 12 padding words that the engine refreshes from
line[0..11] only when wpos == 0; the wrap-read staleness is reproduced,
never masked away) → sqrt-law voicepan sum → lp (highcut) → hp (lowcut) →
ONE mono fbblock = wetL+wetR → feedback ramp → hardclip ±1 → += inL += inR
→ line write (+ padding copy when wpos == 0) → mid/side width → mix
crossfade. `init()` reproduces `setvars(true)`: plain lipol targets and
coefficient build, per-voice phases `i/3`, **no instantize** (the engine's
chorus never instantizes; the time lags first-run-snap at the first
process block).

Declared deviations (bounded, absorbed by the [PROPOSED] budgets; same
classes as the landed Delay/EQ models): engine float32 audio/state
arithmetic → Q-format (≤ 1 LSB/op); float32 lag state; lfophase Q24.43
(engine double; wrap keeps the error bounded); LFO rate quantized through
the engine's float32 `rate`; control-rate formulas evaluated in double
(engine table lerp is float32). **No opaque designed constants** (unlike
DR-0003/DR-0006): every constant is a formula re-derivation or a small
cited algorithmic literal — recorded in [DR-0007](../../decision-records/0007-chorus-constant-inventory.md)
(PROPOSED).

**Constant-inventory provenance**: the lag rate float32 pair
(`0.001f`, `1−0.001f`), feedback scale `0.5·amp_to_linear`, biquad Q
0.707, triangle-LFO shape, `0.25/0.75` lipol smoothing, and the sqrt-law
voicepan are each cited to their pinned source location in the model
docstring. A decision record (DR-0007, PROPOSED, 0003/0006 pattern) makes
the inventory visible and extends 0003's "any further opaque constant
requires a successor record" rule.

## 3. Model vs pinned engine — [PROPOSED] budgets (PENDING-FREEZE)

Method: committed fixture buses (3× bit-identical gate, SXT-012 policies:
controller reset, 0.25 s settle, block-quantized scheduling, 2.5 s tail);
the model replays the settle phase from constructor state, is driven by the
dry bus de-amped by the converged master amplitude (declared input
boundary, SXT-023 pattern), and is compared against the engine's wet bus at
native levels. Budgets = the SXT-023 effect-slice proposals (max ≤ 8,192
LSB; rms ≤ −46 dBFS; corr ≥ 0.98) — proposals, not frozen policy; the
freeze is gated on #12/#16 (§0).

| Case | max abs (LSB ≤ 8192) | rms (dBFS ≤ −46) | spectral corr (≥ 0.98) | tail | Verdict |
|---|---|---|---|---|---|
| fmcombo × notes | 274.9 | −98.42 | 1.000000 | present | **PASS** (PENDING-FREEZE) |
| fmcombo × poly-8 | 114.4 | −106.01 | 1.000000 | present | **PASS** (PENDING-FREEZE) |
| fmtwang2 × notes | 186.4 | −101.42 | 1.000000 | present | **PASS** (PENDING-FREEZE) |
| fmtwang2 × poly-8 | 177.2 | −99.58 | 1.000000 | present | **PASS** (PENDING-FREEZE) |
| alienappears × notes | 530.4 | −94.59 | 0.999999 | present (−54.9 dB rel) | **PASS** (PENDING-FREEZE) |
| alienappears × poly-8 | 1,230.1 | −79.65 | 1.000000 | present | **PASS** (PENDING-FREEZE) |

Artifacts: `artifacts/compare-<slug>__<seq>.json` (per-channel + mono +
tail metrics, budgets, verdicts). Model wet buses:
`artifacts/model__<slug>__<seq>.f32.wav`; per-instance truth traces:
`artifacts/trace_<slug>__<seq>.json.gz`.

Reverb1 bridging (alienappears, declared): the frozen Reverb1 model keeps
its own s24-device/Q4.28 boundary; the chain feeds Q10.21 → Q4.28 by exact
<<7 (split <<2 + the model's internal <<5, unclamped — the engine never
clips the FX chain at ±1) and returns via round-half-up >>7. Bridge error ≤
1/2 LSB at Q10.21 (~−132 dB class), absorbed by the budgets; the reverb1
model is unchanged.

Diagnosis trail (kept honest): the reference leg initially FAILED with
corr 0.67 — two real defects were found and fixed before any budget was
touched: (1) the model wrapped lfophase at 0.5 (the Delay convention)
instead of 1.0 (chorus phase lives in [0,1]); (2) the runner replayed 240
settle blocks while the fixture harness settles 375 blocks
(`int(0.25 s × 48 kHz) / 32`) — a 135-block (2.8 s) timeline
misalignment that no ±32-sample shift scan can see. (2) was localized by
oracle tap instrumentation (DR-0005/0006 method): branch `sxt028c-tap`
(single commit `21056f915` on the pin; tap header sha256 `556581c6…`),
DSP-neutrality shown by the tap-build render being **bit-identical** to the
committed fixture (wet+dry sha256 match). The tap's per-voice
`lfophase/time_v/target` trajectories also confirmed the control plane
matches the engine to float32 print precision. Reconciliation: the
committed fixtures were themselves rendered on the earlier SXT-037 tap
build identified in their sidecars (`engine_version_string`
`1.4.sxt037-tap.ff8b4dba4`), so it is the recorded bit-identical wet+dry
cross-check of `sxt028c-tap` against those committed fixtures that bounds
the render-time build, not a fresh render on the `sxt028c-tap` build; the
residual gap — a fresh re-render of the fixtures on the `sxt028c-tap`
build — is recorded here as unverified.

Mid-render patch-change/reset on the engine side remains **BLOCKED** by the
known surgepy embedding limitation (host-thread `loadPatch`; documented in
sxt-024 §3). Reset semantics are exercised exactly in the RTL
`prs-reset48-128` case (bulk clear + constructor reset = the engine's
fx-rebuild path); panic (`allNotesOff`) is a voice-stage action and the
fixture sequences exercise note-offs + declared tails.

## 4. RTL vs frozen model — EXACT (iverilog)

`rtl/effects/type-chorus/tb_chorus.sv` +
`tools/compare_rtl_model_chorus.py` → `rtl-exactness.json` (status
**PASS**). Two instances behind separate external-memory regions; the
per-voice lag recurrences, tap reads, TDF2 filters, hardclip, feedback MAC,
line write + padding copy, width, and crossfade are audio-rate RTL; the
control plane (lipol RAW targets, per-voice lag targets incl. the LFO
term, coefficient targets, flags) is streamed. Compared with exact integer
equality: every per-instance output sample (O), every tap-interpolation
checkpoint (X: per voice per captured sample the i_dtime / sinc phase /
read-position triple), every declared state checkpoint (T: wpos, 4× lag
v/target, lipol targets, biquad lags + TDF2 registers, per-instance line
hash and ext counters), and the frozen-revision pin (a stale trace revision
refuses PASS).

| Case | Blocks | Stimulus | Result |
|---|---|---|---|
| prs-dual-128 | 128 | PRS, 2 instances serial, disjoint regions | **EXACT** |
| prs-reset48-128 | 128 | same + bulk clear + core reset at block 48 | **EXACT** |
| canonical-fmcombo-512b | 875 | full runner stimulus (settle incl.), 1 instance | **EXACT** |
| canonical-fmtwang2-256b | 631 | full runner stimulus, 1 instance | **EXACT** |
| canonical-alienappears-256b | 631 | full runner stimulus (reverb1 bridge upstream), 1 instance | **EXACT** |

RTL mutant negative controls (each must FAIL): wrong tap interpolation
(sinc-phase clamp removed → wrong table phase), pooled memories (shared
state across instances), wrong lag ramp (time-lag recurrence coefficient
doubled — the LFO-trajectory-class defect) — **all CONTROL-OK (FAIL the
exactness check)**.

Per-instance state acceptance (issue #55): two concurrent instances keep
independent histories — disjoint external regions, per-instance equality,
and the shared-memory mutant demonstrably FAILS the dual-instance check
(prs-dual-128 + mutant-shared). No deterministic corpus preset carries two
chorus instances (the two found carry drift ≠ 0), so the dual-slot fixture
is synthetic, as the issue's fixtures plan allows.

## 5. Negative controls (each must FAIL the check it targets)

`tools/chorus_negative_controls.py` → `negative-controls/` — baseline
sanity first (the unmutated chain passes; max 186 LSB), then all
**CONTROL-OK**:

| Control | Result |
|---|---|
| NC-A generic substitute (nearest-sample taps, equal pans, same boundary) | **fails** the reference budgets (adapted ≠ supported) |
| NC-B dropped tail (render truncated 1.5 s early) | **fails** the tail-region agreement check |
| NC-C wrong order (two serial instances A→B vs B→A) | **flagged** by the order-sensitive equality check |
| NC-D stale stub (frozen-revision pin) | **refused** by the comparator (never PASS) |
| NC-E bypass transparency (mix=0 exact to 1.30 LSB ≤ 4 LSB declared; injected mix=0.001 leak detected at 797 LSB) | **leak detector live** |
| NC-F LFO-rate mutant (chorus rate doubled) | **fails** the reference budgets — the LFO path is load-bearing |

Plus the three RTL mutants of §4 (wrong interp / shared state / lag ramp).

**Follow-up (#93, shared-comparator level).** NC-B above demonstrates the
tail-truncation mismatch magnitude via a bespoke slice-only budget check in
`tools/chorus_negative_controls.py`; it does not exercise a gate in the
shared comparator itself. Issue #93 adds a tail-region gate to
`tools/compare_audio_reference.py` (the tool the other 13 landed/PENDING
leaf lines use, not this leaf's own `compare_chorus_reference.py`, whose
`tail_check` predates and is unaffected by #93) and a companion control —
`tools/shared_comparator_tail_negative_control.py` →
`negative-controls/shared-comparator-drop-tail*` — that truncates this
leaf's own committed `alienappears / seq-notes-coverage-v1` wet fixture and
runs it through the shared comparator end-to-end: the whole-render budget
alone PASSES TRIVIALLY (the truncated model is a byte-identical prefix of
the reference, so the only compared samples are an exact match), and only
the new tail-region gate catches the dropped tail. See #93's PR for the
full re-run evidence across all seven report families that use the shared
comparator.

## 6. External-memory traffic and state (SXT-015/016 conventions)

`tools/chorus_buffer_report.py` → `artifacts/buffer-requirement.json`
(measured from the frozen model's per-instance transaction counters):

* Per-instance external writable state: **ONE mono line of 262,156 × 32-bit
  words = 1,048,624 B (0.9999 MiB)** — the SXT-015 placeholder-class
  estimate for Chorus is confirmed exactly by this leaf.
* Traffic: **49.0 words/sample = 196 B/sample = 9.41 MB/s at 48 kHz per
  instance** (48 reads = 4 voices × 12-tap sinc; 1 mono write; + a 12-word
  padding copy once per 8192 samples-of-blocks amortized). Two slots =
  2 × 1,048,624 B state, 18.8 MB/s — far inside the 800 MB/s placeholder
  bandwidth; the shared-instance schedule bounds Chorus without findings.
* On-chip small state ≈ **284 B/instance** (4× lag v/target, 4× lfophase,
  lp/hp lags + TDF2 registers, 3 lipol ramps, wpos/counters/hash); the
  Q68 tap accumulator is combinational; voicepan is frozen ROM.
* Flash is never writable delay memory; long buffers are external
  WRITABLE memory; all processing stays in-chip (plan section 3).

## 7. Newly-enabled presets (honest delta)

The issue's upper bound: 331 B4-scope candidates (factory 25, contributor
306), 175 strict-FX-complete. After this leaf the per-preset support
status is unchanged: **supported stays 0** — the conjunction in
`reports/coverage-v1/README.md` still fails for every carrier at earlier
gates (voice leaf #48 unlanded; fidelity freeze #12 open; Delay class
landed-FAIL for carriers that use it; listening BLOCKED-on-human #8/#9).
What this leaf adds is the `fx:Chorus` class evidence itself
(PENDING-FREEZE caveat), recorded in the coverage ledger
(`reports/coverage-v1/leaf-verification.json`).

## 8. What this record does NOT establish

- Any fidelity policy or frozen budget (SXT-017/#12; all numbers are
  against [PROPOSED] tolerances; freeze gated on the shared
  delay-semantics decision with #16).
- Any preset-support or musical-quality claim; no human listening has
  occurred (#8/#9 BLOCKED-on-human). Essentiality of the SXT-014 ablation
  delta (2.083 dB, diagnostic) remains UNVERIFIED.
- FPGA/gf180mcu synthesis, place-and-route, timing, power, or hardware
  playback; the RTL is an iverilog-simulated schedule (version recorded in
  `rtl-exactness.json`).
- Any claim about sibling effect classes (Conditioner SXT-028b etc.) or
  about the Delay LFO mechanism (owned by #16).
- Repeatability beyond the committed 3× gates (per-render determinism is
  recorded per fixture sidecar).

## 9. Reproduce

```sh
# oracle host: extraction, fixtures, model runs, reference comparisons
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 tools/extract_chorus_inputs.py
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 tools/render_chorus_fixtures.py
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 model/effects/run_chorus_model.py \
    --slug fmcombo --seq seq-notes-coverage-v1   # per slug/seq
ORACLE_SURGE_DIR=$HOME/oracle/surge python3.11 tools/compare_chorus_reference.py \
    --slug fmcombo --seq seq-notes-coverage-v1

# anywhere with iverilog (RTL exactness; canonical traces committed)
IVERILOG=iverilog python3.11 tools/compare_rtl_model_chorus.py

# anywhere (negative controls + buffer report; model-side)
python3.11 tools/chorus_negative_controls.py
python3.11 tools/chorus_buffer_report.py

# unit/integrity tests
python3 -m pytest tests/test_sxt028c.py -q
```

## 10. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`).
Chorus structure is read and cited from the pinned GPL-3.0-or-later tree
(`src/common/dsp/effects/ChorusEffect{,Impl}.h` and the shared sst
machinery); no Surge source, tables, or assets are committed. The oracle
tap patch script and patched tree stay on the oracle host (method pinned
in DR-0006; this leaf's tap branch: `sxt028c-tap`, single commit
`21056f915`, tap header sha256 `556581c658cf8d76392c99cf291ec07ada61a2b8b76d2d9525bfcbb2ab72d3ef`).
No distribution-license determination has been made for Surge-derived
material.
