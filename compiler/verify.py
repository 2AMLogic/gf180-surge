#!/usr/bin/env python3
"""SXT-020 validation harness (issue #13).

Four check families, all fail-closed (exit non-zero on any failure):

  image     parse a container: magic/version/lengths, container checksum,
            canonical-body re-serialization equality, body sha256, and —
            strongest — lossless graph reconstruction: the normalized graph
            rebuilt from the image body must hash to the header's
            normalized_graph_sha256.
  golden    recompile every manifest case (real presets re-read from
            graphs.jsonl with census-blob-sha assertion; synthetic cases from
            the committed input line) and require byte-identical images /
            identical outcome+codes for rejection records; additionally run
            the image and allocation checks on every compiled case.
  alloc     reconcile a compiled image's allocation section against a fresh
            SXT-015 account of the same source graph and against the bundle
            budgets recorded in the image header.
  controls  the live negative controls: a crafted graph carrying a
            profile-unsupported feature must produce the specific rejection
            and NEVER an image; a corrupted-checksum image must fail image
            verification; an FM3 oscillator compiles under B4-broad (it is
            IN the allowlist) and rejects under B2 (it is not).

Claim discipline: passing every check establishes structural/compiler
properties only — checksums, losslessness, allocation agreement with the
SXT-015 placeholder model, and rejection behavior. It establishes no
fidelity, support, or preset-quality claim, and no technology claim (all
allocation numbers are placeholders [PENDING-SXT-016]).
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from compiler import compile as C  # noqa: E402
from compiler.reject import (  # noqa: E402
    OUTCOME_COMPILED, catalog_codes,
)
from compiler.version import COMPILER_VERSION, IMAGE_FORMAT_VERSION  # noqa: E402
from tools.profile_predict import (  # noqa: E402
    Refuse, load_bundle_file, load_graphs, validate_spec,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" — " + detail) if detail else ""))
    return ok


# --------------------------------------------------------------------------
# image checks
# --------------------------------------------------------------------------

def image_checks(container_bytes, expect=None):
    """Full structural verification of one image. Returns (ok, parsed)."""
    try:
        parsed = C.parse_image(container_bytes)
    except C.ImageError as e:
        return check("image/parse", False, str(e)), None
    ok = check("image/parse", True, "%d bytes" % len(container_bytes))
    header, body = parsed["header"], parsed["body"]
    if expect is not None:
        ok &= check("image/header-expect", header == expect,
                    "header mismatch vs expectation")
    g = C.rebuild_graph(body)
    ok &= check("image/graph-lossless",
                C.graph_sha256(g) == header["normalized_graph_sha256"],
                "rebuilt graph hash vs header")
    ok &= check("image/body-sha",
                hashlib.sha256(parsed["body_bytes"]).hexdigest()
                == header["body_sha256"])
    ok &= check("image/format",
                header["format"] == IMAGE_FORMAT_VERSION
                and header["compiler_version"] == COMPILER_VERSION)
    ok &= check("image/profile-draft",
                header["profile"]["bundle_status"] == "DRAFT-NOT-FROZEN")
    return ok, parsed


# --------------------------------------------------------------------------
# allocation reconciliation
# --------------------------------------------------------------------------

def alloc_checks(parsed, spec):
    """Recompute the SXT-015 account for the image's source graph and require
    agreement with the image's allocation section, then check bundle budgets."""
    header, body = parsed["header"], parsed["body"]
    line = {"p": header["source"]["path"], "b": header["source"]["bank"],
            "sha": header["source"]["census_blob_sha1"],
            "sz": header["source"]["size_bytes"], "pin": header["pin"],
            "st": "normalized", "g": C.rebuild_graph(body)}
    acc = C._account(line, spec)
    alloc = body["derived"]["allocations"]
    mem = acc["memory"]
    ok = True
    ok &= check("alloc/on-chip-agrees",
                alloc["on_chip"]["total_bytes"] == mem["on_chip_state_bytes"],
                "%d vs %d" % (alloc["on_chip"]["total_bytes"],
                              mem["on_chip_state_bytes"]))
    ok &= check("alloc/external-agrees",
                alloc["external_writable"]["total_bytes"]
                == mem["external_writable_state_bytes"],
                "%d vs %d" % (alloc["external_writable"]["total_bytes"],
                              mem["external_writable_state_bytes"]))
    ok &= check("alloc/flash-agrees",
                alloc["flash_assets"]["total_bytes"]
                == acc["assets"]["embedded_flash_bytes"])
    ok &= check("alloc/bandwidth-agrees",
                alloc["bandwidth"]["ext_traffic_bytes_per_s"]
                == mem["ext_traffic_bytes_per_s"])
    # per-instance blocks: every configured instance has its own allocation;
    # two slots of one class are two blocks (never merged).
    inst_blocks = [b for b in alloc["on_chip"]["blocks"]
                   + alloc["external_writable"]["blocks"]
                   if b["kind"] == "fx_instance_state"]
    ok &= check("alloc/per-instance-blocks",
                len(inst_blocks) == len(acc["fx_instances"]),
                "%d blocks vs %d instances"
                % (len(inst_blocks), len(acc["fx_instances"])))
    by_slot = {b["slot"]: b for b in inst_blocks}
    region_ok = True
    for e in acc["fx_instances"]:
        b = by_slot.get(e["slot"])
        if b is None or b["size_bytes"] != e["state_bytes"]:
            region_ok = False
            continue
        want_region = ("external_writable" if e["external"] else "on_chip")
        if not any(x.get("slot") == e["slot"]
                   and x["kind"] == "fx_instance_state"
                   for x in alloc[want_region]["blocks"]):
            region_ok = False
    ok &= check("alloc/instance-sizes-and-regions", region_ok)
    # bundle budgets (from the image's own recorded spec)
    bud = alloc["budgets"]
    ok &= check("alloc/on-chip-budget",
                alloc["on_chip"]["total_bytes"] <= bud["on_chip_ram_bytes"])
    ok &= check("alloc/external-budget",
                alloc["external_writable"]["total_bytes"]
                <= bud["external_writable_bytes"])
    ok &= check("alloc/bandwidth-budget",
                alloc["bandwidth"]["ext_traffic_bytes_per_s"]
                <= bud["external_bandwidth_bytes_per_s"])
    ok &= check("alloc/budgets-match-image-spec",
                bud == {"on_chip_ram_bytes": spec["budgets"]["on_chip_ram_bytes"],
                        "external_writable_bytes":
                            spec["budgets"]["external_writable_bytes"],
                        "external_bandwidth_bytes_per_s":
                            spec["budgets"]["external_bandwidth_bytes_per_s"],
                        "cycle_closure": spec["budgets"]["cycle_closure"]})
    ok &= check("alloc/no-hidden-cycle-gate",
                alloc["cycles_placeholder_v0"]["note"].startswith("NOT GATED"))
    return ok


