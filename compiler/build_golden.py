#!/usr/bin/env python3
"""SXT-020 golden-suite generator (issue #13).

Compiles a fixed, curated case list against the selected DRAFT bundle
(B4-broad) and writes compiler/golden/: byte-pinned compiled images,
rejection records, the synthetic input lines, and manifest.json.

Case selection (documented in reports/sxt-020/EVIDENCE.md):
  compiled  simple single-scene Classic; the SXT-015 worked presets
            (96 Osc Supersaw compiled; July becomes a rejection record —
            it carries an MSEG LFO); wavetable-carrying; dual-scene;
            split-scene; 4-FX-instance; send-FX; all-FX-off baseline.
            An Airwindows-carrying COMPILED image is impossible under the
            DRAFT B4-broad spec (its fx_type_allowlist excludes the
            Airwindows class entirely; the class allowlist binds first,
            profile-v1-DRAFT section 4) — covered instead by the synthetic
            rejection case below and by July; recorded as a finding.
  rejected  real presets carrying bundle-unsupported features, including
            the two compiler-stricter deltas vs SXT-017 (asset_unresolved,
            send_levels_not_exported), plus one clearly-labeled synthetic
            Airwindows-carrying graph pinning both Airwindows-related codes.

Deterministic; re-running rewrites identical bytes.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from compiler import compile as C  # noqa: E402
from compiler.version import COMPILER_VERSION, IMAGE_FORMAT_VERSION  # noqa: E402
from tools.profile_predict import load_bundle_file, load_graphs, validate_spec  # noqa: E402

GOLDEN = REPO / "compiler" / "golden"
GRAPHS = "corpus/normalized/graphs.jsonl"
BUNDLE = "contracts/profile-v1-bundle-DRAFT.json"
BUNDLE_ID = "B4-broad"

COMPILED_CASES = [
    ("simple-classic", "resources/data/patches_factory/Basses/Attacky.fxp",
     "factory single scene, Classic oscillators, LP 12 dB, no FX (dry baseline)"),
    ("all-fx-off-baseline", "resources/data/patches_3rdparty/A.Liv/Basses/Amen Polska.fxp",
     "SXT-015 worked example (c): all-FX-off baseline, waveshaper + unison in the voice path"),
    ("wavetable-asset", "resources/data/patches_3rdparty/Argitoth/Drums/Kick.fxp",
     "wavetable-carrying (resolved asset, flash block)"),
    ("dual-scene", "resources/data/patches_3rdparty/Aleksey Zhehanov/Keys/Accordion Lead.fxp",
     "dual scene mode (two pool voices per note), FM2 oscillators, EQ"),
    ("four-fx-instance", "resources/data/patches_3rdparty/Argitoth/FX/Monster Feedback.fxp",
     "four enabled FX instances (EQ/Distortion/Delay/Reverb 1), insert+send roles, external delay+reverb state"),
    ("split-scene", "resources/data/patches_3rdparty/Bluelight/Splits/Bilbo 110 BPM.fxp",
     "split scene mode, THREE enabled Delay slots (three delay histories), FX Comb filter"),
    ("send-fx", "resources/data/patches_3rdparty/A.Liv/Keys/Grant Me....fxp",
     "send-bus FX (Reverb 2 + Delay as sends with return levels), unison 3"),
    ("supersaw-96osc", "resources/data/patches_3rdparty/Luna/Leads/96 Osc Supersaw.fxp",
     "SXT-015 worked example (b): dual scene, unison 16 on all six slots, Chorus + Reverb 2"),
]

REJECTED_CASES = [
    ("reject-osc-family", "resources/data/patches_3rdparty/A.Liv/Basses/Sqweird.fxp",
     ["oscillator_family_not_in_bundle"], "Window oscillator outside the B4 allowlist"),
    ("reject-fx-class", "resources/data/patches_3rdparty/A.Liv/Basses/Seek And Ye Shall Find.fxp",
     ["effect_class_not_in_bundle"], "FX class outside the B4 tier set"),
    ("reject-adapted-poly", "resources/data/patches_3rdparty/Dan Maurer/Basses/Lucy Louise.fxp",
     ["polylimit_reduction_required"], "adapted-class: stored polylimit exceeds the pool; the compiler rejects original graphs"),
    ("reject-audio-input", "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Further 2.fxp",
     ["audio_input_dependency"], "depends on the external audio input path"),
    ("reject-mseg-gap", "resources/data/patches_3rdparty/A.Liv/Basses/Move Like A Bucket Truck.fxp",
     ["mseg_or_formula_contents_not_exported"], "unresolved: MSEG/Formula LFO contents not exported (SXT-011 gap)"),
    ("reject-july", "resources/data/patches_3rdparty/A.Liv/Keys/July.fxp",
     ["mseg_or_formula_contents_not_exported", "airwindows_algorithm_not_selected",
      "effect_class_not_in_bundle"],
     "SXT-015 worked example (a): multi-code unresolved (MSEG gap takes precedence over the feature codes)"),
    ("reject-instance-overflow", "resources/data/patches_3rdparty/Jacky Ligon/Soundscapes/XTease.fxp",
     ["mseg_or_formula_contents_not_exported", "oscillator_family_not_in_bundle",
      "effect_class_not_in_bundle", "fx_instance_overflow", "send_levels_not_exported"],
     "12 enabled FX instances (corpus max); codes carry every failing gate incl. an enabled send3/4 slot"),
    ("reject-asset-unresolved", "resources/data/patches_factory/FX/Aggero.fxp",
     ["asset_unresolved"],
     "compiler-stricter delta vs SXT-017: wavetable record with neither embedded bytes nor resolved file"),
    ("reject-send-levels", "resources/data/patches_3rdparty/Exquis MPE/Strings/Rock.fxp",
     ["send_levels_not_exported"],
     "compiler-stricter delta vs SXT-017: enabled FX in send slot 3 (send levels for buses 3/4 not exported)"),
]


def build():
    lines, observed, graphs_sha = load_graphs(REPO / GRAPHS)
    by_path = {d["p"]: d for d in lines}
    raw, bundles = load_bundle_file(REPO / BUNDLE)
    spec = validate_spec(bundles[BUNDLE_ID], observed)
    bundle_sha = hashlib.sha256((REPO / BUNDLE).read_bytes()).hexdigest()
    status = next(b["status"] for b in raw["bundles"] if b["bundle_id"] == BUNDLE_ID)

    (GOLDEN / "compiled").mkdir(parents=True, exist_ok=True)
    (GOLDEN / "rejected").mkdir(parents=True, exist_ok=True)
    (GOLDEN / "inputs").mkdir(parents=True, exist_ok=True)

    cases = []

    def emit(case, line, expect_outcome, expect_codes, note, synthetic=False):
        outcome, obj, container = C.compile_line(
            line, spec, BUNDLE_ID, status, bundle_sha)
        assert outcome == expect_outcome, \
            "%s: outcome %s != expected %s" % (case, outcome, expect_outcome)
        entry = {"case": case,
                 "source": {"path": line["p"],
                            "census_blob_sha1": line["sha"]},
                 "expected": {"outcome": outcome},
                 "note": note}
        if synthetic:
            entry["source"]["synthetic"] = True
            (GOLDEN / "inputs" / (case + ".line.json")).write_text(
                json.dumps(line, sort_keys=True, indent=1) + "\n",
                encoding="utf-8")
        if outcome == C.OUTCOME_COMPILED:
            assert container is not None
            (GOLDEN / "compiled" / (case + ".image.bin")).write_bytes(container)
            (GOLDEN / "compiled" / (case + ".image.json")).write_text(
                json.dumps(obj, sort_keys=True, indent=1,
                           ensure_ascii=True, allow_nan=False) + "\n",
                encoding="utf-8")
            entry["expected"]["image_sha256"] = hashlib.sha256(
                container).hexdigest()
        else:
            codes = sorted({r["code"] for r in obj["codes"]})
            assert codes == sorted(expect_codes), \
                "%s: codes %s != expected %s" % (case, codes, expect_codes)
            entry["expected"]["codes"] = codes
            (GOLDEN / "rejected" / (case + ".rejection.json")).write_text(
                json.dumps(obj, sort_keys=True, indent=1,
                           ensure_ascii=True, allow_nan=False) + "\n",
                encoding="utf-8")
        cases.append(entry)
        print("%-26s %s %s" % (case, outcome,
                               entry["expected"].get("codes", "")))

    for case, path, note in COMPILED_CASES:
        emit(case, by_path[path], C.OUTCOME_COMPILED, [], note)

    # synthetic: Airwindows-carrying graph (SYNTHETIC input, committed under
    # inputs/). Pins BOTH Airwindows-related codes: algorithm 7 ('Point') is
    # outside B4's top-12 selection AND the Airwindows class itself is
    # outside B4's fx tier — the class allowlist binds first
    # (profile-v1-DRAFT section 4), so no Airwindows-carrying preset can
    # compile under the DRAFT B4-broad spec.
    base = by_path["resources/data/patches_factory/Basses/Attacky.fxp"]
    import copy
    line = copy.deepcopy(base)
    line["g"]["fx"][6].update({
        "on": 1, "t": 14, "tn": "Airwindows", "aw": 7, "awn": "Point",
        "p": [7, 0.5, 0.5, 0.044824, 1.0, 1.0, 0, 0, 0, 0, 0, 0], "rl": 1.0,
    })
    line["g"]["fxd"] = 0
    line["p"] = "synthetic/airwindows-point.fxp"
    line["sha"] = "synthetic-" + hashlib.sha256(
        C.canonical_json(line["g"])).hexdigest()[:16]
    emit("synthetic-airwindows-point", line, C.OUTCOME_REJECTED,
         ["airwindows_algorithm_not_selected", "effect_class_not_in_bundle"],
         "SYNTHETIC Airwindows-carrying graph ('Point', id 7): pins "
         "airwindows_algorithm_not_selected + effect_class_not_in_bundle "
         "(class binds first under B4); inputs/ line is committed",
         synthetic=True)

    for case, path, codes, note in REJECTED_CASES:
        emit(case, by_path[path],
             C.OUTCOME_UNRESOLVED if codes[0].startswith("mseg_")
             else C.OUTCOME_REJECTED, codes, note)

    manifest = {
        "schema_version": "sxt-020-golden-manifest/1.0.0",
        "artifact": "sxt-020-golden",
        "compiler_version": COMPILER_VERSION,
        "image_format": IMAGE_FORMAT_VERSION,
        "graphs": GRAPHS, "graphs_sha256": graphs_sha,
        "bundle_file": BUNDLE, "bundle_file_sha256": bundle_sha,
        "bundle_id": BUNDLE_ID, "bundle_status": status,
        "claim_scope": "golden images pin compiler behavior (determinism, "
                       "losslessness, rejection codes) against the DRAFT "
                       "bundle; they are NOT support, fidelity, or quality "
                       "evidence",
        "cases": cases,
    }
    (GOLDEN / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=1) + "\n",
        encoding="utf-8")
    print("manifest: %d cases (%d compiled, %d rejected)"
          % (len(cases),
             sum(1 for c in cases if c["expected"]["outcome"] == "compiled"),
             sum(1 for c in cases if c["expected"]["outcome"] != "compiled")))


if __name__ == "__main__":
    sys.exit(build())
