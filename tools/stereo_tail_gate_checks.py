#!/usr/bin/env python3
"""Issue #100 checks: the wet-path tail gate on the STEREO float32 effect-slice
comparators, the rms_diff_dbfs exact-agreement decision, and the spectral_corr
sensitivity characterization.

Legs
----
[1] SXT-028c re-run. The six committed SXT-028c comparison cases are re-run
    with the gated tools/compare_chorus_reference.py. "Before" is the
    committed artifact at PRE_CHANGE_REV (the pre-#100 record, read with
    `git show`, so re-running this leg after the regenerated artifacts land
    still diffs against the original record). Every changed key is listed and
    attributed: SCHEMA (key added/removed by the #100 schema change),
    VERDICT-TEXT (verdict string reworded, status unchanged), ULP (numeric
    value equal to 1e-12 relative: host float/BLAS ordering), or UNEXPLAINED.
    A verdict STATUS change (PASS <-> FAIL) or any UNEXPLAINED difference makes
    the leg FAIL -- that is the issue's stop/escalate condition, and this leg
    reports it rather than hiding it. --write-artifacts regenerates the six
    committed artifacts from the gated tool (only when the leg passes).

[2] Stereo tail-gate controls. Built from the COMMITTED SXT-028c model render
    (real model output) on two fixtures, and from the committed sxt-023 EQ
    model render (the fx comparator's one PASS case):
      baseline                committed model render            -> PASS
      drop-full-tail          declared tail region zeroed (L+R) -> FAIL
      tail-decays-too-fast    extra exp decay (tau 0.4 s) in the
                              declared region                   -> FAIL
      drop-right-tail         R channel's declared tail zeroed  -> FAIL
      truncate-at-tail-start  model render ends at the tail offset -> FAIL
      refusals                missing sidecar / undeclared tail_s / stale
                              frames / sha256 mismatch          -> NO_VERDICT
    The pre-#100 chorus tool (materialized from PRE_CHANGE_REV) is run on the
    same drop-tail / fast-decay renders so the record shows exactly which
    controls the old reference-tail-only gate let through.

[3] rms_diff_dbfs exact agreement. Each emitter (shared mono, chorus, fx) is
    fed an exact-agreement pair; the field must equal RMS_DIFF_DBFS_FLOOR and
    the emitted JSON must parse under a STRICT parser (no -Infinity/NaN).
    Every committed reports/**/*.json is also strict-parsed.

[4] spectral_corr sensitivity sweep (characterization only; the metric is NOT
    changed by #100). Deterministic +-k LSB perturbations are added to
    committed fixtures -- everywhere, only in near-silent frames, only in
    loud frames -- and spectral_corr / rms_diff_dbfs / max_abs_diff are
    recorded for the shared int16 metric and the stereo float metric. Two
    candidate treatments for the pilot freeze are evaluated on the same
    perturbations and on the four committed SXT-040 cases that spectral_corr
    alone decides today.

[5] The other two stereo comparators. sxt-023's three committed cases are
    re-run with the gated compare_fx_reference.py, and sxt-024's three graded
    cases with the gated compare_reverb_model.py AND with the pre-#100 reverb
    tool on the same host (so the gate's effect is separated from the
    pre-existing host drift of the committed sxt-024 record). A verdict status
    change FAILs the leg (stop/escalate). Those leaves' committed artifacts
    are NOT rewritten; the gated re-runs are retained under
    artifacts/sxt023-rerun/ and artifacts/sxt024-rerun/.

Claim scope
-----------
Comparator behaviour only. Control "models" in leg 2 are derived from
committed renders; nothing here is a new model-vs-reference, RTL,
preset-support, or sound-quality claim, and no budget is frozen.

Usage:
  python3 tools/stereo_tail_gate_checks.py [--legs 1,2,3,4,5]
      [--scratch-root DIR] [--write-artifacts]
"""

import argparse
import copy
import datetime
import glob
import json
import os
import shutil
import struct
import subprocess
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

ART = os.path.join(REPO, "reports", "stereo-comparator-tail-gate", "artifacts")
CHORUS = os.path.join(REPO, "tools", "compare_chorus_reference.py")
FX = os.path.join(REPO, "tools", "compare_fx_reference.py")
SHARED = os.path.join(REPO, "tools", "compare_audio_reference.py")
# main before issue #100 (holds the pre-#100 tools and SXT-028c record)
PRE_CHANGE_REV = "b326bc00eaa81bbad74ee71c004f3ae86983f569"

SXT028C = os.path.join(REPO, "reports", "SXT-028c")
CASES = [(s, q) for s in ("alienappears", "fmcombo", "fmtwang2")
         for q in ("seq-notes-coverage-v1", "seq-poly-8-v1")]
LSB = 2.0 ** -21


def emit(lines, s=""):
    lines.append(s)
    print(s)


def resolve_rev(rev):
    r = subprocess.run(["git", "rev-parse", "--verify", rev + "^{commit}"],
                       capture_output=True, text=True, cwd=REPO)
    return r.stdout.strip() if r.returncode == 0 else None


def git_show(rev, path):
    r = subprocess.run(["git", "show", "%s:%s" % (rev, path)],
                       capture_output=True, cwd=REPO)
    return r.stdout if r.returncode == 0 else None


def strict_loads(text):
    def bad(tok):
        raise ValueError("non-standard JSON token %s" % tok)
    return json.loads(text, parse_constant=bad)


# ------------------------------------------------------------ wav helpers --

def read_f32(path):
    with open(path, "rb") as f:
        data = f.read()
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + sz]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + sz + (sz & 1)
    assert fmt[0] == 3 and fmt[1] == 2 and fmt[5] == 32, path
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).T.copy()


def write_f32(path, a):
    a = np.asarray(a, dtype="<f4")
    inter = a.T.reshape(-1).tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, 48000, 48000 * 8, 8, 32)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(inter)) + inter)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def run(cmd):
    r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True,
                       cwd=REPO)
    return r


# ---------------------------------------------------------------- leg 1 --

def _num_equal(a, b, rel=1e-12):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return True
        return abs(a - b) <= rel * max(abs(a), abs(b))
    return None


def flat(o, pre=""):
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(flat(v, pre + "/" + k))
    else:
        out[pre] = o
    return out


def status_of(verdict):
    return (verdict or "").split(" ", 1)[0]


