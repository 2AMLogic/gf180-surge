"""SXT-016 probe: oscillator kernels (Classic, Sine, Wavetable).

CANDIDATE-ARITHMETIC COST ESTIMATOR. The kernels below are integer
reference schedules written from first principles following the STRUCTURE
of the pinned Surge oscillators (read and cited; no GPL code copied):

- Classic: abstract-BLIT oscillator -- a 4-impulse saw/pulse/sub state
  machine, each impulse convolved with a 12-tap windowed-sinc kernel from
  a 256-phase table into a ring buffer, followed by per-OS-sample
  extraction (keytracked 1-pole HPF, DC correction, 3-coefficient
  character biquad).
  surge@58914e59 src/common/dsp/oscillators/ClassicOscillator.cpp
  (ClassicOscillator::convolute, ::process_block; AbstractBlitOscillator);
  src/common/globals.h (OSC_OVERSAMPLING=2, BLOCK_SIZE_OS=64,
  OB_LENGTH=128); src/common/SurgeStorage.h (FIRipol_M=256, FIRipol_N=12).
  NOTE: the SXT-016 issue text glossed Classic as "windowed naive
  saw/pulse + LP"; the pinned engine structure is the BLIT convolution
  above. This probe costs the PINNED STRUCTURE (classic_blit) and also
  the cheaper glossed candidate (naive_polyblep) as a labeled
  adaptation-candidate whose sound would differ (fidelity risk, not a
  support claim).

- Sine: phase accumulator + sine evaluation + per-unison feedback and
  block-rate omega ramp. The pinned engine evaluates sine/cosine with an
  sst FastMath polynomial (SineOscillator.cpp process_block_internal,
  fastsinSSE/fastcosSSE); this probe costs BOTH the pinned polynomial
  structure (sine_poly) and a table+linear-interp candidate (sine_table)
  as named in the issue text.

- Wavetable: BLIT convolution + per-impulse morph-interpolated table
  value from a mip-selected table level.
  surge@58914e59 src/common/dsp/oscillators/WavetableOscillator.cpp
  (::convolute mip selection by phase increment, deformContinuous /
  deformLegacy 2-table linear morph, distort_level saturate; storage
  TableF32WeakPointers[mip][table][pos]).
  A direct per-sample "mip-select + linear interp" playback candidate
  (as glossed in the issue) is also costed (wt_direct) and flagged as an
  adaptation candidate with different aliasing behavior.

All outputs are ESTIMATES under the named assumptions in each record;
no synthesis has been run (see TECH in probes/common.py).
"""
from .common import (AUDIO_BITS_CANDIDATE, BLOCK_SIZE, BLOCK_SIZE_OS,
                     CLOCK_CANDIDATES_HZ, COEFF_BITS, FS_HZ, OpCounter,
                     OSC_OVERSAMPLING, PHASE_BITS_CANDIDATES,
                     SINC_TABLE_PHASES, SINC_TAPS, TECH, closure, op_cycles)

PROBE = "probe_osc"
FIR_OPS = dict(lut=2 * SINC_TAPS, mul=2 * SINC_TAPS, add=2 * SINC_TAPS)

# Named pitch corners for the impulse-rate (cycles/sample depends on it).
PITCH_CORNERS = [
    (261.626, "C4 261.63 Hz"),
    (4186.008, "C8 4186.01 Hz"),
    (8372.016, "MIDI 120 8372.02 Hz (worst modeled)"),
]
OB_LENGTH = BLOCK_SIZE_OS * 2  # globals.h: OB_LENGTH = BLOCK_SIZE_OS << 1 = 128

