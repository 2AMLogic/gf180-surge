"""SXT-043 fixture revision 2 (#329): route-clear ordering and readback.

These tests drive `model/voice/playmode/fixture_config.py` against an API
DOUBLE of the surgepy surface it uses.  The double reproduces the two engine
behaviours #311 established by code reading and native intervention
(queued type switch that keeps voice routes and remaps the slot's p[]
names; `setModDepth01` a no-op on a non-modulatable target whose
`getModDepth01` then reads 0 while the raw depth stays intact).  They verify
ORDERING, IDENTITY MATCHING and READBACK logic only -- not native sound.
Native acceptance (pinned oracle renders, pitch gate, budgets) is reported
separately in reports/SXT-043/EVIDENCE.md.

The valid-reference gate (`reference_validity.py`) is exercised on
synthetic signals: that shows the gate rejects silence and a stale /
non-pitched signal and accepts a pitched Sine, not that any engine render
passes it.
"""
import ast
import json
import math
import os
import sys
import types

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice", "playmode"))

import fixture_config as fc                                   # noqa: E402
import reference_validity as rv                               # noqa: E402
from refusal import Refuse                                    # noqa: E402


# apply_overrides does `import surgepy.constants` (for fxt_off only) at CALL
# time.  The stand-in is installed per test through monkeypatch, which
# restores sys.modules on teardown, so it can never leak into another test
# module (an oracle probe such as `oracle_common.import_surgepy()` must keep
# seeing "not installed" and skip).  No module under test imports surgepy
# at import time; the teardown below still evicts any module that captured
# the stand-in, so a future import-time `import surgepy` cannot cache it.
def _fake_surgepy():
    sp = types.ModuleType("surgepy")
    spc = types.ModuleType("surgepy.constants")
    spc.fxt_off = 0
    sp.constants = spc
    return sp, spc


def _install_fake_surgepy(monkeypatch):
    sp, spc = _fake_surgepy()
    monkeypatch.setitem(sys.modules, "surgepy", sp)
    monkeypatch.setitem(sys.modules, "surgepy.constants", spc)
    yield sp
    for name, mod in list(sys.modules.items()):
        if mod is sp or mod is spc:
            continue                    # monkeypatch restores these two
        if any(v is sp or v is spc
               for v in list(getattr(mod, "__dict__", {}).values())):
            sys.modules.pop(name, None)


@pytest.fixture
def fake_surgepy(monkeypatch):
    yield from _install_fake_surgepy(monkeypatch)


pytestmark = pytest.mark.usefixtures("fake_surgepy")


# ------------------------------------------------------------- API double
class _Id:
    def __init__(self, pid):
        self._pid = pid

    def getSynthSideId(self):
        return self._pid


class Param:
    def __init__(self, pid, name, value=0.0, modulatable=True, gen=0):
        self.pid, self.name, self.value = pid, name, float(value)
        self.modulatable, self.gen = modulatable, gen

    def getName(self):
        return self.name

    def getId(self):
        return _Id(self.pid)


class Src:
    def __init__(self, name):
        self.name = name

    def getName(self):
        return self.name


class Routing:
    def __init__(self, synth, src, dest_pid, depth, scene=0, index=0):
        self.synth, self.src, self.dest_pid = synth, src, dest_pid
        self.depth, self.scene, self.index = float(depth), scene, index

    def getSource(self):
        return self.src

    def getDest(self):
        return self.synth.by_pid[self.dest_pid]

    def getDepth(self):
        return self.depth

    def getNormalizedDepth(self):
        # a non-modulatable destination reports normalized depth 0 while the
        # raw depth is untouched (observed natively, #311)
        return self.depth if self.getDest().modulatable else 0.0

    def getSourceScene(self):
        return self.scene

    def getSourceIndex(self):
        return self.index


OSC_P_BASE = 225                     # Digibass "A Osc 1 Morph" (graphs.jsonl)
WT_NAMES = ["Morph", "Skew Vertical", "Saturate", "Formant", "Skew Horizontal",
            "Unison Detune", "Unison Voices"]
SINE = [("Shape", 0.0, False), ("Feedback", 0.0, True),
        ("FM Behavior", 1.0, False), ("Low Cut", -60.0, True),
        ("High Cut", 70.0, True), ("Unison Detune", 0.1, True),
        ("Unison Voices", 1.0, False)]


