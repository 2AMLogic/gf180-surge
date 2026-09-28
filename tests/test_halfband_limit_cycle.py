"""F-176-2 (#181): the shared HalfbandD2 zero-input limit cycle, DECLARED.

Issue #181 asked for one decision, recorded per the SXT-017 visible-contract
rule: (a) declare the limit cycle with a bound measured over a declared input
sweep, or (b) change the decimator's rounding so the zero-input state decays
to zero. The disposition taken was **(a)**. These tests are what stops that
declaration from rotting:

  * the harness must still measure the property the declaration describes, on
    the committed class, with the settled amplitude obtained by state
    recurrence (a proof) rather than from a finite tail;
  * the REQUIRED failure control must stay live -- zeroing the decimator's
    state at every block boundary must drive the measured amplitude to 0, and
    a sweep with nothing non-zero in it must also FAIL the control;
  * the committed artifact must be internally coherent and its headline bound
    must be the bound the READMEs and leaf records quote;
  * the bound must stay below one int16 LSB. If it ever does not, that is the
    issue's escalate-to-#12 condition, and these tests must fail rather than
    let a stale bound stand;
  * because option (a) was chosen, `HalfbandD2` must still HAVE the limit
    cycle. A future option-(b) change makes these tests fail loudly instead of
    silently contradicting every record listed in section 6 of the evidence.

Nothing here establishes any verdict: no fidelity, preset-support or
musical-quality claim is made or checked. The one RTL-touching test asserts
claim (1) only (RTL == frozen model, exact) and is skipped without iverilog.
"""
import json
import os
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import measure_halfband_limit_cycle as M  # noqa: E402
import voice_model as vm  # noqa: E402

EVIDENCE = os.path.join(REPO, "reports", "halfband-limit-cycle", "EVIDENCE.md")
ARTIFACT = os.path.join(REPO, "reports", "halfband-limit-cycle", "artifacts",
                        "zero-input-limit-cycle-sweep.json")
CONTROL_TRANSCRIPT = os.path.join(REPO, "reports", "halfband-limit-cycle",
                                  "artifacts", "failure-control.txt")

# Every place the declaration must be readable from, per the third acceptance
# box of #181 ("where a reader of the affected leaves will see it").
DECLARATION_SITES = [
    os.path.join(REPO, "model", "voice", "README.md"),
    os.path.join(REPO, "model", "oscillators", "classic", "README.md"),
    os.path.join(REPO, "model", "oscillators", "sine", "README.md"),
    os.path.join(REPO, "model", "oscillators", "wavetable", "README.md"),
    os.path.join(REPO, "reports", "sxt-022", "EVIDENCE.md"),
    os.path.join(REPO, "reports", "sxt-026a", "EVIDENCE.md"),
    os.path.join(REPO, "reports", "SXT-033", "EVIDENCE.md"),
    os.path.join(REPO, "reports", "SXT-040", "EVIDENCE.md"),
    os.path.join(REPO, "reports", "sxt-026", "EVIDENCE.md"),
]

INT16_LSB_Q21 = vm.ONE // 32768          # 64 Q10.21 LSB

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None,
                                    reason="iverilog not available")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def flat(path):
    return " ".join(read(path).split())


def artifact():
    with open(ARTIFACT, encoding="utf-8") as f:
        return json.load(f)


# A small but structurally complete slice of the declared sweep: both signs of
# the range-end DC case (which is a worst case), a passband and a stopband
# sine, a square, and one noise seed. Short drive so the whole module stays
# fast; the committed artifact carries the full 315-case sweep.
def small_sweep_cases(n_drive=8 * M.BLOCK_OS):
    keep = ("dc a=+8", "dc a=-8", "dc a=+0.01",
            "sine f=0.1000 a=1", "sine f=0.3200 a=1", "sine f=0.5000 a=1",
            "square f=0.2550 a=0.5", "noise a=0.5 seed=3")
    cases = [c for c in M.declared_cases(n_drive) if c["case"] in keep]
    assert len(cases) == len(keep), sorted(c["case"] for c in cases)
    return cases


# ------------------------------------------------ the property is still real

