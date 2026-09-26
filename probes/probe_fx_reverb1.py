"""SXT-016 probe: Reverb1 composite kernel + fixed-point stability analysis.

CANDIDATE-ARITHMETIC COST ESTIMATOR following the STRUCTURE of the pinned
sst Reverb1 (read and cited; no GPL code copied):

sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b
include/sst/effects/Reverb1.h (lines as pinned in SXT-015):
- revbits=15 => max_rev_dly=32768; rev_tap_bits=4 => rev_taps=16
  (Reverb1.h:122-131 region; SXT-015 params.reverb1_*)
- composite interleaved line delay[rev_taps * max_rev_dly]; tap t read at
  t + ((delay_pos - (delay_time[t]>>8)) & (max_rev_dly-1)) << rev_tap_bits
- per sample: 16 tap reads -> per-tap one-pole damping
  out_tap = damp*out_tap + (1-damp)*new; feedback fb = -2/16 * sum(out_tap)
  + predelay[(delay_pos - pdtime) & mask]; delay_pos++;
  predelay[delay_pos] = 0.5*(L+R); per-tap write
  delay[(delay_pos<<4)+t] = delay_fb[t]*(fb + out_tap[t]);
  stereo pan sums over taps; then 3 wet biquads (locut/band1/hicut),
  width, mix fade.
- coefficients (delay_time preset tables, delay_fb from decay time) are
  recomputed at control rate on parameter change (rare path).

Buffer traffic classes (acceptance: external bandwidth, not just logic):
- composite tap array: 16 reads + 16 writes per frame, STRIDE rev_taps
  words (64 B) => scattered single-word accesses, bursts of 1
- predelay line: 1 read + 1 write per frame (single-word)
Reconciles SXT-015 _PINNED_TX['reverb1'] = 17r + 17w (matches: 16+1 r,
16+1 w).

Fixed-point stability guard-band analysis (pure math, deterministic):
- zero-latency loop (conservative upper bound; actual taps have >=1
  sample of line delay): out -> tap -> damping -> fb -> tap.
  Uniform damping q: loop matrix = q*(I - (1/8)*11^T) has spectral
  radius exactly q (eigenvalue q*(1-2) on the all-ones vector, q on the
  orthogonal complement).
- Non-uniform delay_fb (per-tap decay differs): spectral radius of
  D*(I - (1/8)*11^T) by power iteration (fixed 200 iterations, rounded
  to 6 decimals) over the worst preset (shape 3) x decay range.
- Quantization noise amplification ~ 1/(1-rho) => guard bits; internal
  word width = audio 24 + guard bits.
"""
from .common import (AUDIO_BITS_CANDIDATE, CLOCK_CANDIDATES_HZ, COEFF_BITS,
                     FS_HZ, MEM_WORD_BYTES, OpCounter,
                     TECH, closure, ext_access_cycles,
                     op_cycles)

PROBE = "probe_fx_reverb1"
REVBITS = 15
MAX_REV_DLY = 1 << REVBITS       # 32768 (Reverb1.h:122; SXT-015 pin)
REV_TAPS = 16                    # rev_tap_bits=4 (Reverb1.h:124; SXT-015 pin)
PREDELAY_BITS = REVBITS          # predelay[max_rev_dly] (Reverb1.h:130)

CITES = [
    "sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b "
    "include/sst/effects/Reverb1.h ::processBlock (16 composite taps, "
    "per-tap one-pole damping, fb = -2/16*sum + predelay read, per-tap "
    "feedback write delay[(delay_pos<<4)+t], pan sums, 3 wet biquads, "
    "width/mix)",
    "sst-effects@adcac695 include/sst/effects/Reverb1.h:122-131 "
    "(revbits=15, rev_taps=16, delay[16*32768]+predelay[32768]; SXT-015 pin)",
    "SXT-015 model/resources/fx_classes.py _PINNED_TX['reverb1'] = 17r+17w",
]

# Preset shape 3 raw delay_time values (STRUCTURE fact: worst preset has the
# largest max delay; exact values are preset data in Reverb1.h loadpreset).
# We use the delay_time RANGE (>>8 applied in process) not the raw list; the
# stability analysis needs only the per-tap decay gains, swept below.
SHAPE3_MAX_DT_SHIFTED = 2711583 >> 8  # largest composite tap index (samples)


