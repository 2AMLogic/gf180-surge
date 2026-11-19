"""Issue #647: a duplicate-checkpoint input refusal is PUBLISHED at every
one of the four RTL-vs-model harness boundaries that called their
`parse_tb` bare, and a prior PASS report at the same path never survives
it.

#639 put every leaf parser on the shared `CheckpointKeys` primitive, so a
repeated checkpoint key raises `LeafInputError`.  In the four harnesses
under test here the refusal used to escape `main()` as an uncaught
traceback: fail-closed (non-zero exit, nothing reports PASS) but silent --
no summary was written, so a verdict from an EARLIER run stayed on disk
byte-identical and still read PASS.  Velocity (#631/PR #652) and play mode
(#645/PR #789) route the refusal through `run_leaf_comparison`; sine and
control publish their own existing report shapes (#647).  This module pins
all four -- both sine entry points included -- at the CLI/report boundary,
and per harness seeds the report path with a PASS summary first: the
stale-PASS survival is the defect this issue exists to close, so a control
that only asserted the exit status would not cover it.

Synthetic traces only, simulator stubbed (the
`test_lfo_checkpoint_key_ownership.py` pattern): these are publication
controls, not evidence about the RTL, the frozen model, or their agreement.
"""

import json
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402
import tools.compare_control_rtl as control  # noqa: E402
import tools.compare_pm_rtl_model as pm  # noqa: E402
import tools.compare_sine_rtl_model as sine  # noqa: E402
import tools.compare_vel_rtl_model as vel  # noqa: E402
from model.control import render_sequence  # noqa: E402
from model.control.engine_stub_counter import CounterStubEngine  # noqa: E402

# A stale verdict from an earlier run at the report path, as the issue's
# failure control seeds it.
SEED_PASS = {"verdict": "PASS", "mismatches": 0}


def _write_run_dir(tmp_path, model):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(model, f)
    return run_dir


def _write_trace(run_dir, name, trace_text):
    path = os.path.join(run_dir, name)
    with open(path, "w") as f:
        f.write(trace_text)
    return path


def _seed_pass(path):
    with open(path, "w") as f:
        json.dump(SEED_PASS, f)


def _stub_sim(monkeypatch, target, trace=None):
    """A clean simulator result; `trace` is the RTL trace path to reuse."""
    def fake(*a, **k):
        return types.SimpleNamespace(sim_fails=[], trace=trace,
                                     stdout="", stdout_tail="")
    monkeypatch.setattr(target, "compile_and_run", fake)


def _assert_published(rc, d):
    """The refusal a duplicate-key trace must produce at the report
    boundary (#647's acceptance check), after a PASS file was seeded."""
    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert all(v == 0 for v in d["checked"].values()), d
    assert d["mismatches"] == 1, d
    assert d["input_error"]["input"] == "rtl_trace", d
    assert "duplicate" in d["input_error"]["reason"], d
    assert "input refusal" in d["first_failures"][0], d


# ---------------------------------------------------------------- velocity
# Already routed through `run_leaf_comparison` (#631); pinned here so the
# four-harness acceptance check is one module.

VEL_MODEL = {
    "sequence": "pub-vel", "control_mode": "normal",
    "blocks": [{"b": 0,
                "voices": [{"slot": 0, "vel_words": [100, 200],
                            "vel_route_sums": [1, 2, 3, 4]}]}],
}
VEL_MATCHING = "V 0 0 100 200\nS 0 0 1 2 3 4\n"
VEL_DUP = VEL_MATCHING + "V 0 0 9 9\n"


def _run_vel(monkeypatch, tmp_path, trace_text):
    run_dir = _write_run_dir(tmp_path, VEL_MODEL)
    trace = _write_trace(run_dir, "tb_vel_trace.txt", trace_text)
    _stub_sim(monkeypatch, rcc, trace)
    out = os.path.join(run_dir, "verdict.json")
    _seed_pass(out)
    monkeypatch.setattr(sys, "argv",
                        ["compare_vel_rtl_model.py", "--run-dir", run_dir,
                         "--out", out])
    rc = vel.main()
    return rc, json.load(open(out))


def test_vel_duplicate_is_published_and_stale_pass_replaced(tmp_path,
                                                            monkeypatch):
    _assert_published(*_run_vel(monkeypatch, tmp_path, VEL_DUP))


# --------------------------------------------------------------- play mode
# Adopted onto `run_leaf_comparison` by #645; pinned here for the same
# reason.  Its model trace carries `blocks[].slots` (per-slot field lists).

