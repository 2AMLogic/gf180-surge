# SXT-037 frozen LP 12 dB filter model (`model/voice/filter_lp12/`)

Frozen reference for the SXT-037 filter-leaf RTL (`rtl/voice/tb_lp12.sv`).
The RTL must match this model **exactly** (integer equality at every
declared checkpoint; `tools/compare_rtl_model_lp12.py`). Model-vs-pinned-
engine agreement is a separate claim governed by **[PROPOSED]** budgets
(PENDING-FREEZE; SXT-013 owns the fidelity policy) measured on the leaf's
carrier fixtures under `reports/sxt-037/`.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
  48 kHz, block size 32 / OS block 64 (`oracle/manifest.json`)
- Type scope: `fut_lp12` **only** (one algorithm per leaf)
- Subtype scope: the full engine-declared set at the pin —
  `st_Standard`(0) → `SVFLP12Aquad`, `st_Driven`(1) → `IIR12CFCquad`,
  `st_Clean`(2) → `IIR12Bquad` (pinned `GetQFPtrFilterUnit` table)
- Observed corpus subtype inventory (graphs.jsonl, informational): 665×
  Standard, 602× Driven, 72× Clean
- Carrier fixtures: `Bluelight/Pads/Bad News.fxp` (Driven, unit 1),
  `Bluelight/Pads/Rainy Day Dreamaway.fxp` (Driven, unit 1),
  `Emu/Drums/T9 Tom.fxp` (Clean, unit 2)

## Declared parameter scope (fail-closed outside)

| Parameter | Declared scope | Outside scope |
|---|---|---|
| filter type | `fut_lp12` (1) | REFUSED (`Refuse`) |
| subtype | {0, 1, 2} | REFUSED |
| resonance (reso) | [0, 1] normalized | REFUSED |
| cutoff input | [-240, +240] st (engine cutoff parameter span) | REFUSED |
| cutoff after `boundFreq` | clamped to [-55, +75] st (pinned) | frozen clamp, declared |
| keytrack / env-mod inputs | absorbed at the control-plane boundary (below) | n/a |

Refusals raise/exit (exit code 2 class) — an out-of-scope fixture can never
silently produce audio (AGENTS.md fail-closed rule).

## Declared control-plane boundary

Block-rate coefficient generation is this leaf's DSP and stays IN the model:
`make_coeffs(cutoff_a, reso_a)` (cited `Coeff_SVF` / `Coeff_LP12` bodies:
`resoscale`, `Map2PoleResonance`, `clipscale`, `boundFreq`,
`ToCoupledForm` / `ToNormalizedLattice`) plus `FromDirect` smoothing
(`tC += 0.2*(N - tC)`; `dC = (tC - C)/64`; FirstRun: `C = tC = N`, `dC = 0`).
The per-block *inputs* `(cutoff_a, reso_a)` for the reference legs are the
engine's own values, captured by the oracle tap instrumentation
(decision-records/0005) — the same declared control-plane boundary class as
SXT-022 (block-rate words streamed around the audio-rate datapath). The
cutoff control arithmetic (`cut + kt*(pitch - ktR) + em*feg + modroutes`,
SurgeVoice.cpp `process_block`) is therefore OUTSIDE this leaf's model; the
leaf reproduces everything from the coefficient maker down.

The voice path reads the advanced kernel C back into the coefficient maker
after every block (`CM[u].C[i] = get1f(fbq->FU[u].C[i], fbqi)`); the model
mirrors this copy-back exactly.

## Frozen word lengths

| Domain | Format | Notes |
|---|---|---|
| samples, filter state, coefficients, clipgain | **Q10.21** (signed 32-bit) | same universal word as the SXT-022 voice model |
| coefficient construction intermediates | double, quantized once | house convention: construction formulas evaluated in double, engine evaluates float32/double mixes (declared deviation, in-budget class) |

Arithmetic rules are the SXT-022 frozen set: exact 64-bit products rounded
round-half-up `r = (a*b + (1 << (s-1))) >> s`, saturation to signed 32-bit,
`qdiv` (round-half-up) only at coefficient rate, no run-time floating point
in the audio path.

## Frozen per-sample schedule (one OS sample)

Reload + kernel per subtype, exactly as the pinned kernel bodies
(`QuadFilterUnit_Impl.h`):

