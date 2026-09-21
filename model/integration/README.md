# SXT-025 — Integrated wet-preset path (`model/integration/`)

Issue: #18 (SXT-025) · Plan:
`docs/surge-xt-chip-plan-v0.1-2026-09-20.md` §6 (SXT-025 row) · Evidence:
[`reports/sxt025/EVIDENCE.md`](../../reports/sxt025/EVIDENCE.md)

**Claim discipline.** One preset running through the integrated path is a
**diagnostic milestone, not a coverage claim** (plan §6). Nothing here is a
frozen fidelity verdict: all budgets are [PROPOSED], PENDING-FREEZE
(SXT-013). No FPGA/gf180mcu synthesis, place-and-route, signoff, or hardware
playback claim is made anywhere in this module. Most importantly, the
configuration recorded here is **adapted, not supported** — see finding
F-1 — so it can never count toward original-preset coverage (#20–#22).

## Pipeline

    compiled patch image (SXT-020)
      -> placement/order/enablement from image.fx_section (never a fixed
         global chain; engine_order = f(stored roles), verified)
      -> control plane: model/control/control_model.py (SXT-021, imported
         unmodified) — event schedule, decisions, latencies, pool/queue policy
      -> voice stage: DECLARED HOST BOUNDARY — see finding F-1
      -> FX chain in stored order: landed leaf models imported unmodified
         (Reverb1: model/effects/reverb1/reverb1_fixed.py SXT-024; EQ/Delay:
         model/effects/{eq,delay}, SXT-023 — instantiated PER IMAGE SLOT,
         per-instance state, never shared)
      -> stereo output

| File | Role |
|---|---|
| `selection_scan.py` / `selection-scan.json` | the forced preset selection (fail-closed census search, tier counts) |
| `preset/Hell_s_Bells__e499f78d.image.{bin,json}` | the committed compiled image (verifier PASS) |
| `extract_preset_inputs.py` / `bells_inputs.json` | fail-closed engine-side extraction of the FX control plane, cross-checked against the image |
| `render_fixtures.py` | pinned-oracle wet/dry reference buses (3x fresh instances, bit-identity gate) |
| `integration_model.py` | the fixed pipeline (this file's declarations) |
| `run_model.py` | E2E runner: wet render + trace + RTL stimulus |
| `compare_integration.py` | achieved metrics vs the SAME upstream fixture |
| `schedule_closure.py` | effects-active schedule closure + stall accounting |
| `negative_controls.py` | NC-A/B/C drivers |
| `sequences/sxt025-smoke-v1.json`, `sequences/sxt025-accept-v1.json` | integration sequences (NOT part of the SXT-012 library) |

## Finding F-1 (bounded): the voice-slice scope blocks a supported preset

The landed SXT-022 voice leaf is a **single-preset arithmetic slice**
(`Basses/Attacky.fxp`: Classic osc + LP 12 dB/Driven + mono +
modwheel-only modulation). The selection scan proves:

* with FX restricted to {EQ, Reverb 1} and the SXT-022 *structural* gates,
  exactly **one** corpus preset survives: `Rozzer/Bells/Hell's Bells.fxp`
  (the selection below);
* the landed voice-model *arithmetic* gates are satisfied by only **two**
  presets in the whole 3,561-entry corpus — `Attacky` (no FX) and
  `Quickspit` (no FX). **No preset carrying FX is renderable by the landed
  voice leaf.**

Per the issue's no-fork rule this integration does not invent Sine/LP24/
velocity-mod/FM voice arithmetic. The integrated pipeline therefore uses the
**declared leaf input boundary**: the pinned engine's own all-off DRY bus of
the SAME preset+sequence — exactly the input boundary the SXT-023/SXT-024 FX
leaves were verified against (model input = dry bus de-amped by the converged
master amplitude; wet compared against the engine's wet bus of the same
render).

Consequences, recorded honestly:

* the wet **FX stage is original** (placement, order, parameters, per-instance
  state, send/return staging from the preset) and passes the fidelity checks;
* the **voice stage is substituted** (engine dry bus), which under AGENTS.md
  makes this an **adapted** configuration: it does NOT count as supported and
  the "status recorded as supported under policy #8" acceptance row is
  delivered as the honest miss (`adapted-voice-input-boundary`);
* the affected dependency is the **voice-leaf scope extension** (SXT-022
  follow-up). The wet-preset gate itself is not weakened and no budget was
  relaxed.

## Declared selection (forced, not tuned)

`Rozzer/Bells/Hell's Bells.fxp` — census blob
`e499f78df5664012717dd2961944502846e28cf7`, graph sha256
`081d6ea6ed299a6793313eb193c9b17d2353e1a4770f54b3e752e23d90cd549a`, compiled
image sha256 `bf21250e85ec52a713671e2067237215c7223996b817b4af88a23a66a708f7a6`.
FX composition: exactly **one Reverb 1 @ send2** (send 0.934822^3, return
1.0^3, mix 1.0, width 0, decaytime 2.924107 -> nominal t60 = 2^2.924107 =
7.585 s). The Reverb1+EQ > Reverb1-only > EQ-only ranking cannot be improved:
no Reverb1+EQ preset survives Tier 2 of the scan (see
`selection-scan.json`), and Delay-carrying presets are out of scope (the
Delay budget decision is open at #16).

## Declared integration conversions and deviations

D-1 **Voice stage host-side** (finding F-1): the engine all-off dry bus of
the same preset+sequence feeds the chain; the SXT-022 leaf is not exercised
by this configuration (it is exercised, and passing, in its own evidence
record).

D-2 **Reverb1 boundary conversions** (Q10.21 chain words <-> leaf words):
(a) Q10.21 -> s24 input: exact `<<2` with a range assert; (b) s32i (Q4.28) ->
Q10.21 send-return output: round-half-up at f=7, saturated. Both are
sub-LSB-class vs the leaf's s24/s32i grids and are part of the measured
error.

D-3 **Gain staging** follows the SXT-023 chain convention: send/return =
`amp_to_linear(level)^3` in Q13.18; master amplitude `A = db_to_linear(volume)`
in Q13.18 with the **engine getter** value (-2.025745 dB loader default; the
image's stored scalar 0.0 dB is pre-migration, non-authoritative — same
loader class as SXT-023's metallic). Scene hardclip ±8 asserted inactive at
fixture peaks; master hardclip structural.

D-4 **Deactivated flags**: Reverb1 lowcut/highcut have no surgepy getter; the
raw .fxp XML carries NO per-param attributes at this revision, and the pinned
Parameter ctor defaults these (non-modulator, deactivatable) params to NOT
deactivated. Verified by the budget: the opposite hypothesis fails at
~-17 dB, the correct one reproduces the engine wet-dry difference exactly.

D-5 **Control-plane timeline**: the control model's block 0 is the first
post-settle block (the fixture harness's convention); the FX chain runs 240
silent settle blocks first (matching the engine's settle) so leaf state
evolution aligns sample-for-sample.

## RTL/host boundary (integrated RTL)

In-chip, in one iverilog simulation (`rtl/integration/tb_sxt025.sv`): the
SXT-021 `control_top` and the SXT-024 `reverb1_core` with its external
writable memory behind the `em_*` port (557,056 x 32b words; flash is never
a substitute), schedule-coupled: the kernel block for index b starts only
after the control plane's block-b boundary, and per-block kernel cycles are
counted against the declared budget.

Host-side (stimulus words emitted by `run_model.py`): the voice stage (D-1),
the send/return/master gain staging, and the s24 send-block quantization.
Full-RTL voice is explicitly NOT required by this issue.

Note: the simulated external memory is zero-wait-state (as in SXT-024), so
the measured in-sim kernel cycles EXCLUDE the A-EXT-2 stall terms; the
stall-inclusive closure uses the SXT-016 E2 probe row (835 cyc/sample-period
including 612 latency-bound) via `schedule_closure.py`.

## Reproduce

```sh
python3 model/integration/selection_scan.py                  # selection record
python3 compiler/verify.py image model/integration/preset/Hell_s_Bells__e499f78d.image.bin
python3 model/integration/extract_preset_inputs.py           # needs the oracle
python3 model/integration/render_fixtures.py                 # 3x bit-identity gate
python3 model/integration/run_model.py --sequence sxt025-smoke-v1
python3 model/integration/compare_integration.py --sequence sxt025-smoke-v1
python3 model/integration/run_model.py --sequence sxt025-accept-v1       # full length
python3 model/integration/compare_integration.py --sequence sxt025-accept-v1
python3 model/integration/schedule_closure.py --trace reports/sxt025/artifacts/trace__sxt025-accept-v1.json
python3 tools/run_sxt025_rtl.py --blocks 1024                # needs iverilog
python3 model/integration/negative_controls.py --sequence sxt025-accept-v1
```

Licensing: all files in this module are original to this repository
(Apache-2.0 per `LICENSE`). The pinned GPL engine is imported at render time
only; no Surge source, tables, or preset payloads are copied. The committed
WAV renders are this project's own renders of the loaded preset, not
redistributed upstream content.
