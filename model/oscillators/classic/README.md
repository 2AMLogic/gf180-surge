# SXT-033 — frozen fixed-point Classic oscillator family model

Issue: #67 (SXT-033) · Model: `classic_model.py` · Runner: `run_model.py` ·
Inputs: `inputs/*.json` (`extract_inputs.py`, requires the external pinned
oracle) · Fixture overrides: `fixture_config.py` ·
RTL: `rtl/oscillators/classic/`

**Status: FROZEN for the SXT-033 RTL.** RTL-vs-model agreement must be EXACT
(integer equality at every declared checkpoint;
`tools/compare_classic_rtl_model.py`). Model-vs-pinned-engine agreement is
governed by [PROPOSED] budgets (see `reports/SXT-033/EVIDENCE.md`); nothing
here is a fidelity, support, or preset-quality claim.

Scope: the Classic oscillator family **beyond** the landed SXT-022 Attacky
configuration (shape 0, sub mix 1, sync 0, unison 1). This leaf extends
PARAMETER coverage only — no new algorithm: the impulse engine is the same
4-state machine frozen in SXT-022 (`model/voice/voice_model.py`, imported for
tables and Q helpers), now driven over the declared parameter classes
observed in the 94 recovery-basis presets' normalized graphs
(`corpus/normalized/graphs.jsonl`, sha256
`c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715`):

| Class | Param | Engine type / range at the pin | Observed (94-preset scan) |
|---|---|---|---|
| shape | p[0] | `ct_percent_bipolar` [-1, 1] | -1.0 .. -0.16, 0 |
| width | p[1]/p[2] | `ct_percent` [0, 1], lag-limited [0.001, 0.999] | 0.019 .. 0.910 |
| sub mix | p[3] | `ct_percent` [0, 1] | 0, 0.023 .. 0.81, 1.0 |
| sync | p[4] | `ct_syncpitch` [0, 60] | 0.568 .. 28.607 (21 slots > 0) |
| unison | p[6] | `ct_osccount` [1, 16] | 1 .. 16 (64 slots > 1) |
| spread | p[5] | `ct_oscspread` [0, 1], `get_extended` = 12·f | 0 .. 0.2 |