class FakeSurge:
    def __init__(self, routes=(), zero_works=True, dup_pid=False):
        self.log = []
        self.gen = 0
        self.by_pid = {}
        self.zero_works = zero_works
        self.pending_type = None
        pid = [1000]

        def P(name, v=0.0):
            pid[0] += 1
            p = Param(pid[0], name, v)
            self.by_pid[p.pid] = p
            return p

        def osc(n, typ):
            o = {"type": P("A Osc %d Type" % n, typ),
                 "octave": P("A Osc %d Octave" % n),
                 "pitch": P("A Osc %d Pitch" % n),
                 "keytrack": P("A Osc %d Keytrack" % n, 1.0),
                 "retrigger": P("A Osc %d Retrigger" % n)}
            if n == 1:
                o["p"] = []
                for k in range(7):
                    q = Param(OSC_P_BASE + (0 if dup_pid and k == 1 else k),
                              "A Osc 1 " + WT_NAMES[k], 0.5)
                    self.by_pid[q.pid] = q
                    o["p"].append(q)
            else:
                o["p"] = [P("A Osc %d %s" % (n, WT_NAMES[k]), 0.5)
                          for k in range(7)]
            return o

        sc = {"osc": [osc(1, 2.0), osc(2, 0.0), osc(3, 0.0)],
              "octave": P("A Octave", -1.0), "level_pfg": P("A PFG", 3.0),
              "pan": P("A Pan"), "width": P("A Width", 1.0),
              "volume": P("A Volume", 0.9), "pitch": P("A Pitch"),
              "vca_level": P("A VCA Gain"), "vca_velsense": P("A Vel Sense"),
              "adsr": [{k: P("A AEG " + k) for k in
                        ("a", "d", "s", "r", "a_s", "d_s", "r_s", "mode")}],
              "filterunit": [{"type": P("A Filter 1 Type", 3.0)},
                             {"type": P("A Filter 2 Type", 3.0)}],
              "wsunit": {"type": P("A Waveshaper Type", 1.0)},
              "filterblock_configuration": P("A Filter Config", 2.0),
              "fm_switch": P("A FM Routing", 1.0), "lowcut": P("A Low Cut"),
              "polymode": P("A Play Mode", 4.0),
              "portamento": P("A Portamento", -4.6),
              "pbrange_up": P("A PB Up", 2.0), "pbrange_dn": P("A PB Dn", 2.0),
              "drift": P("A Drift", 0.1)}
        for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23"):
            sc["mute_" + k] = P("A Mute " + k)
        for n in (1, 2, 3):
            sc["level_o%d" % n] = P("A Osc %d Level" % n, 1.0)
            sc["route_o%d" % n] = P("A Osc %d Route" % n, 2.0)
        self.patch = {"scene": [sc], "character": P("Character"),
                      "volume": P("Volume"), "polylimit": P("Polylimit", 16),
                      "scenemode": P("Scene Mode", 1.0),
                      "fx": [{"type": P("FX %d Type" % i, 2.0)}
                             for i in range(16)]}
        self.routes = [Routing(self, Src(src), pid, depth, scene, index)
                       for (src, pid, depth, scene, index) in routes]

    # --- surgepy surface used by fixture_config ---
    def getPatch(self):
        self.log.append(("getPatch", self.gen))
        return self.patch

    def getParamVal(self, p):
        return p.value

    def setParamVal(self, p, v):
        self.log.append(("set", p.name, p.gen))
        p.value = float(v)
        if p is self.patch["scene"][0]["osc"][0]["type"]:
            self.pending_type = float(v)      # queued, applied next block

    def processMultiBlock(self, *_a):
        self.log.append(("process",))
        if self.pending_type is not None:
            self.pending_type = None
            self.gen += 1
            o = self.patch["scene"][0]["osc"][0]
            new = []
            for k, (name, dflt, mod) in enumerate(SINE):
                q = Param(o["p"][k].pid, "A Osc 1 " + name, dflt, mod, self.gen)
                self.by_pid[q.pid] = q
                new.append(q)
            # handles are fresh objects; routes keep their (pid) target --
            # clear_osc_modulation is skipped on this path (#311)
            self.patch["scene"][0]["osc"][0] = dict(o, p=new)

    def createMultiBlock(self, n):
        return None

    def getAllModRoutings(self):
        return {"global": [],
                "scene": [{"scene": [], "voice": list(self.routes)},
                          {"scene": [], "voice": []}]}

    def _find(self, dest, src, scene, index):
        for r in self.routes:
            if (r.dest_pid == dest.pid and r.src.name == src.name
                    and r.scene == scene and r.index == index):
                return r
        return None

    def setModDepth01(self, dest, src, v, scene=0, index=0):
        self.log.append(("setModDepth01", dest.pid, src.name, scene, index))
        r = self._find(dest, src, scene, index)
        if r is None or not dest.modulatable or not self.zero_works:
            return                              # engine no-op
        if v == 0.0:
            self.routes.remove(r)
        else:
            r.depth = v

    def getModDepth01(self, dest, src, scene=0, index=0):
        r = self._find(dest, src, scene, index)
        return 0.0 if r is None else r.getNormalizedDepth()

    def getExtend(self, p):
        return False

    def getAbsolute(self, p):
        return False

    def getParamMin(self, p):
        return -8.0

    def getParamMax(self, p):
        return 2.0

    def getPortamentoOptions(self, p):
        return {"constantRate": False, "glissando": False,
                "retrigger": False, "curve": 0}

    def getTempoSync(self, p):
        return False


