"""Enumerate tools/*_controls.py so no negative control goes unrun.

CLAUDE.md: "a control must demonstrably fail the check it targets". A control
script nothing executes can rot silently. This module:

1. Fails if a tools/*_controls.py exists that is not in
   tests/negative_controls_registry.json (or the registry names a missing
   script); registry keys are script filenames. The glob covers
   *_negative_controls.py plus profile_budget_controls.py and
   reverb2_reference_controls.py. tools/make_control_mutant.py (a mutant
   generator) and tools/render_control_fixtures.py (a fixture
   renderer/comparator) are helpers, not control runs; they do not match the
   glob and are asserted to stay unregistered (NON_CONTROL_HELPERS) -- adding a control forces a conscious LIVE / NOT_RUN decision.
2. Smoke-imports every registered script and requires a callable main().
3. Executes every LIVE script's main() into a scratch directory and requires
   the registry's acceptance helper (_accept): exit 0 for most scripts (they
   exit 0 only when every control failed its target check), plus a
   script-specific stdout verdict for scripts that exit 0 unconditionally or
   could pass vacuously (profile_budget_controls, reverb2_reference_controls).
   Committed report bytes named in the registry "guard" must be unchanged,
   and every scratch path in the registry "outputs" (only scripts verified to
   write from main() itself) must exist after the run. Scripts that need
   pinned-oracle inputs are NOT_RUN: they are import-smoked only and their execution test is skipped with the reason,
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

import hashlib
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
REGISTRY_PATH = os.path.join(REPO, "tests", "negative_controls_registry.json")
STATUSES = ("LIVE", "NOT_RUN:needs-oracle")


def _registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)["scripts"]


NON_CONTROL_HELPERS = ("make_control_mutant.py", "render_control_fixtures.py")


# Registry keys: a bare filename is an alias for tools/<name>; a key with "/"
# is repo-relative. Discovery scope is exactly tools/*_controls.py UNION the
# model/ control entrypoints below -- nothing else under model/, and never
# reports/ or fixtures/ (archives), so helpers/generators are not controls.
MODEL_CONTROL_GLOBS = ("model/**/negative_controls.py",
                       "model/**/*_negative_controls.py")
MODEL_NON_CONTROL_HELPERS = tuple(
    f"model/integration/{n}.py" for n in (
        "run_model", "render_fixtures", "extract_preset_inputs",
        "compare_integration", "selection_scan", "schedule_closure"))
SXT025_ENTRY = "model/integration/negative_controls.py"


def _on_disk():
    found = {os.path.basename(p) for p in
             glob.glob(os.path.join(TOOLS, "*_controls.py"))}
    for g in MODEL_CONTROL_GLOBS:
        for p in glob.glob(os.path.join(REPO, g), recursive=True):
            found.add(os.path.relpath(p, REPO).replace(os.sep, "/"))
    return sorted(found)


def _path(name):
    return os.path.join(REPO, name) if "/" in name else os.path.join(TOOLS, name)


def _modname(prefix, name):
    return prefix + re.sub(r"\W", "_", name[:-3])


def _sha(rel):
    with open(os.path.join(REPO, rel), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_BUDGET_SUMMARY = re.compile(r"^[ \t]+NC-B([1-4])[ \t]+(\S+)", re.M)


def _accept_budget(rc, out):
    """profile_budget_controls returns 0 unconditionally, so require exactly
    one explicit PASS summary for each of NC-B1..NC-B4 and no FAIL. NC-B5 is
    a recorded finding and is never counted."""
    if rc != 0:
        return False, f"exit {rc}"
    seen = {}
    for num, word in _BUDGET_SUMMARY.findall(out):
        if word not in ("PASS", "FAIL"):
            return False, f"malformed NC-B{num} summary {word!r}"
        seen.setdefault(num, []).append(word)
    for num in "1234":
        words = seen.get(num, [])
        if len(words) != 1:
            return False, f"NC-B{num}: {len(words)} summaries (need exactly 1)"
        if words[0] != "PASS":
            return False, f"NC-B{num} FAIL"
    return True, ""


def _accept_reverb2_reference(rc, out, tmp=None):
    """Require the declared reference-backed cases to have actually run:
    6 cases x 3 controls all 'ok', 'status: PASS', and (when tmp is given) a
    report with the same shape. An empty case selection is a vacuous PASS and
    is rejected."""
    if rc != 0:
        return False, f"exit {rc}"
    lines = out.splitlines()
    ok = [ln for ln in lines if ln.startswith("ok ")]
    bad = [ln for ln in lines if ln.startswith("FAIL ")]
    if bad or len(ok) != 18:
        return False, f"{len(ok)} ok / {len(bad)} FAIL control lines (need 18/0)"
    if "status: PASS" not in lines:
        return False, "no 'status: PASS' line"
    if tmp is not None:
        rep = os.path.join(str(tmp), "reference-controls.json")
        if not os.path.exists(rep):
            return False, "scratch report not written"
        with open(rep, encoding="utf-8") as f:
            doc = json.load(f)
        if (len(doc["cases"]) != 6 or doc["status"] != "PASS"
                or any(len(c["controls"]) != 3 for c in doc["cases"])):
            return False, "report does not hold 6 cases x 3 controls"
    return True, ""


_SXT025_LINE = re.compile(r"^NC-([ABC]): (\S+)", re.M)


def _accept_sxt025(rc, out, tmp=None, seq="sxt025-smoke-v1"):
    """Integrated wet-path controls: exit 0 alone is not enough. Require a
    CONTROL-OK line for each of NC-A/B/C exactly once, the HEALTHY summary,
    and (when tmp is given) the three scratch result files with detected ==
    true and non-empty case coverage. The committed RTL mutant clause that
    also feeds the exit code is historical input, not live RTL coverage."""
    if rc != 0:
        return False, f"exit {rc}"
    seen = {}
    for k, word in _SXT025_LINE.findall(out):
        seen.setdefault(k, []).append(word)
    for k in "ABC":
        # the script prints each line twice (per-control, then transcript)
        if not seen.get(k) or set(seen[k]) != {"CONTROL-OK"}:
            return False, f"NC-{k}: {seen.get(k)} (need only CONTROL-OK)"
    if "ALL CONTROLS HEALTHY" not in out.splitlines():
        return False, "no 'ALL CONTROLS HEALTHY' line"
    if tmp is not None:
        for k in "abc":
            p = os.path.join(str(tmp), "NC_DIR", f"nc-{k}-{seq}.json")
            if not os.path.exists(p):
                return False, f"scratch result {p} not written"
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            if doc.get("detected") is not True:
                return False, f"nc-{k}: detected != true"
            if not doc.get("control"):
                return False, f"nc-{k}: empty case coverage"
    return True, ""


def _accept(ent, rc, out, tmp=None):
    """The one acceptance helper used by the registry run and the failure
    controls. Returns (accepted, reason)."""
    v = ent["verdict"]
    if v == "exit0":
        return rc == 0, f"exit {rc}"
    if v == "budget-nc-b1-b4":
        return _accept_budget(rc, out)
    if v == "reverb2-reference":
        return _accept_reverb2_reference(rc, out, tmp)
    if v == "sxt025-integration":
        return _accept_sxt025(rc, out, tmp)
    raise AssertionError(f"unknown verdict adapter {v!r}")


@contextlib.contextmanager
def _isolated_imports():
    """Scripts add model dirs to sys.path and import same-named helpers
    (e.g. several run_filter_leg.py); restore import state after each.

    Helpers already cached by earlier test modules in a full-suite run would
    shadow the ones a script imports, so model/ and tools/ modules are evicted
    on entry (and put back on exit); the result must not depend on test order.
    """
    path = list(sys.path)
    local = tuple(os.path.join(REPO, d) + os.sep for d in ("model", "tools"))

    def _is_local(mod):
        return (getattr(mod, "__file__", None) or "").startswith(local)

    evicted = {k: m for k, m in sys.modules.items() if _is_local(m)}
    for k in evicted:
        del sys.modules[k]
    before = set(sys.modules)
    try:
        yield
    finally:
        for k in list(sys.modules):
            if k not in before and _is_local(sys.modules[k]):
                del sys.modules[k]
        sys.modules.update(evicted)
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
        assert name.endswith("_controls.py"), name
        assert os.path.exists(_path(name)), f"{name}: path missing"
        assert ent["status"] in STATUSES, (name, ent["status"])
        assert ent["verdict"] in ("exit0", "budget-nc-b1-b4",
                                  "reverb2-reference",
                                  "sxt025-integration"), (name, ent["verdict"])
        if ent["status"] != "LIVE":
            assert ent["reason"], f"{name}: NOT_RUN needs a recorded reason"
        outs = ent.get("outputs", [])
        assert isinstance(outs, list) and all(
            isinstance(o, str) and o and not os.path.isabs(o) for o in outs), (
            name, outs)
    # scripts verified to write their report from main() must declare it, so
    # the scratch-output check cannot silently drop them
    for must, out in (("profile_budget_controls.py", "OUT_REL"),
                      ("reverb2_reference_controls.py",
                       "reference-controls.json")):
        assert out in reg[must].get("outputs", []), (must, out)


def test_every_control_script_is_registered():
    on_disk, reg = set(_on_disk()), set(_registry())
    assert len(on_disk) >= 28, "enumeration found too few scripts"
    assert SXT025_ENTRY in on_disk and SXT025_ENTRY in reg
    assert _registry()[SXT025_ENTRY]["status"] in STATUSES
    for h in MODEL_NON_CONTROL_HELPERS:
        assert os.path.exists(_path(h)), f"helper {h} moved: re-classify"
        assert h not in on_disk and h not in reg, h
    for h in NON_CONTROL_HELPERS:
        assert os.path.exists(_path(h)), f"helper {h} moved: re-classify"
        assert h not in on_disk and h not in reg, (
            f"{h} is a generator/renderer helper, not a control run")
    for must in ("profile_budget_controls.py", "reverb2_reference_controls.py"):
        assert must in on_disk and must in reg, must
    assert on_disk - reg == set(), (
        "unregistered tools/*_controls.py (add to "
        f"tests/negative_controls_registry.json): {sorted(on_disk - reg)}")
    assert reg - on_disk == set(), (
        f"registry names missing scripts: {sorted(reg - on_disk)}")


def test_unregistered_controls_script_is_rejected(tmp_path):
    """Failure control for discovery: the same set comparison must flag a
    scratch tools/<x>_controls.py, and a missing registry row."""
    reg = set(_registry())
    on_disk = set(_on_disk()) | {"scratch_x_controls.py"}
    assert on_disk - reg == {"scratch_x_controls.py"}
    for gone in ("profile_budget_controls.py", "reverb2_reference_controls.py",
                 SXT025_ENTRY):
        assert set(_on_disk()) - (reg - {gone}) == {gone}


@pytest.mark.parametrize("name", sorted(_registry()))
def test_control_script_imports_and_exposes_main(name):
    with _isolated_imports():
        mod = _load(_path(name), _modname("ncl_smoke_", name))
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
        before = {g: _sha(g) for g in ent["guard"]}
        mod = _load(_path(name), _modname("ncl_run_", name))
        rc, out = _run_main(mod, ent["redirect"], ent["argv"], tmp_path)
    ok, why = _accept(ent, rc, out, tmp_path)
    assert ok, (f"{name}: a control did not fail its target check or "
                f"errored ({why}):\n{out[-2000:]}")
    assert {g: _sha(g) for g in ent["guard"]} == before, (
        f"{name}: committed report bytes changed")
    for rel in ent.get("outputs", []):
        assert os.path.exists(os.path.join(str(tmp_path), rel)), (
            f"{name}: scratch output {rel} not written")


def _noop_mutation_copy(tmp_path):
    """Copy rf_global2's control script with the NC-C mutation (swapping the
    coefficient sets) rewritten into a no-op."""
    src = open(_path("rf_global2_negative_controls.py"), encoding="utf-8").read()
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


# ---- script-specific adapter failure controls (cheap, synthetic stdout) ----

def _budget_out(**over):
    res = {"1": "PASS", "2": "PASS", "3": "PASS", "4": "PASS"}
    res.update(over)
    lines = ["NC-B1 (issue #12 acceptance) header", "", "NC-B2 - header", ""]
    for n in "1234":
        for w in ([res[n]] if not isinstance(res[n], list) else res[n]):
            lines.append(f"  NC-B{n} {w} - text")
    lines.append("  NC-B5 recorded (finding, not a sensitivity failure)")
    return "\n".join(lines) + "\n"


BUDGET_ENT = {"verdict": "budget-nc-b1-b4"}


def test_budget_adapter_accepts_only_four_explicit_passes():
    assert _accept(BUDGET_ENT, 0, _budget_out())[0]
    assert not _accept(BUDGET_ENT, 1, _budget_out())[0]
    for n in "1234":
        assert not _accept(BUDGET_ENT, 0, _budget_out(**{n: "FAIL"}))[0], n
        assert not _accept(BUDGET_ENT, 0, _budget_out(**{n: []}))[0], n
        assert not _accept(BUDGET_ENT, 0,
                           _budget_out(**{n: ["PASS", "PASS"]}))[0], n
        assert not _accept(BUDGET_ENT, 0, _budget_out(**{n: "MAYBE"}))[0], n
    # NC-B5 must not stand in for a missing control
    only5 = "  NC-B5 PASS\n"
    assert not _accept(BUDGET_ENT, 0, only5)[0]


def test_reverb2_adapter_rejects_vacuous_empty_case_selection(tmp_path):
    ent = {"verdict": "reverb2-reference"}
    healthy = "ok x\n" * 18 + "status: PASS\n"
    assert _accept(ent, 0, healthy)[0]
    assert not _accept(ent, 0, "status: PASS\n")[0]
    assert not _accept(ent, 0, "ok x\n" * 17 + "FAIL x\nstatus: PASS\n")[0]
    assert not _accept(ent, 1, healthy)[0]
    # synthetic legacy artifact: cases=[] / status PASS / PASS stdout
    legacy = tmp_path / "reference-controls.json"
    legacy.write_text(json.dumps({"cases": [], "status": "PASS"}))
    assert not _accept(ent, 0, "status: PASS\n", tmp_path)[0]
    # the producing CLI itself must now refuse invalid selections
    for sel in ("no__such_case", "", "tacobell__seq-poly-8-v1,",
                "tacobell__seq-poly-8-v1,no__such_case",
                "tacobell__seq-poly-8-v1,tacobell__seq-poly-8-v1"):
        scratch = tmp_path / "cli"
        scratch.mkdir(exist_ok=True)
        with _isolated_imports():
            mod = _load(_path("reverb2_reference_controls.py"), "ncl_rv2_empty")

            def boom(*a, **k):
                raise AssertionError("run_case executed for refused selector")
            mod.run_case = boom
            rc, out = _run_main(mod, [], ["--out", "{tmp}/cli/rc.json",
                                          "--cases", sel], tmp_path)
        assert rc != 0 and "status: PASS" not in out, sel
        assert not (scratch / "rc.json").exists(), sel


def test_reverb2_cli_subset_records_coverage(tmp_path):
    with _isolated_imports():
        mod = _load(_path("reverb2_reference_controls.py"), "ncl_rv2_subset")
        seen = []

        def fake(slug, seq, *a):
            seen.append((slug, seq))
            return {"slug": slug, "sequence": seq, "ok": True,
                    "controls": [{"ok": True, "verdict": "v"}]}
        mod.run_case = fake
        sel = "mystical__seq-poly-8-v1,tacobell__seq-poly-8-v1"
        rc, out = _run_main(mod, [], ["--out", "{tmp}/r.json",
                                      "--cases", sel], tmp_path)
        full_rc, full_out = _run_main(mod, [], ["--out", "{tmp}/f.json"],
                                      tmp_path)
    assert rc == 0 and seen[:2] == [("tacobell", "seq-poly-8-v1"),
                                    ("mystical", "seq-poly-8-v1")]
    cov = json.load(open(tmp_path / "r.json"))["coverage"]
    assert cov["scope"] == "subset" and cov["executed_count"] == 2
    assert cov["requested_case_ids"] == sel.split(",")
    assert "coverage: subset" in out
    # a subset PASS is never accepted by the full-run registry adapter
    assert not _accept({"verdict": "reverb2-reference"}, rc, out, tmp_path)[0]
    assert full_rc == 0 and len(seen) == 8
    assert json.load(open(tmp_path / "f.json"))["coverage"]["scope"] == "full"


def _budget_copies(tmp_path):
    src = open(_path("profile_budget_controls.py"), encoding="utf-8").read()
    repo_line = "REPO = Path(__file__).resolve().parents[1]"
    ladder = "LADDER = (1.0, 2.0, 21.0, 40.0)"
    assert src.count(repo_line) == 1 and src.count(ladder) == 1, "anchor moved"
    healthy = src.replace(repo_line, f"REPO = Path({REPO!r})")
    broken = healthy.replace(ladder, "LADDER = (1.0, 1.0, 1.0, 1.0)")
    paths = {}
    for tag, text in (("healthy", healthy), ("noop", broken)):
        p = tmp_path / f"profile_budget_{tag}_controls.py"
        p.write_text(text, encoding="utf-8")
        paths[tag] = str(p)
    return paths


@pytest.mark.skipif(os.environ.get("NC_LIVE_SLOW") != "1",
                    reason="NOT_RUN: two ~47 s budget runs; set NC_LIVE_SLOW=1"
                           " (not a pass)")
def test_failure_control_budget_noop_is_rejected_despite_exit_zero(tmp_path):
    ent = _registry()["profile_budget_controls.py"]
    guard = ent["guard"]
    before = {g: _sha(g) for g in guard}
    paths = _budget_copies(tmp_path)
    results = {}
    for tag in ("healthy", "noop"):
        scratch = tmp_path / tag
        scratch.mkdir()
        with _isolated_imports():
            mod = _load(paths[tag], f"ncl_budget_{tag}")
            results[tag] = _run_main(mod, ["OUT_REL"], [], scratch)
        assert (scratch / "OUT_REL").exists(), f"{tag}: scratch output missing"
        assert {g: _sha(g) for g in guard} == before, (
            f"{tag}: committed report bytes changed")
    rc_h, out_h = results["healthy"]
    assert _accept(ent, rc_h, out_h)[0], out_h[-1500:]
    rc_b, out_b = results["noop"]
    assert rc_b == 0, "premise: the no-op copy still exits zero"
    assert re.search(r"^[ \t]+NC-B1 FAIL", out_b, re.M)
    assert not _accept(ent, rc_b, out_b)[0]


# ---- SXT-025 integrated wet-path controls (#419) ----

def _tree_hashes(rel_dirs):
    out = {}
    for d in rel_dirs:
        for root, _, files in os.walk(os.path.join(REPO, d)):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), REPO)
                out[rel] = _sha(rel)
    return out


def _sxt025_noop_copies(tmp_path):
    """Temporary source copy of the integration entrypoint with the NC-A
    placement mutation turned into a no-op (the permuted image/inputs are
    replaced by unmodified deep copies). REPO is pinned because the copy lives
    outside model/integration."""
    src = open(_path(SXT025_ENTRY), encoding="utf-8").read()
    repo_line = ("REPO = os.path.dirname(os.path.dirname(os.path.dirname("
                 "os.path.abspath(__file__))))")
    img = '    mut_path = os.path.join(NC_DIR, "image-permuted-placement.json")\n'
    inp = ('    mut_inputs_path = os.path.join(NC_DIR, '
           '"inputs-permuted-placement.json")\n')
    for a in (repo_line, img, inp):
        assert src.count(a) == 1, f"failure-control anchor moved: {a!r}"
    healthy = src.replace(repo_line, f"REPO = {REPO!r}")
    noop = healthy.replace(img, "    mut = copy.deepcopy(image)\n" + img)
    noop = noop.replace(inp, "    mut_inputs = copy.deepcopy(inputs)\n" + inp)
    paths = {}
    for tag, text in (("healthy", healthy), ("noop", noop)):
        p = tmp_path / f"sxt025_{tag}_negative_controls.py"
        p.write_text(text, encoding="utf-8")
        paths[tag] = str(p)
    return paths


def test_failure_control_sxt025_nc_a_noop_is_rejected(tmp_path):
    """NC-A made a no-op in a temp source copy must be rejected by the
    registry adapter even though the committed transcript stays healthy."""
    ent = _registry()[SXT025_ENTRY]
    guard = ent["guard"]
    before = {g: _sha(g) for g in guard}
    paths = _sxt025_noop_copies(tmp_path)
    res = {}
    for tag in ("healthy", "noop"):
        scratch = tmp_path / tag
        scratch.mkdir()
        with _isolated_imports():
            mod = _load(paths[tag], f"ncl_sxt025_{tag}")
            res[tag] = _run_main(mod, ent["redirect"], ent["argv"], scratch)
        assert {g: _sha(g) for g in guard} == before, tag
    rc_h, out_h = res["healthy"]
    assert _accept(ent, rc_h, out_h, tmp_path / "healthy")[0], out_h[-1500:]
    rc_b, out_b = res["noop"]
    assert rc_b != 0, "no-op NC-A mutation was NOT detected by the harness"
    assert "NC-A: CONTROL-BROKEN" in out_b
    assert not _accept(ent, rc_b, out_b, tmp_path / "noop")[0]
    # the committed healthy transcript does not rescue the adapter
    assert "ALL CONTROLS HEALTHY" in open(
        os.path.join(REPO, "reports/sxt-025/negative-controls.txt"),
        encoding="utf-8").read()


def test_sxt025_adapter_rejects_incomplete_runs(tmp_path):
    ent = {"verdict": "sxt025-integration"}
    good = ("NC-A: CONTROL-OK (x)\nNC-B: CONTROL-OK (y)\nNC-C: CONTROL-OK (z)\n"
            "ALL CONTROLS HEALTHY\n")
    assert _accept(ent, 0, good)[0]
    assert not _accept(ent, 1, good)[0]
    assert not _accept(ent, 0, good.replace("NC-B: CONTROL-OK", "NC-B: CONTROL-BROKEN"))[0]
    assert not _accept(ent, 0, good.replace("NC-C: CONTROL-OK (z)\n", ""))[0]
    assert not _accept(ent, 0, good.replace("ALL CONTROLS HEALTHY\n", ""))[0]
    # missing / not-detected / empty scratch results
    assert not _accept(ent, 0, good, tmp_path)[0]
    d = tmp_path / "NC_DIR"
    d.mkdir()
    for k in "abc":
        (d / f"nc-{k}-sxt025-smoke-v1.json").write_text(
            json.dumps({"control": "c", "detected": True}))
    assert _accept(ent, 0, good, tmp_path)[0]
    (d / "nc-b-sxt025-smoke-v1.json").write_text(
        json.dumps({"control": "c", "detected": False}))
    assert not _accept(ent, 0, good, tmp_path)[0]
    (d / "nc-b-sxt025-smoke-v1.json").write_text(
        json.dumps({"control": "", "detected": True}))
    assert not _accept(ent, 0, good, tmp_path)[0]


def test_sxt025_live_run_leaves_committed_artifacts_byte_identical(tmp_path):
    """Whole-tree before/after hash of reports/sxt-025 around a scratch run."""
    ent = _registry()[SXT025_ENTRY]
    before = _tree_hashes(["reports/sxt-025"])
    with _isolated_imports():
        mod = _load(_path(SXT025_ENTRY), "ncl_sxt025_tree")
        rc, out = _run_main(mod, ent["redirect"], ent["argv"], tmp_path)
    assert _accept(ent, rc, out, tmp_path)[0], out[-1500:]
    assert _tree_hashes(["reports/sxt-025"]) == before
    for rel in ent["outputs"]:
        assert os.path.exists(os.path.join(str(tmp_path), rel)), rel
