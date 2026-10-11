#!/usr/bin/env python3
"""Static Verilator lint gate with exhaustive RTL classification (#434).

Stages, in order; the first failing stage decides the status:

  1. inventory  -- every tracked ``rtl/**/*.sv`` is classified exactly once in
                   ``rtl/lint_manifest.json`` (product / sim_model / testbench /
                   mutant_control); no duplicate, stale or unclassified entry;
                   every product file is exactly one explicit lint group.
  2. waivers    -- ``rtl/lint_waivers.json`` is well formed (no wildcard or
                   file-wide waiver, no duplicate, severe rules carry a review
                   decision).
  3. tool       -- the Verilator executable reports the pinned version.  A
                   missing or different tool is NOT_RUN with zero groups run.
  4. run        -- one ``verilator --lint-only ...`` per group, argv array, run
                   from the repository root.  Any error / nonzero exit /
                   unparsable diagnostic fails; errors are never waivable.
  5. compare    -- the full diagnostic multiset equals the reviewed baseline.
                   New, increased, decreased, disappeared entries and source
                   hash drift all fail.

Statuses: PASS (exit 0), FAIL (exit 1), NOT_RUN (exit 2).  Classification
coverage and diagnostic agreement are reported as two separate verdicts.

There is deliberately NO operation that rewrites the waiver baseline.

DOES NOT establish: synthesis / FPGA / gf180mcu qualification, RTL-vs-frozen-
model exactness, model-vs-Surge agreement, or preset quality.  A ``product``
classification only names a candidate module.  Default parameters only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PINNED_VERSION = "5.050"
PINNED_VERSION_PREFIX = "Verilator 5.050 2026-07-01"
# Provenance of the pinned tool (recorded for the CI provisioning step and
# reports/rtl-lint/EVIDENCE.md; the checker itself only enforces the version).
PIN_SOURCE_REPO = "https://github.com/verilator/verilator"
PIN_SOURCE_TAG = "v5.050"
PIN_SOURCE_COMMIT = "848d926ebd4addacacd294dc84e35d9d4ae8078c"
PIN_ARCHIVE_SHA256 = (
    "ec6723f30c1798b1fbbbed97364f09c431fb4875577c314f37240e99b60a4a04")

CLASSES = ("product", "sim_model", "testbench", "mutant_control")
SEVERE_RULES = ("LATCH", "UNDRIVEN", "MULTIDRIVEN", "CASEINCOMPLETE")
REVIEW_STATUSES = ("proposed_pending_pr_review", "approved")

VERILATOR_ARGS = ["--lint-only", "--language", "1800-2017", "-Wall",
                  "-Wno-fatal"]

CLAIM_LIMITS = (
    "Static lint only. Establishes none of: synthesis, FPGA or gf180mcu "
    "qualification; RTL-vs-frozen-model exactness; model-vs-Surge agreement; "
    "preset quality. A 'product' classification names a candidate module, "
    "not a synthesizable or qualified one. Default parameters only. A waiver "
    "records tolerated existing debt, not a correctness finding.")

EXIT = {"PASS": 0, "FAIL": 1, "NOT_RUN": 2}

_DIAG_RE = re.compile(r"^%(Warning|Error)(?:-([A-Z0-9_]+))?: (.*)$")
_LOC_RE = re.compile(r"^(.+?):(\d+):(\d+): (.*)$")
_FP_RE = re.compile(r"^[0-9a-f]{16}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class Refusal(Exception):
    """A stage failure: ``stage`` names where, ``reasons`` says why."""

    def __init__(self, stage, reasons, status="FAIL"):
        super().__init__("%s: %s" % (stage, "; ".join(reasons)))
        self.stage = stage
        self.reasons = list(reasons)
        self.status = status


# --------------------------------------------------------------------------
# helpers


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise Refusal(what, ["cannot read/parse %s: %s" % (path, exc)])
    if not isinstance(doc, dict):
        raise Refusal(what, ["%s: top level must be an object" % path])
    return doc


def tracked_sv(root):
    """Tracked rtl/**/*.sv from git (exact bytes of the path, NUL separated)."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--", "rtl"],
            check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refusal("inventory",
                      ["cannot list tracked files via git: %s" % exc])
    paths = [p.decode("utf-8") for p in out.split(b"\0") if p]
    return sorted(p for p in paths if p.endswith(".sv"))


