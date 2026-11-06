#!/usr/bin/env python3
"""#495: Classic/Sine fixture_config consolidation -- exact before/after check.

A recording fake ``surgepy`` drives each family's ``build_instance`` (every
CARRIERS key) and ``apply_overrides`` + ``read_params``; the ordered
set/get/createMultiBlock/processMultiBlock call log, the returned params dict
and any ``Refuse`` text are compared with goldens captured from the
PRE-change files (origin/main @ ac8a3ce) in tests/golden/osc_fixture_core/.

Regenerate goldens only deliberately:  OSC_FIXTURE_CORE_WRITE_GOLDEN=1
Scope: this checks the fake-driven call sequence only. It makes no
model-vs-reference or fidelity claim and does not re-run SXT-033/SXT-040.
"""

import hashlib
import importlib.util
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(REPO, "tests", "golden", "osc_fixture_core")
FAMILIES = {"classic": "classic", "sine": "sine"}

# sha256 of each committed golden (captured from the pre-change files)
GOLDEN_SHA256 = {
    "classic": "a8e0081694064aba43f24018ce9680fed30d05931b50e38af31884e632f34c1f",
    "sine": "3a634f1c8ebe4fe5b022cea35d1523e3615832f2dd5b435df698450878f3b9e3",
}


class Param:
    def __init__(self, name, v=0.0):
        self.name, self.value = name, float(v)


class FakeSurge:
    """Recording stand-in for the surgepy synth surface fixture_config uses."""

    def __init__(self, load_ok=True):
        self.log = []
        self.load_ok = load_ok
        self.patch = None

    def _p(self, name, v=0.0):
        return Param(name, v)

    def _build(self):
        P = self._p

        def osc(n):
            return {"type": P("osc%d.type" % n, 1.0),
                    "octave": P("osc%d.octave" % n, 0.0),
                    "pitch": P("osc%d.pitch" % n, 0.25),
                    "keytrack": P("osc%d.keytrack" % n, 1.0),
                    "retrigger": P("osc%d.retrigger" % n, 0.0),
                    "p": [P("osc%d.p%d" % (n, k), 0.1 * (k + n))
                          for k in range(7)]}
        sc = {"osc": [osc(1), osc(2), osc(3)],
              "octave": P("octave"), "drift": P("drift", 0.3),
              "level_pfg": P("level_pfg", 1.0), "pan": P("pan"),
              "width": P("width", 1.0), "volume": P("volume", 0.9),
              "vca_level": P("vca_level"), "vca_velsense": P("vca_velsense"),
              "adsr": [{k: P("adsr." + k, 0.5) for k in
                        ("a", "d", "s", "r", "a_s", "d_s", "r_s", "mode")}],
              "filterunit": [{"type": P("fu0.type", 3.0)},
                             {"type": P("fu1.type", 3.0)}],
              "wsunit": {"type": P("ws.type", 1.0)},
              "filterblock_configuration": P("fbc", 2.0),
              "fm_switch": P("fm_switch", 1.0), "lowcut": P("lowcut", -10.0),
              "polymode": P("polymode", 0.0)}
        for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23"):
            sc["mute_" + k] = P("mute_" + k, 0.0)
        for n in (1, 2, 3):
            sc["level_o%d" % n] = P("level_o%d" % n, 1.0)
            sc["route_o%d" % n] = P("route_o%d" % n, 2.0)
        self.patch = {"scene": [sc], "character": P("character", 1.0),
                      "volume": P("master", -3.0),
                      "scenemode": P("scenemode", 1.0),
                      "fx": [{"type": P("fx%d.type" % i, 2.0)}
                             for i in range(16)]}

    def loadPatch(self, path):
        self.log.append(("loadPatch", os.path.basename(path)))
        if self.load_ok:
            self._build()
        return self.load_ok

    def getPatch(self):
        self.log.append(("getPatch",))
        return self.patch

    def getParamVal(self, p):
        self.log.append(("get", p.name))
        return p.value

    def setParamVal(self, p, v):
        self.log.append(("set", p.name, float(v)))
        p.value = float(v)

    def getExtend(self, p):
        self.log.append(("getExtend", p.name))
        return False

    def getAbsolute(self, p):
        self.log.append(("getAbsolute", p.name))
        return False

    def createMultiBlock(self, n):
        self.log.append(("createMultiBlock", n))
        return None

    def processMultiBlock(self, *_a):
        self.log.append(("processMultiBlock",))


class FakeSurgepy:
    def __init__(self, load_ok=True):
        self.made = []
        self.load_ok = load_ok

    def createSurge(self, sr):
        s = FakeSurge(self.load_ok)
        s.log.append(("createSurge", sr))
        self.made.append(s)
        return s


class FakeOC:
    def engine_dir(self):
        return "/fake/engine"


def _install_fake_surgepy_constants():
    """fx_off imports surgepy.constants lazily; stand in when absent."""
    import types
    if "surgepy.constants" not in sys.modules:
        pkg = types.ModuleType("surgepy")
        const = types.ModuleType("surgepy.constants")
        const.fxt_off = 0
        pkg.constants = const
        sys.modules.setdefault("surgepy", pkg)
        sys.modules["surgepy.constants"] = const


