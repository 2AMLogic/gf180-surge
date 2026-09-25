#!/usr/bin/env python3
"""SXT-017 stage 2: cost-closure gate over the SXT-016 probe records (issue #12).

The bundle stage (`tools/profile_predict.py`) answers a *structural* question:
does a preset's original normalized graph fit a candidate bundle's feature
allowlists and state/bandwidth budgets? It deliberately gates nothing on
cycles, because when it was written every cycle number was SXT-015's
`placeholder-v0` and a placeholder supports no fit claim.

SXT-016 (issue #11) has since landed 76 validated probe records. This tool
supplies the leg the bundle stage left open, and only that leg:

    for every candidate bundle B, every candidate word length (M18/M32),
    every NAMED external-memory model (E1/E2/E3) and every candidate clock
    F, compute the worst-case complete-patch cost per output frame over B's
    predicted-supported set and evaluate plan section 5's closure formula.

Plan section 5: "No fit claim is valid without a clock, memory
implementation, and measured schedule." Every row therefore names its clock,
its memory implementation, its multiplier schedule, and the *basis* of each
number. The basis is ESTIMATE, never measurement: no gf180mcu synthesis,
place-and-route, timing signoff, or hardware run stands behind any number
here (probes/common.py TECH; reports/sxt-016/EVIDENCE.md).

## Two totals, and why the asymmetry matters

Some components of a complete patch are priced by an SXT-016 probe; others
are not (LFOs, envelopes, modulation rows, waveshapers, Chorus/Phaser/
Reverb2/Airwindows, and any oscillator family no probe covers). This tool
reports two separate totals per preset and never merges them:

  * `probe_only_cycles_per_frame` — the sum of probe-priced components
    ALONE. Because every omitted component costs >= 0 cycles, this is a
    strict LOWER BOUND on the complete-patch cost.
  * `mixed_cycles_per_frame` — probe-priced components plus SXT-015
    `placeholder-v0` values for the rest (the SXT-016 worked-bundle
    convention). A placeholder may be high or low, so this total is
    directionally unbounded.

The verdicts follow that asymmetry exactly, which is the whole point:

  OVERFLOW_CONCLUSIVE             lower bound alone already exceeds the DSP
                                  budget. Conclusive: pricing the missing
                                  components can only make it worse.
  OVERFLOW_PLACEHOLDER_DEPENDENT  only the mixed total exceeds the budget.
                                  A finding, NOT a conclusion.
  NO_VERDICT_UNPRICED_COMPONENTS  nothing overflows, but unpriced components
                                  remain, so a PASS cannot be claimed.
  within_budget                   every component in the worst-case patch is
                                  probe-priced and the total closes. This is
                                  the ONLY row shape that may carry a fit
                                  claim, and even then only as an estimate
                                  under the named assumptions.

## Admissibility, fit claims, and selection

A bundle is **admissible** at a given budget if at least one configuration
is not ruled out — verdict `within_budget` or `NO_VERDICT_UNPRICED_COMPONENTS`.
It is **fit-claimable** only if some configuration is `within_budget`.
Admissible-but-not-fit-claimable is the honest middle: "this bundle is not
ruled out by anything priced today", which is emphatically not "this bundle
fits". Every selection carries `fit_claim` so the two can never be conflated.

Among the admissible product-candidate bundles, select the one with the
greatest **complete-preset recovery of the preferred-preset set** (a preset
counts only if *every* active feature of its original graph fits at once;
adapted presets never count), with corpus-wide recovery as the tiebreak.
Individual feature frequencies decide nothing. If no product-candidate
bundle is admissible, or if the selected bundle misses the declared
preferred-preset goal, the tool sets `stop_escalate: true` — issue #12's
stop/escalate condition, which is a product-owner decision and not this
tool's to paper over by weakening the goal.

## Negative control (issue #12 acceptance)

`--budget-scale K` multiplies the DSP budget (equivalently: scales the
clock) by K. Re-running with a deliberately inflated budget MUST change the
selected bundle; if it does not, the comparison is not sensitive to budget
and must be fixed. The knob is fail-closed: K != 1 refuses to write to a
path under `reports/sxt-017/` unless `--negative-control` is also given, and
stamps the artifact so an inflated run can never be mistaken for the real
one.

Claim discipline (AGENTS.md): nothing here is a fidelity, preset-quality,
musical-usefulness, area, timing, power, or hardware claim, and nothing here
freezes profile v1. Determinism: same inputs => byte-identical output.

Provenance/licensing: original to this repository (Apache-2.0 per LICENSE);
Python stdlib only. It imports this repository's own SXT-015 accounting
model, SXT-016 probe package, and SXT-017 predictor, and reads committed
SXT-011 graphs; no Surge source, tables, or preset payloads are copied.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from model.resources.accounting import MODEL_VERSION  # noqa: E402
from model.resources.params import REG  # noqa: E402
from probes.common import (CLOCK_CANDIDATES_HZ, FS_HZ, RESERVE_FRACTION,  # noqa: E402
                           TECH, closure, ext_sustained_bytes_per_s)
from probes.worked_bundle import build_bundle  # noqa: E402
from tools.profile_predict import (Refuse, SUPPORTED, _require,  # noqa: E402
                                   _sha256_file, load_bundle_file,
                                   load_graphs, load_slates, predict_line,
                                   validate_spec)

TOOL_VERSION = "sxt-017-budget/1.0.0"

DEFAULT_BUNDLE_IDS = ("B1-core-narrow", "B2-core-wet-plan3", "B3-ext-voice-fx",
                      "B4-broad", "R0-ceiling-reference")
# R0 is the deliberate non-product ceiling row of the bundle stage: it exists
# to bound the comparison, never to be shipped. It is scored like any other
# bundle but is excluded from selection.
DEFAULT_REFERENCE_BUNDLE_IDS = ("R0-ceiling-reference",)

MULTIPLIERS = ("M18", "M32")
E_MODELS = ("E1", "E2", "E3")
DEFAULT_PHASE_BITS = 32

VERDICT_OVERFLOW_CONCLUSIVE = "OVERFLOW_CONCLUSIVE"
VERDICT_OVERFLOW_PLACEHOLDER = "OVERFLOW_PLACEHOLDER_DEPENDENT"
VERDICT_NO_VERDICT = "NO_VERDICT_UNPRICED_COMPONENTS"
VERDICT_WITHIN = "within_budget"

_PROBE_FN_RE = re.compile(
    r"^(?P<probe>probe_[a-z0-9_]+?)__(?P<kernel>[A-Za-z0-9_]+?)"
    r"(?:__ph(?P<phase>\d+))?__a(?P<audio>\d+)__m(?P<mult>\d+)__"
    r"(?P<mem>[a-z0-9]+)\.json$")


def load_probe_index(probes_dir, phase_bits=DEFAULT_PHASE_BITS):
    """Index probe records by (probe, kernel, multiplier), pinning ONE phase
    width so the selection is explicit rather than filename-order dependent.

    Fail-closed: an ambiguous key (two records selected for the same key) or
    an unparseable filename REFUSES the run. Silently letting the last file
    in sort order win is exactly the kind of invisible input choice this
    repository's evidence rules forbid."""
    probes_dir = Path(probes_dir)
    _require(probes_dir.is_dir(),
             "REFUSING: probe directory %s does not exist; SXT-016 (issue #11) "
             "must have been run" % probes_dir)
    idx, origin = {}, {}
    for fn in sorted(p.name for p in probes_dir.glob("*.json")):
        m = _PROBE_FN_RE.match(fn)
        _require(m is not None,
                 "REFUSING: probe filename %r does not match the SXT-016 "
                 "naming convention; it cannot be selected unambiguously" % fn)
        if m.group("phase") is not None and int(m.group("phase")) != phase_bits:
            continue
        rec = json.loads((probes_dir / fn).read_text())
        key = (rec["probe"], rec["kernel"], rec["word_lengths"].get("multiplier"))
        _require(key not in idx,
                 "REFUSING: ambiguous probe selection for %s: %r and %r both "
                 "match (phase pin %d)" % (key, origin.get(key), fn, phase_bits))
        idx[key] = rec
        origin[key] = fn
    _require(idx, "REFUSING: no probe records selected from %s at phase pin %d"
             % (probes_dir, phase_bits))
    return idx, origin


