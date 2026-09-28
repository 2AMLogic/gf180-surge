"""SXT-026 (#176, revised by #180): the wavetable leaf's decimation topology
and its RTL coverage of the 48 kHz output.

Issue #176 recorded two scope gaps in the SXT-026 leaf (#19):

  1. `rtl/oscillators/wavetable/` implemented no post-oscillator stage, so the
     leaf's `rtl_vs_model: PASS` was silently oscillator-scoped -- the ledger
     note and the evidence record did not say so.
  2. The frozen model decimated PER VOICE SLICE where the pinned engine
     decimates PER SCENE, and the size of that difference was unmeasured.

#176 took option (b): declare both as explicit, bounded deviations with the
difference measured (`tools/measure_wt_decimation_stage.py`). **#180 then took
option (a)** under the SXT-017 visible-contract rule
(`decision-records/0018-wavetable-scene-decimation-placement.md`): the stage
moved to one per-SCENE `wt_model.SceneDecimator`, the RTL gained the same
stage in `tb_wavetable.sv`, and `tools/compare_wt_rtl_model.py` now compares
every 48 kHz `mono_block` sample at integer equality.

This file was written under #176 to FAIL the moment a decimator appeared under
`rtl/oscillators/wavetable/` or the comparator started reading `mono_block` --
deliberately, so that option (a) could not land while the declaration still
said otherwise. That is exactly what happened, so the two structural checks
are **inverted** here rather than deleted: they now assert the landed topology
with the same strictness, and a silent regression to the retired placement
fails them just as loudly.

What these tests hold in place:

  * the landed statements must actually be present in the ledger note, the
    evidence record, the model README, the RTL headers and the comparator,
    and the retired boundary must not still be asserted anywhere as current;
  * the RTL must actually contain the per-scene stage AND its single-line
    mutant define, and the comparator must actually read `mono_block` --
    structural checks, so that quietly dropping the 48 kHz coverage fails
    them;
  * the committed measurement artifact must be internally coherent, must
    record which leg is frozen, and its failure control must be live (a
    bit-identical case set must FAIL it).

Nothing here establishes any verdict: no fidelity, preset-support,
RTL-vs-model, or musical-quality claim is made or checked. In particular,
these tests do NOT run the RTL -- the 48 kHz integer-equality verdict and its
scene-decimator mutant control live in `tools/run_sxt026_checks.py` step 6 and
`reports/sxt-026/artifacts/rtl-exactness.txt`.
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

def test_ledger_note_states_the_landed_48khz_rtl_coverage():
    """The osc:Wavetable note must say what its rtl_vs_model PASS covers."""
    with open(LEDGER, encoding="utf-8") as f:
        table = json.load(f)
    leaf = table["leaves"]["osc:Wavetable"]
    note = leaf["note"]
    # the verdicts themselves are unchanged by #176 and by #180
    assert leaf["verification"]["rtl_vs_model"] == "PASS"
    assert leaf["verification"]["model_vs_reference"] == "PARTIAL"
    low = note.lower()
    assert "oscillator output" in low, note
    assert "48 khz" in low, note
    assert "mono_block" in low, note
    assert "per scene" in low, note
    assert "sxt-017" in low, note
    # the landed coverage must be stated as landed, and be traceable to the
    # contract revision that authorized it
    assert "#180" in note, note
    assert "decision-records/0018" in note, note
    # the mutant is what makes the coverage claim mean anything -- a note
    # claiming 48 kHz coverage without naming its control is not enough
    assert "wt_scene_mutant_hb_order" in low, note
    # the measurement must be cited, not merely asserted
    assert "decimation-stage-per-slice-vs-per-scene.json" in note, note
    # and the retired boundary must not still be asserted as current
    assert "implements no post-oscillator stage" not in low, note


def test_evidence_record_states_the_revision_and_the_measurement():
    text = read(EVIDENCE)
    assert "Declared scope (issue #180" in text
    assert "## 2a. Per-slice vs per-scene decimation" in text
    assert "mono_block" in text
    # the claim-discipline header must carry the landed scope, not the
    # retired boundary
    head = text.split("## 0.")[0]
    assert "AND the 48 kHz render" in head, "claim discipline is unscoped"
    assert "NOT the 48 kHz render" not in head, "retired boundary still live"
    # section 8 must still refuse to let the 48 kHz PASS mean more than
    # claim (1)
    not_established = text.split("## 8.")[-1]
    assert "is claim (1) only" in not_established
    assert "No claim that moving the decimator improved fidelity" in \
        not_established
    # every moved render must be PUBLISHED, not silently replaced (#180
    # acceptance): the before->after note and the mutant's 48 kHz evidence
    assert "Change note (issue #180" in text
    assert "corr before → after" in text
    assert "WT_SCENE_MUTANT_HB_ORDER" in text
    # the measured worst case must be in the record, not only in the JSON
    a = artifact()
    assert ("%.1f" % abs(a["summary"]["rms_diff_dbfs_worst"])) in text
    assert str(a["summary"]["max_abs_diff_q21_worst"]) in text


def test_model_readme_declares_both_deviations_as_landed():
    text = read(README)
    assert "RETIRED as a deviation by the #180 contract revision" in text
    assert "RTL coverage (issue #180" in text
    assert "covers the oscillator AND the 48 kHz" in text
    assert "WT_SCENE_MUTANT_HB_ORDER" in text
    assert "tools/measure_wt_decimation_stage.py" in text
    # the move must not be presentable as a fidelity improvement
    assert "Nothing here is a fidelity claim" in text
    # the retired wording must be gone, not merely contradicted further down
    assert "PER VOICE SLICE, not per scene" not in text


def test_rtl_headers_declare_the_landed_stage():
    for name in ("wavetable_core.sv", "tb_wavetable.sv"):
        text = read(os.path.join(RTLDIR, name))
        assert "DECLARED SCOPE (issue #180" in text, name
        assert "tb_voice.sv" in text, name
        assert "decision-records/0018" in text, name


def test_comparator_carries_a_machine_readable_scope():
    import compare_wt_rtl_model as C
    assert set(C.SCOPE) >= {"covers", "does_not_cover", "declared_in",
                            "issue", "superseded_boundary"}
    assert C.SCOPE["issue"] == 180
    assert "96 kHz" in C.SCOPE["covers"]
    assert "48 kHz" in C.SCOPE["covers"]
    assert "mono_block" in C.SCOPE["covers"]
    # the landed scope must not still disclaim the 48 kHz output
    assert "48 kHz" not in C.SCOPE["does_not_cover"]
    # what it still must NOT cover: model-vs-engine fidelity
    assert "fidelity" in C.SCOPE["does_not_cover"]
    # and it must be emitted with every verdict, not merely defined
    assert '"scope": SCOPE,' in read(COMPARATOR)


# ------------------------------------------- the landed topology is still true

def test_wavetable_rtl_implements_the_scene_decimator():
    """Structural, not prose (the #176 check, inverted by #180).

    Under #176 this asserted the leaf's RTL contained NO decimator, so that
    adding one would fail rather than silently contradict declared deviation
    8. #180 added one deliberately, so the check now asserts the opposite with
    the same strictness: the per-scene stage must be present in CODE (not just
    discussed in a comment), in the testbench rather than the per-slot core,
    and it must carry its single-line mutant define -- silently dropping
    either would retire the 48 kHz coverage claim without revising it."""
    tokens = re.compile(r"halfband|halfrate|half_rate|decimat|process_block_d2",
                        re.I)

    def code_lines(name):
        return [ln.split("//", 1)[0]
                for ln in read(os.path.join(RTLDIR, name)).splitlines()]

    tb_hits = [ln for ln in code_lines("tb_wavetable.sv") if tokens.search(ln)]
    assert tb_hits, (
        "tb_wavetable.sv no longer implements the per-scene decimator; "
        "README deviation 7/8 and EVIDENCE section 2 claim 48 kHz "
        "RTL-vs-model coverage that would no longer exist")

    core_hits = [ln for ln in code_lines("wavetable_core.sv")
                 if tokens.search(ln)]
    assert not core_hits, (
        "wavetable_core.sv (the PER-SLOT core) now contains decimator logic; "
        "the scene stage is a shared per-scene resource and belongs in the "
        "testbench, as in rtl/voice/tb_voice.sv: %r" % (core_hits[:3],))

    tb = read(os.path.join(RTLDIR, "tb_wavetable.sv"))
    assert "`ifdef WT_SCENE_MUTANT_HB_ORDER" in tb, (
        "the single-line scene-decimator mutant is gone; the 48 kHz coverage "
        "claim in EVIDENCE section 6 has no live failure control without it")
    assert "M %0d %0d" in tb, "the 48 kHz M trace line is gone"


def test_comparator_reads_and_compares_the_48khz_samples():
    """The #176 check, inverted by #180: the harness must read the model
    trace's 48 kHz stream, must count what it compared, and must refuse a
    scene-mutant run that failed somewhere other than the 48 kHz leg."""
    code = read(COMPARATOR)
    assert re.search(r"""["']mono_block["']""", code), (
        "compare_wt_rtl_model.py no longer reads the model trace's "
        "mono_block; the 48 kHz RTL coverage claimed by README deviation 8 "
        "and EVIDENCE section 2 would be unbacked")
    assert re.search(r"""["']mono48["']""", code), (
        "the comparator no longer reports how many 48 kHz samples it "
        "compared; a silently-empty 48 kHz leg would look like a PASS")
    assert "--mutant-scene" in code and "WT_SCENE_MUTANT_HB_ORDER" in code
    # the failure control must be leg-specific, not merely "something failed"
    assert 'mono_fails = [f for f in cmp_fails if "mono48" in f]' in code, (
        "the scene mutant is no longer required to fail ON the 48 kHz leg; "
        "a mutant that only broke an oscillator checkpoint would prove "
        "nothing about 48 kHz coverage")


def test_checks_script_gates_the_48khz_leg_and_its_mutant():
    """`tools/run_sxt026_checks.py` step 6 is where the 48 kHz verdict and its
    control are actually produced; it must assert both, not just run them."""
    code = read(os.path.join(REPO, "tools", "run_sxt026_checks.py"))
    assert "--mutant-scene" in code
    assert 'd["checked"]["mono48"] == kt_blocks * 32' in code, (
        "the clean run no longer asserts it compared every 48 kHz sample")
    assert 'if "mono48" in f' in code, (
        "the scene mutant is no longer required to fail on the 48 kHz leg")


def test_frozen_model_has_one_scene_stage_not_a_per_slice_one():
    """The model half of the revision, structurally: `Slice` must no longer
    own a halfband or a master stage, and the retired entry points must be
    gone rather than left as dead aliases."""
    sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "wavetable"))
    import wt_model as wm

    assert hasattr(wm, "SceneDecimator"), \
        "the per-scene stage is gone; the #180 revision has been reverted"
    assert not hasattr(wm.Slice, "decimate_scene"), \
        "Slice.decimate_scene() is back: the retired per-slice placement"
    assert not hasattr(wm.Slice, "process_block"), \
        "Slice.process_block() is back: the retired per-slice placement"
    assert hasattr(wm.Slice, "scene_block")

    src = read(os.path.join(REPO, "model", "oscillators", "wavetable",
                            "wt_model.py"))
    slice_src = src.split("class Slice:")[1].split("class SceneDecimator:")[0]
    assert "HalfbandD2" not in slice_src, \
        "a per-voice-slice HalfbandD2 is back in wt_model.Slice"
    assert "master" not in slice_src, \
        "the master stage is back inside wt_model.Slice"

    # ... and the runner must drive exactly one of them for the whole render
    runner = read(os.path.join(REPO, "model", "oscillators", "wavetable",
                               "run_model.py"))
    assert runner.count("wm.SceneDecimator(") == 1, \
        "run_model.py no longer instantiates exactly one scene stage"


