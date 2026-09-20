#!/usr/bin/env python3
"""SXT-013 apparatus: deterministic candidate-pool builder for listening slates.

Reads corpus/normalized/graphs.jsonl (SXT-011 normalized graphs, pinned native
loader) and proposes listening candidate slates for the favorites selection
(issue #8 / SXT-013):

  - a 256-preset slate and a 32-preset pilot slate (pilot is a subset of the
    256) per quota profile,
  - category quotas across basses / leads / keys / plucks / pads / rhythmic /
    textures from BOTH banks (explicit per profile),
  - greedy marginal-coverage selection over normalized-graph diversity tokens
    (oscillator families, FX presence incl. Reverb 1 / Reverb 2 / Airwindows,
    scene modes, unison, filters, waveshapers, modulators, assets),
  - no popularity signal of any kind exists in the inputs and none is used;
    contributor-author caps limit same-author concentration,
  - per-candidate census blob SHA-1 + reasons; per-run summary with quota
    accounting and explicit exclusions.

INTEGRITY: every graphs.jsonl line is cross-checked against the static census
per-preset.csv (path -> git blob SHA-1 + size). A missing or mismatched census
hash REFUSES the run (exit 2) with the offending entries listed. This tool
never repairs, rescores, or silently drops an entry.

HONESTY: the slates are PROPOSALS for human listening selection. Nothing here
freezes a favorites set, and no output of this tool is a support, fidelity, or
quality claim (static normalized data only; see corpus/normalized/README.md).

Deterministic: same inputs -> byte-identical outputs (sorted iteration, no
clock, no randomness, fixed float formatting). Python 3 standard library only.
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPHS = REPO_ROOT / "corpus" / "normalized" / "graphs.jsonl"
DEFAULT_CENSUS_CSV = REPO_ROOT / "corpus" / "census-v0.1" / "results" / "per-preset.csv"

SCHEMA_VERSION = "sxt-013-candidate-slate/1.0.0"
ISSUE = "SXT-013"

# Plan section 2 categories -> census directory names (factory + contributor).
# Conservative, explicit mapping; directories not listed are outside the quota
# system and are reported in the run summary (never silently dropped).
CATEGORY_DIRS = {
    "basses": {"Basses", "Bass"},
    "leads": {"Leads"},
    "keys": {"Keys", "Bells", "Mallets", "Organs", "Chords"},
    "plucks": {"Plucks"},
    "pads": {"Pads"},
    "rhythmic": {"Rhythms", "Sequences", "Arps", "Drums", "Percussion"},
    "textures": {"Textures", "Soundscapes", "Ambiance", "Ambiances",
                 "Atmospheres", "Drones"},
}
CATEGORY_ORDER = ["basses", "leads", "keys", "plucks", "pads", "rhythmic",
                  "textures"]
# Fixed per-category fill order (bank processed first gets the strongest
# coverage picks inside its target share; documented in each profile).
BANK_FILL_ORDER = ["factory", "contributor"]

# Unison values far above the engine's 16-voice UI range occur on some legacy
# parameters; they are clamped for bucketing and counted as anomalies.
UNISON_CLAMP = 16

PROFILES = {
    "balanced": {
        "description": (
            "Equal-footing categories with a 25% minority-bank floor per "
            "category (availability permitting) and a global factory floor of "
            "64/256. Proposed default; the human chooser may pick a different "
            "profile."
        ),
        "slate_total": 256,
        "slate_quotas": {"basses": 40, "leads": 40, "keys": 34, "plucks": 32,
                         "pads": 36, "rhythmic": 38, "textures": 36},
        "bank_min_fraction": 0.25,
        "global_factory_floor": 64,
        "global_factory_cap": None,
        "author_cap": 8,
        "pilot_total": 32,
        "pilot_quotas": {"basses": 5, "leads": 5, "keys": 4, "plucks": 4,
                         "pads": 5, "rhythmic": 5, "textures": 4},
        "pilot_bank_min_fraction": 0.25,
        "pilot_global_factory_floor": 8,
        "pilot_author_cap": 2,
    },
    "factory-lean": {
        "description": (
            "Same category totals, but the factory (bundled) bank is targeted "
            "at >=50% of every category and >=128/256 globally, subject to "
            "factory availability (factory has no textures directory, so the "
            "textures quota is necessarily all-contributor)."
        ),
        "slate_total": 256,
        "slate_quotas": {"basses": 40, "leads": 40, "keys": 34, "plucks": 32,
                         "pads": 36, "rhythmic": 38, "textures": 36},
        "bank_min_fraction": 0.5,
        "global_factory_floor": 128,
        "global_factory_cap": None,
        "author_cap": 8,
        "pilot_total": 32,
        "pilot_quotas": {"basses": 5, "leads": 5, "keys": 4, "plucks": 4,
                         "pads": 5, "rhythmic": 5, "textures": 4},
        "pilot_bank_min_fraction": 0.5,
        "pilot_global_factory_floor": 12,
        "pilot_author_cap": 2,
    },
    "contributor-lean": {
        "description": (
            "Same category totals, no per-category bank floor, and factory "
            "held at exactly 48/256 (approximately the factory share of the "
            "corpus, 641/3561, >= the issue's both-banks requirement): "
            "maximum weight on the contributor bank."
        ),
        "slate_total": 256,
        "slate_quotas": {"basses": 40, "leads": 40, "keys": 34, "plucks": 32,
                         "pads": 36, "rhythmic": 38, "textures": 36},
        "bank_min_fraction": 0.0,
        "global_factory_floor": 48,
        "global_factory_cap": 48,
        "author_cap": 8,
        "pilot_total": 32,
        "pilot_quotas": {"basses": 5, "leads": 5, "keys": 4, "plucks": 4,
                         "pads": 5, "rhythmic": 5, "textures": 4},
        "pilot_bank_min_fraction": 0.0,
        "pilot_global_factory_floor": 6,
        "pilot_author_cap": 2,
    },
}


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_census(census_csv):
    """path -> {blob, size, bank}; refuses on missing columns/duplicates."""
    by_path = {}
    with open(census_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for col in ("path", "git_blob_sha1", "size", "bank"):
            if col not in (reader.fieldnames or []):
                raise Refuse(f"census per-preset.csv missing column {col!r}")
        for row in reader:
            path = row["path"]
            if path in by_path:
                raise Refuse(f"census per-preset.csv duplicate path: {path}")
            by_path[path] = {
                "blob": row["git_blob_sha1"],
                "size": int(row["size"]),
                "bank": row["bank"],
            }
    if not by_path:
        raise Refuse("census per-preset.csv has no data rows")
    return by_path


def load_graphs(graphs_jsonl, census):
    """Parse graphs.jsonl with census-hash integrity checks.

    Returns (entries, integrity) where entries carry the parsed line plus the
    category/bank/dir decomposition. Raises Refuse on any census-hash mismatch
    or path-set divergence (tamper, partial file, stale export).
    """
    entries = []
    violations = []
    with open(graphs_jsonl, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                violations.append(f"graphs.jsonl:{lineno}: empty line")
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                violations.append(f"graphs.jsonl:{lineno}: not JSON: {exc}")
                continue
            path = d.get("p")
            if not path:
                violations.append(f"graphs.jsonl:{lineno}: missing 'p'")
                continue
            cen = census.get(path)
            if cen is None:
                violations.append(
                    f"graphs.jsonl:{lineno}: path not in census: {path}")
                continue
            if d.get("sha") != cen["blob"]:
                violations.append(
                    f"graphs.jsonl:{lineno}: census blob mismatch for {path}: "
                    f"graphs sha {d.get('sha')!r} != census {cen['blob']!r}")
                continue
            if d.get("sz") != cen["size"]:
                violations.append(
                    f"graphs.jsonl:{lineno}: census size mismatch for {path}: "
                    f"graphs {d.get('sz')!r} != census {cen['size']!r}")
                continue
            bank = d.get("b")
            if bank != cen["bank"]:
                violations.append(
                    f"graphs.jsonl:{lineno}: bank disagreement for {path}: "
                    f"graphs {bank!r} != census {cen['bank']!r}")
                continue
            parts = path.split("/")
            # resources/data/patches_factory/<Dir>/Name.fxp
            # resources/data/patches_3rdparty/<Author>/<Dir>/Name.fxp
            if bank == "factory":
                directory = parts[3] if len(parts) >= 5 else "(root)"
                author = "(factory)"
            else:
                directory = parts[4] if len(parts) >= 6 else "(root)"
                author = parts[3] if len(parts) >= 6 else "(root)"
            entries.append({
                "path": path,
                "bank": bank,
                "sha": d["sha"],
                "size": d["sz"],
                "status": d.get("st"),
                "why": d.get("why"),
                "graph": d.get("g"),
                "engine_pin": (d.get("pin") or {}).get("e"),
                "rev": d.get("rev"),
                "directory": directory,
                "author": author,
                "category": category_for(directory),
            })
    graph_paths = {e["path"] for e in entries}
    census_paths = set(census)
    missing = sorted(census_paths - graph_paths)
    if missing:
        violations.append(
            f"{len(missing)} census paths have no graphs.jsonl line, "
            f"first: {missing[0]}")
    if violations:
        detail = "\n".join(f"  - {v}" for v in violations[:25])
        more = ("\n  - ... "
                f"{len(violations) - 25} more" if len(violations) > 25 else "")
        raise Refuse(
            f"census-hash integrity check FAILED ({len(violations)} "
            f"violation(s)); refusing to build slates:\n{detail}{more}")
    return entries


def category_for(directory):
    for cat, dirs in CATEGORY_DIRS.items():
        if directory in dirs:
            return cat
    return None


def active_scenes(graph):
    """Scene indices audible under the preset's scene mode."""
    sm = graph.get("sm", 0)
    sa = graph.get("sa", 0)
    return [0, 1] if sm in (1, 2, 3) else [sa]


