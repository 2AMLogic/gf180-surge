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
import ast
import copy
import gzip
import hashlib
import json
import pathlib
import re
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


def geometry_record(group):
    return load(group, "pin_geometry_probe.json")


def geometry_violations(rec, g):
    """Everything wrong with one pin-geometry record, as a list of strings,
    so the live negative controls can mutate a copy and re-audit with the
    same code the positive tests run. Anti-vacuity: zero inverter instances
    examined fails loudly (the control group's "no isolated masters" would
    otherwise pass vacuously). No check here reads a trace-stop layer as an
    openness verdict: openness is the connectivity record's to say."""
    v = []
    prov = rec["provenance"]
    if prov["pin"] != (ROOT / "signoff" / "requirements.txt").read_text().strip():
        v.append(f"{g}: recorded pin differs from signoff/requirements.txt")
    if prov["stream_content_hash"] != stream_hash(g):
        v.append(f"{g}: stream hash differs from the committed .gds.gz")
    pin = json.loads((ROOT / "signoff" / "t1-item1" / "pdk-pin.json").read_text())
    if prov["lef"]["pdk_revision"] != pin["pdk"]["revision"]:
        v.append(f"{g}: LEF pdk revision differs from "
                 f"signoff/t1-item1/pdk-pin.json")
    masters = rec.get("masters", [])
    if sum(mm.get("instances_total", 0) for mm in masters) <= 0:
        v.append(f"NO_VERDICT: {g}: zero inverter instances examined -- the "
                 f"zero-isolated-masters check would pass vacuously")
    for mm in masters:
        if not mm.get("lef_irects_um"):
            v.append(f"{g}: master {mm.get('master')} resolved no LEF I-pin "
                     f"rects (the named pin did not resolve)")
        if mm.get("instances_total", 0) != mm.get("connectivity_instance_count"):
            v.append(f"{g}: master {mm.get('master')} instance count "
                     f"{mm.get('instances_total')} != connectivity record's "
                     f"{mm.get('connectivity_instance_count')}")
    # The isolated-input summary must be exactly what the same stream's
    # committed connectivity record reports, master by master.
    conn = probe_record(g)
    conn_masters = {f["master"].rsplit("__", 1)[-1] for f in conn["findings"]
                    if f["direction"] == "input"}
    geo_isolated = {mm["master"] for mm in masters
                    if mm.get("isolated_inputs_from_connectivity")}
    summary = set(rec["summary"]["masters_with_isolated_inputs"])
    if geo_isolated != summary:
        v.append(f"{g}: per-master isolated inputs differ from the summary")
    if geo_isolated != conn_masters:
        v.append(f"{g}: isolated inputs differ from the committed open-pin "
                 f"findings' masters {sorted(conn_masters)}")
    if not any("different sets" in n for n in rec.get("notes", [])):
        v.append(f"{g}: LEF/GDS note (the two pin-rect sets differ for the "
                 f"wide inverters) is missing from the record")
    return v


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