def classify(before, after):
    fb, fa = flat(before), flat(after)
    rows = []
    for k in sorted(set(fb) | set(fa)):
        if k not in fa:
            rows.append((k, "SCHEMA(removed)", fb[k], None))
        elif k not in fb:
            rows.append((k, "SCHEMA(added)", None, fa[k]))
        elif fb[k] != fa[k]:
            if k == "/verdict":
                cls = ("VERDICT-TEXT(status %s unchanged)" % status_of(fa[k])
                       if status_of(fb[k]) == status_of(fa[k])
                       else "VERDICT-STATUS-CHANGE")
            elif k == "/schema_version":
                cls = "SCHEMA(version)"
            elif k == "/tail_check/tail_rms_rel_db":
                # same field, new window: the declared 2.5 s region replaces
                # the hard-coded last-2.0 s window (the change #100 asks for)
                cls = "TAIL-WINDOW(declared region replaces hard-coded 2.0 s)"
            elif _num_equal(fb[k], fa[k]):
                cls = "ULP"
            else:
                cls = "UNEXPLAINED"
            rows.append((k, cls, fb[k], fa[k]))
    return rows


def leg1(lines, scratch, write_artifacts):
    emit(lines, "=" * 74)
    emit(lines, "[1] SXT-028c: six committed comparison cases re-run under "
                "the gated stereo comparator")
    emit(lines, "=" * 74)
    rev = resolve_rev(PRE_CHANGE_REV)
    if rev is None:
        emit(lines, "  NOT_RUN: pre-change rev %s not available in this clone"
             % PRE_CHANGE_REV)
        return False, {"status": "NOT_RUN", "reason": "baseline rev missing"}
    emit(lines, "  before = committed artifact at %s (pre-#100 record)" % rev)
    emit(lines, "  after  = tools/compare_chorus_reference.py (working tree)")
    emit(lines)
    out_dir = os.path.join(scratch, "leg1")
    os.makedirs(out_dir, exist_ok=True)
    ok = True
    rows = []
    for slug, seq in CASES:
        name = "compare-%s__%s.json" % (slug, seq)
        rel = "reports/SXT-028c/artifacts/" + name
        before_raw = git_show(rev, rel)
        if before_raw is None:
            emit(lines, "  %s: NOT_RUN (no committed before-artifact)" % name)
            ok = False
            continue
        before = json.loads(before_raw)
        after_path = os.path.join(out_dir, name)
        r = run([CHORUS, "--slug", slug, "--seq", seq, "--json", after_path])
        if r.returncode != 0:
            emit(lines, "  %s: gated tool exit %d (%s)"
                 % (name, r.returncode, r.stdout.strip()[:200]))
            ok = False
            rows.append({"case": name, "status": "NO_VERDICT"})
            continue
        with open(after_path) as f:
            after = strict_loads(f.read())
        diff = classify(before, after)
        counts = {}
        for _k, cls, _b, _a in diff:
            key = cls.split("(")[0]
            counts[key] = counts.get(key, 0) + 1
        flips = [d for d in diff if d[1] == "VERDICT-STATUS-CHANGE"]
        unexpl = [d for d in diff if d[1] == "UNEXPLAINED"]
        case_ok = not flips and not unexpl
        ok &= case_ok
        tc = after["tail_check"]
        lr = after["tail_check_lr"]
        emit(lines, "  %s" % name)
        emit(lines, "    verdict before: %s" % before["verdict"])
        emit(lines, "    verdict after : %s" % after["verdict"])
        emit(lines, "    status        : %s -> %s  (%s)"
             % (status_of(before["verdict"]), status_of(after["verdict"]),
                "unchanged" if not flips else "CHANGED -- STOP/ESCALATE"))
        emit(lines, "    declared tail region: [%d, %d) from %s"
             % (tc["tail_offset"], tc["tail_offset"] + tc["tail_frames"],
                tc["tail_region_sidecar"]))
        emit(lines, "    old tail window     : last 2.0 s (hard-coded) -> "
                    "tail_rms_rel_db %.2f (mono, reference-presence gate only)"
             % before["channels"]["tail_mono"]["tail_rms_rel_db"])
        emit(lines, "    gated tail legs     : covered=%s ref_present=%s "
                    "model_present=%s"
             % (tc["tail_region_covered"], tc["tail_present"],
                tc["model_tail_present"]))
        emit(lines, "    tail residual (dB re ref tail RMS, budget %.1f): mono "
                    "%.2f  L %.2f  R %.2f  -> gate %s"
             % (car.PROPOSED_TAIL["tail_rms_rel_db"], tc["tail_rms_rel_db"],
                lr["L"]["tail_rms_rel_db"], lr["R"]["tail_rms_rel_db"],
                "PASS" if after["tail_gate_ok"] else "FAIL"))
        emit(lines, "    key diff: %s" % ", ".join(
            "%s=%d" % kv for kv in sorted(counts.items())))
        for k, cls, b, a in diff:
            if cls in ("ULP", "UNEXPLAINED", "VERDICT-STATUS-CHANGE",
                       "SCHEMA(removed)", "SCHEMA(version)") \
                    or cls.startswith(("VERDICT-TEXT", "TAIL-WINDOW")):
                emit(lines, "      %-44s %-34s %r -> %r" % (k, cls, b, a))
        added = [k for k, cls, _b, _a in diff if cls == "SCHEMA(added)"]
        emit(lines, "      SCHEMA(added): %d keys under %s"
             % (len(added), sorted({"/".join(k.split("/")[:2]) for k in added})))
        rows.append({
            "case": name,
            "status_before": status_of(before["verdict"]),
            "status_after": status_of(after["verdict"]),
            "tail_gate_ok": after["tail_gate_ok"],
            "tail_rms_rel_db": {"mono": tc["tail_rms_rel_db"],
                                "L": lr["L"]["tail_rms_rel_db"],
                                "R": lr["R"]["tail_rms_rel_db"]},
            "old_window_tail_rms_rel_db":
                before["channels"]["tail_mono"]["tail_rms_rel_db"],
            "diff_counts": counts,
            "unexplained": len(unexpl),
            "verdict_status_changed": bool(flips),
        })
        if write_artifacts and case_ok:
            shutil.copyfile(after_path,
                            os.path.join(SXT028C, "artifacts", name))
    emit(lines)
    n_pass = sum(1 for r in rows if r.get("status_after") == "PASS")
    emit(lines, "  result: %d/6 re-run; %d/6 PASS under the gated tool; "
                "verdict status changes: %d; unexplained diffs: %d"
         % (len([r for r in rows if "status_after" in r]), n_pass,
            sum(1 for r in rows if r.get("verdict_status_changed")),
            sum(r.get("unexplained", 0) for r in rows)))
    if write_artifacts:
        emit(lines, "  committed artifacts regenerated: %s"
             % ("yes" if ok else "NO (leg failed; nothing overwritten)"))
    return ok, {"status": "PASS" if ok else "FAIL", "pre_change_rev": rev,
                "cases": rows}


