#!/usr/bin/env python3
"""Generate synthetic listening-session samples for the audition gate (#447).

Runs the real harness (tools/listening_session.py) three times with a FAKE
renderer, a MOCKED platform player and SCRIPTED listener answers, and writes
one session JSON per playback/confirmation case next to this script:

  - sample-session-player-exit-nonzero-unconfirmed.json
    (negative control: player exits 1, ordinary ratings, confirmation
     declined -> candidate NOT counted; the legacy unconditional result is
     demonstrated rejected by the eligibility gate)
  - sample-session-auto-confirmed.json
    (player exits 0, listener confirms -> counted, player method recorded)
  - sample-session-playoff-manual-confirmed.json
    (--play off, listener confirms external audition -> counted, method
     recorded verbatim)

Every sample is a bookkeeping exercise: NOT pinned-oracle audio, NOT human
listening, and no fidelity or preset claim. Standard library only.

Reproduce:  python3 reports/sxt-013/audition-gate/generate-samples.py
"""

import builtins
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools"))
import listening_session as ls  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

SAMPLES = [
    ("sample-session-player-exit-nonzero-unconfirmed.json",
     "player mocked to exit 1; ordinary ratings; listener DECLINES the "
     "audition confirmation -> candidate not counted (negative control)",
     dict(player_rc=1, confirm=False, method=None, play="auto")),
    ("sample-session-auto-confirmed.json",
     "player mocked to exit 0; listener confirms hearing both stimuli -> "
     "counted, audition method records the automatic player",
     dict(player_rc=0, confirm=True, method=None, play="auto")),
    ("sample-session-playoff-manual-confirmed.json",
     "--play off; listener confirms external audition of the printed files "
     "-> counted, external method recorded verbatim",
     dict(player_rc=None, confirm=True,
          method="laptop speakers, files played from the printed paths",
          play="off")),
]


def write_wav(path, level):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(
            (level, -level)[i % 2].to_bytes(2, "little", signed=True)
            for i in range(16)))


def make_workspace(root):
    preset = root / "fake.fxp"
    preset.write_bytes(b"FAKE-PRESET-BYTES" * 4)
    rel = "fake/A.fxp"
    blob = ls.git_blob_sha1(preset)
    census = root / "census.csv"
    census.write_text(f"path,git_blob_sha1\n{rel},{blob}\n")
    slate = root / "slate.json"
    slate.write_text(json.dumps({
        "schema_version": "sxt-013-candidate-slate/1.0.0",
        "artifact": "audition-gate-sample",
        "candidates": [{"id": "c0", "path": rel, "bank": "fake",
                        "category": "sample", "census_blob_sha1": blob}],
    }))
    return slate, census, rel


def install_rendererFake(preset):
    def fake_verify(cand, census):
        return preset

    def fake_renderer(preset_abs, sequence, out_dir):
        write_wav(Path(out_dir) / f"{sequence}-wet.wav", 1200)
        write_wav(Path(out_dir) / f"{sequence}-dry.wav", 600)
        return {"fake": True}

    ls.verify_candidate = fake_verify
    ls.run_renderer = fake_renderer


def run_one(out_name, note, spec, root):
    slate, census, rel = make_workspace(root)
    preset = root / "fake.fxp"
    install_rendererFake(preset)
    sessions = root / "sessions"

    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "git":  # harness repo_commit probe stays real
            return real_run(cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, spec["player_rc"] or 0)

    if spec["play"] == "auto":
        ls.shutil.which = lambda name: "fakeplay"
        ls.subprocess.run = fake_run

    answers = ["5", "4", "none", "y", "3", "",  # ratings + notes
               "y" if spec["confirm"] else "n"]  # audition confirmation
    if spec["confirm"] and spec["method"] is not None:
        answers.append(spec["method"])
    it = iter(answers)
    builtins.input = lambda *a, **k: next(it)

    args = type("Args", (), {})()
    args.slate = str(slate)
    args.census = str(census)
    args.limit = 0
    args.pick = "first"
    args.compare = "dry"
    args.dry_run = False
    args.operator = "scripted-audition-gate-sample (NOT human listening)"
    args.mode = "open"
    args.sequence = ls.DEFAULT_SEQUENCE
    args.sessions_dir = str(sessions)
    args.audio_cache = str(root / "cache")
    args.play = spec["play"]
    args.level_match = False
    assert ls.run_session(args) == 0
    session = json.loads(next(sessions.glob("*.json")).read_text())
    session["_sample_note"] = (
        f"FAKE bookkeeping sample for issue #447 ({note}); mocked player, "
        "scripted answers, tiny synthetic WAVs. NOT pinned-oracle audio, "
        "NOT human listening, no fidelity or preset claim.")
    session["harness"]["tool_sha256"] = "<omitted>"
    (OUT_DIR / out_name).write_text(
        json.dumps(session, indent=2, sort_keys=True) + "\n")
    rec = session["records"][0]
    print(f"{out_name}: counts={rec['counts_toward_acceptance']} "
          f"audition={rec['audition']['verification']} "
          f"wet_playback={rec['playback']['wet']['outcome']}")


def legacy_rejection_demo():
    """The issue's negative control, as a direct gate check."""
    legacy = {"ratings": {"fidelity_wet_vs_comparison_1to5": 5},
              "counts_toward_acceptance": True, "blind": False}
    problem = ls.acceptance_eligibility_problem(legacy)
    print("legacy unconditional record (pre-#447 shape) rejected by gate: "
          f"{problem!r}")
    assert problem
    return problem


def main():
    for out_name, note, spec in SAMPLES:
        with tempfile.TemporaryDirectory() as td:
            run_one(out_name, note, spec, Path(td))
    legacy_rejection_demo()
    print("done")


if __name__ == "__main__":
    main()
