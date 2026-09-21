# SXT-023 delay budget diagnosis — the miss is the LFO term's presence, not
# lag quantization

Date: 2026-09-20 · Feeds: SXT-017 (#12) budget/word-length decision ·
Status: DIAGNOSIS (no budget changed, no frozen model modified, no support
or fidelity claim)

## 1. The miss (reproduced)

Frozen model vs pinned engine (`surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
surgepy 1.4.HEAD.58914e59c, 48 kHz, block 32), committed fixtures, native
levels, mono sum, proposed budgets max ≤ 8,192 LSB / rms ≤ −46 dBFS /
corr ≥ 0.98:

| slug | rms | max | corr | verdict |
|---|---|---|---|---|
| metallic (2 delays, send fb 0.71, LFO on) | −33.5 dBFS | 195,634 LSB | 0.9752 | FAIL |
| dexie (1 delay, fb 0, tempo-synced LFO rate 1.4125) | −44.2 dBFS | 72,737 LSB | 0.9952 | FAIL |

(`diag-base-*.json`; identical to the PR #44 A2 artifacts — reproduction
confirmed.)

## 2. Isolation result

Method: diagnostic variants of the frozen model (`tools/
diagnose_delay_budget.py`; the frozen model file is untouched) and, where
stated, diagnostic renders of a MODIFIED preset state on the pinned engine
(`tools/diagnose_delay_engine_probe.py`; declared param overrides after
loadPatch, 3× bit-identical determinism gate). Probe renders are diagnosis
inputs, not fixtures of record and not support evidence.

### 2.1 The PR #44 hypothesis is REFUTED

The declared hypothesis — "engine float32 lag-state staircase vs continuous
Q24.43 lag → ±1/256-sample sinc phase jitter, amplified by the 0.71
feedback loop" — is **not the mechanism**:

| variant | metallic | dexie |
|---|---|---|
| base | −33.5 | −44.2 |
| f32lag (SurgeLag<float> emulated: state, target, coefficient pair, every per-sample product/sum rounded to float32) | −33.5 | −44.2 |
| f32table (sinc table taps re-rounded to float32) | −33.5 | — |
| f32both | −33.5 | — |
| nomod + f32lag (see 2.2) | −53.6 | — |
| tgtlag1 (time-lag targets consumed one block late) | −33.5 (max 194,554) | −44.2 |

Emulating float32 lag arithmetic/storage changes nothing at either delay
length (dexie's 153–271 samples AND metallic's send at 24,000 samples, where
the float32 ulp is 2^-9 sample). Lag quantization is not the dominant error;
"float32-lag emulation" should be dropped from the SXT-017 option space.

### 2.2 The dominant mechanism: the LFO term's presence in the delay-time path

| experiment | metallic | dexie |
|---|---|---|
| LFO depth forced to 0 on BOTH sides (engine probe render + model `nomod`) | **−53.3 dBFS**, max 12,655, corr 0.9998 | **−109.6 dBFS**, max 41, corr 1.0000 (quantization floor) |
| LFO slowed 24× (rate param −6) on BOTH sides | — | **−43.7 dBFS** (unchanged) |
| LFO contribution scaled ×0.9 / ×0.95 / ×1.05 (model side) | — | −44.2 / −44.2 / −44.2 (unchanged) |
| LFO same-direction on L and R (model probe) | −31.9 (worse) | −42.5 (worse) |
| width stage bypassed (model probe) | −33.5 (unchanged) | −44.2 (unchanged) |

Findings:

* **dexie: the entire miss is the LFO term.** With depth 0 on both sides the
  frozen model vs engine residual is max 41 LSB / −109.6 dBFS / corr 1.0000
  — at the fixed-vs-float quantization floor (fm_bass_1 EQ class). The
  static delay path — taps, sinc table, lag pipeline, filters, mix, width,
  pan, master — is exact for this preset.
* **metallic: the LFO term is the bulk.** −33.5 → −53.3 dBFS with the LFO
  off on both sides. The remaining −53.3 static residual (max 12,655, corr
  0.9998) is bounded and NOT budget-blocking (−53.3 meets the proposed
  −46), but its mechanism is not isolated (candidates: send/return chain,
  softclip class, 24,000-sample-delay specifics). Declared open.
* **The LFO-path error is presence-class, not trajectory-class.** It is
  invariant to the LFO rate (24× slower: −44.2 → −43.7) and to the
  contribution scale (κ ∈ {0.9, 0.95, 1.05}: −44.2), yet vanishes at depth
  0. Reversing the LFO direction (same-sign on L/R) makes it worse, so the
  model's opposite-sign ±LFOval application is confirmed.
* Scale of the effect: with the LFO on, the model's own mod-on vs mod-off
  output difference is −37.2 dBFS (dexie) / −25.2 dBFS (metallic); the miss
  is ≈ 7–8 dB below the full LFO effect.
* Direct trajectory estimation (windowed cross-correlation of the isolated
  wet-tap signal, engine vs model) gave an apparent L/R anti-phased read
  difference wandering ±2–4 samples, but the estimator is confounded by
  filter group delay and mix leakage; given the rate/scale invariance above
  it should not be read as a literal delay-time trajectory error.

### 2.3 Structure re-read against the pinned header (READ, cited; no code copied)

`sst-effects/.../Delay.h` @ the pinned commit: `SurgeLag<float,true>
timeL{0.0001}` with `process(){ v = v*lpinv + target_v*lp; }` called
per-sample inside the block loop; `setvars(false)` once per block;
`lfophase += lforate` (double phase, float32 rate), direction flip at ±0.5;
`LFOval = 0.99f*LFOval ± lfo_increment` (float32, per block);
`timeL.newValue(sampleRate()*temposyncRatioInv()*noteToPitchIgnoringTuning(12*t)
+ LFOval - FIRoffset)`, `timeR... - LFOval - FIRoffset`;
`i_dtime = clamp((int)timeX.v, blockSize, max-FIRipol_N-1)`;
`rpX = (wpos - i_dtimeX + k) - FIRipol_N (masked)`;
`sincX = FIRipol_N * clamp((int)(FIRipol_M * (float(i_dtimeX+1) - timeX.v)),
0, FIRipol_M-1)` — every element matches the frozen model's implementation,
as do `SurgeSSTFXAdapter.h` (`envelopeRateLinear` → `SurgeStorage::
envelope_rate_linear`, `temposyncRatio` → `time_data.tempo/120`) and the
`table_envrate_linear` build (`dsamplerate_os * 2^((i-256)/16) /
BLOCK_SIZE_OS`, double-then-float). The divergence is therefore NOT in any
of these structural elements; it is something about how the nonzero,
time-varying LFO term flows through the target→lag→read pipeline that the
block-granular structure read does not expose (sub-sample trajectory class,
bounded by the invariances above). Pinning it needs a direct engine-side
d(t) measurement — an impulse-train probe through the modulated delay.

## 3. Options for SXT-017 (#12)

1. **Scope exclusion (recommended interim): declare LFO→delay-time
   modulation outside the frozen delay-slice scope** (visible contract
   revision, same fail-closed class as the Chime Bell LFO-to-FX-param
   rejection). Predicted effect, measured here: the un-modulated delay slice
   meets the proposed budgets today — dexie −109.6 dBFS (floor), metallic
   −53.3 dBFS — both ≤ −46. Presets whose delay time is LFO-modulated count
   as excluded/adapted until the mechanism is fixed. Zero model rework now.
2. **Impulse-probe micro-leaf (recommended before any budget freeze):**
   render the pinned engine with an impulse-train sequence through the
   modulated delay, measure d(t) per block on both channels, diff against
   the model trajectory, and pin the sub-mechanism (the invariances above
   bound it to the presence/sweep class). Predicted effect: either a small
   model revision that collapses dexie/metallic to the floor, or a precise
   engine-semantics citation for a frozen-model addendum. Tooling committed
   (`tools/diagnose_delay_engine_probe.py` pattern extends to the impulse
   sequence). Cost ≈ one leaf.
3. **Delay-specific budget freeze at achieved numbers (fallback):** freeze
   the delay budgets at the honest achieved values — e.g. two tiers:
   modulated (−33/−44 dBFS class) and un-modulated (−53/−110 dBFS class).
   Predicted effect: PASS by declaration, but it bakes in an unexplained
   mechanism and weakens the fidelity contract for every modulated delay
   preset; not recommended while option 2 is cheap.

## 4. Artifacts and reproduction

* Variant metrics: `artifacts-followup/budget-diagnosis/diag-*.json`
  (model-side renders are regenerable via the documented command; not
  committed).
* Engine probe renders retained: `engmod0__{dexie,metallic}__*.f32.wav`
  (+ meta sidecars, render sha256, 3× determinism gate) and the slowrate
  probe `engprobe_d0.46500036120414734_r-6.0__dexie__*.f32.wav`.
* Tools: `tools/diagnose_delay_budget.py` (model variants),
  `tools/diagnose_delay_engine_probe.py` (engine probes; imports the GPL
  engine at runtime only, copies nothing; Apache-2.0).
* No frozen model file, no budget constant, and no committed fixture was
  modified by this diagnosis.
