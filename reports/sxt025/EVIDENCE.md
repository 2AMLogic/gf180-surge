# SXT-025 evidence record — integrated wet-preset path (issue #18)

Branch: `loom/sxt-025-wet-gate` · Issue: #18 (SXT-025) · Date: 2026-09-21

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).

**Claim discipline.** One preset through the integrated path is a
**diagnostic milestone, not a coverage claim** (plan §6). This record
establishes **no** preset-support claim, **no** musical-quality claim, and
**no** FPGA/gf180mcu synthesis, timing, area, or hardware playback claim;
all cycle numbers are candidate-clock arithmetic under named assumptions
(A-CLK class). All fidelity budgets are [PROPOSED], PENDING-FREEZE (SXT-013).
The configuration is **adapted, not supported** (finding F-1) — it never
counts toward original-preset coverage (#20–#22).

## Chosen preset (forced, not tuned)

**`patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp`** — census blob
`e499f78df5664012717dd2961944502846e28cf7`; normalized graph sha256
`081d6ea6ed299a6793313eb193c9b17d2353e1a4770f54b3e752e23d90cd549a`;
compiled image sha256
`bf21250e85ec52a713671e2067237215c7223996b817b4af88a23a66a708f7a6`
(`compiler/verify.py image` PASS, 5 checks).

FX composition: **exactly one Reverb 1 @ send2** (slot 5, engine_order 22,
routing-active; send 0.934822³ = 0.816934 in Q13.18, return 1.0³, mix 1.0,
width 0, decaytime 2.924107 → nominal t60 = 7.585 s, shape 3, roomsize
0.540177, lowcut/highcut active). Selection method: fail-closed census scan
(`model/integration/selection-scan.json`, census sha
`c90424d9…`) over all 3,561 graphs: 1,683 compiled → 186 with FX ⊆
{EQ, Reverb 1} (Delay-carrying presets out per #16) → 122 single-scene +
poly → **1** survivor of the SXT-022 structural voice gates. The
Reverb1+EQ > Reverb1-only > EQ-only ranking cannot be improved (no
Reverb1+EQ preset survives Tier 2; EQ-only candidates all sit further from
the voice slice).

## Finding F-1 (bounded; BLOCKS only the supported-status row)

**No compiled corpus preset carrying EQ/Reverb1 FX is renderable by the
landed SXT-022 voice-model arithmetic.** The landed voice leaf is a
single-preset slice (Attacky: Classic + LP12-Driven + mono + modwheel-only
mod); the scan shows the only presets inside that arithmetic (Attacky,
Quickspit) carry **no FX**. Per the issue's no-fork rule this integration
does not invent Sine/LP24/velocity-mod/FM voice arithmetic; the voice stage
runs at the **declared FX-leaf input boundary** — the pinned engine's own
all-off DRY bus of the SAME preset+sequence (the exact boundary the
SXT-023/SXT-024 FX leaves were verified against). Consequence per AGENTS.md:
this is an **adapted** configuration. The affected dependency (voice-leaf
scope extension) is routed below; the wet-preset gate is not weakened and no
budget was relaxed.

## Acceptance mapping (issue #18)

| #18 acceptance item | Status | Evidence |
|---|---|---|
| Effect placement/order preserved exactly as the preset stores them (no fixed global chain) | **PASS** | The chain is instantiated from the compiled image's `fx_section` (phase `send_bus`, `order_in_phase` 2, `engine_order` 22 for slot 5), re-derived from the stored roles and cross-checked fail-closed (`integration_model._verify_image`); the engine-order invariant and the image-vs-extraction agreement are asserted in `tests/test_sxt025_integration.py`. Single-instance degeneracy of "reordering" is covered by NC-A (placement permutation detected) with the degeneracy recorded in the transcript. |
| Wet/dry levels and gain staging within budget vs the upstream fixture | **PASS (PENDING-FREEZE)** vs [PROPOSED] budgets (max ≤ 8,192 LSB / rms ≤ −46 dBFS / corr ≥ 0.98) | Full-length acceptance (`sxt025-accept-v1`, 840,000 frames = 17.5 s): mono max \|Δ\| **4.5 LSB**, rms **−125.7 dBFS**, spectral corr **1.0**, best shift **0** (L 4.6/−124.8/1.0; R 4.9/−124.6/1.0). Smoke (`sxt025-smoke-v1`): 2.8 LSB / −126.0 dBFS / 1.0 / 0. Gain staging from loader-normalized state (master −2.025745 dB — the image's stored 0.0 dB scalar is pre-migration; send/return cubed per `amp_to_linear`), recorded in the trace manifests. Reference fixtures: 3× fresh-instance renders **bit-identical** (SXT-012 method), dry-bypass read-back verified. |
| Tails after note-off intact and within budget | **FAIL on one [PROPOSED] sub-budget (bounded finding recorded); all other tail budgets PASS** | 12 s tail (≥1.58 × t60) after the last note-off (t=264,000; tail 576,000 frames). PASS: tail rms rel **−52.8 dB** (≤ −50), decay-curve max dev **0.005 dB** (≤ 1.0), stereo-corr delta **5.1e-9** (≤ 0.02), continuity above the floor, absolute tail error −67.1 dBFS. **FAIL: band-energy sub-budget** — the 16–22 kHz band over the tail deviates **25.7 dB** (reference −68.1 dBFS vs model −42.4 dBFS): in the final 3 s the reference band decays to **−99.6 dBFS** while the model floors at **−45.6 dBFS** — the frozen Q4.28 round-half-up recirculation accumulates HF quantization noise the float32 reference does not have (the SXT-016 probe's predicted dither/decay-floor class; the frozen leaf ships no decay-floor dither). Recorded for the SXT-013 word-length/dither decision; **not tuned away** (the same comparator passes the broadband tail at −52.8 dB, so this is a specific, characterized defect class, not general divergence). |
| Memory stalls accounted; schedule closes under worst case with effects active | **PASS** (arithmetic on named assumptions; explicit OVERFLOW objects) | Kernel row = SXT-016 `reverb1_composite_ext_E2` **835 cyc/sample-period incl. ext-memory stalls** (612 latency-bound under A-EXT-2), replacing the SXT-021 stub placeholder. Closure with 4 events/block + control 72 + events 704 + kernel 835 + transfer 8 + contention 990 = **2,257 vs budget 3,200 at 192 MHz → within_budget**; within_budget at 480 MHz; **explicit `schedule_budget_overflow` rejection objects at 48/96 MHz**. Measured traffic: **34 words = 136 B per output frame** (reconciles SXT-024 model + SXT-016 byte rate 6.528 MB/s); external writable buffer 2,228,224 B per instance; flash is never a substitute. |
| Status recorded as supported under policy #8 | **HONEST MISS — NOT SUPPORTED (`adapted-voice-input-boundary`)** | Finding F-1: the voice stage is the engine's own dry bus (declared substitution), so under AGENTS.md this preset is **adapted** and never counts as supported. What IS established: the complete wet FX path (placement, order, per-instance state, gain staging, tails, schedule, external memory) passes the integrated model+RTL path within [PROPOSED] budgets except the recorded band-energy finding. Evidence hashes retained below. PENDING-FREEZE caveat: the fidelity policy is unfrozen; even a full PASS would have been provisional only. |
| Negative control: reordering that preset's effects must be detected | **PASS (control demonstrably fails its check)** | **NC-A** placement permutation (send2 → ains1 in the image + inputs): comparator flags it (spectral corr collapses vs budgets) — `negative-controls/nc-a-*.json`. Degeneracy note: the preset stores ONE effect, so the reorder axis is the engine's phase boundary; recorded. **NC-B** tail truncation (cut 1.0 s after last note-off, silence-padded): tail checks FAIL → detected. **NC-C** silent stub swapped into the integration slot: fails the wet-activity output contract and the budgets; the RTL-side **stale stub** (committed `reverb1_broken_mutant.sv`) FAILS the kernel exactness + txn comparison. Transcript: `negative-controls.txt` — ALL CONTROLS HEALTHY. |

## Integrated RTL (rtl/integration/tb_sxt025.sv)

One iverilog simulation, one clock: `control_top` (SXT-021) + `reverb1_core`
(SXT-024) with 557,056-word external writable memory, schedule-coupled (the
kernel block starts only at the control plane's block boundary). Compared
with exact integer equality over the first 1,024 smoke blocks (all four
events + post-release tail decay):

| Case | control snapshots | decisions | kernel T/O | txn log | traffic | cycles | verdict |
|---|---|---|---|---|---|---|---|
| integrated | EXACT (1,024 T lines) | EXACT (4 E lines) | EXACT (1,024 blocks) | EXACT (278,528 txns + K/Z) | 34 words/frame | worst 1,345 ≤ 102,400/block | **PASS** |
| `reverb1_broken_mutant` (stale tap-7 write) | — | — | **FAIL** | **FAIL** | — | — | **CONTROL-OK** |

Zero underruns. Declared boundary: voice stage + gain staging host-side
(full-RTL voice NOT required by the issue); the simulated external memory is
zero-wait-state, so in-sim cycle counts exclude A-EXT-2 stall terms — the
stall-inclusive closure uses the probe row (see `schedule_closure.py`).

## Event-to-output timing

Max recorded decision latency: **0 samples** (acceptance; smoke 0) — events
quantize UP to the 32-sample block and dispatch at that block's start, the
same ceil convention the engine fixture harness uses, so the model wet bus is
sample-locked to the reference (best shift 0). Worst coincident events per
block: 4 ≤ 8 declared reserve; no drops, no underruns, no overflow.

## Deviations / declared items

D-1 voice stage host-side at the dry-bus boundary (F-1, adapted); D-2
Q10.21↔s24/s32i boundary conversions (exact/rnd7, sub-LSB); D-3 gain staging
per the SXT-023 chain convention with the loader-normalized master volume;
D-4 Reverb1 lowcut/highcut deactivated flags default NOT deactivated at this
revision (absent raw attributes; budget-verified: the opposite hypothesis
fails at ~−17 dB, the correct one reproduces the engine exactly); D-5
control timeline block 0 = first post-settle block, FX chain runs the 240
settle blocks for state alignment. D-6 the RTL exactness coefficients are
taken from the committed `cfg.hex` (the pinned-interpreter artifact) because
the coefficient-plane derivation depends on libm at the last ulp — cross-
interpreter rebuilding shifts band-1 coefficients by ≤ 7 c29 LSB, which the
1024-block RTL run exposed at block 469.

## What this record does NOT establish

* Any supported preset (F-1: adapted configuration) — and therefore no
  progress number toward #20–#22.
* Any frozen budget (SXT-013 BLOCKED on human listening); the band-energy
  finding and the word-length/dither question are routed to that freeze.
* Voice-path fidelity for this preset (SXT-022's Attacky evidence stands
  separately); EQ/Delay kernels inside this preset's path (no such slots —
  their exactness evidence stands in SXT-023).
* Any gf180mcu synthesis, place-and-route, timing closure, area, power, or
  hardware playback result.

## Evidence hashes (sha256)

| Artifact | sha256 |
|---|---|
| selection-scan.json | `2232d4ce4e23448aab8f7f3e66e19ddca813fe0cc23015eb75887192fbd3f6f5` |
| compiled image (.bin) | `bf21250e85ec52a713671e2067237215c7223996b817b4af88a23a66a708f7a6` |
| compiled image (.json) | `b1c3156603b8bdde76f0b54f2c389d68d6ef6ebd89998f71fa1ed5b95987d1c1` |
| bells_inputs.json | `6d4c76b25bb9a73c822293d38cd8fda346147a91389c4ded3af0bc1923ac5ec7` |
| fixture wet smoke / dry | `9e1864200975f3d758ec7a9d17cc9f8c3b24ac173e693ecf9363e35347b175be` / `32e6187da9e0a419097b771bdc64d50f230df4fd92e0f385a9059dfc02faf232` |
| fixture wet accept / dry | `bbb4b14850dbf95dd1a55dbffec68b6375d0fdfc90d6d5a855ec414ee7a05241` / `8399f13dfed5526bd5d1a55a7b01cbe156fd98d39155aba0707e7f1c9e791457` |
| model wet smoke | `263dc33738a7df99eba2f4c542597a774eef0c7fc64e56e957799e4a83d37ee2` |
| model wet accept | `fba8e2e31dc15857d177a28e163f02864c4a850a805831599f17b488c9de823c` |
| trace accept | `e7044ac932f715f8f7039a7fd6fa37ab4b7c086a3e8f9bb83a954f44b4f013b3` |
| compare accept / smoke | `4c27bfefa52f53641dbf5586662484fe3d5fd34fdb968047b24e51052cdc357a` / `fc403c05616efbda32cf9533be34b118c5f8d7221a7ce3857f11caf6be7850dc` |
| schedule-closure.json | `544642cac3b8d0f1c34e89e320ba2b7e5c2f1876e63952ad0a0776fca5efd400` |
| rtl-exactness.json | `4d5702e8d453c96c6e57c1f79d3aa46118b50cc7a1131dcb31d038054d1b25c2` |
| rtl cfg.hex | `ae144e16c2c2982c9e5a28d6ebe62c96c36ec77183d2c15cf32c7181420c616f` |

## Reproduce

```sh
python3 model/integration/selection_scan.py
python3 compiler/verify.py image model/integration/preset/Hell_s_Bells__e499f78d.image.bin
python3 model/integration/extract_preset_inputs.py
python3 model/integration/render_fixtures.py
python3 model/integration/run_model.py --sequence sxt025-smoke-v1
python3 model/integration/compare_integration.py --sequence sxt025-smoke-v1
python3 model/integration/run_model.py --sequence sxt025-accept-v1
python3 model/integration/compare_integration.py --sequence sxt025-accept-v1
python3 model/integration/schedule_closure.py --trace reports/sxt025/artifacts/trace__sxt025-accept-v1.json
python3 tools/run_sxt025_rtl.py --blocks 1024
python3 model/integration/negative_controls.py --sequence sxt025-accept-v1
python3 -m pytest tests/test_sxt025_integration.py
```

## Provenance / licensing

All files under `model/integration/`, `rtl/integration/`,
`tools/run_sxt025_rtl.py`, `tests/test_sxt025_integration.py` and
`reports/sxt025/` are original to this repository (Apache-2.0 per
`LICENSE`). The pinned GPL engine was imported at runtime only (fixture
renders + engine-getter extraction); Reverb1 structure is cited, not copied
(SXT-024 provenance carries). The committed WAVs are this project's own
renders of the loaded preset, not redistributed upstream content.
