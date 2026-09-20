#!/usr/bin/env python3
"""SXT-011: export normalized patch graphs for every census entry.

For every entry in corpus/census-v0.1/corpus-manifest.json this tool:

  1. verifies the .fxp blob identity against the census,
  2. loads the file into the pinned native Surge XT engine through the
     official surgepy binding at 48 kHz (SurgeSynthesizer::loadPatch, the
     authoritative loader with all migrations),
  3. extracts NORMALIZED state (post-migration) with surgepy getters,
  4. compares a small set of raw, int-encoded stored ids (read structurally
     from the .fxp XML) against the normalized values so loader migrations
     become observable events,
  5. validates the extracted graph against live-derived engine ranges,
  6. emits ONE COMPACT single-line JSON object per preset to
     <out>/graphs.jsonl with an explicit per-entry status:
     "normalized" or "analysis_failure" (+ machine-readable reason).
     Unknown/undocumented behavior is a failure entry, never a guess.

Determinism: same corpus bytes + same engine pin => byte-identical
graphs.jsonl. No timestamps or machine paths are written into the
per-preset lines. Run-to-run metadata goes to --summary (JSON), which is
NOT part of the reproducible output.

Licensing: this script is original to the gf180-surge repository
(Apache-2.0). It imports the externally pinned GPL-3.0-or-later engine at
runtime through surgepy and copies no Surge source, tables, assets, or
preset payloads into this repository. Upstream functions relied upon are
cited (not copied) in corpus/normalized/README.md.

Usage:
  python3 tools/export_normalized_graphs.py [--out DIR] [--start N] [--end N]
      [--summary FILE] [--quiet]
"""

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "oracle"))

import oracle_common as oc  # noqa: E402

SCHEMA_VERSION = "sxt-011-normalized-graph-schema/1.0.0"
ENGINE_COMMIT = "58914e59c608ed4384ba6002e44c3465c58b2e71"
ENGINE_VERSION_STR = "1.4.HEAD.58914e59c"
SAMPLE_RATE = 48000

N_SCENES = 2
N_OSCS = 3
N_FILTERUNITS = 2
N_LFOS = 6
N_FX_SLOTS = 16  # pinned engine SurgeStorage.h: n_fx_slots = 16
N_FX_PARAMS = 12
MIXER_PATHS = ["o1", "o2", "o3", "ring_12", "ring_23", "noise"]

# FX slot roles, by patch fx[] array index. Pinned engine:
# SurgeStorage.h fxslot_positions / FxStorage fx[n_fx_slots] initializer
# (ains1, ains2, bins1, bins2, send1, send2, global1, global2,
#  ains3, ains4, bins3, bins4, send3, send4, global3, global4).
FX_ROLES = [
    "ains1", "ains2", "bins1", "bins2",
    "send1", "send2", "global1", "global2",
    "ains3", "ains4", "bins3", "bins4",
    "send3", "send4", "global3", "global4",
]

WT_FILE_EXTS = (".wt", ".wav", ".wtscript")  # SurgeStorage::refresh_wtlistFrom

# Generous upper bound for any enum id the raw-vs-normalized comparison will
# interpret (largest current id range: filter types 0..35). Values outside
# cannot be an id in any known streaming revision and are recorded as
# raw_uninterpretable instead of being compared or silently dropped.
ENUM_ID_BOUND = 127


# --------------------------------------------------------------------------
# raw .fxp structural read (XML sidecar; used ONLY for raw-vs-normalized
# migration comparison and asset provenance; never used to produce state)
# --------------------------------------------------------------------------

