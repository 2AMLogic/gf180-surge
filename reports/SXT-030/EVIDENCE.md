# SXT-030 (#316) — external-memory service/stall instrumentation: EVIDENCE

Issue: #316 (SXT-030 support leaf) · Epic: #3 · Contract:
[`docs/fpga-capture-calibration-procedure.md`](../../docs/fpga-capture-calibration-procedure.md)
§9.1 (register/signal set, deadline-miss output policy) and §9.2 (NC-1) ·
RTL: `rtl/instrumentation/ext_mem_instr.sv` · Bench:
`rtl/instrumentation/tb_ext_mem_instr.sv` · Gate/harness:
`tools/sxt030_stall_bench.py` · Mutants: `tools/make_sxt030_mutants.py` →
`rtl/instrumentation/ext_mem_instr_*_mutant.sv` · Tests:
`tests/test_sxt030_stall_instrumentation.py` · Machine record:
[`bench-results.json`](bench-results.json)

## 0. Scope — read before quoting anything below

**Everything here is SIMULATION ONLY** (Icarus Verilog 13.0, `-g2012`).
No board was run. Nothing in this record is a hardware measurement, an
external-memory latency/bandwidth/underrun figure, an FPGA or gf180mcu
synthesis / place-and-route / timing / power result, a hardware-playback
claim, a Surge-fidelity claim, or a qualification claim. The "fixture" the
instrumentation wraps is a declared **stub traffic shape**, not DSP; its
"audio" is a deterministic stub sample stream. The external memory is a
declared **simulation model** with a fixed latency, not a device.

