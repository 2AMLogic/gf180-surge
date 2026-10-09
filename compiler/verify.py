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

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# Block kinds whose offsets compiler/format.md section 5 makes normative:
# cumulative from 0 in a fixed order per address space.
_NORMATIVE_KINDS = ("voice_state_aggregate", "fx_instance_state",
                    "flash_asset_wavetable")


def expected_layout(acc, wta):
    """Re-derive the deterministic block layout of compiler/format.md section 5
    from the SXT-015 account and the source graph's wavetable records:
    on_chip = voice_state then on-chip fx_slot_N in slot order;
    external_writable = external fx_slot_N in slot order; flash_assets =
    wavetables with embedded bytes in record order. Offsets are cumulative.
    Returns {region: [(name, kind, offset, size_bytes), ...]}."""
    def pack(items):
        out, at = [], 0
        for name, kind, size in items:
            out.append((name, kind, at, size))
            at += size
        return out
    fx = list(acc["fx_instances"])
    return {
        "on_chip": pack(
            [("voice_state", "voice_state_aggregate",
              acc["voice"]["state_bytes_on_chip"])]
            + [("fx_slot_%d" % e["slot"], "fx_instance_state", e["state_bytes"])
               for e in fx if not e["external"]]),
        "external_writable": pack(
            [("fx_slot_%d" % e["slot"], "fx_instance_state", e["state_bytes"])
             for e in fx if e["external"]]),
        "flash_assets": pack(
            [("wavetable_s%s_o%s" % (w.get("sc"), w.get("osc")),
              "flash_asset_wavetable", w.get("emb") or 0)
             for w in wta if (w.get("emb") or 0) > 0]),
    }