def read_fxp_raw(fxp_path):
    """Structural read of the .fxp chunk layout + raw XML int ids.

    Returns a dict. This is a RAW sidecar: values here are pre-migration
    stored ids and must never be exported as current state. Int-encoded
    fields only (value is an integer literal); floats are not interpreted.
    """
    out = {"xml_ok": False, "revision": None, "ints": {}, "wt": {},
           "embedded_wt_sizes": None}
    with open(fxp_path, "rb") as f:
        data = f.read()
    if len(data) >= 76 and data[:4] == b"CcnK" and data[60:64] == b"sub3":
        # chunk header wtsize[scene][osc] (census method, census.py)
        out["embedded_wt_sizes"] = list(struct.unpack_from("<6I", data, 68))
    xml_size = struct.unpack_from("<I", data, 64)[0]
    root = ET.fromstring(data[92:92 + xml_size].rstrip(b"\0"))
    if root.tag != "patch":
        raise ValueError("root element is not <patch>")
    out["xml_ok"] = True
    rev = root.attrib.get("revision")
    out["revision"] = int(rev) if rev is not None and rev.isdigit() else None
    ints = out["ints"]

    # (field key in this sidecar, raw XML suffix under the scene prefix "a_"/"b_")
    # Field keys use 0-based scene/unit indices to match the normalized graph.
    scene_keys = [
        ("osc0.type", "osc1_type"), ("osc1.type", "osc2_type"), ("osc2.type", "osc3_type"),
        ("osc0.param0", "osc1_param0"), ("osc1.param0", "osc2_param0"),
        ("osc2.param0", "osc3_param0"),
        ("fu0.type", "filter1_type"), ("fu0.subtype", "filter1_subtype"),
        ("fu1.type", "filter2_type"), ("fu1.subtype", "filter2_subtype"),
        ("ws.type", "ws_type"), ("pm", "polymode"), ("fbc", "fb_config"),
        ("fm.sw", "fm_switch"),
    ]
    for sc in range(N_SCENES):
        pfx = "ab"[sc]
        for name, key in scene_keys:
            ints["sc%d.%s" % (sc, name)] = raw_int(params_tag(root, pfx + "_" + key))
    for name in ("scenemode", "scene_active", "polylimit", "character",
                 "fx_bypass", "fx_disable"):
        ints[name] = raw_int(params_tag(root, name))
    for i in range(N_FX_SLOTS):
        ttag = params_tag(root, "fx%d_type" % (i + 1))
        ints["fx%d.type" % i] = raw_int(ttag)
        # p0 raw value is only comparable for int-encoded tags; otherwise None
        ptag = params_tag(root, "fx%d_p0" % (i + 1))
        ints["fx%d.p0" % i] = raw_int(ptag) if raw_int(ttag) is not None else None
    for sc in range(N_SCENES):
        for i in range(N_LFOS):
            ints["sc%d.lfo%d.shape" % (sc, i)] = raw_int(
                params_tag(root, "ab"[sc] + "_lfo%d_shape" % i))

    # Wavetable display names come from <extraoscdata> children; the engine
    # streams this attribute into OscillatorStorage::wavetable_display_name
    # (SurgePatch.cpp load_xml "extraoscdata" handling) and falls back to
    # "(Patch Wavetable)"/"(Patch Sample)" when absent.
    eod = root.find("extraoscdata")
    if eod is not None:
        for child in eod:
            sc = child.attrib.get("scene")
            osc = child.attrib.get("osc")
            nm = child.attrib.get("wavetable_display_name")
            if sc is not None and osc is not None:
                out["wt"]["sc%s.osc%s" % (sc, osc)] = {
                    "display_name": nm if nm else None,
                    "script": child.attrib.get("wavetable_script"),
                }
    return out


def params_tag(root, name):
    parameters = root.find("parameters")
    if parameters is None:
        return None
    return parameters.find(name)


def raw_int(tag):
    """Raw stored int/bool attribute, or None when absent or not int-encoded.

    The XML 'type' attribute is the streamed valtype (Parameter.h valtypes:
    vt_int=0, vt_bool=1, vt_float=2). Float params may be stored as locale
    floats or, in very old revisions, as IEEE bit patterns, so they are
    excluded here: this sidecar compares migration-relevant ENUM ids only.
    """
    if tag is None:
        return None
    if tag.attrib.get("type") not in ("0", "1"):
        return None
    v = tag.attrib.get("value")
    if v is None or not v.lstrip("-").isdigit():
        return None
    return int(v)


# --------------------------------------------------------------------------
# wavetable asset resolution inside the pinned data home
# --------------------------------------------------------------------------

class WtIndex:
    """Filename-stem index of wavetable files under <data>/wavetables.

    The engine's wt_list names are file stems without extension
    (SurgeStorage::refreshPatchOrWTListAddDir), scanned recursively from the
    'wavetables' data directory (SurgeStorage::refresh_wtlistAddDir).
    """

    def __init__(self, data_home):
        self.root = os.path.join(data_home, "wavetables")
        self.by_stem = {}
        self._hash_cache = {}
        if os.path.isdir(self.root):
            for dirpath, _dirnames, filenames in os.walk(self.root):
                for fn in filenames:
                    stem, ext = os.path.splitext(fn)
                    if ext.lower() in WT_FILE_EXTS:
                        self.by_stem.setdefault(stem, []).append(
                            os.path.join(dirpath, fn))

    def resolve(self, name):
        """All matching files (relative paths + sha256) for a wavetable name."""
        if not name:
            return []
        hits = self.by_stem.get(name, [])
        out = []
        for p in hits:
            rp = os.path.relpath(p, self.root)
            out.append([rp, self.sha256(p)])
        return sorted(out)

    def sha256(self, path):
        if path not in self._hash_cache:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            self._hash_cache[path] = h.hexdigest()
        return self._hash_cache[path]