CITES_CLASSIC = [
    "surge@58914e59 src/common/dsp/oscillators/ClassicOscillator.cpp "
    "::convolute (4-impulse state machine; 12-tap windowed-sinc FIR from "
    "sinctable into oscbuffer/dcbuffer)",
    "surge@58914e59 src/common/dsp/oscillators/ClassicOscillator.cpp "
    "::process_block (extraction: keytracked 1-pole HPF integrator_hpf, "
    "DC correction, character biquad charFilt, per OS sample)",
    "surge@58914e59 src/common/globals.h (OSC_OVERSAMPLING=2, "
    "BLOCK_SIZE_OS=64, OB_LENGTH=128, MAX_UNISON=16)",
    "surge@58914e59 src/common/SurgeStorage.h (FIRipol_M=256, "
    "FIRipol_N=12, FIRoffset=6)",
]
CITES_SINE = [
    "surge@58914e59 src/common/dsp/oscillators/SineOscillator.cpp "
    "::process_block_internal (phase += omega ramp; fastsinSSE/fastcosSSE "
    "polynomial evaluation; mode shaping valueFromSinAndCosForMode; "
    "unison feedback lastvalue[0/1])",
    "surge@58914e59 libs/sst/sst-basic-blocks (FastMath polynomial "
    "sin/cos; file-level cite, a32b8aec14d661e415bb676bb2e2a0a4da4efc96)",
]
CITES_WT = [
    "surge@58914e59 src/common/dsp/oscillators/WavetableOscillator.cpp "
    "::convolute (mip selection from phase increment a vs wt.dt; "
    "morph table interpolation deformContinuous/deformLegacy 2-entry "
    "linear blend; distort_level saturation)",
    "surge@58914e59 src/common/dsp/oscillators/WavetableOscillator.cpp "
    "::process_block (BLIT extraction: 1-pole HPF per OS sample)",
    "surge@58914e59 src/common/SurgeStorage.h (FIRipol_M=256, "
    "FIRipol_N=12)",
]


def _fir_convolution(o, stereo):
    """12-tap windowed-sinc impulse write (ClassicOscillator/WavetableOscillator
    convolute inner loop, scalar-equivalent of the 4-wide SSE code)."""
    for _ in range(SINC_TAPS):
        o.lut("sinctable_2x", SINC_TABLE_PHASES * SINC_TAPS * 2)
        o.lut("sinctable_2x", SINC_TABLE_PHASES * SINC_TAPS * 2)
        o.mul(AUDIO_BITS_CANDIDATE)   # lipol * deriv
        o.add(AUDIO_BITS_CANDIDATE)   # window + deriv
        o.mul(AUDIO_BITS_CANDIDATE)   # * g
        o.add(AUDIO_BITS_CANDIDATE)   # += buffer
        o.sram_r()
        o.sram_w()
        if stereo:
            o.mul(AUDIO_BITS_CANDIDATE)
            o.add(AUDIO_BITS_CANDIDATE)
            o.sram_r()
            o.sram_w()


def _classic_impulse(o, stereo):
    """One Classic convolute() call, worst case = state-machine case 0."""
    o.mul(COEFF_BITS)   # ipos = oscstate * pitchmult_inv
    o.shift(4)          # ipos >> 24, & 0x3f, >>16 &0xff, &0xffff
    o.mul(COEFF_BITS)   # t = note_to_pitch_inv(detune+sync) (LUT counted below)
    o.lut("note_to_pitch", 512)
    o.mul(COEFF_BITS)   # t_inv = 1/t (reciprocal mul; A-ALU-2)
    # state machine case 0: impulse level + DC bookkeeping
    o.mul(COEFF_BITS)   # (1+wf)*0.5
    o.mul(COEFF_BITS)   # (1-pw)*(-wf)
    o.mul(COEFF_BITS)   # *(1-sub)
    o.mul(COEFF_BITS)   # 0.5*sub*(2-pw2)
    o.mul(COEFF_BITS)
    o.add(COEFF_BITS, )
    o.add(COEFF_BITS)
    o.add(COEFF_BITS)
    o.sub(COEFF_BITS)   # g = tg - last_level
    o.mul(COEFF_BITS)   # last_level DC term (pw*pw2)
    o.mul(COEFF_BITS)   # *(1+wf)*(1-sub)
    o.mul(COEFF_BITS)
    o.sub(COEFF_BITS)
    o.mul(COEFF_BITS)   # g *= out_attenuation
    if stereo:
        o.mul(COEFF_BITS)  # gR = g*panR
        o.mul(COEFF_BITS)  # g *= panL
    _fir_convolution(o, stereo)
    # DC buffer update: dc_uni = t_inv*(1+wf)*(1-sub); dcbuffer += diff
    o.mul(COEFF_BITS)
    o.mul(COEFF_BITS)
    o.sub(COEFF_BITS)
    o.add(COEFF_BITS)
    o.sram_r()
    o.sram_w()
    # rate = t*(1-pw or pw) * (2-pw2 or pw2); oscstate += rate
    o.mul(COEFF_BITS)
    o.mul(COEFF_BITS)
    o.add(COEFF_BITS)
    o.add(COEFF_BITS)
    o.add(2)            # state advance (2-bit)
    o.cmp()


