"""SXT-028g Phaser leaf tests (pytest).

Covers: the frozen constant inventory and word lengths, model determinism,
per-instance independence, the pinned engine quirks this leaf reproduces
(the one-slow-block LFO latency, the legacy-branch allocation, the tone
gate), the reset/panic and mid-tail patch-change semantics, the declared
tail window, the zero-external-traffic property, generator consistency of
the synthetic corner files, and the committed evidence records.

ORACLE-DEPENDENT LEGS (fixture renders, preset extraction, model-vs-
reference agreement) are NOT run here: they skip as NOT_RUN and are never
reported as a pass (AGENTS.md). The same rule covers a missing iverilog:
the RTL-exactness record is asserted only when it has been committed, and a
stale record (model revision drift) FAILS rather than silently passing.
"""

import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import phaser_model as pm  # noqa: E402
from phaser_model import (  # noqa: E402
    PhaserModel, PhaserParams, Refuse, BLOCK, MAX_STAGES, DEFAULT_STAGES,
    SLOWRATE, CLAMP_A, model_revision, ringout_blocks, state_inventory,
)
from corners import CORNERS, record as corner_record  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028g")
INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")


def make(slug="synth-a", **over):
    p = dict(CORNERS[slug])
    p.update(over)
    m = PhaserModel(PhaserParams(p), slug)
    m.initialize()
    return m


def prs(n, seed, amp=1, silence_from=None):
    rs = random.Random(seed)
    out = []
    for b in range(n):
        if silence_from is not None and b >= silence_from:
            out.append(([0] * BLOCK, [0] * BLOCK))
        else:
            out.append(([rs.randint(-(amp << 21), amp << 21)
                         for _ in range(BLOCK)],
                        [rs.randint(-(amp << 21), amp << 21)
                         for _ in range(BLOCK)]))
    return out


# --------------------------------------------------------------------------
# frozen constants / structure
# --------------------------------------------------------------------------

def test_frozen_constants_match_the_pinned_sources():
    assert SLOWRATE == 8                    # EffectCore.h slowrate
    assert MAX_STAGES == 16 and DEFAULT_STAGES == 4     # Phaser.h
    assert CLAMP_A == 32 * (1 << 21)        # Phaser.h clamp(dL, -32, 32)
    assert pm.LEGACY_FREQ == (1.5 / 12, 19.5 / 12, 35 / 12, 50 / 12)
    assert pm.LEGACY_SPAN == (2.0, 1.5, 1.0, 0.5)
    assert (pm.TONE_CLO, pm.TONE_CMID, pm.TONE_CHI) == (-12.0, 67.0, -33.0)
    assert (pm.RATE_MIN, pm.RATE_MAX) == (-7.0, 9.0)
    assert pm.LFO_TABLE_SIZE == 8192 and pm.SAW_CUT == 0.98
    assert pm.SQUARE_CUT == 0.01
    # lipol bs_inv: feedback ramps over blockSize*slowrate, tone over blockSize
    assert pm.FB_BS_INV == (1 << 43) >> 8       # 1/256, exact
    assert pm.TONE_BS_INV == (1 << 43) >> 5     # 1/32, exact


def test_lfo_shapes_match_the_pinned_formulas():
    s = pm.FXModLfo._shape
    assert s(pm.MOD_TRI, 0.0) == 1.0 and s(pm.MOD_TRI, 0.5) == -1.0
    assert s(pm.MOD_SQUARE, 0.2) == 1.0 and s(pm.MOD_SQUARE, 0.7) == -1.0
    # the square's two transition ramps, m = 1/0.01
    assert s(pm.MOD_SQUARE, 0.495) == pytest.approx(0.5)
    assert s(pm.MOD_SQUARE, 0.995) == pytest.approx(0.5)
    # ramp is the negated saw
    for ph in (0.1, 0.5, 0.97, 0.99):
        assert s(pm.MOD_RAMP, ph) == -s(pm.MOD_SAW, ph)
    # sine table is on the engine's float32 grid, table[0] == 0
    assert pm.SINE_TABLE[0] == 0.0
    assert pm.SINE_TABLE[2048] == pytest.approx(1.0, abs=1e-7)


