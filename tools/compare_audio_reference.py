#!/usr/bin/env python3
"""SXT-022 audio comparison: frozen fixed-point model render vs pinned-engine
reference render (fixtures harness, mono int16 WAV, native levels).

Policy (contracts/fidelity-policy-DRAFT.md):
  * no normalization, no time-warping, no reference switching;
  * raw per-sample differences at native level, plus onset-aligned spectra;
  * budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT]: this tool reports ACHIEVED
    numbers against the explicitly-proposed budget values below and marks the
    verdict PENDING-FREEZE -- it never declares fidelity established.

Metrics (on int16 LSB units):
  max_abs_diff        max |ref - model| over the render
  rms_diff            RMS of (ref - model)
  rms_diff_dbfs       RMS difference relative to full scale (32767)
  best_shift          integer sample shift in [-32, 32] minimizing RMS diff
                      (the SXT-012 scheduling granularity bound); shift 0 is
                      reported separately because the model schedules events
                      identically to the render harness
  spectral_corr       correlation of log-magnitude spectra over the whole
                      render (Hann-windowed, averaged per 4096-sample frame)

Usage:
  python3 tools/compare_audio_reference.py --ref REF.wav --model MODEL.wav \
      [--json OUT.json]

SXT-028c-follow-up (#93) tail-region gate, wet-path only, opt-in:
  By default (no --fixture-meta) this tool behaves exactly as before: a dry,
  mono int16 comparison with no tail concept -- the "dry unless the case
  under test is an effect/wet path" rule (AGENTS.md/CLAUDE.md) means the gate
  below must never engage silently.

  --fixture-meta PATH opts a comparison INTO wet-path mode: --ref/--model are
  read as the stereo float32 fixture bus format (SXT-023/SXT-028c fixture
  family; IEEE fmt 3), and the declared tail region -- [duration_s - tail_s,
  duration_s), taken from PATH's own committed render.duration_s/render.tail_s
  fields, never inferred from silence -- becomes part of the verdict: the
  comparator now REFUSES to report PASS unless both the whole-render budgets
  AND the tail-region agreement (the declared tail span must be fully present,
  non-silent, in both files) hold. See tools/compare_chorus_reference.py for
  the sibling tail_check this mirrors (same 3-key shape: tail_present,
  tail_rms_rel_db, ok), and reports/SXT-028c/EVIDENCE.md section 13.
"""

import argparse
import json
import os
import struct
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _relpath_if_under_repo(path):
    """Evidence JSON should record a repo-relative path when possible (other
    comparator tools in this repo follow the same convention), but must
    never fail on a path outside the repo (e.g. a scratch negative-control
    input) -- fall back to the given path unchanged."""
    abspath = os.path.abspath(path)
    if abspath.startswith(REPO + os.sep):
        return os.path.relpath(abspath, REPO)
    return path


# [PROPOSED-TO-BE-FROZEN-AT-PILOT] budget placeholders (SXT-022 proposal,
# derived from the SXT-012 free-phase escalation: raw subtraction is not
# expected to be exact across uncontrolled engine noise; these numbers are
# proposals for the pilot freeze, not frozen policy):
PROPOSED = {
    "max_abs_diff_lsb": 3500,       # ~ -19.4 dBFS equivalent
    "rms_diff_dbfs": -46.0,         # residual RMS at least this far below FS
    "spectral_corr_min": 0.98,
}

# [PROPOSED] wet-path budgets for the stereo float32 Q10.21 fixture domain
# (--fixture-meta mode only). These are NOT re-derived here: they are the
# same frozen numbers already used by tools/compare_fx_reference.py and
# tools/compare_chorus_reference.py for this exact domain (SXT-023 effect-
# slice family) -- reusing an established, already-reviewed calibration
# rather than inventing a new one for this tool.
PROPOSED_WET = {
    "max_abs_diff_lsb": 8192,       # ~ -18 dBFS equivalent
    "rms_diff_dbfs": -46.0,
    "spectral_corr_min": 0.98,
}
LSB_WET = 2.0 ** -21


def read_wav(path):
    with wave.open(path) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return a.astype(np.float64), sr


