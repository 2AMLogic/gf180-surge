#!/usr/bin/env python3
"""SXT-041: extract the SCENE-LFO (SLFO) slice inputs for
`Basses/Attacky.fxp` plus the declared runtime scene-modulation routes.

graphs.jsonl (SXT-011, schema rev 1.0.0) does not carry LFO definition state
at all — voice or scene. The frozen SXT-041 model needs the six scene-LFO
definitions (`scene.lfo[n_lfos_voice + i]`, i.e. indices 6..11 of the
12-entry per-scene LFO array), so this script reads them from the pinned
native engine via surgepy AFTER `loadPatch` at 48 kHz (the same
normalized-state authority as SXT-011) and writes a versioned JSON sidecar
consumed by `model/voice/run_slfo_model.py`.

Declared synthetic fixture (the preset file is NEVER modified)
--------------------------------------------------------------
The leaf's named carrier presets are not renderable end-to-end by the landed
leaves (see the SXT-041 evidence record's applicability section), so the
reference fixture is the landed SXT-022 voice-slice preset (Attacky,
census-blob verified) plus, applied at runtime through the engine's own APIs:

  * two definition overrides on SLFO2 (`setParamVal` on scene.lfo[7]):
    shape -> lt_square, rate -> 1.0. Without them all twelve LFO slots carry
    identical default definitions and per-instance state separation is not
    OBSERVABLE; with them instance 2 runs a different waveform at a
    different rate from instance 1. Read back from the engine and recorded.
  * three scene modulation routes (`setModDepth01`, host modulation API).
    Because `isScenelevel(ms_slfo*)` is true, the engine files these in
    `scene[0].modulation_scene` — the SAME list the preset's own modwheel
    routes live in — not in `modulation_voice`. That placement is the
    leaf's subject matter and is re-verified here:
        SLFO1 (ms_slfo1) -> A Filter 1 Cutoff       normalized depth 0.5
        SLFO1 (ms_slfo1) -> A Filter 1 Resonance    normalized depth 0.5
        SLFO2 (ms_slfo2) -> A Filter 1 Resonance    normalized depth 0.25

Fail-closed: re-verifies the census blob SHA-1, re-checks the SXT-022
structural gates, and REFUSES (exit 2) on any surprise instead of guessing —
shapes outside the frozen waveform set, deform != 0 on a type_3 shape,
lm_random trigger, a route that did not land in `modulation_scene`, a route
targeting an LFO parameter, or a pre-existing scene/voice LFO routing.

Run under the pinned interpreter (auto re-exec via oracle_common).
"""

import argparse
import csv
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402
from refusal import Refuse  # noqa: E402

oc.reexec_under_pinned_python(REPO)

PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus/normalized/graphs.jsonl")

N_VOICE_LFOS = 6
N_SCENE_LFOS = 6
SCENE_LFO_BASE = N_VOICE_LFOS          # scene.lfo[6..11] == ms_slfo1..6
MS_LFO1 = 17                           # ModulationSource.h pinned ids
MS_SLFO1 = 23
FROZEN_SHAPES = (0, 1, 2, 3)           # sine, tri, square, ramp
LT_SQUARE = 2

# Declared definition overrides per fixture variant.
#   "base" — SLFO2 differentiated from SLFO1 (square at 2 Hz vs sine at 1 Hz)
#            so per-instance state separation is OBSERVABLE; SLFO1 keeps the
#            preset's own definition.
#   "fast" — a declared PARAMETER CORNER near the fast end of the engine's
#            ct_lforate range (rate is pow(2, r) Hz at the pin, so r=4 is
#            16 Hz and r=5 is 32 Hz): the whole point is that at 32 Hz one
#            engine block is ~2% of a cycle, which is the regime where the
#            scene route's one-block latency is largest.
VARIANT_OVERRIDES = {
    "base": ((1, "shape", float(LT_SQUARE)), (1, "rate", 1.0)),
    "fast": ((0, "rate", 4.0),
             (1, "shape", float(LT_SQUARE)), (1, "rate", 5.0)),
}
VARIANT_OUT = {"base": "attacky_slfo_inputs.json",
               "fast": "attacky_slfo_fast_inputs.json"}

# Declared fixture routes: (slfo instance 0-based, destination param, f01)
FIXTURE_ROUTES = (
    (0, "cutoff", 0.5),
    (0, "resonance", 0.5),
    (1, "resonance", 0.25),
)

DEST_NAME = {"cutoff": "A Filter 1 Cutoff",
             "resonance": "A Filter 1 Resonance"}


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def git_blob_sha1(path):
    data = open(path, "rb").read()
    hdr = b"blob %d\x00" % len(data)
    return hashlib.sha1(hdr + data).hexdigest()


def graphs_entry(rel):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel:
                return g
    raise Refuse(f"preset not in graphs.jsonl: {rel}")


