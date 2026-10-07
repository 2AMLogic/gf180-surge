#!/usr/bin/env python3
"""SXT-043 declared fixture configuration (shared by the extractor, the
reference renderer and the negative controls).

One implementation of: preset load, parameter read, and the DECLARED fixture
overrides applied through the official surgepy parameter-change path
(`setParamVal` / `setPortamentoOptions`), with mandatory readback
verification.  Structure follows the landed SXT-040 Sine configuration
(`model/oscillators/sine/fixture_config.py`).

WHAT THE OVERRIDES DO, AND WHY THEY ARE DIFFERENT HERE
------------------------------------------------------
Every other voice leaf isolates an *audio* stage and keeps the carrier's
articulation.  This leaf isolates the *articulation* and therefore pins the
audio stage instead: the modeled quantity is the pm_mono_st_fp allocation /
legato / portamento behavior, so the oscillator, filters, waveshaper, FX and
mixer are forced into the already-landed, already-qualified frozen slice and
the carrier contributes its PLAYMODE, PORTAMENTO, mono priority/envelope
modes, amp envelope, scene octave and output staging.

Concretely the modeled slot is forced to a Sine oscillator, shape 0, legacy
FM path (FMmode 0), unison 1, retrigger ON, lowcut/highcut off -- the exact
SXT-026a/SXT-040 legacy quadrature slice -- with both filter units Off, the
waveshaper Off, the scene lowcut off, all 16 FX Off, every other mixer path
muted, the slot's output route pinned to 1, fbc pinned to fc_serial1 (the
mono voice path), scene mode Single and scene drift 0.

These are TEST CONFIGURATIONS.  They are never adapted presets and they
never count toward preset coverage: a render made under them says nothing
about whether the carrier preset is supported.  What is NOT overridden -- and
is therefore under test -- is:

  * `polymode` (pm_mono_st_fp, id 4);
  * `portamento` value and its four options (curve / glissando /
    constant rate / retrigger) and tempo-sync flag;
  * `monoVoicePriorityMode`, `monoVoiceEnvelopeMode` (patch non-param
    config, read back from the engine's own post-load serialization);
  * the amp envelope, scene octave, scene/VCA/velocity-sense gains, pan,
    master volume, patch character.

The oracle renders the SAME overridden configuration, so the comparison is
model-vs-engine over the articulation, not over three unmodeled oscillator
families.

FIXTURE REVISION 2 (issue #329, follow-up to the #311 root cause)
----------------------------------------------------------------
Revision 1 switched the oscillator type FIRST and classified/zeroed
modulation routes AFTERWARDS by post-switch display name.  A voice route into
one of the slot's seven `p[]` parameters survives the queued type switch
(the engine's `clear_osc_modulation` is skipped on the binding path), lands
on the Sine oscillator's integer Shape selector and silences it (Digibass:
`Velocity` / `Filter EG -> A Osc 1 Morph`).  Revision 1's `modpin_zero` then
"zeroed" the retargeted route through `setModDepth01`, which is a no-op on a
non-modulatable target, and its readback compared the NORMALIZED depth --
which reads 0 for such a target while the raw depth stays intact -- so the
committed revision-1 Digibass sidecar records those two routes as pinned
although they were still live.

Revision 2 changes only the ORDER and the READBACK:

  1. immediately after `loadPatch`, before any override, every routing
     whose destination is one of the modeled slot's seven ORIGINAL `p[]`
     parameters (matched by engine synth-side parameter id, captured
     before the type remap; display names are recorded but never used for
     matching) is set to depth 0 through the official `setModDepth01` path
     with its source scene/index preserved; the readback is verified both
     through `getModDepth01` and by re-enumerating `getAllModRoutings()`
     and checking the RAW depth (`osc_p_route_clear`, recorded verbatim in
     fixture metadata with the original depths and the reason);
  2. then the type switch, settle, handle re-fetch (unchanged);
  3. a post-switch guard refuses if ANY routing into the slot's `p[]`
     parameters still carries a nonzero raw depth;
  4. `modpin_zero` readback now also re-enumerates raw depths, so a no-op
     zeroing can never again be recorded as pinned.

Amp/VCA, playmode, portamento and mono priority/envelope behaviour are not
touched by the route clear: only routings whose DESTINATION is an osc-slot
`p[]` parameter are cleared, and those parameters are replaced wholesale by
the pinned Sine slice anyway.  Unknown routes still refuse.
"""

import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, REPO)

from refusal import Refuse  # noqa: E402

