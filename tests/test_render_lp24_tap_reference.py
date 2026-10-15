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


def _run(raw, wav="w", dtype="<f4", shape=(2, 8)):
    return {"version": "1.4.sxt307-tap.test", "blocks": 1, "wav_sha256": wav,
            "raw_sha256": raw, "raw_dtype": dtype, "raw_shape": list(shape)}


class Neutrality(unittest.TestCase):
    def test_pass_on_identical_raw_digests(self):
        r = _run("a")
        self.assertEqual(tool.neutrality_verdict(r, r, r, r), ("PASS", True))

    def test_sub_lsb_difference_is_fail_even_with_identical_wav(self):
        # raw samples differ by < 1 int16 LSB: the quantized WAV digest is identical
        tap, ref = _run("a", wav="same"), _run("b", wav="same")
        self.assertEqual(tool.neutrality_verdict(tap, ref, ref, ref)[0], "FAIL")

    def test_clipped_region_difference_is_fail(self):
        tap, ref = _run("clip1.1", wav="same"), _run("clip1.2", wav="same")
        self.assertEqual(tool.neutrality_verdict(ref, ref, ref, tap)[0], "FAIL")

    def test_format_mismatch_is_fail(self):
        self.assertEqual(tool.neutrality_verdict(_run("a", dtype="<f8"), _run("a"),
                                                 _run("a"), _run("a"))[0], "FAIL")

    def test_nondeterministic_carrier_stays_no_verdict(self):
        self.assertEqual(tool.neutrality_verdict(_run("a"), _run("a"), _run("b"),
                                                 _run("a"))[0], "NO_VERDICT")


class Gate(unittest.TestCase):
    """A deterministic tapped/untapped mismatch must refuse and yield no qualified reference."""

    def _args(self, out):
        return type("A", (), {"out_dir": out})()

    def _patched(self, runs, fn):
        orig = tool.run_variant
        tool.run_variant = lambda a, c, v, o, repeat=0: runs[(v, repeat)]
        try:
            return fn()
        finally:
            tool.run_variant = orig

    def test_mismatch_refuses_without_bundles(self):
        runs = {("tap", 0): _run("t"), ("untapped", 0): _run("u"),
                ("untapped", 2): _run("u"), ("base", 0): _run("u")}
        with tempfile.TemporaryDirectory() as out:
            r = self._patched(runs, lambda: tool.one_case(self._args(out), "edges"))
            self.assertEqual(r["neutrality"], "FAIL")
            self.assertEqual(r["availability"], "REFUSED")
            self.assertFalse(r["reference_qualified"])
            self.assertFalse(os.path.exists(os.path.join(out, "edges", "bundles")))

    def test_failed_control_refuses_other_cases(self):
        runs = {("tap", 0): _run("u"), ("untapped", 0): _run("u"),
                ("untapped", 2): _run("u"), ("base", 0): _run("u")}
        with tempfile.TemporaryDirectory() as out:
            r = self._patched(runs, lambda: tool.one_case(self._args(out), "edges",
                                                          control_ok=False))
            self.assertEqual(r["availability"], "REFUSED")
            self.assertFalse(r["reference_qualified"])

    def test_main_exits_nonzero_when_control_fails(self):
        runs = {("tap", 0): _run("t"), ("untapped", 0): _run("u"),
                ("untapped", 2): _run("u"), ("base", 0): _run("u")}
        env = dict(os.environ, ORACLE_TAP_SURGEPY_DIR="x", ORACLE_BASE_SURGEPY_DIR="x",
                   ORACLE_SURGE_DIR="x")
        orig_env, orig_argv = dict(os.environ), sys.argv
        os.environ.update(env)
        with tempfile.TemporaryDirectory() as out:
            sys.argv = ["t", "--case", "edges", "--out-dir", out]
            try:
                rc = self._patched(runs, tool.main)
            finally:
                sys.argv = orig_argv
                os.environ.clear()
                os.environ.update(orig_env)
        self.assertEqual(rc, 4)


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