DIGIBASS_LIKE = [("Velocity", OSC_P_BASE, 0.366964, 0, 0),
                 ("Filter EG", OSC_P_BASE, 0.223214, 0, 3),
                 ("Velocity", None, 31.7, 0, 0)]          # -> filter cutoff


def _digibass():
    s = FakeSurge()
    cutoff = Param(9001, "A Filter 1 Cutoff")
    s.by_pid[cutoff.pid] = cutoff
    s.routes = [Routing(s, Src(src), pid if pid is not None else cutoff.pid,
                        d, sc, ix) for src, pid, d, sc, ix in DIGIBASS_LIKE]
    return s


def _type_set_index(s):
    return next(i for i, e in enumerate(s.log)
                if e[0] == "set" and e[1] == "A Osc 1 Type")


# ------------------------------------------------------------------ order
def test_osc_p_routes_are_zeroed_and_read_back_before_the_type_switch():
    s = _digibass()
    d, routes = fc.configure_loaded(s, 0)
    t = _type_set_index(s)
    zeroes = [i for i, e in enumerate(s.log) if e[0] == "setModDepth01"
              and e[1] == OSC_P_BASE]
    assert len(zeroes) == 2 and all(i < t for i in zeroes)
    clear = routes["osc_p_route_clear"]
    assert routes["fixture_revision"] == fc.FIXTURE_REVISION == 2
    assert [c["dest_original_name"] for c in clear["cleared"]] == \
        ["A Osc 1 Morph", "A Osc 1 Morph"]
    for c in clear["cleared"]:
        assert c["readback_depth01"] == 0.0
        assert c["readback_raw_depth"] is None          # routing removed
        assert c["dest_param_index"] == 0
    # original state retained for the record
    assert [c["depth_original"] for c in clear["cleared"]] == \
        [0.366964, 0.223214]
    assert not [r for r in s.routes if r.dest_pid == OSC_P_BASE]
    assert routes["pinned"] == []                       # nothing "pinned" falsely
    assert d["osc_type"] == 1 and d["shape"] == 0


def test_source_scene_and_index_are_preserved_on_the_zeroing_call():
    s = _digibass()
    fc.configure_loaded(s, 0)
    calls = [e for e in s.log if e[0] == "setModDepth01" and e[1] == OSC_P_BASE]
    assert ("setModDepth01", OSC_P_BASE, "Velocity", 0, 0) in calls
    assert ("setModDepth01", OSC_P_BASE, "Filter EG", 0, 3) in calls
    rec = fc.configure_loaded(_digibass(), 0)[1]["osc_p_route_clear"]
    assert {(c["src"], c["source_scene"], c["source_index"])
            for c in rec["cleared"]} == {("Velocity", 0, 0),
                                         ("Filter EG", 0, 3)}


def test_osc_parameter_handles_are_refetched_after_the_switch():
    s = _digibass()
    fc.configure_loaded(s, 0)
    t = _type_set_index(s)
    proc = next(i for i in range(t, len(s.log)) if s.log[i] == ("process",))
    assert any(e[0] == "getPatch" and e[1] == 1 for e in s.log[proc:]), \
        "getPatch must be called again after the settle block"
    osc_p_sets = [e for e in s.log[t + 1:]
                  if e[0] == "set" and e[1].startswith("A Osc 1 ")
                  and e[1] not in ("A Osc 1 Type", "A Osc 1 Octave",
                                   "A Osc 1 Pitch", "A Osc 1 Keytrack",
                                   "A Osc 1 Retrigger", "A Osc 1 Level",
                                   "A Osc 1 Route")]
    assert osc_p_sets and all(gen == 1 for _k, _n, gen in osc_p_sets), \
        "every post-switch p[] write must go through a re-fetched handle"