# Carrier presets: issue #77's three named carriers (all pm_mono_st_fp in
# scene A), plus the out-of-class refusal controls.  The modeled slot is
# osc 1 (index 0) for every carrier: the override forces that slot to Sine.
CARRIERS = {
    "bass2": ("patches_factory/Basses/Bass 2.fxp", 0),
    "bass5": ("patches_factory/Basses/Bass 5.fxp", 0),
    "digibass": ("patches_factory/Basses/Digibass.fxp", 0),
    # Refusal controls (the extractor must REFUSE each of these, exit 2).
    # Every one is a real normalized-corpus preset whose scene-A playmode is
    # a DIFFERENT member of the pinned `play_mode` enum, so each demonstrates
    # that the gate rejects by submode and not merely by "not poly":
    #   attacky  - pm_poly       (0)  - the landed SXT-022 carrier
    #   distbass1- pm_mono       (1)
    #   behemoth - pm_mono_st    (2)  - single trigger WITHOUT fingered porta
    #   plain    - pm_mono_fp    (3)  - fingered porta WITHOUT single trigger
    "attacky": ("patches_factory/Basses/Attacky.fxp", 0),
    "distbass1": ("patches_factory/Basses/Dist Bass 1.fxp", 0),
    "behemoth": ("patches_factory/Basses/Behemoth.fxp", 0),
    "plain": ("patches_factory/Basses/Plain.fxp", 0),
}

# Carriers the leaf renders and grades (the rest are refusal controls only).
FIXTURE_CARRIERS = ("bass2", "bass5", "digibass")
REFUSAL_CONTROLS = ("attacky", "distbass1", "behemoth", "plain")

# Modulation destinations (engine display names) that stay LIVE under the
# declared overrides.  These are the destinations already in the landed
# declared route vocabulary (SXT-035 / SXT-042); anything else must be
# structurally inert, pinned, or the carrier is REFUSED.
LIVE_DEST_VOCABULARY = {"A VCA Gain"}

# Modulation sources (engine display names) whose output is identically zero
# throughout a MIDI-note-only fixture sequence: no CC, no aftertouch, no
# pitch bend, no channel pressure, no pedal.  A route from one of these is
# DECLARED INERT, and `assert_sequence_sources_inert` re-checks the sequence
# actually carries no event that could wake it.
INERT_SOURCES = {
    "Modwheel": "no CC events in the fixture sequence",
    "Breath": "no CC events in the fixture sequence",
    "Expression": "no CC events in the fixture sequence",
    "Sustain Pedal": "no pedal events in the fixture sequence",
    "Channel Aftertouch": "no aftertouch events in the fixture sequence",
    "Poly Aftertouch": "no aftertouch events in the fixture sequence",
    "Pitch Bend": "no pitch-bend events in the fixture sequence",
    "Timbre": "MPE off",
    "Macro 1": "no macro automation in the fixture sequence",
    "Macro 2": "no macro automation in the fixture sequence",
    "Macro 3": "no macro automation in the fixture sequence",
    "Macro 4": "no macro automation in the fixture sequence",
    "Macro 5": "no macro automation in the fixture sequence",
    "Macro 6": "no macro automation in the fixture sequence",
    "Macro 7": "no macro automation in the fixture sequence",
    "Macro 8": "no macro automation in the fixture sequence",
}

# Destination-name prefixes the declared overrides make structurally inert,
# each with the override that does it.  Matching is by prefix on the engine's
# own display name, so an unrecognized destination can never slip through.
INERT_DEST_PREFIXES = (
    ("A Filter 1 ", "filter unit 1 forced Off"),
    ("A Filter 2 ", "filter unit 2 forced Off"),
    ("A Filter Balance", "both filter units Off"),
    ("A Filter EG ", "filter unit 1 forced Off (FEG reaches no audio)"),
    ("A Feedback", "both filter units Off at fc_serial1"),
    ("A Waveshaper ", "waveshaper forced Off"),
    ("A Low Cut", "scene low cut forced to its off value"),
    ("A LFO ", "no LFO route reaches the declared audio slice"),
    ("A Noise ", "the noise mixer path is muted"),
    ("A Osc 2 ", "mixer path o2 is muted"),
    ("A Osc 3 ", "mixer path o3 is muted"),
    ("A Ring ", "both ring-modulator paths are muted"),
    ("A Send ", "every FX slot is forced Off"),
    ("FX ", "every FX slot is forced Off"),
    ("B ", "scene mode forced to Single: scene B is not rendered"),
    ("Scene B ", "scene mode forced to Single: scene B is not rendered"),
)

# Fixture revision.  1 = the #77 landing (type switch first, name-based
# post-switch route pin); 2 = #329 (osc-slot p[] routes cleared by original
# parameter identity BEFORE the type switch, raw-depth readback).  Every
# sidecar written by the extractor / reference renderer records it, so an
# artifact produced under revision 1 can never pass for a revision-2 one.
FIXTURE_REVISION = 2

# Depth below which a routing counts as zero on readback (raw and 0..1).
ROUTE_ZERO_EPS = 1e-9