# --------------------------------------------------------------------------
# golden suite
# --------------------------------------------------------------------------

def _load_manifest(golden_dir):
    manifest = json.loads((golden_dir / "manifest.json").read_text())
    if manifest.get("compiler_version") != COMPILER_VERSION:
        return None, "manifest compiler_version %r != current %r" % (
            manifest.get("compiler_version"), COMPILER_VERSION)
    if manifest.get("image_format") != IMAGE_FORMAT_VERSION:
        return None, "manifest image_format mismatch"
    return manifest, None


def _source_line(case, by_path, golden_dir):
    src = case["source"]
    if src.get("synthetic"):
        line = json.loads(
            (golden_dir / "inputs" / (case["case"] + ".line.json")).read_text())
        return line, "synthetic"
    line = by_path.get(src["path"])
    if line is None:
        return None, "path not in graphs.jsonl"
    if line["sha"] != src["census_blob_sha1"]:
        return None, "census blob sha drift for %s" % src["path"]
    return line, "corpus"


def golden_suite(golden_dir=GOLDEN_DIR):
    ok = True
    manifest, err = _load_manifest(golden_dir)
    if manifest is None:
        check("golden/manifest", False, err)
        return False
    check("golden/manifest", True, "%d cases, bundle %s"
          % (len(manifest["cases"]), manifest["bundle_id"]))
    raw, bundles = load_bundle_file(Path(manifest["bundle_file"]))
    lines, observed, graphs_sha = load_graphs(Path(manifest["graphs"]))
    if manifest.get("graphs_sha256") != graphs_sha:
        check("golden/graphs-sha", False, "graphs.jsonl changed since golden "
              "generation; regenerate goldens")
        ok = False
    by_path = {d["p"]: d for d in lines}
    if manifest["bundle_id"] not in bundles:
        check("golden/bundle-id", False)
        return False
    spec = validate_spec(bundles[manifest["bundle_id"]], observed)
    bundle_sha = hashlib.sha256(
        Path(manifest["bundle_file"]).read_bytes()).hexdigest()
    if manifest.get("bundle_file_sha256") != bundle_sha:
        check("golden/bundle-sha", False, "bundle file changed since golden "
              "generation; regenerate goldens")
        ok = False

    with tempfile.TemporaryDirectory(prefix="sxt020-golden-"):
        for case in manifest["cases"]:
            name = case["case"]
            line, why = _source_line(case, by_path, golden_dir)
            if line is None:
                ok &= check("golden/%s/source" % name, False, why)
                continue
            outcome, obj, container = C.compile_line(
                line, spec, manifest["bundle_id"],
                "DRAFT-NOT-FROZEN", bundle_sha)
            exp = case["expected"]
            if outcome != exp["outcome"]:
                ok &= check("golden/%s/outcome" % name, False,
                            "got %s want %s codes=%s"
                            % (outcome, exp["outcome"],
                               ",".join(sorted({r["code"] for r in obj["codes"]})
                                        if outcome != OUTCOME_COMPILED else [])))
                continue
            if outcome == OUTCOME_COMPILED:
                ref = golden_dir / "compiled" / (name + ".image.bin")
                same = container == ref.read_bytes()
                ok &= check("golden/%s/byte-identical" % name, same,
                            "vs %s" % ref.name)
                if not same:
                    continue
                json_ref = golden_dir / "compiled" / (name + ".image.json")
                pretty = json.dumps(obj, sort_keys=True, indent=1,
                                    ensure_ascii=True, allow_nan=False) + "\n"
                ok &= check("golden/%s/json-pair" % name,
                            pretty == json_ref.read_text(),
                            "vs %s" % json_ref.name)
                parsed_ok, parsed = image_checks(container)
                ok &= parsed_ok
                if parsed is not None:
                    ok &= alloc_checks(parsed, spec)
                if exp.get("image_sha256"):
                    ok &= check("golden/%s/sha256" % name,
                                hashlib.sha256(container).hexdigest()
                                == exp["image_sha256"])
            else:
                codes = sorted({r["code"] for r in obj["codes"]})
                ok &= check("golden/%s/codes" % name,
                            codes == sorted(exp["codes"]),
                            "got %s want %s" % (codes, sorted(exp["codes"])))
                ref = (golden_dir / "rejected" / (name + ".rejection.json"))
                same = json.loads(ref.read_text()) == obj
                ok &= check("golden/%s/record-identical" % name, same,
                            "vs %s" % ref.name)
                img_ref = golden_dir / "compiled" / (name + ".image.bin")
                ok &= check("golden/%s/no-image-emitted" % name,
                            not img_ref.exists(),
                            "rejection must never ship an image")
    return ok