def _classic_extraction_per_os_sample(o, stereo):
    """ClassicOscillator::process_block extraction loop, one OS sample."""
    o.mul(AUDIO_BITS_CANDIDATE)  # a = osc_out * hpf
    o.add(AUDIO_BITS_CANDIDATE)  # + oscbuffer
    o.add(AUDIO_BITS_CANDIDATE)  # mdc += dcbuffer
    o.mul(AUDIO_BITS_CANDIDATE)  # mdc * oa
    o.sub(AUDIO_BITS_CANDIDATE)  # ob -= mdc*oa
    o.mul(AUDIO_BITS_CANDIDATE)  # char biquad out2*a1
    o.mul(AUDIO_BITS_CANDIDATE)  # out*b0
    o.mul(AUDIO_BITS_CANDIDATE)  # last_out*b1
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    if stereo:
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.sub(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
    o.sram_r()  # oscbuffer read
    o.sram_r()  # dcbuffer read
    if stereo:
        o.sram_r()


def classic_state_bits(phase_bits):
    per_unison = {
        "oscstate_phase": phase_bits,
        "syncstate_phase": phase_bits,
        "state": 2,
        "last_level": AUDIO_BITS_CANDIDATE,
        "dc_uni": AUDIO_BITS_CANDIDATE,
        "pwidth": AUDIO_BITS_CANDIDATE,
        "pwidth2": AUDIO_BITS_CANDIDATE,
        "rate": AUDIO_BITS_CANDIDATE,
        "drift_lfo_phase": AUDIO_BITS_CANDIDATE,
    }
    per_slot_shared = {
        # oscbuffer L/R + dcbuffer, engine-sized ring (OB_LENGTH+SINC_TAPS);
        # a hardware candidate could shrink the ring to max wavelength + FIR.
        "oscbuffer_L": (OB_LENGTH + SINC_TAPS) * AUDIO_BITS_CANDIDATE,
        "oscbuffer_R": (OB_LENGTH + SINC_TAPS) * AUDIO_BITS_CANDIDATE,
        "dcbuffer": (OB_LENGTH + SINC_TAPS) * AUDIO_BITS_CANDIDATE,
    }
    return per_unison, per_slot_shared


def cost_classic(phase_bits, multiplier, stereo=True):
    """Per-unison-instance cycles/sample for the pinned Classic structure."""
    per_sample_by_corner = {}
    for f0, label in PITCH_CORNERS:
        o = OpCounter()
        # impulses per output sample = 8*f0/96000 (4 impulses/cycle,
        # 2 OS samples per output sample at 96 kHz OS rate)
        impulses = 8 * f0 / 96000.0
        n_imp = int(impulses * BLOCK_SIZE) + (1 if (impulses * BLOCK_SIZE) % 1 else 0)
        for i in range(n_imp):
            _classic_impulse(o, stereo)
        for s in range(BLOCK_SIZE * OSC_OVERSAMPLING):
            _classic_extraction_per_os_sample(o, stereo)
        # block-rate amortized: update_lagvals (5 lag lerps, 1 pitch LUT,
        # 1 hpf table pow), buffer clear is included in impulse writes
        for _ in range(5):
            o.mul(COEFF_BITS)
            o.add(COEFF_BITS)
        o.lut("note_to_pitch", 512)
        o.lut("pow_table", 512)
        total = op_cycles(o, multiplier)
        per_sample_by_corner[label] = round(total / float(BLOCK_SIZE), 1)
    worst = max(per_sample_by_corner.values())
    return worst, per_sample_by_corner, classic_state_bits(phase_bits)


def naive_polyblep_sample(o):
    """Issue-text candidate: naive saw/pulse + 1-pole LP (NOT the pinned
    algorithm; adaptation candidate with different aliasing/character)."""
    o.add(32)                   # phase += step
    o.cmp()                     # wrap
    o.shift(2)                  # saw = phase scaled
    o.cmp()                     # pulse threshold
    o.lut("polyblep_corr", 256)  # 2-point polyblep correction table
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)  # 1-pole LP: y += k*(x-y)
    o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)  # atten


