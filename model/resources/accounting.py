"""SXT-015 deterministic resource accounting over normalized patch graphs.

Model scope (issue #10 / plan sections 3 and 5):
  - per-scene voice state (osc slots, unison, filters, waveshaper, LFOs),
    with per-preset voice-instance counts derived from scene mode — scene
    modes the model cannot account for are an explicit failure, never a guess;
  - per-INSTANCE effect state (two Delay slots = two instances, each with its
    own history), distinct from shared arithmetic and from supported-type
    counts; routing roles (scene insert / send / global) affect concurrency;
  - memory transactions: per-frame reads/writes per instance, external-writable
    vs on-chip classification (long buffers => external writable; flash is
    never counted as delay/reverb storage), bandwidth at 48 kHz;
  - event timing from the fixture sequence library (parameterized queue);
  - budget closure: complete-patch worst-case cost per output frame vs
    budget(F, Fs, reserve); overflow is an explicit rejection object.

THIS IS A BOOKKEEPING MODEL. Cycle numbers are the named `placeholder-v0`
cost profile so the closure machinery is executable; they establish NO
technology cost (SXT-016) and NO fidelity or preset-quality claim.

Determinism: same graph + same parameters => byte-identical result dict when
dumped with sort_keys=True (ints, floats rounded to 6 decimals, no clocks).
"""
import hashlib
import json
from typing import Dict, List, Optional

from .fx_classes import delay_param_derived_samples, fx_class_spec
from .params import REG

MODEL_VERSION = "sxt-015-accounting/1.0.0"

# surgepy scene-mode ids (src/common/SurgeStorage.h:168-171 sm_single..sm_chsplit)
SM_NAMES = {0: "single", 1: "split", 2: "dual", 3: "chsplit"}


