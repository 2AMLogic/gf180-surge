#!/usr/bin/env python3
"""#544 -- T1 physical-flow evidence (items 2/3/4/11), Phase A.

PINS: for each synthesized product group, the committed routed stream is
bound by content hash to its DRC, LVS and ERC reports; a recorded tool failure
is never silently dropped; reports carry no absolute host paths; the
supply-spec declares ties[]; and `signoff/block-manifest.json` cites items
2/3/4/11 only once all `product` groups have passing physical-flow evidence
(live negative control included). The open-pin probe records
(`<g>/open_pin_probe.json`) are bound by content hash to the committed routed
stream and carry the pinned tool identity; their input findings are asserted
only on (instance, pin) identity, never on `$N` net names (klt issue #1063).
DOES NOT: establish that DRC/LVS/ERC are clean (outcomes are recorded as the
tools reported them), timing, corners, "gf180mcu implementation", or fidelity;
explain why the open pins are open or attribute them to the router.
Coverage (groups with a stream / all product groups) is reported separately.
"""
import copy
import gzip
import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "signoff" / "t1-physical"
ITEMS = ("2", "3", "4", "11")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def product_groups():
    return [g["id"] for g in json.loads(
        (ROOT / "rtl" / "lint_manifest.json").read_text())["groups"]]


def physical_groups():
    return sorted(p.parent.name for p in BASE.glob("*/exit_status.json")
                  if p.parent.name != "negative-control")


def read(group, name):
    """Bytes of a committed artifact; large ones are stored as `<name>.gz`."""
    f = BASE / group / name
    if f.exists():
        return f.read_bytes()
    return gzip.decompress((BASE / group / (name + ".gz")).read_bytes())


def load(group, name):
    return json.loads(read(group, name))


def stream_hash(group):
    top = group
    return "sha256:" + sha(read(group, f"{top}.gds"))


def binding_problems(group):
    """Names every report whose recorded stream hash differs from the stream."""
    want = stream_hash(group)
    problems = []
    drc = load(group, "drc.report.json")
    if drc["provenance"]["input"]["content_hash"] != want:
        problems.append("drc")
    lvs = load(group, "lvs.report.json")
    if "sha256:" + lvs["environment"]["layout_sha256"] != want:
        problems.append("lvs")
    erc = load(group, "erc.report.json")
    if erc["provenance"]["input"]["content_hash"] != want:
        problems.append("erc")
    return problems


def citation_ok(manifest, covered, all_groups):
    """Items 2/3/4/11 may be cited only when every product group is covered
    with passing evidence."""
    cited = [i for i in ITEMS if i in manifest.get("evidence", {})]
    if not cited:
        return True
    return set(covered) >= set(all_groups)


