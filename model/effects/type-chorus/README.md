# SXT-028c frozen fixed-point model — Chorus (`model/effects/type-chorus/`)

Frozen reference for the SXT-028c RTL (`rtl/effects/type-chorus/`). The RTL
must match this model **exactly** (integer equality at declared checkpoints
and on every output sample; `tools/compare_rtl_model_chorus.py`).
Model-vs-pinned-engine agreement is a SEPARATE claim governed by
[PROPOSED] error budgets that are **not frozen** — achieved numbers are
reported in `reports/SXT-028c/EVIDENCE.md`, verdicts PENDING-FREEZE
(SXT-017, #12). **No Chorus budget may freeze before #12 decides the
shared LFO-modulated delay-line-semantics finding of SXT-023** (issue #16);
the chorus delay-time path is the same modulation class.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`)
- Structure authority (READ + cited; nothing copied):
  `src/common/dsp/effects/ChorusEffect.h` + `ChorusEffectImpl.h`
  (`ChorusEffect<4>`: `init`/`setvars`/`process`; the engine instantiates
  `v = 4` voices — `Effect.cpp:86`). The `sst-effects` `include/sst/effects/Chorus.h`
  at the pinned submodule commit is an **empty header** in this pin; the
  native `ChorusEffect` is the algorithm authority (it is also what the
  pinned loader instantiates for `fxt_chorus4`). Shared machinery:
  `vembertech/lipol.h` → `lipol_sse<BLOCK_SIZE,false>` (same ramp class as
  Delay), `Lag.h` `OnePoleLag<float,true>` (per-voice time lag, rate
  0.001), sst-filters `BiquadFilter.h` (TDF2, per-sample coefficient lag,
  `coeff_HP`/`coeff_LP2B` at Q=0.707), `Clippers.h` `hardclip_block`
  (±1), `Effect.h` `applyStereoWidth` + `MidSide.h`,
  `SurgeSincTableProvider.h` (`SurgeStorage::sinctable1X` IS this table —
  the chorus reuses `model/effects/delay/sinc_table.py` unchanged).

## Algorithm (frozen schedule, mirrors `ChorusEffectImpl.h::process`)

1. Control pass per block (`setvars(false)`): feedback lipol target
   `0.5·amp_to_linear(fb)`; `rate = envelope_rate_linear(−rate) ·
   (temposync ? temposyncratio : 1)` (engine stores rate in float32 — the
   model quantizes through float32 once); `tm = n2p(12·time) ·
   (temposync ? temposyncratio_inv : 1)`; per voice j: `lfophase[j] += rate`
   (wrap > 1, no direction flip), `lfoout = (2·|2φ−1| − 1)·depth`,
   `time[j].newValue(48000 · tm · (1 + lfoout))`; hp/lp coefficients from
   lowcut/highcut; mix/width lipol targets. `init()` (`setvars(true)`)
   sets plain lipol targets + coefficients and the per-voice phases
   `lfophase[i] = i/3` and sqrt-law `voicepan[i]` with gainscale
   `1/√4`; **no instantize** — the engine's chorus never instantizes; the
   first block ramps from the zero constructor state and the time lags
   first-run-snap at the first process block.
2. Per sample k, per voice j: time-lag process; `i_dtime =
   max(32, min((int)v, 2^18−13))`; `rp = ((wpos − i_dtime + k) − 12) &
   (2^18−1)`; sinc phase `clamp((int)(256·(i_dtime+1−v)), 0, 255)`;
   12-tap sinc read of the **mono** line (48 external reads/frame;
   **unmasked** — reads may cross into the padding words `line[2^18..2^18+11]`,
   which the engine refreshes from `line[0..11]` only when `wpos == 0`;
   the wrap-read staleness is reproduced exactly, never masked away);
   voice output panned by the fixed voicepan (L/R); voices summed.
3. highcut gate → lp, then lowcut gate → hp (TDF2 stereo, per-sample
   coefficient lag d = 0.004).
4. ONE mono `fbblock = wetL + wetR` → feedback ramp → hardclip ±1 →
   `+= dataL += dataR`; line write at wpos (32 writes/frame) + the
   12-word padding copy when `wpos == 0` (once per 8192 blocks).
5. width (mid/side halving exact; side scaled by the width ramp; mid
   intact); mix crossfade `dry·(1−t) + wet·t`; `wpos += 32` (masked).

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| audio samples, line words | **Q10.21** signed 32-bit | range ±1024; line = mono, 2^18+12 words/instance |
| sinc table | **Q2.29** signed 32-bit | `delay/sinc_table.py` unchanged |
| block-rate gain ramps + voicepan | **Q13.18** signed 32-bit | feedback/mix/width lipol; voicepan quantized once at init |
| biquad coefficients + lags + TDF2 state | **Q24.43** signed 64-bit | shared `delay_model.Biquad` |
| per-voice time lag state/targets, lfophase, LFO rate | **Q24.43** signed 64-bit | engine: float32 lag state, double phase, float32 rate — declared deviations |
| tap MAC | Q68 accumulator | sinc(Q2.29)×line(Q10.21)=Q50, ×pan(Q13.18)=Q68, rounded once to Q10.21 |

Arithmetic rules (FROZEN, `qmath.py`): exact products, round-half-up,
saturating; no floating point at audio run time; double precision only at
control rate, quantized once.

## Per-instance state

One `ChorusState` holds: the mono line (2^18+12 words, external writable),
wpos, 4 lfophase words, 4 time lags (v/target), 2 biquads (lags + TDF2
registers), 3 lipol ramps, integrity hash, ext counters. Two configured
Chorus slots are two `ChorusState` objects with two disjoint lines —
state is never shared (AGENTS.md; issue #55 acceptance).

## Declared control-plane boundary (model → RTL)

Streamed one word per line (`<slug>_ctrl.hex`): master amplitude; per
instance: feedback/mix/width RAW lipol targets (3 × Q13.18 — the RTL
applies the 0.25/0.75 smoothing recurrence), the 4 per-voice time-lag
targets (Q24.43, already including the LFO term — the lfophase
accumulators, LFO rate and depth are control-plane), 10 biquad
coefficient targets (Q24.43), flags word (bit0 lp_on / highcut active,
bit1 hp_on / lowcut active). The RTL computes everything audio-rate:
per-voice lag recurrences, i_dtime/sinc phase/tap reads, panning sums,
filters, hardclip, feedback MAC, line write + padding copy, width,
crossfade.

## Declared scope omissions (fail-closed)

* Parameter modulation INTO chorus parameters (no fixture uses it).
* The `envf` member is declared but unused by the pinned `process` (read,
  confirmed; not modeled).
* Chorus in scene-B insert slots (bins routing, SXT-028h scope) — this
  leaf's fixtures exercise ains/global/send roles only.

## Files

* `chorus_model.py` — frozen model (+ `model_revision()` frozen-revision
  pin consumed by the RTL comparator; a stale harness refuses to PASS)

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). Structure read and
cited from the pinned GPL-3.0-or-later tree; no code or tables copied.
Constant inventory: **no opaque designed constants** (unlike Reverb1's
delay-time tables, DR-0003, or Galactic's multipliers, DR-0006) — every
constant is either a formula re-derivation (sinc table, envelope rate,
n2p, db_to_linear, biquad builds, voicepan sqrt law) or a small cited
algorithmic literal (`0.001` lag rate float32 pair, feedback scale 0.5,
biquad Q 0.707, triangle-LFO shape, 0.25/0.75 lipol smoothing), each
cited to its pinned source location in `chorus_model.py`.
