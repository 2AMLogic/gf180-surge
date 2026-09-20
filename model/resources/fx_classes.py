"""Per-instance FX class state and transaction table for SXT-015.

Classes are keyed by the engine's own display strings as exported in the
SXT-011 graphs (`fx[].tn`). Three verification tiers:

  pinned          exact buffer structure cited from the pinned engine/sst
                  sources (facts read from the GPL tree; no code copied);
  no_long_buffer  verified by structure to hold no writable buffer above the
                  external threshold; exact state sizing is deferred to the
                  SXT-028 leaf issues (small placeholder, on-chip);
  unverified      structure not yet pinned: conservative 1 MiB placeholder,
                  flagged `class_state_unverified`, so an unknown class can
                  never silently look cheap.

`two Delay slots = two Delay instances`: every configured slot gets its own
state entry here; arithmetic sharing is a scheduling concern (SXT-016), not
a state-sharing excuse (plan section 3).
"""
from typing import Dict

from .params import REG

# --- per-sample (per output frame) memory transactions, per stereo instance ----
# All values are words per output frame; every non-pinned entry is a named
# placeholder that SXT-016/023/024/028 must replace with measured behavior.

_PINNED_TX = {
    # sst Delay.h processBlock: per channel 1 write, 1 interpolated read
    # (SSESincDelayLine), 1 crossfeed read of the opposite channel.
    "delay": {"ext_reads": 6, "ext_writes": 2},
    "floaty_delay": {"ext_reads": 6, "ext_writes": 2},
    # Reverb1.h processBlock: 16 composite tap reads + predelay 1r/1w +
    # per-tap feedback writes (rev_taps=16 interleaved slots).
    "reverb1": {"ext_reads": 17, "ext_writes": 17},
    # Reverb2.h: predelay 1r/1w, 4 input allpasses (1r+1w each), 8 block
    # allpasses (1r+1w each), 4 delays (2 taps x subsample interp + 1 write).
    "reverb2": {"ext_reads": 40, "ext_writes": 18},
    # ChorusEffectImpl.h: mono shared buffer 1 write, 4 interpolated voice reads.
    "chorus": {"ext_reads": 4, "ext_writes": 1},
    # Flanger.h InterpDelay: per channel 1 write + 2-point interp read.
    "flanger": {"ext_reads": 4, "ext_writes": 2},
    # RotarySpeaker.h:135-136: single mono buffer[1<<18], per-sample 1 write
    # + per-channel interpolated reads (doppler delay dL/dR).
    "rotary": {"ext_reads": 2, "ext_writes": 1},
}

_PINNED_STATE_BYTES = {
    "delay": 2 * (1 << 18) * 4,  # 2,097,152
    "floaty_delay": 2 * (1 << 19) * 4,  # 4,194,304
    "reverb1": (16 * (1 << 15) + (1 << 15)) * 4,  # 2,228,224
    "reverb2": (12 * 131072 + 4 * 131072 + 1536000) * 4,  # 14,532,608
    "chorus": ((1 << 18) + 12) * 4,  # 1,048,624
    "flanger": 2 * 32768 * 4,  # 262,144
    "rotary": (1 << 18) * 4,  # 1,048,576
}

# engine display name (fx[].tn) -> pinned class key
_PINNED_BY_TN = {
    "Delay": "delay",
    "Floaty Delay": "floaty_delay",
    "Reverb 1": "reverb1",
    "Reverb 2": "reverb2",
    "Chorus": "chorus",
    "Flanger": "flanger",
    "Rotary": "rotary",
}

_PINNED_REFS = {
    "delay": "libs/sst/sst-effects/include/sst/effects/Delay.h:200 "
    "(max_delay_length{1<<18}, line[2][...])",
    "floaty_delay": "libs/sst/sst-effects/include/sst/effects/FloatyDelay.h:164 "
    "(max_delay_length{1<<19}, SSESincDelayLine)",
    "reverb1": "libs/sst/sst-effects/include/sst/effects/Reverb1.h:122-131 "
    "(revbits=15, rev_taps=16, delay[16*32768]+predelay[32768])",
    "reverb2": "libs/sst/sst-effects/include/sst/effects/Reverb2.h:63-72,209-214 "
    "(12 allpass*131072 + 4 delay*131072 + predelay 48000*8*4)",
    "chorus": "src/common/dsp/effects/ChorusEffect.h buffer[max_delay_length+FIRipol_N]; "
    "Effect.h:137 (1<<18); SurgeStorage.h:87 (FIRipol_N=12); Effect.cpp:86 (ChorusEffect<4>)",
    "flanger": "libs/sst/sst-effects/include/sst/effects/Flanger.h:162-168 "
    "(2 x InterpDelay line[32768])",
    "rotary": "libs/sst/sst-effects/include/sst/effects/RotarySpeaker.h:135-136 "
    "(buffer[1<<18] mono, doppler delay reads dL/dR)",
}