def test_routes_are_matched_by_parameter_identity_not_display_name():
    s = _digibass()
    # a route into OSC 2's p[0] shares the display-name stem "Morph" but is
    # a different parameter: it must not be cleared (it is inert: o2 muted)
    o2p0 = s.patch["scene"][0]["osc"][1]["p"][0]
    s.routes.append(Routing(s, Src("Velocity"), o2p0.pid, 0.4, 0, 0))
    _d, routes = fc.configure_loaded(s, 0)
    assert all(c["dest_synth_side_id"] == OSC_P_BASE
               for c in routes["osc_p_route_clear"]["cleared"])
    assert any(r["dest"] == "A Osc 2 Morph" for r in routes["inert"])


def test_ambiguous_parameter_identity_refuses():
    s = FakeSurge(dup_pid=True)
    with pytest.raises(Refuse, match="ambiguous"):
        fc.clear_osc_param_routes(s, 0)


def test_a_failed_zeroing_readback_refuses():
    s = _digibass()
    s.zero_works = False
    with pytest.raises(Refuse, match="osc_p_route_clear readback failed"):
        fc.configure_loaded(s, 0)


def test_carrier_without_osc_p_routes_clears_nothing():
    s = FakeSurge()
    _d, routes = fc.configure_loaded(s, 0)
    assert routes["osc_p_route_clear"]["cleared"] == []
    assert [t["param_index"] for t in
            routes["osc_p_route_clear"]["targets"]] == list(range(7))


# --------------------------------------------- old order is fail-closed now
def test_old_order_type_switch_without_clear_is_refused():
    s = _digibass()
    with pytest.raises(Refuse, match="survived the type switch"):
        fc.apply_overrides(s, 0)


def test_rev1_readback_could_not_see_the_stale_route_rev2_refuses():
    """The revision-1 lie, reproduced on the double: after the switch the
    zeroing is a no-op and getModDepth01 reads 0, but the raw depth is
    intact.  Revision 2's raw-depth readback refuses instead of recording
    the route as pinned."""
    s = _digibass()
    stale = []
    _d, pinned_names = fc.apply_overrides(s, 0, _nc_record_stale=stale)
    assert {r["src"] for r in stale} == {"Velocity", "Filter EG"}
    assert all(r["dest"] == "A Osc 1 Shape" for r in stale)
    shape = s.patch["scene"][0]["osc"][0]["p"][0]
    assert s.getModDepth01(shape, Src("Velocity"), 0, 0) == 0.0   # rev-1 check
    with pytest.raises(Refuse, match="modpin_zero readback failed"):
        fc.classify_and_pin_routes(s, pinned_names)


def _function_source(src, name):
    tree = ast.parse(src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node)


def test_production_entry_points_never_pass_the_private_control_hook():
    src = open(fc.__file__, encoding="utf-8").read()
    for fn in ("build_instance", "configure_loaded",
               "clear_osc_param_routes", "classify_and_pin_routes",
               "probe_cut_activation"):
        body = _function_source(src, fn)
        assert "_nc_record_stale" not in body, fn
    for rel in ("model/voice/playmode/extract_inputs.py",
                "tools/render_pm_reference.py"):
        assert "_nc_record_stale" not in open(os.path.join(REPO, rel),
                                              encoding="utf-8").read()


# ------------------------------------- committed-state invariants (no oracle)
def test_normalized_corpus_osc1_route_inventory_for_the_carriers():
    """Hazard inventory from the committed normalized native state
    (graphs.jsonl): of the three declared carriers only Digibass routes into
    an osc-1 parameter, and those are the two #311 routes."""
    want = {fc.preset_rel(c): c for c in fc.FIXTURE_CARRIERS}
    found = {}
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") in want:
                md = g["g"]["md"]["s"][0]
                found[want[g["p"]]] = sorted(
                    (row[0], row[3], row[4]) for row in md["s"] + md["v"]
                    if row[4].startswith("A Osc 1 "))
    assert set(found) == set(fc.FIXTURE_CARRIERS)
    assert found["bass2"] == [] and found["bass5"] == []
    assert found["digibass"] == [(1, 225, "A Osc 1 Morph"),
                                 (16, 225, "A Osc 1 Morph")]