def layout_checks(alloc, instances, expected=None):
    """Offset/interval/ownership checks on an allocation section (issue #392).

    Each address space (on_chip, external_writable, flash_assets) is checked
    independently: equal numeric offsets in different regions are not an
    overlap. Zero-length blocks are accepted (they must still carry an integer
    nonnegative offset <= total) and take no part in the overlap test.
    `instances` is the expected list of fx instances (SXT-015 account).
    `expected` (from expected_layout) reconciles every block of a normative
    kind against the compiler's cumulative fixed-order layout; blocks of any
    other kind (e.g. the zero-length probe control) are not part of that
    layout and are held only to the typing/containment/overlap checks.
    Structural checks only; no hardware-state-isolation claim.
    """
    ok = True
    regions = ("on_chip", "external_writable", "flash_assets")
    for reg in regions:
        sec = alloc[reg]
        blocks = sec["blocks"]
        total = sec["total_bytes"]
        typed = all(_is_int(b.get("offset")) and _is_int(b.get("size_bytes"))
                    and b["offset"] >= 0 and b["size_bytes"] >= 0
                    for b in blocks) and _is_int(total) and total >= 0
        ok &= check("alloc/offsets-integer-nonneg/%s" % reg, typed,
                    "%d blocks" % len(blocks))
        if not typed:
            ok &= check("alloc/blocks-contained/%s" % reg, False,
                        "skipped: non-integer or negative offset/size")
            ok &= check("alloc/no-overlap/%s" % reg, False,
                        "skipped: non-integer or negative offset/size")
            continue
        bad = [b["name"] for b in blocks
               if b["offset"] > total or b["offset"] + b["size_bytes"] > total]
        ok &= check("alloc/blocks-contained/%s" % reg, not bad,
                    ("out of range: %s" % ",".join(map(str, bad))) if bad
                    else "all blocks within total %d" % total)
        live = sorted((b for b in blocks if b["size_bytes"] > 0),
                      key=lambda b: (b["offset"], b["name"]))
        clash = [(a["name"], b["name"]) for a, b in zip(live, live[1:])
                 if b["offset"] < a["offset"] + a["size_bytes"]]
        ok &= check("alloc/no-overlap/%s" % reg, not clash,
                    ("overlap: %s" % clash) if clash else "no overlaps")
        if expected is not None:
            got = sorted(((b.get("name"), b.get("kind"), b.get("offset"),
                           b.get("size_bytes")) for b in blocks
                          if b.get("kind") in _NORMATIVE_KINDS), key=repr)
            exp = sorted(expected[reg], key=repr)
            diff = sorted(set(got) ^ set(exp), key=repr)
            ok &= check("alloc/cumulative-layout/%s" % reg, got == exp,
                        ("differs from format.md section 5 layout: %s"
                         % diff[:4]) if got != exp
                        else "%d blocks at cumulative offsets" % len(exp))
    inst = [b for reg in ("on_chip", "external_writable")
            for b in alloc[reg]["blocks"] if b["kind"] == "fx_instance_state"]
    slots = [b.get("slot") for b in inst]
    want = sorted(e["slot"] for e in instances)
    ok &= check("alloc/unique-slot-ownership",
                len(set(slots)) == len(slots) and sorted(slots) == want,
                "block slots %s vs instance slots %s" % (sorted(slots), want))
    # the duplicated fx_instances placement copy: exactly one entry per
    # expected slot (no missing, extra or duplicate owners) ...
    entries = alloc.get("fx_instances")
    entries = entries if isinstance(entries, list) else []
    eslots = [e.get("slot") if isinstance(e, dict) else None for e in entries]
    one_per_slot = (all(_is_int(v) for v in eslots)
                    and len(set(eslots)) == len(eslots)
                    and sorted(eslots) == want)
    ok &= check("alloc/fx-instances-one-per-slot", one_per_slot,
                "placement slots %s vs instance slots %s" % (eslots, want))
    # ... and only then must every entry agree with its block.
    if not one_per_slot:
        ok &= check("alloc/fx-instances-agree-with-blocks", False,
                    "skipped: placement entries are not one per slot")
        return ok
    where = {}
    for reg in ("on_chip", "external_writable"):
        for b in alloc[reg]["blocks"]:
            if b["kind"] == "fx_instance_state":
                where[b.get("slot")] = (reg, b["offset"], b["size_bytes"])
    agree = all(where.get(e.get("slot")) == (e.get("region"), e.get("offset"),
                                             e.get("size_bytes"))
                for e in entries)
    ok &= check("alloc/fx-instances-agree-with-blocks", agree,
                "%d entries" % len(entries))
    return ok


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
    try:
        expected = expected_layout(acc, line["g"].get("wta", []))
    except (KeyError, TypeError) as exc:
        expected = None
        ok &= check("alloc/cumulative-layout-derivable", False, repr(exc))
    ok &= layout_checks(alloc, acc["fx_instances"], expected)
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

    # NC5 (issue #392): allocation-layout controls. Each mutation rewrites the
    # golden four-fx-instance body, then recomputes body_sha256 and the
    # container digest, so image/* checks PASS and only the allocation layout
    # check named below can catch it. The inner check output is captured, not
    # printed, so an expected FAIL is not confused with a control failing.
    ok &= layout_controls(golden_dir, spec_b4)
    return ok


def _mutated_image(golden_dir, mutate):
    import copy
    data = (golden_dir / "compiled" / "four-fx-instance.image.bin").read_bytes()
    parsed = C.parse_image(data)
    header, body = copy.deepcopy(parsed["header"]), copy.deepcopy(parsed["body"])
    mutate(body["derived"]["allocations"])
    header["body_sha256"] = hashlib.sha256(C.canonical_json(body)).hexdigest()
    return C.build_container(header, body)


def _quiet_verify(container, spec):
    """Run image + alloc checks silently; return {check name: passed}."""
    import contextlib
    import io
    start = len(RESULTS)
    with contextlib.redirect_stdout(io.StringIO()):
        _ok, parsed = image_checks(container)
        if parsed is not None:
            alloc_checks(parsed, spec)
    got = RESULTS[start:]
    del RESULTS[start:]
    return {n: s for n, s, _ in got}