# ---------------------------------------------------------------- leg 2 --

def _mutations(model, off, length):
    """Control renders derived from a committed model render [2, N]."""
    end = off + length
    t = np.arange(length) / 48000.0
    out = {}
    m = model.copy()
    m[:, off:end] = 0.0
    out["drop-full-tail"] = m
    m = model.copy()
    m[:, off:end] = m[:, off:end] * np.exp(-t / 0.4)
    out["tail-decays-too-fast"] = m
    m = model.copy()
    m[1, off:end] = 0.0
    out["drop-right-tail"] = m
    out["truncate-at-tail-start"] = model[:, :off].copy()
    return out


def _summarize(j):
    ch = j.get("channels", {}).get("mono", {})
    return {
        "verdict": j.get("verdict"),
        "status": status_of(j.get("verdict")),
        "budgets": j.get("proposed_budget_results"),
        "max_abs_diff_lsb": ch.get("max_abs_diff_lsb"),
        "rms_diff_dbfs": ch.get("rms_diff_dbfs"),
        "spectral_corr": ch.get("spectral_corr"),
        "tail_gate_ok": j.get("tail_gate_ok"),
        "tail_rms_rel_db": (j.get("tail_check") or {}).get("tail_rms_rel_db"),
        "model_tail_present": (j.get("tail_check") or {}).get(
            "model_tail_present"),
        "tail_region_covered": (j.get("tail_check") or {}).get(
            "tail_region_covered"),
    }