def fingerprint(rule, source, line, col, message):
    blob = "\x1f".join([rule, source, str(line), str(col), message])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# stage 1: inventory


def validate_manifest(manifest, tracked):
    """Return (groups, coverage dict). Raises Refusal('inventory')."""
    errs = []
    if manifest.get("schema") != 1:
        errs.append("manifest schema must be 1")
    files = manifest.get("files")
    groups = manifest.get("groups")
    if not isinstance(files, list) or not isinstance(groups, list):
        raise Refusal("inventory", errs + ["manifest needs 'files' and "
                                           "'groups' lists"])
    cls_of = {}
    for i, ent in enumerate(files):
        if (not isinstance(ent, dict) or set(ent) != {"path", "class"}
                or not isinstance(ent["path"], str)):
            errs.append("files[%d]: malformed entry" % i)
            continue
        if ent["class"] not in CLASSES:
            errs.append("files[%d] %s: unknown class %r"
                        % (i, ent["path"], ent["class"]))
            continue
        if ent["path"] in cls_of:
            errs.append("duplicate manifest entry: %s" % ent["path"])
            continue
        cls_of[ent["path"]] = ent["class"]
    tracked_set = set(tracked)
    unclassified = sorted(tracked_set - set(cls_of))
    stale = sorted(set(cls_of) - tracked_set)
    for p in unclassified:
        errs.append("unclassified tracked file: %s" % p)
    for p in stale:
        errs.append("stale manifest entry (not tracked): %s" % p)

    seen_src = {}
    group_ids = set()
    for i, g in enumerate(groups):
        need = {"id", "source", "top", "dependencies", "include_dirs",
                "defines", "parameter_overrides"}
        if not isinstance(g, dict) or set(g) != need:
            errs.append("groups[%d]: malformed (keys must be %s)"
                        % (i, sorted(need)))
            continue
        for k in ("dependencies", "include_dirs", "defines",
                  "parameter_overrides"):
            if g[k] != []:
                errs.append("group %s: %s must be empty" % (g["id"], k))
        if not isinstance(g["id"], str) or g["id"] in group_ids:
            errs.append("groups[%d]: duplicate/invalid id %r" % (i, g["id"]))
        group_ids.add(g["id"])
        if g["source"] in seen_src:
            errs.append("source in two groups: %s" % g["source"])
        seen_src[g["source"]] = g["id"]
        if cls_of.get(g["source"]) != "product":
            errs.append("group %s source %s is not classified product"
                        % (g["id"], g["source"]))
    for p, c in sorted(cls_of.items()):
        if c == "product" and p not in seen_src:
            errs.append("product file in no lint group: %s" % p)
    if errs:
        raise Refusal("inventory", errs)
    return groups, cls_of


# --------------------------------------------------------------------------
# stage 2: waivers

_ENTRY_KEYS = {"group", "top", "source", "rule", "fingerprint", "line", "col",
               "message", "count", "source_sha256", "explanation",
               "baseline_commit", "verilator_version"}