def cost_naive(phase_bits, multiplier):
    o = OpCounter()
    for _ in range(BLOCK_SIZE):
        naive_polyblep_sample(o)
    total = op_cycles(o, multiplier)
    ps = round(total / float(BLOCK_SIZE), 1)
    state = {
        "phase": phase_bits,
        "lp_state": AUDIO_BITS_CANDIDATE,
        "pulse_state": AUDIO_BITS_CANDIDATE,
    }
    return ps, state


def sine_table_sample(o, phase_bits):
    """Table+phase candidate (issue text): 1024-entry table, linear interp."""
    o.add(32)                    # phase += omega (block-ramped)
    o.cmp()                      # wrap
    o.shift(2)                   # index + frac extract
    o.lut("sine_table", 1024)
    o.lut("sine_table", 1024)
    o.sub(AUDIO_BITS_CANDIDATE)  # frac
    o.mul(AUDIO_BITS_CANDIDATE)  # lerp
    o.add(AUDIO_BITS_CANDIDATE)
    # feedback path (worst fb != 0)
    o.mul(AUDIO_BITS_CANDIDATE)  # lv blend
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)  # * fbv
    o.cmp()                      # fb sign
    o.add(AUDIO_BITS_CANDIDATE)  # x = phase + fb
    o.add(AUDIO_BITS_CANDIDATE)  # + FM (worst)
    o.mul(COEFF_BITS)            # FM depth * master
    # pan + attenuation + unison sum (marginal per instance)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(COEFF_BITS)            # omega ramp


def sine_poly_sample(o, phase_bits):
    """Pinned structure: sst FastMath polynomial sin+cos evaluation."""
    o.add(32)
    o.cmp()
    o.add(AUDIO_BITS_CANDIDATE)  # fb into x
    o.mul(COEFF_BITS)            # FM depth * master
    o.add(AUDIO_BITS_CANDIDATE)
    for _ in range(2):           # fastsin + fastcos polynomial (deg ~7)
        for _ in range(4):
            o.mul(AUDIO_BITS_CANDIDATE)
        for _ in range(4):
            o.add(AUDIO_BITS_CANDIDATE)
        o.cmp()                  # range clamp
    o.mul(AUDIO_BITS_CANDIDATE)  # fb blend lv0
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)  # * fbv
    o.mul(AUDIO_BITS_CANDIDATE)  # pan L
    o.mul(AUDIO_BITS_CANDIDATE)  # pan R
    o.mul(AUDIO_BITS_CANDIDATE)  # atten
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(COEFF_BITS)            # omega ramp


def sine_state_bits(phase_bits):
    return {
        "phase": phase_bits,
        "lastvalue0": AUDIO_BITS_CANDIDATE,
        "lastvalue1": AUDIO_BITS_CANDIDATE,
        "omega_curr": COEFF_BITS,
        "omega_step": COEFF_BITS,
        "omega_prior": COEFF_BITS,
        "playramp": AUDIO_BITS_CANDIDATE,
        "drift_lfo_phase": AUDIO_BITS_CANDIDATE,
    }