def leg2(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[2] stereo tail-gate controls (each must fail the check it "
                "targets)")
    emit(lines, "=" * 74)
    rev = resolve_rev(PRE_CHANGE_REV)
    old_tool = None
    if rev is not None:
        src = git_show(rev, "tools/compare_chorus_reference.py")
        if src is not None:
            old_root = os.path.join(scratch, "pre100")
            os.makedirs(os.path.join(old_root, "tools"), exist_ok=True)
            old_tool = os.path.join(old_root, "tools",
                                    "compare_chorus_reference.py")
            with open(old_tool, "wb") as f:
                f.write(src)
    emit(lines, "  NOTE (claim scope): baselines are the COMMITTED model "
                "renders; every other control")
    emit(lines, "        render is derived from them. Nothing here is a new "
                "fidelity, support, or sound claim.")
    emit(lines)
    rows = []
    ok = True

    def expect(name, tool, r, j, required, extra=None):
        nonlocal ok
        st = "NO_VERDICT" if r.returncode == 2 else status_of(j.get("verdict"))
        good = (st == required)
        ok &= good
        row = {"control": name, "tool": tool, "required": required,
               "observed": st, "exit": r.returncode,
               "result": "CONTROL-OK" if good else "CONTROL-BROKEN"}
        row.update(_summarize(j) if st != "NO_VERDICT"
                   else {"reason": j.get("reason")})
        if st == "FAIL":
            legs = sorted("budget:" + k for k, v in
                          (j.get("proposed_budget_results") or {}).items()
                          if not v)
            if j.get("tail_gate_ok") is False:
                legs.append("tail-gate")
            row["failed_by"] = legs
        if extra:
            row.update(extra)
        rows.append(row)
        emit(lines, "  %-34s %-6s required %-10s observed %-10s exit %d  %s"
             % (name, tool, required, st, r.returncode, row["result"]))
        if row.get("failed_by"):
            emit(lines, "      failed by: %s" % ", ".join(row["failed_by"]))
        if st == "NO_VERDICT":
            emit(lines, "      reason: %s" % j.get("reason"))
        else:
            b = j.get("proposed_budget_results") or {}
            emit(lines, "      budgets max/rms/corr = %s/%s/%s  (max %.1f LSB, "
                        "rms %.2f dBFS, corr %.6f)"
                 % (b.get("max_abs_diff_lsb"), b.get("rms_diff_dbfs"),
                    b.get("spectral_corr"), row["max_abs_diff_lsb"],
                    row["rms_diff_dbfs"], row["spectral_corr"]))
            tc = j.get("tail_check") or {}
            rel = tc.get("tail_rms_rel_db")
            emit(lines, "      tail gate %s: covered=%s model_present=%s "
                        "residual=%s"
                 % ("PASS" if j.get("tail_gate_ok") else "FAIL",
                    tc.get("tail_region_covered"),
                    tc.get("model_tail_present"),
                    "n/a" if rel is None else "%.2f dB" % rel))
            lr = j.get("tail_check_lr") or {}
            for c in ("L", "R"):
                if c in lr:
                    rr = lr[c].get("tail_rms_rel_db")
                    emit(lines, "        %s: model_present=%s residual=%s ok=%s"
                         % (c, lr[c].get("model_tail_present"),
                            "n/a" if rr is None else "%.2f dB" % rr,
                            lr[c].get("ok")))
        return row

    # ---- chorus comparator on two SXT-028c fixtures -----------------------
    for slug, seq in (("fmcombo", "seq-notes-coverage-v1"),
                      ("alienappears", "seq-notes-coverage-v1")):
        fx_dir = os.path.join(SXT028C, "fixtures")
        sidecar = os.path.join(fx_dir, "%s__%s.json" % (slug, seq))
        model_path = os.path.join(SXT028C, "artifacts",
                                  "model__%s__%s.f32.wav" % (slug, seq))
        region = car.declared_tail_region(sidecar, "wet")
        off, length = region["tail_offset"], region["tail_frames"]
        emit(lines, "  fixture %s x %s: declared tail region [%d, %d) "
                    "(render.frames %d - render.tail_s %s x %d)"
             % (slug, seq, off, off + length, region["declared_frames"],
                region["tail_s"], region["sample_rate"]))
        d = os.path.join(scratch, "leg2", slug)
        os.makedirs(d, exist_ok=True)
        base = read_f32(model_path)
        renders = {"baseline": model_path}
        for name, arr in _mutations(base, off, length).items():
            p = os.path.join(d, "%s.f32.wav" % name)
            write_f32(p, arr)
            renders[name] = p
        for name, p in renders.items():
            out = os.path.join(d, "%s.json" % name)
            r = run([CHORUS, "--slug", slug, "--seq", seq, "--model", p,
                     "--json", out])
            j = json.load(open(out)) if os.path.exists(out) else {}
            extra = {}
            if old_tool and name != "baseline":
                # what the pre-#100 gate (reference-tail presence) said
                old_art = os.path.join(d, "old-" + name)
                os.makedirs(old_art, exist_ok=True)
                shutil.copyfile(p, os.path.join(
                    old_art, "model__%s__%s.f32.wav" % (slug, seq)))
                oj = os.path.join(old_art, "old.json")
                subprocess.run([sys.executable, old_tool, "--slug", slug,
                                "--seq", seq, "--fixtures-dir", fx_dir,
                                "--art-dir", old_art, "--json", oj],
                               capture_output=True, text=True, cwd=REPO)
                if os.path.exists(oj):
                    extra["pre100_tool_status"] = status_of(
                        json.load(open(oj)).get("verdict"))
            required = "PASS" if name == "baseline" else "FAIL"
            row = expect("%s/%s" % (slug, name), "chorus", r, j, required,
                         extra)
            if "pre100_tool_status" in row:
                emit(lines, "      pre-#100 chorus tool on the same render: %s"
                     % row["pre100_tool_status"])
            if name == "drop-full-tail" and slug == "fmcombo":
                with open(os.path.join(ART, "control-drop-full-tail-%s.json"
                                       % slug), "w") as f:
                    json.dump(j, f, indent=2)
                    f.write("\n")
            if name == "tail-decays-too-fast":
                with open(os.path.join(ART, "control-tail-decays-too-fast-%s"
                                       ".json" % slug), "w") as f:
                    json.dump(j, f, indent=2)
                    f.write("\n")
        emit(lines)

    # ---- KNOWN GAP probe (recorded, not asserted as a control) -------------
    # The relative-RMS tail leg integrates over the WHOLE declared region, so
    # it is dominated by the early (loud) tail. Zeroing only the late part of
    # a long reverb tail can pass every budget AND the gate. This probe keeps
    # that visible; it is a documented gap (follow-up #111), never counted as
    # a control and never reported as evidence that the gate catches it.
    gaps = []
    slug, seq = "alienappears", "seq-notes-coverage-v1"
    sidecar = os.path.join(SXT028C, "fixtures", "%s__%s.json" % (slug, seq))
    region = car.declared_tail_region(sidecar, "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    base = read_f32(os.path.join(SXT028C, "artifacts",
                                 "model__%s__%s.f32.wav" % (slug, seq)))
    d = os.path.join(scratch, "leg2", "gap")
    os.makedirs(d, exist_ok=True)
    emit(lines, "  KNOWN-GAP probes (NOT controls; outcome recorded, not "
                "asserted):")
    for frac in (0.3, 0.4, 0.6):
        m = base.copy()
        s0 = off + int(length * frac)
        m[:, s0:off + length] = 0.0
        p = os.path.join(d, "zero-late-tail-from-%d.f32.wav" % int(frac * 100))
        write_f32(p, m)
        out = p + ".json"
        r = run([CHORUS, "--slug", slug, "--seq", seq, "--model", p,
                 "--json", out])
        j = json.load(open(out))
        row = {"probe": "%s/zero-late-tail-from-%d%%" % (slug, int(frac * 100)),
               "zeroed_frames": [s0, off + length]}
        row.update(_summarize(j))
        gaps.append(row)
        emit(lines, "    %-42s verdict %-4s | max %.0f LSB rms %.2f dBFS corr "
                    "%.4f | tail residual %.2f dB gate %s%s"
             % (row["probe"], row["status"], row["max_abs_diff_lsb"],
                row["rms_diff_dbfs"], row["spectral_corr"],
                row["tail_rms_rel_db"],
                "PASS" if row["tail_gate_ok"] else "FAIL",
                "   <-- KNOWN-GAP (#111): dropped late tail PASSES"
                if row["status"] == "PASS" else ""))
    emit(lines)

    # ---- refusals (chorus comparator; fmcombo notes) -----------------------
    slug, seq = "fmcombo", "seq-notes-coverage-v1"
    sc_path = os.path.join(SXT028C, "fixtures", "%s__%s.json" % (slug, seq))
    sc = json.load(open(sc_path))
    d = os.path.join(scratch, "leg2", "refusals")
    os.makedirs(d, exist_ok=True)
    variants = {"missing-sidecar": None}
    v = copy.deepcopy(sc)
    del v["render"]["tail_s"]
    variants["undeclared-tail_s"] = v
    v = copy.deepcopy(sc)
    v["render"]["frames"] = sc["render"]["frames"] - 60000
    variants["stale-frames"] = v
    v = copy.deepcopy(sc)
    v["wet"]["sha256"] = "0" * 64
    variants["sha256-mismatch"] = v
    for name, content in variants.items():
        p = os.path.join(d, "%s.json" % name)
        if content is not None:
            with open(p, "w") as f:
                json.dump(content, f, indent=2)
        out = os.path.join(d, "%s.out.json" % name)
        r = run([CHORUS, "--slug", slug, "--seq", seq, "--sidecar", p,
                 "--json", out])
        j = json.load(open(out)) if os.path.exists(out) else {}
        expect("refusal/%s" % name, "chorus", r, j, "NO_VERDICT")
    r = run([FX, "--ref", os.path.join(REPO, "reports", "sxt-023", "fixtures",
                                       "fm_bass_1__seq-notes-coverage-v1-wet"
                                       ".f32.wav"),
             "--model", os.path.join(REPO, "reports", "sxt-023", "artifacts",
                                     "model__fm_bass_1__seq-notes-coverage-v1"
                                     ".f32.wav"),
             "--sidecar", os.path.join(d, "missing-sidecar.json"),
             "--json", os.path.join(d, "fx-missing.out.json")])
    j = json.load(open(os.path.join(d, "fx-missing.out.json")))
    expect("refusal/missing-sidecar", "fx", r, j, "NO_VERDICT")
    emit(lines)

    # ---- fx comparator on the sxt-023 EQ case (its one PASS case) ----------
    ref = os.path.join(REPO, "reports", "sxt-023", "fixtures",
                       "fm_bass_1__seq-notes-coverage-v1-wet.f32.wav")
    model_path = os.path.join(REPO, "reports", "sxt-023", "artifacts",
                              "model__fm_bass_1__seq-notes-coverage-v1.f32.wav")
    region = car.declared_tail_region(car.discover_sidecar(ref), "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    emit(lines, "  fixture sxt-023 fm_bass_1 (fx comparator): declared tail "
                "region [%d, %d)" % (off, off + length))
    d = os.path.join(scratch, "leg2", "fm_bass_1")
    os.makedirs(d, exist_ok=True)
    base = read_f32(model_path)
    renders = {"baseline": model_path}
    for name, arr in _mutations(base, off, length).items():
        p = os.path.join(d, "%s.f32.wav" % name)
        write_f32(p, arr)
        renders[name] = p
    for name, p in renders.items():
        out = os.path.join(d, "%s.json" % name)
        r = run([FX, "--ref", ref, "--model", p, "--json", out])
        j = json.load(open(out)) if os.path.exists(out) else {}
        expect("fm_bass_1/%s" % name, "fx", r, j,
               "PASS" if name == "baseline" else "FAIL")
    emit(lines)
    n_ok = sum(1 for r in rows if r["result"] == "CONTROL-OK")
    emit(lines, "  result: %d/%d controls behaved as required" % (n_ok,
                                                                  len(rows)))
    load_bearing = [r["control"] for r in rows
                    if r["required"] == "FAIL" and r["observed"] == "FAIL"
                    and r.get("budgets") and all(r["budgets"].values())]
    emit(lines, "  gate is load-bearing (all three budgets PASS, verdict FAILs "
                "on the tail gate alone): %s" % ", ".join(load_bearing))
    old_pass = [r["control"] for r in rows
                if r.get("pre100_tool_status") == "PASS"]
    emit(lines, "  controls the PRE-#100 chorus gate let through as PASS: %s"
         % (", ".join(old_pass) or "none"))
    gap_pass = [g["probe"] for g in gaps if g["status"] == "PASS"]
    emit(lines, "  KNOWN-GAP probes whose dropped late tail PASSES the full "
                "verdict: %s" % (", ".join(gap_pass) or "none"))
    return ok, {"status": "PASS" if ok else "FAIL", "controls": rows,
                "load_bearing_controls": load_bearing,
                "passed_by_pre100_tool": old_pass,
                "known_gap_probes": gaps,
                "known_gap_probes_passing": gap_pass}


