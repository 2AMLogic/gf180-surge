"""SXT-026 (#176): the wavetable leaf's declared decimation/RTL boundary.

Issue #176 recorded two scope gaps in the SXT-026 leaf (#19):

  1. `rtl/oscillators/wavetable/` implements no post-oscillator stage, so the
     leaf's `rtl_vs_model: PASS` was silently oscillator-scoped -- the ledger
     note and the evidence record did not say so.
  2. The frozen model decimates PER VOICE SLICE where the pinned engine
     decimates PER SCENE, and the size of that difference was unmeasured.

The disposition was option (b): declare both as explicit, bounded deviations
with the difference measured (`tools/measure_wt_decimation_stage.py`). These
tests are what stops that declaration from rotting:

  * the boundary statements must actually be present in the ledger note, the
    evidence record, the model README, the RTL headers and the comparator;
  * the RTL must actually still contain no decimator -- a structural check, so
    that adding one (option (a)) fails these tests rather than silently
    contradicting the declaration;
  * the committed measurement artifact must be internally coherent, and its
    failure control must be live (a bit-identical case set must FAIL it).

Nothing here establishes any verdict: no fidelity, preset-support,
RTL-vs-model, or musical-quality claim is made or checked.
"""
import json
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import measure_wt_decimation_stage as M  # noqa: E402

LEDGER = os.path.join(REPO, "reports", "coverage-v1", "leaf-verification.json")
EVIDENCE = os.path.join(REPO, "reports", "sxt-026", "EVIDENCE.md")
README = os.path.join(REPO, "model", "oscillators", "wavetable", "README.md")
RTLDIR = os.path.join(REPO, "rtl", "oscillators", "wavetable")
COMPARATOR = os.path.join(REPO, "tools", "compare_wt_rtl_model.py")
ARTIFACT = os.path.join(REPO, "reports", "sxt-026", "artifacts",
                        "decimation-stage-per-slice-vs-per-scene.json")
RUNNER = os.path.join(REPO, "model", "oscillators", "wavetable",
                      "run_model.py")

ORACLE_DATA = os.environ.get(
    "ORACLE_SURGE_DATA",
    "/Users/joseph/dev/surge-xt-oracle/surge/resources/data")