def test_rng_waveforms_are_refused_fail_closed():
    for wave in (pm.MOD_NOISE, pm.MOD_SNH):
        with pytest.raises(Refuse):
            PhaserParams(dict(CORNERS["synth-a"], mod_wave_i=wave))
    with pytest.raises(Refuse):
        PhaserParams(dict(CORNERS["synth-a"], stages_i=17))


def test_one_slow_block_lfo_latency_is_reproduced():
    """Phaser.h never calls modLFO.process(), so valueStereo() returns the
    PREVIOUS slow block's shape sample x the PREVIOUS depth (the lipol
    first_run snap makes the first call current)."""
    m = make("synth-a")
    blocks = prs(4 * SLOWRATE, 5)
    seen = []
    for il, ir in blocks:
        m.process_block(il, ir)
        if m.ctrl["setvars"]:
            seen.append((list(m.ctrl["lfo_stereo"]),
                         [v.new_v for v in m.st.lfo.vals[:2]],
                         m.st.lfo.depth.new_v))
    assert len(seen) == 4
    # first slow block: value == the freshly pushed target (first_run snap)
    d0 = seen[0][2] / float(1 << 43)
    for ch in range(2):
        assert seen[0][0][ch] == pytest.approx(
            seen[0][1][ch] / float(1 << 43) * d0, abs=1e-12)
    # later slow blocks: value == the PREVIOUS block's target x previous depth
    for i in range(1, 4):
        dprev = seen[i - 1][2] / float(1 << 43)
        for ch in range(2):
            assert seen[i][0][ch] == pytest.approx(
                seen[i - 1][1][ch] / float(1 << 43) * dprev, abs=1e-12)


def test_setvars_runs_only_on_every_eighth_block():
    m = make("synth-a")
    flags = []
    for il, ir in prs(3 * SLOWRATE, 9):
        m.process_block(il, ir)
        flags.append(bool(m.ctrl["setvars"]))
    assert flags == [i % SLOWRATE == 0 for i in range(3 * SLOWRATE)]


def test_legacy_branch_allocates_four_units_but_runs_one_stage():
    """Phaser.h's n_stages < 2 branch loops i < 2 (configuring biquads 0..3)
    while processBlock runs only stage 0. Reproduced as pinned."""
    m = make("synth-legacy-a")
    m.process_block(*prs(1, 3)[0])
    configured = [u for u in range(2 * MAX_STAGES)
                  if not m.st.apf[u].first_run]
    assert configured == [0, 1, 2, 3]
    # only units 0 and 1 actually filter, so only they hold TDF2 energy
    assert m.st.apf[0].reg0 != 0 or m.st.apf[1].reg0 != 0
    assert m.st.apf[2].reg0 == 0 and m.st.apf[3].reg0 == 0
    assert state_inventory(1)["biquad_units"] == 4


def test_tone_deactivation_bypasses_the_tone_filters():
    on = make("synth-a", tone_deactivated=False)
    off = make("synth-a", tone_deactivated=True)
    blocks = prs(16, 17)
    for il, ir in blocks:
        on.process_block(il, ir)
        off.process_block(il, ir)
    assert any(v != 0 for v in on.st.lp.reg0)
    assert all(v == 0 for v in off.st.lp.reg0)
    assert all(v == 0 for v in off.st.hp.reg0)


# --------------------------------------------------------------------------
# determinism, per-instance state, tails
# --------------------------------------------------------------------------

def test_model_determinism():
    runs = []
    for _ in range(2):
        m = make("synth-b")
        out = [m.process_block(il, ir) for il, ir in prs(24, 7)]
        runs.append((out, m.st.checkpoint()))
    assert runs[0] == runs[1]


def test_dual_instance_independent_histories():
    a = make("synth-a")
    b = make("synth-b")
    for il, ir in prs(40, 3):
        a.process_block(il, ir)
        b.process_block(ir, il)
    assert a.st.apf is not b.st.apf
    assert a.st.apf_hash() != b.st.apf_hash()
    assert (a.st.dl, a.st.dr) != (b.st.dl, b.st.dr)
    # ... and the same params on the same input DO agree (so the check above
    # is detecting state separation, not just parameter difference)
    c = make("synth-a")
    d = make("synth-a")
    for il, ir in prs(20, 4):
        c.process_block(il, ir)
        d.process_block(il, ir)
    assert c.st.apf_hash() == d.st.apf_hash()