def graphs_modwheel_routes(rel):
    """The preset's own normalized modwheel routes (SXT-022 reuse)."""
    g = graphs_entry(rel)
    routes = {}
    for r in g["g"]["md"]["s"][0]["s"]:
        if r[4] == "A Filter 1 Cutoff":
            routes["cutoff_depth"] = r[5]
        elif r[4] == "A Filter 1 Resonance":
            routes["reso_depth"] = r[5]
    return routes


def structural_gates(s, g, sc, C):
    """SXT-022 slice gates (graphs export + live engine readback)."""
    gg = graphs_entry(PRESET_REL)
    A = gg["g"]["sc"][0]
    if gg["st"] != "normalized":
        raise Refuse("graphs entry not normalized")
    if gg["g"]["sm"] != 0 or gg["g"]["sa"] != 0:
        raise Refuse("not single-scene (sm/sa != 0): the scene-LFO slice is "
                     "declared on the landed single-scene voice arithmetic")
    if any(f["t"] != 0 for f in gg["g"]["fx"]):
        raise Refuse("preset has FX")
    if A["pm"] != 0:
        raise Refuse("not poly playmode")
    if A["fbc"] != 0:
        raise Refuse("filter config not serial1")
    if A["ws"]["t"] != 0:
        raise Refuse("waveshaper not off")
    if A["lc"] != -72.0:
        raise Refuse("lowcut not at off value")
    active = [k for k in ("o1", "o2", "o3") if A["mix"][k][1] == 0]
    if active != ["o1"]:
        raise Refuse(f"active mixer paths {active} != ['o1']")
    if A["osc"][0]["t"] != 0 or A["osc"][0]["uni"] != 1 \
            or A["osc"][0]["rt"] != 1:
        raise Refuse("osc1 not Classic/unison1/retrigger (graphs)")
    if A["fu"][0]["t"] != 1 or A["fu"][1]["t"] != 0:
        raise Refuse("filter units not LP12-active/2-off (graphs)")
    for slot in range(16):
        if int(s.getParamVal(g["fx"][slot]["type"])) != C.fxt_off:
            raise Refuse(f"fx slot {slot} not Off")
    if int(s.getParamVal(sc["polymode"])) != 0:
        raise Refuse("not poly playmode")
    if int(s.getParamVal(sc["filterblock_configuration"])) != 0:
        raise Refuse("filter config not serial1")
    if int(s.getParamVal(sc["wsunit"]["type"])) != 0:
        raise Refuse("waveshaper not off")
    if abs(float(s.getParamVal(sc["lowcut"])) + 72.0) > 0:
        raise Refuse("lowcut not at off value")
    if int(s.getParamVal(sc["osc"][0]["type"])) != 0 \
            or int(s.getParamVal(sc["osc"][0]["retrigger"])) != 1:
        raise Refuse("osc1 not Classic/retrigger (live readback)")
    if abs(float(s.getParamVal(sc["drift"]))) > 0:
        raise Refuse("scene drift not 0 (determinism gate)")
    if len(sc["lfo"]) != N_VOICE_LFOS + N_SCENE_LFOS:
        raise Refuse(f"scene lfo array has {len(sc['lfo'])} entries, expected "
                     f"{N_VOICE_LFOS + N_SCENE_LFOS} (pin drift)")


def read_lfo_def(s, sc, li):
    d = {nm: s.getParamVal(p) for nm, p in sc["lfo"][li].items()}
    return {k: (int(v) if k in ("shape", "trigmode", "unipolar")
                else float(v)) for k, v in sorted(d.items())}