class T1PhysicalPinGeometryProbe(unittest.TestCase):
    """#804 step 1: the committed pin-geometry records re-bind to their
    streams and to the connectivity record they annotate.

    Binds each record's stream hash and tool pin, requires every inverter
    master's LEF I-pin rects to have resolved, and re-derives the
    masters-with-isolated-inputs summary from the same stream's committed
    open_pin_probe.json findings -- the geometry record may never disagree
    with the connectivity record it annotates. DOES NOT: read a trace-stop
    layer as an openness verdict, make a cause or fix claim, or establish
    anything about fidelity or hardware.
    """

    def test_records_rebind_to_streams_masters_and_connectivity(self):
        for g in PROBE_GROUPS:
            rec = geometry_record(g)
            self.assertEqual(rec["group"], g)
            self.assertEqual(geometry_violations(rec, g), [], g)

    def test_negative_control_mutated_stream_hash_fails_the_binding(self):
        rec = copy.deepcopy(geometry_record("ext_mem_instr"))
        rec["provenance"]["stream_content_hash"] = "sha256:" + "0" * 64
        bad = geometry_violations(rec, "ext_mem_instr")
        self.assertTrue(any("stream hash differs" in x for x in bad), bad)

    def test_negative_control_empty_pin_selection_fails_the_control(self):
        # A geometry pass that resolved no inverter instances at all would
        # make control_top's "zero isolated masters" pass vacuously.
        rec = copy.deepcopy(geometry_record("control_top"))
        for mm in rec["masters"]:
            mm["instances_total"] = 0
        bad = geometry_violations(rec, "control_top")
        self.assertTrue(any("vacuously" in x for x in bad), bad)

    def test_negative_control_unresolved_lef_pin_fails_the_named_pins(self):
        rec = copy.deepcopy(geometry_record("ext_mem_instr"))
        next(mm for mm in rec["masters"]
             if mm["master"] == "clkinv_12")["lef_irects_um"] = []
        bad = geometry_violations(rec, "ext_mem_instr")
        self.assertTrue(any("resolved no LEF I-pin rects" in x for x in bad),
                        bad)

    def test_negative_control_stale_isolated_masters_break_the_cross_check(self):
        # Simulate a geometry record re-run against a different stream
        # without refreshing the connectivity binding: the summary must
        # stop agreeing with the committed open-pin findings.
        rec = copy.deepcopy(geometry_record("ext_mem_instr"))
        rec["masters"][0]["isolated_inputs_from_connectivity"] = [
            "gf180mcu_fd_sc_mcu9t5v0__clkinv_1_0"]
        bad = geometry_violations(rec, "ext_mem_instr")
        self.assertTrue(any("isolated inputs differ" in x for x in bad), bad)

    def test_negative_control_dropped_lef_gds_note_hides_the_measurement(self):
        rec = copy.deepcopy(geometry_record("ext_mem_instr"))
        rec["notes"] = [n for n in rec["notes"] if "different sets" not in n]
        bad = geometry_violations(rec, "ext_mem_instr")
        self.assertTrue(any("LEF/GDS note" in x for x in bad), bad)

    def test_baseline_expectation_pins_the_four_open_instances(self):
        rec = geometry_record("ext_mem_instr")
        self.assertEqual(
            set(rec["summary"]["masters_with_isolated_inputs"]),
            {"clkinv_12", "clkinv_16", "inv_8"})
        ctl = geometry_record("control_top")
        self.assertEqual(ctl["summary"]["masters_with_isolated_inputs"], [])
        # control_top places inv_8 and it is NOT isolated there: the master
        # identity alone does not decide the open, and the record says so
        # by carrying it with an empty isolated list.
        inv8 = next(mm for mm in ctl["masters"] if mm["master"] == "inv_8")
        self.assertEqual(inv8["isolated_inputs_from_connectivity"], [])


# --------------------------------------------------------------------------
# #804 steps 2/3: the bounded P&R trials under trials/<group>/<slug>/
# --------------------------------------------------------------------------
TRIALS = BASE / "trials"


def trial_run(slug, group="ext_mem_instr"):
    return json.loads((TRIALS / group / slug / "run.json").read_text())


def trial_dirs(group="ext_mem_instr"):
    """Every recorded trial directory. Anti-vacuity: the two #804 trials
    must exist, and any directory without a parseable run.json fails the
    iteration, so a future trial cannot land silently unbound."""
    dirs = sorted(p.name for p in (TRIALS / group).iterdir() if p.is_dir())
    if not dirs:
        raise AssertionError("no trial directories under trials/" + group)
    return dirs


def _set_leaf(obj, dotted, value):
    """Apply one deep_diff leaf path (`key.key[i].key`) to obj."""
    tokens = dotted.split(".")
    for i, tok in enumerate(tokens):
        last = i == len(tokens) - 1
        m = re.fullmatch(r"(\w+)\[(\d+)\]", tok)
        if m:
            k, idx = m.group(1), int(m.group(2))
            if last:
                obj[k][idx] = value
            else:
                obj = obj[k][idx]
        else:
            if last:
                obj[tok] = value
            else:
                obj = obj[tok]


