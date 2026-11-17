"""Live failure controls for the two policies `.github/workflows/ci.yml`'
header states: every job carries `timeout-minutes`, and every third-party
`uses:` is pinned to a full commit SHA with the tag it was resolved from in
a trailing comment (#730).

What this pins, and what it does NOT:

  * PINS: across `.github/workflows/*.yml` and `*.yaml`, each job block
    under `jobs:` contains a job-level `    timeout-minutes:` with an
    integer value, except a `jobs.<id>.uses:` reusable-workflow-call job
    (GitHub rejects `timeout-minutes` on the calling side; the called
    workflow's own jobs carry the bound), and
    each `uses:` value is `owner/repo[/subpath]@<40 lowercase hex>` followed
    by ` # v<N>`-style tag comment. Local `./`-relative `uses:` are exempt
    (none exist today).
  * DOES NOT: run any workflow, verify a SHA against the upstream tag (the
    comment is not cross-checked), or bound what the jobs do. This is the
    documented-policy failure control only: it makes the next unpinned or
    unbounded job red in CI instead of silent.

Both policies were documented in the ci.yml header with no live check, which
is how `rtl-lint` drifted out of both (#730). The negative controls below
re-run the same scans over doctored copies of the real workflows and must
find the defects, so the scans cannot pass vacuously.

Textual parsing on purpose: CI's pytest job installs numpy and pytest only
(requirements-ci.txt), so no YAML dependency is added here; the block model
is the same one `tests/test_rtl_ci_step_errexit.py` uses for its step
extraction.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(.+?)\s*$")
PINNED_USES_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\s]+)?"   # owner/repo[/subpath]
    r"@[0-9a-f]{40}"                                   # full commit SHA
    r"\s+#\s*v[0-9][A-Za-z0-9.\-]*$"                   # trailing tag comment
)
JOB_RE = re.compile(r"^  ([^\s#][^\s]*):\s*(?:#.*)?$")
JOB_TIMEOUT_RE = re.compile(r"^    timeout-minutes:\s*([0-9]+)\s*$")
# A job's own 4-space `uses:` key marks it a reusable-workflow-call job.
# Deeper indents (a step's `      - uses:`) do not match.
JOB_USES_RE = re.compile(r"^    uses:\s*\S")


def iter_job_blocks(text):
    """Yield (job_id, [lines]) for each job under a top-level `jobs:` key.

    A job starts at exactly two-space indent under `jobs:`; its block is the
    following lines until the next two-space-indented key or a column-0 key.
    """
    lines = text.splitlines()
    in_jobs = False
    current = None
    for line in lines:
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" "):
            # Column-0 key: the jobs section ended.
            if current:
                yield current
            current = None
            in_jobs = False
            continue
        if line.startswith("  ") and not line.startswith("   ") and JOB_RE.match(line):
            if current:
                yield current
            current = (JOB_RE.match(line).group(1), [line])
        elif current is not None:
            current[1].append(line)
    if current:
        yield current


def scan_timeout_policies(text, source="<text>"):
    """Findings: jobs with no job-level `timeout-minutes: <int>`.

    A `jobs.<id>.uses:` reusable-workflow-call job is exempt: GitHub does
    not accept `timeout-minutes` on the calling side, so the called
    workflow's own jobs carry the bound.
    """
    findings = []
    for job_id, block in iter_job_blocks(text):
        if any(JOB_USES_RE.match(line) for line in block):
            continue
        values = [JOB_TIMEOUT_RE.match(line) for line in block]
        values = [m.group(1) for m in values if m]
        if not values:
            findings.append(f"{source}: job {job_id!r} has no job-level timeout-minutes")
    return findings


def scan_use_pins(text, source="<text>"):
    """Findings: `uses:` values that are neither local nor SHA+tag pinned."""
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        m = USES_RE.match(line)
        if not m:
            continue
        ref = m.group(1)
        if ref.startswith("./"):
            continue
        if not PINNED_USES_RE.match(ref):
            findings.append(f"{source}:{line_no}: uses: {ref!r} is not SHA-pinned with a tag comment")
    return findings


def workflow_texts(workflow_dir=None, root=None):
    """(relative name, text) for every `*.yml` and `*.yaml` workflow.

    `workflow_dir`/`root` default to the repo's `.github/workflows/` and
    repo root; the negative controls pass a temp dir so they never touch
    the real workflows.
    """
    workflow_dir = WORKFLOW_DIR if workflow_dir is None else Path(workflow_dir)
    root = ROOT if root is None else Path(root)
    paths = sorted(p for pattern in ("*.yml", "*.yaml")
                   for p in workflow_dir.glob(pattern))
    assert paths, f"no workflow files found under {workflow_dir}"
    return [(p.relative_to(root).as_posix(), p.read_text(encoding="utf-8")) for p in paths]


# ------------------------------------------------------------ live policies
def test_every_workflow_job_has_timeout():
    findings = []
    for source, text in workflow_texts():
        findings.extend(scan_timeout_policies(text, source))
    assert not findings, "\n".join(findings)


def test_every_third_party_use_is_sha_pinned():
    findings = []
    for source, text in workflow_texts():
        findings.extend(scan_use_pins(text, source))
    assert not findings, "\n".join(findings)


# -------------------------------------------------------- negative controls
def test_negative_control_unpinned_use_is_found():
    """A real workflow with one uses: tag-pinned instead of SHA-pinned fails."""
    source, text = workflow_texts()[0]
    unpinned = None
    for line in text.splitlines():
        m = USES_RE.match(line)
        if m and PINNED_USES_RE.match(m.group(1)):
            unpinned = (line, m.group(1))
            break
    assert unpinned, "no pinned uses: found to doctor"
    line, ref = unpinned
    doctored = text.replace(line, line.replace(ref, ref.split("@")[0] + "@v4"), 1)
    findings = scan_use_pins(doctored, source)
    assert findings, "scan did not detect an unpinned uses: (control is vacuous)"
    assert "@v4" in findings[0]


def test_negative_control_job_without_timeout_is_found():
    """A real workflow with one job's timeout-minutes line removed fails."""
    source, text = workflow_texts()[0]
    line = None
    for candidate in text.splitlines():
        if JOB_TIMEOUT_RE.match(candidate):
            line = candidate
            break
    assert line is not None, "no job-level timeout-minutes found to doctor"
    doctored = text.replace(line, "", 1)
    findings = scan_timeout_policies(doctored, source)
    assert findings, "scan did not detect a job without timeout-minutes (control is vacuous)"


