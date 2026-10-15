"""Issue #451: voice RTL-vs-model comparators reject shortened or extended
checkpoint records instead of grading a zip prefix as agreement.

Covers tools/compare_kt_rtl_model.py (V rows) and the LP12/LP24/LP-Moog
comparators (T rows).  The simulator is stubbed where the command-line path
is exercised; these are comparator-shape controls only and say nothing about
the RTL, the frozen model, or their agreement.

Every malformed case is built so that all available samples and fields match
the model -- the only defect is checkpoint width -- so a regression to the
unchecked zip turns these tests red.
"""
import json
import os
import subprocess
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import pytest  # noqa: E402

import _rtl_compile_common as rcc  # noqa: E402
import tools.compare_kt_rtl_model as kt  # noqa: E402
import tools.compare_rtl_model_lp12 as lp12  # noqa: E402
import tools.compare_rtl_model_lp24 as lp24  # noqa: E402
import tools.compare_rtl_model_lpmoog as lpmoog  # noqa: E402

# ---- synthetic one-block traces using each comparator's real schema ----

KT_FIELDS = [100, 10, 20, 30, 1, 2, 3, 4]
KT_MODEL = {"sequence": "s", "control_mode": "normal", "blocks": [{
    "b": 0, "voices": [{"slot": 0, "kt_word": 100,
                        "kt_route_sums": [10, 20, 30], "mod_cutoff": 1,
                        "mod_reso": 2, "mod_envmod": 3, "mod_vca_db": 4}]}]}

C = [101, 102, 103, 104, 105, 106, 107, 108]
LP12_T = [1, 11, 12, 13, *C]                 # 12 fields after block key
LP12_MODEL = {"leg": "t", "instances": [{"trace_blocks": [{
    "b": 0, "subtype": 1, "out_model": [5, 6],
    "after": {"r0": 11, "r1": 12, "r_clip": 13, "C_end": C}}]}]}
LP5_T = [1, 11, 12, 13, 14, 15, *C]          # 14 fields after block key
LP5_MODEL = {"leg": "t", "trace_blocks": [{
    "b": 0, "subtype": 1, "out_model": [5, 6],
    "after": {"r": [11, 12, 13, 14, 15], "C_end": C}}]}

Y = {(0, 0): 5, (0, 1): 6}   # correct output samples

FILTERS = {
    "lp12": (lp12, LP12_MODEL, LP12_T),
    "lp24": (lp24, LP5_MODEL, LP5_T),
    "lpmoog": (lpmoog, LP5_MODEL, LP5_T),
}


def _write_trace(path, name, rows):
    """Write a real RTL trace text file (Y samples + given T/V rows)."""
    lines = ["Y %d %d %d" % (b, k, v) for (b, k), v in Y.items()] \
        if name != "kt" else []
    lines += rows
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return str(path)


def _run_filter(name, tmp_path, t_fields):
    mod, model, _ = FILTERS[name]
    row = "T 0" + "".join(" %d" % v for v in t_fields)
    tb = _write_trace(tmp_path / "t.txt", name, [row])
    return mod.compare(model, tb)


def _run_kt(tmp_path, v_fields):
    row = "V 0 0" + "".join(" %d" % v for v in v_fields)
    tb = _write_trace(tmp_path / "t.txt", "kt", [row])
    return kt.compare(KT_MODEL, kt.parse_tb(tb))


def _malformed(t_full):
    return {
        "block_key_only": [],
        "missing_last_field": t_full[:-1],
        "extra_field": t_full + [999],
    }


@pytest.mark.parametrize("name", sorted(FILTERS))
def test_filter_full_checkpoint_keeps_prior_result(name, tmp_path):
    checked, fails = _run_filter(name, tmp_path, FILTERS[name][2])
    assert fails == []
    assert checked == {"samples": 2, "checkpoints": 1,
                       "fields": len(FILTERS[name][2])}


@pytest.mark.parametrize("case", ["block_key_only", "missing_last_field",
                                  "extra_field"])
@pytest.mark.parametrize("name", sorted(FILTERS))
def test_filter_malformed_checkpoint_is_rejected(name, case, tmp_path):
    full = FILTERS[name][2]
    checked, fails = _run_filter(name, tmp_path, _malformed(full)[case])
    assert fails, "shape error must be reported even though all data matches"
    msg = " ".join(fails)
    assert "SHAPE_ERROR T record 0 (rtl)" in msg
    assert "expected %d" % len(full) in msg
    assert "width %d" % len(_malformed(full)[case]) in msg
    # cannot contribute a complete checkpoint claim
    assert checked["checkpoints"] == 0
    assert checked["fields"] == 0
    assert checked["malformed_checkpoints"] == 1
    assert checked["samples"] == 2   # samples were still compared