def clamp_unison(v):
    return max(0, min(int(v), UNISON_CLAMP))


def graph_features(graph):
    """Diversity tokens from the normalized graph (deterministic order).

    Tokens cover: audible oscillator families, unison buckets, wavetable
    assets, audio-input dependency, FM/ring/noise paths, filter units +
    topology, waveshaper, scene/play modes, character, LFO shapes (incl.
    MSEG/Formula gap markers), FX types (incl. exact 'Reverb 1', 'Reverb 2',
    'Airwindows' presence and per-algorithm Airwindows ids), send usage, and
    a modulation-routing-count bucket. Presence-only: no parameter values.
    """
    tokens = set()
    act = active_scenes(graph)
    max_uni_raw = 0
    for si in act:
        sc = graph["sc"][si]
        mix = sc.get("mix", {})
        for oi, osc in enumerate(sc.get("osc", [])):
            m = mix.get(f"o{oi + 1}", [1, 0, 0, 0])
            level, mute = m[0], m[1]
            if level == 0 or mute == 1:
                continue
            tokens.add(f"osc:{osc['tn']}")
            uni = osc.get("uni", 0)
            if uni:
                max_uni_raw = max(max_uni_raw, int(uni))
                u = clamp_unison(uni)
                if u >= 8:
                    tokens.add("unison:8+")
                elif u >= 4:
                    tokens.add("unison:4-7")
                elif u >= 2:
                    tokens.add("unison:2-3")
        for ring in ("ring_12", "ring_23"):
            m = mix.get(ring, [0, 1, 0, 0])
            if m[0] != 0 and m[1] != 1:
                tokens.add(f"path:{ring}")
        m = mix.get("noise", [0, 1, 0, 0])
        if m[0] != 0 and m[1] != 1:
            tokens.add("path:noise")
        fm = sc.get("fm") or {}
        if fm.get("sw", 0):
            tokens.add("path:fm")
        tokens.add(f"fbc:{sc.get('fbcn')}")
        tokens.add(f"pm:{sc.get('pmn')}")
        for fu in sc.get("fu", []):
            if fu.get("t", 0) != 0:
                tokens.add(f"flt:{fu['tn']}")
        ws = sc.get("ws") or {}
        if ws.get("t", 0) != 0:
            tokens.add(f"ws:{ws.get('tn')}")
        for lfo in sc.get("lfo", []):
            if lfo.get("mag", 0) != 0 and lfo.get("shn"):
                tokens.add(f"lfo:{lfo['shn']}")
        if any(l > 0 for l in sc.get("send", []) or []):
            tokens.add("fxpath:send")
    tokens.add(f"sm:{graph.get('smn')}")
    tokens.add(f"char:{graph.get('chn')}")
    for wta in graph.get("wta", []) or []:
        tokens.add("asset:wavetable")
        if wta.get("emb"):
            tokens.add("asset:wt_embedded")
        if wta.get("res"):
            tokens.add("asset:wt_resolved")
    md = graph.get("md") or {}
    n_routes = len(md.get("g", [])) + sum(
        len(s.get("s", [])) + len(s.get("v", [])) for s in md.get("s", []))
    tokens.add("modroutes:0" if n_routes == 0 else
               "modroutes:1-5" if n_routes <= 5 else
               "modroutes:6-15" if n_routes <= 15 else "modroutes:16+")
    for fx in graph.get("fx", []):
        if fx.get("on", 0) != 1:
            continue
        tokens.add(f"fx:{fx['tn']}")
        tokens.add(f"fxrole:{fx['r']}")
        if fx.get("awn"):
            tokens.add(f"fxaw:{fx['awn']}")
    return tokens, max_uni_raw