class T1Physical(unittest.TestCase):
    def test_three_synthesized_groups_have_recorded_outcomes(self):
        self.assertEqual(
            physical_groups(), ["control_top", "ext_mem_instr", "wavetable_core"])
        for g in physical_groups():
            st = load(g, "exit_status.json")
            self.assertEqual(st["place-and-route"], 0, g)
            for k in ("drc", "lvs", "erc"):
                self.assertIn(k, st, g)
            # a nonzero tool exit is a recorded finding, never omitted
            for k in ("drc.report.json", "lvs.report.json", "erc.report.json"):
                self.assertTrue(read(g, k).strip(), (g, k))

    def test_reports_bound_by_hash_to_stream(self):
        for g in physical_groups():
            self.assertEqual(binding_problems(g), [], g)

    def test_streams_come_from_committed_netlists(self):
        for g in physical_groups():
            rep = load(g, "pnr.report.json")
            self.assertEqual(rep["status"], "ok", g)
            self.assertEqual(rep["stage_reached"], "route", g)

    def test_reports_have_no_absolute_host_paths(self):
        for g in physical_groups():
            for p in (BASE / g).glob("*.json*"):
                text = read(g, p.name.removesuffix(".gz")).decode()
                self.assertNotIn("/home/", text, str(p))

    def test_supply_spec_declares_ties(self):
        spec = json.loads((BASE / "erc-supply-spec.json").read_text())
        self.assertTrue(spec["ties"])
        self.assertTrue(all(n["kind"] == "supply" for n in spec["nets"]))
        for g in physical_groups():
            erc = load(g, "erc.report.json")
            self.assertEqual(erc["spec"], "signoff/t1-physical/erc-supply-spec.json")

    def test_negative_control_stale_stream_breaks_binding(self):
        g = physical_groups()[0]
        want = "sha256:" + sha(read(g, f"{g}.gds") + b"\0")
        self.assertNotEqual(
            load(g, "drc.report.json")["provenance"]["input"]["content_hash"], want)

    def test_negative_control_recorded_failures_are_not_clean(self):
        # The recorded DRC/LVS/ERC outcomes are findings, not waivers: a
        # nonzero tool exit must stay visible in exit_status.json, and a
        # group with one cannot count as passing evidence for the rule.
        failing = [g for g in physical_groups()
                   if any(load(g, "exit_status.json")[k] != 0
                          for k in ("drc", "lvs", "erc"))]
        self.assertTrue(failing, "expected recorded tool failures at Phase A")
        for g in failing:
            fake = {"evidence": {"3": {"file": "x"}}}
            self.assertFalse(citation_ok(fake, [g], product_groups()))

    def test_manifest_cites_items_only_when_all_groups_covered(self):
        manifest = json.loads(
            (ROOT / "signoff" / "block-manifest.json").read_text())
        covered, allg = physical_groups(), product_groups()
        self.assertLess(len(covered), len(allg))  # Phase A: 3 of 11
        for i in ITEMS:
            self.assertNotIn(i, manifest["evidence"], f"item {i} cited early")
        self.assertTrue(citation_ok(manifest, covered, allg))

    def test_negative_control_early_citation_fails_the_rule(self):
        manifest = {"evidence": {"3": {"file": "x"}}}
        self.assertFalse(
            citation_ok(manifest, physical_groups(), product_groups()))


NC = BASE / "negative-control"


def nc_json(name):
    f = NC / name
    if f.exists():
        return json.loads(f.read_bytes())
    return json.loads(gzip.decompress((NC / (name + ".gz")).read_bytes()))


def mutated_netlist():
    m = json.loads((NC / "mutation.json").read_text())
    lines = (ROOT / m["base_netlist"]).read_text().split("\n")
    assert lines[m["line"] - 1] == m["from"], "base netlist drifted"
    lines[m["line"] - 1] = m["to"]
    return "\n".join(lines)


ERC_KLT = "0.9.2"
ERC_METALS = ("Metal1", "Metal2", "Metal3", "Metal4", "Metal5")