def cost_sine(variant, phase_bits, multiplier):
    o = OpCounter()
    fn = sine_table_sample if variant == "sine_table" else sine_poly_sample
    for _ in range(BLOCK_SIZE):
        fn(o, phase_bits)
    # block rate: 5 lag lerps (shape/fb params)
    for _ in range(5):
        o.mul(COEFF_BITS)
        o.add(COEFF_BITS)
    total = op_cycles(o, multiplier)
    ps = round(total / float(BLOCK_SIZE), 1)
    return ps, sine_state_bits(phase_bits)


def _wt_impulse(o, stereo):
    """One WavetableOscillator convolute() call (morph worst case)."""
    o.mul(COEFF_BITS)   # ipos = oscstate * pitchmult_inv
    o.shift(4)
    # deformContinuous: 2-entry morph blend at current table position
    o.lut("wt_table", 2048)
    o.lut("wt_table", 2048)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    # distort_level worst (saturate > 0)
    o.mul(AUDIO_BITS_CANDIDATE)  # x^2
    o.mul(AUDIO_BITS_CANDIDATE)  # a*x^2
    o.add(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)  # x^3
    o.mul(AUDIO_BITS_CANDIDATE)  # clip*x^3
    o.mul(AUDIO_BITS_CANDIDATE)  # (1-clip)*x
    o.add(AUDIO_BITS_CANDIDATE)
    o.cmp()
    o.cmp()
    o.sub(AUDIO_BITS_CANDIDATE)  # g = new - last_level
    o.mul(COEFF_BITS)   # t = note_to_pitch_inv(detune) etc.
    o.lut("note_to_pitch", 512)
    o.mul(COEFF_BITS)   # xt hskew shaping
    o.mul(COEFF_BITS)
    o.mul(COEFF_BITS)
    o.add(COEFF_BITS)
    o.add(COEFF_BITS)
    o.mul(COEFF_BITS)   # rate = t
    if stereo:
        o.mul(COEFF_BITS)
        o.mul(COEFF_BITS)
    _fir_convolution(o, stereo)
    o.add(COEFF_BITS)   # oscstate += rate
    o.cmp()


def _wt_extraction_per_os_sample(o, stereo):
    o.mul(AUDIO_BITS_CANDIDATE)  # hpf: a = osc_out*hpf
    o.add(AUDIO_BITS_CANDIDATE)  # + oscbuffer
    if stereo:
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
    o.sram_r()
    if stereo:
        o.sram_r()


def wt_state_bits(phase_bits):
    return {
        "oscstate_phase": phase_bits,
        "table_pos_state": 11,   # wtsize up to 2048
        "last_level": AUDIO_BITS_CANDIDATE,
        "tableid": 12,
        "tableipol": AUDIO_BITS_CANDIDATE,
        "mipmap": 3,
        "drift_lfo_phase": AUDIO_BITS_CANDIDATE,
    }


def cost_wt_blit(phase_bits, multiplier, stereo=True):
    per_sample_by_corner = {}
    for f0, label in PITCH_CORNERS:
        o = OpCounter()
        impulses = 8 * f0 / 96000.0
        n_imp = int(impulses * BLOCK_SIZE) + (1 if (impulses * BLOCK_SIZE) % 1 else 0)
        for i in range(n_imp):
            _wt_impulse(o, stereo)
        for s in range(BLOCK_SIZE * OSC_OVERSAMPLING):
            _wt_extraction_per_os_sample(o, stereo)
        # block rate: 4 lag lerps + morph update + mip select amortized
        for _ in range(4):
            o.mul(COEFF_BITS)
            o.add(COEFF_BITS)
        o.mul(COEFF_BITS)  # morph shape scale
        o.add(COEFF_BITS)
        for _ in range(6):
            o.cmp()        # mip select compare chain (once per cycle,
            o.add(8)       #  amortized over the wavetable length)
        total = op_cycles(o, multiplier)
        per_sample_by_corner[label] = round(total / float(BLOCK_SIZE), 1)
    worst = max(per_sample_by_corner.values())
    return worst, per_sample_by_corner, wt_state_bits(phase_bits)


