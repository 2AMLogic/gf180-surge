#!/usr/bin/env python3
"""#122: measure the preset-coverage impact of the unpinnable FX RNG streams.

Reads the committed SXT-011 normalized graphs (corpus/normalized/graphs.jsonl)
and the SXT-013 proposal slates, and counts -- per FX class and in total --
how many corpus presets carry at least one effect instance whose sound
depends on an RNG stream that cannot be pinned under the SXT-010 manifest
(tools/fx_rng_characterize.py, decision record 0013).

The selectors are NOT hardcoded here: they are read from the
characterization artifact's `fx_survey`, so the count and the survey cannot
drift apart. A survey entry with `rng_dependence: none` contributes nothing;
`unconditional` contributes every active slot of that class;
`parameter_conditional` contributes only the slots whose named parameter
holds a named RNG value (or is > 0 for `rng_when: "value > 0"`).

FAIL-CLOSED. A class whose audibility conditionality was not analysed is
counted in full (an upper bound on the affected set, never a lower one), and
that is recorded per class. A survey entry whose selector this tool cannot
evaluate REFUSES the run rather than being silently skipped.

This is a COVERAGE REDUCTION record. It is published, not deducted: the
corpus denominator stays 3,561 and the slate denominators stay 256. Affected
presets move to (or stay in) not-supported, they are never removed from the
denominator.

Writes reports/SXT-028-rng/artifacts/coverage-impact.json.
Deterministic: same committed inputs => byte-identical output.
Original to this repository (Apache-2.0); Python standard library only.
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

GRAPHS = "corpus/normalized/graphs.jsonl"
CHARACTERIZATION = "reports/SXT-028-rng/artifacts/rng-characterization.json"
SLATES = [
    "reports/sxt-013/candidates/slate-256-balanced.json",
    "reports/sxt-013/candidates/slate-256-contributor-lean.json",
    "reports/sxt-013/candidates/slate-256-factory-lean.json",
]
OUT_DEFAULT = "reports/SXT-028-rng/artifacts/coverage-impact.json"

CORPUS_TOTAL = 3561


class Refuse(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def slot_is_affected(entry: dict, fx: dict) -> tuple:
    """(affected, detail) for one active FX slot against one survey entry."""
    dep = entry["rng_dependence"]
    if dep == "none":
        return False, None
    if dep == "unconditional":
        return True, "class always constructs an RNG-seeded processor"
    if dep != "parameter_conditional":
        raise Refuse(f"unknown rng_dependence {dep!r} for "
                     f"{entry['fx_type_name']}")
    sel = entry.get("selector") or {}
    idx = sel.get("param_index")
    if idx is None:
        raise Refuse(f"parameter_conditional survey entry for "
                     f"{entry['fx_type_name']} has no param_index")
    params = fx.get("p")
    if not params or idx >= len(params):
        raise Refuse(f"{entry['fx_type_name']} slot has no param[{idx}]")
    raw = float(params[idx])
    if "rng_values" in sel:
        val = int(round(raw))
        if val in set(sel["rng_values"]):
            return True, f"{sel['param']} = {val}"
        return False, None
    if sel.get("rng_when") == "value > 0":
        if raw > 0:
            return True, f"{sel['param']} = {raw!r} (> 0)"
        return False, None
    raise Refuse(f"unevaluatable selector for {entry['fx_type_name']}: {sel}")


def run(repo: Path, out_rel: str) -> int:
    ch_path = repo / CHARACTERIZATION
    if not ch_path.is_file():
        raise Refuse(f"missing characterization artifact: {CHARACTERIZATION} "
                     "(run tools/fx_rng_characterize.py first)")
    ch = json.loads(ch_path.read_text(encoding="utf-8"))
    if ch["finding"]["stream_is_pinnable"]:
        raise Refuse(
            "the characterization says the stream IS pinnable; a coverage "
            "REDUCTION record is the wrong artifact for outcome (a). Build "
            "the frozen model instead."
        )
    survey = {e["fx_type_id"]: e for e in ch["fx_survey"]
              if e.get("fx_type_id") is not None}

    graphs_path = repo / GRAPHS
    if not graphs_path.is_file():
        raise Refuse(f"missing {GRAPHS}")

    per_class = defaultdict(lambda: {"slots": 0, "presets": set()})
    affected_presets = {}
    any_slot_presets = set()
    total = 0
    with open(graphs_path, "rb") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line.decode("utf-8"))
            total += 1
            path = e["p"]
            g = e.get("g") or {}
            fxd = g.get("fxd", 0)
            for fx in g.get("fx", []):
                if fx.get("on") != 1:
                    continue
                entry = survey.get(fx["t"])
                if entry is None:
                    continue
                hit, detail = slot_is_affected(entry, fx)
                if not hit:
                    continue
                any_slot_presets.add(path)
                # A slot in the fx_disable mask does not process, so it
                # cannot carry an RNG dependence. This is the SAME notion of
                # a required effect instance tools/publish_coverage.py uses.
                if fxd & (1 << fx["i"]):
                    continue
                name = entry["fx_type_name"]
                per_class[name]["slots"] += 1
                per_class[name]["presets"].add(path)
                rec = affected_presets.setdefault(path, {
                    "path": path, "bank": e["b"], "census_blob_sha1": e["sha"],
                    "classes": [],
                })
                rec["classes"].append({
                    "fx_type_name": name, "slot": fx["i"], "role": fx["r"],
                    "generator": entry["generator"], "why": detail,
                })
    if total != CORPUS_TOTAL:
        raise Refuse(f"expected {CORPUS_TOTAL} corpus entries, found {total}")

    # every surveyed class must be representable in the count, even at zero
    for entry in ch["fx_survey"]:
        name = entry["fx_type_name"]
        if name not in per_class:
            per_class[name]["slots"] = 0

    slates = {}
    all_paths = set(affected_presets)
    for rel in SLATES:
        p = repo / rel
        if not p.is_file():
            raise Refuse(f"missing slate {rel}")
        s = json.loads(p.read_text(encoding="utf-8"))
        members = {c["path"] for c in s["candidates"]}
        if len(members) != 256:
            raise Refuse(f"slate {rel} is not 256 entries")
        slates[s["artifact"]] = {
            "slate_file": rel,
            "denominator": 256,
            "affected": len(members & all_paths),
            "affected_by_class": {
                name: len(members & d["presets"])
                for name, d in sorted(per_class.items()) if d["slots"]
            },
            "affected_paths": sorted(members & all_paths),
        }

    fxmod = {"Phaser", "Neuron"}
    fxmod_paths = set()
    for name in fxmod:
        fxmod_paths |= per_class[name]["presets"] if name in per_class else set()

    doc = {
        "schema_version": "sxt-028-rng-coverage-impact/1.0.0",
        "issue": "#122",
        "routes_to": "SXT-017 (#12)",
        "decision_record": "decision-records/0013-fx-modulation-rng-stream.md",
        "publication_rule": (
            "This is a published coverage REDUCTION, not a deduction. The "
            "corpus denominator stays 3,561 and every slate denominator "
            "stays 256. Affected presets are reported not-supported with a "
            "named reason; they are never removed from a denominator and "
            "never re-labelled 'out of scope'."
        ),
        "inputs": {
            GRAPHS: sha256_file(graphs_path),
            CHARACTERIZATION: sha256_file(ch_path),
            **{rel: sha256_file(repo / rel) for rel in SLATES},
        },
        "counting_rule": (
            "An effect instance counts only when its slot is ON and NOT in "
            "the patch's fx_disable mask -- the same notion of a REQUIRED "
            "effect instance tools/publish_coverage.py applies, because a "
            "disabled slot does not process and so carries no RNG "
            "dependence. `affected_presets_including_disabled_slots` is "
            "reported alongside so the narrower number is visibly a choice."
        ),
        "corpus": {
            "denominator": total,
            "affected_presets": len(all_paths),
            "affected_presets_including_disabled_slots": len(any_slot_presets),
            "affected_fraction": round(len(all_paths) / total, 6),
            "per_class": {
                name: {"affected_slots": d["slots"],
                       "affected_presets": len(d["presets"]),
                       "rng_dependence":
                           next((e["rng_dependence"] for e in ch["fx_survey"]
                                 if e["fx_type_name"] == name), None),
                       "upper_bound":
                           next((bool(e.get("audibility_conditionality"))
                                 for e in ch["fx_survey"]
                                 if e["fx_type_name"] == name), False)}
                for name, d in sorted(per_class.items())
            },
        },
        "scopes": {
            "issue_122_named_scope": {
                "what": "FXModControl mod_noise (5) / mod_snh (6) -- the "
                        "waveforms SXT-028g refused",
                "classes": sorted(fxmod),
                "affected_presets": len(fxmod_paths),
                "affected_of_corpus": f"{len(fxmod_paths)}/{total}",
            },
            "fx_modulation_rng_family": {
                "what": "every FX modulation shape driven by an RNG, "
                        "including the Flanger's shared-generator path the "
                        "issue asked the survey to find",
                "classes": ["Phaser", "Neuron", "Flanger"],
                "affected_presets": len(
                    set().union(*[per_class[n]["presets"]
                                  for n in ("Phaser", "Neuron", "Flanger")
                                  if n in per_class and per_class[n]["slots"]])
                    or set()),
            },
            "all_unpinnable_rng_classes": {
                "what": "every surveyed FX class whose sound depends on an "
                        "unpinnable RNG stream, modulation or not",
                "affected_presets": len(all_paths),
            },
        },
        "slates": slates,
        "affected_presets": [affected_presets[p]
                             for p in sorted(affected_presets)],
        "not_surveyed": ch["not_surveyed"],
        "claim_scope": (
            "Counts only. This record establishes no support claim for any "
            "preset, affected or not: the corpus is a prioritisation "
            "inventory (AGENTS.md), and nothing here renders, compares or "
            "listens. It bounds how much original-preset coverage the "
            "decision in DR-0013 costs -- an upper bound where a class's "
            "audibility conditionality was NOT_RUN."
        ),
    }

    out = repo / out_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {out_rel}")
    print(f"  corpus denominator            : {total}")
    for name, d in sorted(per_class.items()):
        if d["slots"]:
            print(f"    {name:<16}: {d['slots']:>4} slots, "
                  f"{len(d['presets']):>4} presets")
    print(f"  affected presets (union)      : {len(all_paths)} "
          f"({100 * len(all_paths) / total:.2f}% of corpus)")
    for name, s in sorted(slates.items()):
        print(f"  {name:<28}: {s['affected']}/256")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=str(REPO))
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()
    try:
        return run(Path(args.repo_root).resolve(), args.out)
    except Refuse as e:
        print(f"REFUSE: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