# --------------------------------------------------------------------------
# negative controls (issue #13 acceptance)
# --------------------------------------------------------------------------

def _synthetic_line(base_line, mutate):
    import copy
    line = copy.deepcopy(base_line)
    mutate(line["g"])
    return line


def negative_controls(golden_dir=GOLDEN_DIR):
    """Live controls; each targets one failure mode. Returns all-ok."""
    ok = True
    raw, bundles = load_bundle_file(REPO / "contracts" / "profile-v1-bundle-DRAFT.json")
    lines, observed, _ = load_graphs(REPO / "corpus" / "normalized" / "graphs.jsonl")
    by_path = {d["p"]: d for d in lines}
    spec_b4 = validate_spec(bundles["B4-broad"], observed)
    bundle_sha = hashlib.sha256(
        (REPO / "contracts" / "profile-v1-bundle-DRAFT.json").read_bytes()).hexdigest()
    base = by_path["resources/data/patches_factory/Basses/Attacky.fxp"]

    def run(line, spec):
        return C.compile_line(line, spec, "X", "DRAFT-NOT-FROZEN", bundle_sha)

    # NC1: a 9th enabled FX instance (B4 limit 8) -> fx_instance_overflow,
    # and NO image is ever produced for the graph. The mutation enables nine
    # existing slots (roles stay the engine's own), all with an in-bundle
    # class, so the instance limit is the only new binding gate.
    def add_9th(g):
        g["fxd"] = 0
        for s in g["fx"]:
            if s["i"] <= 8:
                s.update({"on": 1, "t": 3, "tn": "Phaser",
                          "p": [0.0] * 12, "rl": 0.0})
                s.pop("aw", None)
                s.pop("awn", None)
    line = _synthetic_line(base, add_9th)
    outcome, obj, container = run(line, spec_b4)
    codes = sorted({r["code"] for r in obj["codes"]}) \
        if outcome != OUTCOME_COMPILED else []
    ok &= check("nc1/9th-instance-rejected",
                outcome == "rejected" and "fx_instance_overflow" in codes,
                "outcome=%s codes=%s" % (outcome, codes))
    ok &= check("nc1/no-image-emitted", container is None,
                "trimmed image would defeat issue #13")
    ok &= check("nc1/rejection-cataloged",
                all(c in catalog_codes() for c in codes))

    # NC2 (brief-example nuance): an FM3 oscillator is IN B4-broad's
    # allowlist, so it must COMPILE there — and must reject under B2.
    # (Engine ot_FM3 = 5, read from the corpus.)
    def to_fm3(g):
        for sc in g["sc"]:
            sc["osc"][0]["t"] = 5
            sc["osc"][0]["tn"] = "FM3"
    fm3 = _synthetic_line(base, to_fm3)
    outcome_b4, _, container_b4 = run(fm3, spec_b4)
    ok &= check("nc2/fm3-compiles-under-B4", outcome_b4 == OUTCOME_COMPILED
                and container_b4 is not None,
                "FM3 is in B4's oscillator_allowlist")
    spec_b2 = validate_spec(bundles["B2-core-wet-plan3"], observed)
    outcome_b2, obj_b2, _ = run(fm3, spec_b2)
    codes_b2 = sorted({r["code"] for r in obj_b2["codes"]})
    ok &= check("nc2/fm3-rejected-under-B2",
                outcome_b2 == "rejected"
                and "oscillator_family_not_in_bundle" in codes_b2,
                "outcome=%s codes=%s (the B2 polylimit code is expected: "
                "B2's pool is 8 and the base stores 16)"
                % (outcome_b2, codes_b2))

    # NC3: corrupted-checksum image must fail verification.
    _, _, good_container = run(base, spec_b4)
    for label, mutated in (
            ("body-byte", good_container[:len(good_container) // 2]
             + bytes([good_container[len(good_container) // 2] ^ 1])
             + good_container[len(good_container) // 2 + 1:]),
            ("truncated", good_container[:-3])):
        try:
            C.parse_image(mutated)
            failed, why = False, "parse unexpectedly succeeded"
        except C.ImageError as e:
            failed, why = True, str(e)
        ok &= check("nc3/corruption-detected-%s" % label, failed, why)

    # NC4: the golden rejection records really are rejections (no compiled
    # image ships next to a rejection record).
    for rec in (golden_dir / "rejected").glob("*.rejection.json"):
        img = golden_dir / "compiled" / (rec.name.replace(
            ".rejection.json", ".image.bin"))
        ok &= check("nc4/no-image-for-%s" % rec.name.split("__")[0],
                    not img.exists())
    return ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_img = sub.add_parser("image", help="verify one image container")
    p_img.add_argument("file")
    p_g = sub.add_parser("golden", help="run the golden suite")
    p_g.add_argument("--golden-dir", default=str(GOLDEN_DIR))
    p_a = sub.add_parser("alloc", help="verify allocations of one image")
    p_a.add_argument("file")
    sub.add_parser("controls", help="run the negative controls")
    args = ap.parse_args(argv)

    if args.cmd == "image":
        ok, _ = image_checks(Path(args.file).read_bytes())
    elif args.cmd == "alloc":
        raw, bundles = load_bundle_file(
            REPO / "contracts" / "profile-v1-bundle-DRAFT.json")
        _lines, observed, _ = load_graphs(
            REPO / "corpus" / "normalized" / "graphs.jsonl")
        spec = validate_spec(bundles["B4-broad"], observed)
        _ok, parsed = image_checks(Path(args.file).read_bytes())
        ok = bool(_ok) and parsed is not None and alloc_checks(parsed, spec)
    elif args.cmd == "golden":
        ok = golden_suite(Path(args.golden_dir))
    else:
        ok = negative_controls()

    n_fail = sum(1 for _, s, _ in RESULTS if not s)
    print("---\n%s: %d checks, %d failed"
          % ("PASS" if ok else "FAIL", len(RESULTS), n_fail))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