def params_digest() -> str:
    """Stable digest of the parameter set an account was computed with."""
    return hashlib.sha256(
        json.dumps(REG.to_json(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def _r6(x):
    return round(float(x), 6)


def _osc_modulated_slots(scene_index: int, md_scene: Dict) -> set:
    """Osc slots (0-based) reachable as modulation destinations in a scene.

    Destination names carry the engine's own scene prefix ('A Osc 2 Pitch').
    Read live strings from the graph; no name table is copied into this
    repository (schema README mapping notes).
    """
    import re

    pat = re.compile(r"^%s Osc (\d+) " % ("AB"[scene_index],))
    slots = set()
    for bus in ("s", "v"):
        for row in md_scene.get(bus, []):
            m = pat.match(row[4])
            if m:
                slots.add(int(m.group(1)) - 1)
    return slots


def _ws_modulated(scene_index: int, md_scene: Dict) -> bool:
    prefix = "AB"[scene_index]
    for bus in ("s", "v"):
        for row in md_scene.get(bus, []):
            if row[4].startswith(prefix + " ") and "Waveshaper" in row[4]:
                return True
    return False


def _count_modroutes(g: Dict) -> int:
    md = g.get("md", {})
    n = len(md.get("g", []))
    for sc in md.get("s", []):
        n += len(sc.get("s", []))
        n += len(sc.get("v", []))
    return n


def _mseg_or_formula_lfos(scene: Dict) -> List[int]:
    return [i for i, l in enumerate(scene.get("lfo", [])) if "gap" in l]


def account_graph(
    line: Dict,
    fx_instance_limit: Optional[int] = None,
    event_profile: Optional[Dict] = None,
) -> Dict:
    """Account one graphs.jsonl line. Never raises on bad input: failure is
    returned as `status: analysis_failure` with null costs (fail closed)."""
    base = {
        "model_version": MODEL_VERSION,
        "params_digest": params_digest(),
        "cost_profile": REG.cost_profile,
        "path": line.get("p"),
        "sha": line.get("sha"),
        "bank": line.get("b"),
        "limits": {"fx_instances": fx_instance_limit,
                   "voice_pool": REG.voice_pool_limit},
    }
    if line.get("st") != "normalized" or "g" not in line:
        why = line.get("why", {})
        base.update({
            "input_status": "analysis_failure",
            "status": "analysis_failure",
            "anomalies": [{"code": "input_analysis_failure", "detail": why}],
            "rejections": [],
            # fail closed: no default costs are ever produced for a graph
            # that did not normalize
            "scene": None, "voice": None, "fx_instances": None,
            "fx_summary": None, "assets": None, "events": None,
            "memory": None, "budget": None,
        })
        return base

    g = line["g"]
    anomalies: List[Dict] = []
    rejections: List[Dict] = []

    # ------------------------------------------------------------------ scene
    sm = g.get("sm")
    if sm not in SM_NAMES:
        base.update({
            "input_status": "normalized", "status": "analysis_failure",
            "anomalies": [{"code": "scene_mode_unaccountable", "detail": {"sm": sm}}],
            "rejections": [], "scene": None, "voice": None,
            "fx_instances": None, "fx_summary": None, "assets": None,
            "events": None, "memory": None, "budget": None,
        })
        return base
    sa = g.get("sa", 0)
    active_scenes = [sa] if sm == 0 else [0, 1]
    voices_per_note = 2 if sm == 2 else 1
    polylimit = g.get("poly", REG.polylimit_default)
    worst_voices = min(polylimit, REG.voice_pool_limit)
    notes_held_worst = worst_voices // voices_per_note

    scene_accounts = []
    for si in active_scenes:
        sc = g["sc"][si]
        md_scene = g.get("md", {}).get("s", [{}])[si] if si < len(g.get("md", {}).get("s", [])) else {}
        mod_osc = _osc_modulated_slots(si, md_scene)
        osc_slots = []
        unison_load = 0
        for oi, o in enumerate(sc.get("osc", [])):
            uni = o.get("uni", 1)
            uni_eff = max(1, min(uni, REG.max_unison))
            if uni != uni_eff:
                anomalies.append({
                    "code": "unison_out_of_range", "scene": si, "osc": oi,
                    "raw": uni, "effective": uni_eff,
                    "note": "clamped to MAX_UNISON (src/common/globals.h:64); "
                            "raw value outside the engine-declared range",
                })
            mix = sc.get("mix", {}).get("o%d" % (oi + 1), [0, 0, 0, 0])
            muted = bool(mix[1]) or mix[0] == 0
            active = (not muted) or (oi in mod_osc)
            is_wt = bool(o.get("wt"))
            if active:
                unison_load += uni_eff
            osc_slots.append({
                "slot": oi, "type_id": o.get("t"), "type_name": o.get("tn"),
                "muted": muted, "modulated": oi in mod_osc, "active": active,
                "unison": uni_eff if active else 0, "wavetable": is_wt,
            })
        fu = [{"slot": j, "type_id": f.get("t"), "type_name": f.get("tn"),
               "active": f.get("t", 0) != 0}
              for j, f in enumerate(sc.get("fu", []))]
        n_active_fu = sum(1 for f in fu if f["active"])
        ws = sc.get("ws", {})
        ws_active = ws.get("t", 0) != 0 or _ws_modulated(si, md_scene)
        gap_lfos = _mseg_or_formula_lfos(sc)
        for li in gap_lfos:
            anomalies.append({
                "code": "mseg_or_formula_contents_not_exported",
                "scene": si, "lfo": li,
                "note": "SXT-011 exposure gap (schema excluded_fields_note); "
                        "LFO state counted, curve contents unaccounted",
            })
        scene_accounts.append({
            "scene": si,
            "filter_config_id": sc.get("fbc"), "filter_config_name": sc.get("fbcn"),
            # conservative: both units counted when non-Off regardless of the
            # serial/parallel config; exact per-config activation is a
            # SXT-016/023 refinement (QuadFilterChain.cpp A/WS/B selection)
            "osc_slots": osc_slots,
            "active_osc_slots": sum(1 for o in osc_slots if o["active"]),
            "unison_load_per_voice": unison_load,
            "filter_units": fu, "active_filter_units": n_active_fu,
            "waveshaper_active": ws_active, "waveshaper_type": ws.get("tn"),
            "voice_lfos": REG.n_lfos_voice,   # per voice (engine constant)
            "scene_lfos": REG.n_lfos_scene,   # per scene (SLFOs; not exported)
            "mseg_or_formula_lfos": gap_lfos,
        })
    if sm != 0:
        anomalies.append({
            "code": "slfo_defs_not_exported",
            "note": "scene LFO (SLFO) defs are counted at the engine constant "
                    "n_lfos_scene (SurgeStorage.h:75); SXT-011 exports only "
                    "the 6 voice-LFO defs per scene",
        })
    if "audio_input" in g.get("dep", []):
        anomalies.append({
            "code": "audio_input_dependency",
            "note": "preset depends on the external audio input path; "
                    "accounted structurally, not costed (no input fixture)",
        })

    unison_osc_instances_worst = worst_voices * max(
        (s["unison_load_per_voice"] for s in scene_accounts), default=0)
    lfo_instances = (worst_voices * REG.n_lfos_voice
                     + len(active_scenes) * REG.n_lfos_scene)
    env_instances = worst_voices * REG.n_envelopes_per_voice
    wt_active_slots = sum(
        1 for s in scene_accounts for o in s["osc_slots"]
        if o["active"] and o["wavetable"])

    voice_state_bytes = (
        worst_voices * REG.voice_base_state_bytes
        + unison_osc_instances_worst * REG.osc_state_bytes_per_unison
        + worst_voices * max((s["active_filter_units"] for s in scene_accounts),
                             default=0) * REG.filter_unit_state_bytes
        + lfo_instances * REG.lfo_state_bytes
        + wt_active_slots * REG.wt_working_set_bytes
    )
    voice = {
        "scene_mode_id": sm, "scene_mode_name": g.get("smn"),
        "active_scenes": active_scenes, "voices_per_note": voices_per_note,
        "polylimit": polylimit, "worst_case_voices": worst_voices,
        "notes_held_worst_case": notes_held_worst,
        "unison_osc_instances_worst_case": unison_osc_instances_worst,
        "voice_lfo_instances": worst_voices * REG.n_lfos_voice,
        "scene_lfo_instances": len(active_scenes) * REG.n_lfos_scene,
        "lfo_instances_total": lfo_instances,
        "envelope_instances": env_instances,
        "state_bytes_on_chip": voice_state_bytes,
        "scenes": scene_accounts,
        "note": "worst-case voice count is the voice pool bound; dual mode "
                "consumes two pool voices per note (plan section 3)",
    }

    # ------------------------------------------------------------------- FX
    fxd = g.get("fxd", 0)
    fxb = g.get("fxb", 0)
    instances = []
    for slot in g.get("fx", []):
        if not slot.get("on"):
            continue
        i = slot["i"]
        tn = slot.get("tn")
        spec = fx_class_spec(tn)
        for fl in spec["flags"]:
            anomalies.append({
                "code": fl, "slot": i, "fx_class": tn,
                "note": spec["ref"],
            })
        enabled = (fxd >> i) & 1 == 0
        role = slot["r"]
        inactive_role = role.startswith("b") and 1 not in active_scenes
        entry = {
            "slot": i, "role": role, "class": tn, "tier": spec["tier"],
            "enabled_by_fxd": enabled, "processes_this_frame":
                enabled and not inactive_role,
            "routing_inactive": inactive_role,
            "state_bytes": spec["state_bytes"], "external": spec["external"],
            "ext_reads_per_frame": spec["ext_reads"],
            "ext_writes_per_frame": spec["ext_writes"],
            "cycles_per_frame": REG.get(spec["cycle_key"]).value
            if spec["cycle_key"] else 0,
            "flags": list(spec["flags"]),
        }
        if tn in ("Delay", "Floaty Delay"):
            p = slot.get("p", [])
            if len(p) >= 2:
                dl = delay_param_derived_samples(p[0])
                dr = delay_param_derived_samples(p[1])
                entry["param_derived"] = {
                    "time_param_l": p[0], "time_param_r": p[1],
                    "derived_samples_l": dl, "derived_samples_r": dr,
                    "allocated_samples_per_channel": REG.delay_max_length_samples
                    if tn == "Delay" else REG.floaty_delay_max_length_samples,
                    "note": "ESTIMATE-REF: samples = sr*2^(param+margin) per "
                            "sst Delay.h setvars noteToPitch mapping; param "
                            "index mapping and modulatable range need SXT-023 "
                            "confirmation; allocated line is the engine "
                            "constant regardless of set time",
                }
        if "aw" in slot:
            entry["airwindows_algorithm"] = slot["aw"]
        instances.append(entry)

    enabled_instances = [e for e in instances if e["enabled_by_fxd"]]
    processing = [e for e in enabled_instances if e["processes_this_frame"]]
    if fx_instance_limit is not None and len(enabled_instances) > fx_instance_limit:
        rejections.append({
            "code": "fx_instance_overflow",
            "detail": {"enabled_instances": len(enabled_instances),
                       "limit": fx_instance_limit,
                       "slots": [e["slot"] for e in enabled_instances]},
            "note": "instance limit is distinct from supported-type counts "
                    "(plan section 3); overflow is rejected, never squeezed",
        })
    fx_state_ext = sum(e["state_bytes"] for e in instances if e["external"])
    fx_state_onchip = sum(e["state_bytes"] for e in instances if not e["external"])
    fx_summary = {
        "configured_slots": len(instances),
        "enabled_instances": len(enabled_instances),
        "processing_instances": len(processing),
        "distinct_type_count": len({e["class"] for e in instances}),
        "state_bytes_external_writable": fx_state_ext,
        "state_bytes_on_chip": fx_state_onchip,
        "fxb_section_bypass_id": fxb,
        "fxd_disable_mask": fxd,
        "note": "fxb is a loader-level control for every corpus entry "
                "(exporter reset policy, schema README rule 5); per-slot fxd "
                "is honored. Two slots of one type are two instances with "
                "separate state; type count is reported separately",
    }

    # --------------------------------------------------------------- assets
    wta = g.get("wta", [])
    emb_bytes = sum(w.get("emb") or 0 for w in wta)
    unresolved = [w for w in wta if not (w.get("emb") or w.get("res"))]
    if unresolved:
        anomalies.append({
            "code": "asset_bytes_unresolved",
            "detail": {"count": len(unresolved)},
            "note": "wavetable assets with neither embedded size nor resolved "
                    "file record; flash bytes for them are NOT guessed",
        })
    assets = {
        "wavetable_osc_records": len(wta),
        "embedded_flash_bytes": emb_bytes,
        "resolved_records": sum(1 for w in wta if w.get("res")),
        "flash_role": "assets only; flash is never writable delay/reverb "
                      "storage (plan section 3)",
    }

    # --------------------------------------------------------------- events
    ep = event_profile or {
        "max_coincident_events": 8, "peak_events_per_second": 13.333333,
        "source": "fixtures/sequences/ (10 sequence fixtures, SXT-012)",
    }
    depth = REG.event_queue_depth
    if ep["max_coincident_events"] > depth:
        rejections.append({
            "code": "event_queue_overflow",
            "detail": {"max_coincident": ep["max_coincident_events"],
                       "queue_depth": depth},
        })
    events = {
        "queue_depth": depth,
        "max_coincident_events": ep["max_coincident_events"],
        "peak_events_per_second": ep["peak_events_per_second"],
        "worst_case_events_per_frame": min(ep["max_coincident_events"], depth),
        "source": ep["source"],
    }

    # -------------------------------------------------------------- memory
    ext_traffic_words = sum(
        e["ext_reads_per_frame"] + e["ext_writes_per_frame"] for e in processing)
    ext_bytes_per_frame = ext_traffic_words * REG.mem_word_bytes
    bandwidth = ext_bytes_per_frame * REG.sample_rate_hz
    if bandwidth > REG.ext_bandwidth_budget_bytes_per_s:
        rejections.append({
            "code": "ext_bandwidth_overflow",
            "detail": {"required_bytes_per_s": _r6(bandwidth),
                       "budget_bytes_per_s": REG.ext_bandwidth_budget_bytes_per_s},
            "note": "placeholder bandwidth budget; SXT-016 must replace",
        })
    memory = {
        "external_writable_state_bytes":
            fx_state_ext,  # voice state is on-chip; long FX buffers external
        "on_chip_state_bytes": voice_state_bytes + fx_state_onchip,
        "flash_asset_bytes": emb_bytes,
        "ext_traffic_bytes_per_frame": ext_bytes_per_frame,
        "ext_traffic_bytes_per_s": _r6(bandwidth),
        "word_bytes": REG.mem_word_bytes,
        "external_threshold_bytes": REG.external_threshold_bytes,
        "note": "classification: writable class > external_threshold_bytes => "
                "external writable; flash counted as assets only",
    }

    # -------------------------------------------------------------- budget
    voice_cycles = (
        unison_osc_instances_worst * REG.cyc_osc_unison_voice_frame
        + worst_voices * max((s["active_filter_units"] for s in scene_accounts),
                             default=0) * REG.cyc_filter_unit_frame
        + worst_voices * (1 if any(s["waveshaper_active"] for s in scene_accounts)
                          else 0) * REG.cyc_waveshaper_frame
        + lfo_instances * REG.cyc_lfo_frame
        + env_instances * REG.cyc_env_frame
    )
    fx_cycles = sum(e["cycles_per_frame"] for e in processing)
    mod_cycles = _count_modroutes(g) * REG.cyc_modroute_frame
    event_cycles = events["worst_case_events_per_frame"] * REG.cyc_event_frame
    total_cycles = voice_cycles + fx_cycles + mod_cycles + event_cycles
    gross = REG.clock_hz / REG.sample_rate_hz
    dsp_budget = gross * (1 - REG.reserve_fraction)
    if total_cycles > dsp_budget:
        rejections.append({
            "code": "budget_overflow",
            "detail": {"cost_cycles_per_frame": _r6(total_cycles),
                       "dsp_budget_cycles_per_frame": _r6(dsp_budget),
                       "clock_hz": REG.clock_hz,
                       "reserve_fraction": REG.reserve_fraction},
            "note": "plan section 5 closure; cost profile is placeholder-v0 "
                    "(no technology claim)",
        })
    budget = {
        "clock_hz": REG.clock_hz, "sample_rate_hz": REG.sample_rate_hz,
        "gross_cycles_per_frame": _r6(gross),
        "reserve_fraction": REG.reserve_fraction,
        "dsp_budget_cycles_per_frame": _r6(dsp_budget),
        "cost_cycles_per_frame": {
            "voice": _r6(voice_cycles), "fx": _r6(fx_cycles),
            "modulation": _r6(mod_cycles), "events": _r6(event_cycles),
            "total": _r6(total_cycles),
        },
        "utilization_fraction": _r6(total_cycles / gross) if gross else None,
        "closure": "OVERFLOW" if total_cycles > dsp_budget else "within_budget",
    }

    base.update({
        "input_status": "normalized",
        "status": "rejected" if rejections else "fit",
        "scene": {"scene_mode_id": sm, "scene_mode_name": g.get("smn"),
                  "active_scenes": active_scenes},
        "voice": voice, "fx_instances": instances, "fx_summary": fx_summary,
        "assets": assets, "events": events, "memory": memory,
        "budget": budget, "anomalies": anomalies, "rejections": rejections,
    })
    return base
