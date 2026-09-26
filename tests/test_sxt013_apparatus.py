"""SXT-013 apparatus tests (run by CI when tests/ exists).

Covers the automatable guarantees only:
  - the candidate builder is deterministic (same inputs -> byte-identical),
  - it REFUSES on census-hash tampering (exit 2, no artifacts),
  - the committed slates satisfy the declared quotas and are current,
  - the pilot is a subset of the 256 slate, with census hashes everywhere,
  - listening-harness helpers (slate validation, wav RMS/level-match math).

These tests make NO claim about sound fidelity, preset quality, or any
frozen favorites selection. Engine-dependent behavior (rendering) is not
tested here — no engine tree is required or used.

Python 3 standard library only.
"""

import importlib.util
import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sel = _load("sxt013_select", "tools/select_candidates.py")
ls = _load("sxt013_listen", "tools/listening_session.py")

CANDIDATES = REPO / "reports" / "sxt-013" / "candidates"
PROFILES = ("balanced", "factory-lean", "contributor-lean")


def run_builder(out_dir, graphs=None, census=None):
    cmd = [sys.executable, str(REPO / "tools" / "select_candidates.py"),
           "--profile", "all", "--out-dir", str(out_dir)]
    if graphs:
        cmd += ["--graphs", str(graphs)]
    if census:
        cmd += ["--census", str(census)]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    out = tmp_path_factory.mktemp("rebuilt")
    proc = run_builder(out)
    assert proc.returncode == 0, proc.stderr
    return out


def slate_path(kind, profile):
    return CANDIDATES / f"{kind}-{profile}.json"


class TestDeterminism:
    def test_same_inputs_byte_identical(self, rebuilt, tmp_path):
        out = tmp_path / "second-run"
        proc = run_builder(out)
        assert proc.returncode == 0, proc.stderr
        for profile in PROFILES:
            for kind in ("slate-256", "pilot-32"):
                a = (rebuilt / f"{kind}-{profile}.json").read_bytes()
                b = (out / f"{kind}-{profile}.json").read_bytes()
                assert a == b, f"non-deterministic output: {kind}-{profile}"

    def test_committed_artifacts_are_current(self, rebuilt):
        for profile in PROFILES:
            for kind in ("slate-256", "pilot-32"):
                committed = slate_path(kind, profile).read_bytes()
                fresh = (rebuilt / f"{kind}-{profile}.json").read_bytes()
                assert committed == fresh, (
                    f"committed {kind}-{profile}.json is stale; regenerate "
                    f"with tools/select_candidates.py --profile all")


class TestTamperRefusal:
    @pytest.fixture(scope="class")
    def tampered(self, tmp_path_factory):
        root = tmp_path_factory.mktemp("tamper")
        graphs = root / "graphs.jsonl"
        census = root / "census.csv"
        graphs.write_bytes((REPO / "corpus/normalized/graphs.jsonl").read_bytes())
        census.write_bytes(
            (REPO / "corpus/census-v0.1/results/per-preset.csv").read_bytes())
        lines = graphs.read_text(encoding="utf-8").splitlines()
        d = json.loads(lines[100])
        d["sha"] = "0" * 40
        lines[100] = json.dumps(d, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False)
        graphs.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return graphs, census

    def test_refuses_mismatched_census_hash(self, tampered, tmp_path):
        graphs, census = tampered
        out = tmp_path / "out"
        proc = run_builder(out, graphs=graphs, census=census)
        assert proc.returncode == 2
        assert "census-hash integrity check FAILED" in proc.stderr
        assert not (out / "slate-256-balanced.json").exists()


class TestSlates:
    def test_slate_sizes_and_quotas(self):
        quotas = sel.PROFILES["balanced"]["slate_quotas"]
        doc = json.loads(slate_path("slate-256", "balanced").read_text())
        assert doc["totals"]["selected"] == 256
        cats = {}
        for c in doc["candidates"]:
            cats[c["category"]] = cats.get(c["category"], 0) + 1
        assert cats == quotas
        assert doc["totals"]["categories"] == quotas

    def test_both_banks_in_every_profile(self):
        for profile in PROFILES:
            doc = json.loads(slate_path("slate-256", profile).read_text())
            banks = doc["totals"]["banks"]
            assert banks["factory"] > 0 and banks["contributor"] > 0
            assert sum(banks.values()) == 256
            bank_counts = {"factory": 0, "contributor": 0}
            for c in doc["candidates"]:
                bank_counts[c["bank"]] += 1
            assert bank_counts == banks

    def test_pilot_is_subset_of_slate(self):
        for profile in PROFILES:
            slate = json.loads(slate_path("slate-256", profile).read_text())
            pilot = json.loads(slate_path("pilot-32", profile).read_text())
            assert pilot["totals"]["selected"] == 32
            slate_ids = {c["id"] for c in slate["candidates"]}
            for c in pilot["candidates"]:
                assert c["id"] in slate_ids

    def test_census_hashes_and_reasons_present(self):
        for profile in PROFILES:
            doc = json.loads(slate_path("slate-256", profile).read_text())
            for c in doc["candidates"]:
                assert len(c["census_blob_sha1"]) == 40
                assert c["reason"]["slot"]
                assert c["features"]

    def test_no_popularity_data_field_anywhere(self):
        for profile in PROFILES:
            doc = json.loads(slate_path("slate-256", profile).read_text())
            for c in doc["candidates"]:
                allowed = {"id", "path", "bank", "category", "directory",
                           "author", "census_blob_sha1", "size_bytes",
                           "stored_revision", "features", "reason"}
                assert set(c) <= allowed
                assert set(c["reason"]) <= {
                    "slot", "rank_in_stage", "new_diversity_features",
                    "author_cap_overrun", "swapped_for", "selection"}


class TestCensusIntegrityHelpers:
    def test_load_census_size(self):
        census = sel.load_census(sel.DEFAULT_CENSUS_CSV)
        assert len(census) == 3561

    def test_load_graphs_refuses_missing_census_row(self, tmp_path):
        census = sel.load_census(sel.DEFAULT_CENSUS_CSV)
        census.pop(next(iter(census)))
        with pytest.raises(sel.Refuse):
            sel.load_graphs(sel.DEFAULT_GRAPHS, census)


class TestListeningHelpers:
    def test_load_slate_rejects_foreign_schema(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"schema_version": "nope"}))
        with pytest.raises(ls.Refuse):
            ls.load_slate(bad)

    def test_wav_rms_and_level_match(self, tmp_path):
        wav = tmp_path / "tone.wav"
        samples = [int(8000 * v) for v in
                   (0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5)]
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        rms = ls.wav_rms(wav)
        assert abs(rms - 4000 / 32768) < 1e-6
        matched, gain = ls.level_match(wav, 0.5, tmp_path, "lm")
        assert abs(gain - 0.5 * 32768 / 4000) < 1e-6
        assert abs(ls.wav_rms(matched) - 0.5) < 1e-6

    def test_acceptance_mode_string(self):
        assert "mode=open" in ls.ACCEPTANCE_RULE
        assert "supplementary" in ls.ACCEPTANCE_RULE