def test_renderer_revision_gate_refuses_other_revision_inputs():
    with pytest.raises(Refuse, match="fixture revision 1.*STALE"):
        fc.require_current_revision({}, "inputs/x.json")       # rev 1: no field
    with pytest.raises(Refuse, match="STALE"):
        fc.require_current_revision({"fixture_revision": 3}, "x")
    assert fc.require_current_revision(
        {"fixture_revision": fc.FIXTURE_REVISION}, "x") == 2
    # every committed sidecar is revision 1 today -> the renderer refuses it
    for c in fc.FIXTURE_CARRIERS:
        p = os.path.join(REPO, "model", "voice", "playmode", "inputs",
                         c + ".json")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("fixture_revision", 1) != fc.FIXTURE_REVISION:
            with pytest.raises(Refuse, match="STALE"):
                fc.require_current_revision(d, c)
    # and the renderer actually routes through the gate
    with open(os.path.join(REPO, "tools", "render_pm_reference.py"),
              encoding="utf-8") as f:
        rsrc = f.read()
    assert "fc.require_current_revision(inputs," in \
        _function_source(rsrc, "main")


def test_fake_surgepy_is_scoped_to_the_test():
    """Regression guard for the CI leak: the stand-in must be removed (or
    the prior entry restored) when the fixture's monkeypatch is undone."""
    assert sys.modules["surgepy"].__name__ == "surgepy"
    assert not hasattr(sys.modules["surgepy"], "__file__")   # the stand-in
    before = {k: sys.modules.get(k) for k in ("surgepy", "surgepy.constants")}
    mp = pytest.MonkeyPatch()
    gen = _install_fake_surgepy(mp)
    inner = next(gen)
    assert sys.modules["surgepy"] is inner
    with pytest.raises(StopIteration):
        next(gen)
    mp.undo()
    assert {k: sys.modules.get(k) for k in before} == before


def test_current_revision_inputs_never_record_an_osc_p_route_as_pinned():
    for c in fc.FIXTURE_CARRIERS:
        p = os.path.join(REPO, "model", "voice", "playmode", "inputs",
                         c + ".json")
        d = json.load(open(p, encoding="utf-8"))
        if d.get("fixture_revision", 1) != fc.FIXTURE_REVISION:
            continue        # STALE revision-1 sidecar; see EVIDENCE.md
        assert not [r for r in d["modulation_routes"]["pinned"]
                    if r["dest"].startswith("A Osc 1 ")], c


# ------------------------------------------------- valid-reference gate
def _tone(f, seconds=1.25, amp=0.4):
    t = np.arange(int(seconds * rv.SR)) / rv.SR
    return amp * np.sin(2 * math.pi * f * t)


F0_DIGIBASS = rv.expected_f0(60, -1)


def test_expected_f0_uses_key_scene_octave_and_standard_tuning():
    assert rv.expected_f0(69, 0) == 440.0
    assert abs(F0_DIGIBASS - 130.8128) < 1e-3


def test_gate_accepts_a_pitched_sine_at_the_probe_key():
    rec = rv.check(_tone(F0_DIGIBASS), 0, F0_DIGIBASS)
    assert rec["verdict"] == "PASS", rec["fails"]
    assert abs(rec["pitch_error_cents"]) < 1.0


def test_gate_rejects_silence():
    rec = rv.check(np.zeros(int(1.25 * rv.SR)), 0, F0_DIGIBASS)
    assert rec["verdict"] == "FAIL"
    assert rec["meaning"] == "NOT A VALID COMPARISON"


def test_gate_rejects_a_stale_nonpitched_buffer():
    # the #311 stale-buffer observation: nonzero, dominant ~1.46 kHz at key 60
    rec = rv.check(_tone(1460.0, amp=0.2), 0, F0_DIGIBASS)
    assert rec["verdict"] == "FAIL"
    rng = np.random.default_rng(329)
    rec = rv.check(0.2 * rng.standard_normal(int(1.25 * rv.SR)), 0,
                   F0_DIGIBASS)
    assert rec["verdict"] == "FAIL"


def test_gate_rejects_the_wrong_octave_and_an_out_of_tolerance_pitch():
    assert rv.check(_tone(2 * F0_DIGIBASS), 0, F0_DIGIBASS)["verdict"] == "FAIL"
    off = F0_DIGIBASS * 2 ** (40 / 1200)
    assert rv.check(_tone(off), 0, F0_DIGIBASS)["verdict"] == "FAIL"


def test_gate_ignores_a_transient_outside_the_held_segment():
    x = _tone(F0_DIGIBASS)
    x[:int(0.2 * rv.SR)] += 0.5 * np.sign(np.sin(np.arange(int(0.2 * rv.SR))))
    assert rv.check(x, 0, F0_DIGIBASS)["verdict"] == "PASS"
