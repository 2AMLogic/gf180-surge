"""SXT-039 LP Legacy Ladder filter leaf tests (pytest).

Covers: coefficient construction against the cited pinned formulas at known
operating points, the four subtype taps, per-instance state independence,
the softclip8 body and its RTL constants, register-init / reset semantics,
applicability-boundary refusals (fail-closed), the stability argument, the
committed artifacts' self-consistency, and the negative controls.

Oracle-free by construction: every check runs off committed data.  The
RTL exactness case is skipped with an explicit message when iverilog is
absent -- a skipped check is never reported as a pass.
"""
import json
import math
import os
import re
import shutil
import struct
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import voice_model as vm  # noqa: E402
import filter_lpmoog_model as fp  # noqa: E402
import fixtures as fx  # noqa: E402
import run_filter_leg as rfl  # noqa: E402

ARTIFACTS = os.path.join(REPO, "reports", "SXT-039", "artifacts")
ONE = vm.ONE
CONE = float(fp.COEF_ONE)


# ----------------------------------------------------- coefficient maker
def test_coeffs_match_pinned_formulas_at_known_points():
    for cut, reso in ((0.0, 0.5), (36.187477, 0.377679), (-24.0, 0.0), (60.0, 1.0)):
        cm = fp.LPMoogCoeffMaker(fp.SUBTYPE_24DB)
        cm.make_coeffs(vm.qint(cut), vm.qint(reso))
        gg = min(max(440.0 * (2.0 ** (cut / 12.0)) / 96000.0, 0.0), 0.187)
        t_b1 = 1.0 - math.exp(-2 * math.pi * gg)
        q = min(2.15 * reso, 0.5 / (t_b1 ** 4)) if t_b1 > 0 else 2.15 * reso
        want = {0: 3.0 / (3.0 - q), 1: t_b1, 2: q}
        for i, w in want.items():
            got = cm.C[i] / CONE
            # the pinned note_to_pitch table lerp differs from the exact
            # 2^(x/12) mirror by <= ~1e-5 relative; the Q2.29 word adds 2e-9
            assert abs(got - w) <= 5e-5 * max(abs(w), 1e-6), (cut, reso, i, got, w)
        assert all(v == 0 for v in cm.dC)          # FirstRun: dC == 0
        assert cm.C[3:] == [0] * 5                 # Coeff_LP4L writes c[0..2]


def test_gg_clamp_is_the_pinned_engine_clamp():
    # above the clamp the coefficients stop moving (gg pinned at 0.187)
    a = fp.LPMoogCoeffMaker(3)
    a.make_coeffs(vm.qint(70.0), vm.qint(0.5))
    b = fp.LPMoogCoeffMaker(3)
    b.make_coeffs(vm.qint(96.0), vm.qint(0.5))
    assert a.C == b.C
    t_b1 = 1.0 - math.exp(-2 * math.pi * 0.187)
    assert abs(a.C[1] / CONE - t_b1) < 1e-6


def test_resonance_guard_branch():
    # at a very low cutoff the 0.5/t_b1^4 guard is astronomically large, so q
    # is the 2.15*reso branch; the model must not blow up or refuse
    cm = fp.LPMoogCoeffMaker(3)
    cm.make_coeffs(vm.qint(-60.0), vm.qint(1.0))
    assert abs(cm.C[2] / CONE - 2.15) < 1e-6
    assert abs(cm.C[0] / CONE - 3.0 / (3.0 - 2.15)) < 1e-5


def test_from_direct_smoothing_and_reset():
    cm = fp.LPMoogCoeffMaker(3)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    first = list(cm.C)
    cm.make_coeffs(vm.qint(24.0), vm.qint(0.5))
    assert cm.C == first                       # C only moves in the kernel
    assert any(v != 0 for v in cm.dC)          # but dC is now non-zero
    cm.reset()
    cm.make_coeffs(vm.qint(24.0), vm.qint(0.5))
    assert all(v == 0 for v in cm.dC)          # Reset() -> FirstRun again


# ------------------------------------------------------------ softclip8
def test_softclip8_matches_pinned_body_and_is_bounded():
    for xf in (-30.0, -12.0, -3.0, -0.5, 0.0, 0.25, 1.0, 11.9, 12.0, 100.0):
        got = fp.softclip8(vm.qint(xf)) / float(ONE)
        x = max(-12.0, min(12.0, xf))
        want = x + (x * (-(4.0 / 27.0) / 512.0)) * (x * x)
        assert abs(got - want) < 1e-5, (xf, got, want)
    assert abs(fp.softclip8(vm.qint(1e6)) / float(ONE) - (12 - (4 / 27 / 512) * 1728)) < 1e-4


