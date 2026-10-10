"""Issue #418: control/override arguments of tools/publish_coverage.py are
refused at the normal publication destination (incl. traversal and symlink
aliases), before any output mutation.

Every protected-output test runs against an ISOLATED fixture tree (symlinked
inputs, a private copy of reports/coverage-v1) -- never the repository's real
publication. Statuses: a guard-bypassed copy of the tool must FAIL the
protected-output check (live failure control).
"""
import hashlib
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "publish_coverage.py")
sys.path.insert(0, os.path.join(REPO, "tools"))
import publish_coverage as pc  # noqa: E402

PUB = "reports/coverage-v1"
FILES = ("per-preset.csv", "coverage.json")


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_fixture(root):
    """Fixture repo: everything symlinked to the real tree except a private
    copy of reports/coverage-v1 seeded with sentinel publication files."""
    root = str(root)
    for name in os.listdir(REPO):
        if name in (".git", "reports"):
            continue
        os.symlink(os.path.join(REPO, name), os.path.join(root, name))
    os.makedirs(os.path.join(root, "reports"))
    for name in os.listdir(os.path.join(REPO, "reports")):
        if name != "coverage-v1":
            os.symlink(os.path.join(REPO, "reports", name),
                       os.path.join(root, "reports", name))
    pub = os.path.join(root, PUB)
    shutil.copytree(os.path.join(REPO, PUB), pub)
    for n in FILES:
        with open(os.path.join(pub, n), "wb") as f:
            f.write(b"SENTINEL " + n.encode() + b"\n")
    return root, pub


def run_tool(root, outdir, extra=(), tool=TOOL):
    cmd = [sys.executable, tool, "--repo-root", root, "--outdir", outdir,
           *extra]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


LEDGER = os.path.join(REPO, PUB, "integration-ledger.json")
TABLE = os.path.join(REPO, PUB, "leaf-verification.json")
CONTROL_ARG_SETS = {
    "--leaf-table": ["--leaf-table", TABLE],
    "--control-allow-input-drift": ["--control-allow-input-drift"],
    "--rng-exclusion": ["--rng-exclusion", "x.json"],
    "--control-ignore-rng-exclusion": ["--control-ignore-rng-exclusion"],
    "--integration-ledger": ["--integration-ledger", LEDGER],
}


def test_control_arg_table_covers_every_cli_control():
    import re
    src = open(TOOL, encoding="utf-8").read()
    flags = set(re.findall(r'add_argument\("(--[a-z-]+)"', src))
    non_control = {"--repo-root", "--outdir"}
    assert flags - non_control == {f for _, f in pc.CONTROL_ARGS}
    assert set(CONTROL_ARG_SETS) == {f for _, f in pc.CONTROL_ARGS}


@pytest.mark.parametrize("flag", sorted(CONTROL_ARG_SETS))
def test_every_control_refused_at_default_destination(tmp_path, flag):
    root, pub = make_fixture(tmp_path)
    before = {n: sha(os.path.join(pub, n)) for n in FILES}
    r = run_tool(root, PUB, CONTROL_ARG_SETS[flag])
    assert r.returncode != 0 and "REFUSE" in r.stderr, r.stderr
    assert {n: sha(os.path.join(pub, n)) for n in FILES} == before
    assert not os.path.exists(os.path.join(pub, pc.CONTROL_MARKER_FILE))


def alias_dests(root, tmp_path):
    link = os.path.join(root, "alias-link")
    os.symlink(os.path.join(root, PUB), link)
    sub_link = os.path.join(root, "reports", "sub-link")
    os.symlink(os.path.join(root, "reports"), sub_link)
    return {
        "dot": "./reports/coverage-v1/.",
        "traversal": "reports/../reports/coverage-v1",
        "inside": "reports/coverage-v1/scratch",
        "absolute": os.path.join(root, PUB),
        "dir-symlink": "alias-link",
        "parent-symlink": "reports/sub-link/coverage-v1",
    }


