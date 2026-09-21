# SXT-021 — Timed control and scheduling: EVIDENCE

Issue: #14 (SXT-021) · Epic: #2 · Branch: `loom/sxt-021-timed-control` ·
Model: `model/control/` · RTL: `rtl/control/` · Fixtures:
`fixtures/control/` · Comparator: `tools/compare_rtl_model.py` pattern →
`tools/compare_control_rtl.py` · Accounting:
`model/control/accounting.py` →
[`schedule-accounting.json`](schedule-accounting.json) · Negative controls:
[`negative-controls.txt`](negative-controls.txt)

**Scope of everything below: the CONTROL PLANE ONLY.** No oscillator,
filter, effect, or any other DSP exists in this issue; the engine slot is a
clearly-named stub (`engine_stub_counter.py`, RTL `audio_stub_slot`).
Nothing here is a DSP, fidelity, preset-support, preset-quality, or hardware
claim. No gf180mcu synthesis, place-and-route, timing signoff, or hardware
playback was run; every cycle number is candidate-clock arithmetic on the
SXT-016 scheduler-probe rows under named assumptions.

## Acceptance mapping (issue #14)

### 1. "Continuous stereo output at the profile rate for the duration of a fixture with no underruns" — **PASS** (control-plane scope)

- Four committed sequences (3 required, 4 delivered) rendered through the
  model AND the RTL control+stub at 48 kHz, 32-sample blocks, interleaved
  16-bit L/R stereo: `fixtures/control/<id>/model_out.bin` and
  `rtl_out.bin` are **byte-identical** for all four
  (`record.json:byte_identical_model_vs_rtl=true`; comparator verdict PASS:
  exact integer equality on every snapshot, decision, drop record, and all
  32·N output samples).
- Underruns (missing/partial output block for any audio block): **0 in all
  four fixtures**, recorded per fixture and asserted in
  `tests/test_sxt021_control.py`.
- Scope caveat, restated: "output" here is the declared deterministic stub
  pattern, not audio. The framing (48 kHz, 32-sample blocks, stereo word
  order) is what SXT-025 integrates against.

### 2. "Event-to-output latency measured and bounded; note stealing and patch-change glitches characterized" — **PASS**

- Declared convention: events quantize **UP** to the 32-sample block, never
  down (SXT-012 convention); alignment latency ∈ [0, 31] samples, +≤1 block
  to the following DAC frames → bounded ≤ 64 samples ≈ 1.33 ms end-to-end.
- Measured per fixture (record.json): `ctl-notes-steal-v1` max 24 samples;
  `ctl-patch-change-v1` max 31 samples (t=33 event applied at sample 64).
  Every decision carries `latency_samples` in `model_trace.json`.
- Stealing characterized: pool of 8 (declared; see revisions below),
  oldest-active-first, tie → lowest slot. `ctl-notes-steal-v1` block 900:
  note_on 48 steals slot 0 (status `STEAL`, decision recorded). Under the
  stub, a steal is audible as the voice-count nibble change — allocation
  glitches are visible and bounded by construction (≤1 per event).
- Patch-change glitches characterized: v1 declares **HARD SWITCH** at the
  target block boundary — all voices cleared and queued events flushed with
  an explicit recorded count (`ctl-patch-change-v1`: mid-notes switch at
  block 157 clears 2 active voices; boundary switch at block 2000 flushes
  1 queued event). The switch glitch is therefore declared and
  deterministic, not emergent. Tail-then-switch is the declared profile
  revision point (SXT-025 wet-preset tails).

### 3. "Worst-case schedule accounting closes against the profile budget including a declared reserve" — **PASS at 192/480 MHz; explicit OVERFLOW (rejection) at 48/96 MHz**

Per 48 kHz sample period (plan §5 formula), SXT-016 scheduler probe row
(m32) verbatim:

| Component | cyc/sample period | Source |
|---|---:|---|
| control (fixed; once-per-block work charged conservatively at the probe row) | 72 | SXT-016 `control_cycles_per_frame` |
| events (88 × declared worst 8/block) | 704 | SXT-016 `cycles_per_event` × `max_coincident_events_per_frame` |
| stub slot | 2 | **declared here**, named placeholder (SXT-022+ replaces) |
| transfer | 8 | SXT-016 A-CTL-1 |
| contention | 990 | SXT-016 A-CTL-2 |
| **worst-case used** | **1776** | |

Budget = F/Fs × (1 − 0.2 declared reserve). Headline: **1776 vs 3200 at
192 MHz → within_budget (44.4% of gross)**; 480 MHz within_budget;
48 MHz (1776 vs 800) and 96 MHz (1776 vs 1600) → **OVERFLOW, explicit
`schedule_budget_overflow` rejection object** (never silent). Same
verdicts as the SXT-016 probe closure rows on all four candidate clocks.
Committed: `schedule-accounting.json` (constants, per-clock rows,
per-fixture render status).