1. **Driven (`IIR12CFCquad`)**: `C[i] += dC[i]` for i ∈ {0,1,2,4,5,6};
   `y = C4·R0 + C6·x + C5·R1`; `s1 = x·C2 + C0·R0 − C1·R1`;
   `s2 = C1·R0 + C0·R1`; `R0 = s1·Rclip`; `R1 = s2·Rclip`;
   `C7 += dC7`; `Rclip = max(0.1, 1 − C7·y²)` — the clipgain register
   multiplies the state update with its PREVIOUS value.
2. **Clean (`IIR12Bquad`, normalized lattice)**: `f2 = C3·x − C1·R1`;
   `C1 += dC1`; `C3 += dC3`; `g2 = C1·x + C3·R1`; `f1 = C2·f2 − C0·R0`;
   `C0 += dC0`; `C2 += dC2`; `g1 = C0·f2 + C2·R0`; `C4 += dC4`; `C5 += dC5`;
   `C6 += dC6`; `y = C6·g2 + C5·g1 + C4·f1`; `R0 = f1·Rclip`;
   `R1 = g1·Rclip`; `C7 += dC7`; `Rclip = max(0.1, 1 − C7·y²)` — reload
   order interleaved exactly as pinned (K/Q before use in `g`, V before `y`).
3. **Standard (`SVFLP12Aquad`)**: `C0 += dC0`; `C1 += dC1`; the pinned
   zero-delay-feedback SVF ladder (`L, H, B, L2, H2, B2`);
   `R0 = B2·Rclip`; `R1 = L2·Rclip`; `C2 += dC2`;
   `Rclip = max(0.1, 1 − C2·B²)`; `C3 += dC3`; `y = L2·C3`.

Per-instance state (never shared): `R0, R1, Rclip` per voice/unit instance.

### Register initialization (declared, engine-cited)

The per-voice `FBP` is zero-initialized (voice creation) and re-zeroed on a
type/subtype change (`memset(&FBP.FU[u], 0, ...)`, `CM[u].Reset()`),
including the clipgain register: **`Rclip` starts at 0**, so the first OS
sample of an instance seeds no state (`R0 = s1·0 = 0`) and `Rclip ≥ 0.1`
from the second sample on. (Declared divergence from the landed SXT-022
voice model, which initializes its clipgain state to 1.0 — a ≤1-sample
state-seeding approximation there; this leaf freezes the engine behavior.)

## Stability argument (frozen model)

For Driven/Clean, the coupled-form pole radius satisfies `ρ² = a2 =
1 − alpha ≤ 1` with `alpha = sinu·M2PR ≥ 0` in-band, and the self-osc guard
`alpha ≤ sqrt(1 − cosi²) − 1e-4` keeps `ρ < 1` at the resonance corner; the
clipgain contraction `Rclip ∈ [0.1, 1]` further shrinks every state update.
For Standard, the pinned `Q1 ≤ min(2, 2 − 1.52·F1)` clamp bounds the SVF
loop. The model additionally runs an empirical per-block peak monitor
(`stability_verdict`): sustained exponential growth into headroom is
reported **UNSTABLE** (recorded alarm, never a silent clamp).

## Costs (for the SXT-016 reconciliation)

Measured qmul counts of the frozen schedule: Driven 8/sample, Clean
9/sample, Standard 9/sample (per instance; `run_filter_leg.py` reports the
exact totals per fixture). Coefficient-plane cost is per 64-OS-sample block
(one `make_coeffs`), consistent with the SXT-016 assumption that block-rate
coefficient recompute amortizes below 1 cycle/sample
(`probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip`). State: 3×32-bit
registers + 16×32-bit coefficient words per instance (640 bits), vs the
SXT-016 `filter_unit_state_bytes` planning row (256 B) — divergence
recorded in `reports/sxt-037/EVIDENCE.md`, not reconciled away.

## Files

* `filter_lp12_model.py` — the frozen model (importable)
* `run_filter_leg.py` — tap bundle → model legs L1/L2a/L2b + RTL stimulus

## Reproduce

```sh
# reference bundles (oracle host with the externally patched pinned build):
python3 tools/render_lp12_reference.py --cases all --out-dir reports/sxt-037/artifacts
# model legs + RTL stimulus:
python3 model/voice/filter_lp12/run_filter_leg.py \
    --bundle reports/sxt-037/artifacts/bundle-badnews --out-dir /tmp/run-badnews
# exactness (iverilog):
python3 tools/compare_rtl_model_lp12.py --run-dir /tmp/run-badnews
# budgets (PENDING-FREEZE):
python3 tools/compare_lp12_model.py --traces /tmp/run-*/model_trace.json \
    --out-dir reports/sxt-037/artifacts
# negative controls:
python3 tools/lp12_negative_controls.py
```