def build_pool(entries):
    """Eligible candidate pool + recorded exclusions (nothing silent)."""
    pool = []
    exclusions = defaultdict(list)
    anomalies = []
    for e in entries:
        if e["status"] != "normalized":
            exclusions["analysis_failure"].append(e["path"])
            continue
        if e["category"] is None:
            exclusions["directory_outside_quota_categories"].append(e["path"])
        if not e["graph"]:
            exclusions["missing_graph"].append(e["path"])
            continue
        tokens, uni_raw = graph_features(e["graph"])
        if uni_raw > UNISON_CLAMP:
            anomalies.append({"path": e["path"], "field": "unison",
                              "value": uni_raw,
                              "handling": f"clamped to {UNISON_CLAMP} for "
                                          "bucketing"})
        if "audio_input" in (e["graph"].get("dep") or []):
            exclusions["audio_input_dependency"].append(e["path"])
            continue
        pool.append({**e, "features": sorted(tokens)})
    return pool, exclusions, anomalies


def category_pool(pool, cat):
    return sorted((c for c in pool if c["category"] == cat),
                  key=lambda c: c["path"])


def author_capped(cand, author_counts, author_cap):
    """Author caps limit same-author concentration in the contributor bank.

    The factory bank has no meaningful per-author structure (pseudo-author
    '(factory)'); it is bounded by bank quotas instead, never by this cap.
    """
    if cand["author"] == "(factory)":
        return False
    return author_counts[cand["author"]] >= author_cap


