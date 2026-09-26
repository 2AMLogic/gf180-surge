"""SXT-016 probe: 3-band parametric EQ kernel.

CANDIDATE-ARITHMETIC COST ESTIMATOR following the STRUCTURE of the pinned
EQ effect (read and cited; no GPL code copied):

surge@58914e59 src/common/dsp/effects/ParametricEQ3BandEffect.cpp
(three cascaded biquad bands; no delay line - SXT-015 fx_classes
"ParametricEQ3BandEffect: 3 biquads, no delay line"). Band filters are
the engine's BiquadFilter (TDF2 form; sst-filters BiquadFilter.h,
file-level cite, sst-filters@e92d93a).

Modeled: 3 TDF2 biquads x stereo; block-rate parameter-change detection
and coefficient recompute path (rare, costed separately); per-sample
coefficient interpolation variant as a candidate (NOT pinned behavior).

No external memory (state below the 64 KiB threshold; stays on-chip).
"""
from .common import (AUDIO_BITS_CANDIDATE, CLOCK_CANDIDATES_HZ, COEFF_BITS,
                     OpCounter, TECH, closure, op_cycles)

PROBE = "probe_fx_eq"

CITES = [
    "surge@58914e59 src/common/dsp/effects/ParametricEQ3BandEffect.cpp "
    "(3-band parametric EQ, biquad per band, wet path only)",
    "sst-filters@e92d93a include/sst/filters/BiquadFilter.h "
    "(BiquadFilter TDF2; file-level cite)",
    "SXT-015 model/resources/fx_classes.py _NO_LONG_BUFFER['EQ']",
]


def tdf2_biquad(o):
    # y = b0*x + s1 ; s1 = b1*x - a1*y + s2 ; s2 = b2*x - a2*y
    for _ in range(5):
        o.mul(AUDIO_BITS_CANDIDATE)
    for _ in range(4):
        o.add(AUDIO_BITS_CANDIDATE)
    o.sram_r()  # state read (s1,s2 folded into the access count per word)
    o.sram_r()
    o.sram_w()
    o.sram_w()


def run(outdir):
    from .emit import build_record, write_record
    paths = []
    for mult in ("M18", "M32"):
        for reload in ("block", "per_sample"):
            o = OpCounter()
            for _ in range(3):        # bands
                for _ in range(2):    # channels
                    tdf2_biquad(o)
                    if reload == "per_sample":
                        for _ in range(5):
                            o.mul(COEFF_BITS)
                            o.add(COEFF_BITS)
            # block-rate parameter-change check (3 compares/frame)
            for _ in range(3):
                o.cmp()
            logic = op_cycles(o, mult)
            cpf = logic
            st = {"biquad_state": 3 * 2 * 2 * AUDIO_BITS_CANDIDATE,
                  "coeffs": 3 * 5 * COEFF_BITS}
            rec = build_record(
                probe=PROBE, kernel="eq3band_tdf2_" + reload + "_coeffs",
                word_lengths={"audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=False,
                memory_model={"name": "onchip_1rw_sram",
                              "onchip_sram": TECH["onchip_sram"],
                              "external": {"name": "none",
                                           "detail": "state below the "
                                                     "external threshold; "
                                                     "on-chip"}},
                assumptions=[
                    TECH["multipliers"][mult]["assumption"], TECH["adder"],
                    TECH["onchip_sram"], TECH["division"], TECH["clock"],
                    "Reload mode modeled: %s." % (
                        "per-sample coefficient interpolation (candidate, "
                        "NOT pinned behavior)" if reload == "per_sample"
                        else "block-rate coefficient set (pinned behavior; "
                             "coeff recompute on param change is a rare "
                             "path, ~60 ops per changed band, excluded "
                             "from the per-frame count)"),
                ],
                citations=CITES, ops=o.ops_dict(), cycles_per_frame=cpf,
                state_ram_bits=sum(st.values()), ext_bytes_per_frame=0,
                closure_at_clocks={c: closure(c, cpf)
                                   for c in CLOCK_CANDIDATES_HZ},
                sxt015_replacement={
                    "replaces": "cyc_fxgeneric_frame (for the EQ class "
                                "instance)",
                    "sxt015_value": 800,
                    "scope": "per stereo EQ instance per frame",
                },
                extra={"state_bits_detail": st,
                       "rare_path_coeff_recompute_ops_per_band":
                           "approximately 60 (3 table lookups + 12 mul + "
                           "adds), executed only on parameter change"})
            paths.append(write_record(rec, outdir))
    return paths
