"""SXT-038 LP 24 dB filter leaf tests (pytest).

Covers: coefficient construction against the cited pinned formulas at known
operating points (per subtype), the engine tuning-table semantics, the
per-subtype kernel register maps and clipgain slots, per-instance state
isolation, applicability-boundary refusals (fail-closed), the control-plane
equality guard, the case-extraction contract against the committed corpus,
the stability monitor, and the RTL comparator's mismatch detection.

These are unit/contract tests only.  They establish NEITHER claim (2)
(model-vs-pinned-code budgets — `tools/compare_lp24_model.py`, reference
bundles required) NOR claim (3) (musical quality — listening records only).
Reference-dependent budget checks are deliberately NOT pytest cases, so an
absent reference can never be reported as a pass.
"""
import importlib.util
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "model", "voice"))
sys.path.insert(0, os.path.join(ROOT, "model", "voice", "filter_lp24"))

import voice_model as vm  # noqa: E402
import filter_lp24_model as fp  # noqa: E402
import case_plan as cp  # noqa: E402

ONE = vm.ONE
Q = float(ONE)
CASES = os.path.join(ROOT, "reports", "SXT-038", "artifacts", "cases")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------- coefficient construction
def test_driven_coeffs_match_pinned_coeff_lp24_at_a_known_point():
    """Coeff_LP24 + Map4PoleResonance + ToCoupledForm, cutoff 0 st, reso 0.5."""
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    reso, freq = 0.5, 0.0
    gain = 1.0 - 0.5 * reso * reso                       # resoscale (2-pole form)
    reso_eff = reso * max(0.0, 1.0 - max(0.0, (freq - 58) * 0.05))
    q2inv = 1.0 - 1.05 * min(1.0, max(0.001, reso_eff))  # Map4PoleResonance
    sinu, cosi = fp.note_to_omega_d(freq)
    alpha = min(sinu * q2inv, math.sqrt(1.0 - cosi * cosi) - 0.0001)
    a0inv = 1.0 / (1.0 + alpha)
    a1 = -2.0 * cosi * a0inv
    a2 = (1.0 - alpha) * a0inv
    b0 = (1.0 - cosi) * 0.5 * gain * a0inv
    b1 = (1.0 - cosi) * gain * a0inv
    b2 = b0
    ar = 0.5 * -a1
    ai = max(0.5 * math.sqrt(-min(0.0, a1 * a1 - 4.0 * a2)), 8.0 * 1.192092896e-07)
    bb1 = b1 - a1 * b0
    bb2 = b2 - a2 * b0
    assert cm.C[0] == vm.qint(ar)
    assert cm.C[1] == vm.qint(ai)
    assert cm.C[2] == ONE
    assert cm.C[4] == vm.qint(bb1)
    assert cm.C[5] == vm.qint((bb1 * ar + bb2) / ai)
    assert cm.C[6] == vm.qint(b0)
    assert cm.C[7] == vm.qint((1.0 / 64.0) * 10.0 ** (0.05 * freq * 0.55))


def test_lp24_uses_map4pole_not_map2pole():
    """The LP24 leaf must differ from the landed LP12 leaf in exactly this way."""
    reso = 0.7
    m4 = 1.0 - 1.05 * min(1.0, max(0.001, reso))                       # 4-pole
    m2 = 1.0 - 1.05 * min(1.0, max(0.001, 1 - (1 - reso) ** 2))        # 2-pole
    assert abs(m4 - m2) > 1e-3
    assert fp._map4pole_resonance_d(reso, 0.0, fp.SUBTYPE_DRIVEN) == m4