- Declared event reserve = 8 events/block; renders exceeding it are flagged
  and **do not close** their worst-case accounting (see NC1 and the
  overload fixtures' `closes_declared_schedule=false`).
- Stop/escalate (issue #14): **not triggered** — the stub closes at
  192/480 MHz. Honest corollary: the real DSP slot (SXT-022+) must re-close
  the same formula; the stub's 2 cyc/sample-period placeholder is the line
  item that gets replaced.

### 4. "Reset and patch-change behavior deterministic" — **PASS**

- Reset policy declared and implemented: power-on zeroes counter, queue,
  voices, patch id; patch-load clears voices + flushes the queue (recorded)
  while the audio frame counter keeps running.
- Byte-identical re-render verified (`test_reset_and_rerender_deterministic`
  and the fixture re-render test); no clocks, randomness, or environment
  values anywhere in the model or artifacts.

### 5. Negative control: "injecting an event burst exceeding the declared reserve must produce a detected/bounded overload, not silent corruption" — **PASS**

`negative-controls.txt` (all three controls must demonstrably FAIL the
check they target; the generator exits non-zero otherwise):

- **NC1** — burst 12 > reserve 8: block flagged `event_reserve_exceeded`,
  4 events spill to the next block with bounded latency growth (32
  samples), zero drops, zero underruns, and the render's schedule
  accounting **refuses to close**. Burst 30 > reserve AND > 16-deep queue:
  **14 explicit drop records — counted identically in the model statuses
  and in the RTL's in-DUT `X` records** (overload is visible inside the
  DUT, not hidden in the testbench). Output never stops.
- **NC2** — a slot claiming `name = "surge-voice-real-dsp [UNVERIFIED
  CLAIM]"` but emitting all-zero stereo FAILS the output contract
  (non-zero bias, monotone counter field, voice-count nibble vs snapshot).
  The checker does not trust engine names; a stale/silent/mislabeled stub
  cannot pass. Sanity: the declared counter stub passes the same check.
- **NC3** — one injected divergence (queue depth 16→15,
  `control_broken_mutant.sv`, regeneration pinned by
  `tools/make_control_mutant.py`) **FAILS the comparator** on
  `ctl-queue-overflow-v1` (41 mismatches: snapshot queue counts and shifted
  drop records); the unmutated DUT PASSES the same fixture. Precision note
  (in the transcript): bursts that never touch the queue depth do not
  diverge — the control binds where the constant binds.

## Declared policy points (visible contract, not silent choices)

| Point | v1 declaration | Revision point |
|---|---|---|
| Voice pool | 8 scene voices (plan §3; task statement) | profile revision: DRAFT bundle B4's working hypothesis is pool 16 — explicitly NOT confirmed here; profile-v1-DRAFT §8.2 process applies |
| Patch change | HARD SWITCH at block boundary | tail-then-switch for SXT-025 wet tails |
| Event reserve | 8 events/block; overflow = flag + bounded spill; queue-full = explicit counted drops | SXT-016 numbers; re-pin with real DSP |
| Stub slot cost | 2 cyc/sample period placeholder | SXT-022+ real DSP re-closure |
| Stereo framing | interleaved 16-bit L/R words, 32-sample blocks @ 48 kHz | SXT-025 moves to 24-bit audio words (SXT-016 `audio_bits=24`) |
| Input gates | time-sorted stream, 48 kHz, block 32, timestamps in range — fail-closed | — |

## What this issue does NOT establish

- Any DSP behavior, any wet-preset fidelity, any preset support or quality;
  the pinned Surge oracle was not used (stub engine, no DSP — per issue
  setup).
- Any gf180mcu synthesis, timing closure, area, power, or hardware
  playback result. All cycle numbers are arithmetic on named assumptions
  (A-CLK etc.) at candidate clocks.
- Confirmation of voice pool 8 vs 16 (an SXT-016/017 decision; see table
  above) and no freeze of the profile (DRAFT-NOT-FROZEN throughout).
- Patch-change tails (hard switch only) — a declared SXT-025 revision
  point.

## Reproduce

```sh
python3 -m pytest -q tests/test_sxt021_control.py        # full suite w/ iverilog
python3 tools/render_control_fixtures.py                 # re-render + compare (byte-identical)
python3 tools/control_negative_controls.py               # NC transcript (exit 0 = controls healthy)
python3 tools/compare_control_rtl.py --seq fixtures/control/sequences/ctl-queue-overflow-v1.json --run-dir /tmp/cmp
python3 tools/compare_control_rtl.py --seq fixtures/control/sequences/ctl-queue-overflow-v1.json --run-dir /tmp/mut --dut rtl/control/control_broken_mutant.sv   # must FAIL
```

Committed artifacts generated with Icarus Verilog 13.0, Python 3.14
(stdlib only); identical inputs give byte-identical outputs.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`); Python stdlib and
iverilog-simulated SystemVerilog only. Engine facts (block size 32, queue
depth 16 basis, 48 kHz pin, SXT-016 probe rows) are read and cited from
this repository's own pinned-parameter model and probe reports; no Surge
code, tables, or assets copied. The comparator and committed-mutant
*pattern* reuse this repository's own SXT-022 tooling as method. The
gf180-dx7#25 / Parasynth substrate named in the issue remains governed by
its co-design/reuse-audit process (#25, docs/REUSE-AUDIT.md) — nothing was
imported from it here.