OVERRIDE_KEYS = [
    "osc_p_route_clear",
    "mute_o1", "mute_o2", "mute_o3", "mute_noise", "mute_ring_12",
    "mute_ring_23", "fu0_off", "fu1_off", "fx_off", "ws_off", "lc_off",
    "fbc_serial1", "fm_off", "scenemode_single", "retrigger_on",
    "drift_zero", "route_slot_1", "osc_sine", "osc_shape_0",
    "osc_fmmode_legacy", "osc_unison_1", "osc_lowcut_off",
    "osc_highcut_off", "osc_detune_zero", "osc_octave_0", "osc_pitch_0",
    "osc_keytrack_on",
    "scene_pitch_0", "pfg_zero", "modpin_zero",
]


def preset_abs(oc, carrier):
    rel, _slot = CARRIERS[carrier]
    return os.path.join(oc.engine_dir(), "resources", "data", rel)


def preset_rel(carrier):
    rel, _slot = CARRIERS[carrier]
    return "resources/data/" + rel


def read_params(s, slot):
    """Everything the model and its gates read, straight off the engine."""
    patch = s.getPatch()
    sc = patch["scene"][0]
    o = sc["osc"][slot]
    p = {k: s.getParamVal(o["p"][k]) for k in range(7)}
    porta = sc["portamento"]
    return {
        "osc_type": int(s.getParamVal(o["type"])),
        "octave": int(s.getParamVal(o["octave"])),
        "scene_octave": int(s.getParamVal(sc["octave"])),
        "keytrack": bool(s.getParamVal(o["keytrack"])),
        "pitch_param": s.getParamVal(o["pitch"]),
        "pitch_extend": bool(s.getExtend(o["pitch"])),
        "retrigger": bool(s.getParamVal(o["retrigger"])),
        "shape": int(p[0]),
        "fb": p[1],
        "fmmode": int(p[2]),
        "lowcut": p[3],
        "highcut": p[4],
        "unison_detune": p[5],
        "unison": int(p[6]),
        "fb_extend": bool(s.getExtend(o["p"][1])),
        "extend_detune": bool(s.getExtend(o["p"][5])),
        "absolute_detune": bool(s.getAbsolute(o["p"][5])),
        "drift": s.getParamVal(sc["drift"]),
        "character": int(s.getParamVal(patch["character"])),
        "o_level": s.getParamVal(sc["level_o%d" % (slot + 1)]),
        "level_pfg": s.getParamVal(sc["level_pfg"]),
        "pan": s.getParamVal(sc["pan"]),
        "width": s.getParamVal(sc["width"]),
        "scene_volume": s.getParamVal(sc["volume"]),
        "scene_pitch": s.getParamVal(sc["pitch"]),
        "vca_db": s.getParamVal(sc["vca_level"]),
        "vca_velsense": s.getParamVal(sc["vca_velsense"]),
        "master_db": s.getParamVal(patch["volume"]),
        "polylimit": int(s.getParamVal(patch["polylimit"])),
        "adsr": {k: s.getParamVal(sc["adsr"][0][k])
                 for k in ("a", "d", "s", "r", "a_s", "d_s", "r_s", "mode")},
        "fu0_type": int(s.getParamVal(sc["filterunit"][0]["type"])),
        "fu1_type": int(s.getParamVal(sc["filterunit"][1]["type"])),
        "ws_type": int(s.getParamVal(sc["wsunit"]["type"])),
        "filter_config": int(s.getParamVal(sc["filterblock_configuration"])),
        "fm_switch": int(s.getParamVal(sc["fm_switch"])),
        "lowcut_scene": s.getParamVal(sc["lowcut"]),
        "scenemode": int(s.getParamVal(patch["scenemode"])),
        "polymode": int(s.getParamVal(sc["polymode"])),
        "portamento": s.getParamVal(porta),
        "portamento_min": s.getParamMin(porta),
        "portamento_max": s.getParamMax(porta),
        "portamento_options": dict(s.getPortamentoOptions(porta)),
        "portamento_temposync": bool(s.getTempoSync(porta)),
        "pbrange_up": s.getParamVal(sc["pbrange_up"]),
        "pbrange_dn": s.getParamVal(sc["pbrange_dn"]),
        "fx_types": [int(s.getParamVal(patch["fx"][i]["type"]))
                     for i in range(16)],
        "mutes": {k: s.getParamVal(sc["mute_" + k])
                  for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")},
        "route_slot": int(s.getParamVal(sc["route_o%d" % (slot + 1)])),
    }


_NONPARAM_RE = re.compile(r"<nonparamconfig.*?</nonparamconfig>", re.S)
_ATTR_RE = r'<%s\s+v="(-?\d+)"\s*/>'


def read_nonparam_mono_config(s):
    """Read `monoVoicePrority_0` / `monoVoiceEnvelope_0` from the ENGINE.

    These two fields are patch non-param config: they are not Parameters, so
    surgepy exposes no getter for them, and `graphs.jsonl` schema rev 1.0.0
    does not carry them.  They are read here the only authoritative way --
    by asking the engine to serialize the state it produced from its own
    `loadPatch` (`SurgePatch::save_patch`, the inverse of the
    `nonparamconfig` loader whose defaults and `revision < 15` legacy
    override are what make these values preset-dependent).  Nothing is
    guessed and no raw `.fxp` byte is interpreted by this repository.
    """
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "readback.fxp")
        s.savePatch(out)
        with open(out, "rb") as f:
            data = f.read()
    i = data.find(b"<patch")
    if i < 0:
        raise Refuse("engine savePatch readback carries no <patch> element")
    txt = data[i:].decode("utf-8", "replace")
    m = _NONPARAM_RE.search(txt)
    if not m:
        raise Refuse("engine savePatch readback carries no <nonparamconfig>")
    blob = m.group(0)
    got = {}
    for name, field in (("monoVoicePrority_0", "mono_voice_priority_mode"),
                        ("monoVoiceEnvelope_0", "mono_voice_envelope_mode"),
                        ("polyVoiceRepeatedKeyMode_0",
                         "poly_voice_repeated_key_mode")):
        mm = re.search(_ATTR_RE % name, blob)
        if not mm:
            raise Refuse(f"engine readback has no <{name}> element")
        got[field] = int(mm.group(1))
    return got