PM_MODEL = {"carrier": "pub-pm", "sequence": "pub-pm", "pool": 1,
            "blocks": [{"b": 0, "slots": [list(range(16))]}]}
PM_MATCHING = "T 0 0 " + " ".join(str(v) for v in range(16)) + "\n"
PM_DUP = PM_MATCHING + "T 0 0 " + " ".join(["99"] * 16) + "\n"


def _run_pm(monkeypatch, tmp_path, trace_text):
    run_dir = _write_run_dir(tmp_path, PM_MODEL)
    trace = _write_trace(run_dir, "tb_pm_trace.txt", trace_text)
    _stub_sim(monkeypatch, rcc, trace)
    out = os.path.join(run_dir, "verdict.json")
    _seed_pass(out)
    monkeypatch.setattr(sys, "argv",
                        ["compare_pm_rtl_model.py", "--run-dir", run_dir,
                         "--out", out])
    rc = pm.main()
    return rc, json.load(open(out))


def test_pm_duplicate_is_published_and_stale_pass_replaced(tmp_path,
                                                           monkeypatch):
    _assert_published(*_run_pm(monkeypatch, tmp_path, PM_DUP))


# -------------------------------------------------------------------- sine
# Both entry points: the simulator path and the `--trace` reuse path.  The
# model trace and matching trace are the reporting test's (the probe that
# measured the stale-PASS table in the issue body).

SINE_MODEL = {
    "n_unison": 1,
    "legacy": False,
    "blocks": [{
        "b": 0,
        "mono_block": [100, -200, 300],
        "voices": [{
            "slot": 0, "oscout_block": [1, 2, 3],
            "after": {
                "aeg": {"state": 1, "phase": 4, "output": 5},
                "fb_v": 6, "fm_v": 7, "firstblock": 1,
                "hp_r0": 8, "hp_r1": 9, "lp_r0": 10, "lp_r1": 11,
                "char_py": 12, "char_px": 13, "gain_end": 14,
                "prior_valid": 1,
                "phase": [15], "lv0": [16], "lv1": [17], "om_prior": [18],
            },
        }],
    }],
}


def _sine_t_line(b, s, key, aeg_out):
    """Modern `T` line matching SINE_MODEL's voice, with aeg_out as the
    one per-row difference (so the duplicate contradicts, #455's shape)."""
    vals = [b, s, key, 0, 1, 1, 4, aeg_out]
    for u in range(sine.MAXUNI):
        vals += [15, 16, 17, 18] if u == 0 else [0, 0, 0, 0]
    vals.append(1)
    return "T " + " ".join(str(v) for v in vals)


SINE_REST = ("S 0 0 6 7 1 8 9 10 11 12 13\n"
             "G 0 0 14\n"
             "O 0 0 1 2 3\n"
             "M 0 100\nM 0 -200\nM 0 300\n")
SINE_MATCHING = _sine_t_line(0, 0, 60, 5) + "\n" + SINE_REST
SINE_DUP = SINE_MATCHING + _sine_t_line(0, 0, 60, 99) + "\n"

SINE_KEYS = ["tb", "verdict", "comparison", "checked", "mismatches",
             "first_failures", "sim_fails", "sim_stdout_tail"]


def _run_sine_sim(monkeypatch, tmp_path, trace_text):
    run_dir = _write_run_dir(tmp_path, SINE_MODEL)
    trace = _write_trace(run_dir, "tb_trace.txt", trace_text)
    _stub_sim(monkeypatch, sine, trace)
    out = os.path.join(run_dir, "verdict.json")
    _seed_pass(out)
    monkeypatch.setattr(sys, "argv",
                        ["compare_sine_rtl_model.py", "--run-dir", run_dir,
                         "--out", out])
    rc = sine.main()
    return rc, json.load(open(out))


def _run_sine_trace(tmp_path, trace_text):
    run_dir = _write_run_dir(tmp_path, SINE_MODEL)
    trace = _write_trace(run_dir, "reuse.txt", trace_text)
    out = os.path.join(run_dir, "verdict.json")
    _seed_pass(out)
    sys.argv = ["compare_sine_rtl_model.py", "--run-dir", run_dir,
                "--out", out, "--trace", trace]
    try:
        rc = sine.main()
    finally:
        sys.argv = ["compare_sine_rtl_model.py"]
    return rc, json.load(open(out))


def test_sine_sim_duplicate_is_published_and_stale_pass_replaced(
        tmp_path, monkeypatch):
    _assert_published(*_run_sine_sim(monkeypatch, tmp_path, SINE_DUP))


