"""#314 / F-028e-sse-8: per-slot Distortion SSE corpus census (pytest).

Oracle-free. The independent derivation below does NOT call the census
tool's enumerator; it re-reads corpus/normalized/graphs.jsonl itself. The
oracle-dependent 3x determinism gates are NOT re-run here: the one row that
carries an empirical refusal is checked against the committed #136
transcript, and any other row is NOT_RUN by construction.
"""
import copy
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import census_distortion_sse_slots as cs  # noqa: E402

ART = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts")


def _independent_keys():
    keys = []
    for line in open(os.path.join(REPO, "corpus", "normalized",
                                  "graphs.jsonl")):
        r = json.loads(line)
        g = r.get("g")
        if not g:
            continue
        for f in g["fx"]:
            if f["on"] and f["tn"] == "Distortion" and f["p"][11] in (
                    3, 4, 5, 6, 7):
                keys.append((r["p"], f["i"], f["p"][11]))
    return keys


def _committed():
    return json.load(open(os.path.join(ART, "slot-census.json")))


def test_census_is_exactly_the_28_slots_one_to_one():
    keys = _independent_keys()
    assert len(keys) == 28
    c = _committed()
    got = [(s["preset"], s["slot_index"], s["fx_model"]) for s in c["slots"]]
    assert sorted(got) == sorted(keys)
    assert len(set((p, i) for p, i, _ in got)) == 28   # no dup / merge
    assert c["in_scope_slot_instances"] == 28
    assert c["model_histogram"] == {"3": 13, "4": 8, "5": 6, "6": 1, "7": 0}


def test_model7_is_recorded_separately_never_a_synthetic_row():
    c = _committed()
    assert c["model_zero_instances"] == [7]
    assert all(s["fx_model"] != 7 for s in c["slots"])


def test_committed_census_is_fresh():
    assert cs.build_census() == _committed()


def test_every_row_has_a_terminal_disposition_and_none_admitted():
    c = _committed()
    assert c["admitted_carriers"] == 0
    for s in c["slots"]:
        assert s["disposition"] in (cs.REFUSED, cs.REFUSED_EMPIRICAL), s
        assert s["static_screen_reasons"] or s["empirical_refusal_reasons"]
        assert "PASS" not in s["determinism_gate_dry"]
        assert "PASS" not in s["determinism_gate_wet"]


def test_same_preset_distinct_slots_stay_distinct():
    c = _committed()
    by = {}
    for s in c["slots"]:
        by.setdefault(s["preset"], []).append(s["slot_index"])
    multi = {p: v for p, v in by.items() if len(v) > 1}
    assert multi, "corpus has a preset with two SSE slots (Neuro Grease)"
    assert all(len(set(v)) == len(v) for v in multi.values())


def test_empirical_row_matches_committed_136_transcript():
    c = _committed()
    emp = [s for s in c["slots"] if s["disposition"] == cs.REFUSED_EMPIRICAL]
    assert [s["preset"].split("/")[-1] for s in emp] == ["Reverse Crash.fxp"]
    txt = open(os.path.join(ART, "render-refusals.txt")).read()
    assert "dry bus: determinism gate failed" in txt


def _synthetic_graph():
    for line in open(os.path.join(REPO, "corpus", "normalized",
                                  "graphs.jsonl")):
        if "Vospi/Keys/Picked Driven Synth" in line:
            r = json.loads(line)
            if r["p"].endswith("Vospi/Keys/Picked Driven Synth.fxp"):
                return r
    raise AssertionError("fixture preset missing from corpus")


def test_screens_admit_a_clean_graph_and_refuse_each_defect():
    landed = cs.landed_fx_classes()
    g = copy.deepcopy(_synthetic_graph()["g"])
    # make it clean: retrigger on for every audible osc, no mod, no disable
    for sc in g["sc"]:
        for o in sc["osc"]:
            o["rt"] = 1
    g["md"] = {"g": [], "s": [{"s": [], "v": []}, {"s": [], "v": []}]}
    g["fxd"] = 0
    g["fxb"] = 0
    for f in g["fx"]:
        if f["on"] and f["tn"] not in landed:
            f["on"] = 0
    reasons, _ = cs.preset_screens(g, landed)
    assert reasons == []                       # a clean graph is not refused
    for mutate, needle in (
        (lambda x: x.__setitem__("fxd", 1), "fx_disable"),
        (lambda x: x.__setitem__("fxb", 1), "fx_bypass"),
        (lambda x: x["md"]["g"].append([1, 0, 0, 1, "FX S1 Drive", 1, 1]),
         "modulation routed"),
        (lambda x: x["sc"][x["sa"]]["osc"][0].__setitem__("rt", 0),
         "retrigger off"),
        (lambda x: x["fx"][15].update(on=1, tn="Conditioner"), "unlanded"),
    ):
        h = copy.deepcopy(g)
        # ensure osc1 is audible so the retrigger screen can fire
        h["sc"][h["sa"]]["mix"]["o1"][0] = 1.0
        h["sc"][h["sa"]]["mix"]["o1"][1] = 0
        mutate(h)
        r, _ = cs.preset_screens(h, landed)
        assert any(needle in x for x in r), (needle, r)


