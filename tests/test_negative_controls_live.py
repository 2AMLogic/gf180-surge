"""Enumerate tools/*_negative_controls.py so no negative control goes unrun.

CLAUDE.md: "a control must demonstrably fail the check it targets". A control
script nothing executes can rot silently. This module:

1. Fails if a tools/*_negative_controls.py exists that is not in
   tests/negative_controls_registry.json (or the registry names a missing
   script) -- adding a control forces a conscious LIVE / NOT_RUN decision.
2. Smoke-imports every registered script and requires a callable main().
3. Executes every LIVE script's main() into a scratch directory and requires
   exit 0 (the scripts exit 0 only when every control failed its target
   check). Scripts that need pinned-oracle inputs are NOT_RUN: they are
   import-smoked only and their execution test is skipped with the reason,
   never reported as a pass. Slow LIVE scripts (>60 s) run only with
   NC_LIVE_SLOW=1; otherwise they skip with a visible NOT_RUN reason.
4. Failure control: a temporary copy of a control script whose mutation is
   rewritten into a no-op must be reported as not-failing (exit != 0 and a
   CONTROL-BROKEN verdict), while the unmutated copy is healthy.

No byte-frozen file is edited: scripts are only imported and run, with their
output constants re-pointed at a scratch directory.
"""

import contextlib
import glob
import importlib.util
import io
import json
import os
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
REGISTRY_PATH = os.path.join(REPO, "tests", "negative_controls_registry.json")
STATUSES = ("LIVE", "NOT_RUN:needs-oracle")


def _registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)["scripts"]


def _on_disk():
    return sorted(os.path.basename(p)[: -len("_negative_controls.py")]
                  for p in glob.glob(os.path.join(TOOLS,
                                                  "*_negative_controls.py")))


def _path(name):
    return os.path.join(TOOLS, f"{name}_negative_controls.py")


@contextlib.contextmanager
def _isolated_imports():
    """Scripts add model dirs to sys.path and import same-named helpers
    (e.g. several run_filter_leg.py); restore import state after each."""
    mods, path = dict(sys.modules), list(sys.path)
    try:
        yield
    finally:
        for k in list(sys.modules):
            if k in mods:
                continue
            f = getattr(sys.modules[k], "__file__", None) or ""
            # only repo-local modules are dropped; third-party (numpy) stay
            if f.startswith(REPO + os.sep):
                del sys.modules[k]
        sys.path[:] = path


def _load(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_main(mod, redirect, argv, tmp):
    """Run mod.main() with output constants re-pointed at tmp.

    Returns (exit_code, stdout). A non-int/None return counts as 0 only if
    it is None or a tuple whose first element is 0 (control_negative_controls
    returns (rc, lines))."""
    for const in redirect:
        old = getattr(mod, const)
        new = os.path.join(str(tmp), const)
        setattr(mod, const, type(old)(new))
    old_argv = sys.argv
    sys.argv = [mod.__file__] + [a.replace("{tmp}", str(tmp)) for a in argv]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                rc = mod.main()
            except SystemExit as e:
                rc = e.code
    finally:
        sys.argv = old_argv
    if isinstance(rc, tuple):
        rc = rc[0]
    return (0 if rc is None else rc), buf.getvalue()


def test_registry_is_well_formed():
    reg = _registry()
    for name, ent in reg.items():
        assert ent["status"] in STATUSES, (name, ent["status"])
        if ent["status"] != "LIVE":
            assert ent["reason"], f"{name}: NOT_RUN needs a recorded reason"


def test_every_control_script_is_registered():
    on_disk, reg = set(_on_disk()), set(_registry())
    assert len(on_disk) >= 25, "enumeration found too few scripts"
    assert on_disk - reg == set(), (
        "unregistered tools/*_negative_controls.py (add to "
        f"tests/negative_controls_registry.json): {sorted(on_disk - reg)}")
    assert reg - on_disk == set(), (
        f"registry names missing scripts: {sorted(reg - on_disk)}")


@pytest.mark.parametrize("name", sorted(_registry()))
def test_control_script_imports_and_exposes_main(name):
    with _isolated_imports():
        mod = _load(_path(name), f"ncl_smoke_{name}")
        assert callable(getattr(mod, "main", None)), f"{name}: no main()"


@pytest.mark.parametrize("name", sorted(_registry()))
def test_control_script_executes_and_all_controls_fail_their_checks(
        name, tmp_path):
    ent = _registry()[name]
    if ent["status"] != "LIVE":
        pytest.skip(f"{ent['status']}: {ent['reason']} (not a pass)")
    for tool in ent["requires"]:
        if shutil.which(tool) is None:
            pytest.skip(f"NOT_RUN: {tool} absent; {name} controls not "
                        "executed (not a pass)")
    if ent["slow"] and os.environ.get("NC_LIVE_SLOW") != "1":
        pytest.skip(f"NOT_RUN: slow control ({ent['reason']}); set "
                    "NC_LIVE_SLOW=1 to execute (not a pass)")
    with _isolated_imports():
        mod = _load(_path(name), f"ncl_run_{name}")
        rc, out = _run_main(mod, ent["redirect"], ent["argv"], tmp_path)
    assert rc == 0, (f"{name}: a control did not fail its target check or "
                     f"errored (exit {rc}):\n{out[-2000:]}")


def _noop_mutation_copy(tmp_path):
    """Copy rf_global2's control script with the NC-C mutation (swapping the
    coefficient sets) rewritten into a no-op."""
    src = open(_path("rf_global2"), encoding="utf-8").read()
    mutated = "run_routing(8, COEFFS_B, COEFFS_A, seed=33)"
    noop = "run_routing(8, COEFFS_A, COEFFS_B, seed=33)"
    assert src.count(mutated) == 1, "failure-control anchor moved"
    repo_line = "REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))"
    assert src.count(repo_line) == 1
    pinned = f"REPO = {REPO!r}"
    healthy = src.replace(repo_line, pinned)
    broken = healthy.replace(mutated, noop)
    paths = {}
    for tag, text in (("healthy", healthy), ("noop", broken)):
        p = tmp_path / f"rf_global2_{tag}_negative_controls.py"
        p.write_text(text, encoding="utf-8")
        paths[tag] = str(p)
    return paths


def test_failure_control_noop_mutation_is_reported_not_failing(tmp_path):
    paths = _noop_mutation_copy(tmp_path)
    with _isolated_imports():
        healthy = _load(paths["healthy"], "ncl_fc_healthy")
        rc_h, out_h = _run_main(healthy, ["OUT"], [], tmp_path / "h")
    assert rc_h == 0, out_h
    assert "CONTROL-BROKEN" not in out_h

    with _isolated_imports():
        broken = _load(paths["noop"], "ncl_fc_noop")
        rc_b, out_b = _run_main(broken, ["OUT"], [], tmp_path / "b")
    assert rc_b != 0, "no-op mutation was NOT detected by the harness"
    assert "CONTROL-BROKEN (permutation undetected!)" in out_b
