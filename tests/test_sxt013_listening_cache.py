"""SXT-013 listening-cache identity binding tests (issue #404).

Bookkeeping only: a FAKE renderer writes distinct small WAVs. Nothing here
renders with the pinned oracle and nothing makes a fidelity, coverage or
listening claim. Python 3 standard library only (unittest; pytest-runnable).
"""

import argparse
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sxt013_listen_cache", REPO / "tools" / "listening_session.py")
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)

SEQ = ls.DEFAULT_SEQUENCE


def write_wav(path, level):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack("<8h", *([level, -level] * 4)))


class FakeRenderer:
    """Audio level is derived from the preset file bytes (A != B)."""

    def __init__(self):
        self.calls = []

    def __call__(self, preset_abs, sequence, out_dir):
        self.calls.append(Path(preset_abs))
        level = 1000 + len(Path(preset_abs).read_bytes())
        write_wav(Path(out_dir) / f"{sequence}-wet.wav", level)
        write_wav(Path(out_dir) / f"{sequence}-dry.wav", level // 2)
        return {"fake": True}


def legacy_render_wet_dry(preset_abs, sequence, cache_dir, renderer):
    """The PRE-FIX behavior (basename key, reuse iff both files exist),
    reproduced verbatim as the failure control."""
    slug = preset_abs.stem.replace(" ", "_")
    out_dir = cache_dir / slug
    wet = out_dir / f"{sequence}-wet.wav"
    dry = out_dir / f"{sequence}-dry.wav"
    if wet.exists() and dry.exists():
        return wet, dry, {"rendered": False}
    out_dir.mkdir(parents=True, exist_ok=True)
    renderer(preset_abs, sequence, out_dir)
    return wet, dry, {"rendered": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = self.tmp / "cache"
        self.cache.mkdir()
        self.pa = self.tmp / "bankA" / "Lead" / "Same Name.fxp"
        self.pb = self.tmp / "bankB" / "Pad" / "Same Name.fxp"
        for p, data in ((self.pa, b"A" * 10), (self.pb, b"B" * 77)):
            p.parent.mkdir(parents=True)
            p.write_bytes(data)
        self.fake = FakeRenderer()

    def ident(self, p, rel):
        return ls.render_identity(rel, ls.git_blob_sha1(p), SEQ)

    def get(self, p, rel):
        return ls.render_wet_dry(p, SEQ, self.cache, self.ident(p, rel),
                                 renderer=self.fake)


class TestCollision(Base):
    def test_failure_control_legacy_cache_reuses_A_for_B(self):
        wa, _, ia = legacy_render_wet_dry(self.pa, SEQ, self.cache, self.fake)
        wb, _, ib = legacy_render_wet_dry(self.pb, SEQ, self.cache, self.fake)
        self.assertTrue(ia["rendered"])
        self.assertFalse(ib["rendered"])          # wrongly reused
        self.assertEqual(wa, wb)                  # same file
        self.assertEqual(len(self.fake.calls), 1)  # B never rendered

    def test_new_cache_gives_independent_entries(self):
        wa, _, ia = self.get(self.pa, "bankA/Lead/Same Name.fxp")
        wb, _, ib = self.get(self.pb, "bankB/Pad/Same Name.fxp")
        self.assertTrue(ia["rendered"] and ib["rendered"])
        self.assertNotEqual(wa.parent, wb.parent)
        self.assertNotEqual(wa.read_bytes(), wb.read_bytes())
        self.assertEqual(len(self.fake.calls), 2)

    def test_new_cache_rejects_seeded_legacy_basename_entry(self):
        legacy_render_wet_dry(self.pa, SEQ, self.cache, self.fake)
        wb, _, ib = self.get(self.pb, "bankB/Pad/Same Name.fxp")
        self.assertTrue(ib["rendered"])
        self.assertEqual(self.fake.calls[-1], self.pb)
        self.assertNotIn("Same_Name", str(wb))


class TestReuseAndStale(Base):
    REL = "bankA/Lead/Same Name.fxp"

    def test_valid_entry_reused_without_renderer(self):
        self.get(self.pa, self.REL)
        n = len(self.fake.calls)
        wet, dry, info = self.get(self.pa, self.REL)
        self.assertFalse(info["rendered"])
        self.assertEqual(len(self.fake.calls), n)
        b = ls.binding_record(self.ident(self.pa, self.REL), info, self.cache)
        self.assertEqual(b["disposition"], "reused_verified")
        self.assertIsNone(b["reuse_refused_reason"])

    def assert_refused(self, expect, mutate):
        self.get(self.pa, self.REL)
        n = len(self.fake.calls)
        mutate()
        _, _, info = self.get(self.pa, self.REL)
        self.assertTrue(info["rendered"])
        self.assertEqual(len(self.fake.calls), n + 1)
        self.assertIn(expect, info["reuse_refused_reason"])

    def entry(self):
        return ls.entry_dir_for(self.cache, self.ident(self.pa, self.REL))

    def test_tampered_wet(self):
        self.assert_refused("wet wav digest", lambda: write_wav(
            self.entry() / f"{SEQ}-wet.wav", 7))

    def test_tampered_dry(self):
        self.assert_refused("dry wav digest", lambda: write_wav(
            self.entry() / f"{SEQ}-dry.wav", 7))

    def test_missing_identity_record(self):
        self.assert_refused("identity record missing",
                            lambda: (self.entry() / ls.IDENTITY_RECORD).unlink())

    def test_corrupt_identity_record(self):
        self.assert_refused("corrupt", lambda: (
            self.entry() / ls.IDENTITY_RECORD).write_text("{not json"))

    def test_mismatched_recorded_identity(self):
        def mutate():
            p = self.entry() / ls.IDENTITY_RECORD
            rec = json.loads(p.read_text())
            rec["identity"]["renderer_sha256"] = "0" * 64
            p.write_text(json.dumps(rec))
        self.assert_refused("identity mismatch", mutate)

    def test_changed_identity_fields_select_other_entry(self):
        base = self.ident(self.pa, self.REL)
        for field, val in (("preset_blob_sha1", "1" * 40),
                           ("preset_path", "other/Same Name.fxp"),
                           ("sequence_sha256", "2" * 64),
                           ("renderer_sha256", "3" * 64),
                           ("oracle_manifest_sha256", "4" * 64),
                           ("oracle_engine_commit", "5" * 40)):
            other = dict(base, **{field: val})
            self.assertNotEqual(ls.identity_key(other), ls.identity_key(base))
            self.assertFalse(ls.check_entry(
                ls.entry_dir_for(self.cache, other), SEQ, other)[0])
        self.get(self.pa, self.REL)
        for field, val in (("sequence_sha256", "2" * 64),
                           ("renderer_sha256", "3" * 64)):
            other = dict(base, **{field: val})
            n = len(self.fake.calls)
            ls.render_wet_dry(self.pa, SEQ, self.cache, other,
                              renderer=self.fake)
            self.assertEqual(len(self.fake.calls), n + 1)


class TestSession(Base):
    """run_session with mocked verification + fake renderer."""

    def make_args(self, slate, census, sessions):
        return argparse.Namespace(
            slate=str(slate), census=str(census), limit=0, pick="first",
            compare="dry", dry_run=True, operator=None, mode="open",
            sequence=SEQ, sessions_dir=str(sessions),
            audio_cache=str(self.cache), play="off", level_match=False)

    def setUp(self):
        super().setUp()
        self.rels = {"bankA/Lead/Same Name.fxp": self.pa,
                     "bankB/Pad/Same Name.fxp": self.pb}
        census = self.tmp / "census.csv"
        lines = ["path,git_blob_sha1"] + [
            f"{r},{ls.git_blob_sha1(p)}" for r, p in self.rels.items()]
        census.write_text("\n".join(lines) + "\n")
        cands = [{"id": f"c{i}", "path": r, "bank": "b", "category": "c",
                  "census_blob_sha1": ls.git_blob_sha1(p)}
                 for i, (r, p) in enumerate(self.rels.items())]
        slate = self.tmp / "slate.json"
        slate.write_text(json.dumps({
            "schema_version": "sxt-013-candidate-slate/1.0.0",
            "artifact": "fake", "candidates": cands}))
        self.args = self.make_args(slate, census, self.tmp / "sessions")
        self._orig = (ls.verify_candidate, ls.run_renderer)
        ls.verify_candidate = lambda c, census: self.rels[c["path"]]
        ls.run_renderer = self.fake
        self.addCleanup(self.restore)

    def restore(self):
        ls.verify_candidate, ls.run_renderer = self._orig

    def load(self):
        f = next((self.tmp / "sessions").glob("*.json"))
        return json.loads(f.read_text())

    def test_session_associates_each_candidate_with_its_own_audio(self):
        self.assertEqual(ls.run_session(self.args), 0)
        recs = self.load()["records"]
        a, b = recs[0]["audio"], recs[1]["audio"]
        self.assertNotEqual(a["wet"]["sha256"], b["wet"]["sha256"])
        self.assertNotEqual(a["binding"]["identity_key"],
                            b["binding"]["identity_key"])
        for r in recs:
            ident = r["audio"]["binding"]["identity"]
            self.assertEqual(ident["preset_path"], r["path"])
            self.assertEqual(ident["preset_blob_sha1"], r["census_blob_sha1"])
        # binding survives cache removal
        shutil.rmtree(self.cache)
        self.assertIn("identity_record_sha256", recs[0]["audio"]["binding"])

    def test_second_session_reuses_with_binding(self):
        ls.run_session(self.args)
        n = len(self.fake.calls)
        ls.run_session(self.args)
        self.assertEqual(len(self.fake.calls), n)
        second = self.tmp / "sessions" / "20261009-machine-dryrun-2.json"
        if not second.exists():  # date-independent fallback
            second = next(p for p in (self.tmp / "sessions").glob("*-2.json"))
        rec = json.loads(second.read_text())["records"][0]["audio"]
        self.assertFalse(rec["rendered_this_session"])
        self.assertEqual(rec["binding"]["disposition"], "reused_verified")

    def test_missing_oracle_is_blocked_and_not_counted(self):
        def blocked(c, census):
            raise ls.Blocked("cannot locate the pinned engine tree")
        ls.verify_candidate = blocked
        self.args.dry_run = False
        self.args.operator = "tester"
        # no input() must be reached
        self.assertEqual(ls.run_session(self.args), 0)
        s = self.load()
        for r in s["records"]:
            self.assertEqual(r["verification_status"], "BLOCKED")
            self.assertFalse(r["counts_toward_acceptance"])
            self.assertIsNone(r["audio"])
        self.assertEqual(s["counts"]["counting_toward_acceptance"], 0)
        self.assertEqual(s["counts"]["blocked"], 2)
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