def cost_wt_direct(phase_bits, multiplier):
    """Issue-text candidate: per-sample mip-select + linear interp playback
    (NOT the pinned BLIT structure; adaptation candidate, aliasing differs)."""
    o = OpCounter()
    for _ in range(BLOCK_SIZE):
        o.add(32)                    # phase += step
        o.cmp()
        for _ in range(3):           # mip select
            o.cmp()
        o.shift(2)                   # pos + frac
        o.lut("wt_table", 2048)
        o.lut("wt_table", 2048)
        o.mul(AUDIO_BITS_CANDIDATE)  # lerp
        o.add(AUDIO_BITS_CANDIDATE)
        o.lut("wt_table", 2048)      # morph neighbor table
        o.lut("wt_table", 2048)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)  # hpf
        o.sub(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)
        o.add(AUDIO_BITS_CANDIDATE)
        o.mul(AUDIO_BITS_CANDIDATE)  # atten
    total = op_cycles(o, multiplier)
    ps = round(total / float(BLOCK_SIZE), 1)
    state = wt_state_bits(phase_bits)
    state["hpf_state"] = AUDIO_BITS_CANDIDATE
    return ps, state


# ---------------------------------------------------------------------------
def _mm(onchip=TECH["onchip_sram"], ext="none"):
    return {
        "name": "onchip_1rw_sram" + ("" if ext == "none" else "+" + ext),
        "onchip_sram": onchip,
        "external": {"name": ext,
                     "detail": TECH["external"].get(ext, "no external "
                                                    "writable memory used")},
    }


def _assumptions(mult):
    return [
        TECH["multipliers"][mult]["assumption"],
        TECH["adder"],
        TECH["onchip_sram"],
        TECH["table_rom"],
        TECH["division"],
        TECH["simd"],
        TECH["clock"],
        "Audio path 24-bit, coefficients 32-bit, sinc table 256 phases x "
        "12 taps (FIRipol_M/FIRipol_N). Scalar single-lane schedule.",
    ]


def _closure_map(cpf, scope_note):
    return {c: closure(c, cpf) for c in CLOCK_CANDIDATES_HZ}, scope_note


