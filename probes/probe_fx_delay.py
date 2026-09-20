"""SXT-016 probe: stereo Delay kernel + external-memory transaction model.

CANDIDATE-ARITHMETIC COST ESTIMATOR following the STRUCTURE of the pinned
sst Delay (read and cited; no GPL code copied):

sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b
include/sst/effects/Delay.h (lines as pinned in SXT-015):
- max_delay_length = 1<<18 per channel; buffer[2][max+FIRipol_N]
  (Delay.h:200 region; SXT-015 params.delay_max_length_samples)
- per sample, per channel: time lag process; integer+fractional delay time;
  read pointer (wpos - i_dtime - FIRoffset) & mask; sinc index from
  FIRipol_M=256 phases; 12-tap FIR dot product (3x SSE = 12 taps);
- stereo crossfeed MAC, feedback MAC with per-block clipping modes,
  LP/HP biquads inside the feedback loop; 32-sample block writes per
  channel; FIR wrap copy of FIRipol_N words when wpos wraps.

External-memory model (the acceptance requirement: bandwidth to external
memory, not just logic):
- logical transactions: SXT-015 counts 6 reads + 2 writes per frame per
  stereo instance (fx_classes._PINNED_TX["delay"]) -- a LOGICAL
  interpolated-tap read per channel plus crossfeed reads.
- physical naive: the 12-tap FIR needs 12 consecutive words per channel
  per sample => 24 reads + 2 writes per frame if every tap is fetched.
- physical streaming (named assumption A-EXT-BUF below): the 12-word
  read window slides by ~1 word per sample, so a small on-chip window
  buffer refilled by sequential burst needs ~1 word/frame/channel
  sustained, with occasional 12-word re-seek bursts when the delay time
  jumps (tempo sync change, LFO direction flip, param edit).
Latency tolerance: tap reads are consumed in the same frame; slack is
created by the window buffer, quantified per E-model below.

Reconciles SXT-015's placeholder cyc_fxdelay_frame=900 with probe values
and re-states the traffic counts (logical vs physical).
"""
from .common import (AUDIO_BITS_CANDIDATE, CLOCK_CANDIDATES_HZ, COEFF_BITS,
                     FS_HZ, MEM_WORD_BYTES, OpCounter, SINC_TABLE_PHASES,
                     SINC_TAPS, TECH, closure, ext_access_cycles,
                     ext_sustained_bytes_per_s, op_cycles)

PROBE = "probe_fx_delay"
DELAY_MAX = 1 << 18  # engine constant, per channel (SXT-015 pin)

CITES = [
    "sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b "
    "include/sst/effects/Delay.h ::processBlock (per-channel 12-tap sinc "
    "read at (wpos - i_dtime - FIRipol_N/2) & mask; sinc index from "
    "FIRipol_M phases; block write of 32 samples/channel; crossfeed and "
    "feedback MACs; LP/HP biquads in the feedback loop; FIRipol_N-word "
    "wrap copy)",
    "sst-effects@adcac695 include/sst/effects/Delay.h:200 "
    "(max_delay_length{1<<18}; SXT-015 pin)",
    "surge@58914e59 src/common/SurgeStorage.h (FIRipol_M=256, FIRipol_N=12)",
    "SXT-015 model/resources/fx_classes.py _PINNED_TX['delay'] = 6r+2w "
    "(logical transactions, reconciled in this record)",
]


def delay_frame_ops(o, clip_mode="tanh"):
    """One output frame (1 sample, stereo) of delay processing.
    Tap reads/writes are EXTERNAL unless the on-chip variant is used."""
    for _ in range(2):          # per channel
        o.add(COEFF_BITS)       # time lag process
        o.mul(COEFF_BITS)
        o.add(32)               # int/fractional dtime extract + clamp
        o.cmp()
        o.shift(2)
        # 12-tap FIR: 12 sinc table + 12 line reads + 12 MAC
        for _ in range(SINC_TAPS):
            o.lut("sinctable_1x", SINC_TABLE_PHASES * SINC_TAPS)
            o.mul(AUDIO_BITS_CANDIDATE)
            o.add(AUDIO_BITS_CANDIDATE)
        # (12 contiguous line reads counted in the memory model below)
    # negative feedback flip (worst)
    o.sub(AUDIO_BITS_CANDIDATE)
    o.sub(AUDIO_BITS_CANDIDATE)
    # feedback clipping (worst = tanh mode, 2 ch)
    if clip_mode == "tanh":
        for _ in range(2):
            for _ in range(4):
                o.mul(AUDIO_BITS_CANDIDATE)
            for _ in range(3):
                o.add(AUDIO_BITS_CANDIDATE)
            o.cmp()
    # feedback loop filters: LP + HP biquads (TDF2), stereo
    for _ in range(2):          # two filters
        for _ in range(2):      # two channels
            for _ in range(5):
                o.mul(AUDIO_BITS_CANDIDATE)
            for _ in range(4):
                o.add(AUDIO_BITS_CANDIDATE)
    # input pan (trixpan), feedback MAC, crossfeed MAC
    for _ in range(2):
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)   # pan
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)   # feedback MAC
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)   # crossfeed MAC
    # width + mix fade
    for _ in range(4):
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)


