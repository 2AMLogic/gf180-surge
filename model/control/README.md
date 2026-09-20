# SXT-021 — Model control plane (`model/control/`)

Deterministic timed control over compiled patch images: reset policy, event
queues, note allocation/stealing, patch changes, audio framing, a
continuous-output path through a clearly-named **stub** engine, and
worst-case schedule accounting. This package is the **reference** for
`rtl/control/` (exact schedule equality at every declared checkpoint; the
comparator is `tools/compare_control_rtl.py`, following the SXT-022
`compare_rtl_model.py` pattern).

**Claim scope: the control plane only.** No DSP, no fidelity, no
preset-support, no musical-quality, and no hardware claim is made here. The
engine slot is a stub (`engine_stub_counter.py`); its cost enters accounting
as a named placeholder. Stereo output framing is declared here for later
integration (SXT-025), not demonstrated with real audio.

## Declared conventions (normative for the RTL)

| Convention | Declaration (v1) | Provenance / revision point |
|---|---|---|
| Sample rate | 48 000 Hz | engine pin (`model/resources/params.py`) |
| Audio framing | block = 32 samples; one control pass + one stereo output block per block; output = interleaved 16-bit L,R words, little-endian | `fx_frame_block_size` engine pin (SURGE_COMPILE_BLOCK_SIZE); 24-bit audio words are the SXT-025 integration point |
| **Scheduling granularity** | Event timestamps are integer samples; an event at `t` is applied at the start of block `ceil(t/32)` — **events quantize UP to the block, never down**. An event is never applied before its timestamp; alignment latency is 0..31 samples, plus at most one block to the following DAC frames (bounded ≤ 64 samples ≈ 1.33 ms end-to-end). | SXT-012 convention; the engine runs control once per 32-sample block |
| Reset policy | **Power-on**: counter 0, queue empty, voices free, patch 0. **Patch-load**: voices force-cleared, queued events flushed (each recorded), patch id set; block counter keeps running (audio never re-clocks). | deterministic by construction; re-render test in `tests/test_sxt021_control.py` |
| Event queue | FIFO, depth 16; push order = arrival order; the stream must be nondecreasing in `t` (fail-closed). A push onto a full queue is an **explicit detected drop** (`queue_overflow`), never silent corruption. | `event_queue_depth` = 16, corpus-derived (SXT-015 params; SXT-016 probe reconciliation) |
| Declared per-block event reserve | 8 events/block. A block with more arrivals is flagged `event_reserve_exceeded`; the surplus spills to later blocks (bounded by queue capacity). Renders exceeding the reserve **do not close** the worst-case schedule accounting and their records say so. | SXT-016 scheduler probe: worst coincident events per frame = 8 (fixtures-derived, `seq-poly-8-v1`) |
| Voice pool | 8 scene voices | plan §3 "8 scene voices"; DRAFT-profile revision point — bundle B4's working hypothesis is pool 16 (profile-v1-DRAFT §5.2). Declared, not silently assumed; the model fail-closes on any other pool |
| Steal policy | `note_on` with no free slot steals the **oldest active voice** (smallest allocation sequence; tie → lowest slot index). `note_off` releases the oldest active voice holding that note; none → recorded no-op. | declared here (v1); single-channel v1 |
| Patch change | **HARD SWITCH** at the target block boundary: voices cleared, queue flushed (recorded), new patch id. Tail-then-switch is the declared profile revision point for SXT-025 (wet-preset tails); NOT implemented in v1. | declared here (v1) |
| Engine slot | STUB: `engine_stub_counter.py` — 16-bit stereo counter + active-voice nibble (formula mirrored exactly in RTL). Never all-zero; monotone counter field; allocation effects visible. | repo `*_stub*` negative-control naming convention |

## Layout

| File | Contents |
|---|---|
| `control_model.py` | `ControlModel` (block-stepped reference), `Event`, `quantize_block`, `render_sequence` (fail-closed harness) |
| `accounting.py` | worst-case schedule accounting: control + events + stub slot vs `gross × (1 − reserve)` using SXT-016 scheduler rows; OVERFLOW → explicit rejection |
| `engine_stub_counter.py` | the v1 stub engine slot (counter) |
| `engine_stub_silent.py` | NEGATIVE-CONTROL stub (all-zero slot) used by `reports/sxt-021/negative-controls.txt` |

## Worst-case schedule accounting

Per 48 kHz sample period (the plan §5 budget unit), SXT-016 scheduler probe
row (m32) verbatim:

| Component | cyc/sample period |
|---|---:|
| control (fixed, once per block, charged conservatively at the probe row) | 72 |
| events (88 × 8 declared worst case) | 704 |
| stub slot (named placeholder) | 2 |
| transfer (A-CTL-1) | 8 |
| contention (A-CTL-2) | 990 |
| **worst-case used** | **1776** |

Budget = `F/Fs × (1 − 0.2)`: 800 / 1600 / 3200 / 8000 at the 48 / 96 / 192 /
480 MHz candidate clocks. Verdicts: **OVERFLOW (explicit rejection) at 48
and 96 MHz; within_budget at 192 MHz (1776 ≤ 3200, 44.4% of gross) and 480
MHz**. Same verdicts as the SXT-016 probe closure rows (reconciliation note
in `accounting.py`). These are candidate-clock arithmetic checks under named
assumptions (A-CLK) — not a gf180mcu synthesis or timing claim. The
stop/escalate condition (issue #14) is not triggered: the stub closes at
192 MHz.

Committed table: `reports/sxt-021/schedule-accounting.json`.

## Determinism

No clocks, wall time, randomness, or environment values; fixed iteration
orders; canonical JSON traces (sorted keys). Identical inputs produce
byte-identical traces and output recordings — asserted by the committed
fixtures and `tests/test_sxt021_control.py`.

## Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`); Python stdlib only.
Engine facts (block size 32, queue depth 16 basis, sample rate) are read and
cited from the pinned tree via `model/resources/params.py`; no Surge code,
tables, or assets are copied. The comparator/negative-control *pattern*
follows this repository's own SXT-022 tooling (method reuse within the repo).