# ------------------------------------------------- the measurement artifact

def test_measurement_artifact_covers_the_nine_committed_fixtures():
    a = artifact()
    assert a["format"] == "sxt-026-decimation-stage-measurement/2"
    assert a["issue"] == 176
    # /2 records that #180 swapped WHICH leg is the frozen model, without
    # changing the numbers (|a-b| is symmetric)
    assert a["reissue"] == 180
    assert a["frozen_leg"].startswith("b (per scene)"), a["frozen_leg"]
    assert "decision-records/0018" in a["frozen_leg"]
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
        # the byte-identity gate now guards the FROZEN leg (b, per scene)
        assert c["frozen_leg_runner_equality"].startswith("PASS"), c["case"]
        assert len(c["leg_a_render_sha256"]) == 64
        assert len(c["leg_b_render_sha256"]) == 64


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
def test_leg_b_is_still_the_frozen_models_own_render():
    """Since #180 the FROZEN leg is b (per scene): each case's recorded leg-B
    render sha256 must still be what `run_model.py` produces, and must match
    the committed `artifacts/model-*.wav` for that case. Leg A is a legacy
    re-implementation of the retired placement and is deliberately NOT gated
    against the runner any more -- if it were, it would fail by construction.
    """
    import hashlib
    art_dir = os.path.join(REPO, "reports", "sxt-026", "artifacts")
    a = artifact()
    for c in a["cases"]:
        stem = (os.path.basename(c["inputs"])[:-len(".json")] + "__"
                + c["sequence"])
        out = os.path.join("/tmp", "wt180-test", stem)
        r = subprocess.run(
            [sys.executable, RUNNER, "--inputs",
             os.path.join(REPO, c["inputs"]), "--sequence", c["sequence"],
             "--out-dir", out], cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]

        def sha(path):
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()

        got = sha(os.path.join(out, "model.wav"))
        assert got == c["leg_b_render_sha256"], (
            "%s: run_model.py's render moved; the per-scene leg of the "
            "committed measurement no longer describes the frozen model"
            % c["case"])
        # ... and the committed render must be that same render, so a moved
        # model can never leave a stale WAV in the evidence directory
        assert got == sha(os.path.join(art_dir, "model-%s.wav" % stem)), (
            "%s: the committed model-*.wav is not what the frozen model "
            "renders today" % c["case"])


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