def erc_antenna_problems(erc):
    """(#803) every way a committed ERC report's antenna coverage falls
    short, as a list of strings -- so the live negative controls can re-audit
    a mutated copy with the same code the positive tests run. Full coverage
    = a nonzero gate count and exactly one level for each of Metal1..Metal5
    on every gate, each with a table limit, a rule source and a pass or
    violate verdict, with `coverage.checked` reconciling to exactly those
    gate/metal pairs. The gate role `poly` is inapplicable (klt never grades
    stackup[0]) and must stay ungraded. Any skip -- `missing_antenna_pdk`
    (the 0.8.0 shape) or `missing_antenna_limit` (the lowercase-spec shape)
    -- is a problem, never a pass; a `violate` verdict is not."""
    v = []
    gates = erc.get("gates") or []
    if not gates or not erc.get("gate_count"):
        return ["no gates: antenna coverage would pass vacuously"]
    if len(gates) != erc["gate_count"]:
        v.append(f"gates listed {len(gates)} != gate_count {erc['gate_count']}")
    pairs = set()
    ids = [g["gate_id"] for g in gates]
    if len(set(ids)) != len(ids):
        v.append(f"gate ids not unique: {len(ids)} gates, {len(set(ids))} "
                 "distinct (a gate is missing or duplicated)")
    for gate in gates:
        metals = [l for l in gate["levels"] if l["layer"] in ERC_METALS]
        names = [l["layer"] for l in metals]
        for metal in ERC_METALS:
            if names.count(metal) != 1:
                v.append(f"{gate['gate_id']}: {names.count(metal)} levels "
                         f"for {metal}, want exactly one")
        for l in metals:
            pairs.add((gate["gate_id"], l["layer"]))
            if l.get("antenna_ratio_max") is None:
                v.append(f"{gate['gate_id']}/{l['layer']}: no table limit")
            if not l.get("antenna_ratio_source"):
                v.append(f"{gate['gate_id']}/{l['layer']}: no rule source")
            if l.get("verdict") not in ("pass", "violate"):
                v.append(f"{gate['gate_id']}/{l['layer']}: verdict "
                         f"{l.get('verdict')!r} is not a checked verdict")
        poly = [l for l in gate["levels"] if l["layer"] == "poly"]
        if len(poly) != 1:
            v.append(f"{gate['gate_id']}: gate role 'poly' level missing")
        elif poly[0].get("antenna_ratio_max") is not None \
                or poly[0].get("verdict") != "unchecked":
            v.append(f"{gate['gate_id']}: gate role 'poly' must stay ungraded")
    cov = erc.get("coverage", {})
    if not cov.get("checked"):
        v.append("no checked antenna levels")
    checked = []
    for c in cov.get("checked", []):
        cid = c["id"] if isinstance(c, dict) else c
        checked.append(tuple(json.loads(cid.split(":", 1)[1])))
    if len(checked) != len(set(checked)):
        v.append(f"coverage.checked holds duplicate gate/metal records "
                 f"({len(checked)} records, {len(set(checked))} distinct)")
    if len(checked) != len(gates) * len(ERC_METALS):
        v.append(f"coverage.checked holds {len(checked)} records, want "
                 f"exactly {len(gates) * len(ERC_METALS)} (one per "
                 "expected gate/metal pair)")
    checked = set(checked)
    if checked != pairs:
        v.append(f"coverage.checked holds {len(checked)} gate/metal pairs, "
                 f"the gates' levels hold {len(pairs)}")
    for s in cov.get("skipped", []):
        v.append(f"skipped {s['id']}: {s['reason']}")
    return v


