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
  spectral_corr       correlation of log-magnitude spectra over the whole
                      render (Hann-windowed, averaged per 4096-sample frame)

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
below the reference tail RMS. A truncated model render, a zeroed tail, or a
decayed-tail truncation therefore FAILS the verdict instead of passing on a
truncated-window comparison.

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
import hashlib
import json
import os
import sys
import wave

import numpy as np

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
PROPOSED_TAIL = {
    "tail_rms_rel_db": -20.0,       # residual RMS inside the declared tail
                                    # region, relative to the reference tail
                                    # RMS (tail reproduced to <= 10% RMS)
}

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


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    ra = np.log1p(np.abs(np.fft.rfft(a[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def tail_check(ref, mod, region, budget=PROPOSED_TAIL):
    """Tail-region agreement over the DECLARED region.

    Shape-compatible with tools/compare_chorus_reference.py's `tail_check`
    (`tail_present`, `tail_rms_rel_db`, `ok`) plus the explicit region
    provenance and the model-side presence leg the chorus tool lacks.
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
    if rel_db is None:
        reasons.append("tail residual undefined (reference tail RMS is 0)")
    elif rel_db > budget["tail_rms_rel_db"]:
        reasons.append("tail residual %.2f dB exceeds the proposed %.2f dB "
                       "relative budget" % (rel_db, budget["tail_rms_rel_db"]))
    out.update({
        "tail_present": present,
        "model_tail_present": model_present,
        "tail_max_abs_diff_lsb": float(d.max()),
        "tail_rms_diff_lsb": rms,
        "tail_rms_rel_db": rel_db,
        "tail_ref_rms_lsb": ref_rms,
        "tail_model_rms_lsb": mod_rms,
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
    gate passes only when all three pass.
    """
    ref = np.asarray(ref, dtype=np.float64) / lsb
    mod = np.asarray(mod, dtype=np.float64) / lsb
    mono = tail_check(0.5 * (ref[0] + ref[1]), 0.5 * (mod[0] + mod[1]),
                      region, budget)
    lr = {name: tail_check(ref[i], mod[i], region, budget)
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
        actual = sha256_file(render_path)
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
            actual = sha256_file(args.ref)
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
        "spectral_corr": spectral_corr(ref, mod),
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
        tc = tail_check(ref_full, mod_full, region)
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
