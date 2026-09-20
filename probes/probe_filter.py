"""SXT-016 probe: per-voice filter kernels (SVF-style + nonlinear-ladder-style).

CANDIDATE-ARITHMETIC COST ESTIMATOR following the STRUCTURE of the pinned
Surge filter units (read and cited; no GPL code copied):

- SVF topology (svf_tdf2): two cascaded state-variable halves with
  block-set F1/F2/Q coefficients, per the pinned engine's vectorized SVF:
  surge@58914e59 src/common/dsp/filters/VectorizedSVFilter.h (CalcBPF:
  L1 += F1*B1; H1 = In*Q - L1 - Q*B1; B1 += F1*H1; x2 stages).
  Coefficient reload paths costed both ways: block-rate set (engine
  behavior) and per-sample coefficient interpolation (the engine's
  QuadFilterUnit C += dC convention, sst-filters
  FilterCoefficientMaker/QuadFilterUnit_Impl, file-level cite,
  sst-filters@e92d93a).

- Nonlinear ladder-style topology (k35_ladder): two 1-pole stages with a
  per-sample tanh nonlinearity and feedback combine, per the pinned
  sst-filters K35 structure (July's "LP K35" filter unit):
  sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6
  include/sst/filters/K35Filter.h (process_lp: per-sample coefficient
  interpolation C[i]+=dC[i]; doLpf 1-pole; s35 feedback combine; alpha;
  fasttanhSSEclamped per-sample nonlinearity; blend; second doLpf; doHpf).
  The tanh is costed both as a 256-entry LUT+interp candidate and as a
  polynomial candidate (sst basic-blocks FastMath, file-level cite).
  Surge's full ladder families (DiodeLadder, VintageLadders,
  NonlinearFeedbackLadder in sst-filters) share this shape: N 1-pole
  stages + per-stage or per-loop nonlinearity; K35 is the modeled
  representative, NOT a substitute claim for the others (SXT-027).

No synthesis has been run; numbers are relative estimates under the
named assumptions in each record (probes/common.py TECH).
"""
from .common import (AUDIO_BITS_CANDIDATE, CLOCK_CANDIDATES_HZ, COEFF_BITS,
                     FS_HZ, OpCounter, TECH, closure, op_cycles)

PROBE = "probe_filter"

CITES_SVF = [
    "surge@58914e59 src/common/dsp/filters/VectorizedSVFilter.h "
    "(CalcBPF: two cascaded SVF halves, vFloat F1/F2/Q coefficients)",
    "sst-filters@e92d93a include/sst/filters/QuadFilterUnit_Impl.h + "
    "FilterCoefficientMaker_Impl.h (per-sample C += dC interpolation "
    "convention; file-level cite)",
]
CITES_K35 = [
    "sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6 "
    "include/sst/filters/K35Filter.h (process_lp: 8-coefficient per-sample "
    "interpolation; doLpf; s35 combine; alpha; fasttanhSSEclamped "
    "nonlinearity; blend; doLpf2; doHpf)",
    "surge@58914e59 (filter unit mapping: 'LP K35' preset id, "
    "SXT-015 corpus graphs fu[].tn)",
    "sst-basic-blocks@a32b8aec FastMath tanh (file-level cite)",
]


# ---------------------------------------------------------------------------
# SVF kernel (VectorizedSVFilter.h CalcBPF structure, scalar)
# ---------------------------------------------------------------------------
def svf_sample(o, per_sample_coeffs):
    # stage 1: L1 += F1*B1; H1 = In*Q - L1 - Q*B1; B1 += F1*H1
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)   # In*Q
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)   # Q*B1
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)   # F1*H1
    o.add(AUDIO_BITS_CANDIDATE)
    # stage 2 (same shape, driven by B1)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    if per_sample_coeffs:
        # coefficient interpolation path: 3 lerps (C += dC style)
        for _ in range(3):
            o.mul(COEFF_BITS)
            o.add(COEFF_BITS)


