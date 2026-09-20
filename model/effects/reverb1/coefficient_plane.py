#!/usr/bin/env python3
"""SXT-024 Reverb1 coefficient plane (control-rate, host side).

Derives every coefficient the SXT-024 frozen fixed-point model and RTL consume.
This is the CONTROL plane only: it runs at parameter-change rate, never at
audio rate, and is therefore outside the RTL-vs-model exactness claim
(RTL receives the quantized coefficients as inputs; the exactness claim covers
the audio-rate datapath).

STRUCTURE AUTHORITY (read, never copied -- GPL-3.0-or-later tree kept external):
  - sst-effects @ adcac6950292dacc529651093e7ece2d1c8c0d4b
    include/sst/effects/Reverb1.h : loadpreset() (16x4 delay_time tables and
    the `2*roomsize` rescale), update_rtime() (db60 feedback exponent),
    processBlock() (predelay pdtime derivation via noteToPitchIgnoringTuning).
  - surge @ 58914e59c608ed4384ba6002e44c3465c58b2e71
    src/common/SurgeStorage.cpp : note_to_pitch_ignoring_tuning() (tables built
    from the cited powf/pow formulas below -- formulas cited, tables NOT
    copied), db_to_linear() table formula, SurgeStorage.h db60 constant usage.
    src/common/dsp/utilities/DSPUtils.h : amp_to_linear(x) = x*x*x.
    src/common/dsp/effects/SurgeSSTFXAdapter.h : dbToLinear -> storage.
  - sst-filters @ e92d93a92beabde03fa4ab767b285fa21c6608d6
    include/sst/filters/BiquadFilter.h : coeff_HP, coeff_LP2B,
    coeff_orfanidisEQ (via coeff_peakEQ), set_coef normalization, calc_omega.

DEVIATIONS from the pinned float code (recorded, bounded):
  - powf/pow replicated with numpy float32/float64; 1-ulp deviations possible
    and are part of the measured model-vs-reference error, not hidden.
  - The lowcut/highcut "deactivated" flags are NOT exposed by surgepy (SXT-011
    exposure gap class). They are read from the raw .fxp XML attribute
    (documented exception) and cross-checked by the fidelity budget: a wrong
    hypothesis shows up as a budget failure, never silently.

Everything here is original to this repository (Apache-2.0).
"""
import math

import numpy as np

FS = 48000.0

# Reverb1.h loadpreset() delay_time tables (8.8 fixed "256ths of a sample"),
# transcribed as cited constants. These are pinned-source structural facts.
DELAY_TIME_TABLES = {
    0: [1339934, 962710, 1004427, 1103966, 1198575, 1743348, 1033425, 933313,
        949407, 1402754, 1379894, 1225304, 1135598, 1402107, 956152, 1137737],
    1: [1265607, 844703, 856159, 1406425, 786608, 1163557, 1091206, 1129434,
        1270379, 896997, 1415393, 782808, 868582, 1234463, 1000336, 968299],
    2: [1293101, 1334867, 1178781, 1850949, 1663760, 1982922, 1211021, 1824481,
        1520266, 1351822, 1102711, 1513696, 1057618, 1671799, 1406360, 1170468],
    3: [1833435, 2462309, 2711583, 2219764, 1664194, 2109157, 1626137, 1434473,
        2271242, 1621375, 1831218, 2640903, 1577737, 1871624, 2439164, 1427343],
}

REV_TAPS = 16
MAX_REV_DLY = 32768
DECAYTIME_MIN = -4.0
DECAYTIME_MAX = 6.0


def _f32(x):
    return np.float32(x)


def note_to_pitch_ignoring_tuning(x):
    """Replicates SurgeStorage::note_to_pitch_ignoring_tuning (12-TET).

    Pinned formulas (SurgeStorage.cpp init_tables + note_to_pitch_ignoring_tuning):
      table_pitch[i]            = powf(2.f, ((float)i - 256.f) * (1.f/12.f))
      table_two_to_the[i]       = pow(2.0, i * 1.0 / 12.0 / 1000.0)   (double)
      interp: (1-frac)*t[i] + frac*t[i+1], frac from float32 arithmetic.
    """
    x = _f32(min(max(_f32(x + _f32(256.0)), _f32(1e-4)), 512.0 - 1e-4))
    e = int(x)
    a = _f32(x - np.float32(e))
    pow2pos = _f32(a * _f32(1000.0))
    idx = int(pow2pos)
    frac = _f32(pow2pos - np.float32(idx))
    t0 = np.float64(np.power(2.0, idx / 12.0 / 1000.0))
    t1 = np.float64(np.power(2.0, (idx + 1) / 12.0 / 1000.0))
    pow2v = (1.0 - float(frac)) * t0 + float(frac) * t1
    pitch_e = np.float32(np.power(np.float32(2.0), (np.float32(e) - np.float32(256.0)) * np.float32(1.0 / 12.0)))
    return _f32(np.float32(pitch_e) * _f32(pow2v))


