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

import argparse
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


def _feed(answers):
    it = iter(answers)
    return lambda *a, **k: next(it)


def _write_wav(path, level=1000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack("<8h", *([level, -level] * 4)))
    return path


class TestAuditionGate:
    """Issue #447: acceptance ratings require recorded audition.

    Bookkeeping controls only: mocked platform players, scripted listener
    answers, tiny synthetic WAVs. No audio device, no human judgment, no
    fidelity claim.
    """

    @pytest.fixture
    def stimuli(self, tmp_path):
        return (_write_wav(tmp_path / "stim-wet.wav"),
                _write_wav(tmp_path / "stim-dry.wav"))

    @staticmethod
    def _ratings_answers(confirm, method=None):
        # fidelity, timbre, artifacts, tail, confidence, notes, then the
        # audition confirmation (and the free-text method when the automatic
        # path did not cleanly play both stimuli).
        answers = ["5", "4", "none", "y", "3", "", "y" if confirm else "n"]
        if confirm and method is not None:
            answers.append(method)
        return answers

    @staticmethod
    def _install_player(monkeypatch, which_name="fakeplay", rc=None,
                        exc=None):
        calls = []
        monkeypatch.setattr(ls.shutil, "which", lambda name: which_name)

        def run(cmd, **kwargs):
            calls.append(cmd)
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(cmd, rc)
        monkeypatch.setattr(ls.subprocess, "run", run)
        return calls

    def test_negative_control_player_exit_nonzero_never_counts(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        self._install_player(monkeypatch, rc=1)
        monkeypatch.setattr(
            "builtins.input", _feed(self._ratings_answers(confirm=False)))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "auto")
        assert rec["playback"]["wet"]["outcome"] == "player_exit_nonzero"
        assert rec["playback"]["wet"]["returncode"] == 1
        assert rec["playback"]["comparison"]["outcome"] == "player_exit_nonzero"
        assert rec["counts_toward_acceptance"] is False
        assert rec["audition"]["verification"] == ls.AUDITION_UNCONFIRMED
        assert ls.acceptance_eligibility_problem(rec)
        # failure control: the PRE-#447 unconditional result (ordinary
        # ratings, counts flag True, no audition fields) is rejected by the
        # eligibility gate rather than silently counting.
        legacy = {"ratings": rec["ratings"],
                  "counts_toward_acceptance": True, "blind": False}
        assert ls.acceptance_eligibility_problem(legacy)

    def test_manual_confirmation_success_preserves_play_off(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        monkeypatch.setattr("builtins.input", _feed(
            self._ratings_answers(
                confirm=True, method="laptop speakers via printed paths")))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "off")
        assert rec["counts_toward_acceptance"] is True
        assert rec["audition"]["confirmed_heard_both"] is True
        assert rec["audition"]["method"] == \
            "laptop speakers via printed paths"
        assert rec["playback"]["wet"]["outcome"] == "not_attempted_play_off"
        assert rec["playback"]["comparison"]["path"] == str(compare)
        assert ls.acceptance_eligibility_problem(rec) is None

    def test_blank_method_reprompt_still_blank_not_counted(
            self, stimuli, monkeypatch):
        # Negative control for the manual/fallback branch: confirming hearing
        # with --play off and then supplying blank/whitespace methods must
        # not fabricate a method or let the rating count.
        wet, compare = stimuli
        answers = self._ratings_answers(confirm=True, method="")
        answers.append("   \t ")  # still blank on the re-prompt
        monkeypatch.setattr("builtins.input", _feed(answers))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "off")
        assert rec["counts_toward_acceptance"] is False
        assert rec["audition"]["confirmed_heard_both"] is True
        assert rec["audition"]["method"] is None
        assert rec["audition"]["verification"] == ls.AUDITION_UNCONFIRMED
        problem = ls.acceptance_eligibility_problem(rec)
        assert problem and "counts_toward_acceptance is false" in problem

    def test_blank_method_reprompt_then_valid_counts_verbatim(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        answers = self._ratings_answers(confirm=True, method="")
        answers.append("  studio monitors, both files  ")
        monkeypatch.setattr("builtins.input", _feed(answers))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "off")
        assert rec["counts_toward_acceptance"] is True
        assert rec["audition"]["method"] == "studio monitors, both files"
        assert rec["audition"]["verification"] == ls.AUDITION_CONFIRMED
        assert ls.acceptance_eligibility_problem(rec) is None

    def test_eligibility_gate_rejects_placeholder_method(self):
        # The 1.1.0-era fabricated placeholder must never substitute for a
        # listener-supplied method even when every other field looks valid.
        rec = {"ratings": {}, "counts_toward_acceptance": True,
               "blind": False,
               "audition": {"confirmed_heard_both": True,
                            "method": ls.AUDITION_METHOD_PLACEHOLDER,
                            "verification": ls.AUDITION_CONFIRMED}}
        problem = ls.acceptance_eligibility_problem(rec)
        assert problem and "placeholder" in problem

    def test_auto_process_success_still_needs_confirmation(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        self._install_player(monkeypatch, rc=0)
        monkeypatch.setattr(
            "builtins.input", _feed(self._ratings_answers(confirm=False)))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "auto")
        assert rec["playback"]["wet"]["outcome"] == ls.PLAYED_PROCESS_OK
        assert rec["counts_toward_acceptance"] is False
        assert ls.acceptance_eligibility_problem(rec)

    def test_auto_success_confirmed_records_player_and_counts(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        self._install_player(monkeypatch, rc=0)
        monkeypatch.setattr(
            "builtins.input", _feed(self._ratings_answers(confirm=True)))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "auto")
        assert rec["counts_toward_acceptance"] is True
        assert rec["audition"]["method"] == "auto:aplay"
        assert rec["audition"]["verification"] == ls.AUDITION_CONFIRMED
        assert ls.acceptance_eligibility_problem(rec) is None

    def test_launch_exception_recorded_and_external_confirmation_counts(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        self._install_player(monkeypatch, exc=OSError("exec format error"))
        monkeypatch.setattr("builtins.input", _feed(
            self._ratings_answers(confirm=True, method="phone+headphones")))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "auto")
        assert rec["playback"]["wet"]["outcome"] == "launch_error"
        assert "exec format error" in rec["playback"]["wet"]["error"]
        assert rec["counts_toward_acceptance"] is True
        assert rec["audition"]["method"] == "phone+headphones"
        assert ls.acceptance_eligibility_problem(rec) is None

    def test_missing_player_recorded_and_declined_not_counted(
            self, stimuli, monkeypatch):
        wet, compare = stimuli
        monkeypatch.setattr(ls.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            "builtins.input", _feed(self._ratings_answers(confirm=False)))
        rec = ls.rate_open({"path": "fake/A.fxp"}, wet, compare, "dry", "auto")
        assert rec["playback"]["wet"]["outcome"] == "no_player_found"
        assert rec["counts_toward_acceptance"] is False
        assert ls.acceptance_eligibility_problem(rec)

    def test_blind_records_playback_and_stays_supplementary(
            self, stimuli, tmp_path, monkeypatch):
        wet, compare = stimuli
        self._install_player(monkeypatch, rc=0)
        monkeypatch.setattr("builtins.input", _feed(["a", "4", ""]))
        rec = ls.rate_blind({"path": "fake/A.fxp"}, wet, compare, "dry",
                            "auto", False, tmp_path)
        assert rec["counts_toward_acceptance"] is False
        assert set(rec["playback"]) == {"A", "B"}
        assert ls.acceptance_eligibility_problem(rec)