def _import_family(fam):
    _install_fake_surgepy_constants()
    path = os.path.join(REPO, "model", "oscillators", fam, "fixture_config.py")
    spec = importlib.util.spec_from_file_location("fc_under_test_" + fam, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def capture(fam):
    fc = _import_family(fam)
    out = {"carriers": {}, "apply": {}}
    for name in sorted(fc.CARRIERS):
        sp = FakeSurgepy()
        s = fc.build_instance(sp, FakeOC(), name)
        out["carriers"][name] = {"log": [list(e) for e in s.log],
                                 "entry": list(fc.CARRIERS[name])}
    # apply_overrides + read_params on a fresh fake for every slot
    for slot in (0, 1, 2):
        s = FakeSurge()
        s.loadPatch("/x/p.fxp")
        s.log.clear()
        d = fc.apply_overrides(s, slot)
        out["apply"][str(slot)] = {"log": [list(e) for e in s.log],
                                   "params": d}
    s = FakeSurge()
    s.loadPatch("/x/p.fxp")
    s.log.clear()
    out["read_params"] = {"params": fc.read_params(s, 1),
                          "log": [list(e) for e in s.log]}
    out["carrier_overrides"] = [[k, v] for k, v in fc.carrier_overrides(1)]
    out["preset_abs"] = fc.preset_abs(FakeOC(), sorted(fc.CARRIERS)[0])
    refusals = {}
    try:
        fc.build_instance(FakeSurgepy(load_ok=False), FakeOC(),
                          sorted(fc.CARRIERS)[0])
    except fc.Refuse as e:
        refusals["loadPatch"] = str(e)
    orig = fc.carrier_overrides
    try:
        if getattr(fc, "carrier_overrides", None):
            fc.carrier_overrides = lambda slot: [("bogus_key", True)]
            s = FakeSurge()
            s.loadPatch("/x/p.fxp")
            try:
                fc.apply_overrides(s, 0)
            except fc.Refuse as e:
                refusals["unknown_override"] = str(e)
    finally:
        fc.carrier_overrides = orig
    out["refusals"] = refusals
    return json.loads(json.dumps(out))


def _golden_path(fam):
    return os.path.join(GOLDEN, fam + ".json")


def _write(fam, data):
    with open(_golden_path(fam), "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")


if os.environ.get("OSC_FIXTURE_CORE_WRITE_GOLDEN"):
    for _fam in FAMILIES:
        _write(_fam, capture(_fam))


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.mark.parametrize("fam", sorted(FAMILIES))
def test_golden_sha_pinned(fam):
    assert _sha(_golden_path(fam)) == GOLDEN_SHA256[fam]


@pytest.mark.parametrize("fam", sorted(FAMILIES))
def test_equivalent_to_pre_change_golden(fam):
    with open(_golden_path(fam)) as f:
        golden = json.load(f)
    assert capture(fam) == golden


def test_refusal_paths_present():
    for fam in FAMILIES:
        r = capture(fam)["refusals"]
        assert r["loadPatch"].startswith("loadPatch failed: ")
        assert r["unknown_override"].startswith("unknown override ")


def _with_patched(fam, patcher):
    fc = _import_family(fam)
    patcher(fc)
    return fc


@pytest.mark.parametrize("fam", sorted(FAMILIES))
def test_negative_control_wrong_readback_is_refused(fam):
    """A wrong readback must raise Refuse('override readback failed ...')."""
    fc = _import_family(fam)
    s = FakeSurge()
    s.loadPatch("/x/p.fxp")
    real = s.setParamVal

    def lying_set(p, v):
        real(p, v)
        if p.name == "mute_noise":
            p.value = 0.0          # engine silently ignores the override
    s.setParamVal = lying_set
    with pytest.raises(fc.Refuse, match="override readback failed"):
        fc.apply_overrides(s, 0)


def test_negative_control_dropped_route_slot_breaks_equivalence():
    """Dropping Sine's route_slot_1 branch must FAIL the golden check."""
    fc = _import_family("sine")
    orig = fc.carrier_overrides
    fc.carrier_overrides = lambda slot: [
        o for o in orig(slot) if o[0] != "route_slot_1"]
    s = FakeSurge()
    s.loadPatch("/x/p.fxp")
    s.log.clear()
    fc.apply_overrides(s, 1)
    with open(_golden_path("sine")) as f:
        golden = json.load(f)
    assert [list(e) for e in s.log] != golden["apply"]["1"]["log"]


def test_negative_control_wrong_lowcut_key_breaks_equivalence():
    """Classic keys 'lowcut', Sine 'lowcut_scene': a swap must be caught."""
    c, s_ = capture("classic"), capture("sine")
    assert "lowcut" in c["read_params"]["params"]
    assert "lowcut_scene" in s_["read_params"]["params"]
    assert c != s_