def test_the_committed_class_still_holds_a_zero_input_limit_cycle():
    """Option (a) was chosen, so the cycle must still be there. If a future
    change makes the decimator decay to zero, that is option (b) and every
    record listed in EVIDENCE section 6 becomes wrong -- fail here first."""
    m = M.measure_case(M.stim_dc(8.0, 8 * M.BLOCK_OS))
    assert m["status"] == "MEASURED", m
    assert m["settled_peak_q21"] > 0, \
        "HalfbandD2 now settles to zero: #181's option (a) declaration and " \
        "every record citing it must be revised (that is an SXT-017/#12 act)"
    assert m["cycle_period_out_samples"] == 2, m
    assert m["settled_peak_q21"] < INT16_LSB_Q21, \
        "settled amplitude reached one int16 LSB: escalate to #12 (#181 " \
        "stop condition), do not restate the bound"


def test_settled_amplitude_comes_from_a_state_recurrence_not_a_finite_tail():
    """The measurement must be a proof about the infinite future. A recurrence
    means the block sequence repeats forever by construction; re-running the
    recorded cycle from the recurring state must reproduce it exactly."""
    xs = M.stim_dc(8.0, 8 * M.BLOCK_OS)
    m = M.measure_case(xs)
    hb = vm.HalfbandD2()
    for i in range(0, len(xs), M.BLOCK_OS):
        hb.process(xs[i:i + M.BLOCK_OS])
    for _ in range(m["lead_in_blocks"]):
        hb.process([0] * M.BLOCK_OS)
    state_at_cycle_start = M._state(hb)
    out = []
    for _ in range(m["cycle_blocks"]):
        out += hb.process([0] * M.BLOCK_OS)
    assert M._state(hb) == state_at_cycle_start, \
        "the recorded cycle does not return the filter to its own state"
    p = m["cycle_period_out_samples"]
    assert all(out[i] == out[i % p] for i in range(len(out)))
    assert max(abs(s) for s in out[:p]) == m["settled_peak_q21"]


def test_no_verdict_is_reported_rather_than_zero_when_the_cap_is_too_low():
    """A test that did not resolve must never be reported as a pass, and a
    cycle that was not found must never be reported as amplitude 0."""
    m = M.measure_case(M.stim_dc(8.0, 8 * M.BLOCK_OS), max_silence_blocks=1)
    assert m["status"] == "NO_VERDICT"
    assert m["settled_peak_q21"] is None
    assert "NOT zero" in m["note"]


# ------------------------------------------------------- the failure control

def test_failure_control_zeroing_state_at_block_boundaries_measures_zero():
    """#181's required control: if this does not drive every settled amplitude
    to 0, the harness is observing the fixture, not the filter's state."""
    cases = small_sweep_cases()
    sweep = M.run_sweep(cases)
    control = M.run_sweep(cases, cls=M.ZeroedAtBlockBoundary)
    assert all(r["status"] == "MEASURED" for r in sweep + control)
    assert all(r["settled_peak_q21"] == 0 for r in control), \
        [r["case"] for r in control if r["settled_peak_q21"]]
    assert any(r["settled_peak_q21"] > 0 for r in sweep)
    assert M.failure_control(sweep, control)["verdict"] == "PASS"


def test_failure_control_is_two_sided_and_fails_closed():
    """A control that drives zero to zero demonstrates nothing, and a control
    leg that itself rings must FAIL. Both mutants must FAIL the control."""
    cases = small_sweep_cases()
    sweep = M.run_sweep(cases)
    control = M.run_sweep(cases, cls=M.ZeroedAtBlockBoundary)
    # (i) nothing non-zero in the uncontrolled sweep -> FAIL
    assert M.failure_control([dict(r, settled_peak_q21=0) for r in sweep],
                             control)["verdict"] == "FAIL"
    # (ii) a control leg that still rings -> FAIL
    assert M.failure_control(sweep, [dict(r, settled_peak_q21=7)
                                     for r in control])["verdict"] == "FAIL"
    # (iii) an unresolved control case is not a pass either
    assert M.failure_control(
        sweep, [dict(r, status="NO_VERDICT", settled_peak_q21=None)
                for r in control])["verdict"] == "FAIL"


def test_float64_contrast_shows_the_dead_band_is_the_quantizer():
    """Same recursion, same quoted coefficients, no Q10.21 quantization: the
    tail must decay below one Q10.21 LSB. This is NOT a pinned-kernel claim
    and the leg must keep saying so."""
    cases = small_sweep_cases()
    sweep = M.run_sweep(cases)
    fc = M.float_contrast(cases, sweep, silence_blocks=256)
    assert fc["cases"] > 0
    assert fc["all_float_tails_round_to_zero_q21"] is True
    assert fc["pinned_kernel_zero_input_measurement"] == "NOT_RUN"
    assert "NOT the pinned kernel" in fc["is_not"]