class T1PhysicalTriage(unittest.TestCase):
    """#544 Phase A2: triage pins. Recorded, not waived."""

    def test_flow_config_matches_triage(self):
        # DRC triage: tap pitch 30 um (rule cap 15 um) and no pdngen
        # split_cuts (source of every ongrid / via width hit).
        for g in physical_groups():
            power = json.loads((BASE / g / "request.json").read_text())["power"]
            self.assertEqual(power["tapcell"], {"distance_um": 30}, g)
            for c in power["connects"]:
                self.assertNotIn("split_cuts", c, g)

    def test_drc_exit_matches_report(self):
        for g in physical_groups():
            drc = load(g, "drc.report.json")
            self.assertEqual(drc["violation_count"], sum(drc["rule_counts"].values()), g)
            self.assertEqual(
                load(g, "exit_status.json")["drc"] == 0, drc["status"] == "clean", g)
            self.assertFalse(drc["coverage"]["nothing_checked"], g)

    def test_drc_clean_after_flow_triage(self):
        # Result of the triage config above: all three streams are DRC-clean
        # under the curated gf180mcu deck (was 94045 / 107856 / 19850).
        for g in physical_groups():
            self.assertEqual(load(g, "drc.report.json")["status"], "clean", g)

    def test_ext_mem_instr_lvs_mismatch_is_recorded_with_named_instances(self):
        # Undiagnosed physical cause; the failing check stays recorded, not
        # waived. Four instances (clkload1/2/3 and _10285_) and six net splits.
        lvs = load("ext_mem_instr", "lvs.report.json")
        self.assertEqual(lvs["status"], "mismatch")
        errs = [m for m in lvs["mismatches"] if m["severity"] == "error"]
        self.assertEqual(len(errs), lvs["error_count"])
        self.assertEqual(lvs["category_error_counts"], {"net.split": 6, "topology": 8})
        ref = {m["instance"]["reference"] for m in errs
               if m["instance"] and m["instance"]["reference"]}
        self.assertEqual(ref, {"CLKLOAD1", "CLKLOAD2", "CLKLOAD3", "_10285_"})
        self.assertNotEqual(load("ext_mem_instr", "exit_status.json")["lvs"], 0)
        for g in ("control_top", "wavetable_core"):
            self.assertEqual(load(g, "lvs.report.json")["status"], "match", g)

    def test_erc_full_antenna_coverage_under_klt_092(self):
        # #803: ERC re-run under klt 0.9.2 (`--pdk gf180mcu`) through the
        # case-matched Metal1..Metal5 role names. Recorded outcome for all
        # three groups: every gate has one graded level per metal with a
        # table limit and rule source, zero skipped pairs, status clean,
        # exit 0, no electrical findings. Nothing here waives a finding: a
        # future `violate` stays a checked level and a nonzero exit.
        for g in physical_groups():
            erc = load(g, "erc.report.json")
            self.assertEqual(erc["provenance"]["klt_version"], ERC_KLT, g)
            self.assertEqual(erc["pdk"], "gf180mcu", g)
            self.assertEqual(erc_antenna_problems(erc), [], g)
            self.assertEqual(erc["status"], "clean", g)
            self.assertEqual(erc["erc_status"], "clean", g)
            self.assertEqual(erc["erc_finding_count"],
                             len(erc["erc_findings"]), g)
            self.assertEqual(load(g, "exit_status.json")["erc"], 0, g)

    def test_erc_bound_to_mapped_spec_and_092_version(self):
        # Each ERC report is bound to the mapped supply spec (content hash)
        # and states the klt that produced it; DRC/LVS/P&R reports stay
        # 0.8.0 -- the pin did not move (#803 keeps requirements.txt).
        spec = BASE / "erc-supply-spec.json"
        want = "sha256:" + sha(spec.read_bytes())
        names = [e["name"] for e in json.loads(spec.read_text())["stackup"]]
        self.assertEqual(names, ["poly", *ERC_METALS])
        for g in physical_groups():
            erc = load(g, "erc.report.json")
            self.assertEqual(
                erc["spec"], "signoff/t1-physical/erc-supply-spec.json", g)
            self.assertEqual(erc["provenance"]["spec"]["content_hash"], want, g)
            drc = load(g, "drc.report.json")
            self.assertEqual(
                drc["provenance"]["klt_version"],
                (ROOT / "signoff" / "requirements.txt").read_text().strip()
                .split("==")[1], g)