def reverb_frame_ops(o):
    """One output frame (stereo instance), pinned processBlock structure."""
    # 16 tap reads (scattered; counted in traffic classes below)
    for _ in range(REV_TAPS):
        # damping one-pole: out_tap = damp*out_tap + (1-damp)*new
        o.mul(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
    # fb = -2/16 * sum(out_tap) + predelay[...] (15 adds, 2 mul, 1 add)
    for _ in range(REV_TAPS - 1):
        o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    # predelay input: 0.5*(L+R)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    # 16 tap writes: delay[..] = delay_fb[t]*(fb + out_tap[t])
    for _ in range(REV_TAPS):
        o.add(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
    # pan sums: L += ot*panL, R += ot*panR (32 mul, 30 adds)
    for _ in range(REV_TAPS):
        o.mul(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
    for _ in range(REV_TAPS - 1):
        o.add(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
    # 3 wet biquads (TDF2) x stereo
    for _ in range(3):
        for _ in range(2):
            for _ in range(5):
                o.mul(AUDIO_BITS_CANDIDATE)
            for _ in range(4):
                o.add(AUDIO_BITS_CANDIDATE)
    # width + mix fade (stereo)
    for _ in range(4):
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)


def reverb_state_bits():
    small = {"out_tap": REV_TAPS * AUDIO_BITS_CANDIDATE,
             "delay_fb": REV_TAPS * COEFF_BITS,
             "delay_pan_L": REV_TAPS * COEFF_BITS,
             "delay_pan_R": REV_TAPS * COEFF_BITS,
             "biquads": 3 * 2 * 2 * AUDIO_BITS_CANDIDATE,
             "delay_pos": REVBITS}
    lines = {"composite_taps": REV_TAPS * MAX_REV_DLY * AUDIO_BITS_CANDIDATE,
             "predelay": MAX_REV_DLY * AUDIO_BITS_CANDIDATE}
    return small, lines


# ---------------------------------------------------------------------------
# Stability guard-band analysis (deterministic; fixed iterations)
# ---------------------------------------------------------------------------
def _uniform_rho():
    """Uniform per-tap gain q: closed form rho = q (see module docstring)."""
    return 1.0  # sup over q in (0,1) is approached as q -> 1


def _nonuniform_rho(dfb_list, iterations=200):
    """Power iteration on the zero-latency loop matrix
    M = D (I - (1/8) 11^T) with D = diag(dfb). Returns largest |eigenvalue|
    estimate, rounded to 6 decimals. Deterministic (fixed start vector,
    fixed iteration count)."""
    n = len(dfb_list)
    v = [1.0 / n] * n
    for _ in range(iterations):
        # y = (I - (1/8) 11^T) v
        s = sum(v)
        y = [v[i] - 0.125 * s for i in range(n)]
        # v' = D y
        v2 = [dfb_list[i] * y[i] for i in range(n)]
        norm = sum(x * x for x in v2) ** 0.5
        if norm == 0:
            return 0.0
        v = [x / norm for x in v2]
    s = sum(v)
    y = [v[i] - 0.125 * s for i in range(n)]
    v2 = [dfb_list[i] * y[i] for i in range(n)]
    return round(sum(x * x for x in v2) ** 0.5, 6)


def stability_analysis():
    """Guard-band analysis for 24-bit audio words. Returns a dict."""
    # delay_fb[t] = 10^(0.05*-60)^(dt/(256*sr*2^decay)); sweep decay over the
    # parameter range (-4..6) and the worst-preset tap-time structure.
    import math
    worst = {"rho_uniform_sup": 1.0,
             "rho_nonuniform_max": 0.0,
             "decay_time_s_at_max": None}
    for decay in [x / 4.0 for x in range(-16, 25)]:  # -4..6 in 0.25 steps
        dfb = []
        for t in range(REV_TAPS):
            # normalized tap times of shape 3 (largest preset), 0..1
            x = (t + 1) / float(REV_TAPS)
            dt = SHAPE3_MAX_DT_SHIFTED * x
            gain = math.pow(10.0, -3.0 * dt / (256.0 * 48000.0 * math.pow(2.0, decay)))
            dfb.append(gain)
        r = _nonuniform_rho(dfb)
        if r > worst["rho_nonuniform_max"]:
            worst["rho_nonuniform_max"] = r
            worst["decay_time_s_at_max"] = decay
    rho = worst["rho_nonuniform_max"]
    noise_gain = 1.0 / (1.0 - rho) if rho < 1 else float("inf")
    guard_bits = int(math.ceil(math.log2(noise_gain))) if noise_gain > 1 else 0
    return {
        "loop_model": "zero-latency composite loop (conservative upper "
                      "bound; actual taps carry >=1 sample of line delay)",
        "uniform_damping_closed_form": "rho = q exactly (q*(1-2) on the "
                                       "all-ones eigenvector; q on the "
                                       "orthogonal complement); q<1 is "
                                       "the stability condition",
        "rho_uniform_sup": _uniform_rho(),
        "rho_nonuniform_power_iteration": worst,
        "power_iterations": 200,
        "quantization_noise_amplification": round(noise_gain, 3),
        "required_guard_bits": guard_bits,
        "recommended_internal_word_bits": AUDIO_BITS_CANDIDATE + guard_bits,
        "note": "guard band: keep the internal reverb word at 24+%d bits "
                "and |delay_fb|<1; the damping one-pole (damp in "
                "[0.01,0.99]) further attenuates and is part of the loop "
                "only through its |damp|<1 bound" % guard_bits,
        "limit_cycle_note": "fixed-point recirculation needs a dither or "
                            "decay-floor LSB to avoid dead/limit-cycle "
                            "tails; NOT modeled numerically here (SXT-024 "
                            "model work)",
    }


def run(outdir):
    from .emit import build_record, write_record
    paths = []
    small, lines = reverb_state_bits()
    stability = stability_analysis()

    for mult in ("M18", "M32"):
        o = OpCounter()
        reverb_frame_ops(o)
        logic = op_cycles(o, mult)
        for ext in ("E1", "E2", "E3"):
            # traffic: 16 scattered tap reads + 16 tap writes (bursts of 1,
            # stride rev_taps words = 64 B) + predelay 1r + 1w
            tap_r = ext_access_cycles(1, ext, contiguous_burst=False) * REV_TAPS
            tap_w = ext_access_cycles(1, ext, contiguous_burst=False) * REV_TAPS
            pd = ext_access_cycles(1, ext, contiguous_burst=False) * 2
            mem_cycles = tap_r + tap_w + pd
            cpf = logic + mem_cycles
            words = (REV_TAPS * 2 + 2)
            bytes_frame = words * MEM_WORD_BYTES
            rec = build_record(
                probe=PROBE, kernel="reverb1_composite_ext_" + ext,
                word_lengths={"audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=False,
                memory_model={
                    "name": "onchip_1rw_sram+" + ext,
                    "onchip_sram": TECH["onchip_sram"],
                    "external": {"name": ext,
                                 "detail": TECH["external"][ext]["assumption"]},
                },
                assumptions=[
                    TECH["multipliers"][mult]["assumption"], TECH["adder"],
                    TECH["onchip_sram"], TECH["division"], TECH["clock"],
                    TECH["external"][ext]["assumption"],
                    "Composite tap array and predelay line are external "
                    "writable memory (>64 KiB policy, SXT-015); processing "
                    "stays on-chip. Tap accesses are single-word, stride "
                    "64 B: no burst benefit (burst efficiency 1 word per "
                    "64 B bus burst on a 16-bit bus).",
                    "Latency tolerance is LOW: 33 of the accesses are "
                    "consumed in the same frame (16 tap reads + predelay "
                    "read feed the same sample's feedback write); the "
                    "model charges full access latency per access.",
                    "Control-rate coefficient recompute (decay/size/shape "
                    "change; delay_fb pow and preset tables) excluded from "
                    "the per-frame count (rare path).",
                ],
                citations=CITES, ops=o.ops_dict(), cycles_per_frame=cpf,
                state_ram_bits=sum(small.values()),
                ext_bytes_per_frame=bytes_frame,
                closure_at_clocks={c: closure(c, cpf)
                                   for c in CLOCK_CANDIDATES_HZ},
                sxt015_replacement={
                    "replaces": "cyc_fxreverb1_frame + reverb1 traffic "
                                "confirmation",
                    "sxt015_value": 2600,
                    "scope": "per Reverb1 instance per frame (stereo)",
                },
                extra={
                    "buffer_traffic_classes": {
                        "composite_taps": {"words_per_frame": REV_TAPS * 2,
                                           "access_pattern": "scattered, "
                                                             "stride 64 B",
                                           "burst_efficiency": "1 word"},
                        "predelay_line": {"words_per_frame": 2,
                                          "access_pattern": "single word "
                                                            "at (delay_pos)"
                                                            " and sliding "
                                                            "read"},
                        "total_words_per_frame": words,
                        "total_bytes_per_frame": bytes_frame,
                        "bytes_per_s_at_48k": bytes_frame * FS_HZ,
                        "sxt015_logical_words_per_frame": {"reads": 17,
                                                           "writes": 17,
                                                           "reconciliation":
                                                               "matches: "
                                                               "16 tap + 1 "
                                                               "predelay "
                                                               "each way"},
                    },
                    "state_lines_bits": lines,
                    "small_state_bits": small,
                    "fixed_point_stability_guard_band": stability,
                    "latency_bound_cycles_per_frame": mem_cycles,
                })
            paths.append(write_record(rec, outdir))
    return paths
