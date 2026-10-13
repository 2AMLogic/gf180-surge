# SXT-023 / issue #16: Delay delay-time (d(t)) probe and model revision

Dated 2026-10-09. Supersedes the "BLOCKED / NOT_RUN" rows of the 2026-10-08
status table in `followup.md` section "Status of the remaining increment".
`EVIDENCE.md` is sha256-pinned and is not edited; this file and the dated
section appended to `followup.md` are the update.

Claim scope: Delay model-vs-engine (claim 2) and RTL-vs-model (claim 1) for
the `metallic` and `dexie` fixtures only. No preset-support, musical-quality,
synthesis, timing, area, power or hardware claim.

## 1. What the probe measured

`tools/probe_delay_dt_engine.py` (new) drives a fresh pinned surgepy instance
(`1.4.HEAD.58914e59c`, 48 kHz, block 32; engine imported at runtime only, no
Surge code or table copied) with an impulse train through the Delay and fits,
per pulse and per channel, the effective read position v(t) at 1/256-sample
resolution (least squares over integer delay and all 256 sinc phases against
the repository's own table). The model side replays the same block schedule.
Output: `artifacts-followup/dt-probe/dt-probe-{metallic,dexie}.json`
(3x bit-identical renders per probe, recorded in each file).

Mechanisms found, each isolated by a model variant in the probe JSON:

1. **Pre-roll (F-318-1).** `run_fx_model.py` ran 240 silent settle blocks; the
   fixture harness settles `int(0.25*48000)//32 = 375`. The Delay LFO advances
   during settle, so the model's LFO was 135 blocks out of phase. Dominant
   term. (`pre_revision` -> `settle_only`: v error 29 -> 0.24 samples.)
2. **Load-time LFO step.** `loadPatch` runs `Delay::initialize -> setvars(true)`
   once before the host tempo reaches storage, i.e. with the constructor
   `temposyncratio = 1.0`; that one LFO advance persists. Mirrored by
   `DelayModel._load_time_control` (`settle_only` -> `settle_loadstep`:
   0.24 -> 0.02 samples on the dexie/metallic ains instance).
3. **float32 delay-time lag.** The engine's `SurgeLag<float>` state is float32.
   At the 24,000-sample metallic send delay the float32 step falls below half
   an ulp within ~10 samples, so the lag freezes on the float32 grid. The old
   Q24.43 lag is continuous and diverges. The model lag now lives on the
   float32 grid (RNE at 24 significant bits) inside its Q24.43 word.

Platform finding (measured, not assumed): the committed fixtures were rendered
by `surgepy.cpython-311-darwin.so` (arm64, FMA-contracted
`v*lpinv + target*lp`). This dispatch host's engine is linux x86_64, which
evaluates the same statement unfused. The model mirrors the **fixtures of
record** (fused). Against this host's linux engine the probe's `revised`
variant FAILS the d(t) check (send1 delay 24,000: ~5.9 samples apart) while
`linux_x86_semantics` PASSES (fit error <= 0.022 samples, replay residual
<= -78 dB); both are in the JSON. Consequence: the model is calibrated to the
darwin reference of record. A fresh render on this linux host would not match
it, which is itself reference-vs-reference platform variance and is NOT
resolved here (see section 4).

## 2. Achieved numbers (mono sum, native levels, `tools/compare_fx_reference.py`)

| fixture | max (LSB, budget 8,192) | rms (dBFS, budget -46.0) | spectral_corr (>= 0.98) | tail residual mono / L / R (budget -20 dB) | verdict |
|---|---|---|---|---|---|
| metallic | 182.4 | -109.0 | 0.9999995 | -77.4 / -68.8 / -69.8 | PASS |
| dexie | 11.1 | -130.3 | 0.99999999 | -92.5 / -87.8 / -88.1 | PASS |
| fm_bass_1 (EQ, regression) | 7.75 | -120.0 | 0.99999998 | tail gate PASS | PASS |

(was: metallic -33.5 dBFS / 195,634 LSB / tail FAIL; dexie -44.2 dBFS / 72,738
LSB / tail FAIL.) Records: `artifacts/audio-{metallic,dexie,fm_bass_1}.json`.
Previously recorded numbers were produced with the 240-block pre-roll, which is
why the earlier "LFO term is the miss" diagnosis (depth 0 hides the phase
error) pointed at the LFO path: the LFO itself was correct, its phase was not.

## 3. RTL-vs-model (iverilog 13.0, full length, 8,925 blocks incl. 375 settle)

| slug | outputs | checkpoints / fields | mismatches | verdict |
|---|---|---|---|---|
| metallic | 547,200 | 272 / 8,704 | 0 | PASS |
| dexie | 547,200 | 136 / 4,352 | 0 | PASS |
| fm_bass_1 (EQ) | 547,200 | 136 / 4,080 | 0 | PASS |

`rtl/effects/tb_fx*.sv` mirror the float32-grid fused lag bit-for-bit
(`lag_f32`, `f32r86`). Verilator equivalence (`verilator-equivalence-medium.json`):
NOT_RUN for the revised tb; the PR #46 record is for the pre-revision tb and
is STALE with respect to it.

## 4. Open / unproved

* Platform variance of the reference (darwin fused vs linux x86 unfused lag)
  is unresolved; the budgets are met against the committed darwin fixtures.
  A linux-rendered fixture set would need the `revised_unfused_lag`/
  `linux_x86_semantics` model variant, whose control plane (float32 per
  operation) is not what the frozen model implements. Route to #12.
* Control-plane float32 per-operation rounding of the LFO/target expressions
  is not mirrored (declared; below the measured floor on the fixtures).
* Metallic's depth-0 static residual (-53.3 dBFS in the older diagnosis) was
  not re-isolated; with the revised model the full residual is -109 dBFS.
* Only two fixtures; no claim for other delay parameterisations.
