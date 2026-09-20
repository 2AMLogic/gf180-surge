"""SXT-016 worked bundles: full voice+FX worst-case closure at each clock.

Acceptance computation (issue #11): for the two SXT-015 worked presets
(patches_3rdparty/A.Liv/Keys/July.fxp and
patches_3rdparty/Luna/Leads/96 Osc Supersaw.fxp) plus a synthetic bundle
that is feature-complete for the PROBE-COVERED classes, compute the
complete-patch worst-case cost per output frame at each candidate clock
F in {48, 96, 192, 480} MHz and answer: does a candidate budget close?

Method:
- structure (voice counts, unison instances, active filter units, FX
  processing instances, routing inactivity) comes from THIS repository's
  SXT-015 accounting model (model/resources/accounting.py) run on the
  committed normalized graphs;
- cycle/state values for probe-covered components come from the
  validated probe records in reports/sxt-016/probes/ (pinned-structure
  kernels; worst named pitch corners);
- components no probe covers (waveshaper, LFOs, envelopes, modulation
  rows, Phaser, Chorus, Reverb2, Airwindows) REMAIN at the SXT-015
  placeholder-v0 values and are flagged placeholder_component in every
  row; they make the total an UPPER-BOUNDED mix, not a probe result.
- memory model for the bundle: external lines at E1 (conservative
  worst-wait); E2/E3 alternatives live in the per-kernel records.

Pareto discipline: rows are bundles x multipliers x clocks with
cycles/RAM/bandwidth kept as SEPARATE columns. No single combined score
is computed anywhere (plan section 5).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.resources.accounting import account_graph  # noqa: E402
from model.resources.params import REG  # noqa: E402

from probes.common import (CLOCK_CANDIDATES_HZ, FS_HZ, MEM_WORD_BYTES,
                           TECH, closure, ext_sustained_bytes_per_s)

PROBES_REL = os.path.join("reports", "sxt-016", "probes")
WORKED_REL = os.path.join("reports", "sxt-016", "worked-bundles.json")

WORKED_PRESETS = [
    ("july", "resources/data/patches_3rdparty/A.Liv/Keys/July.fxp"),
    ("supersaw",
     "resources/data/patches_3rdparty/Luna/Leads/96 Osc Supersaw.fxp"),
]

# Probe kernels used per component (pinned-structure kernels).
OSC_KERNEL = {"Classic": "classic_blit",
              "Sine": "sine_poly_fastmath",
              "Wavetable": "wavetable_blit"}
FILTER_KERNEL_DEFAULT = "svf_tdf2_block_coeffs"
FILTER_KERNEL_K35 = "k35_ladder_tanh_lut"
FX_KERNEL = {"Delay": "delay_stereo_ext_E1",
             "Floaty Delay": "delay_stereo_ext_E1",
             "EQ": "eq3band_tdf2_block_coeffs",
             "Reverb 1": "reverb1_composite_ext_E1"}
PLACEHOLDER_FX_CYCLE_KEY = {
    "Phaser": "cyc_fxgeneric_frame",
    "Chorus": "cyc_fxchorus_frame",
    "Reverb 2": "cyc_fxreverb2_frame",
    "Airwindows": "cyc_fxgeneric_frame",
    "Flanger": "cyc_fxflanger_frame",
    "Rotary": "cyc_fxgeneric_frame",
}

NOMINAL_PHASE_BITS = 24


def load_probe_records(probes_dir=PROBES_REL):
    idx = {}
    for fn in sorted(os.listdir(probes_dir)):
        if not fn.endswith(".json"):
            continue
        rec = json.load(open(os.path.join(probes_dir, fn)))
        key = (rec["probe"], rec["kernel"],
               rec["word_lengths"].get("multiplier"))
        idx[key] = rec
    return idx


def _rec(idx, probe, kernel, mult):
    r = idx.get((probe, kernel, mult))
    if r is None:
        raise KeyError("missing probe record %s/%s/%s" % (probe, kernel, mult))
    return r


def load_worked_lines():
    lines = {}
    with open(os.path.join("corpus", "normalized", "graphs.jsonl")) as f:
        for raw in f:
            d = json.loads(raw)
            for name, path in WORKED_PRESETS:
                if d.get("p") == path:
                    lines[name] = d
    missing = [n for n, _ in WORKED_PRESETS if n not in lines]
    if missing:
        raise RuntimeError("worked presets not found in graphs.jsonl: %s"
                           % missing)
    return lines


def osc_state_bits(rec):
    """Per-instance + per-slot-shared state for an osc probe record."""
    extra = rec
    pu = (extra.get("state_bits_per_unison_instance")
          or extra.get("state_bits_per_instance")
          or extra.get("state_bits_detail") or {})
    shared = extra.get("state_bits_per_osc_slot_shared") or {}
    table = extra.get("onchip_table_working_set_bits", 0)
    return sum(pu.values()), sum(shared.values()), table


def build_bundle(name, line, idx, mult, fx_instance_limit=4):
    acc = account_graph(line, fx_instance_limit=fx_instance_limit)
    if acc["status"] == "analysis_failure":
        return {"bundle": name, "status": "analysis_failure"}
    g = line["g"]
    voice = acc["voice"]
    worst_voices = voice["worst_case_voices"]

    components = []
    flags = []

    # --- oscillators (probe-covered) ---
    osc_cycles = 0
    osc_ram = 0
    for scene_si in voice["scenes"]:
        for slot in scene_si["osc_slots"]:
            if not slot["active"]:
                continue
            type_name = slot["type_name"]
            kernel = OSC_KERNEL.get(type_name)
            if kernel is None:
                # uncovered osc family: not in any worked preset, but keep
                # the bundle honest if it appears
                flags.append("osc_family_uncovered:%s" % type_name)
                continue
            rec = _rec(idx, "probe_osc", kernel, mult)
            cps = rec["cycles_per_sample"]
            n = worst_voices * slot["unison"]
            osc_cycles += n * cps
            pu, shared, table = osc_state_bits(rec)
            osc_ram += n * pu + shared + table
            components.append({
                "component": "osc:%s scene%d slot%d uni%d" % (
                    type_name, scene_si["scene"], slot["slot"], slot["unison"]),
                "instances": n,
                "cycles_per_frame": round(n * cps, 1),
                "source": "probe_osc/%s" % kernel,
                "state_ram_bits": n * pu + shared + table,
            })
    osc_cycles = round(osc_cycles, 1)

    # --- filter units (probe-covered; mapping flagged) ---
    filt_cycles = 0
    filt_ram = 0
    max_fu = max((s["active_filter_units"] for s in voice["scenes"]),
                 default=0)
    for scene_si in voice["scenes"]:
        for fu in scene_si["filter_units"]:
            if not fu["active"]:
                continue
            kernel = FILTER_KERNEL_K35 if fu["type_name"] == "LP K35" \
                else FILTER_KERNEL_DEFAULT
            if fu["type_name"] != "LP K35":
                flags.append("filter_mapping_generic:%s" % fu["type_name"])
            rec = _rec(idx, "probe_filter", kernel, mult)
            cps = rec["cycles_per_sample"]
            n = worst_voices
            filt_cycles += n * cps
            filt_ram += n * rec["state_ram_bits"]
            components.append({
                "component": "filter:scene%d unit%d %s" % (
                    scene_si["scene"], fu["slot"], fu["type_name"]),
                "instances": n,
                "cycles_per_frame": round(n * cps, 1),
                "source": "probe_filter/%s" % kernel,
                "state_ram_bits": n * rec["state_ram_bits"],
            })
    filt_cycles = round(filt_cycles, 1)

    # --- waveshaper (NOT probe-covered) ---
    ws_cycles = 0
    if any(s["waveshaper_active"] for s in voice["scenes"]):
        ws_cycles = worst_voices * REG.get("cyc_waveshaper_frame").value
        flags.append("placeholder_component:cyc_waveshaper_frame")
        components.append({
            "component": "waveshaper (active voices)",
            "instances": worst_voices,
            "cycles_per_frame": ws_cycles,
            "source": "SXT-015 placeholder-v0 cyc_waveshaper_frame",
            "placeholder_component": True,
        })

    # --- LFOs / envelopes / modulation rows (NOT probe-covered) ---
    lfo_n = voice["lfo_instances_total"]
    env_n = voice["envelope_instances"]
    lfo_cycles = lfo_n * REG.get("cyc_lfo_frame").value
    env_cycles = env_n * REG.get("cyc_env_frame").value
    flags.append("placeholder_component:cyc_lfo_frame")
    flags.append("placeholder_component:cyc_env_frame")
    components.append({
        "component": "LFO instances", "instances": lfo_n,
        "cycles_per_frame": lfo_cycles,
        "source": "SXT-015 placeholder-v0 cyc_lfo_frame",
        "placeholder_component": True})
    components.append({
        "component": "envelope instances", "instances": env_n,
        "cycles_per_frame": env_cycles,
        "source": "SXT-015 placeholder-v0 cyc_env_frame",
        "placeholder_component": True})
    n_mod = 0
    md = g.get("md", {})
    n_mod += len(md.get("g", []))
    for sc in md.get("s", []):
        n_mod += len(sc.get("s", []))
        n_mod += len(sc.get("v", []))
    mod_cycles = n_mod * REG.get("cyc_modroute_frame").value
    flags.append("placeholder_component:cyc_modroute_frame")
    components.append({
        "component": "modulation routing rows", "instances": n_mod,
        "cycles_per_frame": mod_cycles,
        "source": "SXT-015 placeholder-v0 cyc_modroute_frame",
        "placeholder_component": True})

    # --- FX instances (probe-covered where a probe exists) ---
    fx_cycles = 0
    fx_ext_bytes = 0
    fx_ram_bits = 0
    n_rejections = []
    for inst in acc["fx_instances"]:
        if not inst["processes_this_frame"]:
            components.append({
                "component": "fx:slot%d %s (routing-inactive; state "
                             "retained, not processed)" % (inst["slot"],
                                                           inst["class"]),
                "instances": 1, "cycles_per_frame": 0,
                "source": "SXT-015 routing model",
                "state_ram_bits": inst["state_bytes"] * 8,
            })
            fx_ram_bits += inst["state_bytes"] * 8
            continue
        kernel = FX_KERNEL.get(inst["class"])
        if kernel is not None:
            rec = _rec(idx, "probe_fx_" + _fx_probe_name(inst["class"]),
                       kernel, mult)
            cpf = rec["cycles_per_frame"]
            fx_cycles += cpf
            fx_ext_bytes += rec["ext_bytes_per_frame"]
            fx_ram_bits += rec["state_ram_bits"]
            components.append({
                "component": "fx:slot%d %s" % (inst["slot"], inst["class"]),
                "instances": 1,
                "cycles_per_frame": cpf,
                "source": "%s/%s" % (rec["probe"], kernel),
                "state_ram_bits": rec["state_ram_bits"],
                "ext_bytes_per_frame": rec["ext_bytes_per_frame"],
            })
        else:
            key = PLACEHOLDER_FX_CYCLE_KEY.get(inst["class"],
                                               "cyc_fxgeneric_frame")
            cpf = REG.get(key).value
            fx_cycles += cpf
            fx_ext_bytes += (inst["ext_reads_per_frame"]
                             + inst["ext_writes_per_frame"]) * MEM_WORD_BYTES
            fx_ram_bits += inst["state_bytes"] * 8
            flags.append("placeholder_component:%s(%s)" % (key,
                                                           inst["class"]))
            components.append({
                "component": "fx:slot%d %s" % (inst["slot"], inst["class"]),
                "instances": 1,
                "cycles_per_frame": cpf,
                "source": "SXT-015 placeholder-v0 " + key,
                "placeholder_component": True,
                "state_ram_bits": inst["state_bytes"] * 8,
                "ext_bytes_per_frame": (inst["ext_reads_per_frame"]
                                        + inst["ext_writes_per_frame"])
                * MEM_WORD_BYTES,
            })
    if acc["rejections"]:
        n_rejections = [r["code"] for r in acc["rejections"]]
    fx_cycles = round(fx_cycles, 1)

    # --- scheduler (probe-covered) ---
    sched = _rec(idx, "probe_scheduler", "event_queue_and_control", mult)
    sched_cycles = sched["cycles_per_frame"]
    control = sched["control_cycles_per_frame"]
    transfer = sched["transfer_cycles_per_frame"]
    contention = sched["contention_cycles_per_frame"]
    events_n = sched["max_coincident_events_per_frame"]
    components.append({
        "component": "scheduler (control + worst %d events)" % events_n,
        "cycles_per_frame": sched_cycles,
        "source": "probe_scheduler/event_queue_and_control",
    })

    total = round(osc_cycles + filt_cycles + ws_cycles + lfo_cycles
                  + env_cycles + mod_cycles + fx_cycles + sched_cycles, 1)

    voice_ram_bits = (worst_voices * REG.get("voice_base_state_bytes").value
                      * 8 + lfo_n * REG.get("lfo_state_bytes").value * 8)
    flags.append("placeholder_component:voice_base_state_bytes")
    flags.append("placeholder_component:lfo_state_bytes")
    ram_bits = voice_ram_bits + osc_ram + filt_ram + fx_ram_bits \
        + sched["state_ram_bits"]

    closure_at = {}
    for c in CLOCK_CANDIDATES_HZ:
        cl = closure(c, total, control=0, transfer=transfer,
                     contention=contention)
        # scheduler control is already inside sched_cycles; transfer and
        # contention are subtracted from gross here
        cl["sustained_ext_bytes_per_s_E1"] = \
            ext_sustained_bytes_per_s(c, "E1")
        cl["ext_bandwidth_fit"] = (
            "within" if fx_ext_bytes * FS_HZ
            <= cl["sustained_ext_bytes_per_s_E1"] else "EXCEEDS")
        closure_at[c] = cl

    return {
        "bundle": name,
        "preset_path": line.get("p"),
        "preset_sha": line.get("sha"),
        "multiplier": mult,
        "fx_instance_limit": fx_instance_limit,
        "worst_case_voices": worst_voices,
        "scene_mode": voice["scene_mode_name"],
        "components": components,
        "totals": {
            "osc_cycles_per_frame": osc_cycles,
            "filter_cycles_per_frame": filt_cycles,
            "waveshaper_cycles_per_frame": ws_cycles,
            "lfo_cycles_per_frame": lfo_cycles,
            "env_cycles_per_frame": env_cycles,
            "modroute_cycles_per_frame": mod_cycles,
            "fx_cycles_per_frame": fx_cycles,
            "scheduler_cycles_per_frame": sched_cycles,
            "total_cycles_per_frame": total,
        },
        "state_ram_bits_total": ram_bits,
        "ext_bytes_per_frame": fx_ext_bytes,
        "ext_bytes_per_s_at_48k": fx_ext_bytes * FS_HZ,
        "closure_at_clocks": closure_at,
        "flags": sorted(set(flags)),
        "sxt015_rejections": n_rejections,
        "placeholder_policy_note": "components flagged placeholder_component "
                                   "remain at SXT-015 placeholder-v0 values; "
                                   "totals are a mix of probe-replaced and "
                                   "placeholder components, so closure "
                                   "verdicts are UPPER-BOUNDED estimates, "
                                   "never measurements",
    }


def _fx_probe_name(cls):
    return {"Delay": "delay", "Floaty Delay": "delay", "EQ": "eq",
            "Reverb 1": "reverb1"}[cls]


def build_covered_worst(idx, mult):
    """Synthetic bundle feature-complete for probe-covered classes:
    16 voice pool, 3 Classic slots x unison 16 per voice (like 96 Osc
    Supersaw), 2 K35 filter units per voice, FX = Delay + Delay (two
    slots, two histories) + EQ + Reverb 1 (4-instance budget), worst
    event burst. Every cycle component is probe-covered."""
    worst_voices = 16
    components = []
    rec_c = _rec(idx, "probe_osc", "classic_blit", mult)
    cps = rec_c["cycles_per_sample"]
    n = worst_voices * 3 * 16
    osc_cycles = round(n * cps, 1)
    pu, shared, _ = osc_state_bits(rec_c)
    osc_ram = n * pu + 3 * shared
    components.append({
        "component": "osc:Classic x3 slots uni16 (worst pitch corner)",
        "instances": n, "cycles_per_frame": osc_cycles,
        "source": "probe_osc/classic_blit",
        "state_ram_bits": osc_ram})
    rec_f = _rec(idx, "probe_filter", FILTER_KERNEL_K35, mult)
    filt_cycles = round(worst_voices * 2 * rec_f["cycles_per_sample"], 1)
    filt_ram = worst_voices * 2 * rec_f["state_ram_bits"]
    components.append({
        "component": "filter:K35 x2 units", "instances": worst_voices * 2,
        "cycles_per_frame": filt_cycles,
        "source": "probe_filter/" + FILTER_KERNEL_K35,
        "state_ram_bits": filt_ram})
    fx_cycles = 0
    fx_ext = 0
    fx_ram = 0
    for cls, kernel in (("Delay", "delay_stereo_ext_E1"),
                        ("Delay(2nd slot)", "delay_stereo_ext_E1"),
                        ("EQ", "eq3band_tdf2_block_coeffs"),
                        ("Reverb 1", "reverb1_composite_ext_E1")):
        rec = _rec(idx, "probe_fx_" + _fx_probe_name(cls.split("(")[0]),
                   kernel, mult)
        fx_cycles += rec["cycles_per_frame"]
        fx_ext += rec["ext_bytes_per_frame"]
        fx_ram += rec["state_ram_bits"]
        components.append({
            "component": "fx:" + cls, "instances": 1,
            "cycles_per_frame": rec["cycles_per_frame"],
            "source": rec["probe"] + "/" + kernel,
            "state_ram_bits": rec["state_ram_bits"],
            "ext_bytes_per_frame": rec["ext_bytes_per_frame"]})
    sched = _rec(idx, "probe_scheduler", "event_queue_and_control", mult)
    sched_cycles = sched["cycles_per_frame"]
    components.append({
        "component": "scheduler (control + worst 8 events)",
        "cycles_per_frame": sched_cycles,
        "source": "probe_scheduler/event_queue_and_control"})
    total = round(osc_cycles + filt_cycles + fx_cycles + sched_cycles, 1)
    closure_at = {}
    for c in CLOCK_CANDIDATES_HZ:
        cl = closure(c, total, control=0,
                     transfer=sched["transfer_cycles_per_frame"],
                     contention=sched["contention_cycles_per_frame"])
        cl["sustained_ext_bytes_per_s_E1"] = \
            ext_sustained_bytes_per_s(c, "E1")
        cl["ext_bandwidth_fit"] = (
            "within" if fx_ext * FS_HZ
            <= cl["sustained_ext_bytes_per_s_E1"] else "EXCEEDS")
        closure_at[c] = cl
    return {
        "bundle": "covered_worst_synth",
        "preset_path": None,
        "description": "synthetic bundle, feature-complete for the "
                       "probe-covered classes: 16 voices x (3 Classic "
                       "slots x uni16), 2 K35 units/voice, FX = 2x Delay "
                       "(separate states) + EQ + Reverb1, worst event "
                       "burst; NO placeholder components",
        "multiplier": mult,
        "components": components,
        "totals": {
            "osc_cycles_per_frame": osc_cycles,
            "filter_cycles_per_frame": filt_cycles,
            "waveshaper_cycles_per_frame": 0,
            "lfo_cycles_per_frame": 0,
            "env_cycles_per_frame": 0,
            "modroute_cycles_per_frame": 0,
            "fx_cycles_per_frame": round(fx_cycles, 1),
            "scheduler_cycles_per_frame": sched_cycles,
            "total_cycles_per_frame": total,
        },
        "state_ram_bits_total": osc_ram + filt_ram + fx_ram
        + sched["state_ram_bits"],
        "ext_bytes_per_frame": fx_ext,
        "ext_bytes_per_s_at_48k": fx_ext * FS_HZ,
        "closure_at_clocks": closure_at,
        "flags": [],
        "sxt015_rejections": [],
        "placeholder_policy_note": "no placeholder components: every cycle "
                                   "in this row comes from a validated "
                                   "SXT-016 probe record",
    }


def run(probes_dir=PROBES_REL, out=WORKED_REL):
    idx = load_probe_records(probes_dir)
    lines = load_worked_lines()
    bundles = []
    for name, _ in WORKED_PRESETS:
        for mult in ("M18", "M32"):
            bundles.append(build_bundle(name, lines[name], idx, mult))
    for mult in ("M18", "M32"):
        bundles.append(build_covered_worst(idx, mult))
    doc = {
        "issue": "SXT-016 (issue #11) worked bundles",
        "clocks_hz": CLOCK_CANDIDATES_HZ,
        "sample_rate_hz": FS_HZ,
        "memory_model": "external lines at E1 (conservative); see probe "
                        "records for E2/E3",
        "pareto_note": "alternatives kept uncombined: rows are bundles x "
                       "multipliers; cycles, RAM bits, and external bytes "
                       "are separate columns; no single score is computed",
        "bundles": bundles,
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, sort_keys=True, indent=1)
        f.write("\n")
    return doc


def markdown_table(doc):
    """Pareto-style summary table (rows uncombined, no single score)."""
    out = []
    out.append("| Bundle | xMult | total cyc/frame | @48M | @96M | @192M "
               "| @480M | RAM bits | ext B/frame |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for b in doc["bundles"]:
        cells = []
        for c in CLOCK_CANDIDATES_HZ:
            cl = b["closure_at_clocks"][c]
            cells.append("%s (%.0f%%)" % (
                "PASS" if cl["closure"] == "within_budget" else "OVERFLOW",
                100.0 * cl["cost_cycles_per_frame"]
                / cl["gross_cycles_per_frame"]))
        out.append("| %s | %s | %.0f | %s | %s | %s | %s | %d | %d |" % (
            b["bundle"], b["multiplier"],
            b["totals"]["total_cycles_per_frame"], *cells,
            b["state_ram_bits_total"], b["ext_bytes_per_frame"]))
    return "\n".join(out)


if __name__ == "__main__":
    doc = run()
    print(markdown_table(doc))