@pytest.mark.parametrize("name", sorted(FILTERS))
def test_filter_malformed_model_vector_is_rejected(name, tmp_path):
    mod, model, full = FILTERS[name]
    bad = json.loads(json.dumps(model))
    blk = (bad["instances"][0] if name == "lp12" else bad)["trace_blocks"][0]
    blk["after"]["C_end"] = blk["after"]["C_end"][:-1]
    row = "T 0" + "".join(" %d" % v for v in full[:-1])  # prefix "matches"
    tb = _write_trace(tmp_path / "t.txt", name, [row])
    checked, fails = mod.compare(bad, tb)
    assert any("SHAPE_ERROR T record 0 (model)" in f for f in fails), fails
    assert checked["checkpoints"] == 0


def test_kt_full_checkpoint_keeps_prior_result(tmp_path):
    checked, fails = _run_kt(tmp_path, KT_FIELDS)
    assert fails == []
    assert checked == {"voice_checkpoints": 1, "fields": 8}


@pytest.mark.parametrize("case", ["block_key_only", "missing_last_field",
                                  "extra_field"])
def test_kt_malformed_checkpoint_is_rejected(case, tmp_path):
    fields = _malformed(KT_FIELDS)[case]
    checked, fails = _run_kt(tmp_path, fields)
    msg = " ".join(fails)
    assert "SHAPE_ERROR V record (0, 0) (rtl)" in msg, fails
    assert "width %d, expected 8" % len(fields) in msg
    assert checked["voice_checkpoints"] == 0
    assert checked["fields"] == 0
    assert checked["malformed_checkpoints"] == 1


def test_kt_malformed_model_vector_is_rejected(tmp_path):
    bad = json.loads(json.dumps(KT_MODEL))
    bad["blocks"][0]["voices"][0]["kt_route_sums"] = [10, 20]
    row = "V 0 0 100 10 20 1 2 3 4"
    tb = _write_trace(tmp_path / "t.txt", "kt", [row])
    checked, fails = kt.compare(bad, kt.parse_tb(tb))
    assert any("(model)" in f and "SHAPE_ERROR" in f for f in fails), fails
    assert checked["voice_checkpoints"] == 0


# ---- command-line / report path (stubbed simulator) ----

def _stub_sim(monkeypatch, run_dir, trace_name, trace_text):
    def fake_run(cmd, **kwargs):
        if cmd[0] != "iverilog":
            with open(os.path.join(run_dir, trace_name), "w") as f:
                f.write(trace_text)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rcc, "subprocess", types.SimpleNamespace(
        run=fake_run, DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired))


def _prep(tmp_path, model, stimulus):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(model, f)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    for rel in stimulus:
        open(os.path.join(run_dir, rel), "w").close()
    return run_dir


def _main(monkeypatch, mod, run_dir):
    out = os.path.join(run_dir, "verdict.json")
    monkeypatch.setattr(sys, "argv", ["x", "--run-dir", run_dir, "--out", out])
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


@pytest.mark.parametrize("v_row,ok", [
    ("V 0 0 100 10 20 30 1 2 3 4\n", True),
    ("V 0 0\n", False),
    ("V 0 0 100 10 20 30 1 2 3\n", False),
    ("V 0 0 100 10 20 30 1 2 3 4 5\n", False),
])
def test_kt_cli_report_path(tmp_path, monkeypatch, v_row, ok):
    run_dir = _prep(tmp_path, KT_MODEL, kt.STIMULUS_RELPATHS)
    _stub_sim(monkeypatch, run_dir, "tb_kt_trace.txt", v_row)
    rc, d = _main(monkeypatch, kt, run_dir)
    if ok:
        assert rc == 0 and d["verdict"] == "PASS"
        assert d["checked"] == {"voice_checkpoints": 1, "fields": 8}
    else:
        assert rc != 0 and d["verdict"] == "FAIL"
        assert d["comparison"] == "FAIL"
        assert "SHAPE_ERROR" in d["first_failures"][0]
        assert d["checked"]["voice_checkpoints"] == 0


@pytest.mark.parametrize("t_fields,ok", [
    (LP12_T, True), ([], False), (LP12_T[:-1], False), (LP12_T + [9], False)])
def test_lp12_cli_report_path(tmp_path, monkeypatch, t_fields, ok):
    run_dir = _prep(tmp_path, LP12_MODEL, lp12.STIMULUS_RELPATHS)
    text = "Y 0 0 5\nY 0 1 6\nT 0" + "".join(" %d" % v for v in t_fields) + "\n"
    _stub_sim(monkeypatch, run_dir, "tb_trace.txt", text)
    rc, d = _main(monkeypatch, lp12, run_dir)
    if ok:
        assert rc == 0 and d["verdict"] == "PASS"
        assert d["checked"]["checkpoints"] == 1
    else:
        assert rc != 0 and d["verdict"] == "FAIL"
        assert d["comparison"] == "FAIL"
        assert "SHAPE_ERROR" in d["first_failures"][0]
        assert d["checked"]["checkpoints"] == 0