def trial_violations(slug, group="ext_mem_instr", run=None, geo=None,
                     floorplan_tcl=None):
    """Everything wrong with one recorded trial, as a list of strings.
    A completed trial re-binds to its own bytes: the recorded request diff
    must be exactly one leaf, must reproduce the on-disk trial request from
    the committed baseline, that leaf must be visible in the archived
    generated floorplan TCL (the placebo's density leaf never was), the
    trial stream hash must bind its own probe records, and the recorded
    outcome summary must equal what those records actually say. An
    interrupted trial must claim no stream and no downstream verdict.
    `run`/`geo`/`floorplan_tcl` override the on-disk record so the live
    negative controls audit mutated copies, never write the real ones.
    DOES NOT: read a trial as a fix claim -- a bounded finding is a valid
    recorded outcome."""
    d = TRIALS / group / slug
    if run is None:
        run = json.loads((d / "run.json").read_text())
    v = []
    if run.get("schema") != "gf180-surge.pnr-trial/1":
        v.append(f"{slug}: run schema is not gf180-surge.pnr-trial/1")
    if run.get("group") != group:
        v.append(f"{slug}: run group is {run.get('group')!r}, not {group}")
    if run.get("status") == "interrupted":
        if (d / f"{group}.gds.gz").exists():
            v.append(f"{slug}: interrupted trial claims a stream")
        for step in ("drc", "lvs", "open-pin-probe", "pin-geometry-probe"):
            st = run.get("steps", {}).get(step, {})
            if st.get("status") != "NOT_RUN":
                v.append(f"{slug}: interrupted trial records {step} as "
                         f"{st.get('status')!r}, not NOT_RUN")
        return v
    base = json.loads((BASE / group / "request.json").read_text())
    diff = run.get("request_diff", [])
    if len(diff) != 1:
        v.append(f"{slug}: {len(diff)} request leaves changed; the #804 "
                 f"contract is one setting per trial")
    want = copy.deepcopy(base)
    for leaf in diff:
        _set_leaf(want, leaf["path"], leaf["trial"])
    rewrite = run.get("netlist_path_rewrite", {})
    if rewrite.get("trial_request"):
        want["netlist"] = rewrite["trial_request"]
    else:
        v.append(f"{slug}: netlist path rewrite not recorded")
    got = json.loads((d / "request.json").read_text())
    if got != want:
        v.append(f"{slug}: on-disk request.json is not the baseline plus the "
                 f"recorded diff leaves")
    # The changed leaf must be visible in the generated flow: the archived
    # floorplan TCL is what the pinned generator produced from that request.
    tcl_path = d / "pnr-scripts" / f"pnr_{group}_floorplan.tcl"
    if floorplan_tcl is None:
        floorplan_tcl = tcl_path.read_text() if tcl_path.is_file() else None
    if floorplan_tcl is None:
        v.append(f"{slug}: generated floorplan TCL not archived")
    elif diff:
        leaf = diff[0]
        m = re.fullmatch(r"power\.straps\[(\d+)\]\.offset_um", leaf["path"])
        if m:
            strap = got["power"]["straps"][int(m.group(1))]
            line = next((l for l in floorplan_tcl.splitlines()
                         if "add_pdn_stripe" in l
                         and f"-layer {{{strap['layer']}}}" in l), "")
            mo = re.search(r"-offset \{([-0-9.]+)\}", line)
            if not mo or float(mo.group(1)) != float(leaf["trial"]):
                v.append(f"{slug}: {strap['layer']} stripe offset in the "
                         f"generated TCL is "
                         f"{mo.group(1) if mo else None}, not the trial's "
                         f"{leaf['trial']}")
        else:
            v.append(f"{slug}: no reached-the-flow check covers leaf "
                     f"{leaf['path']} -- extend trial_violations first")
    # Stream binding: both trial probe records bind the trial's own stream.
    stream = "sha256:" + sha(gzip.decompress(
        (d / f"{group}.gds.gz").read_bytes()))
    if geo is None:
        geo = json.loads((d / "pin_geometry_probe.json").read_text())
    if geo["provenance"]["stream_content_hash"] != stream:
        v.append(f"{slug}: geometry record hash differs from trial stream")
    conn = json.loads((d / "open_pin_probe.json").read_text())
    if conn["provenance"]["stream_content_hash"] != stream:
        v.append(f"{slug}: connectivity record hash differs from trial stream")
    # The recorded outcome summary must be what the records say.
    inputs = sorted(f["instance"] for f in conn["findings"]
                    if f["direction"] == "input")
    if sorted(run["steps"]["open-pin-probe"]["open_input_pins"]) != inputs:
        v.append(f"{slug}: run.json open inputs differ from the trial "
                 f"connectivity findings")
    lvs = json.loads(gzip.decompress((d / "lvs.report.json.gz").read_bytes()))
    if run["steps"]["lvs"]["status"] != lvs.get("status"):
        v.append(f"{slug}: run.json lvs status differs from lvs.report")
    drc = json.loads(gzip.decompress((d / "drc.report.json.gz").read_bytes()))
    if run["steps"]["drc"]["status"] != drc.get("status"):
        v.append(f"{slug}: run.json drc status differs from drc.report")
    return v