def carrier_overrides(slot):
    """The DECLARED isolation override set for the modeled slot index."""
    return [
        ("mute_o1", slot != 0), ("mute_o2", slot != 1), ("mute_o3", slot != 2),
        ("mute_noise", True), ("mute_ring_12", True), ("mute_ring_23", True),
        ("fu0_off", True), ("fu1_off", True), ("fx_off", True),
        ("ws_off", True), ("lc_off", True), ("fbc_serial1", True),
        ("fm_off", True), ("scenemode_single", True), ("retrigger_on", True),
        ("drift_zero", True), ("route_slot_1", True),
        # audio-stage pin: the already-landed legacy Sine quadrature slice
        ("osc_sine", True), ("osc_shape_0", True),
        ("osc_fmmode_legacy", True), ("osc_unison_1", True),
        ("osc_lowcut_off", True), ("osc_highcut_off", True),
        ("osc_detune_zero", True),
        ("osc_octave_0", True), ("osc_pitch_0", True),
        ("osc_keytrack_on", True), ("scene_pitch_0", True),
        ("pfg_zero", True),
    ]


def _route_rows(s):
    """Flatten `getAllModRoutings()` into `(scope, scene_or_None, routing)`."""
    routings = s.getAllModRoutings()
    rows = [("global", None, r) for r in routings.get("global", [])]
    for si, tbl in enumerate(routings.get("scene", [])):
        for scope in ("scene", "voice"):
            for r in tbl.get(scope, []):
                rows.append((scope, si, r))
    return rows


def _param_id(p):
    """The engine's synth-side parameter id: stable across a type remap
    (the slot's `p[k]` keeps its id while its meaning/name changes)."""
    return int(p.getId().getSynthSideId())


def _raw_depth_of(s, dest_id, src_name, source_scene, source_index):
    """Re-enumerate the engine's routes and return the RAW depth of the
    matching routing, or None when the engine no longer lists it."""
    for _scope, _si, r in _route_rows(s):
        if (_param_id(r.getDest()) == dest_id
                and r.getSource().getName() == src_name
                and int(r.getSourceScene()) == int(source_scene)
                and int(r.getSourceIndex()) == int(source_index)):
            return float(r.getDepth())
    return None


def osc_param_targets(s, slot):
    """Identity of the modeled slot's seven `p[]` parameters, read NOW.

    Returns `{synth_side_id: (k, display_name)}`.  Must be called before the
    type switch: afterwards the same ids carry the new type's names.
    """
    o = s.getPatch()["scene"][0]["osc"][slot]
    targets = {}
    for k in range(7):
        h = o["p"][k]
        pid = _param_id(h)
        if pid in targets:
            raise Refuse("osc slot %d p[%d] and p[%d] share synth-side id %d: "
                         "route identity is ambiguous" % (slot, targets[pid][0],
                                                          k, pid))
        targets[pid] = (k, h.getName())
    return targets