def pick_next(candidates, selected_paths, covered, author_counts, author_cap,
              allow_author_overrun=False):
    """Greedy marginal-coverage pick; fully deterministic tie-breaks.

    With allow_author_overrun, a second pass ignores author caps when caps
    would otherwise exhaust the pool; the caller records the overrun.
    Returns (candidate_or_None, overrun_bool).
    """
    def scan(enforce_caps):
        best = None
        best_key = None
        for c in candidates:
            if c["path"] in selected_paths:
                continue
            if enforce_caps and author_capped(c, author_counts, author_cap):
                continue
            gain = sum(1 for t in c["features"] if t not in covered)
            key = (-gain, -len(c["features"]), c["path"])
            if best_key is None or key < best_key:
                best, best_key = c, key
        return best

    best = scan(enforce_caps=True)
    if best is not None:
        return best, False
    if allow_author_overrun:
        best = scan(enforce_caps=False)
        return best, best is not None
    return None, False


def select_slate(pool, profile, stage):
    """Quota-driven greedy selection. stage: 'slate' or 'pilot'.

    Per category: joint bank floors (never summing above the quota), then
    greedy fills to the quota. Global factory floor/cap are then met by
    same-category swaps (drop weakest opposite-bank pick, add factory pick),
    so the total stays exactly at the quota sum unless a pool is truly
    exhausted — and every deviation is recorded in the accounting, never
    silently.
    """
    if stage == "slate":
        quotas = profile["slate_quotas"]
        bank_min_fraction = profile["bank_min_fraction"]
        global_factory_floor = profile["global_factory_floor"]
        global_factory_cap = profile["global_factory_cap"]
        author_cap = profile["author_cap"]
    else:
        quotas = profile["pilot_quotas"]
        bank_min_fraction = profile["pilot_bank_min_fraction"]
        global_factory_floor = profile["pilot_global_factory_floor"]
        global_factory_cap = None
        author_cap = profile["pilot_author_cap"]

    covered = set()
    selected = []
    selected_paths = set()
    author_counts = Counter()
    accounting = {}
    global_notes = []

    def take(c, slot, overrun=False, swap_for=None):
        nonlocal covered
        gain = [t for t in c["features"] if t not in covered]
        selected.append({"cand": c, "stage": stage, "slot": slot,
                         "new_features": sorted(gain), "overrun": overrun,
                         "swap_for": swap_for})
        covered = covered | set(c["features"])
        selected_paths.add(c["path"])
        author_counts[c["author"]] += 1

    def drop(entry):
        selected.remove(entry)
        selected_paths.discard(entry["cand"]["path"])
        author_counts[entry["cand"]["author"]] -= 1

    for cat in CATEGORY_ORDER:
        cand = category_pool(pool, cat)
        quota = quotas[cat]
        avail = {b: [c for c in cand if c["bank"] == b] for b in BANK_FILL_ORDER}
        notes = []
        # Joint bank floors: the minority floor comes off the quota first;
        # the other bank's floor is bounded by what remains, so floors can
        # never sum above the quota.
        f_floor = min(len(avail["factory"]),
                      int(bank_min_fraction * quota + 0.999999))
        if bank_min_fraction > 0 and len(avail["factory"]) < f_floor:
            notes.append(
                f"factory availability {len(avail['factory'])} < floor "
                f"{f_floor}; shortfall passes to contributor bank")
        c_floor = min(len(avail["contributor"]), quota - f_floor)
        picks = []
        overrun_paths = []
        for _ in range(f_floor):
            c, ov = pick_next(avail["factory"], selected_paths, covered,
                              author_counts, author_cap,
                              allow_author_overrun=True)
            if c is None:
                notes.append("factory floor under-filled: no candidate")
                break
            take(c, f"{cat}:factory-floor", overrun=ov)
            picks.append(c)
            if ov:
                overrun_paths.append(c["path"])
        for _ in range(c_floor):
            c, ov = pick_next(avail["contributor"], selected_paths, covered,
                              author_counts, author_cap,
                              allow_author_overrun=True)
            if c is None:
                notes.append("contributor floor under-filled: no candidate")
                break
            take(c, f"{cat}:contributor-floor", overrun=ov)
            picks.append(c)
            if ov:
                overrun_paths.append(c["path"])
        # Fill the remainder from either bank; author caps may be exceeded
        # ONLY when the category pool would otherwise run out, and every
        # such overrun is recorded (never silent).
        while len(picks) < quota:
            c, ov = pick_next(cand, selected_paths, covered, author_counts,
                              author_cap, allow_author_overrun=True)
            if c is None:
                notes.append(f"pool exhausted at {len(picks)}/{quota}")
                break
            take(c, f"{cat}:fill", overrun=ov)
            picks.append(c)
            if ov:
                overrun_paths.append(c["path"])
        if overrun_paths:
            notes.append(f"author cap exceeded to meet quota "
                         f"({len(overrun_paths)} pick(s))")
        accounting[cat] = {
            "quota": quota,
            "selected": len(picks),
            "factory": sum(1 for c in picks if c["bank"] == "factory"),
            "contributor": sum(1 for c in picks if c["bank"] == "contributor"),
            "notes": notes,
        }

    def bank_count(bank):
        return sum(1 for s in selected if s["cand"]["bank"] == bank)

    # Global factory floor: same-category swaps (contributor -> factory), so
    # the slate total stays constant.
    guard = 0
    while bank_count("factory") < global_factory_floor:
        guard += 1
        if guard > global_factory_floor * len(CATEGORY_ORDER) + len(pool):
            break
        best = None
        best_key = None
        victim = None
        for cat in CATEGORY_ORDER:
            contributors = [s for s in selected
                            if s["cand"]["category"] == cat
                            and s["cand"]["bank"] == "contributor"]
            if not contributors:
                continue
            factories = [c for c in category_pool(pool, cat)
                         if c["bank"] == "factory"]
            c, _ov = pick_next(factories, selected_paths, covered,
                               author_counts, author_cap)
            if c is None:
                continue
            weakest = sorted(contributors,
                             key=lambda s: (len(s["new_features"]),
                                            s["cand"]["path"]))[0]
            key = (-(sum(1 for t in c["features"] if t not in covered)),
                   c["path"])
            if best_key is None or key < best_key:
                best, best_key, victim = c, key, weakest
        if best is None:
            global_notes.append(
                f"global factory floor shortfall: "
                f"{global_factory_floor - bank_count('factory')} "
                "(no swappable factory candidate available)")
            break
        cat = victim["cand"]["category"]
        drop(victim)
        take(best, f"{cat}:global-factory-floor-swap",
             swap_for=victim["cand"]["path"])
        accounting[cat]["factory"] += 1
        accounting[cat]["contributor"] -= 1

    # Global factory cap: drop weakest factory picks, refill from the same
    # category's contributor pool (total constant).
    if global_factory_cap is not None:
        while bank_count("factory") > global_factory_cap:
            factory_sel = [s for s in selected
                           if s["cand"]["bank"] == "factory"]
            weakest = sorted(factory_sel,
                             key=lambda s: (len(s["new_features"]),
                                            s["cand"]["path"]))[0]
            cat = weakest["cand"]["category"]
            drop(weakest)
            accounting[cat]["factory"] -= 1
            accounting[cat]["contributor"] -= 1
            accounting.setdefault("_global", {})
            accounting["_global"]["factory_cap_drops"] = (
                accounting["_global"].get("factory_cap_drops", 0) + 1)
            cand = [c for c in category_pool(pool, cat)
                    if c["bank"] == "contributor"]
            c, ov = pick_next(cand, selected_paths, covered, author_counts,
                              author_cap, allow_author_overrun=True)
            if c is not None:
                take(c, f"{cat}:factory-cap-refill", overrun=ov)
                accounting[cat]["contributor"] += 1
            else:
                accounting[cat]["notes"].append(
                    "factory-cap drop not refilled: contributor pool "
                    "exhausted")

    if global_notes:
        accounting["_global"] = accounting.get("_global", {})
        accounting["_global"]["notes"] = (
            accounting["_global"].get("notes", []) + global_notes)

    return selected, accounting