# --------------------------------------------------------------------------
# normalized extraction (surgepy getters; the authoritative state)
# --------------------------------------------------------------------------

def r6(v):
    """Round a float for deterministic compact JSON; raises on non-finite."""
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("non-finite value from engine: %r" % (v,))
    return round(f, 6)


class Extractor:
    """Holds the live engine plus per-run derived tables (ranges, wt index)."""

    def __init__(self, surgepy, data_home):
        self.sp = surgepy
        self.s = surgepy.createSurge(SAMPLE_RATE)
        self.ms_ids = {
            getattr(surgepy.constants, k)
            for k in dir(surgepy.constants) if k.startswith("ms_")
        }
        self.ranges = {}
        self.wtindex = WtIndex(data_home)

    def val(self, p):
        """Normalized value as int (int/bool params) or rounded float."""
        t = self.s.getParamValType(p)
        v = self.s.getParamVal(p)
        if t in ("int", "bool"):
            return int(round(v))
        return r6(v)

    def valf(self, p):
        return r6(self.s.getParamVal(p))

    def name_of(self, p):
        return self.s.getParamDisplay(p)

    def extract(self, raw):
        """Return the normalized graph dict for the currently loaded preset."""
        s = self.s
        sp = self.sp
        patch = s.getPatch()
        g = {}

        # ---- global ----
        g["sm"] = self.val(patch["scenemode"])
        g["smn"] = self.name_of(patch["scenemode"])
        g["sa"] = self.val(patch["scene_active"])
        g["spl"] = self.val(patch["splitpoint"])
        g["poly"] = self.val(patch["polylimit"])
        g["ch"] = self.val(patch["character"])
        g["chn"] = self.name_of(patch["character"])
        g["fxb"] = self.val(patch["fx_bypass"])
        g["fxbn"] = self.name_of(patch["fx_bypass"])
        g["fxd"] = self.val(patch["fx_disable"])
        g["vol"] = self.valf(patch["volume"])

        # ---- scenes ----
        scenes = []
        deps = set()
        wt_assets = []
        for sc in range(N_SCENES):
            p = patch["scene"][sc]
            e = {}
            e["po"] = self.val(p["pitch"])
            e["oct"] = self.val(p["octave"])
            e["pm"] = self.val(p["polymode"])
            e["pmn"] = self.name_of(p["polymode"])
            e["pbrU"] = self.val(p["pbrange_up"])
            e["pbrD"] = self.val(p["pbrange_dn"])
            e["ktR"] = self.val(p["keytrack_root"])
            e["porta"] = self.valf(p["portamento"])
            e["fbc"] = self.val(p["filterblock_configuration"])
            e["fbcn"] = self.name_of(p["filterblock_configuration"])
            e["f2off"] = self.val(p["f2_cutoff_is_offset"])
            e["f2lnk"] = self.val(p["f2_link_resonance"])
            e["fb"] = self.valf(p["feedback"])
            e["bal"] = self.valf(p["filter_balance"])
            e["lc"] = self.valf(p["lowcut"])
            e["pfg"] = self.valf(p["level_pfg"])
            e["vca"] = self.valf(p["vca_level"])
            e["vs"] = self.valf(p["vca_velsense"])
            e["pan"] = self.valf(p["pan"])
            e["wid"] = self.valf(p["width"])
            e["send"] = [self.valf(sl) for sl in p["send_level"]]

            mix = {}
            for path in MIXER_PATHS:
                mix[path] = [
                    self.valf(p["level_" + path]),
                    self.val(p["mute_" + path]),
                    self.val(p["solo_" + path]),
                    self.val(p["route_" + path]),
                ]
            e["mix"] = mix
            e["fm"] = {"sw": self.val(p["fm_switch"]),
                       "dep": self.valf(p["fm_depth"])}

            oscs = []
            for oi in range(N_OSCS):
                o = p["osc"][oi]
                t = self.val(o["type"])
                tn = self.name_of(o["type"])
                if t == sp.constants.ot_audioinput:
                    deps.add("audio_input")
                oe = {
                    "t": t, "tn": tn,
                    "pit": self.valf(o["pitch"]),
                    "oct": self.val(o["octave"]),
                    "kt": self.val(o["keytrack"]),
                    "rt": self.val(o["retrigger"]),
                }
                oe["p"] = [self.val(pp) if self.s.getParamValType(pp) in ("int", "bool")
                           else self.valf(pp) for pp in o["p"]]
                # unison: per-osc "Unison Voices"/"Unison Detune" params
                uni, udet = None, None
                for pp in o["p"]:
                    nm = pp.getName()
                    if nm.endswith("Unison Voices"):
                        uni = self.val(pp)
                    elif nm.endswith("Unison Detune"):
                        udet = self.valf(pp)
                if uni is not None:
                    oe["uni"] = uni
                if udet is not None:
                    oe["udet"] = udet
                if t in (sp.constants.ot_wavetable, sp.constants.ot_window):
                    oe["wt"] = True
                    rawent = (raw or {}).get("wt", {}).get("sc%d.osc%d" % (sc, oi), {})
                    nm = rawent.get("display_name")
                    emb = None
                    sizes = (raw or {}).get("embedded_wt_sizes")
                    if sizes is not None:
                        emb = sizes[sc * N_OSCS + oi]
                    ent = {"sc": sc, "osc": oi, "name": nm, "emb": emb}
                    if rawent.get("script") is not None:
                        ent["script"] = rawent["script"]
                    if nm:
                        res = self.wtindex.resolve(nm)
                        if res:
                            ent["res"] = res
                    wt_assets.append(ent)
                oscs.append(oe)
            e["osc"] = oscs

            fus = []
            for fi in range(N_FILTERUNITS):
                fu = p["filterunit"][fi]
                fus.append({
                    "t": self.val(fu["type"]),
                    "tn": self.name_of(fu["type"]),
                    "st": self.val(fu["subtype"]),
                    "stn": self.name_of(fu["subtype"]),
                    "cut": self.valf(fu["cutoff"]),
                    "res": self.valf(fu["resonance"]),
                    "em": self.valf(fu["envmod"]),
                    "kt": self.val(fu["keytrack"]),
                })
            e["fu"] = fus

            e["ws"] = {"t": self.val(p["wsunit"]["type"]),
                       "tn": self.name_of(p["wsunit"]["type"]),
                       "dr": self.valf(p["wsunit"]["drive"])}

            lfos = []
            for li in range(N_LFOS):
                l = p["lfo"][li]
                sh = self.val(l["shape"])
                le = {"sh": sh, "shn": self.name_of(l["shape"]),
                      "rate": self.valf(l["rate"]),
                      "mag": self.valf(l["magnitude"]),
                      "up": self.val(l["unipolar"]),
                      "trg": self.val(l["trigmode"])}
                if sh in (sp.constants.lt_mseg, sp.constants.lt_formula):
                    # MSEG/Formula curve contents are not exposed through the
                    # surgepy binding; recorded as an explicit gap, never guessed.
                    le["gap"] = "modulator_contents_not_exposed_by_surgepy"
                lfos.append(le)
            e["lfo"] = lfos
            scenes.append(e)

        g["sc"] = scenes
        if wt_assets:
            g["wta"] = wt_assets

        # ---- fx (16 slots as exposed by the pinned engine) ----
        fxs = []
        for i in range(N_FX_SLOTS):
            fx = patch["fx"][i]
            t = self.val(fx["type"])
            fe = {"i": i, "r": FX_ROLES[i], "t": t, "tn": self.name_of(fx["type"])}
            if t != sp.constants.fxt_off:
                fe["on"] = 1
                fe["p"] = [self.val(pp) if self.s.getParamValType(pp) in ("int", "bool")
                           else self.valf(pp) for pp in fx["p"]]
                fe["rl"] = self.valf(fx["return_level"])
                if t == sp.constants.fxt_airwindows:
                    # exact Airwindows algorithm selection: p[0] int id + the
                    # engine's own display name for that algorithm.
                    fe["aw"] = fe["p"][0]
                    fe["awn"] = self.name_of(fx["p"][0])
            else:
                fe["on"] = 0
            fxs.append(fe)
        g["fx"] = fxs

        # ---- modulation routings (normalized depths via getModDepth01) ----
        md = s.getAllModRoutings()

        def route_row(r):
            src_id = r.getSource().getModSource()
            if src_id not in self.ms_ids:
                raise ValueError("modsource id %r outside live ms_* set" % (src_id,))
            d = r.getDepth()
            nd = r.getNormalizedDepth()
            if not (math.isfinite(d) and math.isfinite(nd)):
                raise ValueError("non-finite modulation depth")
            return [int(src_id), int(r.getSourceScene()), int(r.getSourceIndex()),
                    int(r.getDest().getId().getSynthSideId()),
                    r.getDest().getName(), r6(d), r6(nd)]

        g["md"] = {
            "g": [route_row(r) for r in md["global"]],
            "s": [{
                "s": [route_row(r) for r in md["scene"][sc]["scene"]],
                "v": [route_row(r) for r in md["scene"][sc]["voice"]],
            } for sc in range(N_SCENES)],
        }

        # ---- dynamic dependencies ----
        if deps:
            g["dep"] = sorted(deps)

        return g