def split_component_costs(row):
    """Split one worked-bundle row into (probe-priced lower bound, mixed total).

    `build_bundle` tags every component it prices from a placeholder with
    `placeholder_component: True`, and records oscillator families no probe
    covers as `osc_family_uncovered:<name>` flags (those components are
    costed at zero, which is what makes the probe-only total a lower bound).
    """
    probe_only = 0.0
    placeholder = 0.0
    placeholder_names = []
    for comp in row["components"]:
        c = comp.get("cycles_per_frame", 0) or 0
        if comp.get("placeholder_component"):
            placeholder += c
            placeholder_names.append(comp["component"])
        else:
            probe_only += c
    uncovered = sorted(f.split(":", 1)[1] for f in row["flags"]
                       if f.startswith("osc_family_uncovered:"))
    return {
        "probe_only_cycles_per_frame": round(probe_only, 1),
        "mixed_cycles_per_frame": round(probe_only + placeholder, 1),
        "placeholder_cycles_per_frame": round(placeholder, 1),
        "placeholder_components": sorted(set(placeholder_names)),
        "uncovered_oscillator_families": uncovered,
    }


def _verdict(max_probe_only, max_mixed, budget, has_unpriced):
    if max_probe_only > budget:
        return VERDICT_OVERFLOW_CONCLUSIVE
    if max_mixed > budget:
        return VERDICT_OVERFLOW_PLACEHOLDER
    if has_unpriced:
        return VERDICT_NO_VERDICT
    return VERDICT_WITHIN