def test_standard_uses_fourpole_overshoot_and_os_sample_rate():
    """Coeff_SVF(FourPole=true): overshoot 0.1 and f * 0.5 / dsamplerate_os."""
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_STANDARD)
    cm.make_coeffs(vm.qint(12.0), vm.qint(0.25))
    f = 440.0 * fp.note_to_pitch_ignoring_tuning_d(12.0)
    f1 = 2.0 * math.sin(math.pi * min(0.11, f * (0.5 / 96000.0)))
    r = math.sqrt(0.25)
    q1 = min(2.0 - r * 2.1 + f1 * f1 * 0.1 * 0.9, min(2.0, 2.0 - 1.52 * f1))
    assert cm.C[0] == vm.qint(f1)
    assert cm.C[1] == vm.qint(q1)
    assert cm.C[2] == vm.qint(0.1 * r * f1)
    assert cm.C[3] == vm.qint(1.0 - 0.65 * r)
    assert fp.SR_OS == 96000.0


def test_clean_lattice_and_clipscale():
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_CLEAN)
    cm.make_coeffs(vm.qint(-6.0), vm.qint(0.8))
    assert cm.C[7] == vm.qint(1.0 / 1024.0)          # clipscale(st_Clean)
    assert cm.C[2] > 0 and cm.C[3] > 0               # q1, q2 are magnitudes
    # Map4PoleResonance(st_Clean) = 2.5 - 2.3*clamp(reso)
    assert fp._map4pole_resonance_d(0.8, -6.0, fp.SUBTYPE_CLEAN) == 2.5 - 2.3 * 0.8


def test_note_to_omega_uses_the_engine_table_not_exact_sin():
    """At the top of the cutoff range the LUT differs from exact sin/cos by
    thousands of Q10.21 LSB; the model must follow the engine's table."""
    sinu, cosi = fp.note_to_omega_d(70.5)
    exact = math.sin(2 * math.pi * min(0.5, 440.0 * 2.0 ** (70.5 / 12.0) / 96000.0))
    assert abs(vm.qint(sinu) - vm.qint(exact)) > 100


def test_boundfreq_clamp_applies_to_lp24_but_not_to_the_svf_path():
    a = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    a.make_coeffs(vm.qint(120.0), vm.qint(0.3))
    b = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    b.make_coeffs(vm.qint(75.0), vm.qint(0.3))
    assert a.C == b.C                                  # clamped to +75
    c = fp.LP24CoeffMaker(fp.SUBTYPE_CLEAN)
    c.make_coeffs(vm.qint(-96.0), vm.qint(0.3))
    d = fp.LP24CoeffMaker(fp.SUBTYPE_CLEAN)
    d.make_coeffs(vm.qint(-55.0), vm.qint(0.3))
    assert c.C == d.C                                  # clamped to -55
    # The SVF (st_Standard) path takes no boundFreq clamp at the pin: below
    # the clamp edge its F1 still tracks the cutoff.  (Above ~+67 st the SVF's
    # own min(0.11, ...) argument clamp saturates F1, which is a different,
    # pinned clamp.)
    s1 = fp.LP24CoeffMaker(fp.SUBTYPE_STANDARD)
    s1.make_coeffs(vm.qint(-96.0), vm.qint(0.3))
    s2 = fp.LP24CoeffMaker(fp.SUBTYPE_STANDARD)
    s2.make_coeffs(vm.qint(-55.0), vm.qint(0.3))
    assert s1.C != s2.C


def test_from_direct_first_run_then_smoothing():
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.5))
    assert cm.dC == [0] * fp.N_COEF                    # FirstRun: dC = 0
    first = list(cm.C)
    cm.make_coeffs(vm.qint(24.0), vm.qint(0.5))
    assert cm.C == first                               # C only moves per sample
    assert any(v != 0 for v in cm.dC)                  # smoothing produced deltas
    cm.reset()
    cm.make_coeffs(vm.qint(24.0), vm.qint(0.5))
    assert cm.dC == [0] * fp.N_COEF                    # Reset -> FirstRun again