# --------------------------------------------------------------------------
# raw-vs-normalized migration events (evidence-based differences only)
# --------------------------------------------------------------------------

def migration_events(raw, g, ex):
    """Compare raw stored int ids with normalized values.

    Records an event ONLY when the raw value is present, is interpretable as
    an id of that field (see ENUM_ID_BOUND), and differs from the normalized
    value. The note cites the migration gate in SurgePatch.cpp::load_xml (or
    the oscillator handleStreamingMismatches) that explains the difference.
    Missing raw fields (loader default applied) go to raw_missing; raw values
    that cannot be an id of the field in any known streaming revision (e.g.
    old float bit-pattern storage under an int tag) go to raw_uninterpretable.
    Nothing is silently dropped or guessed.
    """
    sp = ex.sp
    REV15 = "revision<15 'The Great Filter Remap' (SurgePatch.cpp load_xml, issue #3006)"
    SUBTYPE_NOTE = ("revision<8 subtype defaults / revision<=26 subtype migration "
                    "(SurgePatch.cpp load_xml)")
    REV27 = ("revision<=27 Sine/ringmod waveform migration (SurgePatch.cpp "
             "load_xml); rev<=12 files additionally pass SineOscillator::"
             "handleStreamingMismatches wave_remap")
    ev = []
    missing = []
    uninterp = []
    ints = raw.get("ints", {}) if raw else {}

    def id_like(v):
        """True if v can be an enum id of these fields in any known revision.

        127 is a generous bound above every current id range (filter types
        0..35, fx types 0..31, sine shapes 0..31, subtypes 0..15); old float
        bit-pattern storage (|v| ~ 1e9) can never fall inside it.
        """
        return v is not None and 0 <= v <= ENUM_ID_BOUND

    for sc in range(N_SCENES):
        for fu in range(N_FILTERUNITS):
            ft = "sc%d.fu%d.type" % (sc, fu)
            fs = "sc%d.fu%d.subtype" % (sc, fu)
            rt = ints.get(ft)
            rs = ints.get(fs)
            norm = g["sc"][sc]["fu"][fu]
            if rt is None:
                missing.append(ft)
            elif not id_like(rt):
                uninterp.append({"f": ft, "raw": rt})
            if rs is None:
                missing.append(fs)
            elif not id_like(rs):
                uninterp.append({"f": fs, "raw": rs})
            if id_like(rt) and (rt != norm["t"] or
                                (id_like(rs) and rs != norm["st"])):
                # record the (type, subtype) pair as one migration event: the
                # rev<15 remap moves both, the rev<8 defaults and the rev<=26
                # adjustments move the subtype.
                ev.append({"f": "sc%d.fu%d" % (sc, fu), "k": "filter_remap",
                           "raw": [rt, rs], "n": [norm["t"], norm["st"]],
                           "raw_meaning_pre15": "fut_14 id space (FilterConfiguration.h)",
                           "note": (REV15 if rt != norm["t"] else SUBTYPE_NOTE)})

        for oi in range(N_OSCS):
            ot = "sc%d.osc%d.type" % (sc, oi)
            op0 = "sc%d.osc%d.param0" % (sc, oi)
            rt = ints.get(ot)
            r0 = ints.get(op0)
            norm = g["sc"][sc]["osc"][oi]
            if rt is None:
                missing.append(ot)
            elif not id_like(rt):
                uninterp.append({"f": ot, "raw": rt})
            elif rt != norm["t"]:
                ev.append({"f": ot, "k": "osc_type_diff", "raw": rt, "n": norm["t"],
                           "note": "raw osc type differs from normalized (investigate)"})
            if norm["t"] == sp.constants.ot_sine and r0 is not None:
                if not id_like(r0):
                    uninterp.append({"f": op0, "raw": r0})
                elif r0 != norm["p"][0]:
                    ev.append({"f": op0, "k": "sine_shape_remap",
                               "raw": r0, "n": norm["p"][0], "note": REV27})
            # ot_twist pitch adjustment (rev<=27) is a float migration; the raw
            # sidecar deliberately does not interpret floats, so it is not
            # compared here (documented in the schema README).

    # scenemode/ws_type/polymode have no id migrations in the pinned loader;
    # they are compared in the negative-control script, not flagged as events.
    if ints.get("polylimit") is None:
        missing.append("polylimit")
    elif not id_like(ints["polylimit"]):
        uninterp.append({"f": "polylimit", "raw": ints["polylimit"]})
    elif ints["polylimit"] != g["poly"]:
        ev.append({"f": "polylimit", "k": "polylimit_default",
                   "raw": ints["polylimit"], "n": g["poly"],
                   "note": "revision<=15 && polylimit==8 -> DEFAULT_POLYLIMIT (SurgePatch.cpp)"})
    if ints.get("character") is None:
        missing.append("character")
    elif not id_like(ints["character"]):
        uninterp.append({"f": "character", "raw": ints["character"]})
    elif ints["character"] != g["ch"]:
        ev.append({"f": "character", "k": "character_default",
                   "raw": ints["character"], "n": g["ch"],
                   "note": "revision<10 -> character 0 (SurgePatch.cpp)"})

    for i in range(N_FX_SLOTS):
        rt = ints.get("fx%d.type" % i)
        norm_t = g["fx"][i]["t"]
        if rt is None:
            missing.append("fx%d.type" % i)
        elif not id_like(rt):
            uninterp.append({"f": "fx%d.type" % i, "raw": rt})
        elif rt != norm_t:
            ev.append({"f": "fx%d.type" % i, "k": "fx_type_diff",
                       "raw": rt, "n": norm_t,
                       "note": "raw fx type differs from normalized (investigate)"})
        if norm_t == sp.constants.fxt_ringmod:
            r0 = ints.get("fx%d.p0" % i)
            n0 = g["fx"][i].get("p", [None] * N_FX_PARAMS)[0]
            if r0 is not None:
                if not id_like(r0):
                    uninterp.append({"f": "fx%d.p0" % i, "raw": r0})
                elif n0 is not None and r0 != n0:
                    ev.append({"f": "fx%d.p0" % i, "k": "ringmod_shape_remap",
                               "raw": r0, "n": n0, "note": REV27})

    return ev, missing, uninterp