def test_no_external_memory_traffic():
    m = make("synth-maxst")
    for il, ir in prs(32, 13):
        m.process_block(il, ir)
    assert m.st.ext_reads == 0 and m.st.ext_writes == 0
    inv = state_inventory(MAX_STAGES)
    assert inv["biquad_units"] == 2 * MAX_STAGES
    assert inv["bytes_total"] == 3500


def test_declared_tail_window_and_decay():
    assert ringout_blocks(0.1) == 1000
    assert ringout_blocks(0.7) == 3000
    assert ringout_blocks(-0.95) == 5000
    assert ringout_blocks(1.5) == -1        # self-oscillation: no finite span
    p = CORNERS["synth-a"]
    span = ringout_blocks(p["feedback_f"])
    m = make("synth-a")
    burst = 64
    out = [m.process_block(il, ir)
           for il, ir in prs(burst + span, 23, silence_from=burst)]
    onset = max(max(abs(v) for v in out[burst][0]),
                max(abs(v) for v in out[burst][1]))
    terminal = max(max(abs(v) for v in out[-1][0]),
                   max(abs(v) for v in out[-1][1]))
    assert onset > 4          # the tail is present where the input stops
    assert terminal <= 4      # and has died inside the declared span


def test_reset_panic_clears_the_tail():
    m = make("synth-a")
    for il, ir in prs(32, 29):
        m.process_block(il, ir)
    assert m.st.dl != 0 or m.st.dr != 0
    m.reset()
    assert (m.st.dl, m.st.dr) == (0, 0)
    assert all(b.first_run for b in m.st.apf)
    assert m.st.lp.reg0 == [0, 0] and m.st.hp.reg1 == [0, 0]
    ol, orr = m.process_block([0] * BLOCK, [0] * BLOCK)
    assert all(v == 0 for v in ol) and all(v == 0 for v in orr)


def test_patch_change_mid_tail_continues_the_tail():
    """The engine mutates FxStorage in place: the instance keeps dL/dR and
    every register and only picks the new values up at the next setvars."""
    m = make("synth-a")
    for il, ir in prs(64, 31):
        m.process_block(il, ir)
    silent = ([0] * BLOCK, [0] * BLOCK)
    m.process_block(*silent)
    before = (m.st.dl, m.st.dr, m.st.apf_hash())
    m.set_params(PhaserParams(dict(CORNERS["synth-c"])))
    assert (m.st.dl, m.st.dr, m.st.apf_hash()) == before   # nothing reset
    ol, orr = m.process_block(*silent)
    assert max(max(abs(v) for v in ol), max(abs(v) for v in orr)) > 0
    # a stage-count change is the init_stages allocation path: refused
    with pytest.raises(Refuse):
        m.set_params(PhaserParams(dict(CORNERS["synth-b"])))


def test_feedback_clamp_is_reachable_and_bounds_the_node():
    m = make("synth-clamp-a")
    for il, ir in prs(96, 11, amp=8):
        m.process_block(il, ir)
    assert m.st.clamp_hits > 0            # the clamp is a live path
    m2 = make("synth-a")
    for il, ir in prs(32, 11):
        m2.process_block(il, ir)
    assert m2.st.clamp_hits == 0          # and not spuriously engaged


# --------------------------------------------------------------------------
# generator consistency
# --------------------------------------------------------------------------

def test_corner_input_files_match_the_generator():
    for slug in CORNERS:
        path = os.path.join(INPUTS, f"type-phaser-{slug}.json")
        assert os.path.exists(path), path
        on_disk = json.load(open(path))
        assert on_disk == corner_record(slug), (
            f"{path} is stale — regenerate with "
            "`python3 model/effects/type-phaser/corners.py --write`")
        # a synthetic corner must never look like a preset extraction
        assert on_disk["source"] == "synthetic-corner"
        assert on_disk["census_blob_sha1"] is None
        assert on_disk["applicability"]["complete_wet_render_possible"] is False


def test_corner_files_are_accepted_by_the_frozen_model():
    for slug in CORNERS:
        cfg = json.load(open(os.path.join(INPUTS, f"type-phaser-{slug}.json")))
        entry = cfg["chain"]["ains"][0]
        assert entry["type"] == "phaser"
        PhaserParams(dict(entry["params"]))    # must validate, fail-closed


