# SXT-023 frozen fixed-point models — Delay + EQ (`model/effects/`)

Frozen reference for the SXT-023 RTL (`rtl/effects/`). The RTL must match
these models **exactly** (integer equality at declared checkpoints;
`tools/compare_rtl_model_fx.py`). Model-vs-pinned-engine agreement is a
SEPARATE claim governed by [PROPOSED] error budgets that are **not frozen** —
achieved numbers are reported in `reports/sxt-023/EVIDENCE.md`.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, compiled block size 32 (`oracle/manifest.json`)
- Structure authority (READ + cited; nothing copied):
  - Delay: `libs/sst/sst-effects/include/sst/effects/Delay.h`
    (`initialize`/`setvars`/`processBlock`, `max_delay_length = 1<<18`),
    `SurgeSincTableProvider.h` (table construction formula),
    `Lag.h` (OnePoleLag), `BlockInterpolators.h` (lipol_sse),
    `BiquadFilter.h` (TDF2 + per-sample coefficient lag),
    `Clippers.h` (softclip), `WidthProvider.h` + `MidSide.h`,
    `src/common/dsp/effects/DelayEffect.cpp` (ctrl types, streaming fixes)
  - EQ: `src/common/dsp/effects/ParametricEQ3BandEffect.{h,cpp}`
    (slowrate = 8 refresh, band deactivation, gain/mix lipol),
    `BiquadFilter.h` (`calc_omega`, `coeff_peakEQ` → `coeff_orfanidisEQ`)
- Chosen presets (real normalized corpus entries, census-blob verified at
  extraction and at every render):
  - `patches_factory/Plucks/Metallic.fxp` — TWO Delay instances
    (ains1 insert + send1), per-instance state exercised in one patch;
    drift 0, retrigger-clean (bit-identical determinism class)
  - `patches_factory/Basses/FM Bass 1.fxp` — EQ only (3 bands all active)
  - `patches_3rdparty/John Valentine/Keys/Dexie Swirly E-Piano.fxp` —
    Delay with **tempo-synced LFO rate** (patch `tempoOnSave` = 169.5 BPM
    applied by `loadPatch` → `temposyncratio` = 1.4125)
- Inputs: `fx_inputs/{metallic,fm_bass_1,dexie}.json` — fail-closed extraction
  (`extract_fx_inputs.py`): census blob re-verified, graphs.jsonl fx
  types cross-checked, temposync/extend/deform read from surgepy getters and
  cross-checked against the raw .fxp attributes, `deactivated` flags from the
  raw XML + documented loader migrations, drift asserted 0, non-muted
  oscillators asserted retrigger-on.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| audio samples, delay-line words | **Q10.21** signed 32-bit | range ±1024 |
| sinc table | **Q2.29** signed 32-bit | recomputed from the cited formula (double), quantized once |
| block-rate gain ramps (lipol) | **Q13.18** signed 32-bit | feedback/crossfeed/mix/pan/width, send/return gains, master amp |
| biquad coefficients + lags + TDF2 state | **Q24.43** signed 64-bit | engine computes this path in double; Q24.43 keeps 1e-13-class agreement |
| delay-time lag state/targets, LFO value/increment/rate | **Q24.43** signed 64-bit | engine: float32 lag, double lfophase — declared deviations |
| x³ gain format (send/return/feedback) | raw f, gain = f³ | `amp_to_linear` |

Arithmetic rules (FROZEN, `qmath.py`): exact products, round-half-up
`(p + 2^(s−1)) >> s`, saturating; no floating point at audio run time;
double precision only at coefficient/control rate, quantized once.

## Frozen block schedule (32 samples)

