# SXT-039 frozen LP Legacy Ladder filter model (`model/voice/filter_lpmoog/`)

Frozen reference for the SXT-039 filter-leaf RTL (`rtl/voice/tb_lpmoog.sv`).
The RTL must match this model **exactly** (integer equality at every declared
checkpoint; `tools/compare_rtl_model_lpmoog.py`). Model-vs-reference agreement
is a **separate** claim governed by **[PROPOSED]** budgets (PENDING-FREEZE;
SXT-013/#12 owns the fidelity policy), measured against the pinned kernel by
`tools/compare_lpmoog_model.py`. Neither claim says anything about how the
filter sounds (claim 3 needs listening records, of which this leaf has none).

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, block size 32 / OS block 64, filter rate `dsamplerate_os` = 96 kHz
  (`oracle/manifest.json`); pinned `libs/sst/sst-filters@e92d93a9`,
  `libs/sst/sst-basic-blocks@a32b8aec`
- Type scope: `fut_lpmoog` (registry id 3, "LP Legacy Ladder") **only** — one
  algorithm per leaf
- Subtype scope: the **full engine-declared set** at the pin (4 subtypes):
  `st_lpmoog_6dB`(0) → tap `R[0]`, `st_lpmoog_12dB`(1) → `R[1]`,
  `st_lpmoog_18dB`(2) → `R[2]`, `st_lpmoog_24dB`(3) → `R[3]`
  (pinned `LPMOOGquad<subtype>` returns `f->R[subtype]`; one kernel, four taps)
- Observed corpus subtype inventory (`corpus/normalized/graphs.jsonl`,
  informational, not a support claim): 725 LP Legacy Ladder instances —
  6 dB 76, 12 dB 66, 18 dB 44, 24 dB 539
- Carrier instances (real normalized corpus entries, census-blob verified at
  fixture build time): `Bluelight/Pads/King.fxp` scene B units 1 **and** 2
  (24 dB; the second instance is the per-instance-state pair),
  `Damon Armani/Pads/House Of Chords.fxp` scene A unit 2 (24 dB at the gg
  clamp), `Inigo Kennedy/Atmospheres/Disturbances.fxp` scene A unit 1 (6 dB,
  live keytrack + env-mod)

## Declared parameter scope (fail-closed outside)

| Parameter | Declared scope | Outside scope |
|---|---|---|
| filter type | `fut_lpmoog` (3) | REFUSED (`Refuse`, exit-2 class) |
| subtype | {0, 1, 2, 3} | REFUSED |
| resonance | [0, 1] normalized | REFUSED |
| cutoff (post-control `cutoffA`) | [-240, +240] semitones rel. A440 | REFUSED |
| `gg = 440·ntp(cutoff)/96000` | clamped to [0, 0.187] **inside** the model | pinned engine clamp, reproduced exactly (never a model-side clamp of an out-of-scope input) |
| subtype change | only with the engine reset path (register memset + `CM.Reset()`) | REFUSED |
| tuning | standard 12-TET | the retune branch of `MakeCoeffs` is inert at the pin for this provider; non-12-TET is out of scope |

Refusals raise/exit (exit code 2 class) — an out-of-scope fixture can never
silently produce audio (AGENTS.md fail-closed rule).

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| samples, ladder registers `R[0..4]` | **Q10.21** (signed 32-bit) | the universal SXT-022 word; range ±1024 covers the `softclip8` ±12 bound with headroom |
| coefficient plane `C[8]`, `dC[8]`, `tC[8]` | **Q2.29** (signed 32-bit) | leaf-local freeze: the pinned `Coeff_LP4L` coefficients satisfy \|C\| < 4 (`c0 = 3/(3-q) ≤ 3.53`, `c1 = t_b1 ≤ 0.6913`, `c2 = q ≤ 2.15`), so Q2.29 is the **tightest** signed-32-bit word covering the pinned range, and the low end (`c1 ~ 1e-5` at the bottom of the cutoff span) needs every bit of it |
| control words (cutoff, keytrack, env-mod, filter-EG, resonance) | **Q10.21** | the SurgeVoice `cutoffA` arithmetic |
| `softclip8` cubic coefficient | **Q0.40** | `-4/27/8^3`, quantized once |
| `softclip8` first product | **Q1.31** | keeps the cubic correction term significant at the ±12 corner |

Measured effect of the coefficient-word choice (same fixtures, same
reference; recorded for transparency — the **frozen** model is the Q2.29 one):

| case | Q10.21 coefficients: max / rms LSB | **Q2.29 (frozen)**: max / rms LSB |
|---|---|---|
| king-b1 | 56 / 7.6 | **6 / 0.95** |
| king-b2 | 396 / 204.5 | **54 / 25.7** |
| disturb | 1776 / 330.7 | **39 / 8.9** |
| reso1 | 9370 / 2469.5 | **394 / 106.9** |
| cut-lo | 1146 / 404.9 | **1146 / 404.9** (unchanged — a register-word effect, finding F-039-2) |

Arithmetic rules are the SXT-022 frozen set: exact 64-bit products rounded
round-half-up `r = (a·b + (1 << (s-1))) >> s` with `s = fa+fb-fq`, saturated
to signed 32-bit; `qdiv` (round-half-up) only at coefficient rate; **no
audio-rate division** (A-ALU-2 holds for this leaf); no run-time floating
point in the audio path. Frequency-domain constructions (`note_to_pitch`
table body, `exp`) are evaluated in double against the pinned formulas and
quantized once (declared deviation: the engine evaluates float32 tables and
float32 `exp`; the difference is part of the model-vs-reference budget).

## Frozen coefficient construction (one block)

Pinned `Coeff_LP4L` (cited, not copied), evaluated in double and quantized
once into the Q2.29 plane:

```
gg   = clamp(440 · note_to_pitch_ignoring_tuning(cutoffA) / 96000, 0, 0.187)
t_b1 = 1 − exp(−2π·gg)
q    = min(2.15 · clamp(reso, 0, 1),  0.5 / t_b1⁴)      # +inf at t_b1 == 0
C[0] = 3 / (3 − q)      C[1] = t_b1      C[2] = q       # C[3..7] = 0
```

then the pinned `FromDirect` smoothing, shared by every filter type:
`tC += 0.2·(N − tC)`; `dC = (tC − C)/64`; **FirstRun**: `C = tC = N`, `dC = 0`.
`note_to_pitch_ignoring_tuning` is the pinned `SurgeStorage` body (coarse
`table_pitch` entry × the interpolated `table_two_to_the` fine table), not a
plain `2^(x/12)` — the fine-table lerp is part of the frozen construction.

`cutoffA` itself is IN this leaf's model (the issue's keytrack / env-mod
path), frozen from the pinned `SurgeVoice::process_block` body:

```
cutoffA = cutoff + keytrack_depth · (pitch − keytrack_root) + envmod · fenv
```

with the two modulation products formed first and added left to right
(saturating adds). `fenv` is an input word to this leaf: the filter-EG
definition state is absent from normalized schema rev 1.0.0, so the fixtures
drive it with a **declared trajectory** (`fixtures.py`), never a guessed
engine readback — see `reports/SXT-039/EVIDENCE.md` §0.

## Frozen per-sample schedule (one OS sample, one instance)

Pinned `LPMOOGquad<subtype>` order, exactly:

```
C[0] += dC[0];  C[1] += dC[1];  C[2] += dC[2]
fb     = R[3] + R[4]
drive  = (in·C[0] − C[2]·fb) − R[0]
R[0]   = softclip8(R[0] + C[1]·drive)
R[1]  += C[1]·(R[0] − R[1])
R[2]  += C[1]·(R[1] − R[2])
R[4]   = R[3]
R[3]  += C[1]·(R[2] − R[3])
y      = R[subtype]
```

`softclip8` (pinned `Clippers.h`): clamp to ±12, then `y = x + (x·a)·x²` with
`a = −4/27/8³` — the pinned op order (scale first, then cube) is kept because
the cube-first order overflows the sample word.

Per-instance state (never shared, even when arithmetic is shared): the five
registers `R[0..4]`. The per-voice `FBP` is zeroed at voice creation and
re-zeroed on a type/subtype change (`memset(&FBP.FU[u], 0, …)` +
`CM[u].Reset()`), so **all five registers and the FirstRun flag reset
together**; the model refuses a subtype change that does not carry that reset.
After every block the advanced kernel coefficients are read back into the
coefficient maker (`CM[u].C[i] = FU[u].C[i]`), mirrored exactly.

## Stability argument (frozen model)

The only feedback path re-enters stage 0, whose output is `softclip8`-limited
to |R[0]| ≤ 12; stages 1..3 are one-pole smoothers with
`C[1] ∈ [0, 1−exp(−2π·0.187)] = [0, 0.6913]`, i.e. `|1 − C[1]| ≤ 1`, so no
state can exceed the stage-0 bound in steady state and the ladder cannot
diverge for any in-scope coefficient. `stability_verdict()` is the empirical
check of that argument (saturation neighbourhood = UNSTABLE by definition, a
recorded alarm, never a silent clamp); every committed fixture including the
`reso1` (q ceiling) and `hot` (over-unity drive) corners reports STABLE.

## Costs (planning numbers for the SXT-016 reconciliation)

9 MAC (`qmul`) per OS sample per instance — 6 coefficient products + 3
`softclip8` products — plus 11 saturating adds and **zero** audio-rate
divisions; one `make_coeffs` per 64-sample block. Per-instance state: 5×32-bit
registers (160 bits) + the 16×32-bit streamed coefficient plane. No SXT-016
probe exists for `fut_lpmoog`; the nearest planning rows are recorded, not
reconciled away (`reports/SXT-039/artifacts/costs.json`). No timing, area,
power or synthesis claim.

## Files

* `filter_lpmoog_model.py` — the frozen model (importable)
* `fixtures.py` — fixture definitions (control planes + stimulus), shared by
  the model runner and the pinned-kernel reference renderer
* `run_filter_leg.py` — fixture → model trace + RTL stimulus

## Reproduce

```sh
# model run + RTL exactness (iverilog):
python3 model/voice/filter_lpmoog/run_filter_leg.py --case king-b1 --out-dir /tmp/run-king-b1
python3 tools/compare_rtl_model_lpmoog.py --run-dir /tmp/run-king-b1

# budgets against the COMMITTED pinned-kernel reference (no oracle needed):
python3 tools/compare_lpmoog_model.py --run-dirs /tmp/run-king-b1 \
    --ref-dir reports/SXT-039/artifacts --out-dir /tmp/budget

# negative controls + the whole re-verification:
python3 tools/lpmoog_negative_controls.py --artifact-dir /tmp/nc \
    --ref-dir reports/SXT-039/artifacts
python3 tools/run_sxt039_checks.py

# regenerate the reference streams (needs the pinned checkouts, DR-0009):
python3 tools/render_lpmoog_reference.py --cases all \
    --sst-filters <pinned sst-filters> --sst-basic-blocks <pinned sst-basic-blocks> \
    --out-dir reports/SXT-039/artifacts
```