def _set_block(al, region, which, **kv):
    for b in al[region]["blocks"]:
        if b.get("slot") == which and b["kind"] == "fx_instance_state":
            b.update(kv)
    for e in al["fx_instances"]:
        if e["slot"] == which:
            e.update({k: v for k, v in kv.items() if k in ("offset",
                                                          "size_bytes")})


def layout_controls(golden_dir, spec):
    ok = True
    ext, onc = "external_writable", "on_chip"

    def dup_owner(al):
        _set_block(al, ext, 5, slot=4)

    def zero_len(al):
        # a zero-length block at a legal offset (== total) is accepted
        al[ext]["blocks"].append({"kind": "fx_instance_state_probe",
                                  "name": "zero_len_probe", "offset":
                                  al[ext]["total_bytes"], "size_bytes": 0})

    def reverse_packing(al):
        # swap the two external blocks' order: slot 5 at 0, slot 4 after it
        blk = {b["slot"]: b for b in al[ext]["blocks"]
               if b["kind"] == "fx_instance_state"}
        _set_block(al, ext, 5, offset=0)
        _set_block(al, ext, 4, offset=blk[5]["size_bytes"])

    # (label, mutation, check that must FAIL or None for must-pass)
    negatives = (
        ("overlap", lambda al: _set_block(al, ext, 5, offset=0),
         "alloc/no-overlap/external_writable"),
        ("overlap-on-chip", lambda al: _set_block(al, onc, 1, offset=181760),
         "alloc/no-overlap/on_chip"),
        ("out-of-range", lambda al: _set_block(
            al, ext, 5, offset=al[ext]["total_bytes"] - 1),
         "alloc/blocks-contained/external_writable"),
        ("negative-offset", lambda al: _set_block(al, ext, 4, offset=-1),
         "alloc/offsets-integer-nonneg/external_writable"),
        ("bool-offset", lambda al: _set_block(al, ext, 4, offset=True),
         "alloc/offsets-integer-nonneg/external_writable"),
        ("duplicate-slot-ownership", dup_owner, "alloc/unique-slot-ownership"),
        # nonoverlapping, contained, checksum-valid, but reverses the
        # format.md section 5 cumulative slot order (both placement copies)
        ("reverse-packing", reverse_packing,
         "alloc/cumulative-layout/external_writable"),
        ("fx-instances-empty", lambda al: al.update(fx_instances=[]),
         "alloc/fx-instances-one-per-slot"),
        ("fx-instances-omitted", lambda al: al["fx_instances"].pop(),
         "alloc/fx-instances-one-per-slot"),
        ("fx-instances-duplicate", lambda al: al["fx_instances"].append(
            dict(al["fx_instances"][0])), "alloc/fx-instances-one-per-slot"),
    )
    for label, mut, want in negatives:
        res = _quiet_verify(_mutated_image(golden_dir, mut), spec)
        image_ok = all(v for n, v in res.items() if n.startswith("image/"))
        ok &= check("nc5/%s-fails-%s" % (label, want),
                    image_ok and res.get(want) is False,
                    "image checks pass=%s; targeted check=%s"
                    % (image_ok, res.get(want)))
    # positives: the unmutated golden (on_chip voice_state @0 and external
    # fx_slot_4 @0 already share offset 0 across address spaces) and a
    # zero-length block must both pass every layout check.
    for label, mut in (("cross-address-space-equal-offsets", lambda al: None),
                       ("zero-length-block", zero_len)):
        res = _quiet_verify(_mutated_image(golden_dir, mut), spec)
        lay = {n: v for n, v in res.items()
               if n.startswith("alloc/") and ("offsets" in n or "contained" in n
                                              or "overlap" in n
                                              or "ownership" in n
                                              or "cumulative" in n
                                              or "fx-instances" in n)}
        ok &= check("nc5/%s-accepted" % label,
                    bool(lay) and all(lay.values())
                    and all(v for n, v in res.items() if n.startswith("image/")),
                    "%d layout checks" % len(lay))
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
