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
