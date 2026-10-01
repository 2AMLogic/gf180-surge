#!/usr/bin/env python3
"""Issue #165: ONE definition may be called `spectral_corr`.

Issue #110 made `tools/compare_audio_reference.spectral_corr` the single
definition for the `spectral_corr >= 0.98` budget. #165 resolved the six
per-leaf copies that still graded that NAME with their own native-unit
`log1p` definition: three were MIGRATED to the shared function (sxt-028a,
SXT-028e/-sse, SXT-028f) and the 0.999 L2 filter family was RENAMED to
`l2_spectral_corr` (sxt-037, SXT-038, SXT-039).

These tests are the structural guard on that outcome, not a restatement of
it: #110's own record had to list six NOT-MIGRATED leaves precisely because
nothing mechanically prevented a second definition from appearing under the
frozen name. Each check carries a live negative control showing it fails on
the condition it exists to detect.

Nothing here claims any fidelity, RTL, support or sound result: this is a
metric-DEFINITION consistency check over the measurement tooling.
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402


def load_by_path(unique_name, rel):
    """Import a module by FILE PATH under a unique name.

    `model/voice/filter_lp12`, `.../filter_lp24` and `.../filter_lpmoog` each
    hold a DIFFERENT `run_filter_leg.py`. A bare `import run_filter_leg` after
    a sys.path insert resolves to whichever one `sys.modules` already holds
    from an earlier test in the same session -- which silently asserted
    against `filter_lpmoog`'s file (it has no spectral metric at all) instead
    of the one under test. Loading by path keeps the three distinct.
    """
    path = os.path.join(REPO, rel)
    spec = importlib.util.spec_from_file_location(unique_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    spec.loader.exec_module(mod)
    return mod

# The ONE file allowed to define a function named exactly `spectral_corr`
# that computes it. Every other module must delegate to this one (a
# delegating wrapper of the same name is fine and is checked separately
# below: its body is a call into `car.spectral_corr`).
OWNER = "tools/compare_audio_reference.py"

# Tools that define a `spectral_corr` WRAPPER delegating to the shared
# definition, with the full scale each one's bus declares.
DELEGATES = {
    "tools/compare_fx_reference.py": ("compare_fx_reference", 1.0),
    "tools/compare_chorus_reference.py": ("compare_chorus_reference", 1.0),
    "tools/compare_aw49_reference.py": ("compare_aw49_reference", 1.0),
    "tools/distortion_negative_controls.py": ("distortion_negative_controls",
                                              float(1 << 20)),
    "tools/reverb2_negative_controls.py": ("reverb2_negative_controls",
                                           float(1 << 21)),
}


def _py_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in (".git", ".loom", "__pycache__", "node_modules")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def _defines_spectral_corr(path):
    """(defines, delegates) for a .py file.

    `delegates` is True when every `def spectral_corr` in the file is a thin
    wrapper whose body calls `<module>.spectral_corr(...)` -- i.e. it names
    the shared definition rather than recomputing one.
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:                                   # pragma: no cover
        return False, False
    defines, delegating = False, True
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == "spectral_corr":
            defines = True
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
            if not any(isinstance(c.func, ast.Attribute)
                       and c.func.attr == "spectral_corr" for c in calls):
                delegating = False
    return defines, defines and delegating


def find_offenders(root):
    """Files that define their OWN `spectral_corr` computation under `root`."""
    out = []
    for path in sorted(_py_files(root)):
        rel = os.path.relpath(path, root)
        if rel.replace(os.sep, "/") == OWNER:
            continue
        defines, delegates = _defines_spectral_corr(path)
        if defines and not delegates:
            out.append(rel.replace(os.sep, "/"))
    return out


def test_only_the_shared_module_computes_spectral_corr():
    """No file but the owner may COMPUTE something named `spectral_corr`."""
    assert find_offenders(REPO) == [], (
        "these files define their own `spectral_corr` computation; the name "
        "belongs to %s's frozen definition (#110/#165). Either delegate to it "
        "with the bus's declared full scale, or rename the metric." % OWNER)