Delay (`delay/delay_model.py`, mirrors `Delay.h::processBlock`):
1. control pass (`setvars`): feedback/crossfeed lipol targets; lfophase
   advance + wrap (flip direction at 0.5); LFOval one-pole (ca = 0.99f);
   time-lag targets = `48000·tsRatioInv·n2p(12·f) ± LFOval − 6`;
   mix/pan/widthS lipol targets; lp = `coeff_LP2B(ω(highcut/12), 0.707)`,
   hp = `coeff_HP(ω(lowcut/12), 0.707)`; first-block instantize
   (the `inithadtempo` first-pass semantics).
2. per sample k: timeL/timeR lag steps (the engine's float32 pair
   `lp = 0.0001f`, `lpinv = 1 − lp` quantized — their sum ≠ 1, reproducing
   the engine's slow lag drift); `i_dtime = clip((int)v, 32, 2^18−13)`;
   `rp = (wpos − i_dtime + k − 12) & (2^18−1)`; sinc phase
   `clamp((int)(256·(i_dtime+1−v)), 0, 255)`; 12-tap sinc read of the
   stereo lines (24 external reads/frame).
3. negative feedback (fb_sign); feedback-path softclip (deform_type = 1);
   highcut LP2B / lowcut HP (TDF2, per-sample coefficient lag d = 0.004).
4. write buffer: trixpan (input channel); feedback MAC; crossfeed MAC
   (crossed); 32 writes/channel/frame to external memory.
5. width (side scaled by `dbToLinear(width)`, mid intact); mix crossfade
   `dry·(1−t) + wet·t`.

EQ (`eq/eq_model.py`, mirrors `ParametricEQ3BandEffect::process`):
1. `bi == 0` (every 8th block): three `coeff_peakEQ(ω(freq/12), bw, gain)`
   (Orfanidis) → per-sample coefficient-lag targets (startValue on first).
2. bands 1→2→3 in series (TDF2 stereo, per-sample lag steps, shared L/R
   coefficients), each skipped when its gain is deactivated.
3. output gain `db_to_linear(gain)` (lipol ramp); mix crossfade against the
   dry copy.

## Declared control-plane boundary (model → RTL)

Block-rate quantities are computed in the model (double, quantized once) and
streamed one word per line to the RTL (`rtl/<slug>_ctrl.hex`): master
amplitude; per delay instance the 5 lipol raw targets, the two time-lag
targets (already including the LFOval contribution — the lfophase/LFOval
accumulators are control-plane), the 10 biquad coefficient targets and the
flags word; per EQ instance 15 coefficient targets and the gain/mix raw
targets; per send instance the send/return gains. The RTL computes everything
audio-rate: lag recurrences, LFO-free datapath, line reads/writes, TDF2,
softclip, ramps, crossfades.

## Declared scope omissions (fail-closed)

* Parameter modulation INTO the streamed effect parameters (the chosen
  presets have none; the LFO→FX routes present in other presets are out of
  scope, fail-closed).
* Delay clipping modes tanh/hard/hard18 (the chosen presets use soft clip =
  deform_type 1; the tanh mode raises NotImplementedError).
* Graphic EQ / Conditioner / other FX classes (SXT-024+ scope).

## Files

* `qmath.py` — shared fixed-point kernel (round-half-up, saturating)
* `extract_fx_inputs.py`, `fx_inputs/*.json` — fail-closed engine extraction
* `delay/delay_model.py`, `delay/sinc_table.py` — frozen Delay model + sinc
  table derivation; `delay/README.md` — freeze doc
* `eq/eq_model.py`, `eq/README.md` — frozen EQ model + freeze doc
* `run_fx_model.py` — renders a fixture (dry bus in → model wet out), writes
  the model trace + the RTL stimulus hex files

## Reproduce

```sh
python3 model/effects/extract_fx_inputs.py          # refit inputs from the engine
python3 model/effects/run_fx_model.py --slug metallic
python3 tools/compare_fx_reference.py --ref reports/sxt-023/fixtures/... \
    --model reports/sxt-023/artifacts/model__... --json ...
python3 tools/compare_rtl_model_fx.py --slug metallic   # RTL-vs-model exactness
```