def clear_osc_param_routes(s, slot):
    """Override `osc_p_route_clear` (fixture revision 2, issue #329).

    MUST run after `loadPatch` and BEFORE the oscillator type switch.  Every
    routing (any scope) whose destination is one of the modeled slot's seven
    ORIGINAL `p[]` parameters -- matched by synth-side id, never by display
    name -- is set to depth 0 through the official `setModDepth01` path with
    its source scene and index preserved.  Readback is verified twice: the
    0..1 depth via `getModDepth01`, and the RAW depth by re-enumerating
    `getAllModRoutings()` (the route must be gone or carry depth 0).  Any
    failure REFUSES.  The original state of every cleared routing and the
    reason are returned for the fixture metadata.
    """
    targets = osc_param_targets(s, slot)
    cleared = []
    for scope, si, r in _route_rows(s):
        dest = r.getDest()
        did = _param_id(dest)
        if did not in targets:
            continue
        k, orig_name = targets[did]
        src = r.getSource()
        rec = {
            "scope": scope, "scene": si,
            "src": src.getName(),
            "source_scene": int(r.getSourceScene()),
            "source_index": int(r.getSourceIndex()),
            "dest": dest.getName(),
            "dest_original_name": orig_name,
            "dest_param_index": k,
            "dest_synth_side_id": did,
            "depth_original": float(r.getDepth()),
            "norm_depth_original": float(r.getNormalizedDepth()),
            "why": ("destination is osc slot %d p[%d] (%s), which the "
                    "declared Sine type switch remaps; a surviving routing "
                    "retargets the Sine integer Shape selector (#311), so "
                    "its depth is zeroed BEFORE the switch "
                    "(osc_p_route_clear, fixture revision %d)"
                    % (slot, k, orig_name, FIXTURE_REVISION)),
        }
        s.setModDepth01(dest, src, 0.0, scene=rec["source_scene"],
                        index=rec["source_index"])
        back01 = s.getModDepth01(dest, src, scene=rec["source_scene"],
                                 index=rec["source_index"])
        rec["readback_depth01"] = float(back01)
        cleared.append(rec)
    for rec in cleared:
        raw = _raw_depth_of(s, rec["dest_synth_side_id"], rec["src"],
                            rec["source_scene"], rec["source_index"])
        rec["readback_raw_depth"] = raw          # None == routing removed
        if abs(rec["readback_depth01"]) > ROUTE_ZERO_EPS or (
                raw is not None and abs(raw) > ROUTE_ZERO_EPS):
            raise Refuse(
                "osc_p_route_clear readback failed for %s -> %s (p[%d]): "
                "depth01=%r raw=%r" % (rec["src"], rec["dest_original_name"],
                                       rec["dest_param_index"],
                                       rec["readback_depth01"], raw))
    return {
        "fixture_revision": FIXTURE_REVISION,
        "order": "after loadPatch, before the oscillator type switch",
        "match": "engine synth-side parameter id of osc slot p[0..6]",
        "slot": slot,
        "targets": [{"param_index": k, "synth_side_id": pid,
                     "original_name": name}
                    for pid, (k, name) in sorted(targets.items(),
                                                 key=lambda t: t[1][0])],
        "cleared": cleared,
    }


def stale_osc_param_routes(s, slot):
    """Every routing into the slot's `p[]` parameters with a nonzero RAW
    depth (post-switch guard; empty on a correctly configured instance)."""
    o = s.getPatch()["scene"][0]["osc"][slot]
    ids = {_param_id(o["p"][k]) for k in range(7)}
    out = []
    for scope, si, r in _route_rows(s):
        if _param_id(r.getDest()) in ids and abs(r.getDepth()) > ROUTE_ZERO_EPS:
            out.append({"scope": scope, "scene": si,
                        "src": r.getSource().getName(),
                        "dest": r.getDest().getName(),
                        "depth": float(r.getDepth())})
    return out


def classify_and_pin_routes(s, pinned_names):
    """Classify every live modulation route; zero the ones into pinned params.

    Read from the engine's own `getAllModRoutings()` -- the authoritative
    post-`loadPatch` route list, with engine display names -- never from a
    re-parse of the preset file.  Each route is classified as:

      * **inert**  -- its source is identically zero for a MIDI-note-only
        sequence, or its destination is structurally unreachable under the
        declared overrides (a muted mixer path, an Off filter unit, an Off
        FX slot, scene B);
      * **pinned** -- its destination is a parameter the declared fixture
        configuration pins to a constant.  Leaving such a route live would
        defeat the pin it is part of, so the declared override `modpin_zero`
        sets its depth to 0 **through the official `setModDepth01` path** and
        verifies the readback.  This is a test configuration, identical in
        both the model and the oracle render, and never a claim about the
        carrier preset;
      * **live**   -- its destination is in the declared destination
        vocabulary and the model implements it.

    Anything else REFUSES (exit 2).  No route is ever silently dropped.

    Fixture revision 2: a `modpin_zero` readback also re-enumerates the
    routes and checks the RAW depth.  Revision 1 checked only
    `getModDepth01`, which reads 0 on a non-modulatable destination even
    while the raw depth is intact -- that is how the retargeted Digibass
    routes were recorded as pinned though still live (#329).
    """
    live, inert, pinned = [], [], []
    for scope, si, r in _route_rows(s):
        src = r.getSource()
        dest = r.getDest()
        src_name = src.getName()
        dest_name = dest.getName()
        rec = {"scope": scope, "scene": si, "src": src_name,
               "dest": dest_name, "depth": r.getDepth(),
               "norm_depth": r.getNormalizedDepth()}
        if scope == "global":
            rec["why"] = "every FX slot is forced Off"
            inert.append(rec)
            continue
        if si != 0:
            rec["why"] = "scene mode forced to Single: scene B not rendered"
            inert.append(rec)
            continue
        if src_name in INERT_SOURCES:
            rec["why"] = "source %r: %s" % (src_name, INERT_SOURCES[src_name])
            inert.append(rec)
            continue
        if dest_name in pinned_names:
            s.setModDepth01(dest, src, 0.0, scene=r.getSourceScene(),
                            index=r.getSourceIndex())
            back = s.getModDepth01(dest, src, scene=r.getSourceScene(),
                                   index=r.getSourceIndex())
            raw = _raw_depth_of(s, _param_id(dest), src_name,
                                r.getSourceScene(), r.getSourceIndex())
            if abs(back) > ROUTE_ZERO_EPS or (
                    raw is not None and abs(raw) > ROUTE_ZERO_EPS):
                raise Refuse("modpin_zero readback failed for %s -> %s: "
                             "depth01=%r raw=%r -- the zeroing did not take "
                             "(a non-modulatable destination ignores "
                             "setModDepth01)" % (src_name, dest_name, back,
                                                 raw))
            rec["readback_raw_depth"] = raw
            rec["why"] = ("destination is pinned by the declared fixture "
                          "configuration; depth zeroed (modpin_zero)")
            pinned.append(rec)
            continue
        if dest_name in LIVE_DEST_VOCABULARY:
            rec["why"] = "destination in the declared live vocabulary"
            live.append(rec)
            continue
        matched = None
        for prefix, why in INERT_DEST_PREFIXES:
            if dest_name.startswith(prefix):
                matched = why
                break
        if matched:
            rec["why"] = matched
            inert.append(rec)
            continue
        raise Refuse(
            "modulation route %r -> %r (depth %r) is neither structurally "
            "inert under the declared overrides, nor a parameter this "
            "configuration pins, nor in the declared live destination "
            "vocabulary %s -- REFUSED rather than silently dropped"
            % (src_name, dest_name, r.getDepth(),
               sorted(LIVE_DEST_VOCABULARY)))
    return live, inert, pinned