# --------------------------------------------------------------------------
# validation (live-derived ranges; no hardcoded tables)
# --------------------------------------------------------------------------

def validate(g, ex, sp):
    """Validate an extracted graph. Returns a list of violations (must be empty)."""
    v = []
    s = ex.s
    patch = s.getPatch()

    def in_range(tag, param, val):
        lo, hi = ex.ranges.get(tag, (None, None))
        if lo is None:
            lo, hi = s.getParamMin(param), s.getParamMax(param)
            ex.ranges[tag] = (lo, hi)
        if not (lo <= val <= hi):
            v.append("out_of_range:%s=%s not in [%s,%s]" % (tag, val, lo, hi))

    in_range("scenemode", patch["scenemode"], g["sm"])
    in_range("scene_active", patch["scene_active"], g["sa"])
    in_range("fx_bypass", patch["fx_bypass"], g["fxb"])
    in_range("character", patch["character"], g["ch"])
    if len(g["sc"]) != N_SCENES:
        v.append("scene_count")
    for sc in range(N_SCENES):
        e = g["sc"][sc]
        if len(e["osc"]) != N_OSCS or len(e["fu"]) != N_FILTERUNITS \
                or len(e["lfo"]) != N_LFOS:
            v.append("sc%d.counts" % sc)
        in_range("sc%d.polymode" % sc, patch["scene"][sc]["polymode"], e["pm"])
        in_range("sc%d.fbc" % sc, patch["scene"][sc]["filterblock_configuration"], e["fbc"])
        in_range("sc%d.fm_switch" % sc, patch["scene"][sc]["fm_switch"], e["fm"]["sw"])
        in_range("sc%d.ws_type" % sc, patch["scene"][sc]["wsunit"]["type"], e["ws"]["t"])
        for oi, oe in enumerate(e["osc"]):
            in_range("osc.type", patch["scene"][sc]["osc"][oi]["type"], oe["t"])
        for fi, fe in enumerate(e["fu"]):
            in_range("fu.type", patch["scene"][sc]["filterunit"][fi]["type"], fe["t"])
            in_range("fu.subtype", patch["scene"][sc]["filterunit"][fi]["subtype"], fe["st"])
        for li, le in enumerate(e["lfo"]):
            in_range("lfo.shape", patch["scene"][sc]["lfo"][li]["shape"], le["sh"])
    if len(g["fx"]) != N_FX_SLOTS:
        v.append("fx_count")
    for i, fe in enumerate(g["fx"]):
        in_range("fx.type", patch["fx"][i]["type"], fe["t"])
        if fe["t"] == sp.constants.fxt_airwindows:
            p0 = fe.get("aw")
            awparam = patch["fx"][i]["p"][0]
            if p0 is None:
                v.append("aw_param_missing:slot%d" % i)
            else:
                lo, hi = ex.ranges.get("aw_p0", (None, None))
                if lo is None:
                    lo, hi = s.getParamMin(awparam), s.getParamMax(awparam)
                    ex.ranges["aw_p0"] = (lo, hi)
                if not (lo <= p0 <= hi):
                    v.append("aw_id_out_of_range:slot%d=%s not in [%s,%s]"
                             % (i, p0, lo, hi))
    for row in g["md"]["g"]:
        if row[0] not in ex.ms_ids:
            v.append("modsource_id:%d" % row[0])
    for sc in g["md"]["s"]:
        for row in sc["s"] + sc["v"]:
            if row[0] not in ex.ms_ids:
                v.append("modsource_id:%d" % row[0])
    return v


