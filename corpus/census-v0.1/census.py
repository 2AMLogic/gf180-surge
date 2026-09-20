#!/usr/bin/env python3
"""Reproduce a preliminary, static Surge XT preset census (Python stdlib only).

This is NOT a Surge patch loader or a supported-preset classifier. It reads raw
stored XML, verifies the pinned Git blob identities, and follows selected current
voice-processing conditions. Native migrations, modulation, filters, effects
routing, audio quality, and hardware feasibility remain to be qualified.
"""

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import struct
import tarfile
import xml.etree.ElementTree as ET

PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"
OSC = ["Classic", "Sine", "Wavetable", "S&H Noise", "Audio Input", "FM3",
       "FM2", "Window", "Modern", "String", "Twist", "Alias"]
FX = ["Off", "Delay", "Reverb1", "Phaser", "Rotary", "Distortion", "EQ",
      "FrequencyShifter", "Conditioner", "Chorus", "Vocoder", "Reverb2",
      "Flanger", "RingModulator", "Airwindows", "Neuron", "GraphicEQ",
      "Resonator", "CHOW", "Exciter", "Ensemble", "Combulator", "Nimbus",
      "Tape", "Treemonster", "Waveshaper", "MidSide", "SpringReverb",
      "Bonsai", "AudioInput", "FloatyDelay", "Convolution"]
MODES = ["Single", "Key Split", "Dual", "Channel Split"]
PROFILES = {
    "classic_sine": {0, 1},
    "classic_sine_wavetable": {0, 1, 2},
    "classic_sine_wavetable_sh_fm2_fm3": {0, 1, 2, 3, 5, 6},
}
PATHS = ["o1", "o2", "o3", "noise", "ring12", "ring23"]


def label(table, index):
    return table[index] if 0 <= index < len(table) else f"Unknown({index})"


def read_int(params, key):
    # Missing values must not silently become guessed current defaults.
    if key not in params or "value" not in params[key].attrib:
        raise ValueError(f"missing required parameter: {key}")
    return int(params[key].attrib["value"])


def inspect_patch(path, data):
    if len(data) < 92 or data[:4] != b"CcnK" or data[8:12] != b"FPCh":
        raise ValueError("unsupported outer FXP header")
    if data[60:64] != b"sub3":
        raise ValueError("unsupported inner Surge header")
    chunk_size = struct.unpack_from(">I", data, 56)[0]
    xml_size = struct.unpack_from("<I", data, 64)[0]
    wt_sizes = list(struct.unpack_from("<6I", data, 68))
    if chunk_size > len(data) - 60 or xml_size > len(data) - 92:
        raise ValueError("declared chunk/XML extends beyond file")
    patch = ET.fromstring(data[92:92 + xml_size].rstrip(b"\0"))
    if patch.tag != "patch" or patch.find("parameters") is None:
        raise ValueError("missing patch/parameters")
    params = {item.tag: item for item in patch.find("parameters")}
    mode = read_int(params, "scenemode")
    selected = read_int(params, "scene_active")
    if mode not in range(4) or selected not in range(2):
        raise ValueError("unknown scene mode or selection")
    scenes = ["ab"[selected]] if mode == 0 else ["a", "b"]
    osc_ids, needed_counts = set(), []
    conditional_paths = []
    for scene in scenes:
        def value(key):
            return read_int(params, scene + "_" + key)
        solos = [bool(value("solo_" + p)) for p in PATHS]
        mutes = [bool(value("mute_" + p)) for p in PATHS]
        fm = value("fm_switch")
        if fm not in range(4):
            raise ValueError("unknown FM routing")
        if any(solos):
            o1, o2, o3, noise, ring12, ring23 = solos
            # Matches FM && solo_o1 in the pinned SurgeVoice.cpp call.
            # Logical && produces a boolean, even when stored FM is 2 or 3.
            fm = int(bool(fm) and solos[0])
        else:
            o1, o2, o3, noise, ring12, ring23 = [not x for x in mutes]
        # Pinned SurgeVoice.cpp process_block conditions, not just direct mute.
        needed = [
            o1 or ring12,
            o2 or ring12 or ring23 or (bool(fm) and o1),
            o3 or ring23 or ((o1 or o2 or ring12) and fm == 2)
            or ((o1 or ring12) and fm == 3),
        ]
        needed_counts.append(sum(needed))
        used = []
        for i, need in enumerate(needed, 1):
            if need:
                osc_type = value(f"osc{i}_type")
                osc_ids.add(osc_type)
                used.append(f"{i}:{label(OSC, osc_type)}")
        conditional_paths.append(scene + "=" + ",".join(used))
    # Stored non-Off FX presence only: includes disabled/inactive scene slots.
    fx_ids, fx_slots = set(), 0
    for key, item in params.items():
        if key.startswith("fx") and key.endswith("_type"):
            index = int(item.attrib["value"])
            if index:
                fx_ids.add(index)
                fx_slots += 1
    result = {
        "status": "parsed_static_only",
        "stored_revision": int(patch.attrib["revision"]),
        "scene_mode": label(MODES, mode),
        "selected_scene": "ab"[selected],
        "required_scenes": ";".join(scenes),
        "conditional_oscillator_ids": ";".join(map(str, sorted(osc_ids))),
        "conditional_oscillator_families": ";".join(label(OSC, i) for i in sorted(osc_ids)),
        "conditional_oscillator_paths": ";".join(conditional_paths),
        "max_conditional_oscillators_per_scene": max(needed_counts),
        "stored_nonoff_fx_types": ";".join(label(FX, i) for i in sorted(fx_ids)),
        "stored_nonoff_fx_slot_count": fx_slots,
        "stored_fx_disable": read_int(params, "fx_disable"),
        "stored_fx_bypass": read_int(params, "fx_bypass"),
        "embedded_wavetable_bytes_all_scenes": sum(wt_sizes),
        "stored_modrouting_count_all_parameters": sum(len(x.findall("modrouting")) for x in params.values()),
    }
    for name, allowed in PROFILES.items():
        result[name + "_oscillator_screen"] = int(osc_ids <= allowed)
    return result


