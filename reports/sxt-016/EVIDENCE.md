# SXT-016 — Representative cost probes: evidence record (issue #11)

Package: `probes/` (this branch). Outputs:
`reports/sxt-016/probes/` (76 validated JSON records + `SUMMARY.md`),
`reports/sxt-016/worked-bundles.json`,
`reports/sxt-016/negative-control/nc-underspecified-record.json`.

**Standing disclaimer.** Every number here is a PLANNING ESTIMATE against
NAMED assumptions (assumption ids A-* defined in `probes/common.py` and
embedded per record). These are experiments, not production blocks. **No
gf180mcu synthesis, place-and-route, timing signoff, or layout has been
run; nothing here measures any technology.** No fidelity, support,
preset-quality, or hardware-playback claim is made or advanced. State RAM
is reported in bits, separately from logic (logic = normalized op counts,
PDK-neutral relative estimates).

## 1. Issue-#11 acceptance mapping

| # | Acceptance item (issue #11) | Status | Evidence |
|---|---|---|---|
| 1 | Each probe names its technology assumption, clock, and memory implementation | **PASS** | Every emitted record carries `clock_hz_candidates` (full candidate set, A-CLK), `word_lengths`, `memory_model` (on-chip AND external, with text), non-empty `assumptions` and `structure_citations`. Enforcement is mechanical: `probes/validate.py` refuses non-conforming records at write time; demonstrated live by the negative control. |
| 2 | Delay/EQ/Reverb1 kernels include buffer bandwidth to external memory, not just logic cost | **PASS** | Delay: on-chip-line bound + E1/E2/E3 external-line variants with logical-vs-physical traffic reconciliation (SXT-015 6r+2w logical; 24r+2w naive physical; ~2r+2w with the named A-EXT-BUF window cache), latency-tolerance and tempo-sync re-seek analysis. Reverb1: buffer traffic classes (16 scattered composite-tap r/w + predelay 1r/1w = 136 B/frame; matches SXT-015 17r/17w), burst-efficiency 1-word at 64 B stride, latency-bound verdict. EQ: structurally ZERO external traffic (no delay line — SXT-015 `fx_classes._NO_LONG_BUFFER` citation), stated rather than invented. |
| 3 | State RAM reported separately from logic area | **PASS** | Every record: `state_ram_bits` (+ per-component breakdown) beside `ops` (op counts by class and width). Bundles: `state_ram_bits_total` as a separate Pareto column, never merged with cycles. |
| 4 | Estimates reproducible from committed scripts | **PASS** | `python3 probes/run_all.py` regenerates all outputs; rerun verified byte-identical (determinism check in-session; `tests/test_sxt016_probes.py` asserts record-level determinism). No timestamps; sorted keys; integer op counting; the two float analyses use fixed inputs and fixed iteration counts. |
| 5 | Negative control: an unstated clock/memory probe fails review and is excluded from SXT-017 inputs | **PASS** | `reports/sxt-016/negative-control/nc-underspecified-record.json`: a deliberately under-specified record (invented 70 MHz clock, no word lengths, no memory model) is REJECTED with 10 error classes and `write_record` REFUSES to emit it. Exclusion is structural: invalid records cannot reach `reports/sxt-016/probes/`. |

Regression safety: `tests/test_sxt016_probes.py` (9 tests) — validation
positive/negative, emission refusal, byte-identical rerun, assumptions
present on every record, pinned-structure > adaptation-candidate cost
sanity, stability guard-band sanity, fixture event-model reconciliation
(8 coincident), closure-formula arithmetic.

## 2. Worked bundles (acceptance): does a candidate budget close?

Complete-patch worst case per output frame for the two SXT-015 worked
presets plus a synthetic bundle feature-complete for the probe-covered
classes (`probes/worked_bundle.py`; structure from
`model/resources/accounting.py`, cycle values from validated probe
records, memory model E1-conservative):