# ---------------------------------------------------------------- leg 3 --

def leg3(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[3] rms_diff_dbfs under exact agreement (decision: clamp to "
                "RMS_DIFF_DBFS_FLOOR = %.1f)" % car.RMS_DIFF_DBFS_FLOOR)
    emit(lines, "=" * 74)
    d = os.path.join(scratch, "leg3")
    os.makedirs(d, exist_ok=True)
    ok = True
    rows = []
    koala = os.path.join(REPO, "fixtures", "audio", "koala2",
                         "seq-notes-coverage-v1-wet.wav")
    fmb = os.path.join(REPO, "reports", "sxt-023", "fixtures",
                       "fm_bass_1__seq-notes-coverage-v1-wet.f32.wav")
    fmc = os.path.join(SXT028C, "fixtures",
                       "fmcombo__seq-notes-coverage-v1-wet.f32.wav")
    cases = [
        ("shared-mono", [SHARED, "--path", "wet", "--ref", koala, "--model",
                         koala], lambda j: j["rms_diff_dbfs"]),
        ("chorus", [CHORUS, "--slug", "fmcombo", "--seq",
                    "seq-notes-coverage-v1", "--model", fmc],
         lambda j: j["channels"]["mono"]["rms_diff_dbfs"]),
        ("fx", [FX, "--ref", fmb, "--model", fmb],
         lambda j: j["channels"]["mono"]["rms_diff_dbfs"]),
    ]
    for name, cmd, get in cases:
        out = os.path.join(d, name + ".json")
        r = run(cmd + ["--json", out])
        raw = open(out).read() if os.path.exists(out) else ""
        try:
            j = strict_loads(raw)
            strict = True
        except ValueError:
            j = json.loads(raw) if raw else {}
            strict = False
        val = get(j) if j else None
        good = strict and val == car.RMS_DIFF_DBFS_FLOOR and r.returncode == 0
        ok &= good
        rows.append({"emitter": name, "rms_diff_dbfs": val,
                     "strict_json": strict, "verdict": j.get("verdict"),
                     "ok": good})
        emit(lines, "  %-12s exact-agreement rms_diff_dbfs=%r strict-JSON=%s "
                    "verdict=%s -> %s"
             % (name, val, strict, status_of(j.get("verdict")),
                "OK" if good else "BROKEN"))
    bad = []
    n = 0
    for p in sorted(glob.glob(os.path.join(REPO, "reports", "**", "*.json"),
                              recursive=True)):
        n += 1
        try:
            strict_loads(open(p).read())
        except ValueError as e:
            bad.append((os.path.relpath(p, REPO), str(e)[:80]))
    ok &= not bad
    emit(lines, "  committed reports/**/*.json strict-parsed: %d files, %d "
                "rejected%s" % (n, len(bad), "" if not bad else ": %s" % bad))
    return ok, {"status": "PASS" if ok else "FAIL",
                "floor": car.RMS_DIFF_DBFS_FLOOR, "emitters": rows,
                "committed_json_files": n, "strict_rejects": bad}


# ---------------------------------------------------------------- leg 4 --

def pattern(n, seed=0):
    """Deterministic white-ish ternary sequence in {-1, 0, +1} (splitmix64
    hash of the index; no RNG state, reproducible across numpy versions)."""
    x = (np.arange(n, dtype=np.uint64) + np.uint64(seed)) \
        * np.uint64(0x9E3779B97F4A7C15)
    x ^= x >> np.uint64(30)
    x *= np.uint64(0xBF58476D1CE4E5B9)
    x ^= x >> np.uint64(27)
    x *= np.uint64(0x94D049BB133111EB)
    x ^= x >> np.uint64(31)
    return (x % np.uint64(3)).astype(np.int64) - 1


def _frames(x, frame=4096):
    n = len(x) // frame * frame
    return x[:n].reshape(-1, frame)


def corr_variant(a, b, full_scale, mode, frame=4096, floor_db=-100.0,
                 gate_db=-80.0):
    """Candidate treatments (NOT adopted; evaluated for the recommendation).

    fs-floor : log(max(|X| / (FS * sum(win)/2), 10^(floor_db/20))) -- the log
               knee is declared in full-scale units, identical for int16 and
               float buses (current metric: knee at |X| = 1 native unit).
    gated    : current log1p metric, but only frames whose REFERENCE frame RMS
               is >= gate_db dBFS contribute.
    """
    n = min(len(a), len(b))
    fa, fb = _frames(a[:n], frame), _frames(b[:n], frame)
    win = np.hanning(frame)
    if mode == "gated":
        rms = np.sqrt((fa * fa).mean(axis=1))
        keep = rms >= full_scale * 10 ** (gate_db / 20.0)
        if not keep.any():
            return None
        fa, fb = fa[keep], fb[keep]
        ra = np.log1p(np.abs(np.fft.rfft(fa * win, axis=1))).ravel()
        rb = np.log1p(np.abs(np.fft.rfft(fb * win, axis=1))).ravel()
    else:
        ref_mag = full_scale * win.sum() / 2.0
        fl = 10 ** (floor_db / 20.0)
        ra = np.log(np.maximum(np.abs(np.fft.rfft(fa * win, axis=1)) / ref_mag,
                               fl)).ravel()
        rb = np.log(np.maximum(np.abs(np.fft.rfft(fb * win, axis=1)) / ref_mag,
                               fl)).ravel()
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    den = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / den) if den > 0 else 0.0


