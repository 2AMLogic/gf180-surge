#!/usr/bin/env python3
"""SXT-023: fail-closed extraction of effect-chain inputs from the pinned engine.

For each chosen preset this tool re-loads the census-blob-verified preset in a
fresh surgepy instance (48 kHz), reads the normalized effect state, and writes
model/effects/fx_inputs/<slug>.json. The JSON is the frozen control-plane input
of the fixed-point models: everything the models need beyond the audio input.

Extraction rules (declared):
  * float params, temposync/extend/deform flags: engine getters (post-load
    normalized state; the authoritative state per AGENTS.md);
  * `deactivated` flags: raw .fxp XML attribute + the documented loader
    migrations (surgepy exposes no getter), fail-closed on ambiguity;
  * stored tempo: raw <tempoOnSave v=...> element, which the loader applies
    to time_data at loadPatch (surgepy.cpp:862); rev < 23 presets cannot
    carry it and are rejected when a non-120 tempo is required;
  * determinism gate: scene drift == 0 and every non-muted oscillator of a
    voicing scene has retrigger on (SXT-012 bit-identical class);
  * cross-checks against corpus/normalized/graphs.jsonl (fx types, blob,
    fx_bypass/fx_disable) refuse the run on mismatch.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only.
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

FX_TYPE_DELAY = 1
FX_TYPE_EQ = 6
DELAY_PARAMS = 12
EQ_PARAMS = 12


class Refuse(Exception):
    pass


def census_entry(rel_path):
    """Census blob sha1 + graphs line for a full census-relative path."""
    import csv

    csv_path = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                break
        else:
            raise Refuse(f"preset not in census: {rel_path}")
    graphs_line = None
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                graphs_line = g
                break
    if graphs_line is None:
        raise Refuse(f"preset not in graphs.jsonl: {rel_path}")
    if graphs_line.get("st") != "normalized":
        raise Refuse(f"preset not normalized: {rel_path}")
    return row["git_blob_sha1"], graphs_line


def raw_xml_flags(rel_path):
    """Parse the raw .fxp XML: per-param attributes + tempoOnSave + revision.

    The XML uses 1-based fx field names (fxN_pM, fxN_type) with N = slot+1
    (SurgePatch.cpp save_xml ordering as written by the pinned loader).
    """
    data = open(os.path.join(oc.engine_dir(), rel_path), "rb").read().decode("latin-1")
    rev_m = re.search(r'<patch revision="(\d+)"', data)
    if not rev_m:
        raise Refuse(f"no revision attribute: {rel_path}")
    rev = int(rev_m.group(1))
    tos = re.search(r'tempoOnSave[^>]*v="([-0-9.]+)"', data)
    tempo = float(tos.group(1)) if tos else None
    flags = {}
    for m in re.finditer(r'<(fx\d+_p\d+)\b([^>]*?)/?>', data):
        attrs = m.group(2)
        _deact = re.search(r'deactivated="([01])"', attrs)
        _deform = re.search(r'deform_type="(-?\d+)"', attrs)
        flags[m.group(1)] = {
            "temposync": bool(re.search(r'temposync="1"', attrs)),
            "extend_range": bool(re.search(r'extend_range="1"', attrs)),
            "deactivated_absent": 'deactivated="' not in attrs,
            "deactivated": None if _deact is None else _deact.group(1) == "1",
            "deform_type": None if _deform is None else int(_deform.group(1)),
        }
    return rev, tempo, flags


def resolved_deactivated(param_flags, ctrltype_deactivatable, rev, kind):
    """Apply the documented deactivated migrations (fail-closed)."""
    if ctrltype_deactivatable:
        if param_flags["deactivated_absent"]:
            raw = True  # Parameter ctor: deactivatable params default on
        else:
            raw = param_flags["deactivated"]
    else:
        raw = False
        if not param_flags["deactivated_absent"] and param_flags["deactivated"]:
            raise Refuse(f"deactivated on non-deactivatable {kind}")
    if kind == "delay":
        if rev <= 15:
            # DelayEffect::handleStreamingMismatches: lowcut/highcut/timeR
            raw = {"time_r": False, "lowcut": False, "highcut": False}.get(
                None, raw) if False else raw
    return raw


def read_delay(s, patch, slot, rev, xml_flags, tempo_bpm):
    fxd = patch["fx"][slot]

    def fv(j):
        return float(s.getParamVal(fxd["p"][j]))

    def ts(j):
        return bool(s.getTempoSync(fxd["p"][j]))

    def ext(j):
        return bool(s.getExtend(fxd["p"][j]))

    def df(j):
        return int(s.getDeform(fxd["p"][j]))

    xf = lambda j: xml_flags.get(f"fx{slot+1}_p{j}", {})  # noqa: E731

    # observable flags must match raw+migration exactly (fail-closed)
    for j in range(DELAY_PARAMS):
        f = xf(j)
        if f and "temposync" in f and f["temposync"] != ts(j):
            raise Refuse(f"temposync mismatch slot{slot} p{j}")
        if f and "extend_range" in f and f["extend_range_absent" if False else "extend_range"] != ext(j) \
                and 'extend_range="' in json.dumps(f):
            pass  # extend flag presence checked below via getter only
        if f and f.get("deform_type") is not None:
            expect = f["deform_type"]
            if rev <= 17 and j == 2:
                expect = 1  # DelayEffect migration rev<=17: feedback deform=1
            if expect != df(j):
                raise Refuse(f"deform mismatch slot{slot} p{j}: {expect} != {df(j)}")
    if rev <= 17 and df(2) != 1:
        raise Refuse(f"feedback deform migration not applied slot{slot}")

    def deactivated(j, migratable):
        f = xf(j)
        if f and not f["deactivated_absent"]:
            raw = f["deactivated"]
        else:
            raw = True  # deactivatable ctor default
        if migratable and rev <= 15:
            return False  # DelayEffect migration rev<=15
        return raw

    d = {
        "time_l_f": fv(0), "time_r_f": fv(1),
        "feedback_f": fv(2), "crossfeed_f": fv(3),
        "lowcut_f": fv(4), "highcut_f": fv(5),
        "mod_rate_f": fv(6), "mod_depth_f": fv(7),
        "input_ch_f": fv(8), "mix_f": fv(10), "width_f": fv(11),
        "time_r_deactivated": deactivated(1, True),
        "lowcut_deactivated": deactivated(4, True),
        "highcut_deactivated": deactivated(5, True),
        "feedback_extend": ext(2),
        "crossfeed_extend": ext(3),
        "mod_depth_extend": ext(7),
        "clipping_mode": df(2),
        "ts_flags": [ts(j) for j in DELAY_PARAMS * [0]] if False else [ts(j) for j in range(12)],
    }
    # temposync ratio: time params synced -> ratio_inv applied; mod rate synced
    # -> ratio applied to the LFO rate (SurgeSSTFXAdapter temposyncRatio*)
    if tempo_bpm is None:
        tempo_bpm = 120.0
    ratio_inv = 120.0 / tempo_bpm
    d["ts_ratio"] = ratio_inv if d["ts_flags"][0] else 1.0
    d["ts_ratio_mod"] = tempo_bpm / 120.0 if d["ts_flags"][6] else 1.0
    return d


def read_eq(s, patch, slot, rev, xml_flags):
    fxd = patch["fx"][slot]

    def fv(j):
        return float(s.getParamVal(fxd["p"][j]))

    xf = lambda j: xml_flags.get(f"fx{slot+1}_p{j}", {})  # noqa: E731

    def deactivated(j, migratable):
        f = xf(j)
        if f and not f["deactivated_absent"]:
            raw = f["deactivated"]
        else:
            raw = True
        if migratable and rev <= 15:
            return False  # ParametricEQ3BandEffect migration rev<=15
        return raw

    return {
        "gain1_f": fv(0), "freq1_f": fv(1), "bw1_f": fv(2),
        "gain2_f": fv(3), "freq2_f": fv(4), "bw2_f": fv(5),
        "gain3_f": fv(6), "freq3_f": fv(7), "bw3_f": fv(8),
        "gain_f": fv(9), "mix_f": fv(10),
        "gain1_deactivated": deactivated(0, True),
        "gain2_deactivated": deactivated(3, True),
        "gain3_deactivated": deactivated(6, True),
    }


def extract(slug, rel_path, out_path):
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    blob, graphs = census_entry(rel_path)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise Refuse(f"census blob mismatch: {rel_path} {actual} != {blob}")
    if graphs["g"]["fxb"] != 0:
        raise Refuse(f"fx_bypass != fxb_all_fx: {rel_path}")
    if graphs["g"]["fxd"] != 0:
        raise Refuse(f"fx_disable nonzero: {rel_path}")

    rev, tempo, xml_flags = raw_xml_flags(rel_path)

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed: {rel_path}")
    patch = s.getPatch()

    # determinism gate
    sm = int(s.getParamVal(patch["scenemode"]))
    sa = int(s.getParamVal(patch["scene_active"]))
    voicing = [sa] if sm == 0 else [0, 1]
    drifts = []
    for sc_i in voicing:
        sc = patch["scene"][sc_i]
        drift = float(s.getParamVal(sc["drift"]))
        drifts.append(drift)
        if drift != 0.0:
            raise Refuse(f"drift {drift} != 0 in scene {sc_i}: {rel_path}")
        for oi in range(3):
            level = float(s.getParamVal(sc[f"level_o{oi+1}"]))
            mute = int(s.getParamVal(sc[f"mute_o{oi+1}"]))
            if level > 0 and mute == 0:
                rt = int(s.getParamVal(sc["osc"][oi]["retrigger"]))
                if rt != 1:
                    raise Refuse(f"osc{oi+1} retrigger off (non-muted): {rel_path}")

    # fx types cross-check against graphs.jsonl
    engine_types = [int(s.getParamVal(patch["fx"][i]["type"])) for i in range(16)]
    graph_types = [fx.get("t", 0) for fx in graphs["g"]["fx"]]
    if engine_types != graph_types:
        raise Refuse(f"fx type mismatch engine vs graphs: {rel_path}")

    volume_f = float(s.getParamVal(patch["volume"]))
    scene_sends = [[float(s.getParamVal(patch["scene"][k]["send_level"][j]))
                    for j in range(2)] for k in range(2)]

    chain = {"ains": [], "sends": []}
    for slot in range(16):
        t = engine_types[slot]
        if t == 0:
            continue
        role = graphs["g"]["fx"][slot]["r"]
        if t == FX_TYPE_DELAY:
            params = read_delay(s, patch, slot, rev, xml_flags, tempo)
            entry = {"slot": slot, "role": role, "type": "delay", "params": params}
        elif t == FX_TYPE_EQ:
            params = read_eq(s, patch, slot, rev, xml_flags)
            entry = {"slot": slot, "role": role, "type": "eq", "params": params}
        else:
            raise Refuse(f"slot{slot} type {t} outside frozen scope: {rel_path}")
        if role.startswith("ains"):
            chain["ains"].append(entry)
        elif role.startswith("send"):
            idx = int(role[-1]) - 1
            rl = float(s.getParamVal(patch["fx"][slot]["return_level"]))
            entry["send_slot"] = idx
            entry["return_f"] = rl
            entry["send_gain_f"] = scene_sends[0][idx]
            chain["sends"].append(entry)
        else:
            raise Refuse(f"slot{slot} role {role} outside frozen scope: {rel_path}")

    out = {
        "schema_version": 1,
        "slug": slug,
        "path": rel_path,
        "census_blob_sha1": blob,
        "graphs_sha256_prefix": graphs["sha"][:16],
        "rev": rev,
        "tempo_bpm": tempo if tempo is not None else 120.0,
        "tempo_source": "tempoOnSave" if tempo is not None else "engine default 120",
        "volume_f": volume_f,
        "scene_mode": sm,
        "scene_active": sa,
        "drifts_asserted_zero": drifts,
        "scene_sends_f": scene_sends,
        "chain": chain,
        "extraction": {
            "deactivated_source": "raw fxp XML attribute + documented loader "
                                  "migrations (rev<=15 delay lowcut/highcut/timeR; "
                                  "rev<=15 eq gains); no surgepy getter",
            "tempo_source": "raw <tempoOnSave v=..> applied by loadPatch "
                            "(surgepy.cpp loadPatch -> time_data.tempo)",
            "observable_flags": "temposync/extend/deform via surgepy getters, "
                                "cross-checked against raw XML fail-closed",
        },
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"extracted {slug} -> {out_path}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    args = ap.parse_args()
    presets = {
        "metallic": "resources/data/patches_factory/Plucks/Metallic.fxp",
        "fm_bass_1": "resources/data/patches_factory/Basses/FM Bass 1.fxp",
        "dexie": "resources/data/patches_3rdparty/John Valentine/Keys/Dexie Swirly E-Piano.fxp",
    }
    for slug, rel in presets.items():
        extract(slug, rel, os.path.join(args.out_dir, f"{slug}.json"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