def validate_waivers(doc, groups):
    errs = []
    if doc.get("schema") != 1:
        errs.append("waivers schema must be 1")
    if doc.get("verilator_version") != PINNED_VERSION:
        errs.append("waivers verilator_version %r != pinned %r"
                    % (doc.get("verilator_version"), PINNED_VERSION))
    if not _COMMIT_RE.match(str(doc.get("baseline_commit", ""))):
        errs.append("waivers baseline_commit must be a 40-hex commit")
    ents = doc.get("waivers")
    if not isinstance(ents, list):
        raise Refusal("waivers", errs + ["'waivers' must be a list"])
    by_id = {g["id"]: g for g in groups}
    seen = set()
    out = {}
    for i, e in enumerate(ents):
        tag = "waivers[%d]" % i
        if not isinstance(e, dict):
            errs.append("%s: not an object" % tag)
            continue
        extra = set(e) - _ENTRY_KEYS - {"review_decision"}
        missing = _ENTRY_KEYS - set(e)
        if extra or missing:
            errs.append("%s: bad keys (extra %s, missing %s)"
                        % (tag, sorted(extra), sorted(missing)))
            continue
        g = by_id.get(e["group"])
        if g is None:
            errs.append("%s: unknown group %r" % (tag, e["group"]))
            continue
        if e["top"] != g["top"]:
            errs.append("%s: top %r != group top" % (tag, e["top"]))
        for k in ("source", "rule", "fingerprint", "group", "top"):
            if not isinstance(e[k], str) or re.search(r"[*?\[\]]", e[k]) \
                    or not e[k]:
                errs.append("%s: wildcard/empty %s" % (tag, k))
        if e["source"] != g["source"]:
            errs.append("%s: file-wide/other-file waiver source %r "
                        "(group source is %s)" % (tag, e["source"],
                                                  g["source"]))
        if not re.match(r"^[A-Z][A-Z0-9_]*$", str(e["rule"])):
            errs.append("%s: bad rule %r" % (tag, e["rule"]))
        if not _FP_RE.match(str(e["fingerprint"])):
            errs.append("%s: fingerprint must be 16 lowercase hex" % tag)
        elif fingerprint(e["rule"], e["source"], e["line"], e["col"],
                         e["message"]) != e["fingerprint"]:
            errs.append("%s: fingerprint does not match rule/location/"
                        "message" % tag)
        for k in ("line", "col", "count"):
            if (not isinstance(e[k], int) or isinstance(e[k], bool)
                    or e[k] < (0 if k == "col" else 1)):
                errs.append("%s: %s must be a positive integer" % (tag, k))
        if not _SHA_RE.match(str(e["source_sha256"])):
            errs.append("%s: bad source_sha256" % tag)
        if not isinstance(e["explanation"], str) or len(
                e["explanation"].strip()) < 20:
            errs.append("%s: explanation missing/too short" % tag)
        if e["baseline_commit"] != doc.get("baseline_commit"):
            errs.append("%s: baseline_commit differs from file" % tag)
        if e["verilator_version"] != PINNED_VERSION:
            errs.append("%s: verilator_version != pin" % tag)
        if e["rule"] in SEVERE_RULES:
            rd = e.get("review_decision")
            if (not isinstance(rd, dict)
                    or set(rd) != {"status", "reviewer", "reference"}
                    or rd["status"] not in REVIEW_STATUSES
                    or not all(isinstance(rd[k], str) and rd[k].strip()
                               for k in ("reviewer", "reference"))):
                errs.append("%s: severe rule %s needs review_decision "
                            "{status, reviewer, reference}"
                            % (tag, e["rule"]))
        elif "review_decision" in e:
            errs.append("%s: review_decision only valid on severe rules" % tag)
        key = (e["group"], e["fingerprint"])
        if key in seen:
            errs.append("%s: duplicate waiver %s" % (tag, key))
        seen.add(key)
        out[key] = e
    if errs:
        raise Refusal("waivers", errs)
    return out


# --------------------------------------------------------------------------
# stage 3: tool