def leg4(lines, scratch):
    import compare_chorus_reference as cc
    emit(lines, "=" * 74)
    emit(lines, "[4] spectral_corr sensitivity sweep (characterization; metric "
                "NOT changed)")
    emit(lines, "=" * 74)
    emit(lines, "  perturbation: deterministic ternary {-1,0,+1} x k native LSB"
                " (splitmix64 of the index);")
    emit(lines, "  'quiet' = 4096-frames whose reference RMS < 1 native LSB; "
                "'loud' = all other frames.")
    emit(lines, "  columns: spectral_corr (budget >= 0.98) | rms_diff_dbfs "
                "(budget <= -46) | max_abs (LSB)")
    emit(lines, "           | candidate fs-floor(-100 dB) | candidate gated"
                "(ref frame >= -80 dBFS)")
    emit(lines)
    rows = []
    fixtures = [
        ("koala2 (int16 mono, shared metric)", "i16",
         os.path.join(REPO, "fixtures", "audio", "koala2",
                      "seq-notes-coverage-v1-wet.wav"),
         (1, 2, 4, 16, 64, 256)),
        ("behemoth (int16 mono, shared metric)", "i16",
         os.path.join(REPO, "fixtures", "audio", "behemoth",
                      "seq-notes-coverage-v1-wet.wav"),
         (1, 2, 4, 16, 64, 256)),
        ("fmcombo notes (stereo f32, mono sum, stereo-tool metric)", "f32",
         os.path.join(SXT028C, "fixtures",
                      "fmcombo__seq-notes-coverage-v1-wet.f32.wav"),
         (1, 16, 256, 1024, 4096, 16384, 65536)),
        ("alienappears notes (stereo f32, mono sum, stereo-tool metric)",
         "f32", os.path.join(SXT028C, "fixtures",
                             "alienappears__seq-notes-coverage-v1-wet.f32.wav"),
         (1, 16, 256, 1024, 4096, 16384, 65536)),
    ]
    for label, kind, path, ks in fixtures:
        if kind == "i16":
            ref, _ = car.read_wav(path)
            fs, unit, corr = 32767.0, 1.0, car.spectral_corr
        else:
            st = read_f32(path).astype(np.float64)
            ref = 0.5 * (st[0] + st[1])
            fs, unit, corr = 1.0, LSB, cc.spectral_corr
        fr = _frames(ref)
        rms = np.sqrt((fr * fr).mean(axis=1))
        quiet_f = rms < unit
        nq = int(quiet_f.sum())
        quiet = np.zeros(len(ref), dtype=bool)
        quiet[:len(quiet_f) * 4096] = np.repeat(quiet_f, 4096)
        emit(lines, "  %s: %s" % (label, os.path.relpath(path, REPO)))
        emit(lines, "    %d frames of 4096, %d quiet (< 1 LSB RMS)"
             % (len(rms), nq))
        base_ff = corr_variant(ref, ref, fs, "fs-floor")
        pat = pattern(len(ref)).astype(np.float64)
        for where in ("everywhere", "quiet-only", "loud-only"):
            if where == "quiet-only" and nq == 0:
                emit(lines, "    quiet-only: NOT_RUN (fixture has no quiet "
                            "frames)")
                continue
            for k in ks:
                p = pat * k * unit
                if where == "quiet-only":
                    p = np.where(quiet, p, 0.0)
                elif where == "loud-only":
                    p = np.where(quiet, 0.0, p)
                mod = ref + p
                d = mod - ref
                r = float(np.sqrt((d * d).mean()))
                row = {
                    "fixture": os.path.relpath(path, REPO), "where": where,
                    "k_lsb": k,
                    "spectral_corr": corr(ref, mod),
                    "rms_diff_dbfs": car.rms_dbfs(r, fs),
                    "max_abs_diff_lsb": float(np.abs(d).max() / unit),
                    "cand_fs_floor": corr_variant(ref, mod, fs, "fs-floor"),
                    "cand_gated": corr_variant(ref, mod, fs, "gated"),
                }
                rows.append(row)
                emit(lines, "    %-10s k=%-6d corr %.4f %s | rms %8.2f dBFS | "
                            "max %8.0f | fs-floor %.4f | gated %s"
                     % (where, k, row["spectral_corr"],
                        "MISS" if row["spectral_corr"] < 0.98 else "    ",
                        row["rms_diff_dbfs"], row["max_abs_diff_lsb"],
                        row["cand_fs_floor"],
                        "n/a" if row["cand_gated"] is None
                        else "%.4f" % row["cand_gated"]))
        emit(lines, "    (fs-floor self-correlation %.4f)" % base_ff)
        emit(lines)

    # the committed verdicts spectral_corr alone decides today
    emit(lines, "  committed verdicts decided by spectral_corr ALONE (max and "
                "rms budgets pass):")
    live = []
    for slug in ("badnews", "popcorn2k"):
        for seq in ("seq-notes-coverage-v1", "seq-notes-repeated-v1"):
            art = os.path.join(REPO, "reports", "SXT-040", "artifacts")
            refp = os.path.join(art, "%s__%s-ref.wav" % (slug, seq))
            modp = os.path.join(art, "model-%s-%s.wav" % (slug, seq))
            bj = os.path.join(art, "budget-%s-%s.json" % (slug, seq))
            if not (os.path.exists(refp) and os.path.exists(modp)):
                emit(lines, "    %s x %s: NOT_RUN (renders missing)"
                     % (slug, seq))
                continue
            ref, _ = car.read_wav(refp)
            mod, _ = car.read_wav(modp)
            committed = json.load(open(bj))
            n = min(len(ref), len(mod))
            ref, mod = ref[:n], mod[:n]
            row = {"case": "SXT-040 %s x %s" % (slug, seq),
                   "committed_spectral_corr": committed["spectral_corr"],
                   "recomputed_spectral_corr": car.spectral_corr(ref, mod),
                   "rms_diff_dbfs": committed["rms_diff_dbfs"],
                   "max_abs_diff_lsb": committed["max_abs_diff_lsb"],
                   "ref_peak_lsb": float(np.abs(ref).max()),
                   "cand_fs_floor": corr_variant(ref, mod, 32767.0,
                                                 "fs-floor"),
                   "cand_gated": corr_variant(ref, mod, 32767.0, "gated")}
            live.append(row)
            emit(lines, "    %-40s corr %.4f (recomputed %.4f) | rms %.2f "
                        "dBFS | max %.0f | peak %.0f | fs-floor %.4f | gated "
                        "%s"
                 % (row["case"], row["committed_spectral_corr"],
                    row["recomputed_spectral_corr"], row["rms_diff_dbfs"],
                    row["max_abs_diff_lsb"], row["ref_peak_lsb"],
                    row["cand_fs_floor"],
                    "n/a" if row["cand_gated"] is None
                    else "%.4f" % row["cand_gated"]))
    emit(lines)
    emit(lines, "  The candidate columns are diagnostics for the pilot-freeze "
                "decision only; no committed")
    emit(lines, "  verdict is re-graded by them, and no budget is changed. "
                "Pilot-freeze input: #110.")
    return True, {"status": "PASS", "note": "characterization only",
                  "sweep": rows, "spectral_only_verdicts": live}