def read_wav_stereo_f32(path):
    """SXT-023/SXT-028c fixture bus format: stereo float32 (IEEE fmt 3),
    raw engine output, no clip, no normalization. Mirrors the reader in
    tools/compare_chorus_reference.py / tools/compare_fx_reference.py."""
    with open(path, "rb") as f:
        data = f.read()
    pos = 12
    fmt = None
    raw = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + sz]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + sz + (sz & 1)
    audio_fmt, nch, sr, _b, _a, bits = fmt
    if audio_fmt != 3 or bits != 32 or nch != 2:
        raise ValueError(f"expected stereo float32: {path}")
    a = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    return a.T.copy(), sr


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if np.allclose(a, b) else 0.0
    ra = np.log1p(np.abs(np.fft.rfft(a[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def main_dry(args):
    """Unchanged SXT-022 dry comparison (mono int16, native level). Byte-
    identical to the pre-#93 tool: no fixture metadata, no tail concept --
    the AGENTS.md/CLAUDE.md dry rule means this path must never be touched
    by the wet-path tail gate below."""
    ref, sr = read_wav(args.ref)
    mod, sr2 = read_wav(args.model)
    assert sr == sr2 == 48000, (sr, sr2)
    n = min(len(ref), len(mod))
    ref, mod = ref[:n], mod[:n]
    peak = float(np.abs(ref).max()) or 1.0

    def rms_at(shift):
        if shift >= 0:
            r, m = ref[shift:], mod[: n - shift]
        else:
            r, m = ref[: n + shift], mod[-shift:]
        return float(np.sqrt(((r - m) ** 2).mean()))

    shifts = {s: rms_at(s) for s in range(-32, 33)}
    best_shift = min(shifts, key=shifts.get)

    d = np.abs(ref - mod)
    metrics = {
        "frames": n,
        "ref_peak_lsb": peak,
        "model_peak_lsb": float(np.abs(mod).max()),
        "max_abs_diff_lsb": float(d.max()),
        "rms_diff_lsb": float(np.sqrt((d * d).mean())),
        "rms_diff_dbfs": float(20 * np.log10(np.sqrt((d * d).mean()) / 32767.0)),
        "rms_diff_at_shift0_lsb": shifts[0],
        "best_shift": best_shift,
        "rms_diff_at_best_shift_lsb": shifts[best_shift],
        "spectral_corr": spectral_corr(ref, mod),
    }

    proposed_results = {
        "max_abs_diff_lsb": metrics["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": metrics["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": metrics["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED
    metrics["proposed_budget_results"] = proposed_results
    metrics["verdict"] = ("PASS (PENDING-FREEZE: budgets are proposals, not "
                          "frozen policy)" if all(proposed_results.values())
                          else "FAIL against proposed budgets")
    print(json.dumps(metrics, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(metrics, f, indent=2)
            f.write("\n")
    return 0


def _wet_channel_metrics(ref, mod):
    """Whole-render mono metrics in the Q10.21 float32 domain -- identical
    formulas to tools/compare_chorus_reference.py's channel_metrics."""
    n = min(len(ref), len(mod))
    ref, mod = ref[:n], mod[:n]

    def rms_at(shift):
        if shift >= 0:
            r, m = ref[shift:], mod[: n - shift]
        else:
            r, m = ref[: n + shift], mod[-shift:]
        return float(np.sqrt(((r - m) ** 2).mean()))

    shifts = {s: rms_at(s) for s in range(-32, 33)}
    best_shift = min(shifts, key=shifts.get)
    d = np.abs(ref - mod)
    rms = float(np.sqrt((d * d).mean()))
    return {
        "frames": n,
        "ref_peak_lsb": float(np.abs(ref).max() / LSB_WET),
        "model_peak_lsb": float(np.abs(mod).max() / LSB_WET),
        "max_abs_diff_lsb": float(d.max() / LSB_WET),
        "rms_diff_lsb": rms / LSB_WET,
        "rms_diff_dbfs": float(20 * np.log10(rms / LSB_WET / (1 << 20))),
        "rms_diff_at_shift0_lsb": shifts[0] / LSB_WET,
        "best_shift": best_shift,
        "rms_diff_at_best_shift_lsb": shifts[best_shift] / LSB_WET,
        "spectral_corr": spectral_corr(ref, mod),
    }


def _wet_tail_check(ref_mono, mod_mono, sr, offset_s, length_s):
    """Tail-region gate: the declared tail span [offset_s, offset_s+length_s)
    must be FULLY PRESENT (not truncated) in both files, non-silent in the
    reference, AND agree within the same [PROPOSED] budget applied to the
    whole render (reused, not re-derived, for this slice). Unlike
    tools/compare_chorus_reference.py's tail_present (which only inspects
    presence in the reference), this also requires: (1) the model to reach
    the declared tail length -- a truncated/dropped-tail render is caught by
    construction (missing samples), independent of any threshold; and (2) a
    same-length-but-silenced/stale tail stub to fail on magnitude -- length
    alone cannot hide a stub with no real decay content."""
    start = int(round(offset_s * sr))
    length = int(round(length_s * sr))
    ref_tail = ref_mono[start:start + length] if start < len(ref_mono) else ref_mono[0:0]
    mod_tail = mod_mono[start:start + length] if start < len(mod_mono) else mod_mono[0:0]
    ref_complete = len(ref_tail) >= length
    mod_complete = len(mod_tail) >= length

    n = min(len(ref_tail), len(mod_tail))
    tail_rms_rel_db = None
    tail_max_abs_diff_lsb = None
    tail_budget_ok = False
    if n:
        d = np.abs(ref_tail[:n] - mod_tail[:n])
        rms = float(np.sqrt((d * d).mean()))
        ref_rms = float(np.sqrt((ref_tail[:n] * ref_tail[:n]).mean())) or 1e-30
        tail_rms_rel_db = float(20 * np.log10(max(rms / ref_rms, 1e-30)))
        tail_max_abs_diff_lsb = float(d.max() / LSB_WET)
        tail_rms_dbfs = float(20 * np.log10(max(rms / LSB_WET / (1 << 20), 1e-30)))
        tail_budget_ok = bool(
            tail_max_abs_diff_lsb <= PROPOSED_WET["max_abs_diff_lsb"]
            and tail_rms_dbfs <= PROPOSED_WET["rms_diff_dbfs"])

    tail_present = bool(ref_complete and len(ref_tail) and np.abs(ref_tail).max() > 0)
    return {
        "tail_offset_s": offset_s,
        "tail_length_s": length_s,
        "tail_frames_declared": length,
        "tail_frames_ref_available": int(len(ref_tail)),
        "tail_frames_model_available": int(len(mod_tail)),
        "tail_max_abs_diff_lsb": tail_max_abs_diff_lsb,
        "tail_rms_rel_db": tail_rms_rel_db,
        "tail_present": tail_present,
        "ok": bool(tail_present and mod_complete and tail_budget_ok),
    }


def main_wet(args):
    """Wet-path comparison (--fixture-meta given): stereo float32 fixture
    audio, tail-region gate active. See module docstring."""
    with open(args.fixture_meta, encoding="utf-8") as f:
        meta = json.load(f)
    try:
        duration_s = float(meta["render"]["duration_s"])
        tail_s = float(meta["render"]["tail_s"])
    except (KeyError, TypeError) as e:
        print(f"REFUSING: --fixture-meta {args.fixture_meta} is missing "
              f"render.duration_s/render.tail_s ({e}) -- the tail region "
              f"must come from declared fixture data, never be guessed",
              file=sys.stderr)
        return 2
    tail_offset_s = duration_s - tail_s
    if tail_offset_s < 0 or tail_s <= 0:
        print(f"REFUSING: --fixture-meta declares tail_s={tail_s} against "
              f"duration_s={duration_s} -- cannot locate a tail region",
              file=sys.stderr)
        return 2

    ref, sr = read_wav_stereo_f32(args.ref)
    mod, sr2 = read_wav_stereo_f32(args.model)
    assert sr == sr2 == 48000, (sr, sr2)
    ref_mono = 0.5 * (ref[0].astype(np.float64) + ref[1].astype(np.float64))
    mod_mono = 0.5 * (mod[0].astype(np.float64) + mod[1].astype(np.float64))

    metrics = _wet_channel_metrics(ref_mono, mod_mono)
    metrics["fixture_meta"] = _relpath_if_under_repo(args.fixture_meta)
    metrics["tail_region"] = {
        "offset_s": tail_offset_s,
        "length_s": tail_s,
        "source": "fixture_meta:render.duration_s-render.tail_s",
    }

    proposed_results = {
        "max_abs_diff_lsb": metrics["max_abs_diff_lsb"] <= PROPOSED_WET["max_abs_diff_lsb"],
        "rms_diff_dbfs": metrics["rms_diff_dbfs"] <= PROPOSED_WET["rms_diff_dbfs"],
        "spectral_corr": metrics["spectral_corr"] >= PROPOSED_WET["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED_WET
    metrics["proposed_budget_results"] = proposed_results

    tail_check = _wet_tail_check(ref_mono, mod_mono, sr, tail_offset_s, tail_s)
    metrics["tail_check"] = tail_check

    budget_ok = all(proposed_results.values())
    verdict_ok = budget_ok and tail_check["ok"]
    if verdict_ok:
        metrics["verdict"] = ("PASS (PENDING-FREEZE: budgets are proposals, "
                              "not frozen policy)")
    else:
        reasons = []
        if not budget_ok:
            reasons.append("proposed budgets")
        if not tail_check["ok"]:
            reasons.append("tail-region check")
        metrics["verdict"] = "FAIL against " + " and ".join(reasons)

    print(json.dumps(metrics, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(metrics, f, indent=2)
            f.write("\n")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--json", help="write metrics JSON here")
    ap.add_argument(
        "--fixture-meta",
        help="wet-path fixture sidecar JSON (SXT-023/SXT-028c schema: "
             "render.duration_s + render.tail_s). Presence marks this a WET "
             "comparison: --ref/--model are read as stereo float32 fixture "
             "audio and the tail-region gate is enforced. Absent (default) "
             "= dry comparison, unaffected (AGENTS.md dry-unless-wet rule).")
    args = ap.parse_args()
    if args.fixture_meta:
        return main_wet(args)
    return main_dry(args)


if __name__ == "__main__":
    sys.exit(main())
