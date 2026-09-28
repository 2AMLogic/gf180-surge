# SXT-026 — frozen fixed-point wavetable oscillator model

Issue: #19 (SXT-026) · Model: `wt_model.py` · Runner: `run_model.py` ·
Inputs: `inputs/*.json` (`extract_inputs.py`, requires the external pinned
oracle) · RTL: `rtl/oscillators/wavetable/`

**Status: FROZEN for the SXT-026 RTL.** RTL-vs-model agreement must be EXACT
(integer equality at every declared checkpoint;
`tools/compare_wt_rtl_model.py`). Model-vs-pinned-engine agreement is
governed by [PROPOSED] budgets (see `reports/sxt-026/EVIDENCE.md`); nothing
here is a fidelity, support, or preset-quality claim.

Pinned structure (read and cited, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 —
`WavetableOscillator.cpp` (process_block / convolute / deformContinuous /
deformLegacy / distort_level / update_lagvals), `OscillatorBase.h`
(prepare_unison), `sst-basic-blocks OscillatorDriftUnisonCharacter.h`
(UnisonSetup), `Wavetable.cpp` (BuildWT / MipMapWT), `SurgeStorage.h`
(FIRipol_M=256, FIRipol_N=12, MAX_UNISON=16).

## Word lengths (normative)

| Quantity | Format | Notes |
|---|---|---|
| samples / coefficients / table words | Q10.21, signed 32-bit | shared with SXT-022 |
| envelope phase | Q2.29, 32-bit | ADSR state |
| pitchmult_inv (`pmi`) | Q13.18, 32-bit | declared osc pitch range [24, 148] |
| pitchmult | Q10.21 | `qdiv(1<<18, pmi)` |
| oscstate, rate | Q10.21, **64-bit** | no overflow over any fixture; the engine's float32 accumulates rounding — declared deviation |
| `ipos` | `(oscstate*pmi) >> 15`, low 32 bits | engine: `(unsigned)(2^24·oscstate·pmi)` in float32 — model truncates the exact product (finer) |
| sinc lipol fraction | 16-bit unsigned | `ipos & 0xFFFF` |
| mip table words | Q10.21 | level 0 from int15 payload: `s << 7` (EXACT); int16-full: `s << 6` (EXACT); float32 payload: quantized once |
| a_sel (`dt·pitchmult_inv`) | Q10.21 | `qmul(dt, pmi, fb=18)` |

## Operation order (normative, per convolute call)

1. `block_pos = qmul(oscstate >> 6, pmi, fb=18)`
2. `detune = qmul(udet_ext, qmul(detune_bias, v) + detune_offset)` (drift = 0
   asserted in this slice)
3. `ipos`, `delay = (ipos>>24)&0x3F`, `m = ((ipos>>16)&0xFF)*24`,
   `lipol = ipos&0xFFFF`
4. `state == 0`: mip selection — `a_sel = qmul(dt, pmi, fb=18)`; highest
   k in 6..1 with `a_sel < qint(thr_k)` (float32 thresholds,
   `0.015625·1.8·2^-k`) and `wave_size >= 2^(k+1)`; else 0
5. `tempt = ntpi_tuningctr(detune)`
6. `dt2 = qmul(dt, wt_inc)`; hskew Taylor warp (`xt`); formant
   (`ft = lerp(formant_last, formant_t, block_pos)`,
   `formant = ntp_tuningctr(-ft)`, `dt2 = qmul(dt2, qmul(formant, xt))`);
   `if state >= wtsize-1: dt2 += 1 - formant`; `t = qmul(dt2, tempt)`;
   `state &= wtsize-1`
7. morph frame interpolation — `xt14_continuous` (default):
   `tblip = lerp(last_tableipol, tableipol, block_pos)`,
   `tid = tblip >> 21`, `target = min(tid+1, n_tables-1)`,
   `proc = tblip - (tid<<21)`; `xt134_legacy`: fraction/integer split plus
   the monotonic tableid clamp
8. `level = qmul(T[mip][tid][state], 1-proc) + qmul(T[mip][target][state], proc)`
9. `distort_level`: `x1 = level - qmul(qmul(a, level), level) + a` with
   `a = l_vskew >> 1`; `x = qmul(x1, 1-clip) + qmul(qmul(qmul(clip, x1), x1), x1)`;
   clamp ±1
10. `g = qmul(newlevel - last_level, out_attenuation)`; sinc accumulation of
    FIRIPOL_N=12 taps (`SINC_MAIN[m/2+k] + qmul(lipol, SINC_DERIV[m/2+k], fb=16)`)
    into `osc[bufpos+delay+k]`
11. `oscstate += t`; `state = (state+1) & (wtsize-1)`

Per block (process_block): lag steps (`l += qmul(0.05, t-l)` for
shape/vskew/hskew/clip), morph tableid/tableipol update, then
`while oscstate < a_cov: convolute()` per unison voice (`a_cov = 64·pitchmult`),
`oscstate -= a_cov`; output stage
`osc_out = qmul(osc_out, hpf(k)) + osc[bufpos+k]` with the lipol ramp
`hpf(k) = hpf_start + qround(hpf_d·(k+1), 6)`, buffer clear, bufpos advance,
FIRIPOL_N overlap copy at wrap.

## Declared deviations (model vs pinned engine, budget-absorbed)

1. Fixed Q10.21 words vs engine float32 (round-half-up vs float rounding).
2. Mip levels ≥ 1 built in double from the quoted `hrfilter[63]`
   (decision-records/0004); the engine accumulates float32. Level 0 is EXACT
   for int-format payloads.
3. `ipos`/`block_pos` from exact integer products (engine: float32 mantissa
   truncation; diverges at large oscstate — long/high notes).
4. Unison pan law cancels in the declared mono `(L+R)/2` bus;
   `(panL+panR)/2 == 1` per voice (UnisonSetup).
5. `envelope_rate` / `note_to_pitch` tables evaluated from pinned
   construction formulas in double, quantized once (SXT-022 rule).
6. ADSR sqrt (d_s = 1) evaluated in double at the pinned formula.
7. **RETIRED as a deviation by the #180 contract revision — the decimator and
   the master stage are now PER SCENE, the pinned engine's placement.**
   `SceneDecimator` holds ONE `voice_model.HalfbandD2` and the master stage
   for the whole scene and persists across voice death; `Slice` ends at its
   unclipped 96 kHz `sceneout` contribution and `run_model.py` sums those,
   clips once, and drives the one scene stage — the same statement order
   `model/voice/run_model.py` uses for the SXT-022 voice leaf and
   `rtl/voice/tb_voice.sv` implements
   (`SurgeSynthesizer::halfbandA/B` -> `HalfRateFilter::process_block_D2`).
   **This is a change of placement only; no word length, Q format, rounding
   rule or coefficient moved** — see
   `decision-records/0018-wavetable-scene-decimation-placement.md`
   (issue #180, SXT-017 / #12).

   What the retired per-slice placement was worth, measured on all nine
   committed fixtures before the move (`tools/measure_wt_decimation_stage.py`,
   `reports/sxt-026/artifacts/decimation-stage-per-slice-vs-per-scene.json`,
   EVIDENCE section 2a): worst case 1 int16 LSB / −112.1 dBFS residual RMS,
   worst pre-int16 residual 38 Q10.21 LSB (one int16 LSB = 64 Q10.21 LSB).
   The actual re-freeze moved three of the nine committed renders by ≤ 1
   int16 LSB and **no** budget verdict (EVIDENCE section 3 change note).
   **Nothing here is a fidelity claim**: the case for the move was RTL
   coverage of the 48 kHz output and topological agreement with the engine,
   never a measurable fidelity improvement.

   What remains a deviation in this area is item 1 (fixed Q10.21 vs the
   engine's float32 scene arithmetic), which is unchanged by the move and is
   the EVIDENCE section 4 finding's territory, not this item's.

Structural note for deviation 7: `Slice.scene_block()` is the slice's block
entry and returns the unclipped 96 kHz scene contribution;
`SceneDecimator.process_block()` is the scene tail. `Slice.process_block()`
and `Slice.decimate_scene()` no longer exist — the retired per-slice topology
is kept only as `measure_wt_decimation_stage.LegacyPerSliceStage`, so the
measured delta above stays re-derivable, and the tool's fail-closed
byte-identity gate now guards the per-scene leg against `run_model.py`.

**Zero-input limit cycle of the shared decimator (F-176-2, issue #181,
DECLARED — SXT-017 option (a)).** The `voice_model.HalfbandD2` that
`SceneDecimator` now holds does not settle to zero on zero input: it holds a
permanent output-Nyquist (period-2) cycle bounded by **36 Q10.21 LSB = 0.5625
int16 LSB ≈ −95.3 dBFS** over a declared 315-case input sweep
(`reports/halfband-limit-cycle/`, `model/voice/README.md` §"DECLARED
word-length consequence"). That bound is below one int16 LSB, so the placement
deltas recorded above are unaffected by it. **The #180 move makes this leaf
subject to the property where the retired per-slice topology largely was not**:
per-slice state died with each voice, so that leg reached exactly 0 after voice
death, while the per-scene stage keeps ringing — which is precisely the
state-lifetime difference #176 named and #180 adopted on purpose, because it is
what the pinned engine does. The ring-out is now inside this leaf's own
RTL-vs-model compared window (item 8 below), so the cycle is *checked* here
rather than merely declared. Changing the decimator's arithmetic so zero input
decays to zero would be a further SXT-017 / #12 contract revision and is **not**
done in #181.

## RTL coverage (issue #180; the issue-#176 boundary is retired)

8. **`rtl/oscillators/wavetable/` covers the oscillator AND the 48 kHz
   output.** The per-scene stage (per-slot o2 level and VCA × AEG gain ramp,
   scene out, one ±8 clip, one `HalfbandD2` persisting across voice death,
   master, ±8 and ±1 clips) lives in `tb_wavetable.sv` — a scene is a shared
   resource, so it sits one level above the per-slot `wavetable_core.sv`,
   exactly as in `rtl/voice/tb_voice.sv` — and emits an `M` trace line per
   48 kHz sample. `tools/compare_wt_rtl_model.py` reads the model trace's
   `mono_block` and compares every one of those samples at integer equality,
   on every block including blocks with no live voice (the scene filter's
   post-voice-death ring-out is compared too). The leaf's `rtl_vs_model: PASS`
   therefore covers the 48 kHz output; the comparator emits the landed scope
   in its `scope` field on every run, and the ledger note for `osc:Wavetable`
   states it.

   **The coverage claim is only as good as its control**, so it carries one:
   `-DWT_SCENE_MUTANT_HB_ORDER` mutates a single line of the scene decimator's
   reconstruction (the pre-#123 A-even/B-odd branch order that
   `rtl/voice/voice_halfband_order_mutant.sv` isolates on the voice leaf) and
   MUST FAIL the comparison **on the 48 kHz leg specifically** — a run whose
   only failures were elsewhere is refused by the harness.
   `tools/run_sxt026_checks.py` step 6 runs the clean build and both mutants
   every time and records the transcript in
   `reports/sxt-026/artifacts/rtl-exactness.txt`.

   Before #180 this leaf's RTL had no 48 kHz stage at all and the comparator
   did not read `mono_block`, so the PASS was oscillator-scoped (the original
   wording of this deviation, issue #176). What the PASS still does **not**
   establish is unchanged: it is claim (1) only — the RTL matches the frozen
   fixed-point model exactly — and says nothing about model-vs-pinned-engine
   fidelity (claim 2, [PROPOSED]/PARTIAL) or how it sounds (claim 3).

## Unison cap — explicit rejection

`unison` outside 1..MAX_UNISON(16) raises immediately (never clamped). The
engine itself silently clamps (SXT-015 flagged 58 corpus presets); this
product contract rejects beyond-cap unison at load (issue #19 acceptance,
negative control NC-C).

## Residency

Mip table payloads are derived at run time from the external pinned tree
(hash-verified against the image manifest first) and streamed to the RTL as
`rtl/wt_table.hex`; no table bytes are committed to this repository
(decision-records/0004). The on-chip working set is the active mip level
(`model/resources` policy; SXT-016 probe_osc reconciliation in
`reports/sxt-026/EVIDENCE.md`).