def summarize(rows):
    groups = {}
    for name in ["factory", "contributor", "combined"]:
        all_rows = [r for r in rows if name == "combined" or r["bank"] == name]
        ok = [r for r in all_rows if r["status"] == "parsed_static_only"]
        counts = collections.Counter(r["scene_mode"] for r in ok)
        osc_counts, fx_counts = collections.Counter(), collections.Counter()
        for row in ok:
            osc_counts.update(x for x in row["conditional_oscillator_families"].split(";") if x)
            fx_counts.update(x for x in row["stored_nonoff_fx_types"].split(";") if x)
        groups[name] = {
            "manifest_presets": len(all_rows), "parsed_presets": len(ok),
            "unresolved_presets": len(all_rows) - len(ok),
            "fxp_bytes": sum(r["size"] for r in all_rows),
            "stored_revision_counts": dict(sorted(collections.Counter(r["stored_revision"] for r in ok).items())),
            "scene_modes": dict(counts),
            "conditional_oscillator_family_patch_counts": dict(osc_counts.most_common()),
            "max_conditional_oscillators_per_scene_counts": dict(sorted(collections.Counter(r["max_conditional_oscillators_per_scene"] for r in ok).items())),
            "stored_nonoff_fx_patch_count": sum(bool(r["stored_nonoff_fx_types"]) for r in ok),
            "stored_nonoff_fx_slot_count_distribution": dict(sorted(collections.Counter(r["stored_nonoff_fx_slot_count"] for r in ok).items())),
            "stored_fx_type_patch_counts": dict(fx_counts.most_common()),
            "oscillator_family_screens": {
                profile: {
                    "any_scene_mode": sum(r[profile + "_oscillator_screen"] for r in ok),
                    "single_scene_only": sum(r[profile + "_oscillator_screen"] for r in ok if r["scene_mode"] == "Single"),
                } for profile in PROFILES
            },
        }
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Pinned GitHub source tar.gz")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("corpus-manifest.json"))
    parser.add_argument("--out", type=Path, default=Path("census-output"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest["commit"] != PIN or manifest["repository"] != "surge-synthesizer/surge":
        raise ValueError("manifest does not match the analyzed source pin")
    wanted = {entry["path"]: entry for entry in manifest["entries"]}
    if len(wanted) != len(manifest["entries"]):
        raise ValueError("duplicate manifest paths")
    rows, seen = [], set()
    with tarfile.open(args.archive, "r|gz") as archive:
        for member in archive:
            # Read members only. Never extract an archive path into the filesystem.
            _, separator, path = member.name.partition("/")
            if not separator or path not in wanted:
                continue
            if path in seen or not member.isfile():
                raise ValueError(f"duplicate or non-file preset: {path}")
            seen.add(path)
            data = archive.extractfile(member).read()
            entry = wanted[path]
            digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if len(data) != entry["size"] or digest != entry["git_blob_sha1"]:
                raise ValueError(f"manifest content mismatch: {path}")
            row = dict(entry)
            row["bank"] = "factory" if "/patches_factory/" in path else "contributor"
            row["content_verified"] = True
            try:
                row.update(inspect_patch(path, data))
            except (ET.ParseError, ValueError, KeyError, struct.error) as exc:
                row.update(status="unresolved_by_static_parser", error=f"{type(exc).__name__}: {exc}")
            rows.append(row)
    if seen != set(wanted):
        raise ValueError(f"missing {len(set(wanted) - seen)} manifest entries")
    rows.sort(key=lambda r: r["path"])
    summary = {
        "repository": manifest["repository"], "commit": PIN,
        "scope": "Bundled .fxp in patches_factory and patches_3rdparty; test-data excluded",
        "content_verified_against_git_blob_manifest": len(rows),
        "limitations": [
            "Static stored-XML analysis; native Surge loader and migrations not executed.",
            "Oscillator-family screens are necessary-feature screens, not working-preset coverage.",
            "Screens use pinned voice branch conditions for stored scene/mute/solo/FM/ring values.",
            "Inactive scenes are omitted in Single mode; both scenes included for Dual/Split.",
            "No level-based pruning, modulation reachability, filter/waveshaper/FX qualification, audio rendering, or cost measurement.",
            "FX counts are configured non-Off types, not audible or essential-effect counts.",
            "Unresolved XML is retained in total denominators; not silently repaired or labeled corrupt.",
        ],
        "groups": summarize(rows),
        "unresolved": [r for r in rows if r["status"] != "parsed_static_only"],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (args.out / "per-preset.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({name: {key: value for key, value in data.items() if key in [
        "manifest_presets", "parsed_presets", "unresolved_presets", "scene_modes",
        "stored_nonoff_fx_patch_count", "oscillator_family_screens"]}
        for name, data in summary["groups"].items()}, indent=2))


if __name__ == "__main__":
    main()