def test_the_scan_detects_a_reintroduced_per_leaf_copy(tmp_path):
    """Live negative control for the scan above.

    The pre-#165 shape -- a per-leaf native-unit `log1p` copy under the
    frozen name -- must be reported. A scan that could not see it would be
    decorative.
    """
    (tmp_path / "leaf_tool.py").write_text(
        "import numpy as np\n"
        "def spectral_corr(a, b, frame=4096):\n"
        "    return float(np.log1p(np.abs(np.fft.rfft(a))).mean())\n")
    assert find_offenders(str(tmp_path)) == ["leaf_tool.py"]
    # ...and a delegating wrapper of the same name is NOT an offender
    (tmp_path / "leaf_tool.py").write_text(
        "import compare_audio_reference as car\n"
        "def spectral_corr(a, b, frame=4096):\n"
        "    return car.spectral_corr(a, b, full_scale=1.0, frame=frame)\n")
    assert find_offenders(str(tmp_path)) == []


@pytest.mark.parametrize("rel", sorted(DELEGATES))
def test_delegate_matches_the_shared_definition_at_its_declared_full_scale(rel):
    """Each migrated tool's wrapper == the shared function at its own FS.

    This is what makes the 0.98 budget mean one thing: the wrapper may not
    quietly pass a different full scale, frame or floor.
    """
    mod_name, full_scale = DELEGATES[rel]
    mod = __import__(mod_name)
    rs = np.random.default_rng(1965)
    n = 3 * car.SPECTRAL_CORR_FRAME
    a = np.sin(2 * np.pi * 440.0 / 48000.0 * np.arange(n)) * 0.4 * full_scale
    b = a + rs.normal(0.0, 1e-4 * full_scale, n)
    assert mod.spectral_corr(a, b) == car.spectral_corr(
        a, b, full_scale=full_scale)
    # the retired definition on the same pair is a MATERIALLY different
    # number, so a tool that silently reverted would not pass the line above
    assert abs(mod.spectral_corr(a, b)
               - car.spectral_corr_legacy_log1p(a, b)) > 1e-6


def test_distortion_controls_fail_closed_on_a_non_finite_spectral_leg():
    """Live control for #165's fail-closed `verdict()`.

    Before #165 a NaN `spectral_corr` (numpy absent) was IGNORED, so a leg
    that never ran was graded as a pass. AGENTS.md forbids exactly that.
    """
    import distortion_negative_controls as dnc
    ok = {"max_abs_diff_lsb": 0.0, "rms_diff_dbfs": -200.0,
          "spectral_corr": 1.0}
    assert dnc.verdict(ok) == "PASS"
    assert dnc.verdict(dict(ok, spectral_corr=float("nan"))) == "FAIL"
    assert dnc.verdict(dict(ok, spectral_corr=0.5)) == "FAIL"