# ---------------------------------------------------------------- leg 5 --

SXT023_PRESETS = ("dexie", "fm_bass_1", "metallic")
SXT024_CASES = ("click-wet", "preset-notes-coverage-wet",
                "hardreset-midpatch-wet")
REVERB = os.path.join(REPO, "tools", "compare_reverb_model.py")


def _pre100_reverb_tool(scratch, out_dir):
    """The pre-#100 reverb tool, materialized from PRE_CHANGE_REV with its
    REPO pinned to this checkout (it imports the frozen model from here) and
    its hard-coded output directory redirected to scratch, so the committed
    sxt-024 comparison JSONs are never overwritten by this leg."""
    src = git_show(PRE_CHANGE_REV, "tools/compare_reverb_model.py")
    if src is None:
        return None
    src = src.decode()
    a = 'REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))'
    b = 'os.path.join(REPO, "reports", "sxt-024", "comparison"'
    if a not in src or b not in src:
        return None
    src = src.replace(a, "REPO = %r" % REPO)
    src = src.replace(b, "os.path.join(%r" % out_dir)
    p = os.path.join(scratch, "pre100_compare_reverb_model.py")
    with open(p, "w") as f:
        f.write(src)
    return p


def leg5(lines, scratch):
    """Re-run the other two stereo comparators' committed cases (sxt-023 fx,
    sxt-024 reverb) and record the outcome. Their committed artifacts are NOT
    rewritten by #100; the gated re-runs are retained under
    artifacts/sxt023-rerun/ and artifacts/sxt024-rerun/."""
    emit(lines, "=" * 74)
    emit(lines, "[5] sxt-023 (compare_fx_reference.py) and sxt-024 "
                "(compare_reverb_model.py) re-run under the gate")
    emit(lines, "=" * 74)
    ok = True
    rep = {"sxt023": [], "sxt024": []}
    d = os.path.join(ART, "sxt023-rerun")
    os.makedirs(d, exist_ok=True)
    for p in SXT023_PRESETS:
        rel = "reports/sxt-023/artifacts/audio-%s.json" % p
        before = json.loads(git_show(PRE_CHANGE_REV, rel))
        out = os.path.join(d, "audio-%s.json" % p)
        r = run([FX, "--ref", "reports/sxt-023/fixtures/%s__seq-notes-"
                              "coverage-v1-wet.f32.wav" % p,
                 "--model", "reports/sxt-023/artifacts/model__%s__seq-notes-"
                            "coverage-v1.f32.wav" % p,
                 "--preset", p, "--json", out])
        after = strict_loads(open(out).read())
        diff = classify(before, after)
        flips = [x for x in diff if x[1] == "VERDICT-STATUS-CHANGE"]
        unexpl = [x for x in diff if x[1] == "UNEXPLAINED"]
        ok &= (r.returncode == 0 and not flips and not unexpl)
        tc, lr = after["tail_check"], after["tail_check_lr"]
        emit(lines, "  sxt-023 %-10s %s -> %s  (%s) | tail gate %s: mono %.2f "
                    "L %.2f R %.2f dB | ULP %d, unexplained %d"
             % (p, status_of(before["verdict"]), status_of(after["verdict"]),
                "unchanged" if not flips else "CHANGED -- STOP/ESCALATE",
                "PASS" if after["tail_gate_ok"] else "FAIL",
                tc["tail_rms_rel_db"], lr["L"]["tail_rms_rel_db"],
                lr["R"]["tail_rms_rel_db"],
                sum(1 for x in diff if x[1] == "ULP"), len(unexpl)))
        emit(lines, "      after: %s" % after["verdict"])
        rep["sxt023"].append({
            "case": p, "status_before": status_of(before["verdict"]),
            "status_after": status_of(after["verdict"]),
            "tail_gate_ok": after["tail_gate_ok"],
            "tail_rms_rel_db": {"mono": tc["tail_rms_rel_db"],
                                "L": lr["L"]["tail_rms_rel_db"],
                                "R": lr["R"]["tail_rms_rel_db"]},
            "verdict_status_changed": bool(flips),
            "unexplained": len(unexpl)})
    emit(lines)

    # sxt-024: gated tool vs pre-#100 tool, both on THIS host, in parallel
    d = os.path.join(ART, "sxt024-rerun")
    os.makedirs(d, exist_ok=True)
    pre_dir = os.path.join(scratch, "leg5-pre100")
    os.makedirs(pre_dir, exist_ok=True)
    pre_tool = _pre100_reverb_tool(scratch, pre_dir)
    if pre_tool is None:
        emit(lines, "  sxt-024: NOT_RUN (pre-#100 reverb tool unavailable)")
        return False, dict(rep, status="NOT_RUN")
    procs = []
    for c in SXT024_CASES:
        procs.append((c, "gated", subprocess.Popen(
            [sys.executable, REVERB, "case", "--case", c, "--out-dir", d],
            cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)))
        procs.append((c, "pre100", subprocess.Popen(
            [sys.executable, pre_tool, "case", "--case", c],
            cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)))
    rcs = {}
    for c, kind, pr in procs:
        pr.wait()
        rcs[(c, kind)] = pr.returncode
    for c in SXT024_CASES:
        committed = json.loads(git_show(
            PRE_CHANGE_REV, "reports/sxt-024/comparison/%s.json" % c))
        pre = json.load(open(os.path.join(pre_dir, "%s.json" % c)))
        gated = strict_loads(open(os.path.join(d, "%s.json" % c)).read())
        g = gated["tail_gate"]
        gated_wo = {k: v for k, v in gated.items() if k != "tail_gate"}
        gated_wo["checks"] = {k: v for k, v in gated["checks"].items()
                              if k != "tail_gate"}
        # (a) the gate adds ONLY tail_gate: gated minus the gate == pre-#100
        #     tool on the same host, byte-for-byte after key removal
        same_as_pre = (json.dumps(gated_wo, sort_keys=True)
                       == json.dumps(pre, sort_keys=True))
        # (b) pre-#100 tool on this host vs the committed record (pre-existing
        #     drift, independent of #100)
        drift = classify(committed, pre)
        drift_keys = [x[0] for x in drift
                      if x[1] not in ("ULP", "SCHEMA(added)")]
        added_keys = [x[0] for x in drift if x[1] == "SCHEMA(added)"]
        st_c = all(committed["checks"].values())
        st_g = all(gated["checks"].values())
        st_pre = all(pre["checks"].values())
        flips = st_c != st_g
        ok &= (same_as_pre and not flips)
        emit(lines, "  sxt-024 %-28s committed %s | pre-#100 tool here %s | "
                    "gated %s (%s)"
             % (c, "PASS" if st_c else "FAIL", "PASS" if st_pre else "FAIL",
                "PASS" if st_g else "FAIL",
                "unchanged" if not flips else "CHANGED -- STOP/ESCALATE"))
        emit(lines, "      failing checks (gated): %s"
             % (", ".join(k for k, v in gated["checks"].items() if not v)
                or "none"))
        emit(lines, "      tail gate %s over declared [%d, %d): mono %.2f  L "
                    "%.2f  R %.2f dB (budget %.1f)"
             % ("PASS" if g["ok"] else "FAIL",
                g["tail_check"]["tail_offset"],
                g["tail_check"]["tail_offset"] + g["tail_check"]["tail_frames"],
                g["tail_check"]["tail_rms_rel_db"],
                g["tail_check_lr"]["L"]["tail_rms_rel_db"],
                g["tail_check_lr"]["R"]["tail_rms_rel_db"],
                car.PROPOSED_TAIL["tail_rms_rel_db"]))
        emit(lines, "      gated output minus tail_gate == pre-#100 tool output "
                    "(same host): %s" % same_as_pre)
        emit(lines, "      pre-existing drift, committed record vs pre-#100 "
                    "tool on this host (NOT caused by #100): %d value keys %s; "
                    "%d fields the tool gained after the record was committed "
                    "%s" % (len(drift_keys), drift_keys, len(added_keys),
                            added_keys))
        rep["sxt024"].append({
            "case": c, "committed_pass": st_c, "pre100_here_pass": st_pre,
            "gated_pass": st_g, "tail_gate_ok": g["ok"],
            "tail_rms_rel_db": {"mono": g["tail_check"]["tail_rms_rel_db"],
                                "L": g["tail_check_lr"]["L"]["tail_rms_rel_db"],
                                "R": g["tail_check_lr"]["R"]["tail_rms_rel_db"]},
            "gate_only_addition": same_as_pre,
            "preexisting_drift_keys": drift_keys,
            "preexisting_missing_fields": added_keys,
            "exit": {"gated": rcs[(c, "gated")], "pre100": rcs[(c, "pre100")]}})
    rep["status"] = "PASS" if ok else "FAIL"
    return ok, rep