class TestAuditionGateSession:
    """Session-level gating: unconfirmed candidate uncounted, session goes on."""

    @staticmethod
    def _slate_and_census(tmp_path):
        census = tmp_path / "census.csv"
        rels = ["fake/A.fxp", "fake/B.fxp"]
        census.write_text("path,git_blob_sha1\n" + "\n".join(
            f"{r},{ls.git_blob_sha1(tmp_path / 'fake.fxp')}" for r in rels)
            + "\n")
        cands = [{"id": f"c{i}", "path": r, "bank": "b", "category": "c",
                  "census_blob_sha1": ls.git_blob_sha1(tmp_path / "fake.fxp")}
                 for i, r in enumerate(rels)]
        slate = tmp_path / "slate.json"
        slate.write_text(json.dumps({
            "schema_version": "sxt-013-candidate-slate/1.0.0",
            "artifact": "fake", "candidates": cands}))
        return slate, census

    def test_unconfirmed_candidate_not_counted_session_continues(
            self, tmp_path, monkeypatch):
        preset = tmp_path / "fake.fxp"
        preset.write_bytes(b"X" * 20)
        slate, census = self._slate_and_census(tmp_path)

        def fake_renderer(preset_abs, sequence, out_dir):
            for kind, lvl in (("wet", 1200), ("dry", 600)):
                _write_wav(Path(out_dir) / f"{sequence}-{kind}.wav", lvl)
            return {"fake": True}
        monkeypatch.setattr(ls, "verify_candidate", lambda c, cen: preset)
        monkeypatch.setattr(ls, "run_renderer", fake_renderer)
        monkeypatch.setattr(ls.shutil, "which", lambda name: "fakeplay")

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "git":  # the in-harness repo_commit probe
                return subprocess.CompletedProcess(cmd, 0, stdout="a" * 40)
            return subprocess.CompletedProcess(cmd, 0)
        monkeypatch.setattr(ls.subprocess, "run", fake_run)
        # candidate 1: ordinary ratings, declines confirmation;
        # candidate 2: ordinary ratings, confirms (auto played cleanly).
        answers = (TestAuditionGate._ratings_answers(confirm=False)
                   + TestAuditionGate._ratings_answers(confirm=True))
        monkeypatch.setattr("builtins.input", _feed(answers))
        args = argparse.Namespace(
            slate=str(slate), census=str(census), limit=0, pick="first",
            compare="dry", dry_run=False, operator="tester", mode="open",
            sequence=ls.DEFAULT_SEQUENCE,
            sessions_dir=str(tmp_path / "sessions"),
            audio_cache=str(tmp_path / "cache"), play="auto",
            level_match=False)
        assert ls.run_session(args) == 0
        session = json.loads(
            next((tmp_path / "sessions").glob("*.json")).read_text())
        recs = session["records"]
        assert len(recs) == 2  # session continued past the unconfirmed one
        assert [r["counts_toward_acceptance"] for r in recs] == [False, True]
        assert recs[0]["audition"]["verification"] == ls.AUDITION_UNCONFIRMED
        assert recs[1]["audition"]["verification"] == ls.AUDITION_CONFIRMED
        assert recs[0]["ratings"]["fidelity_wet_vs_comparison_1to5"] == 5
        assert session["counts"]["counting_toward_acceptance"] == 1
        assert session["counts"]["audition_unconfirmed_not_counted"] == 1
        assert "supplementary" in ls.ACCEPTANCE_RULE