def test_no_unlanded_class_is_substituted():
    c = _committed()
    tp = [s for s in c["slots"] if s["preset"].endswith("Trance Pluck.fxp")
          and "Damon Armani" in s["preset"]][0]
    assert tp["unlanded_classes_in_chain"] == ["Conditioner"]
    assert tp["disposition"] == cs.REFUSED


# ---------------------------------------------------------------------------
# #336: live parity between the oracle-free census mirror and the oracle-read
# screens committed in the SSE extraction records. Expectations are built from
# the committed record only (render_screens.refusal_reasons plus the
# renderer's unlanded-class rule), never from another call into the census.
# ---------------------------------------------------------------------------
import glob  # noqa: E402

_REC_GLOB = os.path.join(REPO, "model", "effects", "fx_inputs",
                         "type-distortion-sse-*.json")
_DRIFT = "drift = "
_UNLANDED_TAIL = (" -- a complete-wet comparison would need a model this "
                  "project has not landed, and substituting a generic is "
                  "refused")


def _screen_records():
    out = []
    for path in sorted(glob.glob(_REC_GLOB)):
        rec = json.load(open(path))
        if isinstance(rec.get("render_screens"), dict):
            out.append((path, rec))
    return out


def _graphs_by_preset():
    by = {}
    for line in open(os.path.join(REPO, "corpus", "normalized",
                                  "graphs.jsonl")):
        r = json.loads(line)
        by.setdefault(r["p"], []).append(r)
    return by


def _expected_reasons(rec):
    """Oracle record -> expected mirror reasons (drift excluded; the one
    known em-dash/`--` separator spelling is the census's)."""
    exp = [r for r in rec["render_screens"]["refusal_reasons"]
           if not r.startswith(_DRIFT)]
    if rec.get("unlanded_classes_in_chain"):
        exp.append("unlanded class(es) in the active chain: "
                   + ", ".join(rec["unlanded_classes_in_chain"])
                   + _UNLANDED_TAIL)
    return exp


def _assert_parity(path, rec, graphs, mirror):
    name = os.path.basename(path)
    matches = graphs.get(rec["preset_path"], [])
    assert len(matches) == 1, (name, rec["preset_path"], len(matches),
                               "expected exactly one normalized graph")
    landed = set(rec["landed_classes_basis"]["landed_fx_classes"])
    reasons, detail = mirror(matches[0]["g"], landed)
    expected = _expected_reasons(rec)
    assert sorted(reasons) == sorted(expected), (
        f"{name} [{rec['preset_path']}] mirror/oracle screen mismatch:\n"
        f"  mirror  : {sorted(reasons)}\n  oracle  : {sorted(expected)}")
    assert detail["unlanded"] == sorted(
        rec.get("unlanded_classes_in_chain") or []), (name, detail)


def test_mirror_screens_match_committed_oracle_screens():
    recs = _screen_records()
    assert recs, "no committed SSE record carries render_screens"
    graphs = _graphs_by_preset()
    for path, rec in recs:
        _assert_parity(path, rec, graphs, cs.preset_screens)


def test_parity_population_covers_the_distinguishing_cases():
    recs = {os.path.basename(p): r for p, r in _screen_records()}
    names = set(recs)
    for n in ("reversecrash", "mutantlofiacoustic", "trancepluck"):
        assert f"type-distortion-sse-{n}.json" in names, names
    rc = recs["type-distortion-sse-reversecrash.json"]
    assert rc["render_screens"]["refusal_reasons"] == []
    assert not rc.get("unlanded_classes_in_chain")
    ml = recs["type-distortion-sse-mutantlofiacoustic.json"]
    assert any(r.startswith("modulation routed into FX")
               for r in ml["render_screens"]["refusal_reasons"])
    tp = recs["type-distortion-sse-trancepluck.json"]
    rr = tp["render_screens"]["refusal_reasons"]
    assert sum("retrigger off" in r for r in rr) >= 2
    assert any(r.startswith(_DRIFT) for r in rr)
    assert tp["unlanded_classes_in_chain"] == ["Conditioner"]


def test_parity_control_fails_when_mirror_drops_retrigger_screen():
    import pytest

    def mutated(g, landed):
        reasons, detail = cs.preset_screens(g, landed)
        return [r for r in reasons if "retrigger off" not in r], detail

    graphs = _graphs_by_preset()
    hit = 0
    for path, rec in _screen_records():
        if not any("retrigger off" in r
                   for r in rec["render_screens"]["refusal_reasons"]):
            continue
        hit += 1
        with pytest.raises(AssertionError, match="mismatch"):
            _assert_parity(path, rec, graphs, mutated)
    assert hit >= 2


def test_parity_fails_closed_on_missing_or_duplicate_graph():
    import pytest
    path, rec = _screen_records()[0]
    with pytest.raises(AssertionError, match="exactly one"):
        _assert_parity(path, rec, {}, cs.preset_screens)
    g = _graphs_by_preset()[rec["preset_path"]][0]
    with pytest.raises(AssertionError, match="exactly one"):
        _assert_parity(path, rec, {rec["preset_path"]: [g, g]},
                       cs.preset_screens)
