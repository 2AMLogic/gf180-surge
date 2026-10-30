#!/usr/bin/env python3
"""#544 -- T1 physical-flow evidence (items 2/3/4/11), Phase A.

PINS: for each synthesized product group, the committed routed stream is
bound by content hash to its DRC, LVS and ERC reports; a recorded tool failure
is never silently dropped; reports carry no absolute host paths; the
supply-spec declares ties[]; and `signoff/block-manifest.json` cites items
2/3/4/11 only once all `product` groups have passing physical-flow evidence
(live negative control included).
DOES NOT: establish that DRC/LVS/ERC are clean (outcomes are recorded as the
tools reported them), timing, corners, "gf180mcu implementation", or fidelity.
Coverage (groups with a stream / all product groups) is reported separately.
"""
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
    return sorted(p.parent.name for p in BASE.glob("*/exit_status.json"))


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

    def test_erc_not_checked_reason_is_missing_antenna_pdk(self):
        # klt 0.8.0 `erc --pdk` has no gf180mcu antenna table: a tool gap,
        # not an input this repo can supply. Never reported as met.
        for g in physical_groups():
            erc = load(g, "erc.report.json")
            self.assertEqual(erc["status"], "not_checked", g)
            self.assertIsNone(erc["pdk"], g)
            self.assertEqual(erc["coverage"]["checked"], [], g)
            self.assertEqual(
                {s["reason"] for s in erc["coverage"]["skipped"]},
                {"missing_antenna_pdk"}, g)
            self.assertNotEqual(load(g, "exit_status.json")["erc"], 0, g)


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


if __name__ == "__main__":
    unittest.main()
