# SXT-016 — kernel cost probes (`probes/`)

Representative cycle/state/bandwidth cost ESTIMATORS for candidate
arithmetic (issue #11 / SXT-016). Each probe is a standalone stdlib-Python
module whose kernels are integer reference schedules **written from first
principles following the STRUCTURE of the pinned Surge algorithms** —
cited per record; no GPL code, tables, or assets are copied into this
repository (AGENTS.md license rule; REUSE-AUDIT.md).

**These are experiments, not production blocks.** No gf180mcu synthesis,
place-and-route, timing signoff, or layout has been run anywhere in this
package. All numbers are planning estimates against the named assumptions
below; area statements are PDK-neutral relative op counts; state RAM is
reported in bits, separately from logic. Nothing here is a fidelity,
support, or preset-quality claim.

## Reproduce

```sh
python3 probes/run_all.py            # regenerates every JSON + SUMMARY.md
python3 probes/worked_bundle.py      # prints the Pareto table
python3 -m pytest tests/test_sxt016_probes.py -q
```

Outputs are byte-identical on re-run (sorted keys, no timestamps; pure
integer op counting; the two float analyses — pitch corners and the
reverb loop power iteration — use fixed inputs and a fixed iteration
count, rounded to 6 decimals).

## Probes

| Module | Kernel class | Cites (structure) | Replaces (SXT-015) |
|---|---|---|---|
| `probe_osc.py` | Classic BLIT, naive+LP (adaptation cand.), Sine table+poly, Wavetable BLIT + direct (adaptation cand.) | `ClassicOscillator.cpp` `::convolute`/`::process_block`; `SineOscillator.cpp` `::process_block_internal`; `WavetableOscillator.cpp` `::convolute`; `globals.h` OB_LENGTH/BLOCK_SIZE_OS; `SurgeStorage.h` FIRipol_M/N | `cyc_osc_unison_voice_frame` (pinned-structure kernels only), `osc_state_bytes_per_unison`, `wt_working_set_bytes` (partially) |
| `probe_filter.py` | SVF (TDF2 halves) + K35-style nonlinear ladder, block/per-sample coeff reload, per-sample nonlinearity | `VectorizedSVFilter.h` `CalcBPF`; sst-filters@`e92d93a` `K35Filter.h` `process_lp` | `cyc_filter_unit_frame`, `filter_unit_state_bytes` |
| `probe_fx_delay.py` | Stereo dual delay, 12-tap sinc taps, feedback biquads, crossfeed; on-chip + E1/E2/E3 external-line variants | sst-effects@`adcac695` `Delay.h` `::processBlock`/`setvars` | `cyc_fxdelay_frame` + delay traffic re-pin |
| `probe_fx_eq.py` | 3-band TDF2 biquad EQ | `ParametricEQ3BandEffect.cpp`; sst-filters `BiquadFilter.h` (file-level) | `cyc_fxgeneric_frame` (EQ instances) |
| `probe_fx_reverb1.py` | 16-tap composite + predelay, damping, wet biquads; traffic classes; fixed-point stability guard band | sst-effects@`adcac695` `Reverb1.h` `::processBlock`, `:122-131` | `cyc_fxreverb1_frame` + Reverb1 traffic confirmation |
| `probe_scheduler.py` | Event queue, voice alloc, per-frame control; fixture-derived event rates | `SurgeSynthesizer.cpp`/`SurgeVoice.cpp` (file-level); `fixtures/sequences/` | `cyc_event_frame`; provides control/transfer/contention split |
| `worked_bundle.py` | Complete-patch closure for the SXT-015 worked presets + a probe-covered synthetic worst case | uses `model/resources/accounting.py` structure | consumes all of the above |

## Named assumptions (every record embeds the ones it uses)

All assumption identifiers (A-*) are defined verbatim in
`probes/common.py` (`TECH`). Summary:

- **A-CLK (clock):** F ∈ {48, 96, 192, 480} MHz are candidate hypotheses
  for the plan-section-5 closure formula `gross = F/Fs`. None is verified
  achievable in gf180mcu — no synthesis has been run. Fs = 48 kHz.
  Reserve = 20% of gross (SXT-015 policy).
- **A-DSP-1a/b/c (multiplier):** one sequential MAC unit, 18/24/32-bit;
  a w×w multiply costs ceil(w/unit)² passes (schoolbook decomposition).
- **A-ALU-1 (adder):** ≤32-bit add/sub/cmp/shift = 1 cycle at every
  candidate clock. NOT timing-verified; pipelining at 480 MHz would raise
  add costs.
- **A-ALU-2 (division):** no division in any audio path; source divisions
  become multiply-by-precomputed-inverse at coefficient rate.
- **A-MEM-1 (on-chip SRAM):** single-port 1RW synchronous macro, 1-cycle
  read OR write, no dual-port; same-macro read+write serialize. A-MEM-2
  (2× bits, parallel r/w) is named where used.
- **A-MEM-3 (tables):** on-chip ROM/SRAM tables, 1-cycle read.
- **A-EXT-1/2/3 (external memory):** E1 16-bit async SRAM (~24 cyc/word
  sustained, 30-cyc latency, no burst); E2 16-bit sync burst (4 cyc/word,
  10-cyc latency); E3 32-bit sync burst (2 cyc/word, 8-cyc latency).
  These REPLACE the SXT-015 `ext_bandwidth_budget_bytes_per_s` placeholder
  with per-model sustained-bandwidth numbers.
- **A-EXT-BUF (delay window cache):** sliding 16-word per-channel window;
  sustained external traffic ~1 word/frame/channel plus re-seek bursts on
  delay-time jumps; the no-cache naive case (24 words/frame) is also
  reported.
- **A-CTL-1/2 (control path):** audio transfer service 8 cycles/frame;
  contention allowance 990 cycles/frame (33 same-frame external accesses
  × 30-cycle E1 latency, Reverb1 worst).
- **A-SCHED-1 (lanes):** scalar single-lane schedule everywhere. The
  engine's 4-wide SIMD unison/filter lanes are NOT modeled; scalar is
  conservative for throughput and optimistic for area.

Word lengths: phase accumulators at {16, 18, 24, 32} bits (per record),
audio path 24-bit, coefficients/control 32-bit, sinc table 256 phases ×
12 taps (`FIRipol_M`/`FIRipol_N`, `SurgeStorage.h`).

## Technology note (repeat)

Cell-area figures are PDK-neutral relative estimates (normalized op
counts). State memory is in bits. **No gf180mcu synthesis, layout, or
signoff has been run; every number is a planning estimate only.** The
stop/escalate condition from issue #11 (credible gf180mcu memory-macro
numbers unavailable) does not trigger: probes use named generic E-models
and flag — explicitly — that gf180mcu macro timing/area is unmeasured.

## Validation and negative control

`probes/validate.py` refuses any record that does not name its clock
candidate set, memory model (on-chip AND external), word lengths,
assumptions, and citations, or that carries non-deterministic fields.
`probes/negative_control.py` demonstrates the refusal on a deliberately
under-specified record (see `reports/sxt-016/negative-control/`).
Invalid records can never reach `reports/sxt-016/probes/`, which is the
mechanical exclusion SXT-017 relies on.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`). The pinned Surge
engine and sst libraries (GPL-3.0-or-later) were **read and cited** for
algorithm structure only; no Surge/sst source code, tables, coefficient
sets, or preset data were copied. Preset delay-time tables and preset
graphs remain in the external oracle / committed normalized corpus.
Structure citations name files and functions (line ranges where pinned by
SXT-015); "file-level cite" marks files read at file granularity.