def probe_cut_activation(surgepy, oc, carrier):
    """A/B probe: does the engine's Sine `applyFilter` actually run?

    `SineOscillator::applyFilter` is guarded by each cut parameter's
    DEACTIVATED flag, which surgepy exposes no getter for and which the
    carriers inherit from a slot that was not a Sine oscillator before the
    override.  Rather than assume either way, render two short notes on
    FRESH engine instances that differ ONLY in the cut value and compare the
    samples: byte-identical output proves the engine never reads the
    parameter, so the biquad is bypassed and the frozen model must bypass
    it too.  Fresh instances are load-bearing -- reusing one instance leaves
    oscillator and biquad state from the first render and the comparison
    becomes meaningless.

    Returns a measured engine fact, recorded in the sidecar, not a declared
    assumption.
    """
    import hashlib

    import numpy as np

    slot = CARRIERS[carrier][1]

    def render(param_index, value):
        s, _d, _r = build_instance(surgepy, oc, carrier)
        try:
            o = s.getPatch()["scene"][0]["osc"][slot]
            s.setParamVal(o["p"][param_index], float(value))
            s.allNotesOff()
            s.processMultiBlock(s.createMultiBlock(32))
            buf = s.createMultiBlock(128)
            s.playNote(0, 36, 100, 0)
            s.processMultiBlock(buf)
            st = np.asarray(buf)
            mono = 0.5 * (st[0] + st[1])
            return hashlib.sha256(
                np.ascontiguousarray(mono).tobytes()).hexdigest()
        finally:
            del s

    out = {}
    for name, idx, a, b in (("lowcut", 3, -60.0, 20.0),
                            ("highcut", 4, 70.0, 0.0)):
        ha, hb = render(idx, a), render(idx, b)
        out[name + "_deactivated"] = (ha == hb)
        out[name + "_probe"] = {"value_a": a, "value_b": b,
                                "sha256_a": ha, "sha256_b": hb}
    return out


def assert_sequence_sources_inert(seq, inert_route_records):
    """Re-check that the sequence cannot wake a DECLARED-INERT source."""
    kinds = {e.get("type") for e in seq.get("events", [])}
    disallowed = kinds - {"note_on", "note_off"}
    if disallowed and any(
            r["src"] in INERT_SOURCES for r in inert_route_records):
        raise Refuse(
            "sequence %r carries non-note events %s while routes from "
            "declared-inert sources exist (%s) -- the inertness declaration "
            "would be false" % (seq.get("id"), sorted(disallowed),
                                sorted({r["src"] for r in inert_route_records
                                        if r["src"] in INERT_SOURCES})))