def test_migrated_records_carry_the_definition_stamp():
    """Every regenerated 0.98-family record says which definition made it."""
    for rel in ("reports/SXT-028e/negative-controls/negative-controls.json",
                "reports/SXT-028f/negative-controls/negative-controls.json"):
        doc = json.load(open(os.path.join(REPO, rel), encoding="utf-8"))
        blocks = []

        def walk(o):
            if isinstance(o, dict):
                # a MEASURED value only: `budget_results.spectral_corr` is
                # the leg's boolean pass flag, not a measurement
                if isinstance(o.get("spectral_corr"), float):
                    blocks.append(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(doc)
        assert blocks, "%s carries no spectral_corr block" % rel
        for b in blocks:
            assert b.get("spectral_corr_definition") == \
                car.SPECTRAL_CORR_DEFINITION, \
                ("%s has a spectral_corr with no (or a stale) definition "
                 "stamp: a reader cannot tell which definition produced it"
                 % rel)


def test_l2_family_renamed_off_the_frozen_name():
    """The 0.999 L2 family exposes `l2_spectral_corr`, never the frozen name.

    All three producing sites are covered: the SXT-037 (lp12) and SXT-038
    (lp24) leg runners, which each compute the metric themselves, and
    SXT-039's `compare_lpmoog_model`. `model/voice/filter_lpmoog/
    run_filter_leg.py` is asserted separately below to define NEITHER name --
    it has no spectral metric, so it is not a site this issue migrates, and
    pinning that keeps a future copy there from going unnoticed.
    """
    import compare_lpmoog_model as clm
    import compare_lp12_model as clp12
    import compare_lp24_model as clp24
    lp12 = load_by_path("_rfl_lp12",
                        "model/voice/filter_lp12/run_filter_leg.py")
    lp24 = load_by_path("_rfl_lp24",
                        "model/voice/filter_lp24/run_filter_leg.py")
    for mod in (lp12, lp24, clm):
        assert hasattr(mod, "l2_spectral_corr"), mod.__file__
        assert not hasattr(mod, "spectral_corr"), mod.__file__
        assert "NOT compare_audio_reference.spectral_corr" in \
            mod.L2_SPECTRAL_CORR_DEFINITION, mod.__file__
    lpmoog = load_by_path("_rfl_lpmoog",
                          "model/voice/filter_lpmoog/run_filter_leg.py")
    assert not hasattr(lpmoog, "spectral_corr")
    assert not hasattr(lpmoog, "l2_spectral_corr")
    # ONE definition string across the three producers: the artifact rename
    # tool stamps SXT-038's and SXT-039's records with the string it imports
    # from lp12, so a drift between them would stamp a record with a
    # description of a different function.
    assert lp12.L2_SPECTRAL_CORR_DEFINITION == \
        lp24.L2_SPECTRAL_CORR_DEFINITION == clm.L2_SPECTRAL_CORR_DEFINITION
    assert "l2_spectral_corr_min" in clp12.PROPOSED
    assert "l2_spectral_corr_min" in clp24.BUDGETS
    assert "spectral_corr_min" not in clp24.BUDGETS, \
        ("SXT-038 graded `spectral_corr_min` while its siblings graded "
         "`l2_spectral_corr_min`; that naming gap is what hid all eleven "
         "SXT-038 records from the #110 regrade ledger")


def test_no_committed_l2_artifact_carries_the_frozen_name():
    """The committed L2 records use the renamed key (tool's own --check)."""
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools",
                                      "rename_l2_spectral_corr_key.py"),
         "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_ledger_sees_a_spectral_corr_object_not_only_a_leaf():
    """Live control for the #165 ledger fix (the SXT-038 blind spot).

    `has_spectral_value` tested only the LAST path component, so the eleven
    SXT-038 records -- which nest the value in a `spectral_corr` OBJECT --
    were invisible to the #110 ledger. A budget-only record must still not
    match, or every BUDGET-ONLY row would turn into a false finding.
    """
    import regrade_spectral_corr as rsc
    assert rsc.has_spectral_value({"spectral_corr": 0.99})
    assert rsc.has_spectral_value(
        {"spectral_corr": {"achieved": 0.999559, "budget": 0.999,
                           "pass": True, "gating": False}})
    assert not rsc.has_spectral_value({"budgets": {"spectral_corr_min": 0.98}})
    assert not rsc.has_spectral_value(
        {"L2_audio_q1021": {"l2_spectral_corr": 0.9996}})