# ----------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt-stereo-tail-gate")
    ap.add_argument("--legs", default="1,2,3,4,5")
    ap.add_argument("--write-artifacts", action="store_true",
                    help="leg 1: regenerate the six committed SXT-028c "
                         "comparison artifacts (only if the leg passes)")
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
    summary = {"issue": 100, "run_utc": stamp, "repo_head": head,
               "numpy": np.__version__, "legs": {}}
    names = {1: ("sxt028c_rerun", "sxt028c-rerun.txt", leg1),
             2: ("stereo_tail_controls", "negative-controls.txt", leg2),
             3: ("rms_diff_dbfs_floor", "rms-floor.txt", leg3),
             4: ("spectral_corr_sweep", "spectral-corr-sweep.txt", leg4),
             5: ("other_stereo_comparators_rerun", "sxt023-sxt024-rerun.txt",
                 leg5)}
    ok = True
    for leg in (1, 2, 3, 4, 5):
        key, fname, fn = names[leg]
        if leg not in legs:
            summary["legs"][key] = {"status": "NOT_RUN",
                                    "reason": "leg not selected"}
            continue
        lines = ["issue #100 -- stereo comparator tail gate / metric "
                 "findings: leg %d" % leg,
                 "run: %s   repo HEAD: %s   numpy %s" % (stamp, head,
                                                        np.__version__),
                 "claim scope: comparator behaviour only; no fidelity, "
                 "support, or sound claim.", ""]
        if leg == 1:
            good, rep = fn(lines, scratch, args.write_artifacts)
        else:
            good, rep = fn(lines, scratch)
        ok &= good
        summary["legs"][key] = rep
        lines.append("")
        lines.append("leg %d verdict: %s" % (leg, rep["status"]))
        with open(os.path.join(ART, fname), "w") as f:
            f.write("\n".join(lines) + "\n")
        if leg == 4:
            with open(os.path.join(ART, "spectral-corr-sweep.json"), "w") as f:
                json.dump(rep, f, indent=2)
                f.write("\n")
    summary["overall"] = "PASS" if ok else "FAIL"
    slim = {k: {kk: vv for kk, vv in v.items()
                if kk not in ("sweep",)} for k, v in summary["legs"].items()}
    summary["legs"] = slim
    with open(os.path.join(ART, "checks-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    print("OVERALL: %s" % summary["overall"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