def _lanes_required(cost, budget):
    """Lower bound on the parallel-lane count that could close this row.

    Reported because it turns an "OVERFLOW (2829%)" cell into the decision
    input the profile freeze actually needs. It assumes perfectly divisible
    work (A-SCHED-1 is scalar single-lane; no lane schedule has been
    designed, let alone verified), so it is a FLOOR, never a design."""
    if budget <= 0:
        return None
    return int(math.ceil(cost / budget)) if cost > 0 else 0


def predict_supported_paths(lines, spec):
    """Predicted-supported set for one bundle spec (bundle-stage semantics)."""
    paths = []
    for d in lines:
        status, _reasons, _cols = predict_line(d, spec)
        if status == SUPPORTED:
            paths.append(d["p"])
    return paths


def score_bundle(bundle_id, spec, lines, by_path, idx, budget_scale,
                 slates=None, clocks=CLOCK_CANDIDATES_HZ):
    """Full (multiplier x memory model x clock) grid for one bundle."""
    supported = predict_supported_paths(lines, spec)
    grid = []
    per_config = {}
    for mult in MULTIPLIERS:
        for e_model in E_MODELS:
            worst_probe_only = 0.0
            worst_mixed = 0.0
            worst_ram_bits = 0
            worst_ext_bytes_frame = 0
            arg_probe_only = None
            arg_mixed = None
            n_placeholder = 0
            n_uncovered = 0
            uncovered_families = set()
            placeholder_components = set()
            transfer = contention = 0.0
            with REG.override("voice_pool_limit", spec["voice_pool_limit"]):
                for p in supported:
                    row = build_bundle(p, by_path[p], idx, mult,
                                       fx_instance_limit=spec["fx_instance_limit"],
                                       e_model=e_model)
                    if row.get("status") == "analysis_failure":
                        continue
                    split = split_component_costs(row)
                    if split["placeholder_cycles_per_frame"] > 0:
                        n_placeholder += 1
                        placeholder_components.update(split["placeholder_components"])
                    if split["uncovered_oscillator_families"]:
                        n_uncovered += 1
                        uncovered_families.update(
                            split["uncovered_oscillator_families"])
                    if split["probe_only_cycles_per_frame"] > worst_probe_only:
                        worst_probe_only = split["probe_only_cycles_per_frame"]
                        arg_probe_only = p
                    if split["mixed_cycles_per_frame"] > worst_mixed:
                        worst_mixed = split["mixed_cycles_per_frame"]
                        arg_mixed = p
                    worst_ram_bits = max(worst_ram_bits,
                                         row["state_ram_bits_total"])
                    worst_ext_bytes_frame = max(worst_ext_bytes_frame,
                                                row["ext_bytes_per_frame"])
                    # scheduler transfer/contention are per-frame fixed costs
                    # of the same probe record for every preset in this config
                    cl0 = row["closure_at_clocks"][clocks[0]]
                    transfer = cl0["transfer_cycles_per_frame"]
                    contention = cl0["contention_cycles_per_frame"]
            has_unpriced = bool(n_placeholder or n_uncovered)
            for clock in clocks:
                base = closure(clock, worst_mixed, control=0, transfer=transfer,
                               contention=contention)
                budget = base["dsp_budget_cycles_per_frame"] * budget_scale
                verdict = _verdict(worst_probe_only, worst_mixed, budget,
                                   has_unpriced) if supported else "EMPTY_SUPPORTED_SET"
                sustained = ext_sustained_bytes_per_s(clock, e_model)
                required = worst_ext_bytes_frame * FS_HZ
                row_out = {
                    "bundle_id": bundle_id,
                    "multiplier": mult,
                    "multiplier_assumption": TECH["multipliers"][mult]["assumption"],
                    "memory_implementation": e_model,
                    "memory_implementation_assumption": TECH["external"][e_model][
                        "assumption"],
                    "clock_hz": clock,
                    "sample_rate_hz": FS_HZ,
                    "gross_cycles_per_frame": base["gross_cycles_per_frame"],
                    "reserve_fraction": RESERVE_FRACTION,
                    "transfer_cycles_per_frame": transfer,
                    "contention_cycles_per_frame": contention,
                    "dsp_budget_cycles_per_frame": round(budget, 6),
                    "budget_scale": budget_scale,
                    "worst_probe_only_cycles_per_frame": worst_probe_only,
                    "worst_mixed_cycles_per_frame": worst_mixed,
                    "worst_probe_only_preset": arg_probe_only,
                    "worst_mixed_preset": arg_mixed,
                    "worst_state_ram_bits": worst_ram_bits,
                    "worst_ext_bytes_per_frame": worst_ext_bytes_frame,
                    "required_ext_bytes_per_s": required,
                    "sustained_ext_bytes_per_s": sustained,
                    "ext_bandwidth_fit": ("within" if required <= sustained
                                          else "EXCEEDS"),
                    "lanes_required_floor_probe_only":
                        _lanes_required(worst_probe_only, budget),
                    "lanes_required_floor_mixed":
                        _lanes_required(worst_mixed, budget),
                    "verdict": verdict,
                    "basis": "ESTIMATE under named assumptions (SXT-016 probe "
                             "records + SXT-015 structure). NOT a measurement: "
                             "no gf180mcu synthesis, place-and-route, timing "
                             "signoff, or hardware run stands behind it.",
                }
                grid.append(row_out)
                per_config[(mult, e_model, clock)] = row_out
    def _cfg(r):
        return {"multiplier": r["multiplier"],
                "memory_implementation": r["memory_implementation"],
                "clock_hz": r["clock_hz"]}

    fit_configs = [r for r in grid if r["verdict"] == VERDICT_WITHIN]
    admissible_configs = [r for r in grid if r["verdict"] in
                          (VERDICT_WITHIN, VERDICT_NO_VERDICT)]
    if admissible_configs:
        excluded_by = "none"
    elif all(r["verdict"] == VERDICT_OVERFLOW_CONCLUSIVE for r in grid):
        excluded_by = "conclusive_lower_bound"
    else:
        excluded_by = "placeholder_mixed_total"
    sup_set = set(supported)
    slate_cov = {}
    for lbl in sorted(slates or {}):
        s = slates[lbl]
        hit = len(sup_set & s["paths"])
        slate_cov[lbl] = {"slate_size": s["total"],
                          "predicted_supported_count": hit,
                          "essentiality": "UNVERIFIED: proposal slate, not a "
                                          "frozen favorites set"}
    return {
        "bundle_id": bundle_id,
        "predicted_supported_count": len(supported),
        "slate_coverage": slate_cov,
        "grid": grid,
        "admissible": bool(admissible_configs),
        "fit_claimable": bool(fit_configs),
        "excluded_by": excluded_by,
        "admissible_configs": [_cfg(r) for r in admissible_configs],
        "fit_claim_configs": [_cfg(r) for r in fit_configs],
        "unpriced_component_note":
            "components no SXT-016 probe prices are costed at placeholder-v0 "
            "in the mixed total and at ZERO in the probe-only lower bound; a "
            "bundle whose only non-overflowing rows still contain unpriced "
            "components is admissible but NOT fit-claimable",
    }, supported


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graphs", default="corpus/normalized/graphs.jsonl")
    ap.add_argument("--bundle", default="contracts/profile-v1-bundle-DRAFT.json")
    ap.add_argument("--bundle-id", action="append", default=[],
                    help="repeatable; defaults to the five headline bundles")
    ap.add_argument("--reference-bundle", action="append", default=[],
                    help="bundle ids excluded from selection (non-product "
                         "ceiling rows); defaults to R0-ceiling-reference")
    ap.add_argument("--slate", action="append", default=[],
                    help="preferred-preset slate JSON; repeatable")
    ap.add_argument("--primary-slate", default=None,
                    help="slate label that decides the ranking (defaults to "
                         "the first --slate in sorted label order)")
    ap.add_argument("--goal-fraction", type=float, default=0.8,
                    help="plan section 2 product goal: fraction of the "
                         "preferred-preset set that must be supported")
    ap.add_argument("--probes-dir", default="reports/sxt-016/probes")
    ap.add_argument("--phase-bits", type=int, default=DEFAULT_PHASE_BITS)
    ap.add_argument("--budget-scale", type=float, default=1.0,
                    help="negative control: multiply the DSP budget by K")
    ap.add_argument("--negative-control", action="store_true",
                    help="required when --budget-scale != 1")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    scale = args.budget_scale
    _require(scale > 0, "REFUSING: --budget-scale must be > 0")
    is_control = abs(scale - 1.0) > 1e-12
    if is_control:
        _require(args.negative_control,
                 "REFUSING: --budget-scale %r inflates/deflates the DSP budget; "
                 "pass --negative-control to acknowledge that the output is a "
                 "control artifact and not a profile result" % scale)
    out_path = Path(args.out)
    committed = "reports/sxt-017" in out_path.as_posix()
    _require(not (is_control and committed),
             "REFUSING: a --budget-scale run must not be written under "
             "reports/sxt-017/ (a control artifact must never be mistaken for "
             "the profile result); write it to a scratch path instead")

    def _abs(p):
        return Path(p) if Path(p).is_absolute() else REPO / p

    lines, observed, graphs_sha = load_graphs(_abs(args.graphs))
    by_path = {d["p"]: d for d in lines}
    _require(len(by_path) == len(lines),
             "REFUSING: duplicate census paths in graphs file")
    raw, bundles = load_bundle_file(_abs(args.bundle))
    bundle_ids = args.bundle_id or list(DEFAULT_BUNDLE_IDS)
    reference_ids = set(args.reference_bundle or DEFAULT_REFERENCE_BUNDLE_IDS)
    for bid in bundle_ids:
        _require(bid in bundles,
                 "REFUSING: bundle_id %r not in %s (available: %s)"
                 % (bid, args.bundle, sorted(bundles)))
    _require(reference_ids <= set(bundles),
             "REFUSING: reference bundle ids %s not all present in %s"
             % (sorted(reference_ids - set(bundles)), args.bundle))

    idx, origin = load_probe_index(_abs(args.probes_dir), args.phase_bits)

    slates = load_slates([str(_abs(p)) for p in args.slate], by_path) \
        if args.slate else {}
    primary_slate = args.primary_slate or (sorted(slates)[0] if slates else None)
    _require(primary_slate is None or primary_slate in slates,
             "REFUSING: --primary-slate %r is not among the loaded slates %s"
             % (primary_slate, sorted(slates)))
    _require(0 < args.goal_fraction <= 1,
             "REFUSING: --goal-fraction must be in (0, 1]")

    results = []
    for bid in bundle_ids:
        spec = validate_spec(bundles[bid], observed)
        res, _sup = score_bundle(bid, spec, lines, by_path, idx, scale,
                                 slates=slates)
        res["is_product_candidate"] = bid not in reference_ids
        results.append(res)

    def _primary(r):
        if primary_slate is None:
            return r["predicted_supported_count"]
        return r["slate_coverage"][primary_slate]["predicted_supported_count"]

    candidates = [r for r in results
                  if r["is_product_candidate"] and r["admissible"]]
    candidates.sort(key=lambda r: (-_primary(r),
                                   -r["predicted_supported_count"],
                                   r["bundle_id"]))
    chosen = candidates[0] if candidates else None
    selected = chosen["bundle_id"] if chosen else None

    goal = None
    if chosen is not None and primary_slate is not None:
        size = chosen["slate_coverage"][primary_slate]["slate_size"]
        threshold = math.ceil(args.goal_fraction * size)
        got = chosen["slate_coverage"][primary_slate]["predicted_supported_count"]
        goal = {
            "basis_slate": primary_slate,
            "basis_note": "PROPOSAL slate (SXT-013 diversity maximization); the "
                          "frozen favorites set does not exist, so this is a "
                          "provisional stand-in and NOT the product goal's "
                          "real denominator",
            "goal_fraction": args.goal_fraction,
            "slate_size": size,
            "threshold": threshold,
            "predicted_supported": got,
            "goal_met": got >= threshold,
            "shortfall": max(0, threshold - got),
        }
    goal_missed = goal is not None and not goal["goal_met"]
    stop_escalate = (selected is None) or goal_missed or (
        chosen is not None and not chosen["fit_claimable"])

    doc = {
        "artifact": "sxt-017-cost-closure",
        "tool_version": TOOL_VERSION,
        "status": ("NEGATIVE-CONTROL-ARTIFACT (budget deliberately scaled by "
                   "%r; NOT a profile result)" % scale) if is_control else
                  "DRAFT-NOT-FROZEN (issue #12 stage 2: cost-closure leg over "
                  "SXT-016 probe records; freeze remains BLOCKED on SXT-013 "
                  "human listening and SXT-014 listening labels)",
        "claim_scope": "Cost-closure ESTIMATES under named assumptions. NOT a "
                       "measurement, NOT a gf180mcu feasibility result, NOT a "
                       "fidelity/preset-quality/musical claim, and NOT a "
                       "frozen profile. 'within_budget' is the only row shape "
                       "that may carry a fit claim, and only as an estimate.",
        "verdict_semantics": {
            VERDICT_OVERFLOW_CONCLUSIVE:
                "the probe-priced LOWER BOUND alone exceeds the DSP budget; "
                "pricing the unpriced components can only increase the cost, "
                "so this verdict is conclusive under the named assumptions",
            VERDICT_OVERFLOW_PLACEHOLDER:
                "only the placeholder-mixed total exceeds the budget; a "
                "finding, not a conclusion (placeholders may be high or low)",
            VERDICT_NO_VERDICT:
                "nothing overflows, but unpriced components remain, so no fit "
                "claim may be made (plan section 5)",
            VERDICT_WITHIN:
                "every component of the worst-case supported patch is "
                "probe-priced and the total closes at this clock and memory "
                "implementation",
        },
        "selection_rule": "greatest complete-preset recovery of the primary "
                          "preferred-preset slate (adapted never counts), "
                          "corpus-wide recovery as tiebreak, among "
                          "product-candidate bundles that are ADMISSIBLE at "
                          "this budget; feature frequencies decide nothing",
        "budget_scale": scale,
        "is_negative_control": is_control,
        "selected_bundle": selected,
        "selected_bundle_fit_claim": bool(chosen and chosen["fit_claimable"]),
        "goal_test": goal,
        "stop_escalate": stop_escalate,
        "stop_escalate_reasons": [r for r in [
            "no_admissible_product_candidate" if selected is None else None,
            "preferred_preset_goal_missed" if goal_missed else None,
            "selected_bundle_carries_no_fit_claim"
            if chosen is not None and not chosen["fit_claimable"] else None,
        ] if r],
        "stop_escalate_note":
            "issue #12 stop/escalate: the selection above does not meet the "
            "product goal within credible budgets. Freezing profile v1 "
            "requires an explicit, visible product-owner contract revision "
            "(recorded in issue #12 and a decision record). Do NOT weaken the "
            "goal, redefine 'supported', or count adapted presets to "
            "manufacture a passing profile."
            if stop_escalate else
            "no stop/escalate trigger fired at this budget; freezing still "
            "requires SXT-013 listening and SXT-014 labels",
        "provenance": {
            "graphs_file": args.graphs,
            "graphs_sha256": graphs_sha,
            "graphs_count": len(lines),
            "bundle_file": args.bundle,
            "bundle_file_sha256": _sha256_file(_abs(args.bundle)),
            "accounting_model_version": MODEL_VERSION,
            "accounting_cost_profile": REG.cost_profile,
            "probes_dir": args.probes_dir,
            "probe_phase_bits_pin": args.phase_bits,
            "probe_records_selected": {"%s/%s/%s" % k: v
                                       for k, v in sorted(origin.items())},
            "clock_candidates_hz": list(CLOCK_CANDIDATES_HZ),
            "memory_implementations": list(E_MODELS),
            "multipliers": list(MULTIPLIERS),
            "reserve_fraction": RESERVE_FRACTION,
            "reference_bundle_ids": sorted(reference_ids),
            "slates": sorted(slates),
            "primary_slate": primary_slate,
            "scheduler_contention_basis":
                "SXT-016 publishes ONE scheduler record; its contention "
                "allowance is E1-referenced and is applied unchanged at E2/E3. "
                "That makes E2/E3 rows conservative on contention, and it is "
                "stated rather than silently re-derived.",
        },
        "bundles": results,
    }

    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(blob, encoding="utf-8")

    for r in results:
        verdicts = {}
        for g in r["grid"]:
            verdicts[g["verdict"]] = verdicts.get(g["verdict"], 0) + 1
        print("%-24s supported %5d  slate %s  admissible %-5s fit_claim %-5s "
              "excluded_by %-24s verdicts %s"
              % (r["bundle_id"], r["predicted_supported_count"],
                 (r["slate_coverage"][primary_slate]["predicted_supported_count"]
                  if primary_slate else "-"),
                 r["admissible"], r["fit_claimable"], r["excluded_by"],
                 dict(sorted(verdicts.items()))))
    if goal is not None:
        print("goal(%s): %d/%d supported vs threshold %d -> goal_met=%s"
              % (goal["basis_slate"], goal["predicted_supported"],
                 goal["slate_size"], goal["threshold"], goal["goal_met"]))
    print("selected_bundle: %r (budget_scale %g) fit_claim=%s "
          "stop_escalate=%s %s"
          % (selected, scale, bool(chosen and chosen["fit_claimable"]),
             stop_escalate, doc["stop_escalate_reasons"]))
    print("wrote %s (%d bytes)" % (args.out, len(blob)))
    return 0


