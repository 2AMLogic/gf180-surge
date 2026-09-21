# SXT-023 Delay external-memory interface (`rtl/effects/delay/ext_mem_if.md`)

Interface definition + measured traffic for the Delay channel lines.
PINS the delay-line constants that SXT-016 flagged as deferred to SXT-023
(`model/resources/params.py` `delay_max_length_samples` /
`delay_mod_margin_semitones` are SXT-015 estimates — the pins below are the
authoritative values from the pinned source; the committed SXT-015/016 files
are NOT edited; agreement/divergence is recorded here).

## Pinned line constants (state agreement vs SXT-015/016)

| Constant | Pinned value | vs SXT-015/016 |
|---|---|---|
| `max_delay_length` | **262,144 samples (2^18)** per channel | **AGREES** with SXT-015 `delay_max_length_samples = 1<<18` (engine_constant tier) |
| line allocation | 262,144 + 12 words/channel (FIRipol_N guard) | NEW pin (SXT-015 stored the 2^18 only) |
| words/channel | Q10.21, 4 bytes → 1,048,624 B/channel; 2,097,248 B/instance | AGREES with SXT-015 `delay` state_bytes 2,097,152 ± the 48-byte guard (0.002% — SXT-015 rounded to 2^18) |
| `delay_mod_margin_semitones` (SXT-015 placeholder 12.0) | **REPLACED by the pinned mechanism**: the line is fully allocated at 2^18 regardless of parameters; the modulation sweep rides ON TOP of the nominal time and is CLAMPED per sample to `[32, 2^18−13]` (`Delay.h:347-355`). The sweep span is `LFOval` ≈ `inc·min(100, half-period_blocks)` with `inc = (2^(depth/12) − 1)·32` samples/block: ≈ 392 samples at depth 2.0, ≈ 3,202 at extended depth 12.0 — i.e. the modulation margin is a SAMPLE-DOMAIN LFO excursion (≤ 3,208 samples ≈ 1.2% of the line), not a semitone doubling of the allocation | **DIVERGES** from the SXT-015 semitone-margin model (which implied a 2× allocation for parameters > 0); SXT-015's estimate was conservative (over-allocated); no committed SXT-015/016 file is edited — this pin supersedes for SXT-023 scope |
| per-sample time clamp | `max(32, min((int)v, 2^18 − 13))` | NEW pin (`Delay.h:348-349`) |

## Interface (behavioral model: `rtl/effects/fx_line_ext.sv` + the inline
arrays in `rtl/effects/tb_fx.sv` — identical semantics)

Per delay instance: TWO independent channel lines (stereo), each
262,156 × 32-bit words. Word = Q10.21 sample. No read latency in the
behavioral model (the physical-latency tolerance is analyzed below).

```
access(inst, channel, we, addr[17:0], wdata[31:0]) → rdata[31:0]
addr = (wpos − i_dtime + k − 12 + t) & (2^18 − 1)     // reads, t = 0..11
addr = (wpos + k) & (2^18 − 1)                        // writes
```

Addresses wrap the 2^18 ring (the engine's `& (max_delay_length−1)` with
the +12 guard words unused by the masked addressing).

## Measured traffic (per stereo instance, per 32-sample frame)

| Direction | Count | Derivation |
|---|---|---|
| reads | **24** (12-tap sinc × 2 channels) | `Delay.h:365-378` (3×4 SIMD lanes = 12 taps/channel) |
| writes | **64** (32 samples × 2 channels) | `Delay.h:434-441` |
| total | 88 accesses/frame/instance | counted by the RTL sim (`er`/`ew` trace fields) and the model (`ext_reads`/`ext_writes`) |

vs SXT-016 `probe_fx_delay` (E1/E2/E3): the probe's logical 6r+2w
undercounted the physical tap reads (24r) and its naive-physical 24r+2w
matches this measurement's read count; the write count here is 64 words
(32 samples × 2 channels) — the probe's per-frame accounting used the same
per-sample frame basis. Reconciliation: the SXT-016 "window cache" estimate
(~2r+2w with a 4-word cache line) does NOT apply to this tap pattern (the
12-tap window spans 12 consecutive words = 3 cache lines) — the measured
24r+2w stands as the physical bound; a line-placed burst cache would fetch
12 consecutive words per tap window (≤ 4 lines of 64 B per channel per
sample, amortizable across the 32-sample frame to ~12 line fills = 768 B
read/frame/instance worst case, 1,536 B/frame for stereo).

## Burst shape

Reads: 12-consecutive-word windows per channel per sample (48 B), two
windows per sample, stride between windows = 1 sample of line advance.
Writes: 32-consecutive-word bursts per channel per frame (128 B), aligned
to the ring position `wpos` (wraps every 8,192 frames).

## Latency tolerance

The behavioral model assumes 0-cycle reads. Tolerance analysis: the tap
window for sample k is known as soon as `v(k)` (the lag state) is computed —
one lag step before the 12 reads — so a synchronous external memory with
read latency ≤ 1 lag-step-to-use gap (≥ 1 sample time, 20.8 µs at 48 kHz)
is tolerable IF the 12 reads of a tap are issued immediately after the lag
step (they are, in schedule order). Writes have no consumer within the
frame (the tap window never reaches the write position: max read offset =
wpos − 32 vs write at wpos) — write latency tolerance = unbounded within a
frame. A longer-latency DRAM (≥ 32 samples) requires the double-buffer
window cache described above; the traffic budget then stays 24r+2w logical,
12 line-fill bursts physical.