def probe_tool(verilator):
    """Return (path, version_string). Raises Refusal(status=NOT_RUN)."""
    path = shutil.which(verilator) if os.sep not in verilator else (
        verilator if os.access(verilator, os.X_OK) else None)
    if not path:
        raise Refusal("tool", ["verilator executable not found: %s"
                               % verilator], status="NOT_RUN")
    try:
        res = subprocess.run([path, "--version"], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal("tool", ["cannot execute %s --version: %s"
                               % (path, exc)], status="NOT_RUN")
    ver = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
    if res.returncode != 0 or not ver.startswith(PINNED_VERSION_PREFIX):
        raise Refusal("tool", ["wrong verilator version: %r (pinned prefix "
                               "%r)" % (ver, PINNED_VERSION_PREFIX)],
                      status="NOT_RUN")
    return path, ver


# --------------------------------------------------------------------------
# stage 4: run


def parse_diagnostics(text, source):
    """Return (diags, errors).  diags: list of dict(rule,file,line,col,msg)."""
    diags, errors = [], []
    for ln in text.splitlines():
        if not ln.startswith("%"):
            continue
        m = _DIAG_RE.match(ln)
        if not m:
            errors.append("unparsable diagnostic line: %s" % ln)
            continue
        kind, rule, rest = m.groups()
        if kind == "Error":
            errors.append("verilator error: %s" % ln)
            continue
        if not rule:
            errors.append("warning without rule id: %s" % ln)
            continue
        loc = _LOC_RE.match(rest)
        if not loc:
            errors.append("warning without file:line:col: %s" % ln)
            continue
        f, line, col, msg = loc.groups()
        diags.append({"rule": rule, "file": f, "line": int(line),
                      "col": int(col), "message": msg})
    return diags, errors


def group_argv(verilator, g):
    return [verilator] + VERILATOR_ARGS + ["--top-module", g["top"],
                                           g["source"]]


def run_group(verilator, g, root, raw_dir=None):
    argv = group_argv(verilator, g)
    res = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                         timeout=900)
    text = res.stdout + res.stderr
    if raw_dir:
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, g["id"] + ".txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)
    diags, errors = parse_diagnostics(text, g["source"])
    if res.returncode != 0:
        errors.append("verilator exit status %d" % res.returncode)
    counts = {}
    for d in diags:
        fp = fingerprint(d["rule"], d["file"], d["line"], d["col"],
                         d["message"])
        ent = counts.setdefault(fp, dict(d, fingerprint=fp, count=0))
        ent["count"] += 1
    return {
        "id": g["id"], "top": g["top"], "source": g["source"],
        "argv": argv, "cwd": root, "exit_status": res.returncode,
        "source_sha256": sha256_file(os.path.join(root, g["source"])),
        "errors": errors, "diagnostic_total": len(diags),
        "diagnostics": sorted(counts.values(),
                              key=lambda d: (d["line"], d["col"],
                                             d["rule"], d["fingerprint"])),
    }


# --------------------------------------------------------------------------
# stage 5: compare


def compare(observed_groups, waivers):
    """Return (failures, stats).  Full multiset comparison."""
    fails = []
    obs = {}
    for og in observed_groups:
        for d in og["diagnostics"]:
            obs[(og["id"], d["fingerprint"])] = (og, d)
    live_hash = {og["id"]: og["source_sha256"] for og in observed_groups}
    for key, (og, d) in sorted(obs.items()):
        w = waivers.get(key)
        sev = " SEVERE" if d["rule"] in SEVERE_RULES else ""
        where = "%s %s:%d:%d %s" % (og["id"], d["file"], d["line"],
                                    d["col"], d["rule"])
        if w is None:
            fails.append("new%s diagnostic (no waiver): %s [%s] %s"
                         % (sev, where, d["fingerprint"], d["message"]))
        elif d["count"] > w["count"]:
            fails.append("count increased %d -> %d: %s [%s]"
                         % (w["count"], d["count"], where, d["fingerprint"]))
        elif d["count"] < w["count"]:
            fails.append("count decreased %d -> %d: %s [%s]"
                         % (w["count"], d["count"], where, d["fingerprint"]))
    for key, w in sorted(waivers.items()):
        if key not in obs:
            fails.append("stale waiver (diagnostic disappeared): %s %s:%d:%d "
                         "%s [%s]" % (w["group"], w["source"], w["line"],
                                      w["col"], w["rule"], w["fingerprint"]))
        if w["source_sha256"] != live_hash.get(w["group"]):
            fails.append("source hash drift for waiver %s [%s]"
                         % (w["group"], w["fingerprint"]))
    fails = sorted(set(fails))
    n_obs = sum(d["count"] for og in observed_groups
                for d in og["diagnostics"])
    stats = {"observed_diagnostics": n_obs,
             "observed_distinct": len(obs),
             "waived_distinct": len(waivers),
             "waived_total": sum(w["count"] for w in waivers.values()),
             "severe_waivers": sum(1 for w in waivers.values()
                                   if w["rule"] in SEVERE_RULES),
             "severe_waivers_pending_review": sum(
                 1 for w in waivers.values() if w["rule"] in SEVERE_RULES
                 and w["review_decision"]["status"] != "approved")}
    return fails, stats


# --------------------------------------------------------------------------
# driver


def new_report(root):
    return {
        "schema": 1, "check": "rtl-lint (#434)", "status": "NOT_RUN",
        "stage": None, "reasons": [], "cwd": root,
        "pinned_tool": {"version_prefix": PINNED_VERSION_PREFIX,
                        "source_repo": PIN_SOURCE_REPO,
                        "source_tag": PIN_SOURCE_TAG,
                        "source_commit": PIN_SOURCE_COMMIT,
                        "archive_sha256": PIN_ARCHIVE_SHA256},
        "tool": None,
        "classification_coverage": {"status": "NOT_RUN"},
        "diagnostic_agreement": {"status": "NOT_RUN"},
        "groups_executed": 0, "groups": [],
        "claim_limits": CLAIM_LIMITS,
    }