def apply_overrides(s, slot, force_polymode=None, porta_options=None,
                    porta_value=None, _nc_record_stale=None):
    """Apply the declared overrides, then VERIFY every one by readback.

    Returns `(readback_dict, pinned_parameter_names)`.  The second element is
    the set of engine display names of every parameter this configuration
    pins; `classify_and_pin_routes` uses it to decide which modulation routes
    the `modpin_zero` override must neutralize.

    `force_polymode` / `porta_options` / `porta_value` exist only for the
    declared negative controls and parameter-corner probes; a real carrier
    run passes none of them and the readback records that.

    Precondition (fixture revision 2): `clear_osc_param_routes` has already
    run on this instance.  The post-switch guard REFUSES if any routing into
    the slot's `p[]` parameters still carries a nonzero raw depth.
    `_nc_record_stale` is private to the retained-route negative control
    (`tools/probe_pm_reference_validity.py`): when it is a list, the guard's
    findings are appended to it instead of refusing, so the control can
    render the pre-#329 order and show it FAILS the valid-reference gate.
    No production entry point (`configure_loaded`, `build_instance`, the
    extractor, the reference renderer) passes it.
    """
    import surgepy.constants as C

    applied = {}
    pinned_names = set()

    def setp(p, v):
        try:
            pinned_names.add(p.getName())
        except AttributeError:
            pass
        s.setParamVal(p, float(v))

    # PHASE 0 -- the oscillator TYPE must change first, on its own, and the
    # parameter handles must then be re-fetched.  Changing `ot_*` remaps the
    # slot's seven `p[]` Parameters to a different type's meanings, ranges
    # and DEFAULTS (for a Sine slot: Shape / Feedback / Behavior / Low Cut /
    # High Cut / Unison Detune / Unison Voices, with Behavior defaulting to
    # the MODERN path and Low/High Cut to their off extremes -60 / 70).
    # Handles captured before the type change still report the previous
    # type's metadata, so writing osc params through them would silently
    # clamp against the wrong range.
    patch = s.getPatch()
    sc = patch["scene"][0]
    setp(sc["osc"][slot]["type"], 1.0)                      # ot_sine
    applied["osc_type"] = 1
    s.processMultiBlock(s.createMultiBlock(1))
    patch = s.getPatch()
    sc = patch["scene"][0]
    o = sc["osc"][slot]
    for k in range(7):
        pinned_names.add(o["p"][k].getName())
    stale = stale_osc_param_routes(s, slot)
    if stale:
        if _nc_record_stale is None:
            raise Refuse(
                "osc slot %d p[] routings survived the type switch with "
                "nonzero raw depth %r -- they retarget the Sine slot (#311); "
                "clear_osc_param_routes must run BEFORE the switch "
                "(fixture revision %d)" % (slot, stale, FIXTURE_REVISION))
        _nc_record_stale.extend(stale)

    for key, val in carrier_overrides(slot):
        if key.startswith("mute_"):
            setp(sc[key], 1.0 if val else 0.0)
            applied[key] = 1.0 if val else 0.0
        elif key in ("fu0_off", "fu1_off"):
            idx = 0 if key == "fu0_off" else 1
            setp(sc["filterunit"][idx]["type"], 0.0)
            applied["fu%d_type" % idx] = 0
        elif key == "fx_off":
            for i in range(16):
                setp(patch["fx"][i]["type"], C.fxt_off)
            # the loadFx swap lands at the next control pass (SXT-012
            # dry-bypass): settle one block before any readback
            s.processMultiBlock(s.createMultiBlock(1))
            applied["fx_types"] = [0] * 16
        elif key == "ws_off":
            setp(sc["wsunit"]["type"], 0.0)
            applied["ws_type"] = 0
        elif key == "lc_off":
            setp(sc["lowcut"], -72.0)
            applied["lowcut_scene"] = -72.0
        elif key == "fbc_serial1":
            setp(sc["filterblock_configuration"], 0.0)
            applied["filter_config"] = 0
        elif key == "fm_off":
            setp(sc["fm_switch"], 0.0)
            applied["fm_switch"] = 0
        elif key == "scenemode_single":
            setp(patch["scenemode"], 0.0)
            applied["scenemode"] = 0
        elif key == "retrigger_on":
            setp(o["retrigger"], 1.0)
            applied["retrigger"] = 1.0
        elif key == "drift_zero":
            setp(sc["drift"], 0.0)
            applied["drift"] = 0.0
        elif key == "route_slot_1":
            setp(sc["route_o%d" % (slot + 1)], 1.0)
            applied["route_slot"] = 1
        elif key == "osc_sine":
            pass                            # applied in PHASE 0 above
        elif key == "osc_shape_0":
            setp(o["p"][0], 0.0)
            applied["shape"] = 0
        elif key == "osc_fmmode_legacy":
            setp(o["p"][2], 0.0)
            applied["fmmode"] = 0
        elif key == "osc_unison_1":
            setp(o["p"][6], 1.0)
            applied["unison"] = 1
        elif key == "osc_detune_zero":
            # unison 1 makes detune structurally inert, but the Sine slot's
            # default is 0.1; pinning it to 0 keeps the record unambiguous
            setp(o["p"][5], 0.0)
            applied["unison_detune"] = 0.0
        elif key == "osc_lowcut_off":
            # the Sine slot's Low Cut OFF extreme (-60 == 13.75 Hz); the
            # frozen model builds the near-identity coeff_HP biquad from it,
            # as the landed SXT-040 slice does
            setp(o["p"][3], -60.0)
            applied["lowcut"] = -60.0
        elif key == "osc_highcut_off":
            # the High Cut OFF extreme (70 == 25.09 kHz): near-identity
            # coeff_LP2B
            setp(o["p"][4], 70.0)
            applied["highcut"] = 70.0
        elif key == "osc_octave_0":
            setp(o["octave"], 0.0)
            applied["octave"] = 0
        elif key == "osc_pitch_0":
            setp(o["pitch"], 0.0)
            applied["pitch_param"] = 0.0
        elif key == "osc_keytrack_on":
            setp(o["keytrack"], 1.0)
            applied["keytrack"] = 1.0
        elif key == "scene_pitch_0":
            setp(sc["pitch"], 0.0)
            applied["scene_pitch"] = 0.0
        elif key == "pfg_zero":
            setp(sc["level_pfg"], 0.0)
            applied["level_pfg"] = 0.0
        else:
            raise Refuse("unknown override %r" % key)

    # ---- negative-control / parameter-corner forcing (declared) -------
    # These writes deliberately do NOT register as pinned parameters: the
    # playmode and portamento parameterization are the quantities under
    # test, so a modulation route into them stays classified on its own
    # merits rather than being neutralized by `modpin_zero`.
    if force_polymode is not None:
        s.setParamVal(sc["polymode"], float(force_polymode))
        applied["polymode"] = int(force_polymode)
    if porta_value is not None:
        s.setParamVal(sc["portamento"], float(porta_value))
    if porta_options is not None:
        s.setPortamentoOptions(
            sc["portamento"],
            bool(porta_options.get("constantRate", False)),
            bool(porta_options.get("glissando", False)),
            bool(porta_options.get("retrigger", False)),
            int(porta_options.get("curve", 0)))

    d = read_params(s, slot)
    for k, v in applied.items():
        if k.startswith("mute_"):
            got = d["mutes"][k[5:]]
        else:
            got = d[k]
        if isinstance(v, list):
            if list(got) != v:
                raise Refuse("override readback failed: %s = %r" % (k, got))
        elif abs(float(got) - float(v)) > 1e-6:
            raise Refuse("override readback failed: %s = %r (want %r)"
                         % (k, got, v))
    if porta_value is not None and abs(d["portamento"] - porta_value) > 1e-5:
        raise Refuse("portamento override readback failed: %r"
                     % (d["portamento"],))
    if porta_options is not None:
        for key, want in porta_options.items():
            got = d["portamento_options"][key]
            if int(got) != int(want):
                raise Refuse("portamento option readback failed: %s=%r want %r"
                             % (key, got, want))
    return d, pinned_names