def slate_records(selected, stage):
    out = []
    for rank, s in enumerate(selected, 1):
        c = s["cand"]
        out.append({
            "id": c["path"],
            "path": c["path"],
            "bank": c["bank"],
            "category": c["category"],
            "directory": c["directory"],
            "author": c["author"],
            "census_blob_sha1": c["sha"],
            "size_bytes": c["size"],
            "stored_revision": c["rev"],
            "features": c["features"],
            "reason": {
                "slot": s["slot"],
                "rank_in_stage": rank,
                "new_diversity_features": s["new_features"],
                "author_cap_overrun": bool(s.get("overrun")),
                "swapped_for": s.get("swap_for"),
                "selection": (
                    "greedy marginal coverage of normalized-graph diversity "
                    "tokens under explicit quotas; deterministic tie-break "
                    "(gain desc, feature count desc, path asc); no popularity "
                    "signal exists in the inputs and none is used"),
            },
        })
    return out


def build_profile(pool, exclusions, anomalies, profile_name, graphs_path,
                  census_path):
    profile = PROFILES[profile_name]
    slate_sel, slate_acc = select_slate(pool, profile, "slate")
    pilot_sel, pilot_acc = select_slate(
        [s["cand"] for s in slate_sel], profile, "pilot")

    slate_paths = {s["cand"]["path"] for s in slate_sel}
    pilot_paths = {s["cand"]["path"] for s in pilot_sel}
    if not pilot_paths <= slate_paths:
        raise Refuse("internal error: pilot is not a subset of the slate")

    def bank_split(sel):
        return {
            "factory": sum(1 for s in sel if s["cand"]["bank"] == "factory"),
            "contributor": sum(1 for s in sel
                               if s["cand"]["bank"] == "contributor"),
        }

    def categories_split(sel):
        d = defaultdict(int)
        for s in sel:
            d[s["cand"]["category"]] += 1
        return dict(sorted(d.items()))

    common = {
        "schema_version": SCHEMA_VERSION,
        "issue": ISSUE,
        "claim_scope": (
            "PROPOSED listening candidates from normalized static graph data "
            "only. This is NOT a frozen favorites set, NOT a support claim, "
            "NOT a fidelity claim, and NOT a quality claim. Human listening "
            "selection has not happened."),
        "engine_pin": {"commit": (slate_sel[0]["cand"]["engine_pin"]
                                  if slate_sel else None)},
        "inputs": {
            "graphs_jsonl": str(graphs_path),
            "graphs_jsonl_sha256": sha256_file(graphs_path),
            "census_per_preset_csv": str(census_path),
            "census_per_preset_csv_sha256": sha256_file(census_path),
        },
        "integrity": (
            "every line cross-checked against the census per-preset.csv "
            "git blob SHA-1 and size at load time; mismatch refuses the run"),
        "profile": {"name": profile_name, "description": profile["description"],
                    "quotas": {k: v for k, v in profile.items()
                               if k not in ("description",)}},
    }

    slate_doc = {
        **common,
        "artifact": f"slate-{profile['slate_total']}-{profile_name}",
        "selection_method": {
            "algorithm": ("per-category bank floors, then greedy "
                          "marginal-coverage picks; global factory "
                          "floor/cap pass; author caps"),
            "diversity_tokens": (
                "osc families, unison buckets, wavetable assets, audio-input, "
                "fm/ring/noise paths, filter units + topology, waveshaper, "
                "scene/play modes, character, LFO shapes (incl. MSEG/Formula "
                "gap markers), FX types + roles + Airwindows algorithm ids, "
                "send usage, modroute-count buckets"),
            "popularity_bias": (
                "no popularity/download/usage signal exists in the inputs; "
                "selection uses normalized-graph diversity + explicit quotas "
                "only; author caps limit same-author concentration"),
        },
        "totals": {"requested": profile["slate_total"],
                   "selected": len(slate_sel),
                   "banks": bank_split(slate_sel),
                   "categories": categories_split(slate_sel)},
        "quota_accounting": slate_acc,
        "exclusions": {k: sorted(v) for k, v in sorted(exclusions.items())},
        "anomalies": anomalies,
        "candidates": slate_records(slate_sel, "slate"),
    }
    slate_bytes = json.dumps(slate_doc, indent=2, sort_keys=True) + "\n"

    pilot_doc = {
        **common,
        "artifact": f"pilot-{profile['pilot_total']}-{profile_name}",
        "relation": {
            "subset_of": f"slate-{profile['slate_total']}-{profile_name}",
            "slate_sha256": hashlib.sha256(slate_bytes.encode()).hexdigest(),
        },
        "totals": {"requested": profile["pilot_total"],
                   "selected": len(pilot_sel),
                   "banks": bank_split(pilot_sel),
                   "categories": categories_split(pilot_sel)},
        "quota_accounting": pilot_acc,
        "candidates": slate_records(pilot_sel, "pilot"),
    }
    pilot_bytes = json.dumps(pilot_doc, indent=2, sort_keys=True) + "\n"
    return slate_bytes, pilot_bytes