def test_sine_trace_duplicate_is_published_and_stale_pass_replaced(
        tmp_path):
    _assert_published(*_run_sine_trace(tmp_path, SINE_DUP))


def test_sine_healthy_summary_keeps_its_exact_keys(tmp_path, monkeypatch):
    """A healthy run's key set and order are unchanged by the refusal
    branch (acceptance: the committed report shape survives)."""
    rc, d = _run_sine_sim(monkeypatch, tmp_path, SINE_MATCHING)
    assert rc == 0
    assert d["verdict"] == "PASS" and d["comparison"] == "PASS", d
    assert list(d.keys()) == SINE_KEYS, list(d.keys())
    assert "input_error" not in d


# ----------------------------------------------------------------- control
# `run_comparison` writes `run_dir/verdict.json` itself and has no `--out`;
# the report path the stale-PASS control seeds is that verdict file.  The
# refusal falls through to the existing verdict assembly and write, adding
# `input_error` on the refusal path only.

CONTROL_SEQ = {"schema_version": 1, "sample_rate": 48000,
               "block_size": 32, "blocks": 1, "events": [],
               "id": "pub-control"}

CONTROL_KEYS = ["sequence", "dut", "verdict", "comparison",
                "byte_identical_outputs", "model_summary", "checked",
                "mismatches", "first_failures", "sim_fails",
                "sim_stdout_tail"]


def _healthy_control_trace_text():
    """The exact RTL trace the model render expects, derived from the model
    itself: the healthy-path control passes compare and byte-identity with
    the simulator stubbed, so its key-order assertion is a real PASS run."""
    trace, out, _summary = render_sequence(CONTROL_SEQ, CounterStubEngine())
    lines = []
    m_lines = []
    for rec in trace["blocks"]:
        b = rec["b"]
        snap = rec["snapshot_after"]
        t = [b, snap["qcount"], snap["patch_id"], snap["active_count"]]
        for v in snap["voices"]:
            t += [1 if v["active"] else 0, v["note"], v["seq"]]
        lines.append("T " + " ".join(str(x) for x in t))
        for d in rec["decisions"]:
            lines.append("E %d %d %d %d %d %d %d %d %d"
                         % (b, d["seq"], d["type"], d["p1"], d["p2"],
                            d["slot"], d["steal"], d["status"], d["flushes"]))
        for d in rec["drops"]:
            lines.append("X %d %d %d %d %d"
                         % (b, d["t"], d["type"], d["p1"], d["p2"]))
        for i in range(32):
            w = out[(b * 32 + i) * 4:(b * 32 + i) * 4 + 4]
            m_lines.append("M %d %d %d %d"
                           % (b, i, int.from_bytes(w[0:2], "little"),
                              int.from_bytes(w[2:4], "little")))
    return "\n".join(lines + m_lines) + "\n"


def _control_duplicate_trace_text():
    healthy = _healthy_control_trace_text()
    t_line = healthy.splitlines()[0]
    contradicting = t_line.replace("T 0 0", "T 0 9", 1)
    return healthy + contradicting + "\n"


def _run_control(monkeypatch, tmp_path, trace_text):
    run_dir = str(tmp_path)
    seq_path = _write_trace(run_dir, "seq.json",
                            json.dumps(CONTROL_SEQ))
    _write_trace(run_dir, "rtl_trace.txt", trace_text)
    _stub_sim(monkeypatch, control)
    verdict_path = os.path.join(run_dir, "verdict.json")
    _seed_pass(verdict_path)
    monkeypatch.setattr(sys, "argv",
                        ["compare_control_rtl.py", "--seq", seq_path,
                         "--run-dir", run_dir])
    rc = control.main()
    return rc, json.load(open(verdict_path))


def test_control_duplicate_is_published_and_stale_pass_replaced(
        tmp_path, monkeypatch):
    rc, d = _run_control(monkeypatch, tmp_path, _control_duplicate_trace_text())
    _assert_published(rc, d)
    # The refusal rides the existing verdict assembly: the healthy key set
    # in its healthy order, plus `input_error` appended on this path only.
    assert list(d.keys()) == CONTROL_KEYS + ["input_error"], list(d.keys())
    assert d["byte_identical_outputs"] is False


def test_control_healthy_verdict_keeps_its_exact_keys(tmp_path, monkeypatch):
    rc, d = _run_control(monkeypatch, tmp_path,
                         _healthy_control_trace_text())
    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["byte_identical_outputs"] is True
    assert d["comparison"] == "PASS"
    assert list(d.keys()) == CONTROL_KEYS, list(d.keys())
    assert "input_error" not in d
