#!/usr/bin/env python3
"""SXT-033: extract the declared Classic-family fixture inputs for one carrier
from the pinned native engine.

graphs.jsonl (SXT-011) deliberately excludes envelope (ADSR) values, scene
volume/drift, mixer levels and the per-parameter extended-range/absolute
flags (schema rev 1.0.0 scope). The frozen fixed-point model needs them, so
this script reads them from the pinned engine via surgepy AFTER `loadPatch`
at 48 kHz - the same normalized state authority as the SXT-011 export - and
writes a versioned JSON sidecar consumed by `model/oscillators/classic/
classic_model.py`.

The script is fail-closed: it re-verifies the census blob SHA-1, applies the
declared isolation overrides (fixture_config.py) with readback verification,
re-checks every gate the leaf's declared parameter classes assume (Classic
osc at the modeled slot, digital envelope, Warm/Neutral character, drift 0,
deterministic retrigger, non-absolute detune, mono path), and refuses
(exit 2) on any surprise instead of guessing.

Run under the pinned interpreter (auto re-exec via oracle_common); requires
ORACLE_SURGE_DIR (the external pinned oracle).
"""

import argparse
import csv
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "classic"))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")


class Refuse(Exception):
    pass


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def graphs_entry(rel):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel:
                return g
    raise Refuse(f"preset not in graphs.jsonl: {rel}")