class T1PhysicalNegativeControl(unittest.TestCase):
    """The DRC and LVS checks must demonstrably fail on violated inputs."""

    def test_drc_sliver_fails_named_rule(self):
        drc = nc_json("drc.report.json")
        self.assertEqual(drc["status"], "violations")
        self.assertEqual(drc["rule_counts"], {"metal2.width.1": 1})
        self.assertEqual(
            drc["provenance"]["input"]["content_hash"],
            "sha256:" + sha((NC / "drc-sliver.gds").read_bytes()))
        self.assertEqual(nc_json("exit_status.json")["drc"], 3)

    def test_lvs_mutation_fails_against_committed_stream(self):
        lvs = nc_json("lvs.report.json")
        self.assertEqual(lvs["status"], "mismatch")
        self.assertGreater(lvs["error_count"], 0)
        env = lvs["environment"]
        self.assertEqual(
            env["layout_sha256"], sha(read("wavetable_core", "wavetable_core.gds")))
        self.assertEqual(env["reference_sha256"], sha(mutated_netlist().encode()))
        self.assertNotEqual(
            sha(mutated_netlist().encode()),
            sha(read("wavetable_core", "wavetable_core.v")))
        self.assertEqual(nc_json("exit_status.json")["lvs"], 3)

    def test_clean_group_stays_clean_where_control_fails(self):
        # The same checks pass on the unmutated wavetable_core, so the control
        # failure is attributable to the injected defect.
        self.assertEqual(load("wavetable_core", "lvs.report.json")["status"], "match")
        self.assertEqual(load("wavetable_core", "drc.report.json")["status"], "clean")

    def test_erc_lowercase_spec_control_fails_antenna_coverage(self):
        # #803 failure control: the retained pre-mapping spec (lowercase role
        # names) on the SAME wavetable_core stream and the SAME klt 0.9.2
        # misses every gf180mcu table key -- zero checked, every intended
        # metal level skipped `missing_antenna_limit`, exit 4. The positive
        # coverage check must reject this report.
        erc = nc_json("erc.report.json")
        lc = NC / "erc-supply-spec-lowercase.json"
        self.assertEqual(erc["provenance"]["klt_version"], ERC_KLT)
        self.assertEqual(
            erc["provenance"]["input"]["content_hash"],
            stream_hash("wavetable_core"))
        self.assertEqual(
            erc["provenance"]["spec"]["content_hash"], "sha256:" + sha(lc.read_bytes()))
        names = [e["name"] for e in json.loads(lc.read_text())["stackup"]]
        self.assertEqual(
            names, ["poly", "metal1", "metal2", "metal3", "metal4", "metal5"])
        self.assertEqual(erc["coverage"]["checked"], [])
        self.assertEqual(
            {s["reason"] for s in erc["coverage"]["skipped"]},
            {"missing_antenna_limit"})
        bad = erc_antenna_problems(erc)
        self.assertTrue(any("no checked antenna levels" in x for x in bad), bad)
        self.assertTrue(any("missing_antenna_limit" in x for x in bad), bad)
        self.assertEqual(nc_json("exit_status.json")["erc"], 4)

    def test_erc_control_stale_0080_report_fails_the_positive_checks(self):
        # Regress a copy of the committed report to the recorded 0.8.0 shape
        # (klt 0.8.0, pdk null, every level unchecked with
        # missing_antenna_pdk): the coverage check must reject it, so a
        # committed PASS record cannot silently go stale.
        erc = copy.deepcopy(load("wavetable_core", "erc.report.json"))
        erc["provenance"]["klt_version"] = "0.8.0"
        erc["pdk"] = None
        erc["coverage"]["checked"] = []
        erc["coverage"]["skipped"] = [
            {"id": 'antenna:["gate0","metal1"]', "reason": "missing_antenna_pdk"}]
        for gate in erc["gates"]:
            for lv in gate["levels"]:
                lv["antenna_ratio_max"] = None
                lv["antenna_ratio_source"] = None
                lv["verdict"] = "unchecked"
        self.assertNotEqual(erc["provenance"]["klt_version"], ERC_KLT)
        bad = erc_antenna_problems(erc)
        self.assertTrue(any("no checked antenna levels" in x for x in bad), bad)
        self.assertTrue(any("missing_antenna_pdk" in x for x in bad), bad)
        self.assertTrue(any("not a checked verdict" in x for x in bad), bad)

    def test_erc_control_missing_gate_duplicate_id_fails_coverage(self):
        # Review of #806: with 513 declared gates, the last gate replaced by
        # a copy of the first (512 distinct ids) and its five checked
        # entries removed (2560 pairs) used to pass, because the check
        # compared sets. Duplicate ids and a record count off the expected
        # gate x metal total must each be rejected.
        erc = copy.deepcopy(load("wavetable_core", "erc.report.json"))
        self.assertEqual(erc_antenna_problems(erc), [])
        last = erc["gates"][-1]["gate_id"]
        erc["gates"][-1] = copy.deepcopy(erc["gates"][0])
        erc["coverage"]["checked"] = [
            c for c in erc["coverage"]["checked"]
            if not (c["id"] if isinstance(c, dict) else c).startswith(
                f'antenna:["{last}",')]
        self.assertEqual(len(erc["gates"]), erc["gate_count"])
        bad = erc_antenna_problems(erc)
        self.assertTrue(any("not unique" in x for x in bad), bad)
        self.assertTrue(any("want exactly" in x for x in bad), bad)

    def test_regen_every_erc_path_uses_the_shared_092_invocation(self):
        # Review of #806: `check_group` (full flow and --checks-only) ran
        # `klt erc` under the 0.8.0 flow pin without --pdk, losing every
        # antenna level. All four ERC paths must go through `run_erc`.
        import ast
        src = (BASE / "regen.py").read_text()
        tree = ast.parse(src)
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in ("check_group", "erc_only", "erc_control"):
            calls = {c.func.id for c in ast.walk(fns[name])
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            self.assertIn("run_erc", calls, name)
        for name, fn in fns.items():
            if name == "run_erc":
                continue
            for c in ast.walk(fn):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                        and c.func.id == "klt" and c.args
                        and getattr(c.args[0], "value", None) == "erc"):
                    self.fail(f"{name} calls klt erc directly")
        run = ast.get_source_segment(src, fns["run_erc"])
        self.assertIn('"--pdk", "gf180mcu"', run)
        self.assertIn("version=ERC_KLT", run)

    def test_erc_control_duplicate_checked_record_fails_coverage(self):
        # One gate/metal record replaced by a duplicate of another keeps the
        # set and the length-per-gate view plausible; it must still fail.
        erc = copy.deepcopy(load("wavetable_core", "erc.report.json"))
        erc["coverage"]["checked"][-1] = copy.deepcopy(
            erc["coverage"]["checked"][0])
        bad = erc_antenna_problems(erc)
        self.assertTrue(any("duplicate" in x for x in bad), bad)