def markdown_table(doc, multiplier="M32", e_model="E1"):
    """Pareto view: rows uncombined, no single score (plan section 5)."""
    out = ["| Bundle | supported | worst probe-only cyc/frame | worst mixed "
           "cyc/frame | %s |" % " | ".join(
               "@%dM" % (c // 1_000_000) for c in CLOCK_CANDIDATES_HZ),
           "|---|---:|---:|---:|" + "---|" * len(CLOCK_CANDIDATES_HZ)]
    for b in doc["bundles"]:
        rows = {g["clock_hz"]: g for g in b["grid"]
                if g["multiplier"] == multiplier
                and g["memory_implementation"] == e_model}
        if not rows:
            continue
        any_row = rows[CLOCK_CANDIDATES_HZ[0]]
        cells = []
        for c in CLOCK_CANDIDATES_HZ:
            g = rows[c]
            short = {VERDICT_OVERFLOW_CONCLUSIVE: "OVERFLOW*",
                     VERDICT_OVERFLOW_PLACEHOLDER: "overflow?",
                     VERDICT_NO_VERDICT: "NO_VERDICT",
                     VERDICT_WITHIN: "within"}.get(g["verdict"], g["verdict"])
            lanes = g["lanes_required_floor_probe_only"]
            cells.append("%s (lanes>=%s)"
                         % (short, "n/a: budget<=0" if lanes is None else lanes))
        out.append("| %s | %d | %.0f | %.0f | %s |"
                   % (b["bundle_id"], b["predicted_supported_count"],
                      any_row["worst_probe_only_cycles_per_frame"],
                      any_row["worst_mixed_cycles_per_frame"],
                      " | ".join(cells)))
    return "\n".join(out)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
