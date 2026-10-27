#!/usr/bin/env python3
"""#537 -- T1 item 1 synthesizability record is complete and fresh.

PINS: every `product` group in rtl/lint_manifest.json has either a committed
netlist + report (exit 0) or a recorded failure (no silent omission); each
committed netlist matches the report's netlist_sha256; each report's source
hash matches the live RTL bytes (stale-netlist control included).
DOES NOT: establish P&R, timing, equivalence, fidelity, or that item 1 is
`met` -- coverage (N of 11) is reported separately and 8 groups are BLOCKED.
"""
import hashlib
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "signoff" / "t1-item1"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def groups():
    return json.loads((ROOT / "rtl" / "lint_manifest.json").read_text())["groups"]


def rc(g):
    return (BASE / g["id"] / "exit_status.txt").read_text().strip()


def source_is_fresh(report, rtl_bytes):
    return report["provenance"]["input"]["content_hash"] == "sha256:" + sha(rtl_bytes)


class T1Item1(unittest.TestCase):
    def test_every_product_group_has_a_recorded_outcome(self):
        for g in groups():
            d = BASE / g["id"]
            if rc(g) == "0":
                self.assertTrue((d / "report.json").is_file(), g["id"])
                self.assertTrue((d / f"{g['top']}_synth.v").is_file(), g["id"])
            else:
                self.assertTrue((d / "failure.txt").read_text().strip(), g["id"])

    def test_netlists_match_reports_and_sources_are_fresh(self):
        n = 0
        for g in groups():
            if rc(g) != "0":
                continue
            n += 1
            d = BASE / g["id"]
            rep = json.loads((d / "report.json").read_text())
            net = (d / f"{g['top']}_synth.v").read_bytes()
            self.assertEqual(rep["netlist_sha256"], sha(net), g["id"])
            self.assertTrue(source_is_fresh(rep, (ROOT / g["source"]).read_bytes()), g["id"])
        self.assertGreater(n, 0)

    def test_negative_control_stale_netlist_fails_freshness(self):
        g = next(x for x in groups() if x["id"] == "control_top")
        rep = json.loads((BASE / g["id"] / "report.json").read_text())
        rtl = (ROOT / g["source"]).read_bytes()
        self.assertTrue(source_is_fresh(rep, rtl))
        self.assertFalse(source_is_fresh(rep, rtl + b"\n// edited, netlist not regenerated\n"))

    def test_pin_matches_reports(self):
        pin = json.loads((BASE / "pdk-pin.json").read_text())
        for g in groups():
            if rc(g) != "0":
                continue
            rep = json.loads((BASE / g["id"] / "report.json").read_text())
            self.assertEqual(rep["provenance"]["deck"]["content_hash"], pin["liberty"]["content_hash"])
            self.assertIn(pin["pdk"]["revision"], rep["provenance"]["pdk"]["version"])

    def test_block_manifest_does_not_claim_item1_while_groups_blocked(self):
        blocked = [g["id"] for g in groups() if rc(g) != "0"]
        ev = json.loads((ROOT / "signoff" / "block-manifest.json").read_text())["evidence"]
        if blocked:
            self.assertNotIn("1", ev, f"item 1 cited while BLOCKED: {blocked}")


if __name__ == "__main__":
    unittest.main()