# #679 -- committed open-pin probe records: `signoff/t1-physical/<g>/
# open_pin_probe.json`, produced by `signoff/t1-physical/open_pin_probe.py`
# (not a pytest-time run). The records are the artifact; these tests only
# re-bind them: stream hash, pinned tool identity, and the input findings on
# (instance, pin) identity. Net names stay unasserted (klt issue #1063).
PROBE_GROUPS = ("control_top", "ext_mem_instr")
EXPECT_OPEN_INPUTS = {
    ("gf180mcu_fd_sc_mcu9t5v0__clkinv_12_0", "I"),
    ("gf180mcu_fd_sc_mcu9t5v0__clkinv_12_1", "I"),
    ("gf180mcu_fd_sc_mcu9t5v0__clkinv_16_0", "I"),
    ("gf180mcu_fd_sc_mcu9t5v0__inv_8_0", "I"),
}
# #747: measured tie-cell decomposition of the findings. The writer computes
# the tally from the record's own findings; this pins the measured numbers so
# a re-extraction that shifts them cannot pass silently. Measured on the
# committed records: pnr_single_pin_markers equals exactly the unused
# tie-cell output subset (tiel/ZN, tieh/Z), not summary.single_pin_nets.
TIE_OUTPUT_PINS = {"tiel": "ZN", "tieh": "Z"}
EXPECT_TIE_TALLY = {
    "ext_mem_instr": {
        ("gf180mcu_fd_sc_mcu9t5v0__tiel", "ZN"): 44,
        ("gf180mcu_fd_sc_mcu9t5v0__tieh", "Z"): 2,
    },
    "control_top": {
        ("gf180mcu_fd_sc_mcu9t5v0__tiel", "ZN"): 37,
        ("gf180mcu_fd_sc_mcu9t5v0__tieh", "Z"): 1,
    },
}


def tie_output_tally(findings):
    """{(master, pin): count} of the unused tie-cell output findings,
    recomputed here independently of whatever the record carries."""
    t = {}
    for f in findings:
        stem = f["master"].rsplit("__", 1)[-1]
        if TIE_OUTPUT_PINS.get(stem) == f["pin"]:
            t[(f["master"], f["pin"])] = t.get((f["master"], f["pin"]), 0) + 1
    return t


def probe_record(group):
    return load(group, "open_pin_probe.json")


