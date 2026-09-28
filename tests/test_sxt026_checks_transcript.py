"""Issue #203: the SXT-026 acceptance-script transcripts must carry the
`stimulus_lengths` status the verdict JSON has recorded since #194.

`tools/run_sxt026_checks.py` step 6 (`rtl-exactness.txt`) and step 7
(`sustained-concurrent.txt`) call `tools/compare_wt_rtl_model.py`, whose
verdict JSON has carried a `stimulus_lengths` field since #194: whether every
`rtl/*.hex` stimulus file's word count matched the model's own declaration
(mechanism 5 of that harness's docstring -- a file that opens but is
TRUNCATED). Before this issue, both transcript writers built their lines from
a hand-picked subset of the verdict (`verdict`, `mismatches`, `checked`) that
discarded `stimulus_lengths` entirely, so the committed artifact a reader
actually sees could not say whether its own stimulus was complete.

Scope of these controls, same as `tests/test_sxt026_wt_rtl_harness.py`: the
RENDERING path only. Neither `run_model.py --rtl` nor iverilog/vvp nor the
external pinned asset tree is invoked here, so nothing in this file is
evidence about the RTL, the frozen model, or their agreement -- the
end-to-end exactness run that produces the committed
`reports/sxt-026/artifacts/rtl-exactness.txt` and
`sustained-concurrent.txt` is steps 6-7 of `tools/run_sxt026_checks.py`
itself, which need the pinned asset tree (see this issue's PR body for what
was and was not regenerated).
"""