# --------------------------------------------------------------------------
# per-entry export
# --------------------------------------------------------------------------

def export_entry(idx, entry, ex, data_home):
    rel = entry["path"]
    bank = "factory" if "patches_factory" in rel else "contributor"
    fxp = os.path.join(data_home, os.path.relpath(rel, "resources/data"))

    line = {
        "p": rel,
        "b": bank,
        "sha": entry["git_blob_sha1"],
        "sz": entry["size"],
        "st": "normalized",
        "pin": {"e": ENGINE_COMMIT, "sr": SAMPLE_RATE, "sv": SCHEMA_VERSION},
    }

    # blob identity re-verification (abort on mismatch, as SXT-010 does)
    actual = oc.git_blob_sha1(fxp)
    if actual != entry["git_blob_sha1"] or os.path.getsize(fxp) != entry["size"]:
        print("REFUSING: corpus tree mismatch at entry %d: %s" % (idx, rel),
              file=sys.stderr)
        sys.exit(3)

    raw = None
    raw_err = None
    try:
        raw = read_fxp_raw(fxp)
        if raw.get("revision") is not None:
            line["rev"] = raw["revision"]
    except Exception as exc:  # structural read failed (e.g. Snare Tight XML char)
        raw_err = "%s: %s" % (type(exc).__name__, exc)

    try:
        ex.s.allNotesOff()
        ok = bool(ex.s.loadPatch(fxp))
        if not ok:
            line["st"] = "analysis_failure"
            line["why"] = {"phase": "load", "reason": "load_false"}
            return line
    except Exception as exc:
        line["st"] = "analysis_failure"
        line["why"] = {"phase": "load", "reason": "exception",
                       "detail": "%s: %s" % (type(exc).__name__, exc)}
        return line

    try:
        g = ex.extract(raw)
    except Exception as exc:
        line["st"] = "analysis_failure"
        line["why"] = {"phase": "extract", "reason": "exception",
                       "detail": "%s: %s" % (type(exc).__name__, exc)}
        return line

    try:
        violations = validate(g, ex, ex.sp)
        if violations:
            line["st"] = "analysis_failure"
            line["why"] = {"phase": "validate",
                           "reason": "schema_validation_failed",
                           "detail": "; ".join(violations[:8])}
            return line
    except Exception as exc:
        line["st"] = "analysis_failure"
        line["why"] = {"phase": "validate", "reason": "exception",
                       "detail": "%s: %s" % (type(exc).__name__, exc)}
        return line

    try:
        ev, missing, uninterp = migration_events(raw, g, ex)
    except Exception as exc:
        line["st"] = "analysis_failure"
        line["why"] = {"phase": "migration_compare", "reason": "exception",
                       "detail": "%s: %s" % (type(exc).__name__, exc)}
        return line

    if raw_err is not None:
        # Raw structural sidecar unavailable (e.g. Snare Tight): the normalized
        # state is authoritative and complete; the raw comparison is waived and
        # the waiver is recorded, never silent.
        g["raw_note"] = "raw_xml_unreadable: %s" % raw_err
    else:
        if ev:
            g["mi"] = ev
        if missing:
            g["rwm"] = sorted(missing)
        if uninterp:
            g["rwu"] = sorted(uninterp, key=lambda d: (d["f"], d["raw"]))

    line["g"] = g
    return line


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=REPO_ROOT)
    ap.add_argument("--out", default=None,
                    help="output directory for graphs.jsonl (default <repo>/corpus/normalized)")
    ap.add_argument("--summary", default=None, help="run metadata JSON path")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo_root)
    oc.reexec_under_pinned_python(repo)
    out_dir = args.out or os.path.join(repo, "corpus", "normalized")
    os.makedirs(out_dir, exist_ok=True)

    manifest = oc.load_census_manifest(repo)
    entries = manifest["entries"]
    with open(os.path.join(repo, "oracle", "manifest.json"), "r", encoding="utf-8") as f:
        oracle_manifest = json.load(f)
    if oracle_manifest["engine"]["commit"] != manifest["commit"]:
        print("REFUSING: oracle manifest pin %s != census pin %s"
              % (oracle_manifest["engine"]["commit"], manifest["commit"]),
              file=sys.stderr)
        return 2
    if oracle_manifest["engine"]["commit"] != ENGINE_COMMIT:
        print("REFUSING: exporter pin %s != oracle manifest pin %s"
              % (ENGINE_COMMIT, oracle_manifest["engine"]["commit"]), file=sys.stderr)
        return 2

    oc.apply_engine_env()
    surgepy = oc.import_surgepy()
    if surgepy.getVersion() != ENGINE_VERSION_STR:
        print("REFUSING: unexpected engine version %r" % surgepy.getVersion(),
              file=sys.stderr)
        return 2

    ex = Extractor(surgepy, oc.data_home())
    data_home = oc.data_home()
    end = args.end if args.end is not None else len(entries)

    t_all = time.time()
    out_path = os.path.join(out_dir, "graphs.jsonl")
    mode = "w" if args.start == 0 else "a"
    counts = {"normalized": 0, "analysis_failure": 0}
    norm_by_bank = {"factory": 0, "contributor": 0}
    fails_by_bank = {"factory": 0, "contributor": 0}
    mig_kinds = {}
    with open(out_path, mode, encoding="utf-8", newline="\n") as f:
        for i in range(args.start, end):
            line = export_entry(i, entries[i], ex, data_home)
            counts[line["st"]] += 1
            if line["st"] == "normalized":
                norm_by_bank[line["b"]] += 1
                for e in (line.get("g") or {}).get("mi", []):
                    mig_kinds[e["k"]] = mig_kinds.get(e["k"], 0) + 1
            else:
                fails_by_bank[line["b"]] += 1
            f.write(json.dumps(line, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False) + "\n")
            f.flush()
            if not args.quiet and (i + 1) % 250 == 0:
                print("  %d/%d (%.1fs)" % (i + 1, end, time.time() - t_all), flush=True)

    size = os.path.getsize(out_path)
    summary = {
        "issue": "SXT-011",
        "schema_version": SCHEMA_VERSION,
        "engine_commit": ENGINE_COMMIT,
        "engine_version": surgepy.getVersion(),
        "sample_rate": SAMPLE_RATE,
        "census_manifest": "corpus/census-v0.1/corpus-manifest.json",
        "entries_total": end - args.start,
        "counts": counts,
        "normalized_by_bank": norm_by_bank,
        "failures_by_bank": fails_by_bank,
        "migration_event_kinds": mig_kinds,
        "output": out_path,
        "output_bytes": size,
        "under_size_guard": size < 150 * 1024 * 1024,
        "determinism": ("same corpus bytes + engine pin => byte-identical "
                        "graphs.jsonl (no timestamps in per-preset lines)"),
        "wall_seconds": round(time.time() - t_all, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("Normalized-state export only: no audio-support, fidelity, or "
                 "preset-quality claim. Raw .fxp ids are never exported as state."),
    }
    if args.summary:
        os.makedirs(os.path.dirname(os.path.abspath(args.summary)), exist_ok=True)
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    print(json.dumps({k: summary[k] for k in
                      ("entries_total", "counts", "normalized_by_bank",
                       "failures_by_bank", "migration_event_kinds",
                       "output_bytes", "under_size_guard", "wall_seconds")},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
