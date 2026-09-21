"""Fixed-point kernel shared by the SXT-023 effect models.

Conventions follow the frozen SXT-022 voice model (model/voice/README.md):

* every value is a Python int in two's-complement Q-format;
* products are exact, then rounded round-half-up back to the target format:
  r = (a*b + (1 << (s-1))) >> s, s = fa + fb - fq, then saturated;
* no floating point at run time; double-precision evaluation happens only at
  coefficient (block/control) rate and is quantized once.

Frozen word formats (see model/effects/README.md):
  Q10.21  signed 32-bit  - audio samples, delay-line words, sinc taps
  Q2.29   signed 32-bit  - sinc table coefficients
  Q13.18  signed 32-bit  - block-rate gain ramps (lipol lines)
  Q24.43  signed 64-bit  - biquad coefficients/lags/state, delay-time lag,
                           LFO phase/value/increment
"""

MASK32 = (1 << 32) - 1
MASK64 = (1 << 64) - 1

FRAC = {"Q10.21": 21, "Q2.29": 29, "Q13.18": 18, "Q24.43": 43}
WIDTH = {"Q10.21": 32, "Q2.29": 32, "Q13.18": 32, "Q24.43": 64}


def sat(value, fmt):
    """Saturate to the signed range of the format."""
    w = WIDTH[fmt]
    lo = -(1 << (w - 1))
    hi = (1 << (w - 1)) - 1
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def wrap(value, bits):
    """Two's-complement wrap into a signed integer of the given width."""
    m = (1 << bits) - 1
    v = value & m
    if v >= (1 << (bits - 1)):
        v -= (1 << bits)
    return v


def qmul(a, b, fa, fb, fq):
    """Exact product, round-half-up to Qfq, saturated to the target width.

    fa/fb/fq are format names (e.g. "Q10.21").
    """
    s = FRAC[fa] + FRAC[fb] - FRAC[fq]
    prod = a * b
    if s > 0:
        prod = (prod + (1 << (s - 1))) >> s
    elif s < 0:
        prod = prod << (-s)
    return sat(prod, fq)


def qround(value, ffrom, fto):
    """Re-quantize (round-half-up) a fixed-point value between formats."""
    s = FRAC[ffrom] - FRAC[fto]
    if s > 0:
        value = (value + (1 << (s - 1))) >> s
    elif s < 0:
        value = value << (-s)
    return sat(value, fto)


def qadd(a, b, fmt):
    return sat(a + b, fmt)


def qsub(a, b, fmt):
    return sat(a - b, fmt)


def to_q(x, fmt):
    """Quantize a Python float (double) to the format, round-half-up."""
    f = FRAC[fmt]
    v = int(x * (1 << f) + 0.5) if x >= 0 else -int(-x * (1 << f) + 0.5)
    return sat(v, fmt)


def qdiv(a, b, fmt):
    """Divide two fixed values of the same format, round-half-up, same format."""
    f = FRAC[fmt]
    num = a << f
    if b == 0:
        return sat((1 << 62), fmt) if a >= 0 else sat(-(1 << 62), fmt)
    v = (num + (b >> 1)) // b if (num >= 0) == (b >= 0) else -((-num + (b >> 1)) // b) if b < 0 else -((num + (-b >> 1)) // -b)
    return sat(v, fmt)


def clip(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
