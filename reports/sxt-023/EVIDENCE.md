# SXT-023 evidence record — Delay + EQ: fixed models, RTL, per-instance state

Branch: `loom/sxt-023-delay-eq` · Issue: #16 (SXT-023) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).

**Claim discipline.** This record advances: (1) RTL-vs-frozen-model
exactness — achieved for the EQ slice, NOT achieved for the Delay slice
(honest FAIL, see A1); (2) model-vs-pinned-reference — within the proposed
budgets for the EQ slice, NOT within them for the Delay slice (honest FAIL
against [PROPOSED] numbers, pending-freeze). It establishes **no**
preset-support claim, **no** musical-quality claim, and **no** FPGA/gf180mcu
synthesis, timing, or hardware claim. The RTL is an iverilog-simulated
behavioral schedule.

## Presets (real corpus entries; census-blob verified)

| slug | preset | FX used | determinism class | why chosen |
|---|---|---|---|---|
| metallic | `patches_factory/Plucks/Metallic.fxp` | Delay @ains1 + Delay @send1 | bit-identical (drift 0, retrigger on) | **two Delay instances in one patch** = the per-instance-state acceptance case; SXT-014 ablation carrier |
| fm_bass_1 | `patches_factory/Basses/FM Bass 1.fxp` | EQ @ains1 (3 bands active) | bit-identical | EQ carrier; SXT-014 ablation carrier |
| dexie | `patches_3rdparty/.../Dexie Swirly E-Piano.fxp` | Delay @ains1, **tempo-synced LFO rate** (patch tempoOnSave 169.5 BPM → ratio 1.4125) | bit-identical | **tempo-synced delay case** required by the issue |

The tempo-sync path is exercised through patch-stored `tempoOnSave`, applied
by the engine's own `loadPatch` (surgepy.cpp:862) — engine behavior, not a
harness mutation. A candidate EQ+Delay preset with drift ≠ 0
(`Polysynths/Sine Saw.fxp`) was REJECTED by the determinism gate.