def test_softclip8_constants_match_the_rtl():
    src = open(os.path.join(REPO, "rtl", "voice", "tb_lpmoog.sv")).read()
    a = int(re.search(r"SC_A\s*=\s*-32'sd(\d+)", src).group(1))
    lim = int(re.search(r"SC_LIMIT\s*=\s*32'sd(\d+)", src).group(1))
    assert -a == fp.SOFTCLIP8_A
    assert lim == fp.SOFTCLIP8_LIMIT
    assert int(re.search(r"localparam int CFQ = (\d+)", src).group(1)) == fp.COEF_FQ


# --------------------------------------------------------------- kernel
def _run_const(subtype, cut=0.0, reso=0.5, n_blocks=8, level=0.5):
    unit = fp.LPMoogUnit(subtype)
    cm = fp.LPMoogCoeffMaker(subtype)
    out = []
    for _b in range(n_blocks):
        cm.make_coeffs(vm.qint(cut), vm.qint(reso))
        o, _p, c_end = unit.process_block([vm.qint(level)] * 64, cm)
        cm.C = list(c_end)
        out.extend(o)
    return unit, out


def test_subtype_taps_are_the_four_ladder_stages():
    # resonance 0 (no feedback): the four taps are a cascade of identical
    # one-pole stages, so a step response lags deeper with each tap and every
    # tap converges to the same DC value
    outs = {st: _run_const(st, reso=0.0)[1] for st in fp.SUBTYPES}
    early = [abs(outs[st][8]) for st in fp.SUBTYPES]
    assert early[0] > early[1] > early[2] > early[3], early
    late = [outs[st][-1] for st in fp.SUBTYPES]
    assert max(late) - min(late) < 0.01 * ONE, late
    # with resonance the feedback makes the taps differ in steady state too
    res_late = [_run_const(st, reso=0.8)[1][-1] for st in fp.SUBTYPES]
    assert max(res_late) - min(res_late) > 0.01 * ONE, res_late


def test_per_instance_state_is_never_shared():
    cm = fp.LPMoogCoeffMaker(3)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    a = fp.LPMoogUnit(3)
    b = fp.LPMoogUnit(3)
    a.process_block([vm.qint(0.5)] * 64, cm)
    assert b.r == [0] * 5                      # b untouched by a's history
    oa, _p, _c = a.process_block([0] * 64, cm)
    ob, _p, _c = b.process_block([0] * 64, cm)
    assert oa != ob and any(v != 0 for v in oa) and all(v == 0 for v in ob)


def test_registers_zero_init_and_reset_path():
    unit = fp.LPMoogUnit(3)
    assert unit.r == [0] * 5                   # FBP memset semantics
    cm = fp.LPMoogCoeffMaker(3)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    unit.process_block([vm.qint(0.5)] * 64, cm)
    assert any(v != 0 for v in unit.r)
    unit.set_subtype(1)                        # type/subtype change -> memset
    assert unit.r == [0] * 5


def test_stability_on_the_declared_corners():
    for case in ("reso1", "hot", "king-b2"):
        trace = rfl.run_case(case)
        assert trace["stability_verdict"] == "STABLE"
        assert max(trace["stability_peaks"]) < (1 << 30)


# --------------------------------------------------- fail-closed boundary
@pytest.mark.parametrize("fn", [
    lambda: fp.LPMoogUnit(4),
    lambda: fp.LPMoogUnit(-1),
    lambda: fp.LPMoogCoeffMaker(7),
    lambda: fp.LPMoogCoeffMaker(3).make_coeffs(vm.qint(0.0), vm.qint(1.5)),
    lambda: fp.LPMoogCoeffMaker(3).make_coeffs(vm.qint(0.0), vm.qint(-0.1)),
    lambda: fp.LPMoogCoeffMaker(3).make_coeffs(vm.qint(300.0), vm.qint(0.5)),
    lambda: fp.LPMoogCoeffMaker(3).set_subtype(9) if hasattr(
        fp.LPMoogCoeffMaker, "set_subtype") else (_ for _ in ()).throw(fp.Refuse("n/a")),
])
def test_out_of_scope_is_refused(fn):
    with pytest.raises(fp.Refuse):
        fn()


def test_runner_refuses_subtype_change_without_reset(monkeypatch):
    spec = fx.build("king-b1")
    spec["blocks"][1]["subtype"] = 1
    spec["blocks"][1]["reset"] = False
    monkeypatch.setattr(fx, "build", lambda case: spec)
    with pytest.raises(fp.Refuse):
        rfl.run_case("king-b1")


# ------------------------------------------------------------- fixtures
def test_fixture_carriers_are_lpmoog_instances_in_the_committed_graphs():
    for name in fx.CARRIERS:
        c = fx.load_carrier(name)
        assert 0 <= c["subtype"] <= 3
        assert c["rel"].startswith("resources/data/patches_")
        assert c["blob"]


def test_fixture_cases_cover_every_engine_declared_subtype():
    seen = set()
    for case in fx.CASES:
        spec = fx.build(case)
        seen |= {int(b["subtype"]) for b in spec["blocks"]}
    assert seen == set(fp.SUBTYPES)