def test_extractor_refuses_rng_waveforms_by_construction():
    """The extractor's deterministic-waveform gate must agree with the
    model's frozen scope (one rule, two enforcement points)."""
    import ast
    src = open(os.path.join(REPO, "tools",
                            "extract_phaser_inputs.py")).read()
    tree = ast.parse(src)
    waves = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], "id", None)
                == "DETERMINISTIC_WAVES"):
            waves = ast.literal_eval(node.value)
    assert waves == pm.DETERMINISTIC_WAVES


# --------------------------------------------------------------------------
# committed evidence records
# --------------------------------------------------------------------------

def test_oracle_status_record_is_coherent():
    p = os.path.join(SXT, "artifacts", "oracle-status.json")
    d = json.load(open(p))
    assert d["oracle_status"] in ("AVAILABLE", "UNAVAILABLE")
    for name, leg in d["legs"].items():
        if d["oracle_status"] == "UNAVAILABLE":
            assert leg["status"] == "NOT_RUN", name
        assert leg["status"] != "PASS", name


def test_reference_comparison_is_not_claimed_without_an_oracle():
    """Claim 2 must not be recorded as a pass while the oracle is absent."""
    status = json.load(open(os.path.join(SXT, "artifacts",
                                         "oracle-status.json")))
    art = os.path.join(SXT, "artifacts")
    comps = [f for f in os.listdir(art)
             if f.startswith("compare-") and f.endswith(".json")]
    if status["oracle_status"] == "UNAVAILABLE":
        assert comps == [], (
            "a model-vs-reference comparison record exists but no oracle was "
            "available: %s" % comps)
        pytest.skip("model-vs-pinned-engine agreement: NOT_RUN (no oracle)")
    for fn in comps:
        d = json.load(open(os.path.join(art, fn)))
        assert "PENDING-FREEZE" in d["verdict"], fn   # never frozen


def test_buffer_requirement_record():
    br = json.load(open(os.path.join(SXT, "artifacts",
                                     "buffer-requirement.json")))
    assert br["external_writable_memory"]["bytes_total"] == 0
    assert br["external_traffic"]["words_per_sample_32bit"] == 0.0
    for corner in br["external_traffic"]["measured_per_corner"].values():
        assert corner["ext_reads_total"] == 0
        assert corner["ext_writes_total"] == 0
    exact = br["on_chip_state_exact"]
    assert exact["worst_case_bytes"] == state_inventory(MAX_STAGES)["bytes_total"]
    rec = br["sxt015_reconciliation"]
    assert rec["tier_confirmed"] and rec["traffic_confirmed"]
    assert rec["placeholder_was_conservative"] is True
    assert br["cost_closure"]["status"] == "[PENDING-SXT-016]"
    assert br["model_revision"] == model_revision(), "stale record"


def test_tail_window_record():
    tw = json.load(open(os.path.join(SXT, "artifacts", "tail-window.json")))
    for slug, w in tw["windows"].items():
        assert w["ringout_blocks"] == ringout_blocks(
            CORNERS[slug]["feedback_f"]), slug


def test_negative_controls_all_fail_their_checks():
    d = json.load(open(os.path.join(SXT, "negative-controls",
                                    "negative-controls.json")))
    assert d["status"] == "PASS"
    assert d["model_revision"] == model_revision(), "stale record"
    names = {c["control"].split()[0] for c in d["controls"]}
    assert names == {"NC-A", "NC-B", "NC-C", "NC-D", "NC-E", "NC-F"}
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]
        # every control that would also need an oracle says so explicitly
        if "reference_anchored_leg" in c:
            assert c["reference_anchored_leg"]["status"] == "NOT_RUN"


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == model_revision(), "stale record"
    assert len(d["cases"]) >= 5
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]
        assert c["checked"]["outputs"] > 0 and c["checked"]["fields"] > 0
    assert any(c["case"].startswith("prs-clamp") and c["clamp_engagements"] > 0
               for c in d["cases"]), "the +-32 clamp case never engaged it"
    mutants = {m["case"]: m for m in d["mutant_controls"]}
    assert set(mutants) >= {"mutant-shared", "mutant-stageorder",
                            "mutant-lagcoef", "mutant-noclamp"}
    for name, m in mutants.items():
        assert m["ok"] is True and "CONTROL-OK" in m["verdict"], name
        assert m["exact"] is False, name