## Acceptance mapping (issue #16)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| A1 | RTL vs model exact at declared checkpoints | **EQ: PASS** — 547,200 output samples + 136 checkpoints / 4,080 state fields, 0 mismatches (`exactness-eq-fm_bass_1.json`). **Delay: FAIL** — the behavioral tb does not yet reproduce the model bit-exactly: metallic/dexie mismatch on ~98–100% of render samples (max \|d\| ≈ 3.5e5–6.1e5 LSB); T-state fields (lags/targets) match at checkpoints in the earlier probes but the full-render audio path does not. Root causes FOUND AND FIXED during this leaf: planar-vs-interleaved input deinterleave, biquad r1' using the R-channel input (`ir` instead of `il`), the biquad output round-half-up bias (2^41 instead of 2^21 — injected a phantom DC), the LFO-rate table using 48 kHz instead of `dsamplerate_os` = 96 kHz (OSC_OVERSAMPLING = 2), `note_to_pitch` fraction table interpolation (semitone-twelfths), the read offset (FIRipol_N = 12, not FIRoffset = 6 — engine-measured 187.5-sample delay confirmed), and the float32 lag-pair drift (LPT/LPIT constants). Remaining delay defect: not isolated; ~0.9 correlation, best gain 0.90 — the tb needs another iteration (**routed: delay-RTL exactness stays OPEN inside this leaf's follow-up; the models are the frozen reference**) | `exactness-eq-fm_bass_1.json` (PASS), `exactness-delay-metallic.json`, `exactness-delay-dexie.json` (FAIL) |
| A2 | Model vs pinned reference within declared budgets, incl. tempo-synced cases | **EQ: PASS** (PENDING-FREEZE) — fm_bass_1: max 7.8 LSB, rms 1.0 LSB (−120.0 dBFS), spectral corr 1.000, best shift 0 — at the quantization floor. **Delay: FAIL against [PROPOSED] budgets** (honestly reported, not tuned): metallic max 195,634 LSB / rms −33.5 dBFS / corr 0.975; dexie max 72,738 / rms −44.2 dBFS / corr 0.995 vs proposed max 8,192 / rms −46 dBFS / corr 0.98. Dominant deviation: the engine's float32 lag-state staircase at long delays (ulp ≈ 2^-9 sample at 24,000) vs the model's continuous Q24.43 lag — the sinc tap phase jitters ±1/256 sample between engine and model, concentrated at transients and amplified by the 0.71-feedback loop (metallic) — plus the LFO-modulation timing class. Tempo-synced case: dexie (169.5 BPM, ratio 1.4125, sync on the mod-LFO rate) = the closest delay result (rms −44.2 vs −46 proposed). Stop/escalate per the issue: routed to SXT-017/SXT-025 (budget freeze decides tighter model numerics — e.g. float32-lag emulation — or different budgets) | `audio-{fm_bass_1,metallic,dexie}.json` |
| A3 | Per-instance state: two Delay slots independent; shared-state implementation fails | **PASS** | metallic carries TWO real Delay instances (ains1 + send1) with different parameters; the tb instantiates independent per-instance state AND independent line pairs; NC (a): a mutant tb aliasing both instances onto one line pair FAILS the comparator (26+ mismatches) — `negative-controls/nc-a-shared-line.json`, `tb_fx_shared_line.sv` |
| A4 | Feedback stability, interpolation reads, parameter-modulation corners | **Stability: PASS (model)** — extended-max feedback corner (fb_extend, fb_f = 1.0 → loop gain 1.0 through softclip, mix 1.0, click train, 1,740 blocks): bounded, max \|out\| = 1.507, zero saturation samples; RTL-vs-model on this corner FAILS (same open delay-tb defect as A1 — the corner model evidence stands). **Interpolation reads: PASS (model)** — the 12-tap sinc with per-sample phase is the frozen model's core and is verified against the engine to the quantization floor on fm_bass_1-class material and ±4 LSB class on dexie-class material (model-side); **RTL interpolation: covered by the A1 FAIL.** **Modulation: PASS (structural)** — the LFO→delay-time path is implemented (lfophase/LFOval/timing verified: engine-measured 187.5-sample delay vs model 187.5; LFO-rate table corrected to dsamplerate_os = 96 kHz during this leaf); the LFO-modulated metallic/dexie renders are the A2 FAIL cases | `negative-controls/nc-c-maxfb-corner.json`, `/tmp/corner.py` inputs |
| A5 | Bypass passes the unmodified signal (bit-transparent at declared boundaries) | **PASS (model, declared boundary)** — empty-chain run over fm_bass_1 (volume 0 dB → A = 1.0 exactly): out = clip8(A·x) equals the quantized input bit-for-bit on 265,920 samples, 0 mismatches | `negative-controls/nc-d-bypass.json` |
| A6 | Buffer traffic measured against the external-memory model (#10) | **PASS (measured)** — 24 line reads (12-tap sinc × 2 ch) + 64 writes (32 × 2 ch) per frame per instance = 88 accesses; read bursts 2×48 B, write bursts 2×128 B; dexie full-render model counters 6,750,720 reads / 562,560 writes over 8,550 frames. Latency tolerance + burst shape + the SXT-016 window-cache reconciliation in `rtl/effects/delay/ext_mem_if.md` | `artifacts/ext_mem_traffic.json`, `ext_mem_if.md` |
| A7 | Negative controls: (a) shared-line FAIL; (b) wrong-interpolation FAIL; comparator mutant FAIL | **PASS** — (a) shared-line aliasing mutant: comparator FAIL (26+ mismatches); (b) nearest-neighbor tap substitution model: vs engine max 175,619 LSB / rms 18,007 LSB — grossly exceeds the proposed budgets (vs the frozen model's 6,477 rms) → the sinc interpolation is load-bearing and its absence is detected; (e) one-hex-digit mutant of the RTL biquad-lag constant: comparator FAIL | `negative-controls/nc-a-shared-line.json`, `nc-b-*` (NN model `delay_model_nn.py`), `nc-e-comparator-mutant.json`, `tb_fx_mutant.sv` |

## Achieved numbers (summary)

| slice | model-vs-engine (mono, proposed budgets: max ≤ 8,192 LSB / rms ≤ −46 dBFS / corr ≥ 0.98) | RTL-vs-model |
|---|---|---|
| EQ (fm_bass_1) | **max 7.8 LSB, rms 1.0 LSB (−120.0 dBFS), corr 1.000 — PASS** | **exact: 0 / 547,200 samples** |
| Delay (metallic, 2 instances, fb 0.71 class) | max 195,634 LSB, rms −33.5 dBFS, corr 0.975 — **FAIL vs proposed** | FAIL (open tb defect) |
| Delay (dexie, tempo-synced LFO rate) | max 72,738 LSB, rms −44.2 dBFS, corr 0.995 — **FAIL vs proposed (near)** | FAIL (26+ capped) |

Max-feedback corner (fb gain 1.0, softclip loop): model bounded at 1.507
max, no saturation — **stability evidence**.

## Deviations / known error sources (declared)

1. Engine float32 lag-state staircase (ulp 2^-9 sample at 24,000-sample
   delays) vs model continuous Q24.43 lag: tap-phase jitter ±1/256 sample —
   the dominant delay model-vs-reference deviation; amplified by the 0.71
   feedback loop (metallic) and the LFO sweep (dexie).
2. Engine float32 sinc table / float32 table lerps vs double-derived
   Q2.29/Q24.43: ≤1 LSB/tap class.
3. Delay RTL-vs-model (A1 FAIL): open tb defect, root causes found and fixed
   are listed in A1; the remaining ~10%-gain/0.94-corr residual not isolated.
4. Q24.43 biquad path vs engine double: ≤1e-13 class (fm_bass_1 exactness
   confirms the floor).

## Escalations / hand-offs

1. Delay model-vs-reference budgets: NOT met at the [PROPOSED] values →
   per the issue's stop/escalate, routed to SXT-017/SXT-025: either the
   freeze adopts float32-domain lag/phase emulation in the model (cost:
   float32 semantics in the "no float" audio path — a contract revision) or
   sets delay-specific budgets from these achieved numbers.
2. Delay-RTL bit-exactness: open tb defect (A1) — the models + harness +
   stimulus infrastructure are delivered; the remaining tb iteration is
   scoped (the EQ path of the same tb is exact, so the defect is localized
   to the delay datapath).
3. Chime Bell.fxp (Delay+EQ, 112 BPM) was REJECTED: its Delay Mix is
   modulated by a global LFO — LFO-to-FX-parameter modulation is outside the
   frozen scope (fail-closed), noted for SXT-024/SXT-026 scope decisions.

## Licensing / provenance

Everything under `model/effects/`, `rtl/effects/`, `tools/` (new compare/
render tools) and `reports/sxt-023/` is original to this repository
(Apache-2.0 per `LICENSE`). The pinned GPL engine was imported at runtime
only; all structure was READ and cited (file:function references inline
above and in the model headers); the sinc table is re-derived from the
cited construction formula; no Surge source, tables, or presets are copied
into this repository. Method template (float→fixed→RTL exactness harness)
follows the issue's reusable-substrate pointer as method only.

## Explicitly NOT established

* Delay-RTL bit-exactness (open tb defect — A1 FAIL, routed).
* Delay model-vs-reference within the [PROPOSED] budgets (A2 FAIL for the
  delay presets — honest; pending-freeze decision routed).
* Any FPGA/gf180mcu synthesis, timing, area, power, or hardware playback.
* Any preset-support or musical-quality claim (no listening record).
* Effects outside Delay/EQ (Reverb1 #17, complete wet gate #18, SXT-024+).
