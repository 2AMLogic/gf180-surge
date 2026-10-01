"""SXT-015 currency check: `reports/sxt-015/` must be what the tool emits now.

Issue #247. `reports/sxt-017/*` and `reports/sxt-020/*` each carry a test that
re-runs their generator and requires byte-equality with the committed export
(`test_committed_cost_closure_is_current`, `test_committed_artifacts_are_current`,
`test_scan_is_current_and_reconciles`). `reports/sxt-015/*` had none, so two
known deltas (SXT-012 fixture growth; the #117 Conditioner state promotion)
sat stale on `main` until the #239 re-export absorbed them by accident. This
module closes that gap in the same style.

Coverage (stated, not implied)
------------------------------
`tools/account_corpus.py` is re-run once, in full (all 3,561 graphs, worked
examples, negative controls), into a pytest temp dir, and EVERY file it emits
is required to be byte-identical to the committed copy under
`reports/sxt-015/`. The committed tree and the emitted tree must also hold the
same file set, so a stale orphan or an un-committed new artifact both fail.

Exactly one committed file is exempt, by name: `EVIDENCE.md`, the
hand-written evidence record. The tool does not emit it, so there is nothing
to compare it against; its prose is reviewed, not regenerated.

Runtime: one full tool run is ~4-5 s CPU (measured on the #247 build host:
4.6 s user; ~4 s wall with a warm page cache, ~23 s wall cold, dominated by
reading the 17 MB `graphs.jsonl`). The three sandbox controls below each add
one further scan with `--skip-negative-controls`, so the module costs four
scans: ~17 s CPU, ~31 s wall measured on the same host. No subset is sampled.

Decision: how the fixture-library input is treated
--------------------------------------------------
`fixtures/sequences/` is a growing library, and adding a fixture legitimately
moves `event_profile` without (usually) moving any cost. It is nevertheless
treated as a FIRST-CLASS input with NO tolerance window: a new fixture that
moves the export makes this check FAIL until the export is re-generated in
the same change. Reasons:

  * it is not cost-neutral by construction. The profile is handed to
    `account_graph`, whose `max_coincident_events > event_queue_depth` branch
    is an `event_queue_overflow` REJECTION, and its coincidence and rate
    fields are copied into every worked example's `account.events` (the
    fixture COUNT is not, so a fixture that leaves the peaks alone moves
    only `corpus-accounting.json`). A tolerance that ignored
    `event_profile` would also ignore the one fixture that flips a status;
  * the point of the export is that a reader can tell which inputs it was
    computed against. "Current except for fixtures" answers that question no
    better than having no check at all, which is how #247 arose;
  * the cost of strictness is one re-run of the tool in the fixture PR,
    which is cheap and deterministic.

To make that re-export reviewable rather than opaque, a failure on
`corpus-accounting.json` names the top-level keys that moved, so a
fixture-only re-export reads as `event_profile` (plus the examples'
`account.events`) and anything else is visibly something else. If a re-export
moves a status, fit count, rejection code or anomaly count, that movement is
enumerated in `reports/sxt-015/EVIDENCE.md` first (the #239 §8.3 pattern),
not folded into a hygiene change.

Claim scope: bookkeeping freshness only. No cycle, area, technology,
fidelity, preset-support or preset-quality claim; supported-preset delta 0.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "account_corpus.py")
SXT015 = os.path.join(REPO, "reports", "sxt-015")

# committed files under reports/sxt-015/ that the tool does NOT emit, each
# with the reason it is exempt from byte-equality
EXEMPT = {
    "EVIDENCE.md": "hand-written evidence record; not a tool output",
}


def _tree(root):
    """Relative paths of every file under root (sorted, posix separators)."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _run_tool(tool, outdir, *extra):
    r = subprocess.run([sys.executable, tool, "--outdir", str(outdir), *extra],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def _moved_keys(emitted, committed):
    """Top-level JSON keys whose value differs (diagnostic only)."""
    a = json.loads(open(emitted).read())
    b = json.loads(open(committed).read())
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def stale_artifacts(emitted_root, committed_root, emitted_only=False):
    """Every way the committed export differs from a fresh emission.

    Returns a sorted list of human-readable findings; empty means current.
    `emitted_only=True` restricts the comparison to files the run emitted
    (used by the failure controls, which skip the negative-control stage).
    """
    emitted = set(_tree(emitted_root))
    committed = set(_tree(committed_root)) - set(EXEMPT)
    findings = []
    if not emitted_only:
        for rel in sorted(committed - emitted):
            findings.append("%s: committed but no longer emitted" % rel)
        for rel in sorted(emitted - committed):
            findings.append("%s: emitted but not committed" % rel)
    for rel in sorted(emitted & committed):
        e = os.path.join(emitted_root, rel)
        c = os.path.join(committed_root, rel)
        if open(e, "rb").read() == open(c, "rb").read():
            continue
        detail = ""
        if rel.endswith(".json"):
            detail = " (top-level keys moved: %s)" % ", ".join(
                _moved_keys(e, c))
        findings.append("%s: stale%s" % (rel, detail))
    return findings


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    out = tmp_path_factory.mktemp("sxt015-regen")
    _run_tool(TOOL, out)
    return str(out)


def test_exempt_files_exist_and_are_not_emitted(emitted):
    """An exemption must name a real committed file the tool does not write;
    otherwise it is a silent hole in the check."""
    for rel in EXEMPT:
        assert os.path.isfile(os.path.join(SXT015, rel)), rel
        assert not os.path.exists(os.path.join(emitted, rel)), \
            "%s is emitted by the tool; it must not be exempt" % rel


def test_committed_sxt015_export_is_current(emitted):
    findings = stale_artifacts(emitted, SXT015)
    assert not findings, (
        "committed reports/sxt-015/ is stale; re-run "
        "`python3 tools/account_corpus.py` (and enumerate any status / fit / "
        "rejection / anomaly movement in reports/sxt-015/EVIDENCE.md first):\n  "
        + "\n  ".join(findings))


# --- live failure controls (issue #247) -------------------------------------
# Each control builds a sandbox copy of exactly the tool's inputs, applies ONE
# mutation, re-runs the tool there, and requires the comparison above to
# report the committed export stale. A check that stayed green through either
# mutation would not be detecting staleness.

def _sandbox(tmp_path):
    sb = tmp_path / "repo"
    (sb / "tools").mkdir(parents=True)
    shutil.copy2(TOOL, sb / "tools" / "account_corpus.py")
    shutil.copytree(os.path.join(REPO, "model", "resources"),
                    sb / "model" / "resources",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(REPO, "fixtures", "sequences"),
                    sb / "fixtures" / "sequences")
    # large read-only inputs: symlinked, never written by the tool
    for rel in ("corpus/normalized/graphs.jsonl",
                "corpus/census-v0.1/results/per-preset.csv"):
        dst = sb / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.join(REPO, rel), dst)
    return sb


