# SXT-028f evidence record — Reverb 2 (sst-effects tank reverb): frozen fixed-point model, exact RTL, per-instance state; reference leg BLOCKED (no oracle host)

Branch: `feature/issue-58` · Issue: #58 (SXT-028f) · Parent: #21 (SXT-028) ·
Date: 2026-09-25

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz,
block size 32 (`oracle/manifest.json`). Algorithm authority:
`libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b/include/sst/effects/Reverb2.h`
(the Surge `Reverb2Effect` at this pin is a thin `SurgeSSTFXBase` wrapper
around `sst::effects::reverb2::Reverb2<SurgeFXConfig>`;
`src/common/dsp/Effect.cpp:79-80` instantiates it for `fxt_reverb2`).
Supporting pinned headers read and cited: the same sst-effects pin's
`EffectCore.h` and `effects-shared/WidthProvider.h`;
`libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96`
`BlockInterpolators.h` and `QuadratureOscillators.h`; the engine pin's
`src/common/dsp/effects/SurgeSSTFXAdapter.h`. Read + cited; **no source,
table or asset is copied into this repository**.

**Claim discipline.** This record advances exactly one claim: **(1) the RTL
matches the frozen fixed-point model exactly** (iverilog, demonstrated).
It does **NOT** advance **(2) model-vs-pinned-engine agreement** — that leg
is **BLOCKED / NOT_RUN** on this host (§3) — and it advances **no** claim
of kind **(3) "it sounds good"** (no human listening; #8/#9 remain
BLOCKED-on-human). It establishes no preset-support claim, no coverage
claim, no cost or fit claim, no FPGA/gf180mcu synthesis, timing, area or
hardware-playback claim, and it freezes no budget.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Frozen model ↔ RTL exact (incl. dual-instance) | **PASS** — 4 cases, 77,824 output samples, 160 per-sample tank checkpoints, 6,624 state fields | `rtl-exactness.json` |
| RTL negative controls live | **PASS** — 4 injected-defect mutants + 1 stale-revision control, all CONTROL-OK, each with a liveness predicate | `rtl-exactness.json` |
| Model-side negative controls live | **PASS** — 7/7 CONTROL-OK (the issue's five required + bypass + suspend) | `negative-controls/negative-controls.json` |
| Per-instance state (two concurrent instances) | **PASS** — disjoint regions, per-instance equality, pooled-region mutant FAILS | `rtl-exactness.json`, NC-D |
| Tails (present, decaying, dropped tail FAILs) | **PASS** — model-side declared-region tail gate | NC-B, `tests/test_sxt028f.py` |
| External-memory state + traffic | **PASS** (accounting) — 14,532,608 B/instance; 46 words/sample | `artifacts/buffer-requirement.json` |
| External-memory **fit** | **[PENDING-SXT-016] / not claimed** | §6 |
| Model ↔ pinned engine vs [PROPOSED] budgets | **BLOCKED (NOT_RUN)** — no oracle host in this environment | §3 |
| Fixture renders (SXT-012 policies, 3× determinism gate) | **BLOCKED (NOT_RUN)** — needs the oracle host | §1, §3 |
| Newly-enabled presets supported | **0** (honest delta) | §7 |

## 1. Inputs, applicability boundary (fail-closed), refusals

`tools/extract_reverb2_inputs.py` extracts the Reverb 2 chain inputs from
**committed pinned evidence**, not from raw `.fxp` bytes: the SXT-011
normalized graphs (`corpus/normalized/graphs.jsonl`) are the native
loader's post-migration readback at the engine pin, and the census blob
SHA-1 is re-verified against `corpus/census-v0.1/corpus-manifest.json` at
extraction time (a mismatch aborts).

Parameter order is `Reverb2.h:40-57` (`predelay, room_size, decay_time,
diffusion, buildup, modulation, lf_damping, hf_damping, width, mix`) and
every extracted value is range-checked against its declared `paramAt`
range (`Reverb2.h:152-197`); an out-of-range value is a refusal, never a
clamp. All three issue-named carriers pass that cross-check, which is
independent corroboration of the mapping:

| Preset (issue-named carrier) | slot | chain | complete-wet? |
|---|---|---|---|
| `patches_3rdparty/A.Liv/Keys/Grant Me....fxp` | send1 | Reverb 2 + Delay | **no** (fail-closed, below) |
| `patches_3rdparty/A.Liv/Leads/Novuo.fxp` | send1 | EQ + Chorus + Reverb 2 + Delay + **Distortion** | **no** — Distortion is an unlanded sibling class (SXT-028e, #57) |
| `patches_3rdparty/Aleksey Zhehanov/Strings/Harp.fxp` | global1 | EQ + Reverb 2 | **no** (fail-closed, below) |

Fail-closed reasons recorded in every emitted record
(`model/effects/fx_inputs/type-reverb 2-*.json`):

* **`rev2_predelay` temposync is UNRESOLVED.** The per-parameter temposync
  flag is not part of the SXT-011 normalized graph, and the `.fxp` bytes
  are external GPL assets this repository deliberately does not carry. The
  record emits `ts_predelay: null`, and `Reverb2Params` **raises** rather
  than default it to "not synced".
* **Determinism drift is `null`, not `0`.** The SXT-012 3× bit-identical
  render gate needs the oracle host; `drift_asserted: null` = NOT_RUN.
  (Independently: SXT-028c already recorded `Novuo.fxp` as REFUSED at
  extraction for drift ≠ 0 — `reports/SXT-028c/EVIDENCE.md` §1 — so that
  carrier is unlikely to survive the gate when it is run.)
* Unlanded sibling FX classes in the chain, non-default `fx_bypass`,
  non-zero `fx_disable`, and any modulation route whose destination names
  an FX parameter each refuse the preset.

Corpus inventory (`artifacts/carrier-ledger.json`, **inventory and
prioritisation only — NOT a support or coverage claim**, AGENTS.md): 708
presets carry an active Reverb 2 slot; **47 carry two or more Reverb 2
instances** (so the per-instance-state acceptance has real carriers, not
only synthetic ones); 130 are strict-FX-complete against the currently
landed class set; 300 carry at least one FX-destination modulation route
and are therefore outside the frozen scope.

## 2. Frozen fixed-point model

`model/effects/type-reverb 2/reverb2_model.py` (+ the freeze document
`model/effects/type-reverb 2/README.md`). Frozen words: audio and every
external buffer word Q10.21 s32; the `widthS`/`mix` ramps and the four tap
gains Q13.18 s32; the six coefficient ramps, the eight one-pole registers
and the LFO Q24.43 s64. The per-sample schedule mirrors
`Reverb2::processBlock` exactly: mono input fold → predelay ring
(read-before-write) → four input allpasses at `diffusion.v` → per tank
block {`x += in`, two allpasses at `buildup.v`, one-pole lowpass at
`clamp(hf.v, 0.01, 0.99)`, one-pole highpass at `clamp(lf.v, 0.01, 0.99)`,
`(int)(mod.v·lfos[b]·256)`, delay (two output taps, then the sub-sample
interpolated recirculation read, then the write), tap MACs, `x *= decay.v`}
→ `_state = x` → ramp steps → mid/side width → mix crossfade.

Two pinned behaviours are reproduced deliberately and are load-bearing:

* **The LF-damping ramp is never stepped** (`Reverb2.h:478-483` steps every
  other ramp). Its `.v` therefore holds the *previous* block's target for
  the whole block. `tests/test_sxt028f.py::test_lf_damping_ramp_is_never_stepped`
  pins it against the HF ramp (identical class, identical code path, but
  stepped), and the RTL control `mutant-lfdamp` steps it and FAILs.
* **Suspend does not clear the tank.** `suspendProcessing()` is
  `initialize()` is `setvars(true)`, which only rebuilds the tap gains and
  calls `calc_size(1.f)`; only the constructor zeroes buffers, ramps and
  `_state`. `Reverb2Model.suspend()` / `.initialize()` separate the two
  paths and NC-G flags a clearing mutant.

Declared deviations (bounded; they are absorbed by the model-vs-reference
budgets, which this record does **not** measure): engine float32 audio
arithmetic → Q10.21 (≤ 1 LSB-class per op, the same class the landed
Delay/EQ/Reverb1/Chorus models declare); the coefficient ramps, one-pole
registers and LFO held Q24.43 where the engine holds float32, with the
`/32` ramp increment rounded once; the four tap MACs accumulate exactly and
round once where the engine rounds each product to float32; the two
halvings truncate toward zero (the repo's frozen convention); control-rate
transcendentals evaluated in double and quantised once, with explicit
float32 rounding wherever the engine stores a `float`.

Constant inventory: **no opaque designed constants.** Every constant is an
engine literal cited to its pinned line (`0.5508`, `db60 = 0.001`, the
tap-time / allpass / delay millisecond tables, the four tap-gain literals,
the `0.7`/`0.8`/`0.2` parameter scalings, the `[0.01, 0.99]` damping
clamps, `ω = 2π·2⁻²/sr`) or a formula re-derivation (`db_to_linear`, the
0.25/0.75 `lipol_sse` smoothing). No successor to DR-0003 is required.

### Declared allocation profile (and why the bench profile is legal)

| Profile | predelay | allpass ×12 | delay ×4 | words/instance |
|---|---|---|---|---|
| `ENGINE_PROFILE` (default, what §6 accounts) | 1,536,000 | 131,072 | 131,072 | 3,633,152 |
| `HARNESS_PROFILE` (RTL bench only) | 16,384 | 4,096 | 16,384 | 131,072 |

The reduced bench profile exists so two instances fit the simulator. It is
legal **only** because (a) the model **refuses** (`ProfileRefusal`) any
configuration whose ring would alias a live tap — no silent reduction —
and (b) `test_alloc_profile_equivalence` runs the same stimulus under both
profiles and requires **identical output, tank state and transaction
counts**. Both sides of every exactness comparison run the same profile.

## 3. Model vs pinned engine — **NOT_RUN / BLOCKED**

**Status: BLOCKED. Reason: no oracle host in this environment**
(`ORACLE_SURGE_DIR` unset; no built surgepy; `oracle/manifest.json` names
the expected external checkout). No fixture was rendered, no comparison
was run, and **no `compare-*.json` is committed** — a verdict that did not
run must never look like a pass, and
`tests/test_sxt028f.py::test_model_vs_reference_leg_is_not_claimed`
enforces that absence.

Consequently this leaf reports **no** achieved max/rms/corr numbers
against the [PROPOSED] SXT-023 effect-slice budgets (max ≤ 8,192 LSB; rms
≤ −46 dBFS; corr ≥ 0.98), and it does not move the reference-budget
acceptance item. Those budgets are used **only** inside the model-side
controls of §5 as a *substitution detector* (model-vs-model), which is
stated in the control record's own `claim_scope`.

Mid-render patch-change/reset on the engine side is additionally BLOCKED
by the known surgepy embedding limitation already documented in
`reports/sxt-024/EVIDENCE.md` §3. Reset semantics are exercised exactly on
the RTL side (`prs-reset48-128` = bulk clear + constructor reset, the
engine's fx-rebuild path) and the distinct *suspend* semantics are pinned
model-side (§2, NC-G).

**Stop/escalate (per the issue's own clause):** the acceptance criterion is
NOT weakened to make this pass. The gap is bounded and named: the leaf
needs one oracle-host run (fixture render under SXT-012 policies with the
3× bit-identical gate, the temposync-flag readback, the drift assertion,
and the model-vs-engine comparison). Follow-up issue filed — see §9.

## 4. RTL vs frozen model — **EXACT** (iverilog 13.0)

`rtl/effects/type-reverb 2/tb_reverb2.sv` +
`tools/compare_rtl_model_reverb2.py` → `rtl-exactness.json`
(status **PASS**, model revision `1a20c239…`). Two instances behind
disjoint external regions. Audio-rate in the RTL: the six lipol
recurrences (including the pinned "LF never steps" quirk), the LFO
magic-circle recurrence, the predelay ring, twelve allpass rings, four
delay rings with the sub-sample modulated read, eight one-pole filters, the
modulation truncation, the four tap MACs, the decay multiply, the width
matrix and the mix crossfade. Control-plane (streamed, declared in the
model README): six ramp targets, the LFO `dr`/`di` and its control-rate
renormalisation constant, the `widthS`/`mix` RAW targets, eight tap times,
twelve allpass lengths, four delay lengths, the predelay tap.

Compared with **integer equality**: every per-instance output sample (O);
every per-sample tank checkpoint (X: post-input-allpass signal, then per
tank block the modulation integer and both output taps, then the tank
accumulator — four samples per captured block); every declared state
checkpoint (T: all ring indices, configured lengths and tap times, the
eight one-pole registers, the tank, all six ramp v/target pairs, the LFO
`(r, i)`, the `widthS`/`mix` targets, the predelay tap, the three
per-region additive hashes and the per-instance external read/write
counters); and the frozen-revision pin.

| Case | Blocks | Inst | Stimulus | Result |
|---|---|---|---|---|
| `prs-dual-128` | 128 | 2 | PRS, serially chained, disjoint regions | **EXACT** |
| `prs-reset48-128` | 128 | 2 | same + bulk clear and constructor reset at block 48 | **EXACT** |
| `prs-corners-96` | 96 | 2 | parameter corners (min room / zero modulation / bypassed mix / full damping vs. large room / full modulation / no damping) | **EXACT** |
| `prs-sweep-256` | 256 | 2 | block-rate parameter sweep (the only class in which the coefficient ramps carry a non-zero increment) | **EXACT** |

Totals: 77,824 output samples, 160 per-sample tank checkpoints, 92 state
checkpoints, 6,624 state fields — all equal, zero mismatches.

RTL mutant negative controls (each **must** FAIL, and each carries a
*liveness predicate* so a control the stimulus never exercises is reported
`CONTROL-VACUOUS`, never banked as a pass):

| Mutant | Defect | Liveness predicate | Result |
|---|---|---|---|
| `mutant-shared` | the two instances' external regions pooled into one | always live | **CONTROL-OK** |
| `mutant-lfdamp` | the LF-damping ramp is stepped per sample | ramp increment ≠ 0 (measured 1.24e9 Q24.43) | **CONTROL-OK** |
| `mutant-modtrunc` | the modulation `(int)` cast rounds instead of truncating toward zero | 65,160 samples with a non-zero sub-sample fraction | **CONTROL-OK** |
| `mutant-tapgain` | tap gain 1 perturbed by one Q13.18 LSB | all eight output taps read non-zero data | **CONTROL-OK** |
| `control-stale-revision` | trace pinned to a different model revision | always live | **CONTROL-OK** (refused, never PASS) |

The liveness record is committed as `mutant_carrier_exercise` in
`rtl-exactness.json`. It is not decoration: the first run of this harness
reported `mutant-lfdamp` and `mutant-tapgain` as **CONTROL-BROKEN** because
a constant-parameter, 64-block stimulus never moved a ramp and never let a
tap read non-zero data. The carrier case was lengthened and a parameter
sweep added until both predicates held.

**Per-instance state acceptance (issue #58):** two concurrent instances
keep independent histories — disjoint external regions, per-instance
integer equality on outputs and on the three per-region hashes, and the
pooled-region mutant demonstrably FAILS the dual-instance check. 47 corpus
presets carry two or more Reverb 2 slots (§1), so the acceptance is not
limited to synthetic dual-slot cases; those carriers cannot be *rendered*
here only because the reference leg is blocked (§3).

## 5. Negative controls (model-side; each must FAIL its target check)

`tools/reverb2_negative_controls.py` → `negative-controls/negative-controls.json`.
Baseline sanity first (the unmutated model passes its own checks), then:

| Control | Result |
|---|---|
| **NC-A** generic substitute (four feedback combs, no allpass diffusion, no damping, no predelay, no sub-sample read) | **CONTROL-OK** — FAILs the [PROPOSED] agreement budgets; labelled **ADAPTED**, excluded from original-preset coverage |
| **NC-B** dropped tail (render truncated at the tail offset, and tail region zeroed) | **CONTROL-OK** — both FAIL the declared-region tail gate that the full render passes |
| **NC-C** wrong order (two serial instances A→B vs B→A) | **CONTROL-OK** — not bit-identical and outside the budgets |
| **NC-D** shared instead of per-instance state (pooled external region) | **CONTROL-OK** — instance A's state and history change |
| **NC-E** stale stub (frozen-revision pin) | **CONTROL-OK** — refused by the exactness harness and by the test suite |
| **NC-F** bypass transparency (mix = 0 exact; injected mix leak detected) | **CONTROL-OK** |
| **NC-G** suspend must not clear the tank (pinned semantics) | **CONTROL-OK** — a clearing mutant is flagged |

**Claim scope of §5, stated in the artifact itself:** every comparison here
is *model-vs-model* — the frozen model is the reference. These controls
show the checks and the budget thresholds are live and that the listed
defects are detectable. They establish nothing about agreement with the
pinned engine (§3) and no sound claim.

## 6. External memory and traffic (SXT-015/016 conventions)

`tools/reverb2_buffer_report.py` → `artifacts/buffer-requirement.json`,
measured from the frozen model's own per-instance transaction counters and
cross-checked against the pinned structure:

* Per-instance external **writable** state: predelay 1,536,000 words +
  12 allpass rings × 131,072 + 4 delay rings × 131,072 = **3,633,152 ×
  32-bit words = 14,532,608 B = 13.859 MiB**. This confirms the SXT-015
  pinned entry for Reverb 2 **exactly**. It is by a wide margin the largest
  per-instance external resident of the effect classes landed so far
  (Chorus 1.00 MiB, Reverb 1 2.13 MiB, Delay 2.00 MiB).
* Traffic: **29 reads + 17 writes = 46 words/sample = 184 B/sample =
  8.83 MB/s per instance** at 48 kHz (1 predelay read/write; 12 allpass
  read/write; per delay 2 output taps + 2 interpolation reads + 1 write).
  Measured counters match the structural derivation exactly.
* On-chip small state ≈ **295 B/instance** (six ramps, eight one-pole
  registers, the LFO, the tank accumulator, two `lipol_sse` ramps, ring
  indices, configured lengths and tap times, counters and hashes). The wide
  products are combinational; the tap gains are frozen ROM.
* Long buffers are external **WRITABLE** memory; flash is never writable
  delay memory; all processing stays in-chip (plan section 3).

**Finding (recorded, not silently fixed): the SXT-015 per-sample traffic
row for Reverb 2 is an over-estimate.** The shared table
(`model/resources/fx_classes.py`) carries 40 reads / 18 writes; the
structure measured here is 29 reads / 17 writes. Editing that table is
SXT-015/016 scope, not this leaf's, and over-estimating traffic is
*conservative* for a budget, so no SXT-016/017 result is invalidated by
the discrepancy. It is recorded in `sxt015_reconciliation`
(`traffic_agreement: false`) and asserted by the test suite so it stays
visible rather than quietly reconciled.

**External-memory fit: [PENDING-SXT-016], NOT CLAIMED.**
`cyc_fxreverb2_frame` is still a placeholder
(`model/resources/params.py`), and SXT-017 profile v1 is **not frozen**
(#12: PR #109's cost closure found no candidate bundle meeting the budget
goal at any measured corner, STOP/ESCALATE fired, routed to an operator
decision). This leaf therefore supplies the residency and traffic inputs
that the freeze needs and makes **no** fit claim — exactly the disposition
the issue's SXT-017 callout requires.

## 7. Newly-enabled presets (honest delta)

**Supported stays 0.** The conjunction in `reports/coverage-v1/README.md`
still fails for every carrier at earlier gates: the model-vs-engine leg is
BLOCKED here (§3), the fidelity freeze (#12) is open and escalated, sibling
FX classes in the named carriers' chains are unlanded (Distortion,
SXT-028e), the voice stage is incomplete, and listening is BLOCKED-on-human
(#8/#9). What this leaf adds is the `fx:Reverb 2` **class** evidence of §4
and §6 — RTL-vs-model exactness and the external-memory accounting — plus
the fail-closed input records of §1. The issue's B4-scope upper bound (232
candidates) and the 708-carrier inventory of §1 are **not** support claims.

## 8. What this record does NOT establish

- Any model-vs-pinned-engine fidelity result, achieved budget number, or
  freeze (§3 is NOT_RUN/BLOCKED; SXT-017/#12 is escalated to an operator).
- Any preset-support, coverage, or musical-quality claim; no human
  listening has occurred (#8/#9). Essentiality remains UNVERIFIED — the
  issue records no SXT-014 ablation carrier for this algorithm.
- Any cost or fit claim: `cyc_fxreverb2_frame` is unpriced
  [PENDING-SXT-016].
- FPGA/gf180mcu synthesis, place-and-route, timing, power, area, or
  hardware playback. The RTL here is an **iverilog-simulated behavioural
  schedule**, version recorded in `rtl-exactness.json`; it is not
  synthesised and no synthesis claim is implied.
- Anything about sibling effect classes (Distortion SXT-028e, Conditioner
  SXT-028b, …), or about the open SXT-023 delay-semantics finding (#16).
- Repeatability of engine renders (none were made) or of hardware capture
  alignment (none exists).

## 9. Bounded gaps and follow-up

1. **F-028f-1 — oracle-host reference leg (BLOCKED).** Needs: the pinned
   surgepy build; the `rev2_predelay` temposync readback for the three
   carriers; the SXT-012 fixture renders (original + per-slot bypass +
   all-off dry, tails included) under the 3× bit-identical gate; the drift
   assertion; and `model`-vs-engine comparison against the [PROPOSED]
   budgets, with the declared-region wet tail gate (#93/#100). **Filed as
   #126** (same infra-gap class as #96 and #101); this leaf's model, RTL,
   controls and tooling are the inputs it needs.
2. **F-028f-2 — SXT-015 traffic row** (§6): 40/18 vs the measured 29/17,
   state bytes agree exactly. **Filed as #127**, routed to SXT-015/016
   scope; the disagreement stays asserted by
   `tests/test_sxt028f.py::test_buffer_requirement_record` until it is
   dispositioned there.

## 10. Reproduce

```sh
# anywhere with iverilog (RTL-vs-model exactness + RTL mutant controls)
IVERILOG=iverilog python3 tools/compare_rtl_model_reverb2.py     # ~3 min

# anywhere (model-side controls, buffer report, fail-closed extraction)
python3 tools/reverb2_negative_controls.py
python3 tools/reverb2_buffer_report.py
python3 tools/extract_reverb2_inputs.py --scan

# unit / integrity tests
python3 -m pytest tests/test_sxt028f.py -q
```

## 11. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`). The
Reverb 2 structure was read and cited from the pinned GPL-3.0-or-later
`sst-effects`, `sst-basic-blocks` and Surge trees, which stay external; no
Surge source, tables, presets or assets are committed here, and no preset
payload is read by any tool in this leaf (the corpus contributions are the
committed SXT-011 normalized graphs and the SXT-010 census hashes). No
distribution-license determination has been made for Surge-derived
material.
