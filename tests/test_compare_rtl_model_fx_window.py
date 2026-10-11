"""SXT-023 comparator window validation and empty-coverage tests (#452).

Synthetic model/RTL traces and a spy simulator boundary: no iverilog run.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tools import compare_rtl_model_fx as C  # noqa: E402

SETTLE = 2
N_TOTAL = 6


def model_trace(blocks=None, n_total=N_TOTAL):
    if blocks is None:
        blocks = [{"b": b, "out": {"L": [b, b + 1], "R": [b + 2, b + 3]},
                   "instances": []} for b in range(n_total)]
    return {"settle_blocks": SETTLE, "n_blocks_total": n_total, "blocks": blocks}


def rtl_for(mt, bad=None):
    O = {}
    for blk in mt["blocks"]:
        if blk["b"] < SETTLE:
            continue  # the RTL tb emits O lines only from RENDER0
        v = blk["out"]["L"] + blk["out"]["R"]
        if bad == blk["b"]:
            v = [v[0] + 1] + v[1:]
        O[blk["b"]] = v
    return O, {}


class WindowTests(unittest.TestCase):
    def test_validate(self):
        mt = model_trace()
        self.assertEqual(C.validate_window(mt, 0), N_TOTAL)
        self.assertEqual(C.validate_window(mt, 4), 4)
        self.assertEqual(C.validate_window(mt, N_TOTAL), N_TOTAL)
        for bad in (-1, N_TOTAL + 1):
            with self.assertRaises(C.WindowError):
                C.validate_window(mt, bad)
        with self.assertRaises(C.WindowError):
            C.validate_window(model_trace(blocks=[]), 0)
        with self.assertRaises(C.WindowError):
            C.validate_window(model_trace(n_total=0), 0)

    def test_truncated_or_sparse_trace_refused(self):
        # declared extent 6, but only blocks 0..3 carried (cut trace)
        cut = model_trace(blocks=model_trace()["blocks"][:4])
        for n in (0, N_TOTAL, 5):
            with self.assertRaises(C.WindowError):
                C.validate_window(cut, n)
        # a window that ends inside the carried blocks is still valid
        self.assertEqual(C.validate_window(cut, 4), 4)
        sparse = model_trace(blocks=[b for b in model_trace()["blocks"] if b["b"] != 3])
        with self.assertRaises(C.WindowError):
            C.validate_window(sparse, 0)
        # pre-roll blocks are only carried at checkpoints: not required
        preroll_sparse = model_trace(blocks=model_trace()["blocks"][SETTLE - 1:])
        self.assertEqual(C.validate_window(preroll_sparse, 0), N_TOTAL)

    def test_full_and_partial_pass_with_distinct_coverage(self):
        mt = model_trace()
        c_full, f_full = C.compare("x", mt, rtl_for(mt), N_TOTAL)
        c_part, f_part = C.compare("x", mt, rtl_for(mt), 4)
        self.assertEqual(f_full, [])
        self.assertEqual(f_part, [])
        self.assertEqual(c_full["blocks"], N_TOTAL - SETTLE)
        self.assertLess(c_part["blocks"], c_full["blocks"])

    def test_empty_window_is_not_pass(self):
        # negative-window control: pre-fix this returned ([], zero coverage)
        mt = model_trace()
        for n in (-1, -5, SETTLE):
            checked, fails = C.compare("x", mt, rtl_for(mt), n)
            self.assertEqual(checked["outputs"], 0)
            self.assertEqual(fails, [C.NO_COVERAGE])
        self.assertEqual(C.compare("x", model_trace(blocks=[]), ({}, {}))[1],
                         [C.NO_COVERAGE])

    def test_mismatch_still_fails(self):
        mt = model_trace()
        _, fails = C.compare("x", mt, rtl_for(mt, bad=3), 4)
        self.assertEqual(len(fails), 1)
        self.assertIn("block 3 out[0]", fails[0])


class MainTests(unittest.TestCase):
    def run_main(self, max_blocks, mt, bad=None):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "model_trace_metallic.json"), "w") as f:
                json.dump(mt, f)
            trace = os.path.join(d, "t.txt")
            out = os.path.join(d, "s.json")

            def fake_sim(*a, **k):
                O, _ = rtl_for(mt, bad)
                with open(trace, "w") as f:
                    for b, v in O.items():
                        f.write("O %d %s\n" % (b, " ".join(map(str, v))))

            argv = ["x", "--slug", "metallic", "--art-dir", d,
                    "--rtl-trace", trace, "--out", out,
                    "--max-blocks", str(max_blocks)]
            with mock.patch.object(C, "run_sim", side_effect=fake_sim) as spy, \
                    mock.patch.object(sys, "argv", argv), \
                    mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                rc = C.main()
            summary = json.load(open(out)) if os.path.exists(out) else None
            return rc, spy.call_count, summary

    def test_refused_before_simulation(self):
        for n in (-1, N_TOTAL + 1):
            rc, calls, summary = self.run_main(n, model_trace())
            self.assertEqual((rc, calls, summary), (2, 0, None))
        rc, calls, _ = self.run_main(0, model_trace(blocks=[]))
        self.assertEqual((rc, calls), (2, 0))

    def test_truncated_trace_refused_before_simulation(self):
        cut = model_trace(blocks=model_trace()["blocks"][:4])
        for n in (0, N_TOTAL):
            rc, calls, summary = self.run_main(n, cut)
            self.assertEqual((rc, calls, summary), (2, 0, None))
        # bounded window inside the carried blocks: valid partial
        rc, calls, s = self.run_main(4, cut)
        self.assertEqual((rc, calls, s["verdict"], s["coverage"]), (0, 1, "PASS", "partial"))
        self.assertEqual(s["blocks_in_window_expected"], 2)

    def test_full_partial_summaries(self):
        rc, calls, s = self.run_main(0, model_trace())
        self.assertEqual((rc, calls, s["verdict"], s["coverage"]), (0, 1, "PASS", "full"))
        rc, _, s = self.run_main(4, model_trace())
        self.assertEqual((rc, s["verdict"], s["coverage"]), (0, "PASS", "partial"))
        self.assertEqual(s["blocks_requested"], 4)
        self.assertEqual(s["blocks_compared_semantics"], "blocks_actually_compared")
        self.assertEqual((s["blocks_window"], s["blocks_compared"]), (4, 2))  # actual, not requested

    def test_preroll_only_window_is_no_verdict(self):
        # window selects only pre-roll blocks: nothing compared
        rc, calls, s = self.run_main(SETTLE, model_trace())
        self.assertEqual(calls, 1)
        self.assertEqual((rc, s["verdict"], s["coverage"]), (1, "NO_VERDICT", "none"))
        # the no-coverage marker is not a mismatch; the reason stays visible
        self.assertEqual(s["mismatches"], 0)
        self.assertEqual(s["no_verdict_reason"], C.NO_COVERAGE)

    def test_mismatch_fails(self):
        rc, _, s = self.run_main(4, model_trace(), bad=3)
        self.assertEqual((rc, s["verdict"], s["mismatches"]), (1, "FAIL", 1))
        self.assertIsNone(s["no_verdict_reason"])


if __name__ == "__main__":
    unittest.main()