| Bundle | xMult | total cyc/frame | @48M | @96M | @192M | @480M | RAM bits | ext B/frame |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| july | M18 | 16230 | OVERFLOW (1623%) | OVERFLOW (811%) | OVERFLOW (406%) | OVERFLOW (162%) | 26097824 | 24 |
| july | M32 | 11581 | OVERFLOW (1158%) | OVERFLOW (579%) | OVERFLOW (290%) | OVERFLOW (116%) | 26097824 | 24 |
| supersaw | M18 | 550845 | OVERFLOW (55085%) | OVERFLOW (27542%) | OVERFLOW (13771%) | OVERFLOW (5508%) | 125778880 | 252 |
| supersaw | M32 | 279085 | OVERFLOW (27908%) | OVERFLOW (13954%) | OVERFLOW (6977%) | OVERFLOW (2791%) | 125778880 | 252 |
| covered_worst_synth | M18 | 282890 | OVERFLOW (28289%) | OVERFLOW (14144%) | OVERFLOW (7072%) | OVERFLOW (2829%) | 215923 | 168 |
| covered_worst_synth | M32 | 143862 | OVERFLOW (14386%) | OVERFLOW (7193%) | OVERFLOW (3597%) | OVERFLOW (1439%) | 215923 | 168 |

- **Answer: no candidate budget closes** at any candidate clock under
  the modeled scalar single-lane schedule (A-SCHED-1). The
  worst-pitch-corner BLIT oscillator dominates (classic 175.8–352.7
  cyc/sample/instance; 768 instances in the supersaw preset).
- July still overflows at 480 MHz with ~62% of the total in
  probe-covered components (osc 5467 + filters 4608 of 16230 @M18);
  the remainder is flagged placeholder components (LFO 2880, env 640,
  waveshaper 50, Phaser+Airwindows 1600, modulation 270).
- Alternatives are UNCOMBINED (no single score): bundles x multipliers
  x clocks with cycles / RAM bits / external bytes as separate columns;
  adaptation-candidate kernels (naive Classic 13–25, WT-direct 21–39
  cyc/sample) are reported per-record, never averaged in.
- This is a planning input for SXT-017 (parallel lanes, unison
  reduction = adaptation, cheaper candidates = adaptation, clock
  hypotheses), NOT a verdict that the presets are unsupported.

## 3. SXT-015 placeholder/ESTIMATE-REF items REPLACED by this work

| SXT-015 parameter (placeholder) | Replaced by | Values |
|---|---|---|
| `cyc_osc_unison_voice_frame` = 200 | `probe_osc` pinned-structure kernels, worst pitch corner, per unison instance | classic_blit 175.8 (M32) – 352.7 (M18); sine_poly_fastmath 33.3–78.8; wavetable_blit 139.9–262.3 |
| `cyc_filter_unit_frame` = 150 | `probe_filter` | svf_tdf2 32–110; k35_ladder 72–170 (tanh LUT vs poly; block vs per-sample coeff) |
| `cyc_fxdelay_frame` = 900 | `probe_fx_delay` | 184 (on-chip, M32) – 1598 (ext E1 worst, M18) by memory model |
| `cyc_fxgeneric_frame` (EQ class) = 800 | `probe_fx_eq` | 81–321 |
| `cyc_fxreverb1_frame` = 2600 | `probe_fx_reverb1` | 563–3223 by E-model (latency-bound) |
| `cyc_event_frame` = 40 | `probe_scheduler` | 91 per event; 90/frame fixed control; transfer 8; contention 990 |
| `clock_hz` = 480 MHz placeholder | A-CLK candidate set + per-clock closure everywhere | {48, 96, 192, 480} MHz (feasibility NOT verified) |
| `ext_bandwidth_budget_bytes_per_s` = 800 MB/s | per-E-model sustained curves | E1: 8 MB/s @48 MHz – 80 @480; E2: 48–480; E3: 96–960 |
| `osc_state_bytes_per_unison` = 512 B | probe-derived bits/instance (+ shared/slot) | classic 194 b + 30,240 b/slot shared ring; sine 216 b; wt 282 b + 49,152 b table working set |
| `filter_unit_state_bytes` = 256 B | probe-derived | svf 192 b; k35 584 b |
| `wt_working_set_bytes` = 65,536 B | probe-derived mip0 working set | 49,152 b (6 KiB) per active WT slot (mip0; smaller mips halve; SXT-026 owns mip/morph behavior) |
| Delay traffic semantics | reconciled (logical vs physical) | SXT-023 still owns re-pinning `delay_max_length_samples` and the modulatable range (`delay_mod_margin_semitones` NOT replaced) |

NOT replaced (still placeholder-v0, flagged wherever used):
`cyc_waveshaper_frame`, `cyc_lfo_frame`, `cyc_env_frame`,
`cyc_modroute_frame`, `cyc_fxchorus_frame`, `cyc_fxreverb2_frame`,
`cyc_fxflanger_frame`, `cyc_fxgeneric_frame` (non-EQ classes),
`voice_base_state_bytes`, `lfo_state_bytes`, `unverified_fx_state_bytes`,
Reverb2/FloatyDelay structure constants. These need the SXT-023/024/028
leaf issues.