def probe_violations(rec):
    """Everything wrong with one open-pin probe record, as a list of strings,
    so the live negative controls can mutate a copy and re-audit with the
    same code the positive tests run. An unresolved liberty is NO_VERDICT and
    an examined-input-pin tally of 0 is the anti-vacuity leg: both fail
    loudly instead of letting "zero input findings" pass vacuously."""
    v = []
    g = rec["group"]
    prov = rec["provenance"]
    if prov["pin"] != (ROOT / "signoff" / "requirements.txt").read_text().strip():
        v.append(f"{g}: recorded pin differs from signoff/requirements.txt")
    if prov["stream_content_hash"] != stream_hash(g):
        v.append(f"{g}: stream hash differs from the committed .gds.gz")
    pin = json.loads((ROOT / "signoff" / "t1-item1" / "pdk-pin.json").read_text())
    lib = prov["liberty"]
    if lib["content_hash"] != pin["liberty"]["content_hash"] \
            or lib["revision"] != pin["pdk"]["revision"]:
        v.append(f"{g}: liberty identity differs from signoff/t1-item1/pdk-pin.json")
    if not prov["klt_version"]:
        v.append(f"{g}: record carries no klt version")
    if not lib["resolved"]:
        v.append(f"NO_VERDICT: {g}: liberty unresolved, directions are null "
                 f"({lib['reason']})")
    if rec["pins_examined"].get("input", 0) <= 0:
        v.append(f"NO_VERDICT: {g}: zero input pins examined -- the "
                 f"zero-input-findings check would pass vacuously")
    inputs = sorted((f["instance"], f["pin"]) for f in rec["findings"]
                    if f["direction"] == "input")
    if g == "ext_mem_instr" and inputs != sorted(EXPECT_OPEN_INPUTS):
        v.append(f"{g}: open input pins {inputs} != the recorded four")
    if g == "control_top" and inputs:
        v.append(f"{g}: negative control has open input pins {inputs}")
    # #747: the corroboration block must carry the tie-cell subset tally,
    # computed from this record's own findings, agreeing exactly with the
    # pnr marker count. An absent or hand-typed tally fails here.
    cor = rec.get("corroboration", {})
    if rec.get("schema") != "gf180-surge.open-pin-probe/2":
        v.append(f"{g}: schema {rec.get('schema')!r} != the /2 shape with the "
                 f"tie-subset corroboration")
    tally = tie_output_tally(rec["findings"])
    tie_total = sum(tally.values())
    want_tally = {f"{m}/{p}": n for (m, p), n in tally.items()}
    if cor.get("tie_cell_output_tally") != want_tally:
        v.append(f"{g}: recorded tie tally {cor.get('tie_cell_output_tally')} "
                 f"!= {want_tally} recomputed from the findings")
    if cor.get("tie_cell_output_findings") != tie_total:
        v.append(f"{g}: recorded tie total "
                 f"{cor.get('tie_cell_output_findings')} != {tie_total} "
                 f"recomputed from the findings")
    if cor.get("tie_cell_output_findings") != cor.get("pnr_single_pin_markers"):
        v.append(f"{g}: tie subset {cor.get('tie_cell_output_findings')} != "
                 f"pnr markers {cor.get('pnr_single_pin_markers')} -- the "
                 f"exact-agreement annotation no longer holds")
    if cor.get("non_tie_single_pin_findings") != len(rec["findings"]) - tie_total:
        v.append(f"{g}: non-tie count != findings minus the tie subset")
    if cor.get("tie_cell_output_findings", 0) \
            + cor.get("non_tie_single_pin_findings", 0) \
            != rec["summary"]["single_pin_nets"]:
        v.append(f"{g}: tie + non-tie != summary.single_pin_nets")
    if cor.get("open_input_findings_not_in_markers") \
            != rec["summary"]["findings_by_direction"].get("input", 0):
        v.append(f"{g}: open-input count != findings_by_direction.input")
    if tally != EXPECT_TIE_TALLY[g]:
        v.append(f"{g}: measured tie tally {tally} != the committed "
                 f"measurement {EXPECT_TIE_TALLY[g]}")
    return v