def k35_sample(o, tanh_impl):
    # per-sample coefficient interpolation (8 coefficients, K35 processCoeffs)
    for _ in range(8):
        o.add(COEFF_BITS)
    # y1 = doLpf(G, in, z1): (in - z1)*G + z1; z1 = v + result
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    # s35 = lb*z2 + hb*z1
    o.mul(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    # u_clean = alpha*(y1 + s35)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    # nonlinearity: tanh(u_clean * saturation)
    o.mul(AUDIO_BITS_CANDIDATE)
    if tanh_impl == "lut":
        o.lut("tanh_table", 256)
        o.lut("tanh_table", 256)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
    else:  # polynomial (FastMath-style)
        for _ in range(4):
            o.mul(AUDIO_BITS_CANDIDATE)
        for _ in range(3):
            o.add(AUDIO_BITS_CANDIDATE)
        o.cmp()
    # blend clean/driven
    o.mul(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    # y = k * doLpf(G, u, z2)
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    # doHpf: y - doLpf(G, y, z3)
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.sub(AUDIO_BITS_CANDIDATE)
    # result scale: mul by precomputed 1/k (A-ALU-2: no division)
    o.mul(AUDIO_BITS_CANDIDATE)


def svf_state():
    return {"L1": AUDIO_BITS_CANDIDATE, "B1": AUDIO_BITS_CANDIDATE,
            "L2": AUDIO_BITS_CANDIDATE, "B2": AUDIO_BITS_CANDIDATE,
            "F1": COEFF_BITS, "F2": COEFF_BITS, "Q": COEFF_BITS}


def k35_state():
    return {"lz": AUDIO_BITS_CANDIDATE, "hz": AUDIO_BITS_CANDIDATE,
            "z2": AUDIO_BITS_CANDIDATE,
            "coeffs_8": 8 * COEFF_BITS,
            "dcoeffs_8": 8 * COEFF_BITS}


# ---------------------------------------------------------------------------
def run(outdir):
    from .emit import build_record, write_record
    paths = []

    def assumptions(mult, extra):
        return [
            TECH["multipliers"][mult]["assumption"],
            TECH["adder"],
            TECH["onchip_sram"],
            TECH["table_rom"],
            TECH["division"],
            TECH["simd"],
            TECH["clock"],
            "Mono per-voice filter unit; the engine processes 4 voices per "
            "SIMD lane (QuadFilterUnit) - scalar single-lane modeled "
            "(A-SCHED-1). Cutoff/resonance coefficient math at 32-bit; "
            "block-rate coefficient recompute (fasttan/exp via table) is "
            "amortized to <1 cycle/sample and NOT included per-sample.",
        ] + extra

    for mult in ("M18", "M32"):
        for reload_mode in ("block", "per_sample"):
            o = OpCounter()
            for _ in range(64):  # BLOCK_SIZE_OS OS samples -> 32 output samples
                svf_sample(o, reload_mode == "per_sample")
            cps = round(op_cycles(o, mult) / 32.0, 1)
            cpf = int(round(cps * FS_HZ))
            st = svf_state()
            rec = build_record(
                probe=PROBE, kernel="svf_tdf2_" + reload_mode + "_coeffs",
                word_lengths={"audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=False,
                memory_model={"name": "onchip_1rw_sram",
                              "onchip_sram": TECH["onchip_sram"],
                              "external": {"name": "none",
                                           "detail": "no external memory"}},
                assumptions=assumptions(mult, [
                    "Reload mode modeled: %s." % (
                        "per-sample coefficient interpolation (C += dC)"
                        if reload_mode == "per_sample" else
                        "block-rate coefficient set (VectorizedSVFilter "
                        "SetCoeff convention); the other mode is a separate "
                        "record."),
                ]),
                citations=CITES_SVF,
                ops=o.ops_dict(), cycles_per_frame=cpf, per_sample=cps,
                state_ram_bits=sum(st.values()), ext_bytes_per_frame=0,
                closure_at_clocks={c: closure(c, cpf)
                                   for c in CLOCK_CANDIDATES_HZ},
                sxt015_replacement={
                    "replaces": "cyc_filter_unit_frame",
                    "sxt015_value": 150,
                    "scope": "per active filter unit per voice per frame; "
                             "SVF-style topology",
                },
                extra={"state_bits_detail": st})
            paths.append(write_record(rec, outdir))

        for tanh_impl in ("lut", "poly"):
            o = OpCounter()
            for _ in range(64):
                k35_sample(o, tanh_impl)
            cps = round(op_cycles(o, mult) / 32.0, 1)
            cpf = int(round(cps * FS_HZ))
            st = k35_state()
            rec = build_record(
                probe=PROBE, kernel="k35_ladder_tanh_" + tanh_impl,
                word_lengths={"audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=False,
                memory_model={"name": "onchip_1rw_sram",
                              "onchip_sram": TECH["onchip_sram"],
                              "external": {"name": "none",
                                           "detail": "no external memory"}},
                assumptions=assumptions(mult, [
                    "Nonlinearity implementation: %s." % (
                        "256-entry tanh LUT + linear interpolation, per-sample"
                        if tanh_impl == "lut" else
                        "FastMath-style tanh polynomial, per-sample"),
                    "Per-sample coefficient interpolation is part of the "
                    "pinned K35 structure (processCoeffs C[i]+=dC[i]) and is "
                    "included; the division in process_lp is replaced by "
                    "multiply-by-precomputed-inverse (A-ALU-2).",
                ]),
                citations=CITES_K35,
                ops=o.ops_dict(), cycles_per_frame=cpf, per_sample=cps,
                state_ram_bits=sum(st.values()), ext_bytes_per_frame=0,
                closure_at_clocks={c: closure(c, cpf)
                                   for c in CLOCK_CANDIDATES_HZ},
                sxt015_replacement={
                    "replaces": "cyc_filter_unit_frame",
                    "sxt015_value": 150,
                    "scope": "per active filter unit per voice per frame; "
                             "nonlinear-ladder-style topology (K35 shape)",
                },
                extra={"state_bits_detail": st,
                       "per_sample_nonlinearity": True})
            paths.append(write_record(rec, outdir))
    return paths