def gate_lfo_def(d, label):
    shape = int(d["shape"])
    if shape not in FROZEN_SHAPES:
        raise Refuse(f"{label} shape {shape} outside the frozen waveform set "
                     "(noise/snh/envelope/stepseq/mseg/formula are "
                     "fail-closed)")
    if shape in (0, 1, 3) and float(d["deform"]) != 0.0:
        raise Refuse(f"{label} deform {d['deform']} on a type_3 shape is "
                     "outside the frozen slice (needs runtime sin)")
    if int(d["trigmode"]) == 2:
        raise Refuse(f"{label} trigmode lm_random (engine RNG)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--variant", choices=tuple(VARIANT_OVERRIDES),
                    default="base",
                    help="declared fixture variant (see VARIANT_OVERRIDES)")
    ap.add_argument("--out", help="output sidecar path (default: the "
                                  "variant's committed path)")
    args = ap.parse_args()
    out_path = args.out or os.path.join(REPO, "model", "voice",
                                        VARIANT_OUT[args.variant])

    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse(
            "pinned-engine preset not found at %s — set ORACLE_SURGE_DIR to "
            "the pinned engine tree (see oracle/manifest.json); this tool "
            "requires the external oracle" % preset_abs)

    actual = git_blob_sha1(preset_abs)
    expected = census_blob(PRESET_REL)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    import surgepy.constants as C

    if C.ms_slfo1 != MS_SLFO1 or C.ms_lfo1 != MS_LFO1:
        raise Refuse(f"pinned modsource ids drifted: ms_lfo1={C.ms_lfo1} "
                     f"ms_slfo1={C.ms_slfo1} (expected {MS_LFO1}/{MS_SLFO1})")

    s = surgepy.createSurge(48000.0)
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse("loadPatch failed")

        g = s.getPatch()
        sc = g["scene"][0]
        structural_gates(s, g, sc, C)

        # --- no pre-existing LFO routings (voice or scene) ------------------
        base = s.getAllModRoutings()
        for row in base["scene"]:
            for listname in ("voice", "scene"):
                for r in row.get(listname, []):
                    src = r.getSource().getModSource()
                    if MS_LFO1 <= src <= MS_SLFO1 + N_SCENE_LFOS - 1:
                        raise Refuse(
                            f"preset already routes LFO modsource {src} in "
                            f"modulation_{listname}; the isolated scene-LFO "
                            "fixture requires a clean LFO slate")
        for r in base["global"]:
            src = r.getSource().getModSource()
            if MS_LFO1 <= src <= MS_SLFO1 + N_SCENE_LFOS - 1:
                raise Refuse(f"preset already routes LFO modsource {src} "
                             "globally")
        base_scene_routes = len(base["scene"][0].get("scene", []))

        # --- declared definition overrides ---------------------------------
        overrides = []
        for inst, name, want in VARIANT_OVERRIDES[args.variant]:
            li = SCENE_LFO_BASE + inst
            before = float(s.getParamVal(sc["lfo"][li][name]))
            s.setParamVal(sc["lfo"][li][name], want)
            after = float(s.getParamVal(sc["lfo"][li][name]))
            if abs(after - want) > 1e-6:
                raise Refuse(f"SLFO{inst + 1} {name} readback {after} != "
                             f"requested {want} (engine clamped or refused)")
            lo = float(s.getParamMin(sc["lfo"][li][name]))
            hi = float(s.getParamMax(sc["lfo"][li][name]))
            if not (lo <= after <= hi):
                raise Refuse(f"SLFO{inst + 1} {name} {after} outside the "
                             f"engine-declared range [{lo}, {hi}]")
            overrides.append({"scene_lfo_index": li,
                              "modsource": f"ms_slfo{inst + 1}",
                              "param": name,
                              "preset_value": before,
                              "override_value": after,
                              "engine_range": [lo, hi]})

        # --- scene-LFO definitions (fail-closed gates) ---------------------
        slfos = []
        for i in range(N_SCENE_LFOS):
            li = SCENE_LFO_BASE + i
            d = read_lfo_def(s, sc, li)
            gate_lfo_def(d, f"SLFO{i + 1} (scene.lfo[{li}])")
            slfos.append(d)

        # the six VOICE LFOs must stay unrouted and are recorded for contrast
        voice_lfos = [read_lfo_def(s, sc, li) for li in range(N_VOICE_LFOS)]

        # engine-declared parameter ranges at the pin (acceptance: parameter
        # corners = observed carrier values PLUS the declared ranges)
        param_ranges = {}
        for name, p in sorted(sc["lfo"][SCENE_LFO_BASE].items()):
            param_ranges[name] = {"min": float(s.getParamMin(p)),
                                  "max": float(s.getParamMax(p)),
                                  "default": float(s.getParamDef(p))}
        observed = {}
        for name in param_ranges:
            vals = sorted({float(d[name]) for d in slfos})
            observed[name] = vals

        # --- declared fixture routes (host modulation API) -----------------
        routes = []
        for inst, dest_key, f01 in FIXTURE_ROUTES:
            target = sc["filterunit"][0][dest_key]
            ms = s.getModSource(C.ms_slfo1 + inst)
            if not s.isValidModulation(target, ms):
                raise Refuse(f"modulation SLFO{inst + 1} -> fu1 {dest_key} "
                             "invalid at the pin")
            s.setModDepth01(target, ms, f01, 0, 0)
            depth01 = s.getModDepth01(target, ms, 0, 0)
            if abs(depth01 - f01) > 1e-6:
                raise Refuse(f"route depth readback {depth01} != {f01}")
            routes.append({"dest": f"filterunit0_{dest_key}",
                           "dest_param": dest_key,
                           "dest_name": DEST_NAME[dest_key],
                           "slfo_instance": inst,
                           "modsource": f"ms_slfo{inst + 1}",
                           "modsource_id": MS_SLFO1 + inst,
                           "normalized_depth": f01,
                           "depth_readback": depth01})

        # --- route placement gate: scene list, not voice list --------------
        after = s.getAllModRoutings()
        row = after["scene"][0]
        if row.get("voice"):
            raise Refuse(f"{len(row['voice'])} route(s) landed in "
                         "modulation_voice; ms_slfo* is scene-level and must "
                         "file into modulation_scene (isScenelevel)")
        scene_list = row.get("scene", [])
        if len(scene_list) != base_scene_routes + len(FIXTURE_ROUTES):
            raise Refuse(f"expected {base_scene_routes + len(FIXTURE_ROUTES)} "
                         f"scene routes, got {len(scene_list)}")
        seen = {}
        for r in scene_list:
            src = r.getSource().getModSource()
            name = r.getDest().getName()
            if name not in DEST_NAME.values():
                raise Refuse(f"unexpected scene-route destination {name!r}")
            seen[(src, name)] = r.getDepth()
        for entry in routes:
            key = (entry["modsource_id"], entry["dest_name"])
            if key not in seen:
                raise Refuse(f"route readback missing for {key}")
            entry["depth_raw"] = seen[key]
        # the preset's own modwheel routes must still be present, unmodified
        mw = graphs_modwheel_routes(PRESET_REL)
        for name, want in (("A Filter 1 Cutoff", mw["cutoff_depth"]),
                           ("A Filter 1 Resonance", mw["reso_depth"])):
            got = seen.get((6, name))      # ms_modwheel == 6
            if got is None or abs(got - want) > 1e-4:
                raise Refuse(f"preset modwheel route {name} readback {got} != "
                             f"normalized {want}")

        out = {
            "schema_version": 1,
            "issue": "SXT-041",
            "variant": args.variant,
            "parameter_corners": {
                "engine_declared_ranges": param_ranges,
                "observed_scene_lfo_values": observed,
                "note": "engine-declared ranges are read live from the pin "
                        "via getParamMin/getParamMax/getParamDef on "
                        "scene.lfo[6] (ms_slfo1); observed values are the "
                        "distinct values across the six scene-LFO "
                        "definitions of THIS fixture variant",
            },
            "preset": {
                "path": PRESET_REL,
                "census_blob_sha1": expected,
                "actual_blob_sha1": actual,
            },
            "engine": {
                "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
                "version_string": surgepy.getVersion(),
                "sample_rate": int(s.getSampleRate()),
                "block_size": int(s.getBlockSize()),
                "ms_slfo1_id": int(C.ms_slfo1),
                "ms_lfo1_id": int(C.ms_lfo1),
                "scene_lfo_base_index": SCENE_LFO_BASE,
            },
            "definition_overrides": overrides,
            "fixture_routes": routes,
            "route_list": "scene[0].modulation_scene (isScenelevel(ms_slfo*) "
                          "is true; verified: modulation_voice stayed empty)",
            "preset_modwheel_routes": mw,
            "slfo_defs": slfos,
            "voice_lfo_defs_unrouted": voice_lfos,
            "frozen_scope": {
                "modsources": ["ms_slfo1..ms_slfo6 (ids 23..28)"],
                "waveforms": "sine(deform=0), tri(deform=0), square, "
                             "ramp(deform=0)",
                "destination_classes": ["A Filter 1 Cutoff",
                                        "A Filter 1 Resonance"],
                "trigmodes": ["freerun(songpos=0)", "keytrigger"],
                "scene_scheduling": [
                    "one instance set per scene, shared by every voice "
                    "(SurgeVoice ctor copies the scene modsource pointers)",
                    "attack when getNonReleasedVoices(scene) == 0 at note-on",
                    "release when getNonReleasedVoices(scene) == 0 at "
                    "note-off (gate already cleared)",
                    "scene routes consume the PREVIOUS block's output "
                    "(modulation_scene apply precedes the n_lfos_scene "
                    "process loop in processControl)",
                    "all six instances process every block while the scene "
                    "plays, routed or not, voices or not",
                ],
                "gaps": [
                    "rate temposync / deactivated flags not observable via "
                    "surgepy; frozen model implements non-temposync, "
                    "non-deactivated paths",
                    "step-sequencer grids outside normalized schema rev "
                    "1.0.0",
                    "MSEG/Formula contents not exposed by surgepy "
                    "(setIsVoice(false) is read ONLY by the Formula "
                    "modulator at this pin, so it has no arithmetic effect "
                    "inside the frozen waveform set)",
                    "noise/snh shapes consume engine RNG "
                    "(nondeterministic)",
                    "lt_envelope and type_3 deform bends need runtime sin",
                    "send-levels 3/4 exposure gap (schema README) applies to "
                    "SLFO-routed presets; not exercised by this fixture",
                    "scene B / global modulation_global destinations, "
                    "multi-scene (sm != 0) SLFO interaction",
                ],
            },
        }

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, sort_keys=True)
            f.write("\n")
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    finally:
        del s


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