class T1PhysicalOpenPinProbe(unittest.TestCase):
    """#679: the committed open-pin probe records re-bind to their streams.

    Pins the record's binding to the stream and its input findings on
    (instance, pin) identity. DOES NOT: explain the opens, attribute them to
    the router, or establish anything about fidelity, synthesis or hardware.
    """

    def test_records_rebind_to_streams_and_pins(self):
        for g in PROBE_GROUPS:
            rec = probe_record(g)
            self.assertEqual(rec["group"], g)
            self.assertEqual(probe_violations(rec), [], g)

    def test_negative_control_zero_input_tally_fails_the_anti_vacuity_leg(self):
        rec = copy.deepcopy(probe_record("control_top"))
        rec["pins_examined"]["input"] = 0
        bad = probe_violations(rec)
        self.assertTrue(any("vacuously" in x for x in bad), bad)

    def test_negative_control_flipped_direction_fails_control_top(self):
        rec = copy.deepcopy(probe_record("control_top"))
        self.assertTrue(rec["findings"])
        rec["findings"][0]["direction"] = "input"
        bad = probe_violations(rec)
        self.assertTrue(any("negative control has open input pins" in x
                            for x in bad), bad)

    def test_negative_control_perturbed_tie_master_breaks_the_tally(self):
        # If a re-extraction moved one net out of the tie subset, a stale or
        # hand-typed recorded tally must stop matching the findings (#747).
        rec = copy.deepcopy(probe_record("ext_mem_instr"))
        tie = next(f for f in rec["findings"]
                   if f["master"].endswith("__tiel") and f["pin"] == "ZN")
        tie["master"] = tie["master"].replace("__tiel", "__inv_3")
        bad = probe_violations(rec)
        self.assertTrue(any("tie tally" in x for x in bad), bad)
        self.assertTrue(any("committed measurement" in x for x in bad), bad)

    def test_negative_control_consistent_recount_still_breaks_exact_agreement(self):
        # The stronger control (#747): recompute the block honestly from the
        # perturbed findings (as a re-run writer would), so every recorded
        # number is internally consistent again -- the exact agreement with
        # the pnr markers must be the leg that now fails.
        rec = copy.deepcopy(probe_record("ext_mem_instr"))
        tie = next(f for f in rec["findings"]
                   if f["master"].endswith("__tiel") and f["pin"] == "ZN")
        tie["master"] = tie["master"].replace("__tiel", "__inv_3")
        t = tie_output_tally(rec["findings"])
        tie_total = sum(t.values())
        cor = rec["corroboration"]
        cor["tie_cell_output_tally"] = {f"{m}/{p}": n
                                        for (m, p), n in t.items()}
        cor["tie_cell_output_findings"] = tie_total
        cor["non_tie_single_pin_findings"] = len(rec["findings"]) - tie_total
        bad = probe_violations(rec)
        self.assertTrue(any("exact-agreement" in x for x in bad), bad)
        self.assertTrue(any("committed measurement" in x for x in bad), bad)

    def test_negative_control_perturbed_pnr_markers_breaks_exact_agreement(self):
        rec = copy.deepcopy(probe_record("control_top"))
        rec["corroboration"]["pnr_single_pin_markers"] += 1
        bad = probe_violations(rec)
        self.assertTrue(any("exact-agreement" in x for x in bad), bad)

    def test_negative_control_mutated_stream_hash_fails_the_binding(self):
        rec = copy.deepcopy(probe_record("ext_mem_instr"))
        rec["provenance"]["stream_content_hash"] = \
            "sha256:" + "0" * 64
        bad = probe_violations(rec)
        self.assertTrue(any("stream hash differs" in x for x in bad), bad)

    def test_records_carry_the_non_contractual_net_name_caveat(self):
        # The observed `$N` values are explicitly non-contractual (klt issue
        # #1063): the records must say so, and no assertion in this file reads
        # a finding's net (probe_violations keys on instance/pin only).
        for g in PROBE_GROUPS:
            rec = probe_record(g)
            self.assertTrue(any("#1063" in n for n in rec["notes"]), g)


if __name__ == "__main__":
    unittest.main()
