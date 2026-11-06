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


def check_route(gid, req, route, rc_value):
    """Per-request sv2v route assertion; raises AssertionError on a violation."""
    if gid in route["sv2v_groups"]:
        if req.get("sv_frontend") != "sv2v":
            raise AssertionError(f"{gid}: sv2v route not recorded in request.json")
    else:
        if "sv_frontend" in req:
            raise AssertionError(f"{gid}: native group carries sv_frontend")
        if rc_value != "0":
            raise AssertionError(f"{gid}: native group has non-zero exit")


def check_netlist_arg(entry):
    """The freshness argv must re-hash the committed netlist (--netlist <path>).

    Without it `klt synthesize --check` looks for the removed `out/` scratch
    netlist and reports `drifted`, so the attestation silently fails.
    """
    argv = entry["check"]["argv"]
    if "--netlist" not in argv or argv[argv.index("--netlist") + 1] != entry["path"]:
        raise AssertionError(f"{entry['path']}: freshness check lacks --netlist <committed netlist>")


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

    def test_sv2v_route_is_recorded_per_request(self):
        pin = json.loads((BASE / "pdk-pin.json").read_text())
        route = pin["sv_frontend"]
        self.assertEqual(pin["tools"]["sv2v"], "0.0.13")
        self.assertEqual(sorted(route["native_groups"] + route["sv2v_groups"]),
                         sorted(g["id"] for g in groups()))
        for g in groups():
            req = json.loads((BASE / g["id"] / "request.json").read_text())
            check_route(g["id"], req, route, rc(g))

    def test_negative_control_unrecorded_route_is_detected(self):
        req = json.loads((BASE / "rf_send34_core" / "request.json").read_text())
        route = json.loads((BASE / "pdk-pin.json").read_text())["sv_frontend"]
        self.assertIn("rf_send34_core", route["sv2v_groups"])
        # The recorded request passes the route check ...
        check_route("rf_send34_core", req, route, rc({"id": "rf_send34_core"}))
        # ... and the same request with the route stripped must FAIL it.
        stripped = {k: v for k, v in req.items() if k != "sv_frontend"}
        with self.assertRaises(AssertionError):
            check_route("rf_send34_core", stripped, route, rc({"id": "rf_send34_core"}))

    def test_inventory_freshness_checks_hash_the_committed_netlist(self):
        inv = json.loads((BASE / "inventory.partial.json").read_text())
        self.assertGreater(len(inv["derived"]), 0)
        for e in inv["derived"]:
            check_netlist_arg(e)
            self.assertTrue((ROOT / e["path"]).is_file(), e["path"])
        # Every attested source is a lint-manifest product source.
        srcs = {g["source"] for g in groups()}
        self.assertTrue(set(inv["sources"]) <= srcs)
        # Negative control: the pre-fix argv (no --netlist) must be rejected.
        bad = json.loads(json.dumps(inv["derived"][0]))
        i = bad["check"]["argv"].index("--netlist")
        del bad["check"]["argv"][i:i + 2]
        with self.assertRaises(AssertionError):
            check_netlist_arg(bad)

    def test_block_manifest_does_not_claim_item1_while_groups_blocked(self):
        blocked = [g["id"] for g in groups() if rc(g) != "0"]
        ev = json.loads((ROOT / "signoff" / "block-manifest.json").read_text())["evidence"]
        if blocked:
            self.assertNotIn("1", ev, f"item 1 cited while BLOCKED: {blocked}")


if __name__ == "__main__":
    unittest.main()
