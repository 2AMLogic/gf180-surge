"""`tools/_rtl_compile_common.run_leaf_comparison` tests (issue #303).

Issue #303 extracted the report-assembly skeleton five RTL-vs-frozen-model
leaves had copied verbatim (`compare_rtl_model.py`,
`compare_classic_rtl_model.py`, `compare_kt_rtl_model.py`,
`compare_lfo_rtl_model.py`, `compare_mw_rtl_model.py`) into one shared
helper.  The stated risk of that extraction is that a bug in the shared
skeleton moves five leaves' PASS/FAIL reporting at once instead of one, so
this file pins the skeleton's own contract:

  * the published summary key set, key order, exit code and `--out` bytes;
  * the `comparison: NOT_RUN` branch -- a simulator-level failure must not
    run the leaf's `compare` at all (issues #188/#193), and must report the
    leaf's own zeroed `checked` dict verbatim rather than a normalized one;
  * the per-leaf divergences the helper must NOT flatten: the `tb` label
    (basename for the SXT-022 voice leaf, repo-relative for the other four),
    the `checked` shape, and the keytrack leaf's four extra summary fields
    reported INTERLEAVED among the shared ones;
  * two drift guards, each exercised by a control that must raise: a
    `summary_key_order` that does not name exactly the merged key set (which
    would silently drop or re-order a reported field), and a caller trying
    to pass `report_sim_fails` itself (which would feed the NOT_RUN branch
    something that is not a `SimResult`).

The simulator is never invoked here: `compile_and_run` is replaced by a stub
returning a chosen `SimResult` (or, for the issue #360 current-output
controls, the real `compile_and_run` runs against a stubbed `subprocess`), because what is under test is the report
assembly, not the compile/run step (that has its own coverage in
`test_rtl_compile_common.py`) and not any leaf's trace format or comparison
semantics (each leaf's own test file owns those).  Nothing here is evidence
about the RTL, the frozen model, or their agreement.
"""

import io
import json
import os
import subprocess
import sys
import types
from contextlib import redirect_stdout

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402

MODEL_TRACE = {"sequence": "test-seq", "control_mode": "normal",
               "blocks": [{"b": 0, "voices": []}, {"b": 1, "voices": []}]}

# The five leaves #303 deduplicated, and the three it deliberately did not
# (verified divergent in the issue body: a `--trace` reuse branch, no shared
# import at all, and a 187-line `main()` with its own flag set).
DEDUPED_LEAVES = ("compare_rtl_model", "compare_classic_rtl_model",
                  "compare_kt_rtl_model", "compare_lfo_rtl_model",
                  "compare_mw_rtl_model")
EXCLUDED_LEAVES = ("compare_sine_rtl_model", "compare_vel_rtl_model",
                   "compare_wt_rtl_model")


def _write_trace(tmp_path):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(MODEL_TRACE, f)
    return run_dir


def _stub_sim(monkeypatch, *, sim_fails=(), value=7, stdout_tail=""):
    """Replace the compile/run step with a fixed SimResult."""
    seen = {}

    def fake(sv_file, workdir, **kwargs):
        seen["sv_file"] = sv_file
        seen["workdir"] = workdir
        seen["kwargs"] = kwargs
        return rcc.SimResult(os.path.join(workdir, "trace.txt"), value,
                             "stdout text", list(sim_fails), stdout_tail)

    monkeypatch.setattr(rcc, "compile_and_run", fake)
    return seen