def _control(sb, tmp_path):
    out = tmp_path / "out"
    _run_tool(str(sb / "tools" / "account_corpus.py"), out,
              "--skip-negative-controls")
    return stale_artifacts(str(out), SXT015, emitted_only=True)


def test_control_unmutated_sandbox_is_current(tmp_path):
    """The sandbox itself must not introduce drift, or the two mutation
    controls below would pass for the wrong reason."""
    assert _control(_sandbox(tmp_path), tmp_path) == []


def test_control_adding_one_sequence_fixture_makes_the_check_fail(tmp_path):
    sb = _sandbox(tmp_path)
    seqdir = sb / "fixtures" / "sequences"
    src = sorted(p for p in seqdir.iterdir() if p.suffix == ".json")[0]
    shutil.copy2(src, seqdir / "zz-nc-247-added-fixture.json")
    findings = _control(sb, tmp_path)
    assert any(f.startswith("corpus-accounting.json: stale")
               and "event_profile" in f for f in findings), findings


def test_control_flipping_one_fx_class_state_row_makes_the_check_fail(tmp_path):
    """Revert the #117 promotion in the sandbox: Conditioner falls back to the
    shared placeholder and regains `class_state_unverified`."""
    sb = _sandbox(tmp_path)
    fx = sb / "model" / "resources" / "fx_classes.py"
    src = fx.read_text()
    needle = '    "Conditioner": {\n        "leaf": "SXT-028b",'
    assert src.count(needle) == 1, "control mutation no longer applies"
    fx.write_text(src.replace(
        needle, '    "Conditioner-NC-247-unmeasured": {\n'
                '        "leaf": "SXT-028b",'))
    findings = _control(sb, tmp_path)
    assert any(f.startswith("corpus-accounting.json: stale")
               and "anomaly_code_counts" in f for f in findings), findings
