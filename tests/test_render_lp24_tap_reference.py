#!/usr/bin/env python3
"""#307 -- adapter checks for tools/render_lp24_tap_reference.py.

PINS: the tap-stream splitter writes bundles the UNCHANGED LP24 consumer can
load, keeps independent unit instances apart, and the CLI refuses without the
external tap/base builds.  DOES NOT: exercise the engine, establish neutrality,
or say anything about model-vs-reference agreement (that needs the external
tap build; see reports/SXT-307/EVIDENCE.md).
"""

import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tool = _load("lp24_tap_tool", "tools/render_lp24_tap_reference.py")
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lp24"))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, REPO)
runner = _load("lp24_runner_for_tap_test", "model/voice/filter_lp24/run_filter_leg.py")

C8 = [0.5] * 8


def _write_stream(d, tags, blocks=2, os_per_block=3):
    with open(os.path.join(d, "coeffs.jsonl"), "w") as f:
        for tag in tags:
            for b in range(blocks):
                f.write(json.dumps({
                    "tag": tag, "vid": tag // 4, "scene": 0, "key": 60, "channel": 0,
                    "lane": tag % 4, "unit": 0, "b": b, "first": b == 0, "type": 2,
                    "sub": 1, "cut": 1.5, "reso": 0.25, "C": C8, "dC": [0.0] * 8}) + "\n")
    with open(os.path.join(d, "units.bin"), "wb") as f:
        for tag in tags:
            for n in range(blocks * os_per_block):
                f.write(struct.pack("<IIIff", tag, tag % 4, n, float(n), float(2 * n)))
    with open(os.path.join(d, "regs.bin"), "wb") as f:
        for tag in tags:
            for b in range(blocks):
                f.write(struct.pack("<II5f", tag, b, *[float(b + i) for i in range(5)]))


class SplitBundles(unittest.TestCase):
    def test_instances_kept_apart_and_loadable(self):
        case = {"case": "t", "carrier": {"scene": 0, "unit": 0}, "filter": {"type": 2}}
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as out:
            _write_stream(raw, [4, 9])
            insts = tool.split_bundles(raw, out, case, "1.4.sxt307-tap.test")
            self.assertEqual([i[0] for i in insts], [4, 9])
            for tag, _first, nblocks, d in insts:
                self.assertEqual(nblocks, 2)
                meta, coeffs, audio, regs = runner.load_bundle(d)
                self.assertEqual(meta["identity"]["tag"], tag)
                self.assertEqual(len(coeffs), 2)
                self.assertEqual(len(audio), 6)
                self.assertEqual([a[2] for a in audio], list(range(6)))   # re-sequenced
                self.assertTrue(all(a[0] == 0 and a[1] == 0 for a in audio))
                self.assertEqual(len(regs), 2)
            # tag 9's samples are not mixed into tag 4's bundle
            _m, _c, a4, _r = runner.load_bundle(insts[0][3])
            self.assertEqual(len(a4), 6)

    def test_truncated_stream_refused(self):
        case = {"case": "t", "carrier": {}, "filter": {}}
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as out:
            _write_stream(raw, [4])
            with open(os.path.join(raw, "units.bin"), "ab") as f:
                f.write(b"\x00")
            with self.assertRaises(SystemExit):
                tool.split_bundles(raw, out, case, "v")


class Cli(unittest.TestCase):
    def test_refuses_without_external_builds(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ORACLE_TAP_SURGEPY_DIR", "ORACLE_BASE_SURGEPY_DIR",
                            "ORACLE_SURGE_DIR")}
        p = subprocess.run([sys.executable, os.path.join(REPO, "tools",
                            "render_lp24_tap_reference.py"), "--case", "edges",
                            "--out-dir", tempfile.gettempdir()],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 3)
        self.assertIn("REFUSING", p.stderr)

    def test_case_names_are_the_eleven_committed_cases(self):
        self.assertEqual(len(tool.case_names()), 11)


if __name__ == "__main__":
    unittest.main()