def test_negative_control_yaml_workflow_is_scanned(tmp_path):
    """A timeout defect in a `.yaml` workflow (not `.yml`) is found.

    Fails against a `*.yml`-only glob: the `.yaml` file is never read.
    """
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "nw.yaml").write_text(
        "jobs:\n"
        "  slow:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo hi\n",
        encoding="utf-8",
    )
    texts = workflow_texts(workflow_dir=wf_dir, root=wf_dir)
    assert [name for name, _ in texts] == ["nw.yaml"], texts
    findings = []
    for name, text in texts:
        findings.extend(scan_timeout_policies(text, name))
    assert findings, "scan did not detect a defect inside a .yaml workflow (control is vacuous)"
    assert "nw.yaml" in findings[0]


def test_yaml_and_yml_of_one_stem_are_both_scanned(tmp_path):
    """`ci.yml` and `ci.yaml` coexist: both are read, both checked."""
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    good = (
        "jobs:\n"
        "  ok:\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 10\n"
        "    steps:\n"
        "      - run: echo hi\n"
    )
    (wf_dir / "ci.yml").write_text(good, encoding="utf-8")
    (wf_dir / "ci.yaml").write_text(
        good.replace("    timeout-minutes: 10\n", ""), encoding="utf-8"
    )
    texts = workflow_texts(workflow_dir=wf_dir, root=wf_dir)
    assert [name for name, _ in texts] == ["ci.yaml", "ci.yml"], texts
    findings = []
    for name, text in texts:
        findings.extend(scan_timeout_policies(text, name))
    assert findings == ["ci.yaml: job 'ok' has no job-level timeout-minutes"], findings


def test_subpath_action_pin_is_accepted():
    """`owner/repo/sub@<40hex> # vN` (one-slash subpath) is pinned."""
    for ref in (
        "actions/cache/restore@0057852bfaa89a56745cba8c7296529d2fc39830 # v4",
        "github/codeql-action/analyze@"
        "0000000000000000000000000000000000000000 # v3",
    ):
        assert PINNED_USES_RE.match(ref), f"pinned subpath rejected: {ref!r}"
        findings = scan_use_pins(f"      - uses: {ref}\n", "<text>")
        assert findings == [], findings


def test_negative_control_subpath_unpinned_is_found():
    """A subpath action pinned only by tag still fails the scan."""
    ref = "actions/cache/restore@v4"
    findings = scan_use_pins(f"      - uses: {ref}\n", "<text>")
    assert findings, "scan did not detect an unpinned subpath uses: (control is vacuous)"
    assert "@v4" in findings[0]


def test_reusable_workflow_call_job_needs_no_timeout():
    """A `uses:` job is exempt from timeout-minutes; a plain job is not."""
    text = (
        "jobs:\n"
        "  call:\n"
        "    uses: acme/infra/.github/workflows/ci.yml@0057852bfaa89a56745cba8c7296529d2fc39830\n"
        "    with:\n"
        "      target: lint\n"
        "  plain:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo hi\n"
    )
    findings = scan_timeout_policies(text, "<text>")
    assert findings == [
        "<text>: job 'plain' has no job-level timeout-minutes"
    ], findings