class T1PhysicalPNRTrials(unittest.TestCase):
    """#804 steps 2/3: every recorded P&R trial is bound to its own bytes.

    Each trial's run.json must re-derive from its request.json, its archived
    generated TCL, its stream and its probe/LVS/DRC records -- and the
    placebo (a knob the pinned 0.8.0 tool does not read) must keep saying
    so, so the interrupted-baseline history cannot be rewritten into a
    trial that tested something. DOES NOT: treat a qualifying trial as an
    adopted flow (adoption is regen.py + the committed groups, separate),
    or make any fidelity/hardware claim.
    """

    def test_every_recorded_trial_rebinds_to_its_own_bytes(self):
        seen = trial_dirs()
        self.assertIn("placement-density-0p45", seen)
        self.assertIn("m4-strap-offset-0p0", seen)
        for slug in seen:
            self.assertEqual(trial_violations(slug), [], slug)

    def test_placebo_keeps_its_no_knob_finding(self):
        run = trial_run("placement-density-0p45")
        self.assertEqual(run["status"], "interrupted")
        finding = run.get("finding", {})
        self.assertFalse(finding.get("setting_exposed_by_pinned_tool"))
        self.assertTrue(any("#4716" in p for p in finding.get("proof", [])),
                        finding)
        self.assertIn("Does not consume", run.get("cap_accounting", ""))
        # And the generated place TCL really is the baseline density.
        tcl = (TRIALS / "ext_mem_instr" / "placement-density-0p45"
               / ".klt" / "place-and-route" / "pnr_ext_mem_instr_place.tcl")
        self.assertIn("global_placement -density 0.6", tcl.read_text())

    def test_negative_control_mutated_stream_hash_fails_the_binding(self):
        d = TRIALS / "ext_mem_instr" / "m4-strap-offset-0p0"
        geo = json.loads((d / "pin_geometry_probe.json").read_text())
        geo["provenance"]["stream_content_hash"] = "sha256:" + "0" * 64
        bad = trial_violations("m4-strap-offset-0p0", geo=geo)
        self.assertTrue(any("geometry record hash differs" in x
                            for x in bad), bad)

    def test_negative_control_second_leaf_fails_the_one_setting_rule(self):
        run = trial_run("m4-strap-offset-0p0")
        run["request_diff"].append({"path": "floorplan.die_area_um",
                                    "baseline": [0, 0, 1100, 1100],
                                    "trial": [0, 0, 1200, 1200]})
        bad = trial_violations("m4-strap-offset-0p0", run=run)
        self.assertTrue(any("one setting" in x for x in bad), bad)

    def test_negative_control_baseline_tcl_fails_the_knob_leg(self):
        d = TRIALS / "ext_mem_instr" / "m4-strap-offset-0p0"
        real = (d / "pnr-scripts" / "pnr_ext_mem_instr_floorplan.tcl"
                ).read_text()
        patched = real.replace(
            "-layer {Metal4} -width {4.48} -spacing {0.56} -pitch {44.8} "
            "-offset {0.0}",
            "-layer {Metal4} -width {4.48} -spacing {0.56} -pitch {44.8} "
            "-offset {22.4}")
        self.assertNotEqual(patched, real)  # the control must mutate
        bad = trial_violations("m4-strap-offset-0p0",
                               floorplan_tcl=patched)
        self.assertTrue(any("stripe offset" in x for x in bad), bad)

    def test_m4_outcome_is_the_recorded_bounded_finding(self):
        # The M4 offset trial did not qualify: it MOVED the opens (the
        # baseline's clkinv_12_1 and clkinv_16_0 inputs now connect;
        # inv_12_0, open in no baseline record, lost its input) and made
        # LVS worse (31 errors vs the baseline 14). Pinning the recorded
        # outcome keeps the bounded finding from drifting silently.
        run = trial_run("m4-strap-offset-0p0")
        self.assertEqual(run["steps"]["open-pin-probe"]["open_input_pins"], [
            "gf180mcu_fd_sc_mcu9t5v0__clkinv_12_0",
            "gf180mcu_fd_sc_mcu9t5v0__inv_12_0",
            "gf180mcu_fd_sc_mcu9t5v0__inv_8_0"])
        self.assertEqual(run["steps"]["open-pin-probe"]
                         ["input_pins_examined"], 21090)
        self.assertEqual(run["steps"]["lvs"]["status"], "mismatch")
        self.assertEqual(run["steps"]["lvs"]["errors"], 31)
        self.assertEqual(run["steps"]["drc"]["status"], "clean")
        self.assertEqual(run["steps"]["drc"]["violations"], 0)
        geo = json.loads((TRIALS / "ext_mem_instr" / "m4-strap-offset-0p0"
                          / "pin_geometry_probe.json").read_text())
        self.assertEqual(
            geo["summary"]["masters_with_isolated_inputs"],
            ["clkinv_12", "inv_12", "inv_8"])