def build_instance(surgepy, oc, carrier, force_polymode=None,
                   porta_options=None, porta_value=None):
    """Fresh engine instance: loadPatch + declared overrides + readback.

    Returns `(synth, readback, routes)` where `routes` is the
    live/inert/pinned classification produced by `classify_and_pin_routes`
    (which also applies the `modpin_zero` override).
    """
    s = surgepy.createSurge(48000.0)
    _rel, slot = CARRIERS[carrier]
    path = preset_abs(oc, carrier)
    if not os.path.exists(path):
        raise Refuse(
            "pinned-engine preset not found at %s -- set ORACLE_SURGE_DIR to "
            "the pinned engine tree (oracle/manifest.json; install the "
            "prebuilt artifact with oracle/fetch-and-build.sh --prebuilt)"
            % path)
    if not s.loadPatch(path):
        raise Refuse("loadPatch failed: %s" % carrier)
    d, routes = configure_loaded(
        s, slot, force_polymode=force_polymode,
        porta_options=porta_options, porta_value=porta_value)
    return s, d, routes


def configure_loaded(s, slot, force_polymode=None, porta_options=None,
                     porta_value=None):
    """The ONE production configuration sequence on a freshly loaded patch.

    Shared by the extractor, the reference renderer, the cut-activation
    probe and the controls (through `build_instance`):

      1. `clear_osc_param_routes`  -- osc-slot p[] routes zeroed by original
         parameter identity, raw/0..1 readback verified (BEFORE the switch);
      2. `apply_overrides`         -- type switch, settle, handle re-fetch,
         post-switch stale-route guard, declared overrides, readback;
      3. `classify_and_pin_routes` -- every remaining route is live, inert
         or pinned, else REFUSE.

    Returns `(readback, routes)`; `routes` carries the live/inert/pinned
    classification plus the `osc_p_route_clear` record (original and
    revised routing state) and the fixture revision.
    """
    clear = clear_osc_param_routes(s, slot)
    d, pinned_names = apply_overrides(
        s, slot, force_polymode=force_polymode,
        porta_options=porta_options, porta_value=porta_value)
    live, inert, pinned = classify_and_pin_routes(s, pinned_names)
    return d, {"fixture_revision": FIXTURE_REVISION,
               "osc_p_route_clear": clear,
               "live": live, "inert": inert, "pinned": pinned}