def git_blob_sha1(path):
    data = open(path, "rb").read()
    hdr = b"blob %d\x00" % len(data)
    return hashlib.sha1(hdr + data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", required=True, choices=sorted(fc.CARRIERS))
    ap.add_argument("--out",
                    default=None,
                    help="output JSON (default model/oscillators/classic/"
                         "inputs/<carrier>.json)")
    args = ap.parse_args()

    preset_rel = "resources/data/" + fc.CARRIERS[args.carrier][0]
    slot = fc.CARRIERS[args.carrier][1]
    graphs_full = graphs_entry(preset_rel)
    if graphs_full["st"] != "normalized":
        raise Refuse("graphs entry not normalized")
    expected = census_blob(preset_rel)
    ge = graphs_full["g"]
    A = ge["sc"][0]
    osc_graph = A["osc"][slot]
    # cheap structural gates from the committed graphs (authoritative for
    # what the patch itself contains); the applicability boundary is
    # fail-closed: a preset whose Classic content sits outside the declared
    # single-scene mono voice slice is refused, never adapted
    if not any(o["t"] == 0 for o in A["osc"]):
        raise Refuse("no Classic oscillator in scene A: preset requires "
                     "scene-B or voice-graph integration (#48) - outside "
                     "the SXT-033 declared scope")
    if osc_graph["t"] != 0:
        raise Refuse(f"modeled slot osc{slot + 1} is not Classic in the "
                     "committed normalized graph")
    if A["pm"] != 0:
        raise Refuse("not poly playmode")
    # scene-A modulation routings must be provably inert under the declared
    # fixture overrides (filter units off, waveshaper off, FM switch off);
    # anything else (e.g. velocity -> AEG release, LFO chains, osc mod
    # amounts) is outside the declared model boundary - refuse, never ignore
    for r in g["md"]["s"][0].get("s", []):
        dest = r[4] if len(r) > 4 else ""
        if not any(k in dest for k in ("Filter", "Waveshaper")) and                 dest != "A FM Depth":
            raise Refuse("scene-A modulation routing %r is outside the "
                         "declared slice (destination not inert under the "
                         "fixture overrides)" % dest)
    # pan/width: width is dead code under the fc_serial1 override (the
    # voice-level width branch only runs for fc_stereo/fc_wide); scene pan
    # is modeled through the mono pan law (megapanL+R)/2 = 1-0.25*pan^2

    preset_abs = fc.preset_abs(oc, args.carrier)
    if not os.path.exists(preset_abs):
        raise Refuse(
            "pinned-engine preset not found at %s - set ORACLE_SURGE_DIR to "
            "the pinned engine tree (see oracle/manifest.json); this tool "
            "requires the external oracle" % preset_abs)
    actual = git_blob_sha1(preset_abs)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    s = fc.build_instance(surgepy, oc, args.carrier)
    d = fc.read_params(s, slot)

    # fail-closed gates on the post-override state
    if d["osc_type"] != 0:
        raise Refuse(f"modeled slot is not Classic: {d['osc_type']}")
    if abs(d["drift"]) > 0:
        raise Refuse(f"scene drift is {d['drift']}, expected 0 "
                     "(determinism gate)")
    if not d["retrigger"]:
        raise Refuse("retrigger did not read back on")
    if d["absolute_detune"]:
        raise Refuse("absolute detune mode not in SXT-033 slice")
    if d["character"] not in (0, 1):
        raise Refuse(f"character {d['character']} not in slice (Warm/Neutral)")
    if d["filter_config"] != 0 or d["fm_switch"] != 0 or d["ws_type"] != 0:
        raise Refuse("isolation overrides did not hold (fbc/fm/ws)")
    if d["scenemode"] != 0:
        raise Refuse("scene mode did not read back Single")
    if any(t != 0 for t in d["fx_types"]):
        raise Refuse("FX slots did not read back Off")
    if d["fu0_type"] != 0 or d["fu1_type"] != 0:
        raise Refuse("filter units did not read back Off")
    if abs(d["lowcut"] + 72.0) > 1e-6:
        raise Refuse("lowcut did not read back off")
    if abs(d["pan"]) > 1.0:
        raise Refuse("pan outside [-1, 1]: outside the declared mono law")
    if int(d["adsr"]["mode"]) != 0:
        raise Refuse("amp env not in digital mode")
    if int(d["adsr"]["d_s"]) not in (0, 1):
        raise Refuse(f"amp env decay shape {d['adsr']['d_s']} not in slice")
    if not (1 <= d["unison"] <= 16):
        raise Refuse(f"unison {d['unison']} outside 1..16")
    if abs(d["scene_volume"]) == 0:
        raise Refuse("scene volume reads 0")
    if d["polymode"] != 0:
        raise Refuse("not poly playmode (live read)")
    active = [k for k in ("o1", "o2", "o3") if d["mutes"][k] == 0]
    # modeled slot must be the only active oscillator path
    want = "o%d" % (slot + 1)
    if active != [want]:
        raise Refuse(f"active mixer paths {active} != [{want}]")

    out = {
        "schema_version": 1,
        "issue": "SXT-033",
        "carrier": args.carrier,
        "slot": slot,
        "preset_path": preset_rel,
        "preset_census_blob_sha1": expected,
        "graphs_sha256_of_line_source": "corpus/normalized/graphs.jsonl",
        "engine": {
            "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
            "version_string": surgepy.getVersion(),
            "sample_rate": int(s.getSampleRate()),
            "block_size": int(s.getBlockSize()),
        },
        "declared_overrides": fc.carrier_overrides(slot),
        "octave": d["octave"],
        "scene_octave": d["scene_octave"],
        "keytrack": d["keytrack"],
        "pitch_param": d["pitch_param"],
        "retrigger": d["retrigger"],
        "shape": d["shape"],
        "pw": d["pw"],
        "pw2": d["pw2"],
        "submix": d["submix"],
        "sync": d["sync"],
        "unison_detune": d["unison_detune"],
        "unison": d["unison"],
        "extend_detune": d["extend_detune"],
        "absolute_detune": d["absolute_detune"],
        "character": d["character"],
        "drift": d["drift"],
        "o_level": d["o_level"],
        "level_pfg": d["level_pfg"],
        "pan": d["pan"],
        "scene_volume": d["scene_volume"],
        "vca_db": d["vca_db"],
        "vca_velsense": d["vca_velsense"],
        "master_db": d["master_db"],
        "adsr": d["adsr"],
    }
    if args.out is None:
        args.out = os.path.join(REPO, "model", "oscillators", "classic",
                                "inputs", args.carrier + ".json")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Refuse, fc.Refuse) as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