def delay_times(shape, roomsize):
    """Reverb1.h loadpreset(): delay_time[t] = (int)(float)(2.f*roomsize) * delay_time[t]."""
    scale = _f32(_f32(2.0) * _f32(roomsize))
    out = []
    for v in DELAY_TIME_TABLES[int(shape)]:
        prod = _f32(scale * _f32(v))  # int -> float32 exact (< 2^24)
        out.append(int(prod))         # C (int) cast truncates toward zero
    return out


def delay_feedback(delay_time, decaytime):
    """Reverb1.h update_rtime(): delay_fb[t] = db60^(dt/(256*Fs*2^decay)).
    db60 = powf(10.f, 0.05f*-60.f); promotions per the pinned C++ (see module doc)."""
    db60 = _f32(np.power(_f32(10.0), _f32(0.05 * -60.0)))
    pow2 = _f32(np.power(_f32(2.0), _f32(decaytime)))
    den = 256.0 * FS * float(pow2)  # 256.f * double sampleRate -> double
    out = []
    for dt in delay_time:
        arg = _f32(float(dt) / den)  # int / double -> double -> float arg of powf
        out.append(_f32(np.power(db60, arg, dtype=np.float32)))
    return out


def predelay_samples(predelay_param, temposync_ratio=1.0):
    """Reverb1.h processBlock(): pdtime = (int)(48000.f * n2p(12*pd) * tsratio)."""
    pitch = note_to_pitch_ignoring_tuning(_f32(12.0) * _f32(predelay_param))
    pd = _f32(_f32(FS) * pitch)
    pd = _f32(pd * _f32(temposync_ratio))
    return int(pd)


def pan_gains():
    """Reverb1.h initialize(): x = t/15; xbp = -1+2x; pan_L = sqrt(0.5-0.495*xbp)
    (double sqrt, float storage, per the pinned literal types)."""
    pan_l, pan_r = [], []
    for t in range(REV_TAPS):
        x = np.float32(float(t) / np.float32(REV_TAPS - 1.0))
        xbp = _f32(_f32(-1.0) + _f32(2.0) * x)
        pl = math.sqrt(0.5 - 0.495 * float(xbp))
        pr = math.sqrt(0.5 + 0.495 * float(xbp))
        pan_l.append(np.float32(pl))
        pan_r.append(np.float32(pr))
    return pan_l, pan_r


def _calc_omega(scfreq):
    """BiquadFilter.h calc_omega: 2*pi*440*n2p(12*scfreq)*srate_inv (double)."""
    return (2 * math.pi) * 440.0 * float(note_to_pitch_ignoring_tuning(_f32(12.0 * scfreq))) * (1.0 / FS)


def _set_coef(a0, a1, a2, b0, b1, b2):
    """BiquadFilter.h set_coef: normalize by a0."""
    a0inv = 1.0 / a0
    return (b0 * a0inv, b1 * a0inv, b2 * a0inv, a1 * a0inv, a2 * a0inv)


def coeff_hp(omega, q=0.5):
    """BiquadFilter.h coeff_HP (double math as pinned)."""
    if omega > math.pi:
        return _set_coef(1, 0, 0, 1, 0, 0)
    cosi, sinu = math.cos(omega), math.sin(omega)
    alpha = sinu / (2 * q)
    b0 = (1 + cosi) * 0.5
    b1 = -(1 + cosi)
    b2 = (1 + cosi) * 0.5
    a0, a1, a2 = 1 + alpha, -2 * cosi, 1 - alpha
    return _set_coef(a0, a1, a2, b0, b1, b2)


def coeff_lp2b(omega, q=0.5):
    """BiquadFilter.h coeff_LP2B (double math as pinned)."""
    if omega > math.pi:
        return _set_coef(1, 0, 0, 1, 0, 0)
    w_sq = omega * omega
    den = (w_sq * w_sq) + (math.pi ** 4) + w_sq * (math.pi ** 2) * (1 / q - 2)
    g1 = min(1.0, math.sqrt((w_sq * w_sq) / den) * 0.5)
    cosi, sinu = math.cos(omega), math.sin(omega)
    alpha = sinu / (2 * q)
    a = 2 * math.sqrt(g1) * math.sqrt(2 - g1)
    b0 = (1 - cosi + g1 * (1 + cosi) + a * sinu) * 0.5
    b1 = (1 - cosi - g1 * (1 + cosi))
    b2 = (1 - cosi + g1 * (1 + cosi) - a * sinu) * 0.5
    a0, a1, a2 = 1 + alpha, -2 * cosi, 1 - alpha
    return _set_coef(a0, a1, a2, b0, b1, b2)


def coeff_peak_eq(omega, bw, gain_db):
    """BiquadFilter.h coeff_peakEQ -> coeff_orfanidisEQ with G=dbToLinear(gain),
    GB=dbToLinear(gain*0.5), G0=1. db_to_linear: table_dB[i]=powf(10,0.05*(i-384))
    with linear interpolation (SurgeStorage::db_to_linear)."""
    g = _db_to_linear(gain_db)
    gb = _db_to_linear(gain_db * 0.5)
    return _coeff_orfanidis(omega, max(0.0001, bw), g, gb, 1.0)