Pinned structure (read and cited, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 —
`ClassicOscillator.cpp` (init / process_block / convolute incl. the
hard-sync restart branch / update_lagvals), `OscillatorBase.h`
(prepare_unison), sst-basic-blocks `OscillatorDriftUnisonCharacter.h`
(UnisonSetup attenuation/detune/pan; CharacterFilter Warm/Neutral),
`SurgeStorage.cpp` init_tables (pitch tables incl. `table_two_to_the_minus`),
SurgeVoice.cpp (osc process_block is mono unless fbc == fc_wide; pfg applied
post-mixer-sum; `megapanL/R`), sst-filters HalfRateFilter.h.

## Declared parameter-class boundaries (fail-closed refusals)

The model raises (and the extractor refuses, exit 2) outside:

* unison outside 1..16 (engine clamps; this contract rejects, SXT-026 rule);
* absolute detune mode (`p[5].absolute`, engine-read — separate machine);
* scene drift ≠ 0 (determinism gate);
* retrigger off in fixture configurations (deterministic starts);
* FM routing into the modeled slot (fixture override pins `fm_switch` off);
* analog envelope mode, decay shapes outside d_s ∈ {0, 1};
* character Bright (Warm/Neutral declared);
* pitch outside [24, 148].

Applicability boundary: presets whose Classic content sits outside the
declared single-scene mono voice slice (scene-B Classic, FM targets, active
FX/waveshaper/lowcut in the reference path, non-LP12 filter graphs) are NOT
renderable by this leaf; the fixture configuration isolates one slot and the
extractor refuses presets with no scene-A Classic slot (e.g. House Of
Chords — its Classic slots are scene-B; scene-B/voice-graph integration is
#48). Isolation overrides are test configurations, never adapted presets,
never coverage.

## Word lengths (normative; shared with SXT-022/SXT-026)

| Quantity | Format | Notes |
|---|---|---|
| samples / coefficients / rate words | Q10.21, signed 32-bit | round-half-up products |
| envelope phase | Q2.29, 32-bit | ADSR state |
| pitchmult_inv (`pmi`) | Q13.18 | declared osc pitch range [24, 148] |
| oscstate / syncstate | Q10.21, **64-bit**, per unison voice | engine float32 — declared deviation |
| sinc lipol fraction | 16-bit unsigned | `ipos & 0xFFFF` |
| unison constants | float32 emulation at quantization time, then Q10.21 | attenuation 1/√n (`_f32(1.0/_f32(√n))`), detune bias 2/(n−1), offset −1, per-voice detune `udet_f·(bias·v+offset)` in float32 op order |

## Operation order (normative, per convolute call, per unison voice u)

1. sync branch: if `l_sync > 0 and syncstate[u] < oscstate[u]`:
   `ipos = trunc(syncstate[u]·pmi << 24-scale)`; `state[u] = 0`;
   `last_level[u] += dc_uni[u]·(oscstate[u] − syncstate[u])`;
   `oscstate[u] = syncstate[u]`;
   `syncstate[u] = max(0, syncstate[u] + t_sync_u[u])`
   (`t_sync_u[u] = 2·ntpi_tuningctr(detune_u)`);
   else `ipos = trunc(oscstate[u]·pmi << 24-scale)`.
2. Impulse RATE `t = t_u[u]` in BOTH branches:
   `t_u[u] = ntpi_tuningctr(detune_u + min(l_sync, 156 − pitch))`
   (quantization-time constants per voice instance).
3. `delay = (ipos>>24)&0x3F`, `m = ((ipos>>16)&0xFF)·24`, `lipol = ipos&0xFFFF`.
4. `state[u]==0`: `pwidth[u] = limit(l_pw, 0.001, 0.999)`,
   `pwidth2[u] = 2·l_pw2`.
5. 4-state impulse machine (frozen SXT-022 form; `om1 = 1 − sub`):
   case 0 `tg = ((1+wf)/2 + (1−pw)·(−wf))·om1 + (sub/2)·(2−pw2)`, …;
   then `g *= out_attenuation` (unison attenuation; engine op order).
6. 12-tap windowed-sinc accumulation
   `ob[base+k] += (SINC_MAIN[m/2+k] + lipol·SINC_DERIV[m/2+k])·g`.
7. `dc_uni[u] = (t_inv_u[u]·(1+wf))·om1`;
   `dcb[base+6] += dc_uni[u] − olddc`
   (`t_inv_u[u] = exact Q10.21 division 1/t_u[u]` — see deviations).
8. `rate = (state&1 ? t·(1−pw) : t·pw) · (state+1)&2 ? (2−pw2) : pw2`;
   `oscstate[u] = max(0, oscstate[u] + rate)`; `state[u] = (state+1)&3`.

Per block: one lag step per parameter
(`l += 0.05·(target − l)`), hpf target
`min((1−40/48000)², 0.995^(4·min(1, 8.1758·ntp_tuningctr(pitch+l_sync)/96000)))`
with per-sample linear ramp `prev + round(d·(k+1)/64)`;
per voice u `while ((l_sync>0 and syncstate[u] < a_cov) or oscstate[u] < a_cov):
convolute(u)`, then `oscstate[u] −= a_cov` (and `syncstate[u] −= a_cov` when
sync on); shared extraction stage
`osc_out = osc_out·hpf + ob − mdc·(out_attenuation·pitchmult)`,
`mdc += dcb`, character biquad, buffer clear, bufpos advance, 12-word
overlap copy at wrap.

## Declared deviations (model vs pinned engine, budget-absorbed)

1. Fixed Q10.21 words vs engine float32 (round-half-up vs float rounding).
2. `ipos` from the exact integer product (engine: float32 mantissa
   truncation of `2^24·oscstate·pitchmult_inv` — per-impulse sub-sample
   jitter; across a detuned unison stack the jitters differ per voice, which
   shifts the inter-voice beat pattern — the dominant term in the measured
   uni>1 agreement numbers).
3. `oscstate`/`syncstate` accumulate exactly (engine float32 adds).
4. `t_inv = 1/t` as an exact Q10.21 division: the engine uses
   `mech::rcp` = raw `_mm_rcp_ss` (~12-bit correct, microarchitecture-
   specific, not reproducible bit-exactly). The error enters through the
   DC-removal path `mdc·(att·pitchmult)` and is pitch-attenuated.
5. Frequency-domain tables evaluated from the pinned construction formulas
   in double, quantized once (incl. `table_two_to_the_minus`, see finding
   below). The engine lerps float32 tables.
6. Unison pan law: the modeled voice runs mono (`stereo = (fbc == fc_wide)`,
   fixture configs pin fbc to fc_serial1); pan enters only through the mono
   sum law `(megapanL(p)+megapanR(p))/2 = 1 − 0.25·p²`, folded into the outl
   gain word (≤1-LSB rounding deviation vs the engine's split L/R path).
7. ADSR sqrt decay (d_s = 1) evaluated in double at the pinned formula
   (SXT-026 rule).

## Finding: landed SXT-022 pitch-helper fractional term (routed, not absorbed)

The landed SXT-022 helpers `voice_model.ntpi_tuningctr` /
`ntpi_ignoring_tuning` interpolate the fractional semitone with
`2^(idx/1000)`; the pinned construction is
`table_two_to_the_minus[i] = 2^(−i/12/1000)`
(`SurgeStorage.cpp` init_tables, cited). The landed term is 12000× steeper
and sign-flipped. The error is INERT in the SXT-022 Attacky slice (the
helper's argument is identically 0 there, so the fractional term is 1) but
is LIVE in any detune or sync class. This model uses the corrected pinned
construction (`classic_model.ntpi_tuningctr` / `ntp_tuningctr`); the frozen
SXT-022 files are left untouched. Resolution of the SXT-022 artifact
belongs to the freeze owner (#12) / voice-slice generalization (#48).

## Files

* `classic_model.py` — the frozen model (importable)
* `run_model.py` — renders a fixture sequence, writes `model.wav`,
  `model_trace.json`, and the RTL stimulus (`rtl/*.hex`)
* `fixture_config.py` — declared fixture overrides (extractor + renderer)
* `extract_inputs.py` — fail-closed extraction from the pinned engine
* `inputs/*.json` — committed carrier extractions (census-blob verified)

## Reproduce

```sh
python3 model/oscillators/classic/run_model.py --inputs \
    model/oscillators/classic/inputs/horn.json \
    --sequence seq-notes-repeated-v1 --out-dir /tmp/run --rtl
python3 tools/compare_classic_rtl_model.py --run-dir /tmp/run
python3 tools/compare_audio_reference.py \
    --ref reports/SXT-033/artifacts/horn__seq-notes-repeated-v1-ref.wav \
    --model /tmp/run/model.wav
```