import importlib.util
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = os.path.join(REPO, "tools", "run_sxt026_checks.py")
COMPARATOR = os.path.join(REPO, "tools", "compare_wt_rtl_model.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_checks():
    return _load(CHECKS, "sxt026_run_checks")


def _load_comparator():
    return _load(COMPARATOR, "sxt026_compare_wt_rtl_model_for_checks_test")


# Reduced local copy of the comparator test's STIMULUS-derived fixture, kept
# in sync structurally (both read the comparator's own `STIMULUS` table
# rather than hard-coding file names) so a change to the declared stimulus
# set cannot silently desync the two test files.
_COMPARATOR = _load_comparator()
STIMULUS_RELPATHS = [rel for _, rel in _COMPARATOR.STIMULUS]
FIXTURE_WORDS = dict(zip(STIMULUS_RELPATHS, (4, 3, 8, 6, 6)))


def _write_hex(path, n_words):
    with open(path, "w") as f:
        for w in range(n_words):
            f.write("%08x\n" % w)


def _write_run_dir(tmp_path, stimulus_index=True, words=None):
    """A run dir with real (if short) stimulus content and its declared
    index -- enough for `check_stimulus_lengths()` alone; no `model_trace
    .json` blocks or simulator output are needed since this file never
    invokes the comparator's simulator path, only its length check."""
    run_dir = str(tmp_path)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    words = dict(FIXTURE_WORDS if words is None else words)
    for rel in STIMULUS_RELPATHS:
        _write_hex(os.path.join(run_dir, rel), words[rel])
    if stimulus_index:
        with open(os.path.join(run_dir, "rtl/stimulus_index.json"), "w") as f:
            json.dump({"format": "sxt026-wt-stimulus-index/1",
                       "files": dict(FIXTURE_WORDS)}, f)
    return run_dir


# --------------------------------------------------------------------------
# stimulus_lengths_lines(): the rendering function itself
# --------------------------------------------------------------------------


def test_pass_line_states_the_status_explicitly():
    mod = _load_checks()
    sl = {"status": "PASS", "declared_by": "rtl/stimulus_index.json",
          "reason": "all 5 stimulus files match the length the model "
                    "declared",
          "words": {rel: {"declared": n, "actual": n}
                    for rel, n in FIXTURE_WORDS.items()}}
    lines = mod.stimulus_lengths_lines("base", sl)
    assert lines, "a PASS run must not render to no lines at all"
    assert any("stimulus_lengths: PASS" in l for l in lines), lines
    assert any("base" in l for l in lines), lines


def test_fail_line_names_the_truncated_file_and_both_counts():
    mod = _load_checks()
    comparator = _load_comparator()
    run_dir_words = dict(FIXTURE_WORDS)
    truncated_rel = STIMULUS_RELPATHS[2]  # rtl/wt_table.hex by convention
    run_dir_words[truncated_rel] //= 2

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run_dir = _write_run_dir(td, words=run_dir_words)
        sl, fails = comparator.check_stimulus_lengths(run_dir)

    assert sl["status"] == "FAIL", sl
    lines = mod.stimulus_lengths_lines("mutant(mip-thr2)", sl)
    joined = "\n".join(lines)
    assert "stimulus_lengths: FAIL" in joined, joined
    assert truncated_rel in joined, joined
    declared = FIXTURE_WORDS[truncated_rel]
    actual = run_dir_words[truncated_rel]
    assert "declared=%d" % declared in joined, joined
    assert "actual=%d" % actual in joined, joined
    # every OTHER file must not be misreported as mismatching
    for rel in STIMULUS_RELPATHS:
        if rel != truncated_rel:
            assert ("mismatch: %s" % rel) not in joined, (rel, joined)


def test_not_run_line_states_not_run_and_the_reason_not_silence():
    """Outcome checklist item 2: a NOT_RUN verdict must not print nothing --
    the transcript states NOT_RUN explicitly, with the harness's own reason,
    rather than silently omitting the field (which would read as "fine")."""
    mod = _load_checks()
    comparator = _load_comparator()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run_dir = _write_run_dir(td, stimulus_index=False)
        sl, fails = comparator.check_stimulus_lengths(run_dir)

    assert sl["status"] == "NOT_RUN", sl
    lines = mod.stimulus_lengths_lines("base", sl)
    joined = "\n".join(lines)
    assert "stimulus_lengths: NOT_RUN" in joined, joined
    assert "NOT a pass" in joined, joined  # the comparator's own reason text


def test_failure_control_truncated_vs_untouched_are_not_byte_identical():
    """The issue's own Failure control, restated at the rendering level:
    with exactly one stimulus file truncated, the rendered lines must state
    the failure and name the file; with the same run dir untouched, they
    must state PASS. The two renderings must not be byte-identical."""
    mod = _load_checks()
    comparator = _load_comparator()
    import tempfile

    base = tempfile.mkdtemp()
    good_dir = os.path.join(base, "good")
    bad_dir = os.path.join(base, "bad")
    os.makedirs(good_dir)
    os.makedirs(bad_dir)
    _write_run_dir(good_dir)
    bad_words = dict(FIXTURE_WORDS)
    bad_words[STIMULUS_RELPATHS[2]] //= 2
    _write_run_dir(bad_dir, words=bad_words)

    good_sl, _ = comparator.check_stimulus_lengths(good_dir)
    bad_sl, _ = comparator.check_stimulus_lengths(bad_dir)

    good_lines = "\n".join(mod.stimulus_lengths_lines("base", good_sl))
    bad_lines = "\n".join(mod.stimulus_lengths_lines("base", bad_sl))

    assert good_lines != bad_lines, (
        "the transcript rendering is byte-identical between a truncated "
        "and an untouched run dir -- this is exactly what the issue #203 "
        "failure control forbids")
    assert "stimulus_lengths: PASS" in good_lines, good_lines
    assert "stimulus_lengths: FAIL" in bad_lines, bad_lines
    assert STIMULUS_RELPATHS[2] in bad_lines, bad_lines


# --------------------------------------------------------------------------
# structural: both writers in tools/run_sxt026_checks.py must actually call
# the renderer and fold its output into the lines they write, not merely
# define it unused.
# --------------------------------------------------------------------------


def _read(path):
    with open(path) as f:
        return f.read()


def test_step6_writer_calls_the_renderer_before_writing_the_file():
    code = _read(CHECKS)
    # step 6 builds `lines` and then writes rtl-exactness.txt from it
    m = re.search(
        r'lines = \[\](.*?)with open\(os\.path\.join\(ART, '
        r'"rtl-exactness\.txt"\), "w"\) as f:', code, re.S)
    assert m, "could not locate step 6's lines-building block in " \
              "tools/run_sxt026_checks.py; has it been restructured?"
    step6_body = m.group(1)
    assert "stimulus_lengths_lines(" in step6_body, (
        "step 6 no longer calls stimulus_lengths_lines() before writing "
        "rtl-exactness.txt -- the transcript would again discard the "
        "verdict's stimulus_lengths field (issue #203)")
    assert 'd["stimulus_lengths"]' in step6_body, step6_body


def test_step7_writer_calls_the_renderer_before_writing_the_file():
    code = _read(CHECKS)
    m = re.search(
        r'lines7 = \[(.*?)with open\(os\.path\.join\(ART, '
        r'"sustained-concurrent\.txt"\), "w"\) as f:', code, re.S)
    assert m, "could not locate step 7's lines7-building block in " \
              "tools/run_sxt026_checks.py; has it been restructured?"
    step7_body = m.group(1)
    assert "stimulus_lengths_lines(" in step7_body, (
        "step 7 no longer calls stimulus_lengths_lines() before writing "
        "sustained-concurrent.txt -- the transcript would again discard "
        "the verdict's stimulus_lengths field (issue #203)")
    assert 'd["stimulus_lengths"]' in step7_body, step7_body


def test_renderer_is_the_single_place_both_steps_use():
    """Both call sites must go through the same function, so the two
    writers cannot drift apart in what they consider a complete report."""
    code = _read(CHECKS)
    assert code.count("def stimulus_lengths_lines(") == 1, (
        "exactly one renderer is expected; a second copy could drift")
    assert code.count("stimulus_lengths_lines(") >= 3, (
        "expected the definition plus at least one call from each of "
        "step 6 and step 7")