# #827 -- the relative-argv convention #826 established for the two
# `pin_geometry_probe.py` calls in `trial.py`: the probe records its argv as
# given, so running from the trial directory (`cwd=tdir`) under bare names
# keeps absolute host paths out of a produced record's `provenance.argv`.
TRIAL_PY = BASE / "trial.py"
PROBE_SCRIPT = "pin_geometry_probe.py"
PROBE_PATH_FLAGS = ("--stream", "--out", "--conn")
PROBE_CALL_SITES = 2  # the full flow and --rerun-geometry
# One call site of trial.py as of 32e7c566, before #826 made both relative.
PRE_826_PROBE_CALL = '''
gp = subprocess.run(
    [sys.executable, str(HERE / "pin_geometry_probe.py"), group,
     "--stream", str(tdir / f"{group}.gds.gz"), "--out",
     str(tdir / "pin_geometry_probe.json"), "--conn",
     str(tdir / "open_pin_probe.json")],
    cwd=ROOT, capture_output=True, text=True, env=os.environ)
'''


def _argv_list(call):
    """The call's argv when it is a list literal (positional or `args=`)."""
    if call.args and isinstance(call.args[0], ast.List):
        return call.args[0]
    return next((k.value for k in call.keywords
                 if k.arg == "args" and isinstance(k.value, ast.List)), None)


def probe_calls(tree):
    """Every call in `tree`, in source order, whose argv list literal names
    the probe script."""
    found = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and _argv_list(c) is not None and any(
                 PROBE_SCRIPT in ast.unparse(e) for e in _argv_list(c).elts)]
    return sorted(found, key=lambda c: (c.lineno, c.col_offset))