TRIANGLE_REL = "wavetables/Basic/Triangle.wt"
ORACLE_PRESENT = os.path.isfile(os.path.join(ORACLE_DATA, TRIANGLE_REL))
needs_oracle = pytest.mark.skipif(
    not ORACLE_PRESENT, reason="external pinned oracle asset root not present")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def artifact():
    with open(ARTIFACT, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------- the boundary is stated

def test_ledger_note_states_the_oscillator_only_rtl_boundary():
    """The osc:Wavetable note must say what its rtl_vs_model PASS covers."""
    with open(LEDGER, encoding="utf-8") as f:
        table = json.load(f)
    leaf = table["leaves"]["osc:Wavetable"]
    note = leaf["note"]
    # the verdicts themselves are unchanged by #176
    assert leaf["verification"]["rtl_vs_model"] == "PASS"
    assert leaf["verification"]["model_vs_reference"] == "PARTIAL"
    low = note.lower()
    assert "oscillator output" in low, note
    assert "48 khz" in low, note
    assert "mono_block" in low, note
    assert "per voice slice" in low and "per scene" in low, note
    assert "sxt-017" in low, note
    # the measurement must be cited, not merely asserted
    assert "decimation-stage-per-slice-vs-per-scene.json" in note, note


def test_evidence_record_states_the_boundary_and_the_measurement():
    text = read(EVIDENCE)
    assert "Declared scope boundary (issue #176)" in text
    assert "## 2a. Per-slice vs per-scene decimation" in text
    assert "mono_block" in text
    # the claim-discipline header must carry the scope, not only section 2
    head = text.split("## 0.")[0]
    assert "NOT the 48 kHz render" in head, "claim discipline is unscoped"
    # section 8 must refuse the 48 kHz RTL claim explicitly
    not_established = text.split("## 8.")[-1]
    assert "No RTL-vs-model claim for the 48 kHz output" in not_established
    # the measured worst case must be in the record, not only in the JSON
    a = artifact()
    assert ("%.1f" % abs(a["summary"]["rms_diff_dbfs_worst"])) in text
    assert str(a["summary"]["max_abs_diff_q21_worst"]) in text


def test_model_readme_declares_both_deviations():
    text = read(README)
    assert "PER VOICE SLICE, not per scene" in text
    assert "RTL coverage boundary (declared, issue #176)" in text
    assert "no halfband/decimator" in text
    assert "tools/measure_wt_decimation_stage.py" in text


def test_rtl_headers_declare_the_missing_stage():
    for name in ("wavetable_core.sv", "tb_wavetable.sv"):
        text = read(os.path.join(RTLDIR, name))
        assert "DECLARED SCOPE (issue #176" in text, name
        assert "tb_voice.sv" in text, name


def test_comparator_carries_a_machine_readable_scope():
    import compare_wt_rtl_model as C
    assert set(C.SCOPE) >= {"covers", "does_not_cover", "declared_in", "issue"}
    assert C.SCOPE["issue"] == 176
    assert "96 kHz" in C.SCOPE["covers"]
    assert "mono_block" in C.SCOPE["does_not_cover"]
    assert "48 kHz" in C.SCOPE["does_not_cover"]
    # and it must be emitted with every verdict, not merely defined
    assert '"scope": SCOPE,' in read(COMPARATOR)


# --------------------------------------------- the declaration is still true

def test_wavetable_rtl_still_contains_no_decimator():
    """Structural, not prose: the declared deviation says this leaf's RTL has
    no halfband/decimator/48 kHz stage. If one is ever added (option (a)),
    this test must fail so the declaration is revised rather than contradicted
    silently."""
    tokens = re.compile(r"halfband|halfrate|half_rate|decimat|process_block_d2"
                        r"|\bmono_block\b", re.I)
    for name in sorted(os.listdir(RTLDIR)):
        if not name.endswith(".sv"):
            continue
        for lineno, line in enumerate(read(os.path.join(RTLDIR, name))
                                      .splitlines(), 1):
            code = line.split("//", 1)[0]          # comments may DISCUSS it
            assert not tokens.search(code), (
                "%s:%d implements a decimation/48 kHz stage, contradicting "
                "declared deviation 8 in model/oscillators/wavetable/"
                "README.md: %r" % (name, lineno, line.strip()))


def test_comparator_does_not_read_the_48khz_samples():
    """The exactness harness must not start comparing the model trace's 48 kHz
    streams without the declaration moving with it. Looks for a LOOKUP of the
    key (a quoted token), so the docstring's and SCOPE's prose mentions of it
    do not trip the check."""
    code = read(COMPARATOR)
    for key in ("mono_block", "samples16"):
        assert not re.search(r"""["']%s["']""" % key, code), (
            "compare_wt_rtl_model.py now reads the model trace's %r stream; "
            "declared deviation 8 (oscillator-only RTL boundary) must be "
            "revised together with it" % key)


# ------------------------------------------------- the measurement artifact

def test_measurement_artifact_covers_the_nine_committed_fixtures():
    a = artifact()
    assert a["format"] == "sxt-026-decimation-stage-measurement/1"
    assert a["issue"] == 176
    assert a["partial_run"] is False, "a capped run must not be committed"
    assert "MODEL-vs-MODEL ONLY" in a["claim_scope"]
    assert len(a["cases"]) == 9
    # exactly the (inputs, sequence) pairs that have a committed model render
    art_dir = os.path.join(REPO, "reports", "sxt-026", "artifacts")
    committed = {n[len("model-"):-len(".wav")]
                 for n in os.listdir(art_dir)
                 if n.startswith("model-") and n.endswith(".wav")}
    measured = {"%s__%s" % (os.path.basename(c["inputs"])[:-len(".json")],
                            c["sequence"]) for c in a["cases"]}
    assert measured == committed, (measured ^ committed)
    for c in a["cases"]:
        assert c["leg_a_runner_equality"].startswith("PASS"), c["case"]
        assert len(c["leg_a_render_sha256"]) == 64


def test_measured_difference_is_bounded_and_stated_consistently():
    """The recorded per-case numbers must agree with the summary and with the
    'below one int16 LSB' reading the README/EVIDENCE state."""
    a = artifact()
    cases = a["cases"]
    assert a["summary"]["max_abs_diff_lsb_worst"] == max(
        c["max_abs_diff_lsb"] for c in cases)
    assert a["summary"]["max_abs_diff_q21_worst"] == max(
        c["max_abs_diff_q21"] for c in cases)
    # one int16 LSB is 64 Q10.21 LSB; a case with a zero int16 residual may
    # not carry a Q10.21 residual that would have crossed that boundary
    for c in cases:
        if c["max_abs_diff_lsb"] == 0:
            assert c["max_abs_diff_q21"] < 64, c["case"]
    # the declared bound in the README/EVIDENCE prose
    assert a["summary"]["max_abs_diff_lsb_worst"] <= 1.0


def test_state_lifetime_leg_is_measured_where_it_exists():
    """Every case must record the after-last-voice-death region, and the
    per-slice leg must be exactly silent there (its filter state died with the
    voice) -- that asymmetry is the state-lifetime half of the deviation."""
    for c in artifact()["cases"]:
        post = c["after_last_voice_death"]
        assert post is not None, c["case"]
        assert post["per_slice_peak_q21"] == 0, c["case"]
        assert post["frames"] > 0, c["case"]


def test_failure_control_verdict_is_pass_on_the_committed_cases():
    a = artifact()
    assert a["failure_control"]["verdict"] == "PASS"
    assert a["failure_control"]["differing_qualifying_cases"] >= 1
    # recomputing it from the committed cases must agree
    assert M.failure_control(a["cases"]) == a["failure_control"]
    # and the required voice-lifetime coverage must really be there
    assert any(c["max_live_voices"] > 1 for c in a["cases"])
    assert all(c["has_voice_death_mid_render"] for c in a["cases"])


def test_failure_control_is_live():
    """A control must demonstrably fail the check it targets: a case set that
    is bit-identical everywhere (i.e. voice death was never exercised by the
    comparison) must come back FAIL, not PASS."""
    cases = json.loads(json.dumps(artifact()["cases"]))
    for c in cases:
        c["bit_identical"] = True
    assert M.failure_control(cases)["verdict"] == "FAIL"
    # ... and a qualifying-case-free set is FAIL too (nothing was exercised)
    for c in cases:
        c["bit_identical"] = False
        c["max_live_voices"] = 1
        c["has_voice_death_mid_render"] = False
    assert M.failure_control(cases)["verdict"] == "FAIL"


def test_shared_decimator_zero_input_limit_cycle_is_recorded():
    """F-176-2: the shared HalfbandD2 holds a non-decaying zero-input limit
    cycle. It is why the per-scene leg never reaches exactly zero after a
    voice dies, so the evidence record states it; this test keeps the stated
    mechanism true of the committed class."""
    sys.path.insert(0, os.path.join(REPO, "model", "voice"))
    import voice_model as vm
    hb = vm.HalfbandD2()
    hb.process([vm.qint(0.5)] + [0] * 63)
    tail = []
    for _ in range(2000):
        tail += hb.process([0] * 64)
    settled = tail[-256:]
    peak = max(abs(x) for x in settled)
    assert peak > 0, "no limit cycle: EVIDENCE F-176-2 must be revised"
    assert peak < 64, \
        "limit cycle exceeds one int16 LSB; F-176-2's bound is stale"
    flat = " ".join(read(EVIDENCE).split())
    assert "F-176-2" in flat and "zero-input limit cycle" in flat, \
        "F-176-2 is not recorded in the evidence record"


# --------------------------------------------------------- oracle-gated legs

@needs_oracle
def test_leg_a_is_still_the_frozen_models_own_render():
    """The structural `scene_block()` / `decimate_scene()` split of
    `wt_model.Slice` must stay numerics-preserving: each case's recorded leg-A
    render sha256 must still be what `run_model.py` produces."""
    import hashlib
    a = artifact()
    for c in a["cases"]:
        out = os.path.join("/tmp", "wt176-test",
                           os.path.basename(c["inputs"])[:-5] + "__"
                           + c["sequence"])
        r = subprocess.run(
            [sys.executable, RUNNER, "--inputs",
             os.path.join(REPO, c["inputs"]), "--sequence", c["sequence"],
             "--out-dir", out], cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        h = hashlib.sha256()
        with open(os.path.join(out, "model.wav"), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == c["leg_a_render_sha256"], (
            "%s: run_model.py's render moved; the per-slice leg of the "
            "committed measurement no longer describes the frozen model"
            % c["case"])


@needs_oracle
def test_measurement_reproduces_on_a_committed_case():
    """Re-measuring one case must reproduce the committed metrics exactly
    (the model is pure integer; there is no tolerance to spend)."""
    a = artifact()
    want = next(c for c in a["cases"]
                if c["case"] == "kick-wtfix / seq-wt-base-v1")
    r = M.render_both(
        os.path.join(REPO, "model", "oscillators", "wavetable", "inputs",
                     "kick-wtfix.json"),
        os.path.join(REPO, "fixtures", "sequences", "seq-wt-base-v1.json"))
    got = M.metrics_for(r)
    for k in ("frames", "blocks", "max_abs_diff_lsb", "rms_diff_lsb",
              "rms_diff_dbfs", "max_abs_diff_q21", "frames_differing",
              "bit_identical", "max_live_voices", "voice_death_blocks",
              "after_last_voice_death"):
        assert got[k] == want[k], k