_NO_LONG_BUFFER = {
    # tn -> one-line structural justification (file read in the pinned tree)
    "EQ": "ParametricEQ3BandEffect: 3 biquads, no delay line",
    "Graphic EQ": "GraphicEQ11BandEffect: biquad bank, no delay line",
    "Conditioner": "ConditionerEffect: gain/lipol state, no delay line",
    "Ring Mod": "RingModulatorEffect: gain/osc state, no delay line",
    "Mid-Side Tool": "MSToolEffect: matrix/eq state, no delay line",
    "Waveshaper": "WaveShaperEffect: waveshaper registers, no delay line",
    "Distortion": "DistortionEffect: shaper + biquad state, no long buffer",
    "Freq Shift": "FrequencyShifterEffect: Hilbert allpass state, no long buffer",
    "Phaser": "PhaserEffect (sst Phaser.h): per-stage allpass state only",
    "Resonator": "ResonatorEffect: SVF bank state, no delay line",
    "Combulator": "CombulatorEffect: 3 short comb filters, state below threshold",
    "Audio In": "AudioInputEffect: pass-through routing state",
    "Ensemble": "BBDEnsembleEffect.h:98-101: 16 BBDDelayLine<128..1024> stage "
    "lines (~7.7k floats total) + BBD nonlin state",
}

_PINNED_CYCLE_KEY = {
    "delay": "cyc_fxdelay_frame",
    "floaty_delay": "cyc_fxdelay_frame",
    "reverb1": "cyc_fxreverb1_frame",
    "reverb2": "cyc_fxreverb2_frame",
    "chorus": "cyc_fxchorus_frame",
    "flanger": "cyc_fxflanger_frame",
    "rotary": "cyc_fxgeneric_frame",
}

_UNVERIFIED = [
    # algorithm-dependent or not yet pinned; conservative placeholder until the
    # SXT-028 leaf issue for the exact algorithm pins state and traffic
    "Airwindows",  # algorithm id p[0] selects 1 of ~200 plugins; per-algorithm
    "Nimbus",
    "Convolution",  # impulse-size dependent (ConvolutionEffect.h TwoStageConvolver)
    "Vocoder",
    "Tape",
    "Spring Reverb",
    "Neuron",
    "Treemonster",
    "Bonsai",
    "Exciter",
    "CHOW",
]

_SPEC_CACHE: Dict[str, Dict] = {}


def fx_class_spec(tn: str) -> Dict:
    """Return the class spec dict for an engine display name (deterministic)."""
    if tn in _SPEC_CACHE:
        return _SPEC_CACHE[tn]
    word = REG.mem_word_bytes
    thresh = REG.external_threshold_bytes
    if tn == "Off":
        spec = {"class": "off", "tier": "pinned", "state_bytes": 0,
                "external": False, "ext_reads": 0, "ext_writes": 0,
                "cycle_key": None, "flags": [], "ref": "fxt_off"}
    elif tn in _PINNED_BY_TN:
        key = _PINNED_BY_TN[tn]
        sb = _PINNED_STATE_BYTES[key]
        tx = _PINNED_TX[key]
        spec = {"class": tn, "tier": "pinned", "state_bytes": sb,
                "external": sb > thresh,
                "ext_reads": tx["ext_reads"], "ext_writes": tx["ext_writes"],
                "cycle_key": _PINNED_CYCLE_KEY[key],
                "flags": [], "ref": _PINNED_REFS[key]}
    elif tn in _NO_LONG_BUFFER:
        sb = 8192
        spec = {"class": tn, "tier": "no_long_buffer", "state_bytes": sb,
                "external": sb > thresh, "ext_reads": 0, "ext_writes": 0,
                "cycle_key": "cyc_fxgeneric_frame",
                "flags": ["class_state_unverified"],
                "ref": "no long buffer verified: " + _NO_LONG_BUFFER[tn] +
                "; exact state sizing ESTIMATE-REF deferred to SXT-028"}
    elif tn in _UNVERIFIED:
        sb = REG.unverified_fx_state_bytes
        spec = {"class": tn, "tier": "unverified", "state_bytes": sb,
                "external": sb > thresh,
                "ext_reads": 4, "ext_writes": 2,
                "cycle_key": "cyc_fxgeneric_frame",
                "flags": ["class_state_unverified", "class_traffic_unverified"],
                "ref": "ESTIMATE-REF: structure not pinned; conservative "
                "placeholder (unverified_fx_state_bytes); SXT-028 must replace "
                "per exact algorithm"}
    else:
        spec = {"class": tn, "tier": "unknown_engine_class",
                "state_bytes": REG.unverified_fx_state_bytes,
                "external": True, "ext_reads": 4, "ext_writes": 2,
                "cycle_key": "cyc_fxgeneric_frame",
                "flags": ["fx_class_unverified", "unknown_engine_class"],
                "ref": "ESTIMATE-REF: display name not in the SXT-015 class "
                "table; counted at the conservative placeholder and flagged"}
    spec["ext_bytes_per_frame"] = (spec["ext_reads"] + spec["ext_writes"]) * word
    _SPEC_CACHE[tn] = spec
    return spec


def delay_param_derived_samples(param_value: float) -> int:
    """Delay time param -> line samples, per pinned mapping.

    sst Delay.h setvars: time = sampleRate * noteToPitchIgnoringTuning(12*f)
    with noteToPitch(12*f) = 2^f, i.e. samples = sr * 2^param. A modulation
    margin is added on the exponent; the result is clamped to the allocated
    maximum line. The exact modulatable range needs SXT-023 confirmation
    (delay_mod_margin_semitones is an ESTIMATE-REF parameter).
    """
    import math

    margin = REG.delay_mod_margin_semitones / 12.0
    raw = REG.sample_rate_hz * math.pow(2.0, float(param_value) + margin)
    return int(min(math.ceil(raw), REG.delay_max_length_samples))