def _name_problem(node):
    """Why `node` is not a bare relative file name, or None when it is one:
    a string constant or an f-string of constants and bare names, neither
    rooted at `/`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "is an absolute path" if node.value.startswith("/") else None
    if isinstance(node, ast.JoinedStr):
        first = node.values[0]
        if isinstance(first, ast.Constant) and first.value.startswith("/"):
            return "is an absolute path"
        for part in node.values:
            if (isinstance(part, ast.FormattedValue)
                    and not isinstance(part.value, ast.Name)):
                return "is an f-string of something other than a bare name"
        return None
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "str":
        return "is a str(...) path expression"
    return "is not a string constant or f-string"


def probe_argv_problems(source):
    """(#827) Every way the `pin_geometry_probe.py` calls in
    `signoff/t1-physical/trial.py` depart from the relative-argv convention
    (#826), as a list of strings -- so the live negative controls re-audit the
    pre-#826 shape with the same code the positive test runs. Exactly
    PROBE_CALL_SITES calls whose argv list names the probe; each runs with
    `cwd=tdir`, and the value after each of --stream, --out and --conn is a
    bare relative name. A call whose argv is not a list literal is invisible
    here and shows only if it displaces a visible one (the count drops).
    Proves the invocation shape only, never that a produced record is
    host-neutral."""
    v = []
    sites = probe_calls(ast.parse(source))
    if len(sites) != PROBE_CALL_SITES:
        v.append(f"found {len(sites)} {PROBE_SCRIPT} call sites, want "
                 f"{PROBE_CALL_SITES}")
    for call in sites:
        where = f"line {call.lineno}"
        cwd = {k.arg: k.value for k in call.keywords if k.arg}.get("cwd")
        if not isinstance(cwd, ast.Name) or cwd.id != "tdir":
            shown = "absent" if cwd is None else ast.unparse(cwd)
            v.append(f"{where}: cwd={shown}, want cwd=tdir")
        elts = _argv_list(call).elts
        for flag in PROBE_PATH_FLAGS:
            hits = [i for i, e in enumerate(elts)
                    if isinstance(e, ast.Constant) and e.value == flag]
            if not hits:
                v.append(f"{where}: no {flag} argument")
            for i in hits:
                if i + 1 == len(elts):
                    v.append(f"{where}: {flag} has no value")
                    continue
                problem = _name_problem(elts[i + 1])
                if problem:
                    v.append(f"{where}: {flag} value "
                             f"{ast.unparse(elts[i + 1])} {problem}")
    return v


class T1PhysicalTrialProbeArgv(unittest.TestCase):
    """#827: `trial.py` invokes `pin_geometry_probe.py` under relative
    argv from the trial directory (#826), checked live at the source level."""

    def test_probe_calls_run_from_trial_dir_under_relative_names(self):
        """Proves only the *invocation shape* of the two
        `pin_geometry_probe.py` calls in `signoff/t1-physical/trial.py`
        (#815 AC1, promoted from a one-shot grep): `cwd=tdir` and bare
        `--stream` / `--out` / `--conn` names. It proves only that shape --
        never that a produced record is host-neutral, which needs a real
        trial. Static: no OpenROAD, PDK, klt or network."""
        self.assertEqual(probe_argv_problems(TRIAL_PY.read_text()), [])

    def test_negative_control_pre826_absolute_argv_is_rejected(self):
        # Both call sites as of 32e7c566, before #826: cwd=ROOT and
        # str(tdir / ...) values. The checker must name every defect.
        bad = probe_argv_problems(PRE_826_PROBE_CALL * 2)
        self.assertEqual(len(bad), 8, bad)
        self.assertEqual(sum("cwd=ROOT, want cwd=tdir" in x for x in bad), 2)
        for flag in PROBE_PATH_FLAGS:
            self.assertEqual(
                sum(f"{flag} value str(tdir / " in x for x in bad), 2, bad)

    def test_negative_control_added_call_site_fails_the_count(self):
        # A third, well-formed call site changes nothing but the count.
        src = TRIAL_PY.read_text()
        site = ast.get_source_segment(src, probe_calls(ast.parse(src))[0])
        self.assertEqual(
            probe_argv_problems(src + "\n" + site + "\n"),
            [f"found 3 {PROBE_SCRIPT} call sites, want {PROBE_CALL_SITES}"])

    def test_negative_control_each_non_relative_form_is_rejected(self):
        # One known-good call site, twice, with one defect introduced at a
        # time: each form is rejected, and only for its own defect.
        src = TRIAL_PY.read_text()
        good = ast.get_source_segment(src, probe_calls(ast.parse(src))[0])
        self.assertEqual(probe_argv_problems(good + "\n" + good), [])
        for old, new, want in (
                ('f"{group}.gds.gz"', '"/home/ubuntu/trial/x.gds.gz"',
                 "is an absolute path"),
                ('"pin_geometry_probe.json"',
                 'tdir / "pin_geometry_probe.json"',
                 "is not a string constant or f-string"),
                ('f"{group}.gds.gz"', 'f"{tdir / group}.gds.gz"',
                 "is an f-string of something other than a bare name"),
                ('"--conn"', '"--input"', "no --conn argument")):
            bad = probe_argv_problems((good + "\n" + good).replace(old, new))
            self.assertEqual(len(bad), 2, (new, bad))
            self.assertTrue(all(want in x for x in bad), (new, bad))


if __name__ == "__main__":
    unittest.main()