def run_check(root, manifest_path, waivers_path, verilator="verilator",
              raw_dir=None, observed_out=None):
    """Run all stages; return report dict.  Never raises for gate failures."""
    rep = new_report(root)
    try:
        manifest = load_json(manifest_path, "inventory")
        tracked = tracked_sv(root)
        try:
            groups, cls_of = validate_manifest(manifest, tracked)
        except Refusal:
            rep["classification_coverage"] = {
                "status": "FAIL", "tracked": len(tracked)}
            raise
        by_class = {c: sum(1 for v in cls_of.values() if v == c)
                    for c in CLASSES}
        rep["classification_coverage"] = {
            "status": "PASS", "tracked": len(tracked),
            "classified": len(cls_of), "by_class": by_class,
            "groups": len(groups)}
        waivers = validate_waivers(load_json(waivers_path, "waivers"), groups)
        path, ver = probe_tool(verilator)
        rep["tool"] = {"path": path, "version": ver,
                       "sha256": sha256_file(path)}
        for g in groups:
            if not os.path.isfile(os.path.join(root, g["source"])):
                raise Refusal("run", ["group source missing: %s"
                                      % g["source"]])
        observed, errs = [], []
        for g in groups:
            try:
                og = run_group(path, g, root, raw_dir)
            except (OSError, subprocess.SubprocessError) as exc:
                raise Refusal("run", ["tool execution error in %s: %s"
                                      % (g["id"], exc)])
            rep["groups_executed"] += 1
            observed.append(og)
            rep["groups"].append({k: og[k] for k in (
                "id", "top", "source", "argv", "cwd", "exit_status",
                "source_sha256", "diagnostic_total", "errors")})
            errs += ["%s: %s" % (g["id"], e) for e in og["errors"]]
        if observed_out:
            with open(observed_out, "w", encoding="utf-8") as fh:
                json.dump(observed, fh, indent=1)
        rep["observed"] = observed
        if errs:
            rep["diagnostic_agreement"] = {"status": "NOT_RUN",
                                           "reason": "elaboration errors"}
            raise Refusal("run", errs)
        fails, stats = compare(observed, waivers)
        rep["diagnostic_agreement"] = dict(
            stats, status="FAIL" if fails else "PASS", failures=fails)
        if fails:
            raise Refusal("compare", fails)
        rep["status"], rep["stage"] = "PASS", "compare"
    except Refusal as r:
        rep["status"], rep["stage"], rep["reasons"] = (r.status, r.stage,
                                                      r.reasons)
        if r.status == "NOT_RUN":
            rep["groups_executed"] = 0
    return rep


def public_report(rep):
    out = {k: v for k, v in rep.items() if k != "observed"}
    return out


def write_report(rep, path):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(public_report(rep), fh, indent=1)
            fh.write("\n")


def summarize(rep, stream):
    print("rtl-lint status: %s (stage: %s)" % (rep["status"], rep["stage"]),
          file=stream)
    cc, da = rep["classification_coverage"], rep["diagnostic_agreement"]
    print("  classification coverage: %s %s"
          % (cc["status"], {k: v for k, v in cc.items() if k != "status"}),
          file=stream)
    print("  diagnostic agreement:    %s %s"
          % (da["status"], {k: v for k, v in da.items()
                            if k not in ("status", "failures")}),
          file=stream)
    print("  groups executed: %d" % rep["groups_executed"], file=stream)
    if rep.get("tool"):
        print("  tool: %s" % rep["tool"]["version"], file=stream)
    for r in rep["reasons"]:
        print("  reason: %s" % r, file=stream)
    print("  " + CLAIM_LIMITS, file=stream)


# --------------------------------------------------------------------------
# negative controls (temporary copies only; production files never written)


_LATCH_INJECTION = (
    "\n  // injected by check_rtl_lint negative control (temp copy only)\n"
    "  logic nc_inj_en, nc_inj_q;\n"
    "  always_comb if (nc_inj_en) nc_inj_q = 1'b1;\n")