def delay_state_bits():
    # per-instance small state; the 2 x 2^18-sample LINE is the external
    # (or huge on-chip) buffer counted separately in bits.
    small = {"time_lag_L": COEFF_BITS, "time_lag_R": COEFF_BITS,
             "lfophase": COEFF_BITS, "LFOval": COEFF_BITS,
             "wpos": 18,
             "biquad_lp": 4 * AUDIO_BITS_CANDIDATE,
             "biquad_hp": 4 * AUDIO_BITS_CANDIDATE}
    line_bits = 2 * DELAY_MAX * AUDIO_BITS_CANDIDATE
    return small, line_bits


EXT_BUF_ASSUMPTION = (
    "A-EXT-BUF: sliding-window line cache. The 12-tap FIR read window "
    "moves ~1 word/sample, so an on-chip (SINC_TAPS+slack)-word window "
    "per channel is refilled by a sequential burst; sustained external "
    "traffic ~1 word/frame/channel, with a 12-word re-seek burst when "
    "the delay time jumps (tempo-sync change, LFO direction flip, param "
    "edit; assumed <=1 re-seek per 256 frames, worst case every frame "
    "reported separately). Without this cache the physical traffic is "
    "24 words/frame (naive)."
)


def run(outdir):
    from .emit import build_record, write_record
    paths = []
    small, line_bits = delay_state_bits()

    for mult in ("M18", "M32"):
        # ---- logic ops (memory-port cycles counted separately) ----
        o = OpCounter()
        delay_frame_ops(o)
        logic_cycles = op_cycles(o, mult)

        # ---- variant: fully on-chip line (reference; 1.5 Mbit > policy
        #      threshold, shown as the on-chip bound) ----
        sram_cycles = 24 + 2  # 24 tap reads + 2 writes, serialized (A-MEM-1)
        cpf = logic_cycles + sram_cycles
        rec = build_record(
            probe=PROBE, kernel="delay_stereo_onchip_line",
            word_lengths={"audio_bits": AUDIO_BITS_CANDIDATE,
                          "coeff_bits": COEFF_BITS, "multiplier": mult},
            has_phase_accumulator=False,
            memory_model={"name": "onchip_1rw_sram",
                          "onchip_sram": TECH["onchip_sram"] + " "
                          "(line fully on-chip; read+write serialize)",
                          "external": {"name": "none",
                                       "detail": "line on-chip"}},
            assumptions=[
                TECH["multipliers"][mult]["assumption"], TECH["adder"],
                TECH["onchip_sram"], TECH["table_rom"], TECH["division"],
                TECH["clock"],
                "Worst-case feedback clipping mode (tanh) and both feedback "
                "filters active.",
            ],
            citations=CITES, ops=o.ops_dict(), cycles_per_frame=cpf,
            state_ram_bits=line_bits + sum(small.values()),
            ext_bytes_per_frame=0,
            closure_at_clocks={c: closure(c, cpf)
                               for c in CLOCK_CANDIDATES_HZ},
            sxt015_replacement={
                "replaces": "cyc_fxdelay_frame",
                "sxt015_value": 900,
                "scope": "per stereo Delay/FloatyDelay instance per frame "
                         "(on-chip-line variant; state retention per slot "
                         "per SXT-015)",
            },
            extra={
                "line_bits": line_bits,
                "small_state_bits": small,
                "note": "on-chip line exceeds the 64 KiB external-class "
                        "threshold; shown as the zero-wait bound, not a "
                        "policy-compliant candidate (SXT-015 policy)",
            })
        paths.append(write_record(rec, outdir))

        # ---- variants: line in external memory, E1/E2/E3 ----
        for ext in ("E1", "E2", "E3"):
            # naive: every FIR tap word fetched: 24 reads + 2 writes/frame
            naive_cycles = (ext_access_cycles(12, ext) * 2
                            + ext_access_cycles(1, ext) * 2)
            naive_bytes = (24 + 2) * MEM_WORD_BYTES
            # streaming: 1 word/frame/channel sustained + 2 writes
            stream_cycles = (ext_access_cycles(1, ext) * 2
                             + ext_access_cycles(1, ext) * 2)
            stream_bytes = 4 * MEM_WORD_BYTES
            # worst: re-seek burst every frame on top of streaming
            reseek = ext_access_cycles(12, ext)
            cpf_naive = logic_cycles + naive_cycles
            cpf_stream = logic_cycles + stream_cycles
            cpf_worst = logic_cycles + stream_cycles + reseek
            cpf = cpf_worst  # record the worst-case schedule; details below
            sustained = ext_sustained_bytes_per_s(48_000_000, ext)
            rec = build_record(
                probe=PROBE, kernel="delay_stereo_ext_" + ext,
                word_lengths={"audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=False,
                memory_model={
                    "name": "onchip_1rw_sram+window_cache+" + ext,
                    "onchip_sram": TECH["onchip_sram"]
                    + "; per-channel sliding window cache of "
                      "(FIRipol_N+4) words (A-EXT-BUF)",
                    "external": {"name": ext,
                                 "detail": TECH["external"][ext]["assumption"]},
                },
                assumptions=[
                    TECH["multipliers"][mult]["assumption"], TECH["adder"],
                    TECH["onchip_sram"], TECH["table_rom"], TECH["division"],
                    TECH["clock"],
                    TECH["external"][ext]["assumption"],
                    EXT_BUF_ASSUMPTION,
                    "cycles_per_frame reported is the WORST case (re-seek "
                    "burst every frame); sustained and naive variants are "
                    "in traffic_models below.",
                    "Two Delay slots = two instances with two separate "
                    "lines and two window caches (per-instance state is "
                    "never shared; plan section 3).",
                ],
                citations=CITES, ops=o.ops_dict(), cycles_per_frame=cpf,
                state_ram_bits=sum(small.values()) + 2 * (SINC_TAPS + 4) * AUDIO_BITS_CANDIDATE,
                ext_bytes_per_frame=stream_bytes,
                closure_at_clocks={c: closure(c, cpf)
                                   for c in CLOCK_CANDIDATES_HZ},
                sxt015_replacement={
                    "replaces": "cyc_fxdelay_frame + ext traffic re-pin for "
                                "delay",
                    "sxt015_value": 900,
                    "scope": "per stereo Delay instance per frame "
                             "(external-line variant " + ext + ")",
                },
                extra={
                    "traffic_reconciliation": {
                        "sxt015_logical_words_per_frame": {"reads": 6,
                                                           "writes": 2},
                        "physical_naive_words_per_frame": {"reads": 24,
                                                           "writes": 2,
                                                           "note": "12-tap "
                                                                   "FIR x 2 "
                                                                   "channels, "
                                                                   "no cache"},
                        "physical_streaming_words_per_frame": {
                            "reads": 2, "writes": 2,
                            "note": "A-EXT-BUF sliding window; sustained"},
                        "physical_worst_words_per_frame": {
                            "reads": 2 + 24, "writes": 2,
                            "note": "streaming + full 12-word re-seek burst "
                                    "per channel every frame"},
                        "note": "SXT-015 counted LOGICAL transactions "
                                "(interpolated tap = 1 word); physical "
                                "traffic depends on the named memory "
                                "model. Delay line state stays per-instance "
                                "(2 slots = 2 histories).",
                    },
                    "traffic_models": {
                        "naive": {"cycles_per_frame": cpf_naive,
                                  "ext_bytes_per_frame": naive_bytes,
                                  "ext_bytes_per_s_at_48k": naive_bytes * FS_HZ},
                        "streaming": {"cycles_per_frame": cpf_stream,
                                      "ext_bytes_per_frame": stream_bytes,
                                      "ext_bytes_per_s_at_48k": stream_bytes * FS_HZ},
                        "worst": {"cycles_per_frame": cpf_worst,
                                  "ext_bytes_per_frame": stream_bytes + 24 * MEM_WORD_BYTES,
                                  "ext_bytes_per_s_at_48k": (stream_bytes + 24 * MEM_WORD_BYTES) * FS_HZ},
                    },
                    "latency_tolerance": {
                        "reads_same_frame": True,
                        "window_slack_frames": 0,
                        "note": "tap reads are consumed in-frame; the "
                                "window cache covers " + ext + " latency "
                                "only while the next window is prefetched "
                                "during the previous frame. If external "
                                "latency exceeds one frame of slack the "
                                "pipeline stalls by the difference; at %s "
                                "first-access latency is %d cycles vs %d "
                                "sustained-access cycles/frame modeled."
                                % (ext, TECH["external"][ext]["latency_cycles"],
                                   stream_cycles),
                        "prefetch_guard": "delay time is block-ramped "
                                          "(timeL/timeR lag), so next-frame "
                                          "tap positions are predictable "
                                          "except at direction flips and "
                                          "tempo-sync changes",
                    },
                    "tempo_sync_note": "fractional taps: tempo-sync ratio "
                                       "rescales dtime (Delay.h setvars "
                                       "temposyncRatio); a tempo change "
                                       "moves the read window continuously "
                                       "-> covered by the streaming model; "
                                       "step changes are the worst case "
                                       "counted above",
                    "sustained_external_bytes_per_s_at_48mhz": sustained,
                })
            paths.append(write_record(rec, outdir))
    return paths
