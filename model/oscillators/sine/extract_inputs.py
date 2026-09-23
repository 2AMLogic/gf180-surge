#!/usr/bin/env python3
"""SXT-040: extract the declared Sine-family fixture inputs for one carrier
from the pinned native engine.

graphs.jsonl (SXT-011) deliberately excludes envelope (ADSR) values, scene
volume/drift, mixer levels and the per-parameter extended-range/absolute
flags (schema rev 1.0.0 scope). The frozen fixed-point model needs them, so
this script reads them from the pinned engine via surgepy AFTER `loadPatch`
at 48 kHz - the same normalized state authority as the SXT-011 export - and
writes a versioned JSON sidecar consumed by `model/oscillators/sine/
sine_model.py`.

The script is fail-closed: it re-verifies the census blob SHA-1, checks the
normalized Sine shape against the committed graphs line (post-migration
authority: the raw .fxp value is pre-migration and is never used), applies
the declared isolation overrides (fixture_config.py) with readback
verification, verifies the declared fixture sequences carry no controller
events (the value-zero route premise), and refuses (exit 2) on any surprise
instead of guessing.

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
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "sine"))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
SEQ_DIR = os.path.join(REPO, "fixtures", "sequences")

DECLARED_SEQUENCES = ("seq-notes-coverage-v1", "seq-notes-repeated-v1",
                      "seq-notes-holds-v1")

# modsource ids whose value is identically 0 across the declared fixture
# sequences (no controller/aftertouch/bend events; the renderer resets CC1,
# CC11, CC64, aftertouch and pitchbend to 0). Free-running sources (keytrack,
# EGs, LFOs, scene LFOs, random, alternate, lowest/highest/latest key) are
# NOT in this set and may only target muted/off paths.
VALUE_ZERO_SOURCES = {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 29, 30, 35,
                      36, 37}


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


def scan_sequences():
    """The value-zero route premise: declared sequences carry note events
    only (no CC/aftertouch/pitchbend that could move a controller source)."""
    for sid in DECLARED_SEQUENCES:
        path = os.path.join(SEQ_DIR, sid + ".json")
        with open(path, encoding="utf-8") as f:
            seq = json.load(f)
        for e in seq["events"]:
            if e["type"] not in ("note_on", "note_off"):
                raise Refuse("declared sequence %s carries event type %r - "
                             "the value-zero route premise fails (refusing, "
                             "never ignoring)" % (sid, e["type"]))


def gate_routes(graphs_full, slot):
    """Fail-closed scene-A route gate (scene routes `s` AND voice routes
    `v`; both live in md.s[0]). Allowed iff the destination is provably
    inert under the declared fixture overrides (muted osc, off filter
    units / waveshaper / FM routing), is a landed modeled class with an
    identically-zero source value, or is carried by a value-zero source
    into machinery that stays at its unmodulated value (+0.0 exactly).

    Velocity (1) and keytrack (2) are NOT value-zero (notes sound at
    velocity 100; keytrack outputs (pitch-root)/12), so their destinations
    must be inert by override. LFO/scene-LFO sources are free-running and
    likewise may only target muted/off paths."""
    modeled = "A Osc %d " % (slot + 1)
    value_zero_only = (
        "Amp EG", "Pre-Filter Gain", "VCA Gain", "LFO",
        "Highpass", "Low Cut", "Pan", "Pitch", "Volume",
    )
    checked = []
    md0 = graphs_full["g"]["md"]["s"][0]
    rows = [(r, "scene") for r in md0.get("s", [])]
    rows += [(r, "voice") for r in md0.get("v", [])]
    for r, kind in rows:
        src = r[0]
        dest = r[4] if len(r) > 4 else ""
        if dest.startswith(("A Osc 1 ", "A Osc 2 ", "A Osc 3 ")):
            if dest.startswith(modeled):
                # destination on the MODELED slot: only value-zero sources
                if src not in VALUE_ZERO_SOURCES:
                    raise Refuse("scene-A routing %r into the modeled slot "
                                 "is carried by free-running source %d - "
                                 "outside the declared slice" % (dest, src))
                checked.append((src, dest, "modeled-slot/value-zero"))
            else:
                checked.append((src, dest, kind + "/muted-osc"))
            continue
        if any(k in dest for k in ("Filter 1", "Filter 2", "Filter EG",
                                   "Waveshaper", "Noise")):
            checked.append((src, dest, kind + "/off-path"))
            continue
        if "FM Depth" in dest:
            checked.append((src, dest, kind + "/fm-off"))
            continue
        if any(k in dest for k in value_zero_only):
            if src not in VALUE_ZERO_SOURCES:
                raise Refuse("scene-A routing %r (source %d) targets live "
                             "machinery and the source is free-running - "
                             "outside the declared slice" % (dest, src))
            checked.append((src, dest, kind + "/value-zero"))
            continue
        raise Refuse("scene-A modulation routing %r (source %d) is outside "
                     "the declared slice (destination not provably inert)"
                     % (dest, src))
    return checked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", required=True, choices=sorted(fc.CARRIERS))
    ap.add_argument("--out",
                    default=None,
                    help="output JSON (default model/oscillators/sine/"
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
    # fail-closed: a preset whose Sine content sits outside the declared
    # single-scene mono voice slice is refused, never adapted
    if not any(o["t"] == 1 for o in A["osc"]):
        raise Refuse("no Sine oscillator in scene A: preset requires "
                     "scene-B or voice-graph integration (#48) - outside "
                     "the SXT-040 declared scope")
    if osc_graph["t"] != 1:
        raise Refuse(f"modeled slot osc{slot + 1} is not Sine in the "
                     "committed normalized graph")
    if A["pm"] != 0:
        pmnames = {1: "mono", 2: "mono single trigger",
                   3: "mono single trigger + fingered portamento"}
        raise Refuse("scene-A playmode is %r - voice management outside the "
                     "declared poly slice (SXT-043 scope)"
                     % pmnames.get(A["pm"], A["pm"]))
    raw_shape = osc_graph["p"][0]
    if not isinstance(raw_shape, int) or not 0 <= raw_shape <= 31:
        raise Refuse("normalized sine shape %r outside [0, 31]" % (raw_shape,))
    routes = gate_scene_routes(graphs_full, slot)
    scan_sequences()

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
    if d["osc_type"] != 1:
        raise Refuse(f"modeled slot is not Sine: {d['osc_type']}")
    if int(d["shape"]) != int(raw_shape):
        raise Refuse("live sine shape %r != normalized graphs shape %r - the "
                     "normalized (post-migration) state must be authoritative"
                     % (d["shape"], raw_shape))
    if d["fmmode"] not in (0, 1):
        raise Refuse(f"sine behavior {d['fmmode']} outside declared {{0, 1}}")
    if abs(d["drift"]) > 0:
        raise Refuse(f"scene drift is {d['drift']}, expected 0 "
                     "(determinism gate)")
    if not d["retrigger"]:
        raise Refuse("retrigger did not read back on")
    if d["absolute_detune"]:
        raise Refuse("absolute detune mode not in SXT-040 slice")
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
    if abs(d["lowcut_scene"] + 72.0) > 1e-6:
        raise Refuse("scene lowcut did not read back off")
    if abs(d["pan"]) > 1.0:
        raise Refuse("pan outside [-1, 1]: outside the declared mono law")
    if int(d["adsr"]["mode"]) != 0:
        raise Refuse("amp env not in digital mode")
    if int(d["adsr"]["d_s"]) not in (0, 1, 2):
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
        "issue": "SXT-040",
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
        "pitch_extend": d["pitch_extend"],
        "retrigger": d["retrigger"],
        "shape": d["shape"],
        "fb": d["fb"],
        "fb_extend": d["fb_extend"],
        "fmmode": d["fmmode"],
        "lowcut": d["lowcut"],
        "highcut": d["highcut"],
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
        "scene_routes_checked": [[src, dest, how]
                                 for src, dest, how in routes],
    }
    if args.out is None:
        args.out = os.path.join(REPO, "model", "oscillators", "sine",
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
