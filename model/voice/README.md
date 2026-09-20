# SXT-022 frozen fixed-point voice model (`model/voice/`)

Frozen reference for the SXT-022 RTL (`rtl/voice/tb_voice.sv`). The RTL must
match this model **exactly** (integer equality at every declared checkpoint;
`tools/compare_rtl_model.py`). Model-vs-pinned-engine agreement is a separate
claim governed by error budgets, which are **not frozen** — SXT-022 reports
achieved numbers only.

- Preset: `resources/data/patches_factory/Basses/Attacky.fxp`
  (census blob `4675e423a7489b02f501f7763b4760f64ab035f9`)
- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`)
- Inputs: `attacky_inputs.json` (engine-read state missing from
  `graphs.jsonl` schema rev 1.0.0) + modulation routings from
  `corpus/normalized/graphs.jsonl`

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| samples, filter state, coefficients, gains, sinc table | **Q10.21** (signed 32-bit) | range ±1024; headroom for the filter's clipgain path |
| envelope phase / sustain / rates | **Q2.29** (signed 32-bit) | rates are control-plane words computed from the pinned rate table |
| `pitchmult_inv` | **Q13.18** | declared pitch range [24, 148] (asserted) |
| sinc sub-sample fraction (`lipol`) | 16-bit integer | derivative table pre-scaled by 1/65536 |

Arithmetic rules (FROZEN):

1. Every value is a Python `int` in two's-complement Q-format. No floating
   point at run time.
2. Products are exact 64-bit, then rounded **round-half-up** back to the
   target format: `r = (a*b + (1 << (s-1))) >> s`, `s = fa+fb-fq`, and
   saturated to the signed 32-bit range.
3. Divisions exist only at coefficient (block) rate (`qdiv`, round-half-up)
   — consistent with cost assumption A-ALU-2 (no audio-rate division).
4. The sinc sub-sample position truncates toward zero, matching the engine's
   `(unsigned int)` cast.
5. Frequency-domain conversions (note_to_pitch family, envelope-rate and dB
   tables) are evaluated in double precision against the pinned table
   *formulas* and quantized once (declared deviation: the engine lerps
   float32 tables; agreement is within one float32 ulp and is part of the
   model-vs-reference budget).

## Frozen block schedule (one 32-sample engine block)

1. **Dispatch**: events with `ceil(t/32) <= b` fire now. `note_on` creates a
   voice (constructor: envelopes `attack_from(0)`, one envelope step, ramp
   anchors, oscillator init with `oscstate = 0`, lags instantized).
   `note_off` releases the matching gated voice (envelope `release()`).
   `cc1` sets the modwheel FAST_LINE target.
2. **Voice control pass** (per voice, creation order): envelope step (amp
   then filter), modulated `cutoff_a = cut + depth*mw + envmod*feg_out`,
   `reso_a`, ramp targets `fbp_gain = db_to_linear(vca)*aeg_out`,
   `fbp_outl = 0.5*volume^3` (megapan(0) = 1, vs = 0).
3. **Oscillator block** (64 OS samples): `pitchmult_inv`, lag steps
   (`v += 0.05*(target - v)`), hpf target `min(integrator_hpf, 0.995^invt)`
   with a per-sample linear ramp `prev + round(d*(k+1)/64)`,
   `while oscstate < a_cov: convolute()`, `oscstate -= a_cov`, then the
   extraction loop (leaky integrator `osc_out = osc_out*hpf + ob - mdc*oa`,
   DC accumulator `mdc += dcbuffer`, character biquad), buffer clear,
   `bufpos` advance, wrap copy.
4. **Convolute** (per impulse): `ipos = trunc(oscstate*pitchmult_inv << 24)`,
   `delay = (ipos>>24) & 0x3f`, phase `m = (ipos>>16) & 0xff`,
   `lipol = ipos & 0xffff`; 4-impulse state machine (general sub/shape
   case); 12-tap windowed-sinc accumulation
   `ob += (sinc[m+k] + lipol*sincD[m+k]) * g`; DC-buffer impulse at
   `base + FIRoffset`; per-state rate update; `oscstate += rate` (max 0).
5. **Coefficient plane**: `MakeCoeffs(cutoff_a, reso_a)` for
   `fut_lp12/st_Driven` (boundFreq, Map2PoleResonance, ToCoupledForm with the
   `ai >= 8*1.19e-7` floor, `clipscale`), then `FromDirect` smoothing
   (`tC += 0.2*(N - tC)`, `dC = (tC - C)/64`; first run: `C = N`, `dC = 0`).
6. **Filter chain per OS sample** (fc_serial1, mixer level constant):
   `C[i] += dC[i]` (saturating), `IIR12CFC` coupled-form step with per-sample
   clipgain state `f_clip = max(0.1, 1 - C7*y^2)`, serial-1 routing (mix1 =
   mix2 = 1), per-sample gain/output ramps `start + round(d*(k+1)/64)`,
   scene accumulate (L and R identically — mono bus, pan = 0).
7. **Scene/output**: hard clip ±8 (declared engine default), halfband D2
   (M=6 steep; single pass — the R lane is identical on the mono bus),
   master amplitude (converged after settle), hard clip ±8, mono
   `(L+R)/2` with L == R, int16 conversion
   `int(clip(x, -1, 1) * 32767)` (truncation toward zero).

## Declared control-plane boundary (model → RTL)

Block-rate coefficient generation stays in the model and is streamed to the
RTL: envelope RATES (rate-table outputs), `pmi`, `pitchmult`, `a_cov`, hpf
target, filter `C[8]`/`dC[8]`, gain/output ramp targets, modwheel value,
master amplitude. The RTL reproduces the envelope state machines and the
complete audio-rate datapath, and must equal the model at every declared
checkpoint (state after blocks 0, 1, every 64th block, and every block of a
released voice) plus every output sample.

## Declared scope omissions (fail-closed in code where feasible)

* Scene drift: extracted and asserted **0** (determinism gate) — drift LFO
  noise cannot enter the slice; the RTL implements no RNG.
* Oscillators 2/3 are muted and retrigger-flagged; their free-running init
  consumes engine RNG but cannot affect audio (no noise/FM paths active).
* LFO1 processes in the engine but has no modulation destinations — omitted.
* Velocity → VCA gain is 0 (`vs = 0`) — velocity path omitted.
* Voice polyphony limited to 8 slots; portamento inactive (`porta` at min).
* Character filter supports Warm/Neutral only (preset is Warm).
* Envelope digital mode only, `a_s = 1`, `d_s = 0` (preset values).

## Files

* `voice_model.py` — the frozen model (importable; see module docstring)
* `run_model.py` — renders a fixture sequence, writes `model.wav`,
  `model_trace.json`, and the RTL stimulus (`rtl/*.hex`)
* `extract_inputs.py` — fail-closed extraction of the normalized voice
  inputs from the pinned engine (`attacky_inputs.json`)
* `attacky_inputs.json` — committed extraction (census-blob verified)

## Reproduce

```sh
python3 model/voice/run_model.py --sequence seq-notes-repeated-v1 \
    --out-dir /tmp/run
python3 tools/compare_rtl_model.py --run-dir /tmp/run
python3 tools/compare_audio_reference.py \
    --ref fixtures/render-out/reference-dry.wav --model /tmp/run/model.wav
```