# --------------------------------------------------------------------------
# #426: Phaser same-shape drift-0 carrier screen. These tests check the
# screen's refusal/selection logic with injected non-live fakes and, when
# committed, the live record's internal consistency. They are NOT live-oracle
# evidence; without reports/SXT-028g/artifacts/carrier-drift-screen.json the
# record legs are NOT_RUN (skipped), never a pass.
# --------------------------------------------------------------------------

import carrier_drift_screen as cds  # noqa: E402
import screen_phaser_carriers as scr  # noqa: E402

SCREEN = os.path.join(SXT, "artifacts", "carrier-drift-screen.json")


def load_screen():
    if not os.path.exists(SCREEN):
        pytest.skip("carrier-drift-screen.json not committed (NOT_RUN)")
    return json.load(open(SCREEN))


def derive_gate_status(gate):
    drifts = gate["drift_per_voicing_scene"]
    assert set(drifts) == set(gate["voicing_scenes"]), "voicing scene mismatch"
    return "PASS" if all(v == 0.0 for v in drifts.values()) else "FAIL"


def check_original_eligibility(shape_rec):
    orig = shape_rec["original_result"]
    assert orig["determinism_gate"]["status"] == \
        derive_gate_status(orig["determinism_gate"])
    el = shape_rec["original_eligibility"]
    if derive_gate_status(orig["determinism_gate"]) == "FAIL":
        assert el["render_eligible"] is False, "failed original made eligible"
        assert el["drift_screen"] == "FAIL"
    else:
        assert el["drift_screen"] == "PASS"
        assert el["render_eligible"] != True  # noqa: E712


def _rec(path, drifts, screened=True):
    gate = None
    if screened:
        gate = {"status": "PASS" if all(v == 0.0 for v in drifts.values())
                else "FAIL", "drift_per_voicing_scene": drifts,
                "voicing_scenes": sorted(drifts)}
    return {"path": path, "screened": screened, "determinism_gate": gate,
            "refusal": None if screened else {"code": "x"}}


def test_shape_is_declared_and_original_satisfies_it():
    sh = scr.SHAPES[0]
    pred = scr.make_predicate(sh)
    cands = cds.enumerate_candidates(pred)
    assert len(cands) == sh["expected_count"]
    assert sh["path"] in [c["path"] for c in cands]
    assert sh["path"].endswith("Leads/Squelch.fxp")


def test_predicate_rejects_other_shapes():
    sh = scr.SHAPES[0]
    pred = scr.make_predicate(sh)
    inner = next(c["graph"] for c in cds.enumerate_candidates(pred)
                 if c["path"] == sh["path"])
    orig = {"st": "normalized", "g": inner}
    assert pred(orig)
    for mutate in (
            lambda g: g["g"].__setitem__("fxb", 1),
            lambda g: g["g"].__setitem__("sa", 1),
            lambda g: g["g"]["fx"][1].__setitem__("on", 1),
            lambda g: g["g"]["fx"][0].__setitem__("t", 1),
            lambda g: g["g"]["fx"][0].__setitem__("on", 0)):
        bad = json.loads(json.dumps(orig))
        mutate(bad)
        assert not pred(bad)


def test_declarations_name_the_squelch_refusal_in_extractor_and_renderer():
    for name in ("extract_phaser_inputs.py", "render_phaser_fixtures.py"):
        txt = open(os.path.join(REPO, "tools", name), encoding="utf-8").read()
        assert "#426" in txt and "0.1875" in txt and \
            "screen_phaser_carriers.py" in txt, name
    # the existing fail-closed extractor drift gate is still present
    ext = open(os.path.join(REPO, "tools", "extract_phaser_inputs.py"),
               encoding="utf-8").read()
    assert "if drift != 0.0:" in ext


def test_no_eligible_candidate_is_bounded_gap():
    cands = [_rec("a", {"A": 0.1}), _rec("b", {"A": 0.0}, screened=False),
             _rec("orig", {"A": 0.0})]
    assert scr.select_replacement(cands, "orig") == ([], None)


def test_scene_b_only_drift_fails_gate():
    class S:
        vals = {"mode": 2, "act": 0, "dA": 0.0, "dB": 0.25}

        def getParamVal(self, k):
            return self.vals[k]
    patch = {"scenemode": "mode", "scene_active": "act",
             "scene": [{"drift": "dA"}, {"drift": "dB"}]}
    g = cds.DRIFT_GATE(S(), patch)
    assert g["status"] == "FAIL" and g["drift_per_voicing_scene"]["A"] == 0.0
    with pytest.raises(AssertionError):
        cds.assert_drift_gate_passed({"path": "x", "screened": True,
                                      "determinism_gate": g})