## 4. Headline findings (estimates)

1. **No closure at any candidate clock** under scalar single-lane
   arithmetic; the quantified SXT-017 levers are parallel lanes, unison
   reduction (adaptation), cheaper oscillator candidates (adaptation),
   and the clock hypothesis itself.
2. **Phase width moves RAM, not cycles**: 16→32-bit phase changes
   Classic per-instance state by 32 bits and cycles by 0; audio-word
   width (via the MAC partial-product schedule) dominates cycles.
3. **Delay external traffic is memory-model-dependent**: 26 words/frame
   naive vs ~4 with the named window cache; SXT-015's 6r+2w is a
   LOGICAL count. Reverb1's 34 scattered words/frame are
   latency-bound (990 cyc/frame contention allowance at E1), not
   bandwidth-bound.
4. **Reverb1 fixed-point guard band**: zero-latency loop spectral
   radius approaches 1 at max decay (rho = 0.99995 => ~15 guard bits
   for quantization noise; internal word 24+15 bits or a shorter
   max-decay cap). SXT-024 decision input; limit-cycle/dither behavior
   not modeled.
5. **Scheduler is small vs voice cost** (818 cyc/frame at the worst
   fixture burst) but is now measured, not guessed.

## 5. Deviations from the issue text (recorded, not silent)

- The issue glosses Classic as "windowed naive saw/pulse + LP", Sine as
  "table+phase", and Wavetable as "mip-select + linear interp". The
  PINNED structures are: Classic = abstract-BLIT 12-tap sinc
  convolution (`ClassicOscillator::convolute`); Sine = FastMath
  polynomial sin/cos (`SineOscillator::process_block_internal`);
  Wavetable = BLIT + per-impulse morph-interpolated mip-selected table
  read (`WavetableOscillator::convolute`). Per the plan ("read the
  actual algorithm"), the probes cost the PINNED STRUCTURES — these are
  what replace the SXT-015 placeholders — and ALSO cost the issue's
  glossed candidates, labeled adaptation candidates whose sound would
  differ and which therefore never count toward original-preset support.
- gf180mcu memory-macro numbers are not available to this work; probes
  use the named generic E1/E2/E3 models and say so everywhere. The
  issue's stop/escalate condition (no credible numbers before SXT-017)
  is therefore recorded as a standing limitation rather than a BLOCK:
  the estimates are explicitly assumption-bound, and no budget freeze
  is claimed. Escalation note for SXT-017: do not freeze hard budgets
  from these numbers alone.
- SIMD 4-wide lanes (which the engine uses) are not modeled
  (A-SCHED-1); scalar numbers are conservative for throughput,
  optimistic for area.

## 6. What SXT-017 may and may not conclude

May conclude (with this record + `worked-bundles.json` as inputs):
- relative comparisons of candidate arithmetic and memory models under
  the named assumptions;
- that the plan-section-5 formula, applied to these numbers, does not
  close at any candidate clock for the worked bundles — hence profile v1
  must change at least one of: lanes/parallelism, unison/polyphony
  (adaptation), kernel candidates (adaptation), clock hypothesis, or the
  product contract (visible revision per SXT-017);
- the guard-band and external-traffic findings as decision inputs for
  SXT-023/024.

May NOT conclude:
- any measured gf180mcu area, power, timing, or feasibility claim (no
  synthesis/PnR/signoff has been run);
- that any adaptation candidate (naive Classic, WT-direct playback,
  reduced unison) preserves original-preset sound — that requires the
  fidelity contract and listening records;
- support or quality claims of any kind from cycle/RAM/bandwidth
  numbers (AGENTS.md: numeric tests never establish musical
  usefulness);
- closure of any bundle containing placeholder components without
  repeating the flag (July/supersaw totals mix probe and placeholder
  values; only `covered_worst_synth` is placeholder-free).

## 7. What remains unproved

- Achievability of any candidate clock or external-memory timing in
  gf180mcu (macro selection, I/O, physical design).
- Whether adaptation candidates would pass any fidelity contract.
- Costs of uncovered classes (Phaser, Chorus, Reverb2, Airwindows,
  waveshaper, LFOs, envelopes, modulation rows) — placeholder-v0.
- Actual parallel-lane schedules, bus arbitration with concurrent
  instances, and DRAM/SRAM refresh effects.
- Everything in plan section 6 after SXT-017.