def test_aliases_of_publication_dir_refused(tmp_path):
    root, pub = make_fixture(tmp_path)
    before = {n: sha(os.path.join(pub, n)) for n in FILES}
    for name, dest in alias_dests(root, tmp_path).items():
        r = run_tool(root, dest, ["--control-allow-input-drift"])
        assert r.returncode != 0 and "REFUSE" in r.stderr, (name, r.stderr)
        assert {n: sha(os.path.join(pub, n)) for n in FILES} == before, name
    assert not os.path.exists(os.path.join(pub, "scratch"))


def test_file_level_symlink_alias_refused(tmp_path):
    root, pub = make_fixture(tmp_path)
    scratch = os.path.join(root, "scratch")
    os.makedirs(scratch)
    os.symlink(os.path.join(pub, "coverage.json"),
               os.path.join(scratch, "coverage.json"))
    before = sha(os.path.join(pub, "coverage.json"))
    r = run_tool(root, "scratch", ["--control-allow-input-drift"])
    assert r.returncode != 0 and "REFUSE" in r.stderr
    assert sha(os.path.join(pub, "coverage.json")) == before


def test_scratch_control_run_works_with_marker(tmp_path):
    root, pub = make_fixture(tmp_path)
    before = {n: sha(os.path.join(pub, n)) for n in FILES}
    r = run_tool(root, "scratch-out", ["--control-allow-input-drift"])
    assert r.returncode == 0, r.stderr
    out = os.path.join(root, "scratch-out")
    import json
    cov = json.load(open(os.path.join(out, "coverage.json")))
    assert cov["control_mode"]["enabled"] is True
    assert cov["control_mode"]["controls"] == ["--control-allow-input-drift"]
    assert os.path.isfile(os.path.join(out, pc.CONTROL_MARKER_FILE))
    assert {n: sha(os.path.join(pub, n)) for n in FILES} == before


def test_ordinary_scratch_publication_deterministic_and_unmarked(tmp_path):
    root, pub = make_fixture(tmp_path)
    shas = []
    for d in ("a", "b"):
        r = run_tool(root, d)
        assert r.returncode == 0, r.stderr
        shas.append({n: sha(os.path.join(root, d, n)) for n in FILES})
        assert not os.path.exists(os.path.join(root, d, pc.CONTROL_MARKER_FILE))
        assert b"control_mode" not in open(
            os.path.join(root, d, "coverage.json"), "rb").read()
    assert shas[0] == shas[1]
    for n in FILES:  # same bytes as the committed publication
        assert shas[0][n] == sha(os.path.join(REPO, PUB, n))


def protected_output_intact(tool, tmp_path):
    """The protected-output check: a control run aimed at the fixture's normal
    publication directory must be refused with the publication bytes
    unchanged. Returns True when that holds."""
    os.makedirs(tmp_path)
    root, pub = make_fixture(tmp_path)
    before = {n: sha(os.path.join(pub, n)) for n in FILES}
    if tool is None:
        tool = TOOL
    else:  # bypassed copy lives in the fixture so its REPO_ROOT is the fixture
        os.makedirs(os.path.join(root, "bypassed"))
        with open(os.path.join(root, "bypassed", "publish_coverage.py"),
                  "w", encoding="utf-8") as f:
            f.write(tool)
        tool = os.path.join(root, "bypassed", "publish_coverage.py")
    r = run_tool(root, PUB, ["--control-allow-input-drift"], tool=tool)
    after = {n: sha(os.path.join(pub, n)) for n in FILES}
    return r.returncode != 0 and after == before


def test_failure_control_guard_bypassed_copy_fails_protected_output(tmp_path):
    """Live failure control: with the guard bypassed in a temporary source
    copy (isolated fixture tree only), the same protected-output check FAILS;
    with the real tool it passes."""
    call = "    controls = control_mode_guard(repo, args)\n"
    src = open(TOOL, encoding="utf-8").read()
    assert call in src
    bypassed = src.replace(
        call, "    controls = active_controls(args)  # guard bypassed\n", 1)
    assert protected_output_intact(None, tmp_path / "real") is True
    assert protected_output_intact(bypassed, tmp_path / "bypassed") is False
