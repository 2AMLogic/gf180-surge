"""SXT-037 LP 12 dB filter leaf tests (pytest).

Covers: coefficient construction against the cited pinned formulas at known
operating points, per-subtype kernel behavior, register-init semantics,
applicability-boundary refusals (fail-closed), the stability monitor, the
RTL comparator's mismatch detection, and negative-control wiring that does
not require the oracle or iverilog.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "model", "voice"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "model", "voice", "filter_lp12"))

import voice_model as vm  # noqa: E402
import filter_lp12_model as fp  # noqa: E402

ONE = vm.ONE
Q = float(ONE)


def test_driven_coeffs_match_pinned_form_at_known_point():
    # cutoff 0 st (440 Hz), reso 0.5, Driven: mirror the pinned formulas in
    # double and compare against the quantized model words.
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    reso = 0.5
    freq = 0.0
    reso_eff = reso * max(0.0, 1.0 - max(0.0, (freq - 58) * 0.05))
    m2pr = 1.0 - 1.05 * min(1.0, max(0.001, 1 - (1 - reso_eff) ** 2))
    p = 1.0
    ph = min(0.5, 440.0 * p / 96000.0)
    sinu = math.sin(2 * math.pi * ph)
    cosi = math.cos(2 * math.pi * ph)
    alpha = sinu * m2pr
    alpha = min(alpha, math.sqrt(1 - cosi * cosi) - 1e-4)
    a0inv = 1 / (1 + alpha)
    a1 = -2 * cosi * a0inv
    a2 = (1 - alpha) * a0inv
    gain = 1 - 0.5 * reso * reso
    b0 = (1 - cosi) * 0.5 * a0inv * gain
    ar = -a1 / 2
    ai = 0.5 * math.sqrt(max(0.0, -(a1 * a1 - 4 * a2)))
    bb1 = (1 - cosi) * a0inv * gain - a1 * b0
    bb2 = (1 - cosi) * 0.5 * a0inv * gain - a2 * b0
    want = {
        0: ar, 1: ai, 2: 1.0, 4: bb1, 5: (bb1 * ar + bb2) / ai, 6: b0,
        7: (1 / 64.0) * (10 ** (0.05 * (freq * 0.55))),
    }
    for i, w in want.items():
        got = cm.C[i] / Q
        # Q10.21 intermediate quantization (esp. ai -> C5) allows ~1e-3
        # relative drift against the pure-double mirror
        assert abs(got - w) <= 2e-3 * max(abs(w), 1e-3), (i, got, w)
    assert all(v == 0 for v in cm.dC)      # FirstRun


def test_clean_uses_lattice_and_clipscale_1_over_1024():
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_CLEAN)
    cm.make_coeffs(vm.qint(20.0), vm.qint(0.25))
    # lattice form: q-words in (0, 1]; clipscale = 1/1024 exactly
    assert 0 < cm.C[2] <= ONE and 0 < cm.C[3] <= ONE
    assert cm.C[7] == vm.qdiv(ONE, vm.qint(1024.0))
    # Driven at the same point has a different structure (C2 == ONE) and
    # a different clipscale
    cm2 = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm2.make_coeffs(vm.qint(20.0), vm.qint(0.25))
    assert cm2.C[2] == ONE and cm2.C[7] != cm.C[7]


def test_standard_svf_coeffs_and_gain_decrease_with_reso():
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_STANDARD)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.0))
    g_loreso = cm.C[3]
    cm2 = fp.LP12CoeffMaker(fp.SUBTYPE_STANDARD)
    cm2.make_coeffs(vm.qint(0.0), vm.qint(1.0))
    g_hireso = cm2.C[3]
    assert g_hireso < g_loreso                     # 1 - 0.65*sqrt(reso)
    # F1 = 2 sin(pi * min(0.11, f * 0.5 / 96000)) at 0 st: the coefficient
    # maker runs at dsamplerate_os = 96000 (SurgeVoice::sampleRateReset();
    # F-038-3 / #102 -- the pre-#102 model used 48000, i.e. 440/96000 here)
    f1 = 2 * math.sin(math.pi * min(0.11, 440.0 * 0.5 / 96000.0))
    assert abs(cm.C[0] / Q - f1) < 1e-6
    assert abs(cm.C[0] / Q - 2 * math.sin(math.pi * 440.0 / 96000.0)) > 1e-3


def test_driven_clipscale_is_exact_pow_not_db_table():
    # sst-filters clipscale calls its own db_to_linear = pow(10, 0.05 x)
    # (F-038-4 / #102), not Surge's interpolated dB table.  At 37.5 st the
    # dB argument (20.625 dB) sits mid-way between table entries, where
    # the table's linear interpolation error is largest.
    freq = 37.5
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(freq), 0)
    exact = vm.qint((1 / 64.0) * 10 ** (0.05 * freq * 0.55))
    table = vm.qdiv(vm.db_to_linear(vm.qint(freq * 0.55)), vm.qint(64.0))
    assert abs(cm.C[7] - exact) <= 1
    assert abs(cm.C[7] - table) > 100


def test_bound_freq_clamp_is_frozen():
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(200.0), 0)              # inside scope, above bound
    cm2 = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm2.make_coeffs(vm.qint(75.0), 0)              # exactly the bound
    assert cm.C == cm2.C


def test_out_of_scope_refused():
    for bad in (
        lambda: fp.LP12CoeffMaker(3),                       # subtype 3
        lambda: fp.LP12CoeffMaker(9),                       # subtype 9
        lambda: fp.LP12Unit(7),                             # kernel subtype
        lambda: fp.LP12CoeffMaker(1).make_coeffs(vm.qint(0.0), qintf(1.01)),
        lambda: fp.LP12CoeffMaker(1).make_coeffs(vm.qint(300.0), 0),
        lambda: fp.LP12CoeffMaker(1).make_coeffs(vm.qint(-300.0), 0),
    ):
        try:
            bad()
        except fp.Refuse:
            pass
        else:
            raise AssertionError("out-of-scope request was accepted")


def qintf(x):
    return vm.sat(int(math.floor(x * ONE + 0.5)))


def test_driven_kernel_clipgain_zero_init_seeds_no_state():
    # FBP memset semantics: Rclip starts 0 -> first sample leaves R0=R1=0
    unit = fp.LP12Unit(fp.SUBTYPE_DRIVEN)
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.8))
    x = qintf(0.5)
    out, peak, c_end = unit.process_block([x] * 4, cm)
    assert unit.r0 != 0                        # recovered after first sample
    assert out[0] == vm.qmul(c_end[6], x)      # y = C6*x (states were 0)
    assert unit.r_clip >= vm.qint(0.1)


def test_stability_monitor_flags_growth_and_accepts_bounded():
    growing = [2 ** i for i in range(40)]
    assert fp.stability_verdict(growing) == "UNSTABLE"
    bounded = [1000 + (i % 7) for i in range(40)]
    assert fp.stability_verdict(bounded) == "STABLE"


def test_per_instance_state_independent():
    a, b = fp.LP12Unit(fp.SUBTYPE_DRIVEN), fp.LP12Unit(fp.SUBTYPE_DRIVEN)
    cm = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.9))
    sig = [qintf(0.3 * math.sin(i / 5.0)) for i in range(64)]
    a.process_block(sig, cm)
    b.process_block(sig, cm)
    assert (a.r0, a.r1, a.r_clip) == (b.r0, b.r1, b.r_clip)   # same drive
    sig2 = [qintf(0.9 * math.sin(i / 3.0)) for i in range(64)]
    a.process_block(sig2, cm)
    b.process_block(sig[:32] + sig2[32:], cm)
    assert (a.r0, a.r1) != (b.r0, b.r1)       # divergence: state is per-instance


def test_comparator_detects_mismatch(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    from tools.compare_rtl_model_lp12 import compare

    trace = {"instances": [{"trace_blocks": [{
        "b": 0, "subtype": 1, "in": [5], "out_model": [42],
        "out_engine_q": [42], "C_start": [0] * 8, "dC": [0] * 8,
        "after": {"r0": 1, "r1": 2, "r_clip": 3,
                  "C_end": [4] * 8}}]}]}
    lines = ["Y 0 0 42", "T 0 1 1 2 3 4 4 4 4 4 4 4 4"]
    p = tmp_path / "tb_trace.txt"
    p.write_text("\n".join(lines) + "\n")
    checked, fails = compare(trace, str(p))
    assert not fails and checked["samples"] == 1 and checked["fields"] == 12
    lines[0] = "Y 0 0 43"
    p.write_text("\n".join(lines) + "\n")
    checked, fails = compare(trace, str(p))
    assert fails and "sample 0" in fails[0]


def test_mutant_file_differs_by_single_constant():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tb = open(os.path.join(repo, "rtl", "voice", "tb_lp12.sv")).read()
    mu = open(os.path.join(repo, "rtl", "voice", "lp12_broken_mutant.sv")).read()
    assert tb.replace("(64'sd1 << 20)", "(64'sd1 << 19)") == mu
    assert tb.count("(64'sd1 << 20)") == 1


def test_reference_tool_refuses_without_taps(tmp_path, monkeypatch):
    # without the patched oracle, the render tool must refuse (exit 3 class)
    import subprocess
    r = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "render_lp12_reference.py"),
         "--out-dir", str(tmp_path / "o"), "--cases", "badnews", "--smoke"],
        capture_output=True, text=True, env={**os.environ, "ORACLE_SURGE_DIR":
                                             "/nonexistent"})
    assert r.returncode == 3
    assert "REFUSING" in r.stderr or "oracle unavailable" in r.stderr


# --- SXT-037 stability-leg controls (issue #653) -------------------------
# The model-vs-engine comparator grades two stability legs.  Before #653 the
# "engine" leg was `max(stability_peaks)` -- the MODEL's per-block state peak
# under a second name -- so it could not fail while the model leg passed, and
# the model leg was a bare `< 1 << 31` threshold rather than the frozen
# model's monitor verdict.  These controls fail if either leg regresses to a
# model quantity or to a threshold.

def _lp12_budget_trace(case, **inst_over):
    """A minimal LP12 model trace whose single instance is inside every
    PROPOSED L1/L2 budget, so only the stability legs can fail it."""
    inst = {
        "key": {"tag": 0, "lane": 0, "name": "unit1"},
        "blocks": 1,
        "subtypes": [1],
        "l1_C_max": 1,
        "l1_C_rms": 0.5,
        "l2a": {"n": 64, "max_abs_lsb": 10, "rms_lsb": 1.0,
                "engine_peak_lsb": 1 << 20},
        "l2_spectral_corr": 0.9999,
        "stability_peaks": [1000],
        "stability_verdict": "STABLE",
    }
    for k, v in inst_over.items():
        if k == "l2a":
            inst["l2a"].update(v)
        elif v is None:
            inst.pop(k, None)
        else:
            inst[k] = v
    return {"leg": "L2a-own-coeffs", "meta": {"case": case},
            "instances": [inst]}


def _run_lp12_comparator(trace, tmp_path):
    """Drive tools/compare_lp12_model.py over one trace; return (rc, record)."""
    import json
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tp = tmp_path / "model_trace.json"
    tp.write_text(json.dumps(trace))
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, os.path.join(repo, "tools", "compare_lp12_model.py"),
         "--traces", str(tp), "--out-dir", str(out)],
        capture_output=True, text=True)
    rec = out / f"compare-{trace['meta']['case']}.json"
    return r, (json.loads(rec.read_text()) if rec.exists() else None)


def test_engine_stability_leg_fails_on_engine_peak_with_model_peak_fine(tmp_path):
    # THE #653 control: the engine tap peak is out of bounds while the model
    # state peak and the model monitor verdict are both fine.  An engine leg
    # aliased to the model peak cannot produce this FAIL.
    r, rec = _run_lp12_comparator(
        _lp12_budget_trace("engine-runaway",
                           l2a={"engine_peak_lsb": 1 << 29},
                           stability_peaks=[1000],
                           stability_verdict="STABLE"),
        tmp_path)
    assert r.returncode == 0, r.stderr
    v = rec["results"]["unit1.lane0"]
    assert v["stability_model"] == "STABLE"          # model leg unaffected
    assert v["model_state_peak_lsb"] == 1000
    assert v["stability_engine"] == "UNBOUNDED"      # engine leg caught it
    assert v["stability"] == "FAIL"
    assert v["L1_coefficients"] == "PASS" and v["L2_audio"] == "PASS"
    assert "FAIL" in rec["verdict"]                  # and it fails the case
    # the two peaks are independent quantities, not one number twice
    assert v["engine_tap_peak_lsb"] != v["model_state_peak_lsb"]


def test_engine_stability_leg_passes_a_bounded_engine_peak(tmp_path):
    # Mirror of the control above: same model numbers, engine tap in bounds.
    r, rec = _run_lp12_comparator(_lp12_budget_trace("engine-bounded"), tmp_path)
    assert r.returncode == 0, r.stderr
    v = rec["results"]["unit1.lane0"]
    assert v["stability_engine"] == "BOUNDED"
    assert v["stability"] == "PASS"
    assert v["engine_tap_peak_lsb"] == 1 << 20
    assert v["engine_tap_peak_max_lsb"] == 1 << 28
    assert "PASS" in rec["verdict"]


def test_model_stability_leg_reads_the_monitor_verdict_not_a_threshold(tmp_path):
    # Sustained exponential growth the monitor's growth detection calls
    # UNSTABLE, staying below BOTH the monitor's own 1 << 30 saturation floor
    # and the pre-#653 bare `< 1 << 31` threshold -- so only the real monitor
    # verdict can fail this, and the comparator must report it.
    growing = [1 << (14 + i) for i in range(16)]        # 16 KLSB -> 1 << 29
    assert fp.stability_verdict(growing) == "UNSTABLE"  # growth detection
    assert max(growing) < (1 << 30)        # not the saturation-floor leg
    assert max(growing) < (1 << 31)        # the pre-#653 threshold said STABLE
    r, rec = _run_lp12_comparator(
        _lp12_budget_trace("monitor-unstable", stability_peaks=growing,
                           stability_verdict=fp.stability_verdict(growing)),
        tmp_path)
    assert r.returncode == 0, r.stderr
    v = rec["results"]["unit1.lane0"]
    assert v["stability_model"] == "UNSTABLE"
    assert v["stability_engine"] == "BOUNDED"     # engine leg is fine
    assert v["stability"] == "FAIL"
    assert "FAIL" in rec["verdict"]


def test_comparator_refuses_trace_without_monitor_verdict(tmp_path):
    # Fail-closed: a trace predating `stability_verdict` cannot be graded on
    # the model leg and must never be defaulted to STABLE.
    r, rec = _run_lp12_comparator(
        _lp12_budget_trace("no-verdict", stability_verdict=None), tmp_path)
    assert r.returncode != 0
    assert "stability_verdict" in r.stderr and "Refusing" in r.stderr
    assert rec is None                     # no record written


def test_comparator_refuses_silent_engine_tap(tmp_path):
    # `engine_peak_lsb` is floored at 1 LSB, so an absent engine tap would
    # otherwise grade BOUNDED on no engine samples at all.
    r, rec = _run_lp12_comparator(
        _lp12_budget_trace("silent-tap", l2a={"n": 0, "engine_peak_lsb": 1}),
        tmp_path)
    assert r.returncode != 0
    assert "no engine tap samples" in r.stderr and "Refusing" in r.stderr
    assert rec is None


def test_lp12_runner_emits_the_monitor_verdict_the_comparator_reads():
    # The comparator's model leg reads a trace field the runner must emit
    # (the LP 24 dB and LP Moog runners already do).  Drive run_instance on
    # one synthetic block and check the field is the monitor's own verdict.
    import importlib.util
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo, "model", "voice", "filter_lp12",
                        "run_filter_leg.py")
    spec = importlib.util.spec_from_file_location("lp12_run_filter_leg", path)
    rfl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rfl)

    cm = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    coef = [{"unit": 0, "lane": 0, "sub": fp.SUBTYPE_DRIVEN, "first": True,
             "type": fp.TYPE_LP12, "cut": 0.0, "reso": 0.5,
             "C": [c / Q for c in cm.C], "dC": [d / Q for d in cm.dC]}]
    audio = [(i, 0.25 * math.sin(i / 7.0), 0.1 * math.sin(i / 7.0))
             for i in range(vm.BLOCK_SIZE_OS)]

    res = rfl.run_instance((0, 0), audio, coef)
    assert "stability_verdict" in res, "runner must emit the monitor verdict"
    assert res["stability_verdict"] == fp.stability_verdict(res["stability_peaks"])
    assert res["stability_verdict"] in ("STABLE", "UNSTABLE")
    # the engine leg's quantity is engine tap data, not a model state peak
    assert res["l2a"]["engine_peak_lsb"] != max(res["stability_peaks"])