def _run(run_dir, *, out=None, parse_tb=None, compare=None,
         default_checked=None, **kw):
    """Call the helper, returning (rc, printed_text, key_order, summary)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = rcc.run_leaf_comparison(
            tb="/somewhere/tb_thing.sv", tb_label="rtl/thing/tb_thing.sv",
            run_dir=run_dir, out=out,
            parse_tb=parse_tb if parse_tb else (lambda path: "parsed"),
            compare=compare if compare else (lambda mt, rt: ({"f": 2}, [])),
            compile_kwargs=kw.pop("compile_kwargs", {"out_name": "tb.vvp"}),
            default_checked=(default_checked if default_checked is not None
                             else {"f": 0}),
            **kw)
    text = buf.getvalue()
    pairs = json.loads(text, object_pairs_hook=lambda ps: ps)
    return rc, text, [k for k, _ in pairs], json.loads(text)


# --------------------------------------------------------------------------
# The published report shape
# --------------------------------------------------------------------------


def test_passing_comparison_reports_pass_and_exit_zero(tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)

    rc, _, order, d = _run(run_dir)

    assert rc == 0
    assert order == ["tb", "verdict", "comparison", "checked", "mismatches",
                     "first_failures", "sim_fails", "sim_stdout_tail"]
    assert d["tb"] == "rtl/thing/tb_thing.sv"
    assert d["verdict"] == "PASS"
    assert d["comparison"] == "PASS"
    assert d["checked"] == {"f": 2}
    assert d["mismatches"] == 0
    assert d["first_failures"] == []
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""


def test_disagreement_is_a_fail_with_first_ten_failures(tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    fails = ["mismatch %d" % i for i in range(25)]

    rc, _, _, d = _run(run_dir, compare=lambda mt, rt: ({"f": 9}, fails))

    assert rc == 1
    assert d["verdict"] == "FAIL"
    assert d["comparison"] == "FAIL"
    assert d["mismatches"] == 25
    assert d["first_failures"] == fails[:10]
    assert d["sim_fails"] == []          # not a simulator-level failure


def test_out_file_matches_stdout_and_ends_with_a_newline(tmp_path,
                                                         monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "verdict.json")

    rc, text, _, _ = _run(run_dir, out=out)

    with open(out) as f:
        written = f.read()
    assert rc == 0
    assert written == text                     # same bytes, same key order
    assert written.endswith("}\n")


def test_without_out_nothing_is_written(tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)

    _run(run_dir, out=None)

    assert sorted(os.listdir(run_dir)) == ["model_trace.json"]


def test_compile_kwargs_reach_the_compile_step_verbatim(tmp_path,
                                                        monkeypatch):
    run_dir = _write_trace(tmp_path)
    seen = _stub_sim(monkeypatch)

    _run(run_dir, compile_kwargs={"out_name": "tb_kt.vvp", "absolute": True,
                                  "done_prefix": "DONE kt-qmuls=",
                                  "stimulus_files": ("rtl/a.hex",)})

    assert seen["sv_file"] == "/somewhere/tb_thing.sv"
    assert seen["workdir"] == run_dir
    # report_sim_fails is the helper's, every other axis is the leaf's
    assert seen["kwargs"] == {"report_sim_fails": True,
                              "out_name": "tb_kt.vvp", "absolute": True,
                              "done_prefix": "DONE kt-qmuls=",
                              "stimulus_files": ("rtl/a.hex",)}


# --------------------------------------------------------------------------
# A simulator-level failure is NOT a comparison disagreement (#188, #193)
# --------------------------------------------------------------------------


def test_sim_failure_is_not_run_and_never_calls_compare(tmp_path,
                                                        monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch, sim_fails=["missing declared input: rtl/a.hex"],
              value=None, stdout_tail="ERROR: ... Unable to open rtl/a.hex")
    called = []

    rc, _, _, d = _run(
        run_dir,
        parse_tb=lambda path: called.append("parse_tb"),
        compare=lambda mt, rt: called.append("compare") or ({"f": 1}, []),
        default_checked={"lfo_checkpoints": 0, "lfo_fields": 0,
                         "route_sums": 0})

    assert called == [], called
    assert rc == 1
    assert d["verdict"] == "FAIL"
    assert d["comparison"] == "NOT_RUN"
    assert d["sim_fails"] == ["missing declared input: rtl/a.hex"]
    assert d["mismatches"] == 1          # the sim failure, not a mismatch
    assert "Unable to open" in d["sim_stdout_tail"]
    # the LEAF's zeroed checked dict, reported verbatim and in its own order
    assert list(d["checked"]) == ["lfo_checkpoints", "lfo_fields",
                                  "route_sums"]
    assert set(d["checked"].values()) == {0}


def test_default_checked_is_not_mutated_across_runs(tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch, sim_fails=["boom"])
    default_checked = {"mw_values": 0, "route_sum_checkpoints": 0}

    _run(run_dir, default_checked=default_checked)

    assert default_checked == {"mw_values": 0, "route_sum_checkpoints": 0}


# --------------------------------------------------------------------------
# Issue #360: a trace this invocation did not produce never reaches the leaf
# --------------------------------------------------------------------------
#
# These drive the REAL `compile_and_run` (reporting mode) through the
# wrapper, with only `subprocess` stubbed: iverilog "succeeds", and vvp exits
# 0 after optionally writing `fresh_trace` to the expected path. That keeps
# the missing-current-output decision inside the helper under test rather
# than in a hand-picked SimResult.

STALE_PASSING_TRACE = "a previous invocation's passing trace\n"


def _stub_subprocess(monkeypatch, run_dir, fresh_trace):
    vvp_calls = []

    def fake_run(cmd, **kwargs):
        if cmd[0] == "iverilog":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        vvp_calls.append(cmd)
        if fresh_trace is not None:
            with open(os.path.join(run_dir, "tb_trace.txt"), "w") as f:
                f.write(fresh_trace)
        return types.SimpleNamespace(returncode=0, stdout="DONE\n",
                                     stderr="")

    monkeypatch.setattr(rcc, "subprocess", types.SimpleNamespace(
        run=fake_run, DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired))
    return vvp_calls


@pytest.mark.parametrize("preseed", [False, True],
                         ids=["empty-dir", "stale-passing-trace"])
def test_missing_current_output_is_not_run_and_never_parses(
        tmp_path, monkeypatch, preseed):
    """Both no-output controls: exit 0, no trace written by this run. The
    stale case pre-seeds a trace the leaf's own parse/compare would PASS;
    it must be rejected identically to the empty dir, never parsed."""
    run_dir = _write_trace(tmp_path)
    trace = os.path.join(run_dir, "tb_trace.txt")
    if preseed:
        with open(trace, "w") as f:
            f.write(STALE_PASSING_TRACE)
    vvp_calls = _stub_subprocess(monkeypatch, run_dir, fresh_trace=None)
    called = []

    def parse_tb(path):
        called.append("parse_tb")
        with open(path) as f:
            return f.read()

    def compare(mt, rt):
        called.append("compare")
        return {"f": 1}, ([] if rt == STALE_PASSING_TRACE else ["differs"])

    rc, _, order, d = _run(
        run_dir, parse_tb=parse_tb, compare=compare,
        compile_kwargs={"out_name": "tb.vvp", "trace_name": "tb_trace.txt"},
        default_checked={"checkpoints": 0, "fields": 0})

    assert len(vvp_calls) == 1          # the simulator really did run
    assert called == [], called
    assert rc == 1
    assert d["verdict"] == "FAIL"
    assert d["comparison"] == "NOT_RUN"
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert d["sim_fails"][0].startswith(
        "missing current-run output: tb_trace.txt"), d["sim_fails"]
    assert d["mismatches"] == 1
    assert d["checked"] == {"checkpoints": 0, "fields": 0}
    assert list(d["checked"]) == ["checkpoints", "fields"]
    assert order == ["tb", "verdict", "comparison", "checked", "mismatches",
                     "first_failures", "sim_fails", "sim_stdout_tail"]
    assert not os.path.exists(trace)    # the stale trace was invalidated


def test_fresh_trace_is_the_one_parsed_over_a_stale_one(tmp_path,
                                                        monkeypatch):
    """Healthy path: a stale passing trace is pre-seeded, the current run
    writes a different (disagreeing) one. The leaf must see the CURRENT
    content -- FAIL -- proving the stale trace cannot mask a fresh result."""
    run_dir = _write_trace(tmp_path)
    with open(os.path.join(run_dir, "tb_trace.txt"), "w") as f:
        f.write(STALE_PASSING_TRACE)
    _stub_subprocess(monkeypatch, run_dir, fresh_trace="fresh, disagrees\n")
    seen = []

    def parse_tb(path):
        with open(path) as f:
            seen.append(f.read())
        return seen[-1]

    rc, _, _, d = _run(
        run_dir, parse_tb=parse_tb,
        compare=lambda mt, rt: ({"f": 1},
                                [] if rt == STALE_PASSING_TRACE
                                else ["differs"]),
        compile_kwargs={"out_name": "tb.vvp", "trace_name": "tb_trace.txt"})

    assert seen == ["fresh, disagrees\n"]
    assert rc == 1
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []


# --------------------------------------------------------------------------
# Per-leaf divergences the helper must not flatten
# --------------------------------------------------------------------------


def test_extra_summary_fields_keep_their_interleaved_order(tmp_path,
                                                           monkeypatch):
    """The keytrack leaf's published shape: `sequence`/`control_mode` after
    `tb`, `rtl_qmuls`/`blocks` after `checked` -- not appended at the end."""
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch, value=180126)
    order = ("tb", "sequence", "control_mode", "verdict", "comparison",
             "checked", "rtl_qmuls", "blocks", "mismatches",
             "first_failures", "sim_fails", "sim_stdout_tail")

    rc, _, got_order, d = _run(
        run_dir,
        extra_summary_fields=lambda mt, sim: {
            "sequence": mt.get("sequence"),
            "control_mode": mt.get("control_mode"),
            "rtl_qmuls": sim.value,
            "blocks": len(mt["blocks"]),
        },
        summary_key_order=order)

    assert rc == 0
    assert got_order == list(order)
    assert d["sequence"] == "test-seq"
    assert d["control_mode"] == "normal"
    assert d["rtl_qmuls"] == 180126
    assert d["blocks"] == 2


def test_extra_fields_without_an_order_are_appended(tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)

    _, _, order, _ = _run(run_dir,
                          extra_summary_fields=lambda mt, sim: {"extra": 1})

    assert order[-1] == "extra"


# --------------------------------------------------------------------------
# Controls: each drift guard must demonstrably fire
# --------------------------------------------------------------------------


def test_control_summary_key_order_missing_a_key_raises(tmp_path,
                                                        monkeypatch):
    """A published field silently dropped from the report must not be
    possible: an order that omits `sim_fails` is refused, not honored."""
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    order = ("tb", "verdict", "comparison", "checked", "mismatches",
             "first_failures", "sim_stdout_tail")   # sim_fails omitted

    with pytest.raises(ValueError) as exc:
        _run(run_dir, summary_key_order=order)

    assert "summary_key_order" in str(exc.value)


def test_control_summary_key_order_with_an_unknown_key_raises(tmp_path,
                                                              monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    order = ("tb", "verdict", "comparison", "checked", "mismatches",
             "first_failures", "sim_fails", "sim_stdout_tail", "invented")

    with pytest.raises(ValueError):
        _run(run_dir, summary_key_order=order)


def test_control_caller_supplied_report_sim_fails_raises(tmp_path,
                                                         monkeypatch):
    """The NOT_RUN branch needs a SimResult; a caller turning reporting off
    would get an unrelated return shape, so that is refused up front."""
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)

    with pytest.raises(ValueError) as exc:
        _run(run_dir, compile_kwargs={"out_name": "tb.vvp",
                                      "report_sim_fails": False})

    assert "report_sim_fails" in str(exc.value)


# --------------------------------------------------------------------------
# The dedup itself: who routes through the shared skeleton, and who does not
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", DEDUPED_LEAVES)
def test_deduped_leaf_uses_the_shared_skeleton(name):
    mod = __import__(name)
    assert getattr(mod, "run_leaf_comparison", None) is rcc.run_leaf_comparison


@pytest.mark.parametrize("name", EXCLUDED_LEAVES)
def test_excluded_leaf_was_left_alone(name):
    """#303's scope decision, kept visible: these three were verified
    divergent and must not be quietly folded into the shared skeleton
    without their own analysis."""
    mod = __import__(name)
    assert getattr(mod, "run_leaf_comparison", None) is None


# --------------------------------------------------------------------------
# Issue #361: input failures publish a current NOT_RUN refusal, never a
# stale verdict, never a numeric verdict, never a traceback
# --------------------------------------------------------------------------
#
# Reporting-boundary controls only. Nothing here is evidence about the RTL,
# the frozen model, or their agreement.

STALE_PASS = {"tb": "stale", "verdict": "PASS", "comparison": "PASS"}

KT_ORDER = ("tb", "sequence", "control_mode", "verdict", "comparison",
            "checked", "rtl_qmuls", "blocks", "mismatches", "first_failures",
            "sim_fails", "sim_stdout_tail")


def _kt_extras(mt, sim):
    # indexes the model exactly like compare_kt_rtl_model.extra_summary_fields
    return {"sequence": mt.get("sequence"),
            "control_mode": mt.get("control_mode"),
            "rtl_qmuls": sim.value, "blocks": len(mt["blocks"])}


def _mutate_model(run_dir, how):
    path = os.path.join(run_dir, "model_trace.json")
    if how == "absent":
        os.remove(path)
    elif how == "invalid-json":
        with open(path, "w") as f:
            f.write('{"blocks": [')
    elif how == "binary":
        with open(path, "wb") as f:
            f.write(b"\xff\xfe\x00garbage")
    elif how == "directory":
        os.remove(path)
        os.mkdir(path)
    elif how == "not-an-object":
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
    elif how == "no-blocks":
        with open(path, "w") as f:
            json.dump({"sequence": "x"}, f)
    elif how == "empty-blocks":
        with open(path, "w") as f:
            json.dump({"blocks": []}, f)
    elif how == "block-without-b":
        with open(path, "w") as f:
            json.dump({"blocks": [{"voices": []}]}, f)
    elif how == "block-without-voices":
        with open(path, "w") as f:
            json.dump({"blocks": [{"b": 0}]}, f)
    elif how == "voice-without-slot":
        with open(path, "w") as f:
            json.dump({"blocks": [{"b": 0, "voices": [{"key": 1}]}]}, f)
    else:
        raise AssertionError(how)


MODEL_MUTATIONS = ["absent", "invalid-json", "binary", "directory",
                   "not-an-object", "no-blocks", "empty-blocks",
                   "block-without-b", "block-without-voices",
                   "voice-without-slot"]


@pytest.mark.parametrize("how", MODEL_MUTATIONS)
def test_bad_model_is_refused_before_simulation_with_stale_pass_replaced(
        tmp_path, monkeypatch, how):
    run_dir = _write_trace(tmp_path)
    _mutate_model(run_dir, how)
    out = os.path.join(run_dir, "verdict.json")
    with open(out, "w") as f:
        json.dump(STALE_PASS, f)
    launched = []
    monkeypatch.setattr(rcc, "compile_and_run",
                        lambda *a, **k: launched.append(1))
    reached = []

    rc, _, _, d = _run(
        run_dir, out=out,
        parse_tb=lambda p: reached.append("parse"),
        compare=lambda mt, rt: reached.append("compare") or ({"f": 5}, []),
        default_checked={"f": 0})

    assert launched == [] and reached == []   # never simulated or compared
    assert rc == 1
    assert d["verdict"] == "FAIL"
    assert d["comparison"] == "NOT_RUN"
    assert d["checked"] == {"f": 0}
    assert d["input_error"]["input"] == "model"
    assert d["input_error"]["path"].endswith("model_trace.json")
    assert d["input_error"]["reason"]
    with open(out) as f:
        on_disk = json.load(f)
    assert on_disk == d and on_disk != STALE_PASS     # current, not stale


@pytest.mark.parametrize("how", ["absent", "invalid-json", "no-blocks"])
def test_keytrack_metadata_is_not_derived_from_a_refused_model(
        tmp_path, monkeypatch, how):
    run_dir = _write_trace(tmp_path)
    _mutate_model(run_dir, how)
    monkeypatch.setattr(rcc, "compile_and_run", lambda *a, **k: 1 / 0)

    rc, text, order, d = _run(run_dir, extra_summary_fields=_kt_extras,
                              summary_key_order=KT_ORDER)

    assert rc == 1
    assert order == list(KT_ORDER) + ["input_error"]
    assert d["sequence"] is None and d["control_mode"] is None
    assert d["rtl_qmuls"] is None and d["blocks"] is None   # not fabricated
    assert d["comparison"] == "NOT_RUN"


def _trace_case(tmp_path, monkeypatch, parse_tb, out_preseed=True):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "verdict.json")
    if out_preseed:
        with open(out, "w") as f:
            json.dump(STALE_PASS, f)
    compared = []
    rc, _, _, d = _run(
        run_dir, out=out, parse_tb=parse_tb,
        compare=lambda mt, rt: compared.append(1) or ({"f": 9}, []),
        default_checked={"f": 0})
    return rc, d, out, compared


def _raise(exc):
    def parse(path):
        raise exc
    return parse


@pytest.mark.parametrize("exc,label", [
    (FileNotFoundError(2, "No such file"), "absent"),
    (PermissionError(13, "denied"), "unreadable"),
    (ValueError("invalid literal for int() with base 10: 'x1'"),
     "malformed-token"),
    (IndexError("list index out of range"), "truncated-row"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), "undecodable"),
])
def test_trace_input_failures_are_refused_not_compared(tmp_path, monkeypatch,
                                                       exc, label):
    rc, d, out, compared = _trace_case(tmp_path, monkeypatch, _raise(exc))

    assert compared == []
    assert rc == 1
    assert d["verdict"] == "FAIL"
    assert d["comparison"] == "NOT_RUN"
    assert d["checked"] == {"f": 0}          # no partial coverage
    assert d["sim_fails"] == []              # the simulator did not fail
    assert d["input_error"]["input"] == "rtl_trace"
    with open(out) as f:
        assert json.load(f) == d


@pytest.mark.parametrize("exc", [KeyError("x"), TypeError("x"),
                                 AttributeError("x"), ZeroDivisionError()])
def test_control_programmer_errors_are_not_relabelled_as_input_refusal(
        tmp_path, monkeypatch, exc):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "verdict.json")

    with pytest.raises(type(exc)):
        _run(run_dir, out=out, parse_tb=_raise(exc))

    assert not os.path.exists(out)    # and no verdict is left at all


def test_stale_pass_is_removed_even_when_the_run_then_crashes(tmp_path,
                                                              monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "verdict.json")
    with open(out, "w") as f:
        json.dump(STALE_PASS, f)

    with pytest.raises(KeyError):
        _run(run_dir, out=out, parse_tb=_raise(KeyError("defect")))

    assert not os.path.exists(out)


def test_sim_failure_branch_is_unchanged_and_has_no_input_error(tmp_path,
                                                                monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch, sim_fails=["vvp exited rc=4"])

    rc, _, order, d = _run(run_dir)

    assert rc == 1 and d["comparison"] == "NOT_RUN"
    assert "input_error" not in d
    assert order == ["tb", "verdict", "comparison", "checked", "mismatches",
                     "first_failures", "sim_fails", "sim_stdout_tail"]


def test_numeric_mismatch_stays_fail_not_an_input_refusal(tmp_path,
                                                          monkeypatch):
    rc, d, _, _ = _trace_case(
        tmp_path, monkeypatch, lambda p: "parsed")   # healthy parse
    assert rc == 0 and d["comparison"] == "PASS"     # stale PASS replaced

    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    rc, _, _, d = _run(run_dir,
                       compare=lambda mt, rt: ({"f": 3}, ["m differs"]))
    assert rc == 1
    assert d["comparison"] == "FAIL"
    assert d["checked"] == {"f": 3}
    assert "input_error" not in d


def test_healthy_run_replaces_a_stale_verdict_and_has_no_input_error(
        tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "verdict.json")
    with open(out, "w") as f:
        json.dump({"verdict": "FAIL", "stale": True}, f)

    rc, text, _, d = _run(run_dir, out=out)

    assert rc == 0 and "input_error" not in d
    with open(out) as f:
        assert f.read() == text


def test_stdout_only_refusal_still_reports(tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    _mutate_model(run_dir, "invalid-json")

    rc, _, _, d = _run(run_dir, out=None)

    assert rc == 1 and d["comparison"] == "NOT_RUN"
    assert sorted(os.listdir(run_dir)) == ["model_trace.json"]


def test_unwritable_output_is_nonzero_and_names_the_publish_failure(
        tmp_path, monkeypatch, capsys):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "no-such-dir", "verdict.json")

    rc, _, _, d = _run(run_dir, out=out)

    assert rc == 1                    # a PASS comparison, but unpublished
    assert "no current verdict was published" in capsys.readouterr().err
    assert not os.path.exists(out)


def test_output_that_cannot_be_invalidated_is_nonzero(tmp_path, monkeypatch,
                                                      capsys):
    run_dir = _write_trace(tmp_path)
    _stub_sim(monkeypatch)
    out = os.path.join(run_dir, "verdict.json")
    os.mkdir(out)                     # a directory: os.remove fails

    rc, _, _, _ = _run(run_dir, out=out)

    assert rc == 1
    assert "could not invalidate the prior verdict" in capsys.readouterr().err


def test_control_validate_model_hook_refusal_precedes_simulation(
        tmp_path, monkeypatch):
    run_dir = _write_trace(tmp_path)
    monkeypatch.setattr(rcc, "compile_and_run", lambda *a, **k: 1 / 0)

    def validate(model):
        raise rcc.LeafInputError("model", "m", "leaf wants n_unison")

    rc, _, _, d = _run(run_dir, validate_model=validate)

    assert rc == 1 and d["input_error"]["reason"] == "leaf wants n_unison"