# -------------------------------------------- the committed artifact coheres

def test_committed_artifact_is_internally_coherent():
    a = artifact()
    assert a["format"] == M.FORMAT and a["issue"] == 181
    assert a["finding"] == "F-176-2"
    s = a["sweep"]["summary"]
    rows = a["sweep"]["cases"]
    assert s["cases"] == len(rows) == 315
    assert s["cases_unresolved"] == []
    assert s["cases_measured"] == len(rows)
    peaks = [r["settled_peak_q21"] for r in rows]
    assert all(p is not None for p in peaks)
    assert s["worst_settled_peak_q21"] == max(peaks)
    assert s["cases_with_nonzero_limit_cycle"] == sum(1 for p in peaks if p)
    assert s["int16_lsb_in_q21"] == INT16_LSB_Q21
    assert s["worst_below_one_int16_lsb"] is True
    # the sweep is a SWEEP: multiple amplitudes, frequencies including the
    # stopband (> 0.25 of the input rate), and noise, each followed by silence
    fams = {r["family"] for r in rows}
    assert {"impulse", "dc", "sine", "square", "two_tone", "noise"} <= fams
    amps = {abs(r["params"]["amp"]) for r in rows if "amp" in r["params"]}
    assert len(amps) >= 8 and max(amps) == 8.0
    freqs = {r["params"]["f_of_input_rate"] for r in rows
             if "f_of_input_rate" in r["params"]}
    assert any(f > 0.25 for f in freqs) and any(f < 0.25 for f in freqs)
    assert a["declared_input_range"]["bound_q21"] == vm.qint(8.0)
    assert a["failure_control"]["verdict"] == "PASS"
    assert a["failure_control"]["control_cases_nonzero"] == 0
    assert a["failure_control"]["uncontrolled_nonzero_cases"] > 0
    assert a["float_contrast"]["pinned_kernel_zero_input_measurement"] \
        == "NOT_RUN"


def test_committed_artifact_is_strict_json_with_no_infinity_tokens():
    """The repo forbids non-standard JSON tokens in committed report artifacts
    (tests/test_stereo_tail_gate.py scans reports/**/*.json). A dBFS of exact
    silence must be `null` with a stated reason, not `-Infinity`."""
    def reject(tok):
        raise AssertionError("non-standard JSON token %r in %s"
                             % (tok, os.path.relpath(ARTIFACT, REPO)))
    with open(ARTIFACT, encoding="utf-8") as f:
        a = json.load(f, parse_constant=reject)
    zero = [r for r in a["sweep"]["cases"] if r["settled_peak_q21"] == 0]
    assert zero, "no exact-zero case left to check the null-dBFS path"
    for r in zero:
        assert r["settled_peak_dbfs"] is None, r["case"]
        assert r["settled_peak_dbfs_is_null_because"], r["case"]


def test_committed_artifact_worst_case_reproduces_on_the_committed_class():
    """Re-derive the headline bound from the committed class, case by case, for
    every case the artifact records as a worst case."""
    a = artifact()
    worst = a["sweep"]["summary"]["worst_settled_peak_q21"]
    by_case = {c["case"]: c for c in
               M.declared_cases(a["method"]["drive_input_samples"])}
    checked = 0
    for name in a["sweep"]["summary"]["worst_cases"]:
        m = M.measure_case(by_case[name]["samples"])
        assert m["status"] == "MEASURED", name
        assert m["settled_peak_q21"] == worst, (name, m["settled_peak_q21"])
        checked += 1
    assert checked > 0


def test_committed_artifact_records_the_rtl_check_as_exact():
    """Second acceptance box: the RTL copies were CHECKED, not assumed. The
    settled region must be inside the compared window with zero mismatches."""
    a = artifact()
    assert "rtl_leg" in a, "the committed artifact has no RTL leg"
    leg = a["rtl_leg"]
    assert leg["verdict"] == "PASS"
    assert leg["cascade_text_identical_across_copies"] is True
    files = {c["file"] for c in leg["copies"]}
    assert files == set(M.RTL_COPIES)
    for c in leg["copies"]:
        assert c["verdict"] == "PASS", c["file"]
        assert c["settled_region_samples_compared"] > 0, c["file"]
        assert c["settled_region_mismatching_samples"] == 0, c["file"]
        assert c["unexplained_mismatching_samples"] == 0, c["file"]
        assert c["settled_peak_disagreements"] == [], c["file"]