def test_selection_deterministic_excludes_original_and_failures():
    cands = [_rec("z", {"A": 0.0}), _rec("b", {"A": 0.0}),
             _rec("a", {"A": 0.0}), _rec("f", {"A": 0.5}),
             _rec("orig", {"A": 0.0})]
    ranked, selected = scr.select_replacement(cands, "orig")
    assert ranked == ["a", "b", "z"] and selected == "a"
    assert scr.select_replacement(list(reversed(cands)), "orig") == \
        (ranked, selected)


def test_missing_oracle_is_not_run_and_writes_nothing(tmp_path):
    class Absent:
        is_live = False

        def open(self):
            raise cds.OracleAbsent("no oracle")
    doc = scr.screen_all(Absent())
    assert doc["status"] == "NOT_RUN" and doc["live"] is False
    out = tmp_path / "x.json"
    with pytest.raises(Exception):
        cds.write_record(doc, str(out))
    assert not out.exists()


def test_injected_loader_run_is_never_writable_as_live_evidence(tmp_path):
    class Fake:
        is_live = False

        def open(self):
            return {"pin": cds.ENGINE_PIN}

        def load(self, rel, sha):
            raise cds.LoadRefusal(cds.R_LOAD_FAILED, "fake")
    rec = scr.screen_shape(scr.SHAPES[0], Fake())
    assert rec["run"]["coverage"]["candidates_screened"] == 0
    assert rec["selection"]["outcome"] == "BOUNDED_GAP"
    assert rec["original_eligibility"]["render_eligible"] is False
    with pytest.raises(Exception):
        cds.write_record(rec["run"], str(tmp_path / "y.json"))


def test_shape_check_refuses_native_disagreement():
    sh = scr.SHAPES[0]
    cand = next(c for c in cds.enumerate_candidates(scr.make_predicate(sh))
                if c["path"] == sh["path"])
    ntypes = [fx.get("t", 0) for fx in cand["graph"]["fx"]]

    class S:
        def __init__(self, types, fxb=0):
            self.types, self.fxb = types, fxb

        def getParamVal(self, k):
            if isinstance(k, tuple):
                return self.types[k[1]]
            return {"fxb": self.fxb, "fxd": 0, "mode": 0, "act": 0}[k]
    patch = {"fx": [{"type": ("t", i)} for i in range(len(ntypes))],
             "fx_bypass": "fxb", "fx_disable": "fxd", "scenemode": "mode",
             "scene_active": "act"}
    chk = scr.make_shape_check({})
    assert chk(S(ntypes), patch, cand) is None
    wrong = list(ntypes)
    wrong[3] = 3                      # disagrees with graphs.jsonl
    assert chk(S(wrong), patch, cand)
    assert chk(S(ntypes, fxb=2), patch, cand)


def test_screen_record_live_and_consistent():
    d = load_screen()
    assert d["live"] is True and d["issue"] == "#426"
    s = d["shapes"][0]
    assert s["run"]["coverage"]["candidates_in_corpus"] == \
        scr.SHAPES[0]["expected_count"]
    check_original_eligibility(s)


def test_mutation_nonzero_drift_original_made_eligible_fails():
    d = load_screen()
    s = d["shapes"][0]
    if derive_gate_status(s["original_result"]["determinism_gate"]) != "FAIL":
        pytest.skip("original drift is 0 in the record; mutation N/A")
    bad = json.loads(json.dumps(s))
    bad["original_result"]["determinism_gate"]["status"] = "PASS"
    with pytest.raises(AssertionError):
        check_original_eligibility(bad)
    bad2 = json.loads(json.dumps(s))
    bad2["original_eligibility"]["render_eligible"] = True
    with pytest.raises(AssertionError):
        check_original_eligibility(bad2)


def test_mutation_control_on_synthetic_failed_original():
    """Live-independent control: a FAIL original made eligible must be caught."""
    ok = {"original_result": _rec("o", {"A": 0.1875}),
          "original_eligibility": {"drift_screen": "FAIL",
                                   "render_eligible": False}}
    check_original_eligibility(ok)
    ok["original_eligibility"]["render_eligible"] = True
    with pytest.raises(AssertionError):
        check_original_eligibility(ok)