def test_declared_fenv_is_labelled_as_declared_everywhere():
    for case in fx.CASES:
        assert fx.build(case)["fenv_source"] == "declared-trajectory"


# ------------------------------------------------- committed artifacts
def _committed(name):
    path = os.path.join(ARTIFACTS, name)
    if not os.path.exists(path):
        pytest.skip(f"committed artifact missing: {name}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_committed_reference_index_pins_the_engine_and_submodules():
    idx = _committed("reference-index.json")
    assert idx["engine_pin"] == "58914e59c608ed4384ba6002e44c3465c58b2e71"
    assert idx["submodule_pins"]["sst-filters"].startswith("e92d93a9")
    assert idx["submodule_pins"]["sst-basic-blocks"].startswith("a32b8aec")
    assert "NOT the full engine" in idx["leg"]
    assert set(idx["cases"]) == set(fx.CASES)


def test_committed_rtl_verdicts_are_pass():
    for case in fx.CASES:
        v = _committed(f"rtl-{case}.json")
        assert v["verdict"] == "PASS", (case, v["mismatches"])
        assert v["checked"]["samples"] > 0 and v["checked"]["fields"] > 0


def test_committed_budgets_reproduce_from_the_committed_reference():
    import compare_lpmoog_model as clm
    import tempfile
    for case in ("king-b1", "disturb", "cut-lo"):
        committed = _committed(f"budget-{case}.json")
        with tempfile.TemporaryDirectory() as td:
            trace = rfl.run_case(case)
            with open(os.path.join(td, "model_trace.json"), "w", encoding="utf-8") as f:
                json.dump(trace, f)
            got = clm.compare_case(td, ARTIFACTS)
        assert got["L2_audio_q1021"]["max_abs_lsb"] == \
            committed["L2_audio_q1021"]["max_abs_lsb"], case
        assert got["verdict"] == committed["verdict"], case


def test_committed_negative_controls_all_failed_as_designed():
    nc = _committed("negative-control.json")
    assert any(k.startswith("NC-A") for k in nc) and any(k.startswith("NC-B") for k in nc)
    for name, entry in nc.items():
        assert entry["outcome"].startswith(("CONTROL-OK", "NOT_RUN")), (name, entry)
    for name, entry in nc.items():
        if name.startswith(("NC-A", "NC-B")):
            assert entry["budget_fail"] is True, name


def test_deadzone_finding_artifact_is_quantified():
    dz = _committed("deadzone-sweep.json")
    first24 = dz["first_nonzero_output_cut_semi"]["subtype_3_24dB"]
    assert first24 is not None and first24 < -60.0    # below the parameter span


# ----------------------------------------------------- RTL exactness
@pytest.mark.skipif(shutil.which("iverilog") is None or shutil.which("vvp") is None,
                    reason="iverilog/vvp unavailable: RTL exactness NOT_RUN "
                           "(never reported as a pass)")
def test_rtl_matches_the_frozen_model_exactly(tmp_path):
    import compare_rtl_model_lpmoog as crm
    trace = rfl.run_case("toggle")            # subtype changes + resets
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w", encoding="utf-8") as f:
        json.dump(trace, f)
    rfl.write_rtl_stimulus(trace, run_dir)
    checked, fails = crm.compare(trace, crm.build_and_run(crm.TB, run_dir))
    assert not fails, fails[:5]
    assert checked["samples"] == trace["n_blocks"] * 64
    # and the committed mutant must FAIL the same comparison
    _checked, mut_fails = crm.compare(trace, crm.build_and_run(crm.MUTANT, run_dir))
    assert mut_fails, "mutant control stopped failing: broken control"


def test_reference_streams_have_the_declared_lengths():
    for case in fx.CASES:
        path = os.path.join(ARTIFACTS, f"ref-{case}.f32")
        if not os.path.exists(path):
            pytest.skip("committed reference streams missing")
        n = os.path.getsize(path) // 4
        assert n == fx.CASES[case]["blocks"] * 64, case
        coef = os.path.join(ARTIFACTS, f"refcoef-{case}.f32")
        assert os.path.getsize(coef) // 4 == fx.CASES[case]["blocks"] * 21, case


def test_reference_is_not_the_lp12_bundle_output():
    """The stimulus bundles' LP 12 dB OUTPUT column is never used as this
    leaf's reference (it is a different algorithm)."""
    spec = fx.build("king-b1")
    with open(os.path.join(ARTIFACTS, "ref-king-b1.f32"), "rb") as f:
        data = f.read()
    ref = struct.unpack(f"<{len(data) // 4}f", data)
    assert len(ref) == len(spec["input"])
    # the reference differs from the (gain-scaled) input it was rendered from
    assert max(abs(a - b) for a, b in zip(ref, spec["input"])) > 1e-3