What this record establishes, and only this: the §9.1 register/signal set
and the §9.2 NC-1 mechanisms exist in RTL, and in simulation the NC-1
validity gate behaves as §9.2 specifies — an over-subscribed take surfaces
as a *measured stall* on all three witnesses, never as silence, and the
three live negative controls the issue names each fail the check they
target. #304 inherits this RTL and bench; it must still run NC-1 **live on
its own rig** (§9.3: "A control from an earlier session does not certify a
later one").

## 1. Declared simulation parameters (assumptions, not measurements)

| Parameter | Value | Basis |
|---|---:|---|
| core cycles per 48 kHz frame | 1,000 | the 48 MHz A-CLK candidate named in procedure §1.2, ÷ 48 kHz |
| external-memory latency | 3 cycles → **4 cycles per 32-bit word** with the issue-on-ack handshake | the E2-class "~4 cycles/32-bit word" sustained assumption of §1.3 |
| nominal `SVC_WINDOW_LIMIT` (reset value) | 960 cycles | declared; max = 1,000 − `SVC_RESERVE` (8) = 992 |
| stub fixture traffic | 6 words/frame (4 reads + 2 writes; two per-instance histories, tags 0/1) | ≥ the #19 measured-shape anchor ≈ 1,070,000 B/s ≈ 5.6 words per 48 kHz frame (§1.2/§1.3) |
| M2 tight window | 16 cycles | provably below the 24 cycles the 6-word fixture needs |
| `HOLD_RESET` (held sample before any frame exists) | 0x4000 | declared non-zero constant; see §4 |

Because these are declared, every cycle figure below (occupancy, blocked
cycles, the rung at which M1 stalls) is a **consequence of these
parameters**. None of it predicts what #304's board will show.

## 2. What was built

- **`ext_mem_instr`** (core): control-link register file; per-frame
  service sequencer; `LOADGEN_WORDS_PER_FRAME` load generator (M1; tag 2,
  same scattered address mix, queued *ahead* of the fixture's own accesses
  so added load starves the fixture's data); `SVC_WINDOW_LIMIT` grant
  throttle (M2); the counters/sticky bits; `stall_strobe` (one-cycle pulse
  on the missed frame's output cycle) and latching `stall_led`; the
  held-sample deadline-miss output policy.
- **Deadline model.** A frame's external service *misses its deadline* iff
  not every access of that frame (load-generator + fixture) completed by
  the frame's commit cycle. Accesses may be issued only while
  `cycle < SVC_WINDOW_LIMIT`; the window is clamped to ≤ 992 so every
  access issued inside it completes before commit. Consequence: every miss
  leaves un-issued work and therefore records `STALL_CYCLES_MAX > 0`.
  Unfinished work is abandoned at commit (no carry-over), so a stall stays
  localized to the frames that were over-subscribed.
- **Bench** (`tb_ext_mem_instr.sv`): runs one take from a stimulus file;
  counts frames on the `out_valid` timebase (the LRCLK-equivalent, kept
  independent of the DUT's `FRAME_COUNT`), logs `stall_strobe` against that
  timebase, reads every register over the control link **before** and
  **after** the take, counts every completed access in the memory model
  itself, and reads every register again after a post-take reset.
- **Gate** (`tools/sxt030_stall_bench.py`): the §9.2 validity gate as
  written, plus take-integrity checks (any failure = `NO_VERDICT`):
  `BUILD_ID` read back equals the expected identity (sha256 of the DUT
  bytes, first 32 bits, passed in at build time); `FRAME_COUNT` delta equals
  the frames on the timebase; `EXT_WORDS_RD/WR` (total and per tag) equal the
  memory model's own counts; no traffic at all is refused; counters are zero
  before the take and after a reset.

### 2.1 Register map (control link, 32-bit words)

| Addr | Name | Access | Notes |
|---:|---|---|---|
| 0x00 | `BUILD_ID` | RO | build-time nonce |
| 0x01 | `CTRL` | RW | bit0 `RUN` (frames start only while set) — *addition* |
| 0x02 | `STATUS` | RO | bit0 `OUTPUT_FAULT` (sticky), bit1 `FIRST_STALL_VALID`, bit2 `STALL_LED`, bit3 `STALL_FRAMES` saturated — *addition: container for the sticky bits* |
| 0x03 | `FRAME_COUNT` | RO | saturating |
| 0x04 / 0x05 | `EXT_WORDS_RD` / `EXT_WORDS_WR` | RO | saturating, all tags |
| 0x06 | `SVC_OCCUPANCY_MAX` | RO | peak per-frame cycles with an access in flight |
| 0x07 | `STALL_FRAMES` | RO | saturating at `2^STALL_W − 1` (default 32-bit) |
| 0x08 | `STALL_CYCLES_MAX` | RO | worst per-frame count of cycles with un-issued work and the grant closed |
| 0x09 | `FIRST_STALL_FRAME` | RO | sticky; meaningful only with `FIRST_STALL_VALID` (so a stall in frame 0 is distinguishable from "none") |
| 0x0A | `LOADGEN_WORDS_PER_FRAME` | RW | M1; latched at frame start |
| 0x0B | `SVC_WINDOW_LIMIT` | RW | M2; clamped to ≤ 992 on write; latched at frame start |
| 0x10–0x12 | `EXT_WORDS_RD_TAG0..2` | RO | per-tag: instance 0, instance 1, load generator — *the §9.1 "per-instance tagged" counters* |
| 0x14–0x16 | `EXT_WORDS_WR_TAG0..2` | RO | per-tag writes |

Pins: `stall_strobe`, `stall_led` (latching), `frame_start`, `out_valid`.
The additions are additive and change no §9.1 row's meaning; the
procedure document records them visibly (its §9.1 implementation note).

## 3. Acceptance mapping (issue #316)

| # | Acceptance | Status | Where |
|---|---|---|---|
| A1 | In-budget run: `STALL_FRAMES == 0`, no strobe, comparison passes | **PASS** (simulation) | `takes.in_budget`; `test_in_budget_run` |
| A2 | Over-subscribed via **M2**: all three witnesses fire and agree on the frame range | **PASS** (simulation) | `gates.NC1_M2`; `test_m2_all_three_witnesses_fire_and_agree` |
| A3 | Over-subscribed via **M1**: rung at which stalls begin recorded; ladder reaches a stall | **PASS** (simulation) — first stalling rung **L2** under §1's declared parameters | `ladder`, `gates.NC1_M1`; `test_m1_ladder_reaches_a_stall_and_records_the_rung` |
| A4 | Deadline-miss output is not silence; held-sample policy asserted; silence variant fails | **PASS** (simulation) | `takes.m2_throttle.held_policy_violations == []`; `controls.silence_on_miss` → gate **FAIL**; `test_deadline_miss_holds_the_previous_sample_not_silence` |
| A5 | Counters stubbed to zero while output degrades → refused (`NO_VERDICT`) | **PASS** (simulation) | `controls.zero_counters`, `controls.silence_zero_counters` → gate **NO_VERDICT**; `test_zero_counter_builds_are_refused` |
| A6 | No hardware measurement / latency-underrun figure / synthesis / qualification claim in this evidence | **PASS** (by inspection of this record; §0, §6) | — |

Detail (from `bench-results.json`):

- **A1 in-budget** (24 frames, L0, nominal window): `STALL_FRAMES` 0,
  no strobe, LED 0, `OUTPUT_FAULT` 0, exact comparison PASS on all 24 frames;
  `EXT_WORDS_RD` 96 / `EXT_WORDS_WR` 48, per-tag writes [24, 24, 0];
  `SVC_OCCUPANCY_MAX` 24 cycles.
- **A2 M2** (24 frames; window 16 for frames 8–15, nominal otherwise):
  counters `STALL_FRAMES` 8, `FIRST_STALL_FRAME` 8 (valid),
  `STALL_CYCLES_MAX` 983, `OUTPUT_FAULT` 1; strobe frames 8–15; residual
  (comparison-FAIL) frames 8–15 — all three equal the commanded range. No
  dropout; every stalled frame repeats its predecessor exactly.
- **A3 M1 ladder** (16-frame takes, rung applied to frames 4–11):

  | Rung | words/frame added | B/s added | `STALL_FRAMES` | comparison |
  |---|---:|---:|---:|---|
  | L0 | 0 | 0 | 0 | PASS |
  | L1 | 174 | 33,408,000 (#12 modeled worst case, 696 B/frame) | 0 | PASS (`SVC_OCCUPANCY_MAX` 720) |
  | L2 | 348 | 66,816,000 | 8 (frames 4–11) | FAIL in exactly frames 4–11 |

  The climb stops at the first stalling rung, as §9.2 prescribes. "L2" is a
  **simulation figure under the §1 parameters** (348 + 6 words × 4 cycles
  exceeds the 960-cycle window; 174 + 6 does not) — it is neither a rig
  figure nor a product claim.
- **A4/A5 controls** (each mutant run on the same in-budget + M2 takes):

  | Control | Mutation | Gate verdict | Expected | Control status |
  |---|---|---|---|---|
  | silence-on-miss | miss → output forced to 0 | **FAIL** (silent; held policy violated) | FAIL | PASS |
  | zero counters | `stall_count` tied 0 (counters, `OUTPUT_FAULT`, strobe, LED dead; output still held) | **NO_VERDICT** | NO_VERDICT | PASS |
  | silence + zero counters | both of the above | **NO_VERDICT** | NO_VERDICT | PASS |
  | M2 throttle never engages | frame latches nominal window; register still reads back the commanded value | **FAIL** (no witness fires) | FAIL | PASS |
  | `BUILD_ID` mismatch | real build, expected identity off by one bit | **NO_VERDICT** | NO_VERDICT | PASS |

  Each mutant is an exact generated line mutation of the real source
  (`tools/make_sxt030_mutants.py --check`; asserted by
  `test_committed_mutants_are_exact_generated_mutations`). The same takes
  graded on the real design give PASS, so each control demonstrably fails
  the check it targets and nothing else.

### 3.1 Edge cases (curator test plan)

| Case | Result |
|---|---|
| Stall in frame 0 (window 16 from before `RUN`) | `FIRST_STALL_FRAME` 0 with `FIRST_STALL_VALID` 1; frame 0 emits `HOLD_RESET` (non-zero); gate PASS |
| `FIRST_STALL_FRAME` stickiness (bursts at 3–4 and 9–11) | stays 3; `STALL_FRAMES` 5; strobe = residual = {3,4,9,10,11}; gate PASS |
| `STALL_FRAMES` saturation (`STALL_W` = 3, 12 stalled frames) | reads 7, `STATUS` saturated bit set; 12 strobes; gate PASS (agreement rule accounts for saturation) |
| Counter reset | every real take reads all counters/status zero before the take and after a post-take reset (`SVC_WINDOW_LIMIT` back to 960) |
| M1 ladder through the 696 B/frame rung | L1 runs clean; stall at L2 |

### 3.2 Gate logic branches without a simulator

`test_gate_branches_on_synthetic_witnesses` drives `nc1_gate` through every
§9.2 branch on synthetic witnesses, including the one no mutant reaches:
**counters fire but the audio comparison passes → FAIL ("too weak"), not
PASS**.

## 4. Findings and contract clarifications (visible, not silent)

1. **Stall before any frame exists.** §9.1 says "hold the previous frame's
   sample" but a stall in frame 0 has no previous frame. Holding the reset
   value 0 would be silence, which §9.1 forbids. This implementation holds a
   declared non-zero `HOLD_RESET` (0x4000). Recorded in the procedure doc's
   §9.1 implementation note.
2. **`FIRST_STALL_FRAME` = 0 is ambiguous on its own.** A `STATUS` valid
   bit disambiguates "first stall in frame 0" from "no stall".
3. **The deadline is the frame's whole external service**, load included;
   a missed frame holds even if its fixture reads happened to complete
   (M2 at window 16 completes the four reads but not the two writes). This
   is the conservative reading of "frames whose external service missed its
   deadline"; it does not weaken any control.
4. **No contract weakening was needed.** Every §9.1 row is implemented as
   specified; the Stop/escalate condition (contract not implementable) did
   not trigger. The additions in §2.1 are additive.
5. **Freshness.** `bench-results.json` records sha256 over the six `.sv`
   sources; `test_committed_record_names_current_sources_and_no_hw_claim`
   re-derives them, and `test_committed_results_are_current` re-runs the
   bench and requires byte-equal results. Editing any of those `.sv` files
   turns this record STALE until `python3 tools/sxt030_stall_bench.py
   --write` is re-run. (These are RTL pins; `docs/byte-frozen-sources.md`
   audits Python sources only and is unchanged.)

## 5. How it was checked

```
python3 tools/make_sxt030_mutants.py --check
python3 tools/sxt030_stall_bench.py --write
python3 -m pytest -q tests/test_sxt030_stall_instrumentation.py
```

Simulator: Icarus Verilog 13.0 (`~/.local/bin`). The same bench run under
the host's Icarus Verilog 12.0 (`/usr/bin`) produced a byte-identical
results record; that is simulator-to-simulator repeatability of this bench,
nothing more. CI's pytest job installs no simulator, so there the simulation
tests are reported as skipped `NOT_RUN` (never as passes); the gate-logic,
mutant-shape and record-freshness (sha256) tests still run.

## 6. Status register

| Item | Status |
|---|---|
| §9.1 register/signal set in RTL | **PASS** (simulation) |
| NC-1 validity gate, M2 | **PASS** (simulation) |
| NC-1 validity gate, M1 ladder | **PASS** (simulation; first stalling rung L2 under declared parameters) |
| Held-sample policy; silence variant fails | **PASS** (simulation) |
| Zero-counter builds refused | **PASS** (simulation; `NO_VERDICT`) |
| Never-engaging throttle fails | **PASS** (simulation) |
| Live hardware measurement of any kind | **NOT_RUN** — #304 |
| NC-1 run live on the selected board | **NOT_RUN** — #304 |
| Logic-analyzer capture of `stall_strobe` against a real LRCLK | **NOT_RUN** — #304 (the bench's frame timebase is its simulation stand-in) |
| Phase-A analog `dropout` / `stuck` / `residual` checks | **NOT_RUN** — #304 (simulation screens for dropout/stuck are recorded, not the Phase-A checks) |
| Latency / underrun / stall figures for the instrument | **NOT_RUN** — none produced; simulation cycle counts are not such figures |
| FPGA synthesis / place-and-route / timing / power of this RTL | **NOT_RUN** — not attempted, not claimed |
| gf180mcu synthesis / P&R / signoff | **NOT_RUN** — #24 |
| Integration with the real external-memory controller (e.g. MIG) | **NOT_RUN** — the bench memory is a fixed-latency model |
| Any hardware-playback, Surge-fidelity or preset-quality claim | **none made** |