def run(outdir):
    from .emit import build_record, write_record
    paths = []
    repl = {
        "replaces": "cyc_osc_unison_voice_frame",
        "sxt015_value": 200,
        "scope": "per unison-osc instance per output sample, worst named "
                 "pitch corner; complete-patch closure in "
                 "reports/sxt-016/worked-bundles.json",
    }
    repl_naive = dict(repl)
    repl_naive["replaces"] = "none (adaptation candidate; NOT a pin of " \
                             "cyc_osc_unison_voice_frame)"
    repl_direct = dict(repl)
    repl_direct["replaces"] = "none (adaptation candidate; NOT a pin of " \
                              "cyc_osc_unison_voice_frame)"

    for mult in ("M18", "M32"):
        for phase_bits in PHASE_BITS_CANDIDATES:
            # --- Classic (pinned BLIT structure) ---
            cps, by_corner, state = cost_classic(phase_bits, mult)
            pu, ps_shared = state
            state_bits = sum(pu.values()) + sum(ps_shared.values())
            cpf = int(round(cps * FS_HZ))
            cl, note = _closure_map(
                cpf, "per single unison-osc instance; complete-patch "
                     "closure is worked_bundle's job")
            rec = build_record(
                probe=PROBE, kernel="classic_blit",
                word_lengths={"phase_bits": phase_bits,
                              "audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=True, memory_model=_mm(),
                assumptions=_assumptions(mult), citations=CITES_CLASSIC,
                ops=cost_classic_ops(mult), cycles_per_frame=cpf,
                per_sample=cps,
                state_ram_bits=state_bits,
                ext_bytes_per_frame=0,
                closure_at_clocks=cl,
                sxt015_replacement=repl,
                extra={
                    "instance_scope": "one unison voice of one Classic "
                                      "oscillator slot (stereo out)",
                    "state_bits_per_unison_instance": pu,
                    "state_bits_per_osc_slot_shared": ps_shared,
                    "cycles_per_sample_by_pitch_corner": by_corner,
                    "closure_scope_note": note,
                    "worst_pitch_corner": max(by_corner, key=by_corner.get),
                })
            paths.append(write_record(rec, outdir))

            # --- naive+LP adaptation candidate ---
            ps_n, st_n = cost_naive(phase_bits, mult)
            cpf_n = int(round(ps_n * FS_HZ))
            cl_n, _ = _closure_map(cpf_n, "per instance; adaptation "
                                          "candidate, not a support claim")
            rec = build_record(
                probe=PROBE, kernel="classic_naive_plus_lp",
                word_lengths={"phase_bits": phase_bits,
                              "audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=True, memory_model=_mm(),
                assumptions=_assumptions(mult)
                + ["CANDIDATE DEVIATION: naive saw/pulse + 1-pole LP is "
                   "NOT the pinned Classic algorithm (BLIT); it would "
                   "change aliasing and character => any preset using it "
                   "is adapted, never supported (plan section 2)."],
                citations=CITES_CLASSIC
                + ["issue #11 gloss 'windowed naive saw/pulse + LP'; "
                   "deviation from pinned structure recorded in "
                   "README/EVIDENCE"],
                ops=cost_naive_ops(mult), cycles_per_frame=cpf_n,
                per_sample=ps_n,
                state_ram_bits=sum(st_n.values()),
                ext_bytes_per_frame=0, closure_at_clocks=cl_n,
                sxt015_replacement=repl_naive,
                extra={"state_bits_detail": st_n,
                       "adaptation_flag": True})
            paths.append(write_record(rec, outdir))

            # --- Sine table candidate ---
            ps_s, st_s = cost_sine("sine_table", phase_bits, mult)
            cpf_s = int(round(ps_s * FS_HZ))
            cl_s, _ = _closure_map(cpf_s, "per instance")
            rec = build_record(
                probe=PROBE, kernel="sine_table",
                word_lengths={"phase_bits": phase_bits,
                              "audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=True, memory_model=_mm(),
                assumptions=_assumptions(mult)
                + ["Table candidate: 1024-entry sine table + linear "
                   "interp; the pinned engine uses an sst FastMath "
                   "polynomial (sine_poly record). A table reproducing "
                   "the pinned behavior must pass the fidelity contract "
                   "(plan section 4)."],
                citations=CITES_SINE, ops=cost_sine_ops("sine_table", mult),
                cycles_per_frame=cpf_s, per_sample=ps_s,
                state_ram_bits=sum(st_s.values()), ext_bytes_per_frame=0,
                closure_at_clocks=cl_s, sxt015_replacement=repl,
                extra={"state_bits_detail": st_s})
            paths.append(write_record(rec, outdir))

            # --- Sine poly (pinned structure) ---
            ps_p, st_p = cost_sine("sine_poly", phase_bits, mult)
            cpf_p = int(round(ps_p * FS_HZ))
            cl_p, _ = _closure_map(cpf_p, "per instance")
            rec = build_record(
                probe=PROBE, kernel="sine_poly_fastmath",
                word_lengths={"phase_bits": phase_bits,
                              "audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=True, memory_model=_mm(),
                assumptions=_assumptions(mult)
                + ["Pinned structure: polynomial sin+cos per unison "
                   "(fastsinSSE/fastcosSSE), no table."],
                citations=CITES_SINE, ops=cost_sine_ops("sine_poly", mult),
                cycles_per_frame=cpf_p, per_sample=ps_p,
                state_ram_bits=sum(st_p.values()), ext_bytes_per_frame=0,
                closure_at_clocks=cl_p, sxt015_replacement=repl,
                extra={"state_bits_detail": st_p})
            paths.append(write_record(rec, outdir))

            # --- Wavetable BLIT (pinned structure) ---
            cps_w, by_corner_w, st_w = cost_wt_blit(phase_bits, mult)
            cpf_w = int(round(cps_w * FS_HZ))
            cl_w, _ = _closure_map(cpf_w, "per instance")
            rec = build_record(
                probe=PROBE, kernel="wavetable_blit",
                word_lengths={"phase_bits": phase_bits,
                              "audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=True, memory_model=_mm(),
                assumptions=_assumptions(mult)
                + ["Wavetable table content lives in flash as an asset; "
                   "the on-chip working set for the mip level in play is "
                   "counted in state RAM (mip0 2048 entries = 49152 "
                   "bits; smaller mips halve per level)."],
                citations=CITES_WT, ops=cost_wt_ops(mult),
                cycles_per_frame=cpf_w, per_sample=cps_w,
                state_ram_bits=sum(st_w.values())
                + 2048 * AUDIO_BITS_CANDIDATE,
                ext_bytes_per_frame=0, closure_at_clocks=cl_w,
                sxt015_replacement=repl,
                extra={
                    "state_bits_per_instance": st_w,
                    "onchip_table_working_set_bits": 2048 * AUDIO_BITS_CANDIDATE,
                    "cycles_per_sample_by_pitch_corner": by_corner_w,
                    "worst_pitch_corner": max(by_corner_w,
                                              key=by_corner_w.get),
                })
            paths.append(write_record(rec, outdir))

            # --- Wavetable direct playback candidate ---
            ps_d, st_d = cost_wt_direct(phase_bits, mult)
            cpf_d = int(round(ps_d * FS_HZ))
            cl_d, _ = _closure_map(cpf_d, "per instance; adaptation "
                                          "candidate")
            rec = build_record(
                probe=PROBE, kernel="wavetable_direct_interp",
                word_lengths={"phase_bits": phase_bits,
                              "audio_bits": AUDIO_BITS_CANDIDATE,
                              "coeff_bits": COEFF_BITS, "multiplier": mult},
                has_phase_accumulator=True, memory_model=_mm(),
                assumptions=_assumptions(mult)
                + ["CANDIDATE DEVIATION: per-sample mip+interp playback "
                   "is NOT the pinned BLIT wavetable structure; aliasing "
                   "behavior differs => adapted presets only."],
                citations=CITES_WT, ops=cost_wt_direct_ops(mult),
                cycles_per_frame=cpf_d, per_sample=ps_d,
                state_ram_bits=sum(st_d.values())
                + 2048 * AUDIO_BITS_CANDIDATE,
                ext_bytes_per_frame=0, closure_at_clocks=cl_d,
                sxt015_replacement=repl_direct,
                extra={"state_bits_detail": st_d,
                       "adaptation_flag": True})
            paths.append(write_record(rec, outdir))
    return paths


# Ops snapshots for records (structural, from the kernel bodies above).
def cost_classic_ops(mult):
    o = OpCounter()
    _classic_impulse(o, True)
    _classic_extraction_per_os_sample(o, True)
    return o.ops_dict()


def cost_naive_ops(mult):
    o = OpCounter()
    naive_polyblep_sample(o)
    return o.ops_dict()


def cost_sine_ops(variant, mult):
    o = OpCounter()
    fn = sine_table_sample if variant == "sine_table" else sine_poly_sample
    fn(o, 24)
    return o.ops_dict()


def cost_wt_ops(mult):
    o = OpCounter()
    _wt_impulse(o, True)
    _wt_extraction_per_os_sample(o, True)
    return o.ops_dict()


def cost_wt_direct_ops(mult):
    o = OpCounter()
    o.add(32); o.cmp()
    for _ in range(3):
        o.cmp()
    o.shift(2)
    for _ in range(2):
        o.lut("wt_table", 2048)
    o.mul(AUDIO_BITS_CANDIDATE); o.add(AUDIO_BITS_CANDIDATE)
    for _ in range(2):
        o.lut("wt_table", 2048)
    o.mul(AUDIO_BITS_CANDIDATE); o.mul(AUDIO_BITS_CANDIDATE)
    o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE); o.sub(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE); o.add(AUDIO_BITS_CANDIDATE)
    o.mul(AUDIO_BITS_CANDIDATE)
    return o.ops_dict()