# ------------------------------------------------------------- kernel shape
def test_register_map_and_clipgain_slot_per_subtype():
    """R[2] is clipgain for SVF/coupled-form, R[4] for the lattice."""
    x = [vm.qint(0.25)] * 8
    for sub, clip_idx in ((fp.SUBTYPE_STANDARD, 2), (fp.SUBTYPE_DRIVEN, 2),
                          (fp.SUBTYPE_CLEAN, 4)):
        cm = fp.LP24CoeffMaker(sub)
        cm.make_coeffs(vm.qint(0.0), vm.qint(0.3))
        u = fp.LP24Unit(sub)
        assert u.r == [0] * fp.N_REG                   # FBP zero-init
        u.process_block(x, cm)
        assert u.r[clip_idx] >= fp.CLIP_FLOOR          # clipgain floor reached
        others = [i for i in range(fp.N_REG) if i != clip_idx]
        assert any(u.r[i] != 0 for i in others)        # state registers moved


def test_first_sample_seeds_no_state_because_clipgain_starts_at_zero():
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.3))
    u = fp.LP24Unit(fp.SUBTYPE_DRIVEN)
    u.process_block([vm.qint(0.5)], cm)
    assert u.r[0] == 0 and u.r[1] == 0 and u.r[3] == 0 and u.r[4] == 0


def test_per_instance_state_is_never_shared():
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.4))
    a = fp.LP24Unit(fp.SUBTYPE_DRIVEN)
    b = fp.LP24Unit(fp.SUBTYPE_DRIVEN)
    a.process_block([vm.qint(0.4)] * 64, cm)
    b.process_block([0] * 64, cm)
    assert a.r != b.r
    # the silent instance kept its own (zero) state: nothing leaked from `a`
    assert [b.r[i] for i in (0, 1, 3, 4)] == [0, 0, 0, 0]
    assert any(a.r[i] != 0 for i in (0, 1, 3, 4))


def test_subtype_change_zeroes_the_registers():
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    cm.make_coeffs(vm.qint(0.0), vm.qint(0.4))
    u = fp.LP24Unit(fp.SUBTYPE_DRIVEN)
    u.process_block([vm.qint(0.4)] * 64, cm)
    assert any(v != 0 for v in u.r)
    u.set_subtype(fp.SUBTYPE_CLEAN)
    assert u.r == [0] * fp.N_REG


def test_qmul_counts_per_subtype():
    cm = {s: fp.LP24CoeffMaker(s) for s in fp.SUBTYPES}
    counts = {}
    for s in fp.SUBTYPES:
        cm[s].make_coeffs(vm.qint(0.0), vm.qint(0.3))
        u = fp.LP24Unit(s)
        u.process_block([vm.qint(0.1)] * 64, cm[s])
        counts[s] = u.qmul_count // 64
    assert counts == {fp.SUBTYPE_STANDARD: 19, fp.SUBTYPE_DRIVEN: 22,
                      fp.SUBTYPE_CLEAN: 28}


# --------------------------------------------------- fail-closed boundaries
def test_out_of_scope_requests_are_refused_not_clamped():
    import pytest
    for sub in (3, -1, 9):
        with pytest.raises(fp.Refuse):
            fp.LP24CoeffMaker(sub)
        with pytest.raises(fp.Refuse):
            fp.LP24Unit(sub)
    cm = fp.LP24CoeffMaker(fp.SUBTYPE_DRIVEN)
    for reso in (1.5, -0.1):
        with pytest.raises(fp.Refuse):
            cm.make_coeffs(vm.qint(0.0), vm.qint(reso))
    for cut in (300.0, -300.0):
        with pytest.raises(fp.Refuse):
            cm.make_coeffs(vm.qint(cut), vm.qint(0.3))


def test_stability_monitor_flags_growth_and_saturation():
    assert fp.stability_verdict([1000] * 32) == "STABLE"
    assert fp.stability_verdict([1 << 30]) == "UNSTABLE"
    grow = [int((1 << 21) * (4.0 ** i)) for i in range(20)]
    assert fp.stability_verdict(grow) == "UNSTABLE"