def _db_to_linear(x):
    """SurgeStorage::db_to_linear: table_dB lookup = powf(10,0.05*(x)) with
    linear interpolation between integer dB cells (x+384, e=(int)x, a=x-e)."""
    y = x + 384.0
    e = int(y)
    a = np.float32(y - float(e))
    v0 = np.float32(np.power(np.float32(10.0), np.float32(0.05 * (e - 384))))
    v1 = np.float32(np.power(np.float32(10.0), np.float32(0.05 * (e + 1 - 384))))
    return _f32((1.0 - float(a)) * float(v0) + float(a) * float(v1))


def _coeff_orfanidis(omega, bw, g, gb, g0):
    """BiquadFilter.h coeff_orfanidisEQ (double math as pinned; minBW=0.0001)."""
    w0 = omega
    dww = 2 * w0 * math.sinh((math.log(2.0) / 2.0) * bw)
    if abs(g - g0) > 0.00001:
        f = abs(g * g - gb * gb)
        g00 = abs(g * g - g0 * g0)
        f00 = abs(gb * gb - g0 * g0)
        num = g0 * g0 * (w0 * w0 - math.pi ** 2) ** 2 + g * g * f00 * (math.pi ** 2) * dww * dww / f
        den = (w0 * w0 - math.pi ** 2) ** 2 + f00 * math.pi * math.pi * dww * dww / f
        g1 = math.sqrt(num / den)
        if omega > math.pi:
            g = g1 * 0.9999
        g01 = abs(g * g - g0 * g1)
        g11 = abs(g * g - g1 * g1)
        f01 = abs(gb * gb - g0 * g1)
        f11 = abs(gb * gb - g1 * g1)
        w2 = math.sqrt(g11 / g00) * math.tan(w0 / 2) ** 2
        w_lower = w0 * 2 ** (-0.5 * bw)
        w_upper = 2 * math.atan(math.sqrt(f00 / f11) * math.sqrt(g11 / g00) * math.tan(w0 / 2) ** 2 / math.tan(w_lower / 2))
        dw = abs(w_upper - w_lower)
        big_dw = (1 + math.sqrt(f00 / f11) * w2) * math.tan(dw / 2)
        c = f11 * big_dw * big_dw - 2 * w2 * (f01 - math.sqrt(f00 * f11))
        d = 2 * w2 * (g01 - math.sqrt(g00 * g11))
        a = math.sqrt((c + d) / f)
        b = math.sqrt((g * g * c + gb * gb * d) / f)
        a0 = 1 + w2 + a
        a1 = -2 * (1 - w2)
        a2 = 1 + w2 - a
        b0 = g1 + g0 * w2 + b
        b1 = -2 * (g1 - g0 * w2)
        b2 = g1 - b + g0 * w2
        return _set_coef(a0, a1, a2, b0, b1, b2)
    return _set_coef(1, 0, 0, 1, 0, 0)


def build(params, deactivated=None, temposync_ratio=1.0):
    """Build the full coefficient plane for one Reverb1 instance.

    params: dict with the 11 Reverb1 param values (float, normalized engine
    values as read post-load at 48 kHz), keys:
      predelay, shape, roomsize, decaytime, damping, lowcut, freq1, gain1,
      highcut, mix, width
    deactivated: dict of deactivation flags for lowcut/highcut (surgepy
    exposure gap; supplied from the raw .fxp attributes, cross-checked by the
    fidelity budget).
    Returns a plain dict of Python numbers (floats pre-quantization).
    """
    p = params
    deact = {"lowcut": False, "highcut": False}
    if deactivated:
        deact.update(deactivated)

    dt = delay_times(int(p["shape"]), float(p["roomsize"]))
    dfb = delay_feedback(dt, float(p["decaytime"]))
    pdtime = predelay_samples(float(p["predelay"]), temposync_ratio)
    pan_l, pan_r = pan_gains()
    damp = float(min(max(np.float32(p["damping"]), np.float32(0.01)), np.float32(0.99)))
    damp_m1 = float(_f32(1.0) - _f32(damp))

    band = coeff_peak_eq(_calc_omega(float(p["freq1"]) / 12.0), 2.0, float(p["gain1"]))
    locut = coeff_hp(_calc_omega(float(p["lowcut"]) / 12.0), 0.5)
    hicut = coeff_lp2b(_calc_omega(float(p["highcut"]) / 12.0), 0.5)

    return {
        "delay_time": dt,
        "delay_fb": [float(v) for v in dfb],
        "pdtime": pdtime,
        "pan_l": [float(v) for v in pan_l],
        "pan_r": [float(v) for v in pan_r],
        "damp": damp,
        "damp_m1": damp_m1,
        "band1": band,
        "locut": locut,
        "hicut": hicut,
        "lowcut_active": not deact["lowcut"],
        "hicut_active": not deact["highcut"],
        "mix": float(p["mix"]),
        "width_s": float(_db_to_linear(float(p["width"]))),
        "shape": int(p["shape"]),
        "roomsize": float(p["roomsize"]),
        "decaytime": float(p["decaytime"]),
    }
