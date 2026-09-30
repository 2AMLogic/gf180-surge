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
  rms_diff_dbfs       RMS difference relative to full scale (32767),
                      clamped to RMS_DIFF_DBFS_FLOOR (-300.0) so exact
                      agreement is a finite, strict-JSON value (issue #100)
  best_shift          integer sample shift in [-32, 32] minimizing RMS diff
                      (the SXT-012 scheduling granularity bound); shift 0 is
                      reported separately because the model schedules events
                      identically to the render harness
  spectral_corr       correlation of full-scale-referenced, floored
                      log-magnitude spectra over the whole render (Hann 4096
                      frames; floor -100 dBFS per bin; the shared definition
                      of issue #110, see SPECTRAL_CORR_* below)

Wet-path tail gate (issue #93; policy draft section 2.5 and section 5 rule 4)
----------------------------------------------------------------------------
A wet-path comparison must declare `--path wet` together with the fixture
sidecar that produced the reference (`--sidecar`, auto-discovered next to the
reference when it follows the committed `<seq>-wet.wav` / `<seq>.json`
convention). The verdict then requires budget-pass AND tail-pass over the
*declared* tail region

    [last_event_sample, last_event_sample + tail_s * sample_rate)

read verbatim from the sidecar -- never inferred from silence. Tail-pass
requires all of: the declared region is fully covered by both renders, the
reference tail region carries energy, the model tail region carries energy, and
the residual RMS inside the region is at least PROPOSED_TAIL["tail_rms_rel_db"]
below the reference tail RMS, and (issue #111) the tail SHAPE agrees: the
per-window (PROPOSED_TAIL["decay_curve_window_s"]) RMS level of the model is
within PROPOSED_TAIL["decay_curve_max_dev_db"] of the reference in every
window whose reference level is at or above the DECLARED floor
PROPOSED_TAIL["decay_curve_floor_dbfs"]. A truncated model render, a zeroed
tail, a decayed-tail truncation, or a LATE-tail truncation/fast decay (which
the whole-region residual cannot see: the early tail dominates it) therefore
FAILS the verdict instead of passing on a truncated-window comparison.

Dry comparisons are unaffected (AGENTS.md dry rule): `--path dry` is the
default, no gate is applied, and the emitted JSON/stdout is byte-identical to
the pre-#93 tool. So that a wet comparison cannot silently skip the gate, the
tool REFUSES (exit 2, verdict NO_VERDICT) when a reference/model filename
declares a wet bus while `--path wet` was not passed, when `--path wet` was
passed without a usable sidecar, or when the sidecar's declared frames/sha256
do not describe the reference render.

Exit status: 0 = PASS, or any dry verdict (unchanged pre-#93 behaviour: dry
consumers read the verdict field); 1 = wet comparison with a FAIL verdict;
2 = refusal (NO_VERDICT -- nothing was graded).

Usage:
  python3 tools/compare_audio_reference.py --ref REF.wav --model MODEL.wav \
      [--json OUT.json]
  python3 tools/compare_audio_reference.py --path wet --sidecar FIXTURE.json \
      --ref REF-wet.wav --model MODEL.wav [--json OUT.json]
"""

import argparse
import json
import os
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402

# [PROPOSED-TO-BE-FROZEN-AT-PILOT] budget placeholders (SXT-022 proposal,
# derived from the SXT-012 free-phase escalation: raw subtraction is not
# expected to be exact across uncontrolled engine noise; these numbers are
# proposals for the pilot freeze, not frozen policy):
PROPOSED = {
    "max_abs_diff_lsb": 3500,       # ~ -19.4 dBFS equivalent
    "rms_diff_dbfs": -46.0,         # residual RMS at least this far below FS
    "spectral_corr_min": 0.98,
}

# [PROPOSED-TO-BE-FROZEN-AT-PILOT] wet-path tail budget (issue #93). The
# criterion is RELATIVE to the reference tail RMS on purpose: a full-scale
# criterion goes vacuous as a tail decays, which is exactly the loophole a
# dropped or stubbed tail would pass through.
#
# Tail-SHAPE leg (issue #111). The residual leg integrates over the whole
# declared region, which the loud early tail dominates, so zeroing only the
# LATE part of a long tail passed it. The decay-curve leg compares per-window
# RMS levels (dBFS) of model and reference across the declared region, in the
# spirit of the sxt-024 `decay_curve` check:
#   * windows of `decay_curve_window_s` (50 ms; sxt-024 window precedent),
#     starting at the declared tail offset; a final partial window is graded;
#   * only windows whose REFERENCE level is >= `decay_curve_floor_dbfs` are
#     graded. The floor is a DECLARED budget in full-scale units (identical
#     meaning for int16 and float buses), never inferred from the render's own
#     silence or noise floor. A reference tail with no window at/above the
#     floor cannot be shape-graded and FAILS closed;
#   * every graded window must satisfy |model_db - ref_db| <=
#     `decay_curve_max_dev_db` (two-sided: a model tail that stops early or
#     fails to decay both fail). 1.0 dB is the sxt-024 decay_curve value and
#     sits just above the 0.92 dB level deviation that a window whose residual
#     met the -20 dB relative budget above can show (20*log10(1 - 10^-1)).
# A late-tail defect whose reference level is below the declared floor is not
# seen by this leg by construction; that limit is recorded in
# reports/tail-shape-leg/EVIDENCE.md, not hidden.
PROPOSED_TAIL = {
    "tail_rms_rel_db": -20.0,       # residual RMS inside the declared tail
                                    # region, relative to the reference tail
                                    # RMS (tail reproduced to <= 10% RMS)
    "decay_curve_window_s": 0.05,   # tail-shape window length (issue #111)
    "decay_curve_floor_dbfs": -100.0,  # declared grading floor, dBFS
    "decay_curve_max_dev_db": 1.0,  # max per-window level deviation, dB
}

# Full scale of the mono int16 comparator in LSB units (same value the
# `rms_diff_dbfs` metric uses).
INT16_FULL_SCALE = 32767.0

# rms_diff_dbfs under exact agreement (issue #100 decision). 20*log10(0) is
# -inf, which Python's json writes as the non-standard token `-Infinity` that
# strict JSON parsers (jq, JSON.parse, serde_json) reject. The field is
# therefore CLAMPED to this finite floor: a value equal to the floor means
# "residual RMS at or below 1e-15 of full scale, including exact agreement".
# The floor sits far below any representable nonzero residual of the committed
# renders (one int16 LSB over 10^7 frames is ~ -160 dBFS), so no nonzero
# residual is collapsed onto it, and every budget comparison (<= -46 dBFS)
# grades identically to -inf. Shared by every comparator that emits the field
# (compare_chorus_reference.py, compare_fx_reference.py).
RMS_DIFF_DBFS_FLOOR = -300.0


def rms_dbfs(rms, full_scale):
    """20*log10(rms / full_scale), clamped to RMS_DIFF_DBFS_FLOOR (finite)."""
    if not rms > 0:
        return RMS_DIFF_DBFS_FLOOR
    return max(float(20 * np.log10(rms / full_scale)), RMS_DIFF_DBFS_FLOOR)


WET_NAME_MARKERS = ("-wet", "_wet", ".wet")
DRY_NAME_MARKERS = ("-dry", "_dry", ".dry")


class TailRegionError(Exception):
    """The declared tail region cannot be established from committed data."""


def read_wav(path):
    with wave.open(path) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return a.astype(np.float64), sr


# ---------------------------------------------------------------------------
# spectral_corr definition (issue #110; a visible revision of the
# [PROPOSED-TO-BE-FROZEN-AT-PILOT] contract, recorded in
# contracts/fidelity-policy-DRAFT.md section 2.3 as input to the SXT-017
# freeze #12). ONE definition, shared by every comparator that grades the
# `spectral_corr` budget (this tool, compare_chorus_reference.py,
# compare_fx_reference.py and the tools that import their channel_metrics):
#
#   frames     non-overlapping 4096-sample frames (trailing partial frame
#              dropped), Hann window w = np.hanning(4096)
#   magnitude  m = |rfft(frame * w)| / (FS * sum(w) / 2), i.e. referenced to
#              the bus's DECLARED full scale FS (int16 bus: 32767 LSB; float32
#              bus: 1.0), so a full-scale sinusoid on a bin centre reads 1.0
#              (0 dBFS) in every unit system
#   floor      L = ln(max(m, 10 ** (SPECTRAL_CORR_FLOOR_DB / 20))), with
#              SPECTRAL_CORR_FLOOR_DB = -100 dBFS per bin
#   gating     none (every frame and every bin contributes)
#   statistic  Pearson correlation of L_ref and L_model over all
#              (frame, bin) pairs; zero-variance (all-floor) spectra give 1.0
#              when both floored spectra are identical and 0.0 otherwise;
#              renders shorter than one frame give 1.0 iff allclose.
#
# It replaces the pre-#110 native-unit `log1p(|X|)`, whose log knee sat at one
# int16 LSB here and at full scale in the float tools (~50 dB apart for the
# same name and the same 0.98 budget; reports/stereo-comparator-tail-gate/
# section 6). Why -100 dBFS per bin: it is 10 dB below the weakest sinusoid
# the int16 bus can carry (1 LSB peak = -90.3 dBFS), so every component the
# coarsest bus represents is graded, and ~35 dB above the int16 quantization
# noise per Hann bin (~-135 dBFS), so requantization alone cannot move the
# metric. The value was declared in #100 before any case was re-graded with
# it; it was NOT tuned to a case (the floor-sensitivity table in
# reports/spectral-corr-fs-floor/ shows how the re-graded verdicts move for
# neighbouring floors). The floor and the 0.98 budget are both
# [PROPOSED-TO-BE-FROZEN-AT-PILOT].
SPECTRAL_CORR_FRAME = 4096
SPECTRAL_CORR_FLOOR_DB = -100.0
SPECTRAL_CORR_DEFINITION = "fs-log-floor-v2 (Hann 4096, |X|/(FS*sum(w)/2), " \
                           "floor -100 dBFS/bin, no gating; issue #110)"
FULL_SCALE_INT16 = 32767.0
FULL_SCALE_F32 = 1.0


def _fs_log_spectrum(x, full_scale, frame, floor_db):
    w = np.hanning(frame)
    n = len(x) // frame * frame
    mag = np.abs(np.fft.rfft(np.asarray(x[:n], dtype=np.float64)
                             .reshape(-1, frame) * w, axis=1))
    mag /= full_scale * w.sum() / 2.0
    return np.log(np.maximum(mag, 10.0 ** (floor_db / 20.0))).ravel()


def spectral_corr(a, b, *, full_scale, frame=SPECTRAL_CORR_FRAME,
                  floor_db=SPECTRAL_CORR_FLOOR_DB):
    """spectral_corr under the shared definition above (issue #110).

    `full_scale` is REQUIRED and is the bus's declared full scale in the
    caller's native unit (FULL_SCALE_INT16 or FULL_SCALE_F32); it is what makes
    the metric unit-invariant, so there is deliberately no default."""
    if not full_scale > 0:
        raise ValueError("spectral_corr: full_scale must be > 0")
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if np.allclose(a[:n], b[:n]) else 0.0
    ra = _fs_log_spectrum(a[:n], full_scale, frame, floor_db)
    rb = _fs_log_spectrum(b[:n], full_scale, frame, floor_db)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    if d > 0:
        return float((ra * rb).sum() / d)
    return 1.0 if np.array_equal(ra, rb) else 0.0


def spectral_corr_legacy_log1p(a, b, frame=4096):
    """The pre-#110 native-unit definition, retained ONLY so the regrade
    record (tools/regrade_spectral_corr.py) can prove it recomputes the
    committed pre-#110 values from the same renders. Never used to grade."""
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if np.allclose(a[:n], b[:n]) else 0.0
    ra = np.log1p(np.abs(np.fft.rfft(a[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def name_declares(path, markers):
    return any(m in os.path.basename(path).lower() for m in markers)


def discover_sidecar(ref_path):
    """Conventional sidecar next to the reference render, or None.

    Committed conventions only (fixtures/render_fixture.py,
    tools/render_fx_fixtures.py, tools/render_*_reference.py):
      <dir>/<sequence>-wet.wav  ->  <dir>/<sequence>.json
      <render>.wav              ->  <render>.wav.json
    Nothing is guessed beyond these.
    """
    for suffix in ("-wet.f32.wav", "-wet.wav", "_wet.wav"):
        if ref_path.endswith(suffix):
            cand = ref_path[: -len(suffix)] + ".json"
            if os.path.exists(cand):
                return cand
    for cand in (ref_path + ".json", os.path.splitext(ref_path)[0] + ".json"):
        if os.path.exists(cand):
            return cand
    return None


def declared_tail_region(sidecar_path, bus):
    """Tail region from DECLARED fixture metadata only (never silence-inferred).

    Accepts the two committed sidecar shapes:
      * SXT-012 fixtures (`fixtures/audio/<preset>/<seq>.json`): per-bus
        `frames`, `last_event_sample`, `tail_s`, plus `engine.sample_rate`.
      * effect-slice fixtures (`reports/*/fixtures/*.json`): `render.frames`,
        `render.tail_s`, `render.sample_rate`.
    Raises TailRegionError when the region cannot be established from declared
    data; the caller then refuses instead of guessing (issue #93 stop
    condition).
    """
    with open(sidecar_path) as f:
        sc = json.load(f)
    if not isinstance(sc, dict):
        raise TailRegionError("sidecar %s is not a JSON object" % sidecar_path)
    render = sc.get("render") if isinstance(sc.get("render"), dict) else {}
    engine = sc.get("engine") if isinstance(sc.get("engine"), dict) else {}
    busd = sc.get(bus) if isinstance(sc.get(bus), dict) else None
    if busd is None:
        raise TailRegionError(
            "sidecar %s declares no '%s' bus block" % (sidecar_path, bus))

    sr = engine.get("sample_rate", render.get("sample_rate"))
    tail_s = busd.get("tail_s", render.get("tail_s"))
    total = busd.get("frames", render.get("frames"))
    missing = [n for n, v in (("sample_rate", sr), ("tail_s", tail_s),
                              ("frames", total)) if v is None]
    if missing:
        raise TailRegionError(
            "sidecar %s does not declare %s for bus '%s': a tail region cannot "
            "be defined from committed data, and this tool does not guess one "
            "(issue #93 stop condition)"
            % (sidecar_path, "/".join(missing), bus))

    length_f = float(tail_s) * float(sr)
    length = int(round(length_f))
    if abs(length_f - length) > 1e-6:
        raise TailRegionError(
            "declared tail_s=%r x sample_rate=%r is not an integral frame count "
            "(%r)" % (tail_s, sr, length_f))
    if length <= 0:
        raise TailRegionError(
            "declared tail_s=%r yields an empty tail region" % (tail_s,))
    total = int(total)

    if "last_event_sample" in busd:
        offset = int(busd["last_event_sample"])
        source = "sidecar %s.last_event_sample + declared tail_s" % bus
        if offset < 0 or offset + length > total:
            raise TailRegionError(
                "declared tail region [%d, %d) is not contained in the declared "
                "%d frames (sidecar %s)"
                % (offset, offset + length, total, sidecar_path))
    else:
        offset = total - length
        source = ("declared frames - tail_s (sidecar bus '%s' declares no "
                  "last_event_sample)" % bus)
        if offset < 0:
            raise TailRegionError(
                "declared tail (%d frames) exceeds the declared render length "
                "(%d frames) in sidecar %s" % (length, total, sidecar_path))

    return {
        "sidecar": sidecar_path,
        "bus": bus,
        "sample_rate": int(sr),
        "tail_s": tail_s,
        "declared_frames": total,
        "declared_sha256": busd.get("sha256"),
        "tail_offset": offset,
        "tail_frames": length,
        "tail_region_source": source,
    }


def tail_decay_curve(rt, mt, sample_rate, full_scale, budget=PROPOSED_TAIL):
    """Tail-shape leg (issue #111): windowed decay-curve comparison.

    rt/mt: the reference/model samples of the DECLARED tail region, in the
    caller's LSB unit; `full_scale` is full scale in that same unit, so the
    declared floor is applied in dBFS. Window levels use `rms_dbfs` (a silent
    window is RMS_DIFF_DBFS_FLOOR, i.e. far below any graded reference level,
    so a zeroed model window always fails). Returns the leg's record; `ok` is
    False when any graded window deviates by more than the budget, or when no
    reference window reaches the declared floor (the leg cannot grade the
    tail shape, and a leg that graded nothing is never reported as a pass).
    """
    win = int(round(float(budget["decay_curve_window_s"]) * sample_rate))
    floor = float(budget["decay_curve_floor_dbfs"])
    max_dev = float(budget["decay_curve_max_dev_db"])
    n = min(len(rt), len(mt))
    ref_db, mod_db = [], []
    for s in range(0, n, win):
        r = rt[s:s + win]
        m = mt[s:s + win]
        ref_db.append(rms_dbfs(float(np.sqrt((r * r).mean())), full_scale))
        mod_db.append(rms_dbfs(float(np.sqrt((m * m).mean())), full_scale))
    ref_db = np.array(ref_db)
    mod_db = np.array(mod_db)
    graded = ref_db >= floor
    out = {
        "window_frames": win,
        "floor_dbfs": floor,
        "floor_source": "declared budget PROPOSED_TAIL['decay_curve_floor_"
                        "dbfs'] (never inferred from silence)",
        "max_dev_budget_db": max_dev,
        "total_windows": int(len(ref_db)),
        "graded_windows": int(graded.sum()),
        "ref_first_window_dbfs": (float(ref_db[0]) if len(ref_db) else None),
        "ref_last_graded_window_dbfs": (float(ref_db[graded][-1])
                                        if graded.any() else None),
    }
    if not graded.any():
        out.update({"max_dev_db": None, "worst_window": None,
                    "windows_over_budget": 0, "ok": False,
                    "reason": ("no reference tail window reaches the declared "
                               "decay-curve floor %.1f dBFS; the tail shape "
                               "cannot be graded" % floor)})
        return out
    dev = np.abs(mod_db - ref_db)
    idx = np.flatnonzero(graded)
    worst = int(idx[np.argmax(dev[graded])])
    over = int((dev[graded] > max_dev).sum())
    out.update({
        "max_dev_db": float(dev[worst]),
        "worst_window": {"index": worst, "start_frame_in_tail": worst * win,
                         "ref_dbfs": float(ref_db[worst]),
                         "model_dbfs": float(mod_db[worst])},
        "windows_over_budget": over,
        "ok": over == 0,
        "reason": ("" if over == 0 else
                   "tail decay curve deviates %.2f dB (> %.2f dB budget) in "
                   "%d of %d graded windows (worst window %d: reference "
                   "%.1f dBFS, model %.1f dBFS)"
                   % (float(dev[worst]), max_dev, over, int(graded.sum()),
                      worst, float(ref_db[worst]), float(mod_db[worst]))),
    })
    return out


def tail_check(ref, mod, region, budget=PROPOSED_TAIL,
               full_scale=INT16_FULL_SCALE):
    """Tail-region agreement over the DECLARED region.

    Shape-compatible with tools/compare_chorus_reference.py's `tail_check`
    (`tail_present`, `tail_rms_rel_db`, `ok`) plus the explicit region
    provenance and the model-side presence leg the chorus tool lacks.

    Since issue #111 it also carries the tail-SHAPE leg (`tail_decay_curve`,
    see `tail_decay_curve`), and the per-leg results `tail_rms_rel_ok` /
    `tail_decay_curve_ok` so a record shows which leg decided. `full_scale`
    is full scale in the caller's LSB unit (int16: 32767; the stereo gate
    passes 1/lsb).
    """
    off = region["tail_offset"]
    length = region["tail_frames"]
    end = off + length
    out = {
        "tail_offset": off,
        "tail_frames": length,
        "tail_region_source": region["tail_region_source"],
        "tail_region_sidecar": region["sidecar"],
        "tail_budget": dict(budget),
    }
    covered = len(ref) >= end and len(mod) >= end
    out["tail_region_covered"] = bool(covered)
    if not covered:
        out.update({
            "tail_present": bool(len(ref) >= end
                                 and np.abs(ref[off:end]).max() > 0),
            "model_tail_present": False,
            "tail_max_abs_diff_lsb": None,
            "tail_rms_diff_lsb": None,
            "tail_rms_rel_db": None,
            "tail_ref_rms_lsb": None,
            "tail_model_rms_lsb": None,
            "tail_rms_rel_ok": False,
            "tail_decay_curve": None,
            "tail_decay_curve_ok": False,
            "ok": False,
            "reason": ("declared tail region [%d, %d) is not covered by the "
                       "compared renders (ref %d frames, model %d frames); a "
                       "truncated-window comparison cannot grade a tail"
                       % (off, end, len(ref), len(mod))),
        })
        return out

    rt = ref[off:end]
    mt = mod[off:end]
    d = np.abs(rt - mt)
    rms = float(np.sqrt((d * d).mean()))
    ref_rms = float(np.sqrt((rt * rt).mean()))
    mod_rms = float(np.sqrt((mt * mt).mean()))
    present = bool(np.abs(rt).max() > 0)
    model_present = bool(np.abs(mt).max() > 0)
    rel_db = (float(20 * np.log10(max(rms / ref_rms, 1e-30)))
              if ref_rms > 0 else None)
    reasons = []
    if not present:
        reasons.append("reference tail region carries no energy (this fixture "
                       "cannot support a wet-tail comparison)")
    if not model_present:
        reasons.append("model tail region is silent (dropped or stubbed tail)")
    rel_ok = rel_db is not None and rel_db <= budget["tail_rms_rel_db"]
    if rel_db is None:
        reasons.append("tail residual undefined (reference tail RMS is 0)")
    elif not rel_ok:
        reasons.append("tail residual %.2f dB exceeds the proposed %.2f dB "
                       "relative budget" % (rel_db, budget["tail_rms_rel_db"]))
    # tail-shape leg (issue #111): the residual above is dominated by the
    # early tail; this leg grades every declared-region window down to the
    # declared floor, so a late-tail truncation or late fast decay fails.
    dc = tail_decay_curve(rt, mt, region["sample_rate"], full_scale, budget)
    if not dc["ok"]:
        reasons.append(dc["reason"])
    out.update({
        "tail_present": present,
        "model_tail_present": model_present,
        "tail_max_abs_diff_lsb": float(d.max()),
        "tail_rms_diff_lsb": rms,
        "tail_rms_rel_db": rel_db,
        "tail_ref_rms_lsb": ref_rms,
        "tail_model_rms_lsb": mod_rms,
        "tail_rms_rel_ok": bool(rel_ok),
        "tail_decay_curve": dc,
        "tail_decay_curve_ok": bool(dc["ok"]),
        "ok": not reasons,
        "reason": "; ".join(reasons),
    })
    return out


def stereo_tail_gate(ref, mod, region, lsb, budget=PROPOSED_TAIL):
    """Wet-path tail gate for STEREO buses (issue #100).

    ref/mod: arrays shaped [2, N] at native float level; `lsb` converts to
    the comparator's LSB unit so the reported `*_lsb` fields are true. The
    same four legs as the mono gate (covered region, reference tail present,
    model tail present, relative residual budget) are applied to the mono sum
    (the returned `tail_check`, shape-identical to the mono tool's) AND to
    each of L and R (`tail_check_lr`), because a stereo model can drop or
    stub one channel's tail while the mono sum still carries energy. The
    gate passes only when all three pass. Since issue #111 each of the three
    also carries the tail-shape (decay-curve) leg; native full scale is 1.0,
    i.e. 1/lsb in the LSB unit.
    """
    ref = np.asarray(ref, dtype=np.float64) / lsb
    mod = np.asarray(mod, dtype=np.float64) / lsb
    fs = 1.0 / lsb
    mono = tail_check(0.5 * (ref[0] + ref[1]), 0.5 * (mod[0] + mod[1]),
                      region, budget, full_scale=fs)
    lr = {name: tail_check(ref[i], mod[i], region, budget, full_scale=fs)
          for name, i in (("L", 0), ("R", 1))}
    ok = bool(mono["ok"] and lr["L"]["ok"] and lr["R"]["ok"])
    reasons = ["%s: %s" % (name, c["reason"])
               for name, c in (("mono", mono), ("L", lr["L"]), ("R", lr["R"]))
               if not c["ok"]]
    return mono, lr, ok, "; ".join(reasons)


def validate_region_against_render(region, sr, frames, render_path):
    """Refusal reason (str) when the declared region does not describe the
    render it is applied to, else None. Mirrors the mono tool's checks."""
    if region["sample_rate"] != sr:
        return ("sidecar declares sample_rate %r but the reference render is "
                "%r Hz" % (region["sample_rate"], sr))
    if region["declared_frames"] != frames:
        return ("sidecar declares %d frames but %s holds %d: the sidecar is "
                "STALE with respect to the reference render"
                % (region["declared_frames"], os.path.basename(render_path),
                   frames))
    declared_sha = region.get("declared_sha256")
    if declared_sha:
        actual = oc.sha256_file(render_path)
        if actual != declared_sha:
            return ("sidecar declares %s sha256 %s... but %s hashes to %s...: "
                    "the tail region would be read from metadata that does "
                    "not describe this render"
                    % (region["bus"], declared_sha[:16],
                       os.path.basename(render_path), actual[:16]))
    return None


def refuse(reason, out_json=None):
    payload = {"verdict": "NO_VERDICT (refused)", "reason": reason}
    print(json.dumps(payload, indent=2))
    print("REFUSED: " + reason, file=sys.stderr)
    if out_json:
        with open(out_json, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--json", help="write metrics JSON here")
    ap.add_argument("--path", choices=("dry", "wet"), default="dry",
                    help="which bus is under test; 'wet' enables the "
                         "tail-region gate and selects the sidecar bus block "
                         "(default: dry -- no gate, AGENTS.md dry rule)")
    ap.add_argument("--sidecar",
                    help="fixture sidecar JSON declaring the tail region "
                         "(required for --path wet; auto-discovered next to "
                         "--ref when it follows the committed convention)")
    args = ap.parse_args()

    # Fail closed: a wet bus must never be graded through the ungated dry path.
    if args.path == "dry" and (name_declares(args.ref, WET_NAME_MARKERS)
                               or name_declares(args.model, WET_NAME_MARKERS)):
        return refuse(
            "reference/model filename declares a wet bus but --path wet was not "
            "passed; a wet comparison must be tail-gated (issue #93). Re-run "
            "with --path wet --sidecar <fixture>.json.", args.json)
    if args.path == "wet" and name_declares(args.ref, DRY_NAME_MARKERS):
        return refuse(
            "--path wet was passed but the reference filename declares a dry "
            "bus (%s); refusing to grade a mislabelled comparison."
            % os.path.basename(args.ref), args.json)

    region = None
    if args.path == "wet":
        sidecar = args.sidecar or discover_sidecar(args.ref)
        if not sidecar:
            return refuse(
                "--path wet requires a fixture sidecar declaring the tail "
                "region (note-off offset plus declared tail length); none was "
                "given and none was found next to %s. Do not guess a tail "
                "region -- record a bounded finding instead (issue #93 stop "
                "condition)." % args.ref, args.json)
        if not os.path.exists(sidecar):
            return refuse("sidecar not found: %s" % sidecar, args.json)
        try:
            region = declared_tail_region(sidecar, args.path)
        except TailRegionError as e:
            return refuse(str(e), args.json)

    ref, sr = read_wav(args.ref)
    mod, sr2 = read_wav(args.model)
    assert sr == sr2 == 48000, (sr, sr2)

    if region is not None:
        if region["sample_rate"] != sr:
            return refuse(
                "sidecar declares sample_rate %r but the reference render is "
                "%r Hz" % (region["sample_rate"], sr), args.json)
        if region["declared_frames"] != len(ref):
            return refuse(
                "sidecar declares %d frames but %s holds %d: the sidecar is "
                "STALE with respect to the reference render"
                % (region["declared_frames"], os.path.basename(args.ref),
                   len(ref)), args.json)
        declared_sha = region.get("declared_sha256")
        if declared_sha:
            actual = oc.sha256_file(args.ref)
            if actual != declared_sha:
                return refuse(
                    "sidecar declares %s sha256 %s... but %s hashes to %s...: "
                    "the tail region would be read from metadata that does not "
                    "describe this render"
                    % (region["bus"], declared_sha[:16],
                       os.path.basename(args.ref), actual[:16]), args.json)

    ref_full, mod_full = ref, mod
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
        "rms_diff_dbfs": rms_dbfs(float(np.sqrt((d * d).mean())), 32767.0),
        "rms_diff_at_shift0_lsb": shifts[0],
        "best_shift": best_shift,
        "rms_diff_at_best_shift_lsb": shifts[best_shift],
        "spectral_corr": spectral_corr(ref, mod, full_scale=FULL_SCALE_INT16),
        "spectral_corr_definition": SPECTRAL_CORR_DEFINITION,
    }

    proposed_results = {
        "max_abs_diff_lsb": metrics["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": metrics["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": metrics["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED
    metrics["proposed_budget_results"] = proposed_results
    budgets_ok = all(proposed_results.values())

    if region is None:
        # Dry path: pre-#93 output, byte for byte -- no tail gate, no new keys.
        metrics["verdict"] = ("PASS (PENDING-FREEZE: budgets are proposals, not "
                              "frozen policy)" if budgets_ok
                              else "FAIL against proposed budgets")
        rc = 0
    else:
        tc = tail_check(ref_full, mod_full, region,
                        full_scale=INT16_FULL_SCALE)
        metrics["path"] = "wet"
        metrics["fixture_sidecar"] = region["sidecar"]
        metrics["proposed_tail_budget"] = dict(PROPOSED_TAIL)
        metrics["tail_check"] = tc
        if budgets_ok and tc["ok"]:
            metrics["verdict"] = (
                "PASS (PENDING-FREEZE: budgets and the wet-path tail-region "
                "gate are proposals, not frozen policy)")
            rc = 0
        else:
            parts = []
            if not budgets_ok:
                parts.append("budget: " + ", ".join(
                    sorted(k for k, v in proposed_results.items() if not v)))
            if not tc["ok"]:
                parts.append("tail-region gate: " + tc["reason"])
            metrics["verdict"] = ("FAIL against proposed budgets (%s)"
                                  % "; ".join(parts))
            rc = 1

    print(json.dumps(metrics, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(metrics, f, indent=2)
            f.write("\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