# ------------------------------------------------------- case / plan contract
def test_committed_cases_cover_all_three_subtypes_and_the_named_carriers():
    subs, rels = set(), set()
    for name in os.listdir(CASES):
        case = cp.load_case(os.path.join(CASES, name))
        assert case["filter"]["type"] == 2
        ov = case.get("overrides", {})
        subs.add(int(ov.get("subtype", case["filter"]["subtype"])))
        if "toggle_subtype" in ov:
            subs.add(int(ov["toggle_subtype"]))
        rels.add(case["carrier"]["rel"])
    assert subs == {0, 1, 2}
    for named in ("Edges Rhythm.fxp", "House Of Chords.fxp", "Main Brass.fxp"):
        assert any(r.endswith(named) for r in rels), named


def test_plan_control_words_are_float32_and_reset_starts_each_segment():
    case = cp.load_case(os.path.join(CASES, "phase1.json"))
    plan = cp.build_plan(case)
    assert len(plan) == case["stimulus"]["blocks"]
    assert plan[0]["reset"] is True
    assert sum(1 for p in plan if p["reset"]) == 1 + max(p["seg"] for p in plan)
    assert all(cp.f32(p["cut"]) == p["cut"] for p in plan)
    # keytrack + env-mod actually move the cutoff on this carrier
    assert len({p["cut"] for p in plan}) > 10


def test_plan_refuses_a_non_lp24_case():
    import copy
    import pytest
    case = copy.deepcopy(cp.load_case(os.path.join(CASES, "edges.json")))
    case["filter"]["type"] = 1
    with pytest.raises(cp.Refuse):
        cp.build_plan(case)


def test_extractor_reproduces_the_committed_cases():
    ex = _load("lp24_extract", "model/voice/filter_lp24/extract_inputs.py")
    graphs = ex.load_graphs()          # also verifies the corpus sha256
    for name, blob, scene, unit, bundle, seq in ex.CARRIERS:
        case = ex.carrier_case(name, blob, scene, unit, bundle, seq, graphs)
        committed = cp.load_case(os.path.join(CASES, f"{name}.json"))
        assert case["filter"] == committed["filter"]
        assert case["carrier"] == committed["carrier"]


# ------------------------------------------------------- RTL comparator wiring
def test_rtl_comparator_detects_a_single_bit_difference():
    cmp_mod = _load("lp24_cmp", "tools/compare_rtl_model_lp24.py")
    trace = {"trace_blocks": [{"b": 0, "subtype": 1, "out_model": [5, 6],
                               "after": {"r": [1, 2, 3, 4, 5],
                                         "C_end": [0] * 8}}]}
    good = "Y 0 0 5\nY 0 1 6\nT 0 1 1 2 3 4 5 0 0 0 0 0 0 0 0\n"
    bad = "Y 0 0 5\nY 0 1 7\nT 0 1 1 2 3 4 5 0 0 0 0 0 0 0 0\n"
    import tempfile
    for text, want_fail in ((good, False), (bad, True)):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text)
            path = f.name
        checked, fails = cmp_mod.compare(trace, path)
        os.unlink(path)
        assert bool(fails) is want_fail
        assert checked["samples"] == 2


def test_committed_rtl_verdicts_are_exact_where_present():
    art = os.path.join(ROOT, "reports", "SXT-038", "artifacts")
    seen = 0
    for name in sorted(os.listdir(art)):
        if not (name.startswith("rtl-") and name.endswith(".json")):
            continue
        with open(os.path.join(art, name), encoding="utf-8") as f:
            v = json.load(f)
        assert v["verdict"] == "PASS" and v["mismatches"] == 0, name
        assert v["checked"]["samples"] > 0 and v["checked"]["fields"] > 0
        seen += 1
    assert seen >= 11


def test_committed_negative_controls_all_failed_their_target_check():
    path = os.path.join(ROOT, "reports", "SXT-038", "artifacts",
                        "negative-controls.json")
    with open(path, encoding="utf-8") as f:
        nc = json.load(f)
    assert nc["all_controls_ok"] is True
    assert all(c["control_ok"] for c in nc["controls"])
    kinds = {c["control"] for c in nc["controls"]}
    assert {"NC-A", "NC-B", "NC-C", "NC-D", "NC-E"} <= kinds