def main():
    ap = argparse.ArgumentParser(
        description="SXT-013 deterministic candidate-pool builder (proposals "
                    "for human listening; freezes nothing)")
    ap.add_argument("--graphs", default=str(DEFAULT_GRAPHS),
                    help="normalized graphs.jsonl (default: committed export)")
    ap.add_argument("--census", default=str(DEFAULT_CENSUS_CSV),
                    help="census per-preset.csv (default: committed census)")
    ap.add_argument("--profile", default="balanced",
                    choices=sorted(PROFILES) + ["all"],
                    help="quota profile (default: balanced; 'all' emits all)")
    ap.add_argument("--out-dir", required=True,
                    help="output directory for slate/pilot JSON files")
    args = ap.parse_args()

    graphs_path = Path(args.graphs)
    census_path = Path(args.census)
    try:
        census = load_census(census_path)
        entries = load_graphs(graphs_path, census)
        pool, exclusions, anomalies = build_pool(entries)
        profiles = sorted(PROFILES) if args.profile == "all" else [args.profile]
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for profile_name in profiles:
            slate_bytes, pilot_bytes = build_profile(
                pool, exclusions, anomalies, profile_name, graphs_path,
                census_path)
            profile = PROFILES[profile_name]
            slate_path = out_dir / (
                f"slate-{profile['slate_total']}-{profile_name}.json")
            pilot_path = out_dir / (
                f"pilot-{profile['pilot_total']}-{profile_name}.json")
            slate_path.write_text(slate_bytes, encoding="utf-8")
            pilot_path.write_text(pilot_bytes, encoding="utf-8")
            slate_doc = json.loads(slate_bytes)
            pilot_doc = json.loads(pilot_bytes)
            print(f"wrote {slate_path.name}: "
                  f"{slate_doc['totals']['selected']} candidates "
                  f"(factory {slate_doc['totals']['banks']['factory']}, "
                  f"contributor {slate_doc['totals']['banks']['contributor']})")
            print(f"wrote {pilot_path.name}: "
                  f"{pilot_doc['totals']['selected']} candidates "
                  f"(factory {pilot_doc['totals']['banks']['factory']}, "
                  f"contributor {pilot_doc['totals']['banks']['contributor']})")
        pool_note = (
            f"pool: {len(pool)} eligible of {len(entries)} census entries; "
            + "; ".join(f"{k}={len(v)}" for k, v in sorted(exclusions.items()))
            + f"; anomalies={len(anomalies)}")
        print(pool_note)
        print("NOTE: proposals for human listening only; nothing is frozen.")
        return 0
    except Refuse as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