def test_committed_artifact_records_each_leafs_ring_out_window():
    """The acceptance box also asks whether the ring-out falls outside any
    leaf's compared window -- so every leaf leg must carry a verdict, that
    question must be answered from the leaf's OWN committed comparator counts
    (never assumed), and a leg that did not run must read NOT_RUN rather than
    an implied pass."""
    a = artifact()
    assert "leaf_legs" in a, "the committed artifact has no in-situ leaf legs"
    assert len(a["leaf_legs"]) == len(M.LEAF_LEGS)
    for row in a["leaf_legs"]:
        assert row["status"] in ("MEASURED", "NOT_RUN"), row
        if row["status"] != "MEASURED":
            continue
        leaf = row["leaf"]
        assert row["blocks_after_last_voice_death"] > 0, leaf
        assert row["ring_out_region_exists_in_this_render"] is True, leaf
        assert isinstance(row["post_death_mono_peak_q21"], int), leaf
        summary = row["committed_comparator_summary"]
        assert summary["verdict"] in ("PASS", "FAIL", "NOT_RUN"), leaf
        answer = row["ring_out_inside_committed_comparator_window"]
        if summary["verdict"] == "NOT_RUN":
            # a comparator that did not run answers nothing
            assert answer is None, leaf
            continue
        assert summary["verdict"] == "PASS", leaf
        assert summary["mismatches"] == 0, leaf
        assert answer is True, leaf
        assert row["committed_comparator_mono_samples_compared"] \
            >= row["render_mono_samples"], leaf


# ----------------------------------------- the declaration is where it says

def test_evidence_record_states_option_a_and_the_measured_bound():
    a = artifact()
    worst = a["sweep"]["summary"]["worst_settled_peak_q21"]
    f = flat(EVIDENCE)
    assert "option (a)" in f and "F-176-2" in f
    assert "%d Q10.21 LSB" % worst in f, \
        "EVIDENCE does not quote the measured worst case %d" % worst
    assert "0.5625 int16 LSB" in f
    # the three claims stay separated, and what is NOT_RUN says so
    assert "NOT_RUN" in f
    assert "no preset-support" in f.lower() or "no** preset-support" in f.lower()


def test_every_affected_record_carries_the_declaration_and_the_bound():
    a = artifact()
    worst = a["sweep"]["summary"]["worst_settled_peak_q21"]
    for path in DECLARATION_SITES:
        f = flat(path)
        rel = os.path.relpath(path, REPO)
        assert "F-176-2" in f, rel
        assert "#181" in f, rel
        assert "%d Q10.21 LSB" % worst in f, \
            "%s does not quote the measured bound %d Q10.21 LSB" % (rel, worst)
        assert "reports/halfband-limit-cycle" in f, rel


def test_declaration_routes_the_arithmetic_change_to_the_contract_owner():
    """Option (b) must stay visibly owned by SXT-017 / #12 everywhere the
    property is declared -- otherwise a later reader could 'just fix it'."""
    for path in [os.path.join(REPO, "model", "voice", "README.md"), EVIDENCE]:
        f = flat(path)
        assert "#12" in f, os.path.relpath(path, REPO)
        assert "contract revision" in f, os.path.relpath(path, REPO)


def test_failure_control_transcript_is_committed():
    f = read(CONTROL_TRANSCRIPT)
    assert "ZeroedAtBlockBoundary" in f
    assert "PASS" in f


# --------------------------------------------------------- claim (1), gated

@needs_iverilog
def test_rtl_copies_reproduce_the_settled_amplitude_exactly():
    """Claim (1) only: each RTL copy's own decimator text, spliced VERBATIM,
    must match the frozen model over the settled region. Small case set so
    this stays a few seconds; the committed artifact carries all 315."""
    cases = small_sweep_cases()
    sweep = M.run_sweep(cases)
    leg = M.rtl_leg(cases, sweep, "/tmp/hblc-test-rtl")
    assert leg["cascade_text_identical_across_copies"] is True, \
        "the three RTL copies' cascade text has diverged"
    for c in leg["copies"]:
        assert c["settled_region_samples_compared"] > 0, c["file"]
        assert c["settled_region_mismatching_samples"] == 0, c["file"]
        assert c["unexplained_mismatching_samples"] == 0, c["file"]
    assert leg["verdict"] == "PASS"
