#!/usr/bin/env python3
"""Issue #93 checks: the wet-path tail gate in the shared audio comparator,
plus the dry re-run parity log.

Legs
----
[1] dry re-run parity. Every committed dry comparison case whose reference AND
    model renders are both committed is re-run twice: once with the pre-change
    tool (`git show <baseline-rev>:tools/compare_audio_reference.py`) and once
    with the working-tree tool. Byte-identical stdout and JSON is REQUIRED --
    the tail gate must not re-grade or re-shape any dry case (AGENTS.md dry
    rule). Where a committed per-case JSON exists it is diffed too; a
    difference there is pre-existing tool-lineage drift (the pre-2026-09-24
    inverted `rms_diff_dbfs` flag, issue #95), reported and attributed, never
    swallowed and never "fixed" here.

[2] wet tail-gate controls, on a committed SXT-012 wet fixture whose sidecar
    declares the tail region (`last_event_sample` + `tail_s`):
      full-tail              model == reference            -> PASS required
      drop-full-tail         declared tail region zeroed   -> FAIL required
      drop-decayed-tail      second half of the tail zeroed, chosen so that
                             ALL THREE global budgets still pass             ->
                             FAIL required *by the tail gate alone* (this is
                             the control that shows the gate does the work)
      truncate-at-tail-start model render ends at the tail offset -> FAIL
                             required (no pass by truncated-window compare)
      undeclared-wet-path    wet reference graded without --path wet ->
                             refusal (exit 2, NO_VERDICT) required
      no-sidecar             --path wet with no sidecar    -> refusal required
      stale-sidecar          sidecar frames/sha256 do not describe the
                             reference render                -> refusal required

Claim scope
-----------
This tool exercises COMPARATOR behaviour only. Leg 2 constructs its "model"
inputs from the committed reference render itself, so the `full-tail` PASS is a
tool self-test: it is NOT a model-vs-reference fidelity result and establishes
nothing about any model, RTL, preset, or sound. Leg 1 establishes only that the
dry output did not change.

Usage:
  python3 tools/tail_gate_checks.py [--scratch-root DIR] [--legs 1,2]
                                    [--baseline-rev origin/main]
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "compare_audio_reference.py")
ART = os.path.join(REPO, "reports", "shared-comparator-tail-gate", "artifacts")

# Wet control fixtures: committed SXT-012 mono int16 wet buses whose sidecars
# declare last_event_sample + tail_s (both tail regions are [153600, 273600)).
# A = Koala 2 (primary; long quiet effect tail), B = Behemoth (second preset,
# so the controls are not a property of one render).
WET_REF = os.path.join(REPO, "fixtures", "audio", "koala2",
                       "seq-notes-coverage-v1-wet.wav")
WET_SIDECAR = os.path.join(REPO, "fixtures", "audio", "koala2",
                           "seq-notes-coverage-v1.json")
WET_REF_B = os.path.join(REPO, "fixtures", "audio", "behemoth",
                         "seq-notes-coverage-v1-wet.wav")
WET_SIDECAR_B = os.path.join(REPO, "fixtures", "audio", "behemoth",
                             "seq-notes-coverage-v1.json")


def log_open():
    return []


def emit(lines, s=""):
    lines.append(s)
    print(s)


def read_wav_i16(path):
    with wave.open(path) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").copy()
    return a, sr


def write_wav_i16(path, data, sr=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.asarray(data, dtype="<i2").tobytes())


def run_tool(tool, ref, model, out_json, path="dry", sidecar=None):
    cmd = [sys.executable, tool, "--ref", ref, "--model", model,
           "--json", out_json]
    if path != "dry":
        cmd += ["--path", path]
    if sidecar:
        cmd += ["--sidecar", sidecar]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return r


# --------------------------------------------------------------------------
# Leg 1: dry re-run parity (pre-change tool vs working-tree tool)
# --------------------------------------------------------------------------

def _pair_key(basename):
    import re
    b = basename[:-4]
    for junk in ("model-", "model__", "reference-", "-ref", "-dry",
                 "-lfo-fixture", "-mw-fixture"):
        b = b.replace(junk, "")
    return tuple(sorted(t for t in re.split(r"[^A-Za-z0-9]+", b) if t))


def _is_mono16(path):
    try:
        with wave.open(path) as w:
            return w.getnchannels() == 1 and w.getsampwidth() == 2
    except Exception:
        return False


def discover_dry_cases():
    """Committed dry cases: (leaf, ref, model) with both renders committed.

    Pairing is by the committed naming conventions (`*-ref.wav` /
    `reference-*.wav` against `model*`), matched on the normalized
    carrier/sequence token set. Mono int16 only (the shared comparator's
    format); stereo float32 effect-slice fixtures are graded by their own
    tools and are reported as NOT_RUN here.
    """
    import glob
    cases, skipped = [], []
    for d in sorted(glob.glob(os.path.join(REPO, "reports", "*",
                                           "artifacts"))):
        wavs = [p for p in sorted(glob.glob(os.path.join(d, "*.wav")))
                if _is_mono16(p)]
        refs = [p for p in wavs if "ref" in os.path.basename(p).lower()]
        mods = [p for p in wavs
                if os.path.basename(p).lower().startswith("model")]
        leaf = os.path.basename(os.path.dirname(d))
        paired_r, paired_m = set(), set()
        for r in refs:
            for m in mods:
                if _pair_key(os.path.basename(r)) == _pair_key(
                        os.path.basename(m)):
                    cases.append((leaf, r, m))
                    paired_r.add(r)
                    paired_m.add(m)
        for p in refs:
            if p not in paired_r:
                skipped.append((leaf, p, "no committed model render"))
        for p in mods:
            if p not in paired_m:
                skipped.append((leaf, p, "no committed reference render"))
    return cases, skipped


# tokens a committed comparator-JSON filename may add on top of the
# carrier/sequence tokens of the case it grades (budget-<case>.json,
# audio-<case>.json, ...). Anything else is not treated as a match.
_JSON_NAME_EXTRA = {"budget", "audio", "compare", "metrics", "nc"}


def committed_json_for(ref):
    """Committed per-case comparator JSON for a discovered pair, or None.

    Matched by filename tokens only (the old dry JSONs record no input paths),
    and only when the JSON is in this tool's shape. A missing match is reported
    as NONE, never inferred.
    """
    import glob
    key = set(_pair_key(os.path.basename(ref)))
    for cand in sorted(glob.glob(os.path.join(os.path.dirname(ref),
                                              "*.json"))):
        toks = set(_pair_key(os.path.basename(cand)[:-5] + ".wav"))
        if not toks or not key <= toks or not (toks - key) <= _JSON_NAME_EXTRA:
            continue
        try:
            with open(cand) as f:
                j = json.load(f)
        except Exception:
            continue
        if isinstance(j, dict) and "rms_diff_at_shift0_lsb" in j:
            return cand
    return None


def classify_committed_diff(committed_bytes, current_bytes):
    """Attribute each key that differs between a committed JSON and a re-run.

    Classes:
      ULP(<key>)          -- same value to ~1e-9 relative (host float/BLAS
                             ordering); numerically the same measurement
      RMS-FLAG-#95(...)   -- the pre-2026-09-24 inverted rms_diff_dbfs flag and
                             the verdict that followed from it (issue #95)
      UNEXPLAINED(<key>)  -- anything else; surfaced loudly, never swallowed
    """
    try:
        a = json.loads(committed_bytes)
        b = json.loads(current_bytes)
    except Exception:
        return ["UNEXPLAINED(<unparseable JSON>)"]
    fa = a.get("proposed_budget_results") or {}
    fb = b.get("proposed_budget_results") or {}
    rms_flag_only = ({k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)}
                     == {"rms_diff_dbfs"})
    out = []
    for k in sorted(set(a) | set(b)):
        av, bv = a.get(k), b.get(k)
        if av == bv:
            continue
        if isinstance(av, float) and isinstance(bv, float) and \
                abs(av - bv) <= 1e-9 * max(1.0, abs(av)):
            out.append("ULP(%s)" % k)
        elif k == "proposed_budget_results" and rms_flag_only:
            out.append("RMS-FLAG-#95(proposed_budget_results.rms_diff_dbfs "
                       "%s -> %s)" % (fa.get("rms_diff_dbfs"),
                                      fb.get("rms_diff_dbfs")))
        elif k == "verdict" and rms_flag_only:
            out.append("RMS-FLAG-#95(verdict follows the corrected rms flag)")
        else:
            out.append("UNEXPLAINED(%s: %r -> %r)" % (k, av, bv))
    return out


def materialize_baseline(rev, scratch):
    """Write the pre-change comparator from <rev> into scratch; None on failure."""
    out = os.path.join(scratch, "baseline_compare_audio_reference.py")
    r = subprocess.run(["git", "show",
                        "%s:tools/compare_audio_reference.py" % rev],
                       capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0 or not r.stdout:
        return None, r.stderr.strip()
    with open(out, "w") as f:
        f.write(r.stdout)
    return out, None


def leg1(lines, scratch, baseline_rev):
    emit(lines, "=" * 74)
    emit(lines, "[1] dry re-run parity: pre-change tool (%s) vs working tree"
         % baseline_rev)
    emit(lines, "=" * 74)
    baseline, err = materialize_baseline(baseline_rev, scratch)
    if not baseline:
        emit(lines, "  NOT_RUN: could not materialize the baseline tool from "
                    "%s (%s)" % (baseline_rev, err))
        emit(lines, "  A leg that did not run is NOT a pass.")
        return False, {"status": "NOT_RUN", "reason": err or "git show failed"}

    cases, skipped = discover_dry_cases()
    emit(lines, "  discovered %d committed dry cases (mono int16, both renders "
                "committed)" % len(cases))
    ok = True
    rows = []
    for leaf, ref, model in cases:
        rel_ref = os.path.relpath(ref, REPO)
        rel_mod = os.path.relpath(model, REPO)
        base_json = os.path.join(scratch, "base.json")
        cur_json = os.path.join(scratch, "cur.json")
        rb = run_tool(baseline, ref, model, base_json)
        rc = run_tool(TOOL, ref, model, cur_json)
        same_stdout = rb.stdout == rc.stdout
        same_rc = rb.returncode == rc.returncode
        with open(base_json, "rb") as f:
            bb = f.read()
        with open(cur_json, "rb") as f:
            cb = f.read()
        same_json = bb == cb
        parity = same_stdout and same_json and same_rc
        ok &= parity
        cj = committed_json_for(ref)
        cj_status, cj_classes = "NONE", []
        if cj:
            with open(cj, "rb") as f:
                committed = f.read()
            if committed == cb:
                cj_status = "MATCHES-COMMITTED"
            else:
                cj_classes = classify_committed_diff(committed, cb)
                cj_status = "DIFFERS-FROM-COMMITTED: " + "; ".join(cj_classes)
        rows.append({"leaf": leaf, "ref": rel_ref, "model": rel_mod,
                     "baseline_vs_current": "BYTE-IDENTICAL" if parity
                                            else "DIFFERS",
                     "committed_json": os.path.relpath(cj, REPO) if cj else None,
                     "committed_json_status": cj_status,
                     "committed_json_diff_classes": cj_classes})
        emit(lines, "  %-10s %-52s %s | committed: %s"
             % (leaf, os.path.basename(rel_ref),
                "BYTE-IDENTICAL" if parity else "DIFFERS", cj_status))
        if not parity:
            emit(lines, "      baseline rc=%d current rc=%d stdout_same=%s "
                        "json_same=%s" % (rb.returncode, rc.returncode,
                                          same_stdout, same_json))
    for leaf, p, why in skipped:
        emit(lines, "  %-10s %-52s NOT_RUN (%s)"
             % (leaf, os.path.basename(p), why))
    unexplained = [r for r in rows
                   if any(c.startswith("UNEXPLAINED")
                          for c in r["committed_json_diff_classes"])]
    emit(lines, "  leg 1: %s (%d/%d dry cases byte-identical vs the pre-change "
                "tool)"
         % ("PASS" if ok else "FAIL",
            sum(1 for r in rows if r["baseline_vs_current"] == "BYTE-IDENTICAL"),
            len(rows)))
    emit(lines, "  committed-JSON comparison (supplementary, NOT this change's "
                "gate): %d match, %d differ"
         % (sum(1 for r in rows
                if r["committed_json_status"] == "MATCHES-COMMITTED"),
            sum(1 for r in rows
                if r["committed_json_status"].startswith("DIFFERS"))))
    emit(lines, "    all differences are ULP float ordering and/or the "
                "pre-2026-09-24 rms-flag lineage (#95);")
    emit(lines, "    unexplained committed differences: %d%s"
         % (len(unexplained),
            "" if not unexplained else " <== INVESTIGATE: "
            + ", ".join(r["ref"] for r in unexplained)))
    emit(lines, "    no committed artifact of another leaf is rewritten by this "
                "change.")
    emit(lines)
    return ok, {"status": "PASS" if ok else "FAIL",
                "baseline_rev": baseline_rev,
                "unexplained_committed_diffs": [r["ref"] for r in unexplained],
                "cases": rows,
                "not_run": [{"leaf": leaf, "render": os.path.relpath(p, REPO),
                             "reason": why} for leaf, p, why in skipped]}


# --------------------------------------------------------------------------
# Leg 2: wet tail-gate controls
# --------------------------------------------------------------------------

def region_of(sidecar_path):
    with open(sidecar_path) as f:
        sc = json.load(f)
    off = int(sc["wet"]["last_event_sample"])
    sr = int(sc["engine"]["sample_rate"])
    tail = int(round(float(sc["wet"]["tail_s"]) * sr))
    return off, tail, sr, sc["wet"]["tail_s"]


def dither(n, offset=0):
    """Deterministic +-1 LSB pattern (no RNG: reproducible across runtimes)."""
    i = np.arange(offset, offset + n, dtype=np.int64)
    return ((i * 2654435761) % 3).astype(np.int64) - 1


def leg2(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[2] wet-path tail-gate controls")
    emit(lines, "=" * 74)
    missing = [p for p in (WET_REF, WET_SIDECAR, WET_REF_B, WET_SIDECAR_B)
               if not os.path.exists(p)]
    if missing:
        emit(lines, "  NOT_RUN: committed wet control fixture(s) missing: %s"
             % ", ".join(os.path.relpath(p, REPO) for p in missing))
        emit(lines, "  A leg that did not run is NOT a pass.")
        return False, {"status": "NOT_RUN", "reason": "fixture missing"}

    off, tail, sr, tail_s = region_of(WET_SIDECAR)
    ref, _ = read_wav_i16(WET_REF)
    offb, tailb, srb, tail_sb = region_of(WET_SIDECAR_B)
    refb, _ = read_wav_i16(WET_REF_B)

    emit(lines, "  control fixture A : %s" % os.path.relpath(WET_REF, REPO))
    emit(lines, "    sidecar         : %s" % os.path.relpath(WET_SIDECAR, REPO))
    emit(lines, "    declared tail region: [%d, %d) = last_event_sample %d + "
                "tail_s %s x %d Hz" % (off, off + tail, off, tail_s, sr))
    emit(lines, "  control fixture B : %s" % os.path.relpath(WET_REF_B, REPO))
    emit(lines, "    sidecar         : %s"
         % os.path.relpath(WET_SIDECAR_B, REPO))
    emit(lines, "    declared tail region: [%d, %d) = last_event_sample %d + "
                "tail_s %s x %d Hz" % (offb, offb + tailb, offb, tail_sb, srb))
    emit(lines, "  NOTE (claim scope): every control 'model' below is built FROM"
                " the reference render itself,")
    emit(lines, "        so the PASS control is a comparator self-test -- NOT a "
                "model-vs-reference")
    emit(lines, "        fidelity result, and not a claim about any model, RTL, "
                "preset, or sound.")
    emit(lines)

    # ---- constructed control renders (scratch only; never committed) ------
    # (1) full tail, model differs from the reference by a deterministic
    #     +-1 LSB inside the first half of the declared tail: within every
    #     proposed budget AND within the tail budget -> must PASS.
    within = ref.astype(np.int64).copy()
    within[off:off + tail // 2] += dither(tail // 2, off)
    p_within = os.path.join(scratch, "a-full-tail-within-budget.wav")
    write_wav_i16(p_within, within, sr)

    # (2) declared tail region zeroed -> must FAIL (the drop-tail control)
    dropped = ref.copy()
    dropped[off:off + tail] = 0
    p_dropped = os.path.join(scratch, "a-drop-full-tail.wav")
    write_wav_i16(p_dropped, dropped, sr)

    # (3) tail present but decaying far too fast (extra exp decay, tau 0.4 s
    #     inside the declared region): a plausible stubbed/short tail that
    #     passes ALL THREE global budgets -> must FAIL on the tail gate alone
    t = np.arange(tail) / float(sr)
    fast = ref.copy()
    fast[off:off + tail] = np.round(ref[off:off + tail] * np.exp(-t / 0.4))
    p_fast = os.path.join(scratch, "a-tail-decays-too-fast.wav")
    write_wav_i16(p_fast, fast, sr)

    # (4) model render truncated exactly at the declared tail offset: the
    #     compared window is then bit-exact, so every global budget passes
    #     vacuously -> must FAIL on the tail gate alone (policy draft section 5
    #     rule 4: no pass by truncated-window comparison)
    p_trunc = os.path.join(scratch, "a-truncate-at-tail-start.wav")
    write_wav_i16(p_trunc, ref[:off], sr)

    # (5) refusal inputs: a wet-named reference with no sidecar beside it, and
    #     a short reference the committed sidecar does not describe
    nosidecar_dir = os.path.join(scratch, "no-sidecar")
    os.makedirs(nosidecar_dir, exist_ok=True)
    p_nosidecar_ref = os.path.join(nosidecar_dir, "orphan-wet.wav")
    write_wav_i16(p_nosidecar_ref, ref, sr)
    p_stale_ref = os.path.join(scratch, "a-short-wet.wav")
    write_wav_i16(p_stale_ref, ref[: off + tail // 2], sr)

    # (6) second preset, second reverb tail: dropped tail must fail there too
    droppedb = refb.copy()
    droppedb[offb:offb + tailb] = 0
    p_droppedb = os.path.join(scratch, "b-drop-full-tail.wav")
    write_wav_i16(p_droppedb, droppedb, srb)

    controls = [
        # name, ref, model, path, sidecar, expect, gate_only
        ("full-tail-within-budget", WET_REF, p_within, "wet", WET_SIDECAR,
         "PASS", False),
        ("drop-full-tail", WET_REF, p_dropped, "wet", WET_SIDECAR, "FAIL",
         False),
        ("tail-decays-too-fast", WET_REF, p_fast, "wet", WET_SIDECAR, "FAIL",
         True),
        ("truncate-at-tail-start", WET_REF, p_trunc, "wet", WET_SIDECAR,
         "FAIL", True),
        ("undeclared-wet-path", WET_REF, p_within, "dry", None, "REFUSE",
         False),
        ("no-sidecar", p_nosidecar_ref, p_within, "wet", None, "REFUSE",
         False),
        ("stale-sidecar", p_stale_ref, p_within, "wet", WET_SIDECAR, "REFUSE",
         False),
        ("drop-full-tail-second-preset", WET_REF_B, p_droppedb, "wet",
         WET_SIDECAR_B, "FAIL", False),
    ]

    ok = True
    rows = []
    for name, r_in, m_in, path, sidecar, expect, gate_only in controls:
        out_json = os.path.join(ART, "tailgate-%s.json" % name)
        r = run_tool(TOOL, r_in, m_in, out_json, path=path, sidecar=sidecar)
        with open(out_json) as f:
            j = json.load(f)
        verdict = j.get("verdict", "<none>")
        got = ("PASS" if verdict.startswith("PASS")
               else "REFUSE" if verdict.startswith("NO_VERDICT")
               else "FAIL" if verdict.startswith("FAIL") else "?")
        expect_rc = {"PASS": 0, "FAIL": 1, "REFUSE": 2}[expect]
        good = got == expect and r.returncode == expect_rc
        tc = j.get("tail_check") or {}
        emit(lines, "  %-24s expect %-7s got %-7s rc=%d  %s"
             % (name, expect, got, r.returncode, "OK" if good else "WRONG"))
        if tc:
            emit(lines, "      tail: covered=%s ref_present=%s "
                        "model_present=%s rel=%s dB ok=%s"
                 % (tc.get("tail_region_covered"), tc.get("tail_present"),
                    tc.get("model_tail_present"),
                    ("%.2f" % tc["tail_rms_rel_db"])
                    if tc.get("tail_rms_rel_db") is not None else "n/a",
                    tc.get("ok")))
        if "proposed_budget_results" in j:
            pb = j["proposed_budget_results"]
            emit(lines, "      budgets: max=%s rms=%s corr=%s  "
                        "(max %.0f LSB, rms %.2f dBFS, corr %.4f)"
                 % (pb["max_abs_diff_lsb"], pb["rms_diff_dbfs"],
                    pb["spectral_corr"], j["max_abs_diff_lsb"],
                    j["rms_diff_dbfs"], j["spectral_corr"]))
        if verdict.startswith("FAIL") or verdict.startswith("NO_VERDICT"):
            emit(lines, "      %s" % (j.get("reason") or verdict))

        # decisive controls: the three global budgets must PASS while the tail
        # gate alone forces the FAIL (otherwise the gate is not load-bearing)
        if gate_only:
            budgets_pass = all(j["proposed_budget_results"].values())
            gate_fails = not tc.get("ok", True)
            if not (budgets_pass and gate_fails):
                good = False
                emit(lines, "      WRONG: this control must pass all three "
                            "global budgets and fail ONLY on the tail gate "
                            "(budgets_pass=%s gate_fails=%s)"
                     % (budgets_pass, gate_fails))
            else:
                emit(lines, "      all three global budgets PASS; the verdict "
                            "is FAIL solely because of the tail gate")
        ok &= good
        rows.append({"control": name, "expect": expect, "got": got,
                     "returncode": r.returncode,
                     "gate_only_required": bool(gate_only),
                     "json": os.path.relpath(out_json, REPO),
                     "verdict": verdict, "as_required": bool(good)})
        emit(lines)
    emit(lines, "  leg 2: %s (%d/%d controls behaved as required)"
         % ("PASS" if ok else "FAIL",
            sum(1 for x in rows if x["as_required"]), len(rows)))
    emit(lines)
    return ok, {
        "status": "PASS" if ok else "FAIL",
        "claim_scope": ("comparator behaviour only; control models are derived "
                        "from the reference render, so no model-vs-reference, "
                        "RTL, preset-support or sound claim follows"),
        "controls": rows,
        "fixtures": [
            {"reference": os.path.relpath(WET_REF, REPO),
             "sidecar": os.path.relpath(WET_SIDECAR, REPO),
             "declared_tail_region": {"offset": off, "frames": tail}},
            {"reference": os.path.relpath(WET_REF_B, REPO),
             "sidecar": os.path.relpath(WET_SIDECAR_B, REPO),
             "declared_tail_region": {"offset": offb, "frames": tailb}},
        ]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt-tail-gate-checks")
    ap.add_argument("--legs", default="1,2")
    ap.add_argument("--baseline-rev", default="origin/main",
                    help="git rev holding the pre-#93 comparator (leg 1)")
    args = ap.parse_args()
    legs = {int(x) for x in args.legs.split(",") if x.strip()}

    scratch = args.scratch_root
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    os.makedirs(ART, exist_ok=True)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=REPO).stdout.strip()
    header = log_open()
    emit(header, "issue #93 -- shared-comparator wet-path tail gate: checks")
    emit(header, "run: %s   repo HEAD: %s" % (stamp, head))
    emit(header, "tool: tools/compare_audio_reference.py")
    emit(header, "claim scope: comparator behaviour only. No "
                 "model-vs-reference, RTL, preset-support,")
    emit(header, "             or sound-quality claim follows from anything "
                 "below.")
    emit(header)

    summary = {"issue": 93, "run_utc": stamp, "repo_head": head, "legs": {}}
    ok = True
    l1, l2 = None, None
    if 1 in legs:
        l1 = list(header)
        good, rep = leg1(l1, scratch, args.baseline_rev)
        ok &= good
        summary["legs"]["dry_rerun_parity"] = rep
    else:
        summary["legs"]["dry_rerun_parity"] = {"status": "NOT_RUN",
                                               "reason": "leg not selected"}
    if 2 in legs:
        l2 = list(header)
        good, rep = leg2(l2, scratch)
        ok &= good
        summary["legs"]["wet_tail_controls"] = rep
    else:
        summary["legs"]["wet_tail_controls"] = {"status": "NOT_RUN",
                                                "reason": "leg not selected"}

    summary["overall"] = "PASS" if ok else "FAIL"
    print("OVERALL: %s" % summary["overall"])

    if l2 is not None:
        l2.append("leg 2 verdict: %s"
                  % summary["legs"]["wet_tail_controls"]["status"])
        with open(os.path.join(ART, "negative-controls.txt"), "w") as f:
            f.write("\n".join(l2) + "\n")
    if l1 is not None:
        l1.append("leg 1 verdict: %s"
                  % summary["legs"]["dry_rerun_parity"]["status"])
        with open(os.path.join(ART, "rerun-dry-cases.txt"), "w") as f:
            f.write("\n".join(l1) + "\n")
    with open(os.path.join(ART, "checks-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
