#!/usr/bin/env python3
"""SXT-028c: fail-closed extraction of Chorus-chain inputs from the engine.

Follows model/effects/extract_fx_inputs.py (SXT-023) conventions: census
blob re-verified at extraction, graphs.jsonl fx types cross-checked,
temposync/deform flags via surgepy getters cross-checked against the raw
.fxp XML (fail-closed), `deactivated` flags from the raw XML attribute +
documented loader migrations (ChorusEffect handleStreamingMismatches:
rev<=15 resets lowcut/highcut deactivated to false), drift == 0 and
non-muted-oscillator retrigger-on asserted for every voicing scene
(SXT-012 bit-identical determinism class), no modulation routes into FX
parameters (fail-closed refusal, SXT-028a precedent).

Writes model/effects/fx_inputs/type-chorus-<slug>.json — the frozen
control-plane input of the chorus model: the chorus slot parameters, the
landed sibling chain (eq / delay / reverb1 classes) with their own
parameters, send/return gains, tempo, and an applicability record that
states whether a complete-wet render is possible for the preset (it is
refused when any active slot needs an unlanded sibling class — fail-
closed, never silently dropped).

Chorus (fxt_chorus4 = 9) parameters (ChorusEffect.h chorus_params):
time(0) rate(1) depth(2) feedback(3) lowcut(4) highcut(5) mix(6) width(7).

Original to this repository (Apache-2.0); imports the GPL engine at
runtime only.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

from model.effects.extract_fx_inputs import (  # noqa: E402
    Refuse, census_entry, raw_xml_flags, read_delay, read_eq,
)

FX_TYPE_CHORUS = 9
CHORUS_PARAMS = 8
LANDED_CLASSES = {0, 1, 2, 6, 9}  # off, delay, reverb1, eq, chorus(this leaf)

PRESETS = {
    # issue-named carriers (extract + applicability; refusals recorded)
    "novuo": "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp",
    "ancient_fm": "resources/data/patches_3rdparty/Altenberg/Basses/Ancient FM.fxp",
    "piercing": "resources/data/patches_3rdparty/Altenberg/Basses/Piercing.fxp",
    # deterministic full-chain carriers (see EVIDENCE.md §1)
    "fmcombo": "resources/data/patches_factory/Basses/FM Combo.fxp",
    "fmtwang2": "resources/data/patches_3rdparty/Luna/MPE/FM Twang 2.fxp",
    "melon": "resources/data/patches_factory/Polysynths/Melon.fxp",
}


def read_chorus(s, patch, slot, rev, xml_flags, tempo_bpm):
    fxd = patch["fx"][slot]

    def fv(j):
        return float(s.getParamVal(fxd["p"][j]))

    def ts(j):
        return bool(s.getTempoSync(fxd["p"][j]))

    xf = lambda j: xml_flags.get(f"fx{slot+1}_p{j}", {})  # noqa: E731

    # observable temposync flags must match raw XML exactly (fail-closed)
    for j in range(CHORUS_PARAMS):
        f = xf(j)
        if f and "temposync" in f and f["temposync"] != ts(j):
            raise Refuse(f"temposync mismatch slot{slot} p{j}")

    def deactivated(j):
        f = xf(j)
        if f and not f["deactivated_absent"]:
            raw = f["deactivated"]
        else:
            raw = True  # deactivatable ctor default
        if rev <= 15:
            return False  # ChorusEffect::handleStreamingMismatches rev<=15
        return raw

    d = {
        "time_f": fv(0), "rate_f": fv(1), "depth_f": fv(2),
        "feedback_f": fv(3), "lowcut_f": fv(4), "highcut_f": fv(5),
        "mix_f": fv(6), "width_f": fv(7),
        "lowcut_deactivated": deactivated(4),
        "highcut_deactivated": deactivated(5),
        "ts_flags": [ts(j) for j in range(CHORUS_PARAMS)],
    }
    if tempo_bpm is None:
        tempo_bpm = 120.0
    # ChorusEffect setvars: time temposync -> temposyncratio_inv on tm;
    # rate temposync -> temposyncratio on the LFO rate
    d["ts_time"] = bool(d["ts_flags"][0])
    d["ts_rate"] = bool(d["ts_flags"][1])
    d["ts_ratio"] = 120.0 / tempo_bpm if d["ts_time"] else 1.0
    d["ts_ratio_mod"] = tempo_bpm / 120.0 if d["ts_rate"] else 1.0
    return d


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
    for m in graphs["g"].get("md", []):
        if len(m) > 4 and "FX" in str(m[4]):
            raise Refuse(f"modulation route into FX parameter ({m[4]}): {rel_path}")

    rev, tempo, xml_flags = raw_xml_flags(rel_path)

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed: {rel_path}")
    patch = s.getPatch()

    # determinism gate (voicing scenes only, SXT-023 rule)
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

    engine_types = [int(s.getParamVal(patch["fx"][i]["type"])) for i in range(16)]
    graph_types = [fx.get("t", 0) for fx in graphs["g"]["fx"]]
    if engine_types != graph_types:
        raise Refuse(f"fx type mismatch engine vs graphs: {rel_path}")

    # applicability: complete-wet render possible only when every active
    # class is landed/in-flight (delay landed-FAIL caveat recorded)
    out_of_scope = sorted({t for t in engine_types if t not in LANDED_CLASSES})
    has_delay = 1 in engine_types
    complete_wet = not out_of_scope
    if not complete_wet:
        print(f"applicability {slug}: complete-wet REFUSED (unlanded classes "
              f"{out_of_scope})", file=sys.stderr)

    volume_f = float(s.getParamVal(patch["volume"]))
    scene_sends = [[float(s.getParamVal(patch["scene"][k]["send_level"][j]))
                    for j in range(2)] for k in range(2)]

    chain = {"ains": [], "sends": []}
    chorus_slots = []
    for slot in range(16):
        t = engine_types[slot]
        if t == 0:
            continue
        role = graphs["g"]["fx"][slot]["r"]
        if t == FX_TYPE_CHORUS:
            params = read_chorus(s, patch, slot, rev, xml_flags, tempo)
            entry = {"slot": slot, "role": role, "type": "chorus", "params": params}
            chorus_slots.append(slot)
        elif t == 1:
            params = read_delay(s, patch, slot, rev, xml_flags, tempo)
            entry = {"slot": slot, "role": role, "type": "delay", "params": params}
        elif t == 6:
            params = read_eq(s, patch, slot, rev, xml_flags)
            entry = {"slot": slot, "role": role, "type": "eq", "params": params}
        elif t in (2,):
            # reverb1 (SXT-024): its frozen inputs are extracted by the
            # reverb tooling; recorded here as class-present only
            entry = {"slot": slot, "role": role, "type": "reverb1",
                     "note": "inputs via model/effects/reverb1 tooling"}
        else:
            raise Refuse(f"slot{slot} type {t} outside landed scope: {rel_path}")
        if role.startswith("ains"):
            chain["ains"].append(entry)
        elif role.startswith("send"):
            idx = int(role[-1]) - 1
            rl = float(s.getParamVal(patch["fx"][slot]["return_level"]))
            entry["send_slot"] = idx
            entry["return_f"] = rl
            entry["send_gain_f"] = scene_sends[0][idx]
            chain["sends"].append(entry)
        elif role.startswith("global") or role.startswith("bins"):
            entry["inactive_note"] = ("global/bins slot recorded for census; "
                                      "not processed by this leaf's chain model")
            chain.setdefault("inactive", []).append(entry)
        else:
            raise Refuse(f"slot{slot} role {role} outside frozen scope: {rel_path}")

    out = {
        "schema_version": 1,
        "leaf": "SXT-028c",
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
        "chorus_slots": chorus_slots,
        "chain": chain,
        "applicability": {
            "complete_wet_render_possible": complete_wet,
            "unlanded_classes": out_of_scope,
            "delay_sibling_landed_fail": has_delay,
            "note": "complete-wet refused fail-closed when any active slot "
                    "needs an unlanded class; refusal retained as evidence",
        },
        "extraction": {
            "deactivated_source": "raw fxp XML attribute + documented loader "
                                  "migration (rev<=15 chorus lowcut/highcut); "
                                  "no surgepy getter",
            "tempo_source": "raw <tempoOnSave v=..> applied by loadPatch "
                            "(surgepy.cpp loadPatch -> time_data.tempo)",
            "observable_flags": "temposync via surgepy getters, cross-checked "
                                "against raw XML fail-closed",
            "mod_routes": "graphs.jsonl md rows screened; any FX-destination "
                          "route refuses extraction (fail-closed)",
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
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--refusals",
                    default=os.path.join(REPO, "reports", "SXT-028c",
                                         "artifacts", "extract-refusals.txt"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
    refusals = []
    for slug, rel in sorted(PRESETS.items()):
        try:
            extract(slug, rel, os.path.join(args.out_dir, f"type-chorus-{slug}.json"))
        except Refuse as e:
            refusals.append(f"{slug}: REFUSED: {e}")
            print(f"REFUSED {slug}: {e}", file=sys.stderr)
    with open(args.refusals, "w", encoding="utf-8") as f:
        f.write("\n".join(refusals) + ("\n" if refusals else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
