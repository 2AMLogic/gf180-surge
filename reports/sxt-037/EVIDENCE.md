# SXT-037 evidence record — voice leaf: filter algorithm LP 12 dB

Branch: `loom/leaf-71-lp12` · Issue: #71 (SXT-037) · Date: 2026-09-22

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.sxt037-tap.ff8b4dba4` (patched oracle build; version string as reported
by the engine in every committed `bundle-*/meta.json`; see DR-0005), 48 kHz,
block size 32 / OS block 64 (`oracle/manifest.json`). LP 12 dB algorithm
authority: pinned `sst-filters` `FilterCoefficientMaker_Impl.h`
(`Coeff_SVF`, `Coeff_LP12`, `resoscale`, `Map2PoleResonance`, `clipscale`,
`boundFreq`, `ToCoupledForm`, `ToNormalizedLattice`, `FromDirect`),
`QuadFilterUnit_Impl.h` (`SVFLP12Aquad`, `IIR12CFCquad`, `IIR12Bquad`),
`QuadFilterUnit.h` (subtype→kernel table), and `SurgeVoice.cpp`
(cutoff/keytrack/FEG control arithmetic, per-voice FBP zero-init, per-block
C read-back) — read and cited, never copied.

**Claim discipline.** This record advances exactly two claims: (1) *the RTL
matches the frozen fixed-point model exactly* (iverilog-simulated;
demonstrated on every fixture including the stability corners), and (2) *the
model reproduces the pinned engine at the filter-stage boundary within
[PROPOSED] budgets* — measured, PENDING-FREEZE, with two recorded budget
findings (§3). It establishes **no** fidelity-policy freeze, **no**
preset-support claim, **no** musical-quality claim (no listening record),
and **no** FPGA/gf180mcu synthesis, timing, area, or hardware playback
claim. The RTL is an iverilog-simulated schedule, not synthesis-closed.

## Leaf scope as implemented

One algorithm (`fut_lp12`), **all three engine-declared subtypes** at the
pin: `st_Standard`(0)→`SVFLP12Aquad`, `st_Driven`(1)→`IIR12CFCquad`,
`st_Clean`(2)→`IIR12Bquad` (coefficients via `Coeff_SVF` /
`Coeff_LP12`+`ToCoupledForm` / `Coeff_LP12`+`ToNormalizedLattice`).
Observed corpus subtype inventory (graphs.jsonl, informational): 665 /
602 / 72. Declared parameter scope and fail-closed boundaries:
`model/voice/filter_lp12/README.md`.

## Carrier fixtures and the stage boundary (why taps)

The three issue-declared carriers are real normalized corpus presets whose
LP 12 dB instances cover two subtypes and the keytrack path:

| case | preset (census blob verified) | LP12 instance | params (cut / res / em / kt) |
|---|---|---|---|
| badnews | `Bluelight/Pads/Bad News.fxp` (`8c61a189…`) | unit 1, **Driven** | −2.40 / 0.0 / +30.0 / kt 1.0 (ktR 72) |
| rainy | `Bluelight/Pads/Rainy Day Dreamaway.fxp` (`13979de9…`) | unit 1, **Driven** | +37.09 / 0.014 / +30.0 / kt 1.0 (ktR 33) |
| t9 | `Emu/Drums/T9 Tom.fxp` (`314e3cc7…`) | unit 2, **Clean** | +47.61 / 0.0 / +39.44 / kt 0 |

No corpus preset inside the landed SXT-022 *voice* arithmetic
(`model/integration/selection-scan.json`, F-1) exercises any filter other
than Attacky's, and the carriers' voice graphs (multi-oscillator, noise,
LFO/mod routes, FX) are #48 (SXT-026a) scope. The leaf therefore compares
model vs engine **at the exact leaf boundary** — the filter unit's
input/output signals and its per-block coefficient plane — captured by the
ORACLE TAP INSTRUMENTATION (decision-records/0005): a read-only,
externally-patched build of the pinned tree. Nothing GPL-derived entered
this repository; every artifact embeds the neutrality proof below.

Corner cases (rendered through the same boundary, `setParamVal` on the
scene filter-unit parameters — the official host path): resonance
self-oscillation corner (`badnews-reso1`, reso→1.0), boundFreq clamp edges
(`badnews-cut-hi` cutoff→+96 ⇒ engine clamps +75; `badnews-cut-lo`
cutoff→−96 ⇒ clamps −55), the third subtype (`t9-substd`, unit-2 subtype
→Standard ⇒ SVF kernel), and the coefficient-reload path (`badnews-toggle`,
subtype Driven→Clean mid-render ⇒ engine `FBP` memset + `CM.Reset()`
+ `FromDirect` FirstRun). Sequence: `seq-notes-repeated-v1` (196,800
frames; same-pitch retriggers exercise per-instance state re-creation);
FAST-MODE smoke used `seq-lp12-smoke-v1` (≤4k active samples).

**Neutrality (decisive control).** `attacky-neutrality` (deterministic
preset class: drift 0, retrigger on): tapped vs untapped renders of the
same patched build are **bit-identical**
(`bundle-attacky-neutrality/meta.json`, `neutral: true`), and the patched
build's `render_fixture.py` render of Attacky (`e86f79af0a2a…`) equals a
fresh **unpatched-source** rebuild rendered on the same host (bit-identical
shas). The carriers themselves are SXT-012 nondeterministic-class presets
(drift/retrigger free phase), so per-carrier bit gates are not decisive and
are recorded as `engine_deterministic_same_case: false`; the model
consumes each instance's actual tapped signal, so the legs below are
unaffected by that class.

## 1. Frozen model (word lengths, op order)

Q10.21 signed 32-bit words (the SXT-022 universal word), round-half-up
products, `qdiv` only at coefficient rate, no run-time floating point.
Coefficient construction (double, quantized once — declared deviation
class), `FromDirect` smoothing (smooth 0.2, `blockSizeInv` 1/64, FirstRun),
per-sample `C[i] += dC[i]` reload orders, clipgain register position
(state multiply uses the PREVIOUS clipgain), per-instance registers
`R0/R1/Rclip` with the engine's zero-init (`Rclip` starts 0 ⇒ the first OS
sample of an instance seeds no state — a declared divergence from the
landed SXT-022 voice model, which initializes 1.0), per-instance state
never shared, and the per-block C read-back (`CM[u].C[i] =
get1f(fbq->FU[u].C[i], fbqi)`): all frozen in
[`model/voice/filter_lp12/README.md`](../../model/voice/filter_lp12/README.md)
and `filter_lp12_model.py`. Stability argument (pole radius `ρ² = a2 ≤ 1`
with the self-osc `alpha` clamp; clipgain contraction `Rclip ∈ [0.1, 1]`;
pinned `Q1 ≤ min(2, 2−1.52·F1)` for Standard) plus an empirical per-block
peak monitor (`stability_verdict`; saturation is UNSTABLE by definition).

## 2. RTL vs frozen model — EXACT

`rtl/voice/tb_lp12.sv` (iverilog `-g2012`), stimulus emitted by the frozen
model (declared control-plane boundary: block-start `C[8]`/`dC[8]` +
subtype + reset flags streamed; inputs as Q10.21 words). Integer equality
at every output sample and every declared checkpoint (end-of-block
`R0, R1, Rclip, C[8]`):

| case | samples | checkpoints | state fields | verdict |
|---|---|---|---|---|
| badnews | 124,416 | 1,944 | 23,328 | **PASS (0 mismatches)** |
| rainy | 124,416 | 1,944 | 23,328 | **PASS** |
| t9 | 217,472 | 3,398 | 40,776 | **PASS** |
| badnews-reso1 | 124,416 | 1,944 | 23,328 | **PASS** |
| badnews-cut-hi | 124,416 | 1,944 | 23,328 | **PASS** |
| badnews-cut-lo | 124,416 | 1,944 | 23,328 | **PASS** |
| t9-substd | 217,472 | 3,398 | 40,776 | **PASS** |
| badnews-toggle | 130,560 | 2,040 | 24,480 | **PASS** |

Artifacts: `artifacts/rtl-*.json` (verdicts), `artifacts/bundle-*/`
(stimulus sources), `artifacts/model-trace-*.json.gz` (three representative
full traces). The toggle case includes the mid-render subtype change
(reset flag + `FromDirect` FirstRun) and quad-lane rotation (per-instance
state per lane; the stimulated instance carries all subtype transitions).
The self-osc and clamp corners run the same exact RTL schedule.

## 3. Model vs pinned engine — [PROPOSED] budgets, achieved numbers

Two budget findings are recorded (marked ★); per AGENTS.md/SXT-013 rules
they are recorded, not tuned away:

- **★ L1 absolute-LSB budget is mis-scaled across coefficient roles.**
  The proposed `max|ΔC| ≤ 16 LSB` holds for roles of order-1 scale but is
  uninformative for `C5 (= c2)` of the coupled form, which reaches ~10.0
  and divides by the pole half-angle `ai` (~5e-3 at band edges), and for
  the near-clamp regions where `1−cosi²` loses precision. A scale-relative
  budget (e.g. `|ΔC|/max(1,|C|)`) is the finding for the SXT-013 freeze.
- **★ The stage-level spectral-correlation sub-budget (≥0.999) is
  mis-scaled.** The L2b attribution legs (below) hold the *kernel* error at
  −76 to −98 dB relative to the engine peak while the same leg scores
  0.95–0.99 on log-magnitude spectral correlation: the metric is dominated
  by the sparse spectrum of a filtered voice signal, not by error
  magnitude. A relative-RMS criterion is the finding for the freeze.

### L2a primary leg — model (own coefficients) vs engine filter output

Achieved on the stimulated instance (max/rms in Q10.21 LSB; dB relative to
the engine output peak; `spec` = the proposed spectral-correlation metric):

| case | L2a max (≤4096) | L2a rms (≤256) | dB rel peak | spec (≥0.999★) | model peak (bounded) |
|---|---|---|---|---|---|
| badnews | **799 PASS** | 269.2 (marginal miss) | −53.4 | 0.9514 ★ | 5,174,757 STABLE |
| rainy | **626 PASS** | **87.2 PASS** | −81.1 | 0.9944 ★ | 8,011,345 STABLE |
| t9 | **517 PASS** | **161.5 PASS** | −81.6 | 0.9960 ★ | 8,879,424 STABLE |
| badnews-reso1 (corner) | 1,684,636 | 407,812 | −8.0 | 0.9875 ★ | 68,478,654 STABLE (5.2% of s32) |
| badnews-cut-hi (corner) | **561 PASS** | **40.9 PASS** | −75.3 | 0.9592 ★ | 236,992 STABLE |
| badnews-cut-lo (corner) | **359 PASS** | **111.0 PASS** | −21.9 | 0.6992 ★ | 11,803,601 STABLE |
| t9-substd (corner) | 59,439 | 20,836 | −40.3 | 0.9900 ★ | 2,166,111 STABLE |
| badnews-toggle (reload) | **802 PASS** | **187.2 PASS** | −56.6 | 0.9408 ★ | 5,443,043 STABLE |

Reading (honest):

- **Primary carriers PASS the max/rms budgets** (badnews rms 269.2 vs 256
  is a marginal recorded miss); the self-osc corner and the Standard-at-
  deep-sweep corner exceed per-sample budgets by the physics of ρ≈1 poles
  (quantization-level coefficient differences integrate over seconds) —
  both legs remain **bounded and stable** (model peak ≤ 5.2% of s32;
  engine outputs finite and bounded), which is the corner's declared
  criterion.
- **L2b attribution legs** (model kernel driven by the ENGINE's own
  quantized coefficients) isolate the kernel: badnews max 147 / rms 19.1
  (−76.3 dB); rainy max 275 / rms 40.4 (−87.8 dB); t9 max 340 / rms 23.3
  (−98.4 dB); reso1 corner max 101,880 / rms 18,460 (−34.9 dB, the ρ≈1
  sensitivity). The gap between L2b and L2a attributes the primary-carrier
  error to coefficient-plane construction (float32/double mix vs frozen
  Q10.21 construction), not to the audio path.
- `badnews-cut-lo` (cutoff clamped to −55 st) is near-static audio; its
  spectral-correlation value (0.699) is the metric artifact of §3★ in the
  extreme, while max/rms PASS tightly.

Per-case verdicts against the a-priori proposals:
`artifacts/compare-*.json` — **FAIL against proposed budgets** on every
case (driven by the two ★ mis-scaled sub-budgets), with all achieved
numbers recorded above. Per the fidelity policy this is input to the
SXT-013 freeze, NOT a fidelity verdict in either direction, and NOT
silently relaxed.

## 4. Stability corners — both legs

- **Engine leg:** finite, bounded outputs at reso→1.0 (self-osc corner:
  bounded Driven oscillation via the clipgain register), and at both
  boundFreq clamp edges (engine render peaks recorded in each
  `bundle-*/meta.json`).
- **Model leg:** bounded (largest state peak 68,478,654 LSB = 5.2% of the
  s32 range at reso1) with `stability_verdict = STABLE` on every case
  (`compare-*.json`).
- **Detected-not-silent control:** NC-D (below) proves the monitor flags
  the same drive without the clipgain contraction.

## 5. Costs vs SXT-016 probes (divergences recorded, not reconciled away)

Measured schedule cost of the landed kernels: **11 MAC/sample** (Driven
CFC, Standard SVF), **15 MAC/sample** (Clean normalized lattice), per
instance, one 32×32 MAC per cycle (A-DSP-1c), plus ~8 coefficient adds and
block-rate coefficient construction (64-sample period) — measured from the
frozen schedule (`run-*/model_trace.json`) and cross-checked against the
RTL `qmul_count`. SXT-016 planning rows:
`probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip` = **32 cycles/sample**
(the issue's 1,536,000 cyc/frame = 32 × 48,000), `filter_unit_state_bytes`
= 256 B. Recorded divergences: the probe prices the SVF-TDF2 kernel class
at 24-bit audio words and a different op mix — the landed LP12 kernels land
inside its envelope (11–15 MAC/sample < 32 cyc/sample); state is 640 bits
per instance here (3×32-bit registers + 16×32-bit coefficient/state words,
32-bit words) vs the probe's 192-bit register-only 24-bit accounting.
Per the issue's cost note, per-type kernel mapping and corner costs are
confirmed at implementation.

## 6. Negative controls (each must FAIL the check it targets)

`artifacts/negative-controls.txt` / `.json` (exit 0 = all controls failed
their checks):

| Control | Result |
|---|---|
| NC-A wrong-subtype: Driven carriers driven through the Clean path; Clean carrier through Driven | **CONTROL-OK** — L2 budgets FAIL by 100×–3000× (max 121,506 / 974,296 / 1,872,304 LSB) |
| NC-B wrong-algorithm: LP 24 dB/Driven (pinned `Coeff_LP24`+`IIR24CFC` structure) substituted for LP 12 dB | **CONTROL-OK** — budgets FAIL (max 124,955 LSB) |
| NC-C applicability boundary: reso > 1.0, subtype 3, subtype 9 | **CONTROL-OK** — all REFUSED (exit-2 class); out-of-scope never silently clamped |
| NC-D instability detected, not silent: clipgain-disabled control kernel at the reso→1 corner | **CONTROL-OK** — monitor reports **UNSTABLE** (saturation reached); frozen model on the same drive: STABLE |
| NC-E RTL mutant: `lp12_broken_mutant.sv` (single-constant mutation of the qmul round-half-up bias) | **CONTROL-OK** — exactness FAILs (31 mismatches in block 0) |

## 7. Recovery basis / supported delta (honest)

The issue attributes 70 slate-basis presets (essentiality UNVERIFIED) and
515 corpus B4-predicted presets to this leaf's requirement. What this leaf
**establishes** is the filter algorithm leaf itself: RTL-vs-model EXACT
(§2), model-vs-engine measured at the filter-stage boundary with recorded
budget findings (§3), stability corners on both legs (§4), and the
applicability boundary fail-closed (NC-C). What it does **not** establish:
any complete-preset render (the carriers' voice graphs require #48), any
wet-path integration (SXT-025 boundary unchanged), any preset-support or
fidelity claim (coverage stays gated on #12/#48). Coverage-table entry
`filter_type:LP 12 dB`: `rtl_vs_model: PASS`,
`model_vs_reference: NO_VERDICT` (PENDING-FREEZE budgets, findings
recorded), `fixture_verified_paths: []` (stage-level evidence only — no
preset is counted as supported by this leaf), with the three carriers and
corners recorded under stage-verified boundary cases.

## 8. Licensing / provenance

All files under `model/voice/filter_lp12/`, `rtl/voice/tb_lp12.sv`,
`rtl/voice/lp12_broken_mutant.sv`, `tools/*lp12*`, `tools/render_lp12_reference.py`,
`tools/compare_lp12_model.py` and `reports/sxt-037/` are original to this
repository (Apache-2.0 per `LICENSE`). Engine structure is cited from the
pinned GPL-3.0-or-later tree; the oracle tap instrumentation (DR-0005)
lives entirely outside this repository (patch script sha256
`0712926beb62651e50f3e5ccd39cec0586e20244077f25b6427ff1ce0a5cfbad`); no
Surge source, tables, presets, or assets are copied into this repository.

## 9. What this record does NOT establish

- Any fidelity policy or frozen budget (all §3 budgets are proposals with
  recorded findings; SXT-013 owns the freeze).
- Any preset-support, preset-quality, or complete-wet-preset claim; no
  human listening has occurred; `fixture_verified_paths` is empty by design.
- Any FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback result; the RTL is an iverilog-simulated schedule.
- The carriers' full voice graphs (SXT-026a/#48), the SVF/other filter
  types' own leaves (SXT-049+), effects leaves (#21/SXT-028).

## 10. Reproduce (oracle host for §3 legs; local for §2)

```sh
# reference bundles + taps (oracle host, externally patched pinned build):
python3 tools/render_lp12_reference.py --out-dir reports/sxt-037/artifacts \
    --cases badnews,rainy,t9,badnews-reso1,badnews-cut-hi,badnews-cut-lo,t9-substd,badnews-toggle,attacky-neutrality
# model legs + RTL stimulus (per case):
python3 model/voice/filter_lp12/run_filter_leg.py \
    --bundle reports/sxt-037/artifacts/bundle-badnews --out-dir /tmp/run-badnews
# RTL exactness:
python3 tools/compare_rtl_model_lp12.py --run-dir /tmp/run-badnews
# budget verdicts:
python3 tools/compare_lp12_model.py --traces /tmp/run-*/model_trace.json \
    --out-dir reports/sxt-037/artifacts
# negative controls (needs the bundles + iverilog for NC-E):
python3 tools/lp12_negative_controls.py
pytest tests/test_sxt037_lp12.py
```