def _temp_repo(root, tmp):
    """Make a real git repo in tmp containing rtl/ (+ manifest/waivers)."""
    dst = os.path.join(tmp, "repo")
    shutil.copytree(os.path.join(root, "rtl"), os.path.join(dst, "rtl"))
    subprocess.run(["git", "init", "-q", dst], check=True)
    subprocess.run(["git", "-C", dst, "add", "-A"], check=True)
    return dst


def _expect(name, rep, status, stage, needle):
    ok = (rep["status"] == status and rep["stage"] == stage
          and any(needle in r for r in rep["reasons"]))
    if not ok:
        return False, ("CONTROL-BROKEN %s: wanted %s/%s containing %r, got "
                       "%s/%s %s" % (name, status, stage, needle,
                                     rep["status"], rep["stage"],
                                     rep["reasons"][:3]))
    return True, "CONTROL-OK %s: %s at stage %s (%r)" % (
        name, status, stage, needle)


def negative_controls(root, manifest_path, waivers_path, verilator):
    """Return (all_ok, lines).  Each control must FAIL its target stage."""
    lines, oks = [], []

    def record(res):
        oks.append(res[0])
        lines.append(res[1])

    with tempfile.TemporaryDirectory(prefix="rtl-lint-nc-") as tmp:
        waivers = load_json(waivers_path, "waivers")
        groups, _ = validate_manifest(load_json(manifest_path, "inventory"),
                                      tracked_sv(root))
        # 1. unclassified tracked RTL (inventory stage; no verilator needed)
        repo = _temp_repo(root, tmp)
        extra = os.path.join(repo, "rtl", "nc_unclassified.sv")
        with open(extra, "w") as fh:
            fh.write("module nc_unclassified; endmodule\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
        rep = run_check(repo, manifest_path, waivers_path, verilator)
        record(_expect("unclassified-tracked-rtl", rep, "FAIL", "inventory",
                       "unclassified tracked file: rtl/nc_unclassified.sv"))
        # 2. missing tool / wrong version (NOT_RUN, zero groups)
        rep = run_check(root, manifest_path, waivers_path,
                        os.path.join(tmp, "no-such-verilator"))
        good = _expect("missing-tool", rep, "NOT_RUN", "tool", "not found")
        if good[0] and rep["groups_executed"] != 0:
            good = (False, "CONTROL-BROKEN missing-tool: groups executed")
        record(good)
        fake = os.path.join(tmp, "verilator-fake")
        with open(fake, "w") as fh:
            fh.write("#!/bin/sh\necho 'Verilator 5.048 2026-01-01 rev x'\n")
        os.chmod(fake, 0o755)
        rep = run_check(root, manifest_path, waivers_path, fake)
        good = _expect("wrong-version-tool", rep, "NOT_RUN", "tool",
                       "wrong verilator version")
        if good[0] and rep["groups_executed"] != 0:
            good = (False, "CONTROL-BROKEN wrong-version: groups executed")
        record(good)
        # 3. baseline run (real verilator), reused for the waiver mutations
        raw = os.path.join(tmp, "raw")
        base = run_check(root, manifest_path, waivers_path, verilator, raw)
        if base["status"] != "PASS":
            lines.append("CONTROL-BROKEN baseline did not PASS (%s/%s); the "
                         "waiver controls would be meaningless"
                         % (base["status"], base["stage"]))
            return False, lines
        lines.append("CONTROL-OK baseline: PASS (%d groups)"
                     % base["groups_executed"])
        oks.append(True)
        observed = base["observed"]

        def mutate(name, fn, needle):
            doc = json.loads(json.dumps(waivers))
            fn(doc["waivers"])
            wp = os.path.join(tmp, name + ".json")
            with open(wp, "w") as fh:
                json.dump(doc, fh)
            w = validate_waivers(load_json(wp, "waivers"), groups)
            fails, _ = compare(observed, w)
            hit = [f for f in fails if needle in f]
            ok = bool(hit)
            oks.append(ok)
            lines.append(("CONTROL-OK %s: FAIL at stage compare (%s)"
                          % (name, hit[0][:110])) if ok else
                         "CONTROL-BROKEN %s: no %r failure" % (name, needle))

        def drop_first_nonsevere(ws):
            for i, e in enumerate(ws):
                if e["rule"] not in SEVERE_RULES:
                    del ws[i]
                    return

        def bump(ws):
            ws[0]["count"] += 1

        def stale(ws):
            e = json.loads(json.dumps(ws[0]))
            e["line"] += 100000
            e["fingerprint"] = fingerprint(e["rule"], e["source"], e["line"],
                                           e["col"], e["message"])
            ws.append(e)

        def drop_latch(ws):
            for i, e in enumerate(ws):
                if e["rule"] == "LATCH":
                    del ws[i]
                    return
            raise AssertionError("no LATCH waiver")

        mutate("new-warning (waiver removed)", drop_first_nonsevere,
               "new diagnostic (no waiver)")
        mutate("new-severe-latch (waiver removed)", drop_latch,
               "new SEVERE diagnostic")
        mutate("count-decreased (waiver count raised above observed)",
               bump, "count decreased")
        # count-increased: every baseline count is 1, so the waiver cannot be
        # lowered; duplicate one observed diagnostic instead (temp copy).
        dup = json.loads(json.dumps(observed))
        dup[0]["diagnostics"][0]["count"] += 1
        fails, _ = compare(dup, validate_waivers(waivers, groups))
        hit = [f for f in fails if f.startswith("count increased")]
        oks.append(bool(hit))
        lines.append(("CONTROL-OK count-increased (observed diagnostic "
                      "duplicated): FAIL at stage compare (%s)" % hit[0][:90])
                     if hit else "CONTROL-BROKEN count-increased")
        mutate("stale-waiver (added, never observed)", stale, "stale waiver")

        # 4. injected latch, real verilator on a temp copy of one group
        ldir = os.path.join(tmp, "latchcopy")
        os.makedirs(ldir)
        repo = _temp_repo(root, ldir)
        target = next(g for g in groups if g["id"] == "rf_global2_core")
        tp = os.path.join(repo, target["source"])
        with open(tp) as fh:
            src = fh.read()
        idx = src.rindex("endmodule")
        with open(tp, "w") as fh:
            fh.write(src[:idx] + _LATCH_INJECTION + src[idx:])
        rep = run_check(repo, manifest_path, waivers_path, verilator)
        hit = [r for r in rep["reasons"] if r.startswith(
            "new SEVERE diagnostic") and " LATCH " in r and "nc_inj_q" in r]
        ok = (rep["status"] == "FAIL" and rep["stage"] == "compare"
              and bool(hit) and rep["groups_executed"] == len(groups))
        oks.append(ok)
        lines.append("CONTROL-OK injected-latch: real verilator, full run, "
                     "fresh LATCH -> FAIL at stage compare (%s)" % hit[0][:90]
                     if ok else "CONTROL-BROKEN injected-latch: %s/%s %s"
                     % (rep["status"], rep["stage"], rep["reasons"][:2]))
    return all(oks), lines


# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", default="rtl/lint_manifest.json")
    ap.add_argument("--waivers", default="rtl/lint_waivers.json")
    ap.add_argument("--report", default=None)
    ap.add_argument("--raw-dir", default=None,
                    help="write raw verilator output per group here")
    ap.add_argument("--verilator", default="verilator")
    ap.add_argument("--root", default=REPO,
                    help="repository root (default: this checkout)")
    ap.add_argument("--negative-control", action="store_true",
                    help="run the failure controls on temporary copies; "
                         "exit 0 only if every control fails as intended")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    man = os.path.join(root, args.manifest)
    wai = os.path.join(root, args.waivers)

    if args.negative_control:
        try:
            ok, lines = negative_controls(root, man, wai, args.verilator)
        except Refusal as r:
            print("NOT_RUN/FAIL controls could not start: %s" % r)
            return 1
        except (OSError, subprocess.SubprocessError, AssertionError) as exc:
            print("FAIL controls could not run: %s" % exc)
            return 1
        for ln in lines:
            print(ln)
        print("ALL CONTROLS HEALTHY" if ok else "CONTROLS BROKEN")
        return 0 if ok else 1

    rep = run_check(root, man, wai, args.verilator, args.raw_dir)
    write_report(rep, args.report)
    summarize(rep, sys.stdout)
    return EXIT[rep["status"]]


if __name__ == "__main__":
    sys.exit(main())
