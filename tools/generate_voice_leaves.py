#!/usr/bin/env python3
"""SXT-027 voice-feature leaf generator (issue #20).

Deterministically derives a prioritized, recovery-ordered plan of voice
feature leaf issues from committed data only:

  corpus/normalized/graphs.jsonl            (SXT-011 normalized graphs)
  reports/sxt-017/predictions/B4-broad.json (SXT-017 DRAFT bundle predictions)
  reports/sxt-020/compile-corpus-scan.json  (SXT-020 compile-stage rejections)
  reports/sxt-013/candidates/slate-256-*.json (SXT-013 proposal slates)
  model/integration/selection-scan.json     (SXT-025 F-1 voice-slice finding)

One leaf per algorithm/submode/topology in the B4-broad voice scope
(oscillator families, filter types, waveshaper types, scene modes, FM
routing forms, playmodes, unison stack, modulation source behaviors).
Ordered by whole-preset recovery over the committed recovery basis: the
union of the three SXT-013 proposal slates' B4-predicted-supported paths.
Leaves are attributed by feature requirement: a B4-supported preset counts
for a leaf when its ORIGINAL graph requires the leaf's feature on an
active slot/route (SXT-015 accounting active-slot rules, the same rules
the SXT-017 predictor gated on). Shared presets legitimately attribute to
multiple leaves; this is requirement attribution, not marginal-gain
accounting (recorded as a bounded finding in every run's output).

Fail-closed discipline (mirrors tools/profile_predict.py):
  - unknown feature keys (osc family / filter type / waveshaper type /
    playmode name / scene mode / modsource id / fm id) REFUSE the run;
  - integrity mismatches between graphs, predictions, slates and the
    compile scan REFUSE the run;
  - a leaf whose newly-enabled preset set is empty (recovery basis AND
    corpus both zero) is never emitted: the run REFUSES instead;
  - adapted presets (polylimit/unison reduction classes) are excluded
    from every recovery set by construction: only B4-predicted-supported
    presets are attributed.

Claim discipline: every recovery number is a STRUCTURAL prediction over
DRAFT bundle data. Essentiality of the slate basis is UNVERIFIED (SXT-013
listening is BLOCKED; the slates are deterministic diversity-maximized
proposals, not listening-ranked favorites). Nothing here is a fidelity,
preset-quality, fit-on-cycles, or hardware claim, and filing or running
this generator establishes none.

Determinism: same input bytes => byte-identical outputs (sorted keys,
fixed separators, floats rounded to 6 decimals, no timestamps).

Provenance/licensing: original to this repository (Apache-2.0 per
LICENSE); Python stdlib only. Imports this repository's own SXT-015
accounting model. Engine facts cited below (file/function paths, enum
values, orderings) were read from the pinned GPL-3.0-or-later tree at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 and are
cited, never copied: src/common/SurgeStorage.h (play_mode, fm_routing,
scene_mode enums), src/common/ModulationSource.h (modsources enum),
src/common/dsp/oscillators/*, src/common/FilterConfiguration.h,
libs/sst/sst-filters, libs/sst/sst-waveshapers.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from model.resources.accounting import MODEL_VERSION, account_graph  # noqa: E402

TOOL_VERSION = "sxt-027-leaf-gen/1.0.0"
PLAN_SCHEMA = "sxt-027-leaf-plan/1.0.0"

ENGINE_PIN = "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71"
BUNDLE_ID = "B4-broad"
GRAPHS_SHA = "c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715"

ESSENTIALITY_CAVEAT = (
    "essentiality UNVERIFIED: the recovery basis is the union of the three "
    "SXT-013 proposal slates' B4-predicted-supported paths (deterministic "
    "diversity-maximized proposals; SXT-013 human listening is BLOCKED and "
    "no listening-ranked favorites set exists). Recovery counts are "
    "structural requirement attribution over DRAFT bundle predictions, not "
    "musical value, not marginal gains, and not a fidelity or quality claim."
)

F1_NOTE = (
    "F-1 (SXT-025, model/integration/selection-scan.json): the landed SXT-022 "
    "voice leaf implements exactly one voice graph (Attacky: Classic osc, "
    "LP 12 dB/Driven, mono bus, modwheel-only mod). Its census scan found "
    "exactly two corpus presets inside that arithmetic (Attacky, Quickspit), "
    "neither carrying FX. Voice-slice generalization beyond Attacky is the "
    "first-class leaf (SXT-026a, issue #48); every per-feature leaf below is "
    "gated on it and its recovery counts are B4-model attributions, not "
    "incremental gains over the landed slice."
)

LEDGER = [
    {
        "leaf_key": "voice_slice_generalization",
        "status": "filed",
        "issue": 48,
        "sxt": "SXT-026a",
        "title": "SXT-026a: voice-leaf scope extension — second voice slice "
                 "(blocks #18's supported-status row)",
        "note": "First-class F-1 leaf (voice-slice generalization beyond "
                "Attacky). Already filed; the generator neither re-files it "
                "nor allocates an SXT number for it.",
    },
    {
        "leaf_key": "osc_family:Wavetable",
        "status": "landed",
        "issue": 19,
        "sxt": "SXT-026",
        "title": "SXT-026: Add Wavetable asset and playback support",
        "note": "Landed and closed (reports/sxt-026/EVIDENCE.md). Listed "
                "for attribution only; never a filing candidate.",
    },
]

OSC_SOURCES = "src/common/dsp/oscillators/{name}Oscillator.cpp/.h"
FILTER_SOURCES = [
    "src/common/FilterConfiguration.h (fut_ registry + subtype model)",
    "src/common/dsp/filters/BiquadFilter.h",
    "src/common/dsp/filters/VectorizedSVFilter.cpp/.h",
    "src/common/dsp/QuadFilterChain.cpp",
    "libs/sst/sst-filters (pinned submodule; per-type kernel)",
]

OSC_META = {
    "Classic": {
        "sources": [OSC_SOURCES.format(name="Classic")],
        "cost": "SXT-016 probe_osc__classic_blit__ph24__a24__m32__onchip: "
                "8,438,400 cyc/frame (naive+lp variant 1,525,440) at the "
                "probe's declared A-DSP-1c assumptions; landed-slice "
                "integrated measurement 37.7-39.8 MAC/sample "
                "(reports/sxt-022). Planning numbers, not technology "
                "claims.",
        "overlap": "Partially landed: SXT-022 (#15) implements the exact "
                   "Attacky configuration only (shape 0.0, sub mix 1.0, "
                   "sync 0, unison 1). This leaf covers the remainder of "
                   "the family (shape range, sub-oscillator mix, sync, "
                   "unison stacking). Related: #15, #48.",
    },
    "Sine": {
        "sources": [OSC_SOURCES.format(name="Sine")],
        "cost": "SXT-016 probe_osc__sine_table__ph24__a24__m32__onchip: "
                "1,118,400 cyc/frame; probe_osc__sine_poly_fastmath__ph24: "
                "1,598,400. Planning numbers, not technology claims.",
        "overlap": "#48 (SXT-026a) covers a Sine slice (IIR24 LP 24 "
                   "dB/Driven carrier Hell's Bells) as the F-1 second "
                   "slice; this leaf tracks full-family coverage including "
                   "the engine's streaming-mismatch shape remaps. "
                   "Related: #48.",
    },
    "Wavetable": {
        "sources": [OSC_SOURCES.format(name="Wavetable")],
        "cost": "SXT-016 probe_osc__wavetable_blit__ph24__a24__m32__onchip "
                "/ probe_osc__wavetable_direct_interp__ph24. Landed: "
                "reports/sxt-026/EVIDENCE.md.",
        "overlap": "Landed by SXT-026 (#19, closed). Never a filing "
                   "candidate; listed for attribution only.",
    },
    "FM2": {
        "sources": [OSC_SOURCES.format(name="FM2")],
        "cost": "[ESTIMATE] no SXT-016 probe for the FM2 kernel; SXT-015 "
                "placeholder-v0 accounting only. An SXT-016-class probe is "
                "required before profile freeze.",
        "overlap": "",
    },
    "FM3": {
        "sources": [OSC_SOURCES.format(name="FM3")],
        "cost": "[ESTIMATE] no SXT-016 probe for the FM3 kernel; SXT-015 "
                "placeholder-v0 accounting only. An SXT-016-class probe is "
                "required before profile freeze.",
        "overlap": "",
    },
    "S&H Noise": {
        "sources": [OSC_SOURCES.format(name="SampleAndHold")],
        "cost": "[ESTIMATE] no SXT-016 probe for the S&H/Noise kernel; "
                "SXT-015 placeholder-v0 accounting only. An SXT-016-class "
                "probe is required before profile freeze.",
        "overlap": "",
    },
}

FILTER_META = {
    "LP 12 dB": ("svf", "Related: #15 (Attacky slice lands LP 12 dB/Driven "
                        "only), #48."),
    "LP 24 dB": ("svf", "Related: #48 (IIR24 coupled-form slice)."),
    "HP 12 dB": ("svf", ""),
    "HP 24 dB": ("svf", ""),
    "BP 12 dB": ("svf", ""),
    "BP 24 dB": ("svf", ""),
    "N 12 dB": ("svf", ""),
    "N 24 dB": ("svf", ""),
    "LP K35": ("k35", ""),
    "HP K35": ("k35", ""),
    "LP Legacy Ladder": ("estimate", ""),
    "LP Vintage Ladder": ("estimate", ""),
    "LP Diode Ladder": ("estimate", ""),
    "LP Cutoff Warp": ("estimate", ""),
    "N Cutoff Warp": ("estimate", ""),
    "LP Res Warp": ("estimate", ""),
    "BP Res Warp": ("estimate", ""),
    "HP Res Warp": ("estimate", ""),
    "LP OB-Xd 12 dB": ("estimate", ""),
    "LP OB-Xd 24 dB": ("estimate", ""),
    "BP OB-Xd 12 dB": ("estimate", ""),
    "HP OB-Xd 12 dB": ("estimate", ""),
    "N OB-Xd 12 dB": ("estimate", ""),
    "MULTI Tri-pole": ("estimate", ""),
    "FX Comb +": ("estimate", ""),
    "FX Comb -": ("estimate", ""),
    "FX Allpass": ("estimate", ""),
    "FX Cutoff Warp AP": ("estimate", ""),
    "FX Sample & Hold": ("estimate", ""),
}
FILTER_COST = {
    "svf": "SXT-016 SVF/TDF2 kernel-class probe exists "
           "(probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip: "
           "1,536,000 cyc/frame); per-type kernel mapping and corner costs "
           "confirmed at implementation.",
    "k35": "SXT-016 K35 ladder kernel-class probe exists "
           "(probe_filter__k35_ladder_tanh_lut__a24__m32__onchip: "
           "3,456,000 cyc/frame); per-subtype saturation mapping confirmed "
           "at implementation.",
    "estimate": "[ESTIMATE] no SXT-016 probe for this filter type; SXT-015 "
                "placeholder-v0 accounting only. An SXT-016-class probe is "
                "required before profile freeze.",
}

WS_SOURCES = [
    "libs/sst/sst-waveshapers (pinned submodule; wst_ shaper kernels)",
    "src/common/dsp/SurgeVoice.cpp (waveshaper unit application)",
]
WS_COST = ("[ESTIMATE] no SXT-016 probe for the waveshaper unit; SXT-015 "
           "placeholder-v0 accounting only. Per-voice shaper cost belongs "
           "in the SXT-016 refinement wave.")

SCENE_MODE_SOURCES = [
    "src/common/SurgeStorage.h (scene_mode enum sm_* / display names)",
    "src/common/SurgeSynthesizer.cpp (scene routing, per-scene state)",
    "src/common/dsp/SurgeVoice.cpp (per-scene voice instantiation)",
]
PLAYMODE_SOURCES = [
    "src/common/SurgeStorage.h (play_mode enum pm_poly..pm_latch)",
    "src/common/SurgeSynthesizer.cpp (voice allocation/stealing per mode)",
    "src/common/dsp/SurgeVoice.cpp (per-mode articulation: legato, "
    "retrigger, portamento)",
]
FM_SOURCES = [
    "src/common/SurgeStorage.h (fm_routing enum fm_2to1/fm_3to2to1/"
    "fm_2and3to1)",
    "src/common/dsp/SurgeVoice.cpp (FM routing setup per voice)",
    "oscillator process_block FM input mixing (per-family)",
]
UNISON_SOURCES = [
    "src/common/dsp/SurgeVoice.cpp (unison voice stack setup)",
    "src/common/dsp/oscillators/*.cpp (per-family unison handling)",
]
MOD_SOURCES_BASE = [
    "src/common/ModulationSource.h (modsources enum, pinned ids)",
    "src/common/ModulationSource.cpp",
    "src/common/dsp/modulators/LFOModulationSource.cpp/.h",
    "src/common/dsp/modulators/ADSRModulationSource.h",
    "src/common/dsp/SurgeVoice.cpp (processControl mod routing "
    "application)",
]

MOD_BEHAVIOR_META = {
    "velocity": {
        "ids": [1, 30],
        "names": {"1": "ms_velocity", "30": "ms_releasevelocity"},
        "extra_sources": [],
        "note": "Velocity (and release velocity) modulation routes. "
                "Per-instance state rule: routes are per-scene and "
                "per-destination; state is never shared across scenes.",
    },
    "keytrack": {
        "ids": [2],
        "names": {"2": "ms_keytrack"},
        "extra_sources": [],
        "note": "Keytrack modulation routes.",
    },
    "aftertouch": {
        "ids": [3, 4],
        "names": {"3": "ms_polyaftertouch", "4": "ms_aftertouch"},
        "extra_sources": [],
        "note": "Channel/poly aftertouch routes; the per-voice vs "
                "per-scene application distinction is part of the leaf.",
    },
    "pitchbend": {
        "ids": [5],
        "names": {"5": "ms_pitchbend"},
        "extra_sources": ["fixtures/sequences/seq-pitchbend-v1.json"],
        "note": "Pitchbend modulation routes (distinct from scene "
                "pitch-bend-range handling).",
    },
    "modwheel": {
        "ids": [6],
        "names": {"6": "ms_modwheel"},
        "extra_sources": ["fixtures/sequences/seq-modwheel-v1.json"],
        "note": "Partially landed: the Attacky slice (SXT-022, #15) "
                "implements modwheel -> Filter 1 Cutoff/Resonance only. "
                "This leaf covers modwheel routes to arbitrary "
                "destinations (per the landed smoothing semantics). "
                "Related: #15.",
    },
    "macro-ctrl": {
        "ids": [7, 8, 9, 10, 11, 12, 13, 14],
        "names": {"7": "ms_ctrl1", "8": "ms_ctrl2", "9": "ms_ctrl3",
                  "10": "ms_ctrl4", "11": "ms_ctrl5", "12": "ms_ctrl6",
                  "13": "ms_ctrl7", "14": "ms_ctrl8"},
        "extra_sources": ["fixtures/sequences/seq-macro-sweep-v1.json"],
        "note": "Macro controllers ctrl1..ctrl8: one mechanism, eight "
                "instances. Per-instance state is preserved even when "
                "arithmetic is shared (AGENTS.md).",
    },
    "envelope-source": {
        "ids": [15, 16],
        "names": {"15": "ms_ampeg", "16": "ms_filtereg"},
        "extra_sources": [],
        "note": "Amp/filter envelope as modulation source "
                "(ADSRModulationSource routing).",
    },
    "lfo": {
        "ids": [17, 18, 19, 20, 21, 22],
        "names": {"17": "ms_lfo1", "18": "ms_lfo2", "19": "ms_lfo3",
                  "20": "ms_lfo4", "21": "ms_lfo5", "22": "ms_lfo6"},
        "extra_sources": [],
        "note": "Scene LFO instances 1..6: one modulator class, six "
                "per-instance state sets (never merged). Step-sequencer "
                "grids are outside normalized-schema rev 1.0.0; missing "
                "LFO definition state is read from the pinned engine "
                "post-loadPatch by a fail-closed extractor (SXT-022 "
                "extract_inputs.py pattern) and the gap is recorded, "
                "never guessed.",
    },
    "slfo": {
        "ids": [23, 24, 25, 26, 27, 28],
        "names": {"23": "ms_slfo1", "24": "ms_slfo2", "25": "ms_slfo3",
                  "26": "ms_slfo4", "27": "ms_slfo5", "28": "ms_slfo6"},
        "extra_sources": [],
        "note": "Scene-B/global LFO (SLFO) instances 1..6, same class as "
                "lfo at scene routing scope. Carries the SXT-017 "
                "slfo_definitions budget-risk caveat; the send-levels 3/4 "
                "exposure gap (schema README) applies to SLFO-routed "
                "presets.",
    },
    "timbre": {
        "ids": [29],
        "names": {"29": "ms_timbre"},
        "extra_sources": [],
        "note": "Timbre (MPE) modulation routes.",
    },
    "random": {
        "ids": [31, 32],
        "names": {"31": "ms_random_bipolar", "32": "ms_random_unipolar"},
        "extra_sources": [],
        "note": "Random per-voice sources: the determinism class must "
                "follow the SXT-012 reference-variation rules (per-voice "
                "RNG seeding is part of the frozen behavior).",
    },
    "alternate": {
        "ids": [33, 34],
        "names": {"33": "ms_alternate_bipolar",
                  "34": "ms_alternate_unipolar"},
        "extra_sources": [],
        "note": "Alternate (note-parity) sources.",
    },
    "breath": {
        "ids": [35],
        "names": {"35": "ms_breath"},
        "extra_sources": [],
        "note": "Breath CC routes.",
    },
    "expression": {
        "ids": [36],
        "names": {"36": "ms_expression"},
        "extra_sources": [],
        "note": "Expression CC routes.",
    },
    "sustain": {
        "ids": [37],
        "names": {"37": "ms_sustain"},
        "extra_sources": [],
        "note": "Sustain pedal as mod source.",
    },
    "key-position": {
        "ids": [38, 39, 40],
        "names": {"38": "ms_lowest_key", "39": "ms_highest_key",
                  "40": "ms_latest_key"},
        "extra_sources": [],
        "note": "Lowest/highest/latest key sources.",
    },
}

MODSOURCE_NAMES = {}
for _meta in MOD_BEHAVIOR_META.values():
    MODSOURCE_NAMES.update({int(k): v for k, v in _meta["names"].items()})

PLAYMODE_CATALOG = {
    "Mono": "pm_mono",
    "Mono (Single Trigger)": "pm_mono_st",
    "Mono (Fingered Portamento)": "pm_mono_fp",
    "Mono (Single Trigger & Fingered Portamento)": "pm_mono_st_fp",
    "Latch (Monophonic)": "pm_latch",
}
SCENE_MODE_CATALOG = {1: "Key Split", 2: "Dual", 3: "Channel Split"}
FM_CATALOG = {1: "2 > 1 (fm_2to1)", 2: "3 > 2 > 1 (fm_3to2to1)",
              3: "2 and 3 > 1 (fm_2and3to1)"}
WS_DRIVE_ONLY_KEY = "waveshaper_drive_only:modulated-off"

SEQ_DEFAULTS = [
    "fixtures/sequences/seq-notes-coverage-v1.json",
    "fixtures/sequences/seq-notes-repeated-v1.json",
    "fixtures/sequences/seq-notes-holds-v1.json",
]
NEG_CONTROL_PATTERN = (
    "reports/sxt-022/artifacts/negative-control.txt and "
    "tools/reverb_negative_controls.py"
)


class Refuse(Exception):
    """Fail-closed refusal: bad input, unknown feature, zero-recovery leaf."""


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _require(cond, msg):
    if not cond:
        raise Refuse(msg)


def load_inputs(args):
    graphs_path = Path(args.graphs)
    pred_path = Path(args.prediction)
    scan_path = Path(args.scan)
    f1_path = REPO / "model/integration/selection-scan.json"

    lines = []
    with open(graphs_path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                lines.append(json.loads(ln))
    by_path = {d["p"]: d for d in lines}
    _require(len(by_path) == len(lines),
             "REFUSING: duplicate census paths in graphs file")

    graphs_sha = _sha256_file(graphs_path)
    _require(graphs_sha == GRAPHS_SHA,
             "REFUSING: graphs sha256 %s != pinned %s (this generator is "
             "bound to the committed SXT-011 export; a new census requires "
             "a new pinned manifest)" % (graphs_sha, GRAPHS_SHA))

    pred = json.loads(pred_path.read_text())
    _require(pred.get("bundle_id") == BUNDLE_ID,
             "REFUSING: prediction bundle_id %r != %r"
             % (pred.get("bundle_id"), BUNDLE_ID))
    prov = pred.get("provenance", {})
    _require(prov.get("graphs_sha256") == graphs_sha,
             "REFUSING: prediction provenance graphs_sha256 mismatch")
    _require(pred.get("totals", {}).get("supported") ==
             sum(1 for e in pred["presets"] if e["status"] == "supported"),
             "REFUSING: prediction totals inconsistent with per-preset list")

    scan = json.loads(scan_path.read_text())
    _require(scan.get("totals", {}).get("total") == len(lines),
             "REFUSING: compile scan total %r != graphs line count %d"
             % (scan.get("totals", {}).get("total"), len(lines)))

    slates = {}
    for sp in args.slate:
        s = json.loads(Path(sp).read_text())
        label = s.get("artifact") or Path(sp).stem
        cands = s.get("candidates")
        _require(isinstance(cands, list) and cands,
                 "REFUSING slate %s: no candidates list" % sp)
        paths = set()
        for c in cands:
            cid, csha = c.get("id"), c.get("census_blob_sha1")
            _require(cid in by_path,
                     "REFUSING slate %s: candidate %r not in graphs"
                     % (sp, cid))
            _require(by_path[cid]["sha"] == csha,
                     "REFUSING slate %s: census blob SHA mismatch for %r"
                     % (sp, cid))
            paths.add(cid)
        slates[label] = paths

    f1 = json.loads(f1_path.read_text())
    _require(f1.get("finding", {}).get("id") == "F-1",
             "REFUSING: selection-scan.json does not carry finding F-1")
    tier4 = f1.get("tier4_survivors_any_fx", [])
    landed_paths = sorted(t["path"] for t in tier4)
    _require(len(landed_paths) == 2 and all(p in by_path
                                            for p in landed_paths),
             "REFUSING: unexpected landed-arithmetic survivor set %r"
             % (landed_paths,))

    status_by_path = {e["path"]: e["status"] for e in pred["presets"]}
    supported = sorted(p for p, s in status_by_path.items()
                       if s == "supported")
    basis = set()
    for lbl, paths in slates.items():
        basis |= {p for p in paths if status_by_path.get(p) == "supported"}

    return {
        "lines": lines, "by_path": by_path, "pred": pred, "scan": scan,
        "slates": slates, "f1": f1, "landed_paths": landed_paths,
        "supported": supported, "basis": sorted(basis),
        "status_by_path": status_by_path,
        "input_hashes": {
            "graphs": graphs_sha,
            "prediction": _sha256_file(pred_path),
            "compile_scan": _sha256_file(scan_path),
            "selection_scan": _sha256_file(f1_path),
            "slates": {Path(sp).name: _sha256_file(Path(sp))
                       for sp in args.slate},
        },
    }


def feature_keys(data):
    """Derive per-preset leaf keys for B4-supported presets.

    Active-slot rules follow the SXT-015 accounting (the same rules the
    SXT-017 predictor gated on). Unknown feature keys REFUSE."""
    keys_by_path = {}
    osc_seen, filt_seen, ws_seen = set(), set(), set()
    pm_seen, sm_seen, ms_seen = set(), set(), set()
    for p in data["supported"]:
        d = data["by_path"][p]
        g = d["g"]
        acc = account_graph(d)
        keys = set()
        sm = g.get("sm")
        _require(sm in (0, 1, 2, 3), "REFUSING: scene mode %r" % (sm,))
        if sm != 0:
            smn = g.get("smn")
            _require(smn in SCENE_MODE_CATALOG.values(),
                     "REFUSING: unknown scene mode name %r" % (smn,))
            sm_seen.add(sm)
            keys.add("scene_mode:%d" % sm)
        for scene in acc["voice"]["scenes"]:
            si = scene["scene"]
            for o in scene["osc_slots"]:
                if not o["active"]:
                    continue
                tn = o["type_name"]
                _require(tn in OSC_META,
                         "REFUSING: unknown oscillator family %r (preset %s)"
                         % (tn, p))
                osc_seen.add(tn)
                keys.add("osc_family:%s" % tn)
                if o["unison"] > 1:
                    keys.add("voice_topology:unison_stack")
            for fu in scene["filter_units"]:
                if not fu["active"]:
                    continue
                tn = fu["type_name"]
                _require(tn in FILTER_META,
                         "REFUSING: unknown filter type %r (preset %s)"
                         % (tn, p))
                filt_seen.add(tn)
                keys.add("filter_type:%s" % tn)
            if scene["waveshaper_active"]:
                tn = scene["waveshaper_type"]
                if tn == "Off":
                    keys.add(WS_DRIVE_ONLY_KEY)
                else:
                    _require(isinstance(tn, str) and tn,
                             "REFUSING: waveshaper type %r (preset %s)"
                             % (tn, p))
                    ws_seen.add(tn)
                    keys.add("waveshaper_type:%s" % tn)
            sc = g["sc"][si]
            fmsw = sc.get("fm", {}).get("sw", 0)
            _require(fmsw in (0, 1, 2, 3), "REFUSING: fm routing %r" % (fmsw,))
            if fmsw:
                keys.add("fm_routing:%d" % fmsw)
            pmn = sc.get("pmn")
            _require(pmn == "Poly" or pmn in PLAYMODE_CATALOG,
                     "REFUSING: unknown playmode name %r (preset %s)"
                     % (pmn, p))
            if pmn != "Poly":
                pm_seen.add(pmn)
                keys.add("playmode:%s" % pmn)
            md_scene = (g.get("md", {}).get("s", [{}])[si]
                        if si < len(g.get("md", {}).get("s", [])) else {})
            for bus in ("s", "v"):
                for row in md_scene.get(bus, []):
                    src = row[0]
                    _require(src in MODSOURCE_NAMES,
                             "REFUSING: modsource id %r outside the pinned "
                             "enum map (preset %s)" % (src, p))
                    ms_seen.add(src)
                    for behavior, meta in MOD_BEHAVIOR_META.items():
                        if src in meta["ids"]:
                            keys.add("mod_behavior:%s" % behavior)
        keys_by_path[p] = keys

    observed = {
        "osc_family": sorted(osc_seen),
        "filter_type": sorted(filt_seen),
        "waveshaper_type": sorted(ws_seen) + ["<modulated-Off drive path>"],
        "scene_mode_ids": sorted(sm_seen),
        "playmode": sorted(pm_seen),
        "modsource_ids": sorted(ms_seen),
    }
    return keys_by_path, observed


def build_candidates(data, keys_by_path):
    """One candidate per observed feature. Recovery is requirement
    attribution over (a) the slate-union basis and (b) all B4-supported
    presets. Compile-scan rejection codes are joined per preset as
    lineage context."""
    scan_codes = {o["path"]: o.get("codes", []) for o in
                  data["scan"].get("outcomes", [])}
    cands = {}
    for p in data["supported"]:
        for k in keys_by_path[p]:
            c = cands.setdefault(k, {"basis": [], "corpus": []})
            c["corpus"].append(p)
    for p in data["basis"]:
        for k in keys_by_path[p]:
            cands[k]["basis"].append(p)
    return cands, scan_codes


def emit_guard(key, cand):
    """A leaf with zero newly-enabled presets is never emitted (issue #20:
    'leaves enabling zero preferred presets are not filed')."""
    _require(cand["basis"] or cand["corpus"],
             "REFUSING: leaf %r enables zero presets (recovery basis and "
             "corpus B4-supported set both empty); per issue #20 such a "
             "leaf is not filed" % (key,))


def subtype_inventory(data):
    inv = {}
    for p in data["supported"]:
        d = data["by_path"][p]
        acc = account_graph(d)
        for scene in acc["voice"]["scenes"]:
            si = scene["scene"]
            for fu in scene["filter_units"]:
                if not fu["active"]:
                    continue
                k = "filter_type:%s" % fu["type_name"]
                stn = d["g"]["sc"][si]["fu"][fu["slot"]]["stn"]
                inv.setdefault(k, {})
                inv[k][stn] = inv[k].get(stn, 0) + 1
    return {k: dict(sorted(d.items())) for k, d in sorted(inv.items())}


def leaf_title(key):
    if key == WS_DRIVE_ONLY_KEY:
        return "waveshaper drive-only modulated path"
    if key == "voice_topology:unison_stack":
        return "unison stack topology (>1 voice)"
    dim, _, val = key.partition(":")
    if dim == "osc_family":
        return "oscillator family: %s" % val
    if dim == "filter_type":
        return "filter algorithm: %s" % val
    if dim == "waveshaper_type":
        return "waveshaper type: %s" % val
    if dim == "scene_mode":
        return "scene mode: %s" % SCENE_MODE_CATALOG[int(val)]
    if dim == "playmode":
        return "playmode submode: %s" % val
    if dim == "fm_routing":
        return "scene FM routing form: %s" % FM_CATALOG[int(val)]
    if dim == "mod_behavior":
        return "modulation behavior: %s" % val
    raise Refuse("REFUSING: unknown leaf key %r (not in the leaf catalog)"
                 % (key,))


def leaf_statics(key):
    """Pinned sources, cost note, scope text, negative control and fixture
    sequences for one leaf key (the plan's leaf-issue template pre-fill)."""
    dim, _, val = key.partition(":")
    common_src = [ENGINE_PIN]
    if dim == "osc_family":
        _require(val in OSC_META,
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        m = OSC_META[val]
        return {
            "sources": common_src + m["sources"],
            "cost": m["cost"],
            "overlap": m["overlap"],
            "scope": ("Oscillator family '%s': full arithmetic at the "
                      "pinned commit (all submodes of the family's submode "
                      "selector, per-instance state, unison handling). The "
                      "observed submode inventory comes from the committed "
                      "normalized graphs; the engine-declared param set is "
                      "read at the pin." % val),
            "neg_control": ("wrong-family control: render the fixture "
                            "preset with this family's slots driven by the "
                            "landed Classic arithmetic (substituted) - the "
                            "reference-budget check must FAIL; plus one "
                            "single-constant RTL mutant that fails the "
                            "model-equality check (SXT-022 pattern)."),
            "sequences": SEQ_DEFAULTS,
        }
    if dim == "filter_type":
        _require(val in FILTER_META,
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        kernel, rel = FILTER_META[val]
        return {
            "sources": common_src + FILTER_SOURCES,
            "cost": FILTER_COST[kernel],
            "overlap": rel,
            "scope": ("Filter algorithm '%s' (one fut_ type incl. its "
                      "engine-declared subtype set): coefficient "
                      "construction, per-unit register state, subtype "
                      "behaviors, keytrack/env-mod paths. The observed "
                      "subtype inventory is embedded from the committed "
                      "graphs; the full subtype set is read at the pin."
                      % val),
            "neg_control": ("wrong-algorithm control: substitute the "
                            "landed LP 12 dB/Driven biquad for this type - "
                            "the reference-budget check must FAIL; "
                            "wrong-subtype control: same type, wrong "
                            "subtype must also FAIL."),
            "sequences": SEQ_DEFAULTS,
        }
    if dim == "waveshaper_type":
        _require(bool(val),
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        return {
            "sources": common_src + WS_SOURCES,
            "cost": WS_COST,
            "overlap": "",
            "scope": ("Waveshaper type '%s' (one wst_ kernel): transfer "
                      "behavior, drive scaling, per-voice application "
                      "point and gain staging at the pinned commit." % val),
            "neg_control": ("bypass/drive-zeroed control and a "
                            "generic-tanh substitution control - both must "
                            "FAIL the reference-budget check."),
            "sequences": SEQ_DEFAULTS,
        }
    if key == WS_DRIVE_ONLY_KEY:
        return {
            "sources": common_src + WS_SOURCES,
            "cost": WS_COST,
            "overlap": "",
            "scope": ("Topology boundary: waveshaper slot at type Off "
                      "whose drive parameter is nonetheless modulated (the "
                      "SXT-015 accounting's waveshaper-active rule) - the "
                      "drive-only gain path must be reproduced exactly, "
                      "not dropped."),
            "neg_control": ("drive-modulation-dropped control - must FAIL "
                            "the reference-budget check."),
            "sequences": SEQ_DEFAULTS,
        }
    if dim == "scene_mode":
        _require(val in {str(k) for k in SCENE_MODE_CATALOG},
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        return {
            "sources": common_src + SCENE_MODE_SOURCES,
            "cost": ("SXT-016 probe_scheduler__event_queue_and_control: 72 "
                     "control cyc/frame + 990 contention at the probe's "
                     "assumptions; per-scene voice cost is the sum of the "
                     "scene's own voice leaves. [ESTIMATE] pending SXT-016 "
                     "refinement."),
            "overlap": "",
            "scope": ("Scene mode '%s' topology (sm=%s): per-scene state, "
                      "split/dual voice routing, shared scene-voice pool "
                      "semantics at the pinned commit."
                      % (SCENE_MODE_CATALOG[int(val)], val)),
            "neg_control": ("collapsed-scene control: render the fixture "
                            "preset as Single scene (scene A only) - the "
                            "reference-budget check must FAIL."),
            "sequences": SEQ_DEFAULTS + [
                "fixtures/sequences/seq-poly-8-v1.json"],
        }
    if dim == "playmode":
        _require(val in PLAYMODE_CATALOG,
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        return {
            "sources": common_src + PLAYMODE_SOURCES,
            "cost": ("SXT-016 probe_scheduler__event_queue_and_control "
                     "(control-path basis); articulation arithmetic is "
                     "per-voice [ESTIMATE] pending SXT-016 refinement."),
            "overlap": "",
            "scope": ("Playmode submode '%s' (%s): voice allocation, "
                      "legato/retrigger/portamento articulation semantics. "
                      "Portamento arithmetic may be shared across mono "
                      "submodes, but each submode's semantics are "
                      "separately frozen and controlled."
                      % (val, PLAYMODE_CATALOG[val])),
            "neg_control": ("forced-Poly control: render the mono fixture "
                            "as Poly - articulation differences must FAIL "
                            "the reference-budget check."),
            "sequences": SEQ_DEFAULTS,
        }
    if dim == "fm_routing":
        _require(val in {str(k) for k in FM_CATALOG},
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        return {
            "sources": common_src + FM_SOURCES,
            "cost": ("[ESTIMATE] FM routing adds per-voice FM input "
                     "mixing; no dedicated SXT-016 probe. Covered by the "
                     "carrier oscillator-family leaf's probe where one "
                     "exists."),
            "overlap": ("Related: #48 (scene FM with muted FM sources is "
                        "an explicit SXT-026a scope candidate)."),
            "scope": ("Scene FM routing form '%s' (fm sw=%s): which "
                      "source oscillators FM the target, depth scaling, "
                      "muted-source behavior."
                      % (FM_CATALOG[int(val)], val)),
            "neg_control": ("fm-off control (depth forced to 0): the "
                            "reference-budget check must FAIL on "
                            "FM-dependent fixtures."),
            "sequences": SEQ_DEFAULTS,
        }
    if dim == "mod_behavior":
        _require(val in MOD_BEHAVIOR_META,
                 "REFUSING: unknown leaf value %r for dimension %r"
                 % (val, dim))
        m = MOD_BEHAVIOR_META[val]
        ids = ", ".join("%s (%s)" % (i, MODSOURCE_NAMES[i])
                        for i in m["ids"])
        return {
            "sources": common_src + MOD_SOURCES_BASE + m["extra_sources"],
            "cost": ("SXT-016 probe_scheduler__event_queue_and_control "
                     "(control-path basis); per-source evaluation cost "
                     "[ESTIMATE] pending SXT-016 refinement."),
            "overlap": "",
            "scope": ("Modulation behavior '%s' - pinned modsource ids "
                      "%s. %s" % (val, ids, m["note"])),
            "neg_control": ("routing-zeroed control (depth forced to 0, "
                            "per destination class) and a source-swap "
                            "control (landed modwheel in place of this "
                            "source) - both must FAIL the reference-budget "
                            "check."),
            "sequences": m["extra_sources"] or SEQ_DEFAULTS,
        }
    if key == "voice_topology:unison_stack":
        return {
            "sources": common_src + UNISON_SOURCES,
            "cost": ("SXT-015 unison state/cost model (osc_state_bytes_per_"
                     "unison, unison voice instances at worst-case poly); "
                     "[ESTIMATE] pending SXT-016 refinement."),
            "overlap": ("Related: #15 (unison 1 in the landed slice), #48 "
                        "(scene-width inertness at unison 1 is an SXT-026a "
                        "scope candidate)."),
            "scope": ("Voice topology boundary: unison stacks > 1 voice "
                      "(up to MAX_UNISON 16) - per-voice detune/spread "
                      "arithmetic, per-instance unison state, voice-pool "
                      "interaction."),
            "neg_control": ("unison-collapsed control (stack forced to 1 "
                            "voice): the reference-budget check must FAIL "
                            "on unison fixtures."),
            "sequences": SEQ_DEFAULTS + [
                "fixtures/sequences/seq-poly-8-v1.json"],
        }
    raise Refuse("REFUSING: unknown leaf key %r (not in the leaf catalog)"
                 % (key,))


_SHA_BY_PATH = {}


def data_sha(p):
    return _SHA_BY_PATH.get(p, "")


def issue_body(key, sxt, st, basis, corpus, carriers, recj):
    lines = []
    ap = lines.append
    ap("**Epic:** #2 · **Plan:** "
       "docs/surge-xt-chip-plan-v0.1-2026-09-20.md §6 · planning ID: "
       "SXT-%s · Generated by SXT-027 (#20), tool %s." % (sxt, TOOL_VERSION))
    ap("")
    ap("## Behavior and scope")
    ap(st["scope"])
    if st["overlap"]:
        ap("")
        ap(st["overlap"])
    ap("")
    ap("Pinned source (read and cited, never copied): %s."
       % "; ".join(st["sources"]))
    ap("")
    ap("## Inputs / outputs / state")
    ap("- Model domain: 48 kHz engine pin, float32-model placeholder word "
       "policy [PENDING-SXT-016/023]; fixed-point model conventions follow "
       "`model/voice/README.md` (SXT-022).")
    ap("- Inputs: normalized graph state (`corpus/normalized/graphs.jsonl`, "
       "sha256 `%s`) for the fixture carriers; missing definition state "
       "(LFO grids, ADSR) is read from the pinned engine post-loadPatch by "
       "a fail-closed extractor (`model/voice/extract_inputs.py` pattern), "
       "never guessed." % GRAPHS_SHA)
    ap("- Outputs: dry bus for this voice leaf unless the fixture is a "
       "wet-path case (AGENTS.md comparison rule); stereo scope as "
       "declared in the leaf's freeze doc.")
    ap("- State: per-instance state is preserved even when arithmetic is "
       "shared (AGENTS.md); initialization, reset and event timing follow "
       "the SXT-021 control conventions.")
    ap("")
    ap("## Fixtures and oracle")
    ap("- Oracle: the pinned engine at %s, 48 kHz (SXT-010 manifest); "
       "renders via `tools/render_fixture.py`, comparisons via "
       "`tools/compare_audio_reference.py` and "
       "`tools/compare_rtl_model.py`." % ENGINE_PIN)
    ap("- Carrier presets (real normalized corpus entries): %s."
       % "; ".join("`%s` (blob %s)" % (c, data_sha(c)) for c in carriers))
    ap("- Sequences: %s." % ", ".join("`%s`" % s for s in st["sequences"]))
    ap("- Parameter corners: the leaf freezes the observed normalized "
       "parameter ranges of its carriers plus the engine-declared ranges "
       "at the pin.")
    ap("")
    ap("## Acceptance")
    ap("- [ ] Frozen fixed-point model with word lengths + op order "
       "documented (`model/voice/` conventions).")
    ap("- [ ] Model-vs-pinned-engine dry-render budgets reported on the "
       "carrier fixtures (PENDING-FREEZE; achieved numbers recorded, not "
       "tuned).")
    ap("- [ ] RTL-vs-model exact at declared checkpoints "
       "(`tools/compare_rtl_model.py`, integer equality).")
    ap("- [ ] Cycle/state costs recorded against SXT-016 probes and the "
       "SXT-015 accounting; divergences recorded, not reconciled away.")
    ap("- [ ] **Negative control (must demonstrably fail):** %s Committed "
       "control transcript required (pattern: %s)."
       % (st["neg_control"], NEG_CONTROL_PATTERN))
    ap("")
    ap("## Deliverables")
    ap("- `model/voice/` (model + freeze doc), `rtl/voice/` (schedule + "
       "harness), comparison runs under `reports/SXT-%s/artifacts/`, "
       "evidence record `reports/SXT-%s/EVIDENCE.md`." % (sxt, sxt))
    ap("")
    ap("## Dependencies and recovery")
    ap("- Depends on #15 (landed leaf + harness), #48 (F-1 voice-slice "
       "generalization - prerequisite for any non-Attacky voice graph), "
       "#13, #14 (images, scheduling). Wet carriers additionally integrate "
       "through #18's declared boundaries.")
    ap("- **Newly-enabled presets (recovery basis): %d** slate-basis "
       "presets (essentiality UNVERIFIED - see data lineage); **%d / "
       "1,685** corpus B4-predicted-supported presets. Requirement "
       "attribution, not marginal gains; adapted presets are never "
       "counted." % (len(basis), len(corpus)))
    if basis:
        ap("- Recovery basis presets (path, census blob):")
        for p in basis:
            ap("  - `%s` %s" % (p, data_sha(p)))
    ap("- Compile-stage rejection codes among the corpus set (SXT-020 "
       "scan lineage): %s."
       % (", ".join("%s ×%d" % (k, v) for k, v in sorted(recj.items()))
          or "none"))
    ap("")
    ap("## Cost note")
    ap(st["cost"])
    ap("")
    ap("## Non-goals")
    ap("Effects leaves (#21 / SXT-028); profile freezing (#12); fidelity "
       "or listening verdicts; monolithic family-wide ports (one "
       "algorithm/submode/topology per leaf).")
    ap("")
    ap("## Stop/escalate")
    ap("If the leaf cannot meet proposed budgets on its carriers, record "
       "the bounded finding and route to SXT-013/#12 - do not weaken the "
       "wet-preset gate or the acceptance rules to pass.")
    ap("")
    ap("### Licensing / data lineage")
    ap("- Original work Apache-2.0 (LICENSE); engine facts cited from the "
       "pinned GPL tree; no Surge source, tables, or payloads copied into "
       "this repository. Governed by #25 and `docs/REUSE-AUDIT.md`.")
    ap("- Data lineage: graphs.jsonl (sha256 `%s`) · B4-broad predictions "
       "(SXT-017) · slate-256 proposal slates (SXT-013, essentiality "
       "UNVERIFIED) · compile scan (SXT-020) · F-1 finding (SXT-025, "
       "model/integration/selection-scan.json). Filed under #20."
       % GRAPHS_SHA)
    ap("")
    ap("Depends on #15, #48.")
    return "\n".join(lines) + "\n"


def build_leaf(key, cand, scan_codes, sub_inv, alloc_sxt, file_now):
    st = leaf_statics(key)
    basis, corpus = cand["basis"], cand["corpus"]
    recj = {}
    for p in corpus:
        for code in scan_codes.get(p, []):
            recj[code] = recj.get(code, 0) + 1
    carriers = sorted(basis)[:3] or sorted(corpus)[:3]
    sxt_str = "%03d" % alloc_sxt
    return {
        "leaf_key": key,
        "sxt": sxt_str,
        "title": "SXT-%s: voice leaf — %s" % (sxt_str, leaf_title(key)),
        "filing": "file-now" if file_now else "backlog",
        "recovery": {
            "basis_presets": [{"path": p, "sha": data_sha(p)}
                              for p in basis],
            "basis_count": len(basis),
            "corpus_b4_supported_count": len(corpus),
            "essentiality": ESSENTIALITY_CAVEAT,
        },
        "compile_scan_rejections_among_corpus": dict(sorted(recj.items())),
        "statics": st,
        "subtype_inventory": sub_inv,
        "fixture_carriers": carriers,
        "issue_body": issue_body(key, sxt_str, st, basis, corpus,
                                 carriers, recj),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graphs", default="corpus/normalized/graphs.jsonl")
    ap.add_argument("--prediction",
                    default="reports/sxt-017/predictions/B4-broad.json")
    ap.add_argument("--scan",
                    default="reports/sxt-020/compile-corpus-scan.json")
    ap.add_argument("--slate", action="append", default=[])
    ap.add_argument("--out-plan", default="reports/sxt-027/leaf-plan.json")
    ap.add_argument("--out-backlog",
                    default="reports/sxt-027/leaf-backlog.json")
    ap.add_argument("--out-bodies", default=None,
                    help="optional directory for FILE-NOW issue bodies")
    ap.add_argument("--first-sxt", type=int, default=32)
    ap.add_argument("--file-now", type=int, default=12)
    args = ap.parse_args(argv)

    if not args.slate:
        args.slate = [
            "reports/sxt-013/candidates/slate-256-balanced.json",
            "reports/sxt-013/candidates/slate-256-factory-lean.json",
            "reports/sxt-013/candidates/slate-256-contributor-lean.json",
        ]

    data = load_inputs(args)
    global _SHA_BY_PATH
    _SHA_BY_PATH = {d["p"]: d["sha"] for d in data["lines"]}

    keys_by_path, observed = feature_keys(data)
    cands, scan_codes = build_candidates(data, keys_by_path)
    sub_invs = subtype_inventory(data)

    for key, cand in cands.items():
        emit_guard(key, cand)

    def order(k):
        c = cands[k]
        return (-len(c["basis"]), -len(c["corpus"]), k)

    ledger_keys = {e["leaf_key"] for e in LEDGER}
    candidates = sorted((k for k in cands if k not in ledger_keys),
                        key=order)
    ledgered = sorted(k for k in cands if k in ledger_keys)

    plan_entries = []
    backlog_entries = []
    for idx, k in enumerate(candidates):
        fn = idx < args.file_now and len(cands[k]["basis"]) > 0
        e = build_leaf(k, cands[k], scan_codes, sub_invs.get(k, {}),
                       args.first_sxt + idx, fn)
        plan_entries.append(e)
        if not fn:
            backlog_entries.append(e)

    ledger_entries = []
    for le in LEDGER:
        key = le["leaf_key"]
        entry = dict(le)
        if key == "voice_slice_generalization":
            cov = {
                "basis": [p for p in data["basis"]
                          if p not in data["landed_paths"]],
                "corpus": [p for p in data["supported"]
                           if p not in data["landed_paths"]],
            }
        else:
            cov = cands.get(key, {"basis": [], "corpus": []})
        entry["recovery_basis_count"] = len(cov["basis"])
        entry["recovery_corpus_count"] = len(cov["corpus"])
        entry["essentiality"] = ESSENTIALITY_CAVEAT
        ledger_entries.append(entry)

    zero_basis = [e["leaf_key"] for e in plan_entries
                  if e["recovery"]["basis_count"] == 0]

    plan = {
        "schema_version": PLAN_SCHEMA,
        "artifact": "sxt-027-voice-leaf-plan",
        "tool_version": TOOL_VERSION,
        "status": "PLAN-ONLY (issues are planning artifacts; filing a leaf "
                  "is not an implementation, support, fidelity, or quality "
                  "claim)",
        "issue": 20,
        "plan_row": "SXT-027",
        "method": {
            "leaf_granularity": "one algorithm/submode/topology per leaf "
                                "(osc family incl. its submode selector; "
                                "filter fut_ type incl. its engine-declared "
                                "subtype set; waveshaper wst_ type; scene "
                                "mode; FM routing form; playmode submode; "
                                "unison-stack boundary; modulator behavior "
                                "class with per-instance state)",
            "attribution": "feature-requirement attribution over active "
                           "slots/routes (SXT-015 accounting rules, the "
                           "same rules as the SXT-017 predictor); shared "
                           "presets attribute to multiple leaves; NOT "
                           "marginal-gain accounting (bounded finding)",
            "recovery_basis": "union of the three SXT-013 proposal slates' "
                              "B4-predicted-supported paths",
            "ordering": "basis recovery desc, then corpus recovery desc, "
                        "then leaf key asc; SXT allocation starts at "
                        "SXT-%03d and follows this order"
                        % args.first_sxt,
            "essentiality_caveat": ESSENTIALITY_CAVEAT,
            "f1_note": F1_NOTE,
            "file_now_rule": "top %d candidates in order with basis "
                             "recovery > 0" % args.file_now,
        },
        "provenance": {
            "engine_pin": ENGINE_PIN,
            "inputs": data["input_hashes"],
            "accounting_model_version": MODEL_VERSION,
            "prediction_bundle_id": BUNDLE_ID,
            "supported_count": len(data["supported"]),
            "basis_count": len(data["basis"]),
            "slates": sorted(data["slates"]),
            "compile_scan_rejection_code_counts":
                data["scan"].get("rejection_code_counts", {}),
        },
        "observed_vocabulary": observed,
        "ledger": ledger_entries,
        "ledgered_leaf_keys": ledgered,
        "allocation_table": [
            {"sxt": "SXT-%s" % e["sxt"], "leaf_key": e["leaf_key"],
             "title": e["title"], "filing": e["filing"],
             "basis_recovery": e["recovery"]["basis_count"],
             "corpus_recovery": e["recovery"]["corpus_b4_supported_count"]}
            for e in plan_entries
        ],
        "filed_now": [e for e in plan_entries if e["filing"] == "file-now"],
        "backlog": backlog_entries,
        "backlog_zero_basis_deferred": zero_basis,
    }

    blob = json.dumps(plan, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"
    out_plan = Path(args.out_plan)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_plan.write_text(blob, encoding="utf-8")

    backlog = {
        "schema_version": "sxt-027-leaf-backlog/1.0.0",
        "artifact": "sxt-027-voice-leaf-backlog",
        "tool_version": TOOL_VERSION,
        "note": "Leaves NOT filed now, in recovery order; file later by "
                "this order (issue #20). Entries are planning artifacts "
                "only.",
        "essentiality_caveat": ESSENTIALITY_CAVEAT,
        "provenance": plan["provenance"],
        "leaves": [
            {k: e[k] for k in ("leaf_key", "sxt", "title", "recovery",
                               "fixture_carriers", "statics",
                               "subtype_inventory")}
            for e in backlog_entries
        ],
    }
    bblob = json.dumps(backlog, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n"
    out_backlog = Path(args.out_backlog)
    out_backlog.parent.mkdir(parents=True, exist_ok=True)
    out_backlog.write_text(bblob, encoding="utf-8")

    if args.out_bodies:
        bdir = Path(args.out_bodies)
        bdir.mkdir(parents=True, exist_ok=True)
        for e in plan_entries:
            if e["filing"] == "file-now":
                (bdir / ("%s.md" % e["sxt"])).write_text(
                    e["issue_body"], encoding="utf-8")

    print("plan: %d candidate leaves (%d file-now, %d backlog); ledger: %s"
          % (len(plan_entries), len(plan_entries) - len(backlog_entries),
             len(backlog_entries),
             ", ".join("%s->#%s" % (le["leaf_key"], le.get("issue"))
                       for le in ledger_entries)))
    for e in plan_entries:
        print("  SXT-%-3s %-46s basis=%3d corpus=%4d %s"
              % (e["sxt"], e["leaf_key"],
                 e["recovery"]["basis_count"],
                 e["recovery"]["corpus_b4_supported_count"], e["filing"]))
    print("wrote %s (%d bytes), %s (%d bytes)"
          % (out_plan, len(blob), out_backlog, len(bblob)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
