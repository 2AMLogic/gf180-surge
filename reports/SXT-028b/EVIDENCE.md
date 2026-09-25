# SXT-028b evidence record — Conditioner (ConditionerEffect): frozen fixed model, exact RTL, reference leg BLOCKED

Issue: #54 (SXT-028b) · Epic: #3 · Parent: #21 (SXT-028) · Date: 2026-09-25

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz,
block size 32 (`oracle/manifest.json`). Algorithm authority: the pinned
source files listed in `model/effects/type-conditioner/README.md`. They
were read at the pinned commits (fetched from raw.githubusercontent.com on
this host, 2026-09-25) and cited; nothing was copied.

**Claim discipline.** This record establishes one claim:

- **(1) RTL == frozen fixed-point model, exactly.** Demonstrated with
  iverilog on synthetic stimuli and seven parameter corners.

It does **not** establish:

- **(2) Model vs. pinned engine.** BLOCKED: no oracle on this host.
- **(3) Musical quality.** No listening record exists.

It also makes no preset-support claim, no FPGA or gf180mcu synthesis,
timing, area or hardware claim, and freezes no budget. Essentiality is
UNVERIFIED: listening is pending (#9).

## Headline results

| Acceptance item (issue #54) | Status | Evidence |
|---|---|---|
| Fixed-model/RTL equality | **PASS** | `rtl-exactness.json`: 4 cases, 2 instances each, 344 blocks, 44,032 output samples + 23,392 checkpoint fields, 0 mismatches, revision pin OK |
| Reference budgets [PROPOSED, not frozen] | **BLOCKED** | No oracle checkout or surgepy on this host (§3). No budget is proposed from data, none is frozen, and nothing is claimed. |
| Per-instance state (dual-slot) | **PASS** (model and RTL) | RTL: `dual-lifecycle` exact per instance; the pooled-state RTL mutant FAILs. Model: NC-2. |
| Tails (span, patch change mid-tail, reset/panic, dropped tail FAILs) | **PASS** (claim 1 scope) | The span is declared from source (99 `process()` blocks plus the control-only transition). It is covered exactly in RTL, with suspend and fresh re-spawn mid-tail; the dropped-tail control FAILs (§4). The reference tail leg is BLOCKED. |
| External-memory traffic / residency | **PASS** (leaf measurement); aggregate **[PENDING-SXT-016]** | `artifacts/buffer-requirement.json`: 2,444 B on-chip per instance, 0 external bytes and 0 external traffic, 3R+3W state accesses per sample |
| Negative controls live | **PASS** (12 of 12 fail their checks) | 7 model-level (`negative-controls/`) + 5 RTL-level (`rtl-exactness.json` → `controls`) |
| Fail-closed input extraction (`fx_inputs/type-conditioner-*.json`) | **NOT_RUN** | `tools/extract_conditioner_inputs.py` is an oracle-host tool; its pure logic is unit-tested. No output files exist. |

Coverage is reported separately from agreement. The RTL cases exercise:

- 358 `process()` instance-blocks and 42 control-only instance-blocks
  (11 + 11 after the first tail; 20 on instance 1 after its fresh
  re-spawn with no input present)
- 1 engine suspend and 1 fresh re-spawn, both mid-tail
- 326 instance-blocks under gain reduction, down to a minimum gain of 0.2246
- all three EQ/HP stages active in at least one instance
- side low-cut at +70 st, where ω > π and `coeff_HP` zeroes S
- every param at its min and at its max, plus the loader defaults
- the stored values of all four fixture presets

This coverage does not include parameter modulation (out of frozen scope),
temposync (the effect has no temposync parameter), or any
model-vs-reference agreement.

## 1. Pinned-source findings (recorded, not silently absorbed)

1. **No gate, no LFO.** The issue text ("gate/compressor/LFO", "shared
   LFO", `process_block`) comes from `tools/generate_effect_leaves.py`.
   The pinned `ConditionerEffect` is a bass/treble peaking EQ → M/S side
   high-pass and width → balance/threshold pregain → 128-sample look-ahead
   limiter → output gain. `a_rate`/`r_rate` are dead members. The pinned
   source is the authority.
2. **The detector reads a fixed leaf.** `la = lamax[lookahead - 2]` reads
   slot 126. The 7-level max tree built in `lamax[128..254]` is never read.
   The detector therefore sees one sample in every 128 (whichever sample
   lands at `bufpos == 126`) and holds it for 128 samples; peaks elsewhere
   in the cycle never reduce gain. The model and RTL reproduce this
   exactly. A windowed-max "fix" fails exactness (NC-7).
3. **Lifecycle.**
   - Patch load re-spawns every FX (`SurgeSynthesizerIO.cpp` →
     `loadFx(false, true)`), so everything restarts fresh.
   - `stopSound()` → `suspend()` → `init()` clears only the limiter state.
     Biquad registers and lags, the lipol ramps and the ringout counter
     survive.
   - Both paths are modeled and exercised in RTL.
4. **Ring-out.** `get_ringout_decay() = 100`. After the last
   input-present block the engine runs 99 more `process()` blocks. Then
   `process_only_control()` takes over: audio passes through untouched and
   the envelope relaxes toward `la = 1`. When input resumes, the ring
   first emits the content it held when processing stopped (reproduced).
5. **Reciprocal.** `process()` uses `mech::rcp` (SSE approximate).
   `process_only_control()` uses an exact `1.f/x`. The model uses an exact
   reciprocal for both. This is the largest declared deviation (§3).
6. **SXT-015 note.** `model/resources/fx_classes.py` justifies the
   Conditioner placeholder with "no delay line". There is a 1 KiB
   look-ahead line. The classification (on-chip, 0 external traffic) and
   the 8,192 B conservative placeholder both still hold against the
   measured 2,444 B.

## 2. Frozen fixed-point model

Files:

- `model/effects/type-conditioner/conditioner_model.py`: `model_revision()`
  is the sha256 of the file.
- `model/effects/type-conditioner/README.md`: word lengths, state layout,
  lifecycle table, deviations.

Formats:

- Audio Q10.21.
- Ramps Q13.18.
- Q24.43 for the biquad coefficients, lags and TDF2 registers; the
  envelope trackers; the gain; and the squared-peak leaves.

The shared `delay_model.Biquad` / `Lipol` classes are reused unchanged.
Attack and release are computed by an exact float32 emulation of the
engine's chain, cross-checked against numpy float32.

## 3. Model vs pinned engine: BLOCKED

- **Why BLOCKED.** This host has no pinned Surge checkout
  (`oracle/manifest.json` expects `ORACLE_SURGE_DIR`) and no surgepy. No
  fixture was rendered, and no extraction or comparison ran.
- **Why the committed ablation renders cannot substitute.** The SXT-014
  Doomsday tree (`reports/sxt-014/ablations/doomsday/`) has a
  bypass-slot06 render, which in principle is the Conditioner's input
  (global2 is Off). But the renders are **mono `(L+R)/2` int16**. The
  Conditioner's width/balance/M/S stages and its `max(|L|,|R|)` detector
  are stereo-dependent, and the limiter is nonlinear, so the stereo input
  cannot be reconstructed. Feeding a mono downmix and comparing would test
  a different signal, so it was **not** done and nothing is reported from
  it.
- **Unmeasured deviations, largest first:**
  1. `mech::rcp` → exact reciprocal (~2⁻¹² relative class). This may
     offset even unity gain.
  2. `sqrtf` → exact integer square root.
  3. M/S truncation.
  4. The double-precision control plane.

  **No budget for this leaf may freeze** (SXT-017, #12) until the `rcp`
  deviation is measured on the oracle, or `rcp` is reproduced bit-exactly.
- **Oracle-host plan** (the path that turns this leg from BLOCKED to
  measured):
  1. Run `tools/extract_conditioner_inputs.py`.
  2. Render stereo float32 wet/dry fixture buses for the Conditioner slot
     on seq-notes-coverage-v1 and seq-poly-8-v1.
  3. Drive the model through `process_ringout` with the engine's
     input-present flags.
  4. Compare with the shared comparator, including its tail gate.

  **Fixture candidates:**
  - **Doomsday** (global1; EQ/Reverb1/Delay upstream): Delay is in flight,
    and the open SXT-023 delay-budget finding applies to the input bus.
  - **Piercing** (Chorus → Conditioner in global1 → global2): Chorus has
    landed.
  - **AOE** (ains1 Conditioner, then send1 Delay).
  - **Computer Language 1** (ains1 only).

  The fixture-bus approach, which captures the Conditioner's own stereo
  input, isolates this leaf from the upstream budgets.

## 4. RTL vs frozen model: EXACT (iverilog)

**Setup.** The testbench is `rtl/effects/type-conditioner/tb_conditioner.sv`,
the harness is `tools/compare_rtl_model_conditioner.py`, and the record is
`rtl-exactness.json` (Icarus Verilog 13.0). The harness compares every
output sample and every checkpoint field with integer equality:

- `bufpos`, the envelope trackers and gain
- the 4 lipol cur/tgt pairs
- 15 biquad lags and 6 TDF2 registers
- a position-weighted hash over the ring and leaves

It also enforces the frozen-model revision pin and, where a case declares
one, tail coverage.

| Case | Instances / params | Blocks | Result |
|---|---|---|---|
| dual-lifecycle | Doomsday stored values + SYNTH_B (all stages on, HP 12 st, off-centre balance) | 200 | PASS: input present 0–39 and 150–169; tail `process()` blocks 40–138; control-only 139–149 (both instances); resume at 150 after control-only; block 180 **suspend (panic) on inst0, fresh re-spawn (patch change) on inst1, both mid-tail**; tail coverage 200 ≥ 140 required |
| corners-0 | loader defaults + all-min | 48 | PASS |
| corners-1 | all-max (HP at +70 st, ω > π) + AOE | 48 | PASS |
| corners-2 | Computer Language 1 + Piercing | 48 | PASS |

**Fixture-value corners.** These come from `corpus/normalized/graphs.jsonl`,
which is native-loader normalized and rounded to 6 decimals. The census
blob SHA-1 is re-verified and matches the issue's prefixes. The
`deactivated` flags are **ASSUMED** to be the engine defaults, because
graphs.jsonl does not export them. That is sufficient for claim 1; it is
not an extraction.

**Bench bugs found and fixed.** An earlier draft of this bench, and of its
harness, never passed. Three causes were found:

- **iverilog `inout` bug.** Iverilog 13 writes an array element passed to
  a task `inout` port back to the wrong element. Instance 0 reported
  instance 1's lipol targets.
- **Wrong shift count.** The Q24.43 × Q10.21 product was shifted by 22
  instead of 43.
- **Wrong saturation.** Saturation was symmetric, but `qmath.sat` is
  asymmetric.

The rewritten bench avoids array-element task ports entirely; the header
comment records why.

## 5. Negative controls (each must FAIL the check it targets)

Every control below failed its check. In each case the matching positive
control passes the same check, so no check is vacuous.

| # | Control | Check it targets | Result |
|---|---|---|---|
| NC-1 | serial A→B vs B→A (permute pattern) | order-sensitive exactness | FAIL (unpermuted passes) |
| NC-2 | two instances pooled into one state | dual-instance exactness | FAIL for both instances (independent instances pass) |
| NC-3 | generic instantaneous limiter, labeled ADAPTED | original-preset coverage gate + exactness | REFUSED by the gate and fails exactness; the frozen model is admitted; the wet reference is retained byte-identical |
| NC-4 | render truncated 4 blocks into the tail | tail coverage | FAIL (44 < 140 blocks); the full render passes; the look-ahead drain is non-zero |
| NC-5 | trace with a stale revision word | revision pin | REFUSED, although the data are identical (the live revision passes) |
| NC-6 | scheduler that stops `process()` when input stops | exactness over the tail | FAIL |
| NC-7 | windowed-max detector in place of the fixed leaf 126 | exactness | FAIL |
| RTL | `tb_conditioner_mutant_shared.sv` (ring/leaves/bufpos/envelope pooled into instance 0) | dual-instance exactness | FAIL (14,378 mismatches) |
| RTL | `tb_conditioner_mutant_nolimiter.sv` (gain forced to 1.0) | exactness | FAIL (10,685 mismatches) |
| RTL | slot contents permuted (params swapped between instances) | exactness | FAIL (27,473 mismatches) |
| RTL | stale revision word | revision pin | REFUSED |
| RTL | run stopped 20 blocks before the required tail span | tail coverage | FAIL, with **0 data mismatches** (the check really is the tail gate) |

## 6. State residency and external-memory traffic

`tools/conditioner_buffer_report.py` writes
`artifacts/buffer-requirement.json` from the frozen model's transaction
counters.

- **Per-instance state.** 19,551 bits (2,444 B). Of that, 2,048 B is the
  writable look-ahead ring plus leaves.
- **Residency.** This is far below the 65,536 B external threshold, so the
  state is **on-chip**, with **0 external bytes and 0 external traffic**.
  Flash is not used.
- **Traffic.** State-memory traffic is 3 reads + 3 writes per processed
  sample and none in control-only blocks.
- **Instances.** Each additional instance is a disjoint copy.
- **Reconciliation with SXT-015.** The 8,192 B placeholder is
  conservative, and the external classification agrees.
- **Profile aggregate.** [PENDING-SXT-016].

This is accounting only; it makes no area or placement claim.

## 7. Newly-enabled presets (unchanged honest delta)

`reports/sxt-028/leaves/SXT-028b/newly-enabled.json` counts:

- 175 strict-FX-complete presets
- 365 B4-scope candidates (an upper bound)

This is FX-scope accounting only. **Nothing moves to "supported"**,
because the reference leg is BLOCKED, and voice, scheduling and the
profile freeze also gate support.

## 8. What this record does NOT establish

- Agreement with the pinned engine on any preset. BLOCKED.
- Any frozen or even data-proposed budget.
- That `rcp`, `sqrtf` or the float32 audio path are within any tolerance.
- That the `deactivated` flags of the fixture presets equal the assumed
  defaults.
- Any claim about modulation into Conditioner parameters.
- Musical usefulness, preset support, synthesis, timing, area, or
  hardware playback.

## 9. Reproduce

```sh
# anywhere (model-side): negative controls + state report
python3 tools/conditioner_negative_controls.py
python3 tools/conditioner_buffer_report.py
# anywhere with iverilog: RTL exactness + RTL controls (~10 min)
python3 tools/compare_rtl_model_conditioner.py
# unit / record-integrity tests (live RTL smoke test skips NOT_RUN w/o iverilog)
python3 -m pytest tests/test_sxt028b.py -q
# oracle host only (NOT_RUN here): fail-closed extraction
tools/extract_conditioner_inputs.py
```

## 10. Provenance and licensing

Everything under `model/effects/type-conditioner/`,
`rtl/effects/type-conditioner/`, and the `tools/*conditioner*` scripts
listed below is original to this repository (Apache-2.0):

- `tools/compare_rtl_model_conditioner.py`
- `tools/conditioner_negative_controls.py`
- `tools/conditioner_buffer_report.py`
- `tools/conditioner_corners.py`
- `tools/extract_conditioner_inputs.py`

No Surge or SST source, tables, assets, preset payloads, or renders are
committed. The constants are cited literals, and the formulas are
re-derived from the pinned sources. No distribution-license determination
has been made.