def test_the_ledger_rename_class_cannot_launder_a_moved_value():
    """Live control for RENAME-#165.

    The class exists so a name-only change classifies; it must NOT absorb a
    change of VALUE hiding under the new name.
    """
    import regrade_spectral_corr as rsc
    rel = "reports/SXT-039/artifacts/budget-chords.json"
    k_old, k_new = "/L2_audio_q1021/spectral_corr", \
        "/L2_audio_q1021/l2_spectral_corr"
    lo, ln = {k_old: 0.9996}, {k_new: 0.9996}
    assert rsc.classify(rel, k_old, 0.9996, "<absent>", ln, lo) == "RENAME-#165"
    assert rsc.classify(rel, k_new, "<absent>", 0.9996, ln, lo) == "RENAME-#165"
    moved = {k_new: 0.5}
    assert rsc.classify(rel, k_old, 0.9996, "<absent>", moved, lo) != \
        "RENAME-#165"
    assert rsc.classify(rel, k_new, "<absent>", 0.5, moved, lo) != "RENAME-#165"
    # and the class is confined to the declared L2 family
    assert rsc.classify("reports/sxt-022/artifacts/x.json", k_old, 0.9996,
                        "<absent>", ln, lo) != "RENAME-#165"


def test_the_ledger_rename_class_runs_before_the_verdict_class():
    """`spectral_corr.pass` is nested INSIDE the renamed SXT-038 object.

    If VERDICT matched first, the rename would be reported as a status flip
    (True -> absent) in all eleven SXT-038 records.
    """
    import regrade_spectral_corr as rsc
    rel = "reports/SXT-038/artifacts/compare-brass.json"
    lo = {"/spectral_corr/pass": True}
    ln = {"/l2_spectral_corr/pass": True}
    assert rsc.classify(rel, "/spectral_corr/pass", True, "<absent>", ln, lo) \
        == "RENAME-#165"
    assert rsc.classify(rel, "/l2_spectral_corr/pass", "<absent>", True, ln,
                        lo) == "RENAME-#165"


# --------------------------------------------------------------------------
# The committed #165 evidence record must stay consistent with the tooling it
# describes. These do NOT re-derive the measurements (that is
# tools/spectral_corr_per_leaf_checks.py's job, and the artifacts carry its
# transcripts); they catch an evidence record that has gone STALE relative to
# the code -- the failure mode AGENTS.md warns about when a committed record is
# read as a current verdict.
REC = "reports/spectral-corr-per-leaf-migration"


def test_the_committed_checks_summary_covers_every_leg_at_pass():
    s = json.load(open(os.path.join(REPO, REC, "artifacts",
                                    "checks-summary.json"), encoding="utf-8"))
    assert s["issue"] == 165
    assert s["shared_definition"] == car.SPECTRAL_CORR_DEFINITION, \
        ("the committed record was produced under a different shared "
         "definition than the current tooling: it is STALE, not a pass")
    assert sorted(s["legs_run"]) == [1, 2, 3, 4, 5, 6], \
        "a leg that did not run must never be read as a pass"
    assert len(s["legs"]) == 6
    for key, leg in s["legs"].items():
        assert leg["status"] == "PASS", (key, leg["status"])


def test_the_evidence_record_names_both_spectral_leg_flips():
    """Acceptance: 'every verdict flip is named'.

    The two SXT-028e spectral-leg flips the migration caused are derived from
    the committed record here and must each appear in the EVIDENCE prose, so
    the record cannot drift into claiming a clean migration.
    """
    flips = json.load(open(os.path.join(REPO, REC, "artifacts",
                                        "migration-flips.json"),
                           encoding="utf-8"))["spectral_leg_flips"]
    assert len(flips) == 2, [f["block"] for f in flips]
    doc = open(os.path.join(REPO, REC, "EVIDENCE.md"), encoding="utf-8").read()
    for f in flips:
        for v in (f["old"], f["new"]):
            assert "%.6f" % v in doc, \
                ("EVIDENCE.md does not name the flip at %s (%.6f -> %.6f)"
                 % (f["block"], f["old"], f["new"]))
    # ...and no OVERALL verdict moved, which is the stronger claim it makes
    led = json.load(open(os.path.join(REPO, REC, "artifacts",
                                      "regrade-ledger.json"),
                         encoding="utf-8"))
    assert led["verdict_flips"] == []
    assert led["unexplained"] == []
