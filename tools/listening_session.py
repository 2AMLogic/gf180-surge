#!/usr/bin/env python3
"""SXT-013 apparatus: structured listening-session harness for favorites.

For each candidate of a pilot/slate JSON produced by tools/select_candidates.py
this harness:

  1. re-verifies the candidate's census blob SHA-1 against the committed
     census (mismatch refuses the session),
  2. locates or renders its fixture audio through the SXT-012 renderer
     (fixtures/render_fixture.py, unchanged: fresh-instance reset policy,
     wet + diagnostic dry, no normalization) and caches it locally,
  3. pairs the WET render against the comparison the operator requested
     (default: the diagnostic DRY render; or --compare custom:<path>),
  4. runs the requested session mode and records structured ratings.

Modes
  open   UNBLINDED, LEVEL-CORRECT: stimuli keep their native render levels
         (no per-clip normalization). Per the fidelity policy (DRAFT), only
         ratings recorded in this mode count toward the favorites acceptance.
  blind  pairwise blind: A/B order randomized per candidate; optional
         --level-match RMS-matches the quieter stimulus (a level MATCH, which
         is a normalization of the pair and therefore supplementary-only).
         Stimulus identities are revealed and recorded only after rating.

Method note (docs/REUSE-AUDIT.md): this is an original implementation that
adapts the METHOD of the Parasynth audition harness and the TorchSynth
explorer-session/favorites contracts (both Apache-2.0, pinned in the audit).
No sibling code is copied; playback is delegated to the platform player.

HONESTY: this tool records what a listener reports; it computes no fidelity
metric and confers no support/fidelity/quality claim by itself. A
--dry-run session is a machine exercise with placeholder ratings — it
demonstrates plumbing end-to-end and is NOT human listening.

Python 3 standard library only (the pinned-python render runs in a
subprocess of fixtures/render_fixture.py, which enforces its own runtime).
"""

import argparse
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

DEFAULT_CENSUS_CSV = REPO_ROOT / "corpus" / "census-v0.1" / "results" / "per-preset.csv"
DEFAULT_SESSIONS_DIR = REPO_ROOT / "decisions" / "listening-sessions"
DEFAULT_CACHE_DIR = REPO_ROOT / ".listening-cache"
DEFAULT_SEQUENCE = "seq-notes-coverage-v1"
RENDER_SCRIPT = REPO_ROOT / "fixtures" / "render_fixture.py"
ORACLE_MANIFEST = REPO_ROOT / "oracle" / "manifest.json"

SCHEMA_VERSION = "sxt-013-listening-session/1.0.0"
ISSUE = "SXT-013"

ACCEPTANCE_RULE = (
    "Ratings count toward favorites acceptance ONLY in mode=open "
    "(unblinded, level-correct, no per-clip normalization). Blind "
    "level-matched sessions are supplementary per the fidelity policy "
    "(contracts/fidelity-policy-DRAFT.md, listening procedure).")

CLAIM_SCOPE = (
    "A listening session records one listener's structured judgments on "
    "fixed audio. It is not a fidelity measurement, not a support claim, and "
    "not by itself a frozen selection. Dry-run sessions are machine "
    "exercises with placeholder ratings and are NOT human listening.")


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(path):
    data = Path(path).read_bytes()
    blob = b"blob %d\x00" % len(data) + data
    return hashlib.sha1(blob).hexdigest()


def load_census(census_csv):
    by_path = {}
    import csv

    with open(census_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_path[row["path"]] = row["git_blob_sha1"]
    if not by_path:
        raise Refuse("census per-preset.csv has no data rows")
    return by_path


def load_slate(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("schema_version") != "sxt-013-candidate-slate/1.0.0":
        raise Refuse(f"{path}: not a select_candidates.py slate "
                     f"(schema_version {doc.get('schema_version')!r})")
    if not doc.get("candidates"):
        raise Refuse(f"{path}: slate has no candidates")
    return doc


def engine_root():
    env = os.environ.get("ORACLE_SURGE_DIR")
    if env:
        return Path(env)
    if ORACLE_MANIFEST.exists():
        with open(ORACLE_MANIFEST, encoding="utf-8") as f:
            loc = (json.load(f).get("engine", {}).get("expected_checkout", {})
                   .get("location_used_for_evidence"))
        if loc and Path(loc).exists():
            return Path(loc)
    raise Refuse(
        "cannot locate the pinned engine tree; set ORACLE_SURGE_DIR")


def verify_candidate(cand, census):
    path = cand.get("path")
    if path not in census:
        raise Refuse(f"candidate not in census: {path}")
    if cand.get("census_blob_sha1") != census[path]:
        raise Refuse(
            f"census blob mismatch for {path}: slate "
            f"{cand.get('census_blob_sha1')!r} != census {census[path]!r}")
    preset_abs = engine_root() / path
    if not preset_abs.exists():
        raise Refuse(f"preset file missing from pinned engine tree: {preset_abs}")
    actual = git_blob_sha1(preset_abs)
    if actual != census[path]:
        raise Refuse(
            f"on-disk blob mismatch for {path}: {actual} != census "
            f"{census[path]}")
    return preset_abs


def render_wet_dry(preset_abs, sequence, cache_dir):
    """Locate or render wet+dry via fixtures/render_fixture.py (subprocess)."""
    slug = preset_abs.stem.replace(" ", "_")
    out_dir = cache_dir / slug
    wet = out_dir / f"{sequence}-wet.wav"
    dry = out_dir / f"{sequence}-dry.wav"
    if wet.exists() and dry.exists():
        return wet, dry, {"rendered": False}
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(RENDER_SCRIPT), "render",
           "--preset-file", str(preset_abs),
           "--sequence", sequence, "--out", str(out_dir)]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Refuse(f"renderer failed ({proc.returncode}): "
                     f"{(proc.stderr or proc.stdout).strip()[-500:]}")
    stdout = proc.stdout
    try:
        info = json.JSONDecoder().raw_decode(stdout[stdout.index("{"):])[0]
    except (ValueError, IndexError) as exc:
        raise Refuse(f"cannot parse renderer output: {exc}; "
                     f"stdout tail: {stdout[-300:]}") from exc
    return wet, dry, {"rendered": True, "renderer_report": info}


def wav_rms(path):
    """RMS of a 16-bit PCM wav as float in [0, 1] (sample scale)."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise Refuse(f"unexpected wav format: {path}")
        frames = w.readframes(w.getnframes())
    n = len(frames) // 2
    if n == 0:
        return 0.0
    ints = struct.unpack(f"<{n}h", frames)
    acc = 0
    for v in ints:
        acc += float(v) * float(v)
    return (acc / n) ** 0.5 / 32768.0


def level_match(stim_path, target_rms, cache_dir, tag):
    """Write an RMS-matched copy of stim (supplementary-blind mode only)."""
    with wave.open(str(stim_path), "rb") as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    stim_rms = wav_rms(stim_path)
    if stim_rms <= 0.0:
        raise Refuse(f"silent stimulus, cannot level-match: {stim_path}")
    gain = target_rms / stim_rms
    n = len(frames) // 2
    ints = struct.unpack(f"<{n}h", frames)
    out = bytearray()
    for v in ints:
        x = int(round(v * gain))
        out += struct.pack("<h", max(-32768, min(32767, x)))
    out_path = cache_dir / f"{Path(stim_path).stem}-{tag}.wav"
    with wave.open(str(out_path), "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(out))
    return out_path, gain


def play(path, play_mode):
    if play_mode == "off":
        print(f"    [play off] listen to: {path}")
        return
    player = None
    for cand in (("afplay",) if sys.platform == "darwin" else
                 ("aplay", "play", "paplay")):
        if shutil.which(cand):
            player = cand
            break
    if player is None:
        print(f"    [no player found] listen to: {path}")
        return
    print(f"    playing ({player}): {path}")
    subprocess.run([player, str(path)], check=False)


def ask(prompt, validator, default=None):
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            return validator(raw)
        except Exception:
            print("    invalid input, try again")


def scale_1_5(raw):
    v = int(raw)
    if not 1 <= v <= 5:
        raise ValueError
    return v


def conf_1_5(raw):
    v = int(raw)
    if not 1 <= v <= 5:
        raise ValueError
    return v


def ask_choice(options):
    def parse(raw):
        low = raw.strip().lower()
        if low in options:
            return low
        raise ValueError
    return parse


def ask_bool(prompt):
    return ask(prompt, ask_choice(("y", "yes", "n", "no"))) in ("y", "yes")


def stim_record(kind, path, level_treatment):
    return {
        "kind": kind,
        "path": str(path),
        "sha256": sha256_file(path),
        "level_treatment": level_treatment,
    }


def rate_open(cand, wet, compare, compare_kind, play_mode):
    """Unblinded level-correct rating (the acceptance mode)."""
    print(f"  OPEN (level-correct) pair for: {cand['path']}")
    print("    stimulus WET   (native level):")
    play(wet, play_mode)
    print(f"    stimulus {compare_kind.upper()} (native level):")
    play(compare, play_mode)
    ratings = {
        "fidelity_wet_vs_comparison_1to5": ask(
            "    fidelity of WET vs comparison [1-5]: ", scale_1_5),
        "timbre_match_1to5": ask(
            "    timbre match [1-5]: ", scale_1_5),
        "artifacts": ask("    artifacts [none|minor|severe]: ",
                         ask_choice(("none", "minor", "severe"))),
        "tail_ok": ask_bool("    effect tail present/acceptable? [y/n]: "),
        "confidence_1to5": ask("    confidence [1-5]: ", conf_1_5),
        "notes": input("    notes (free text, may be empty): ").strip(),
    }
    return {
        "ratings": ratings,
        "counts_toward_acceptance": True,
        "blind": False,
    }


def rate_blind(cand, wet, compare, compare_kind, play_mode, level_match_on,
               cache_dir):
    """Pairwise blind rating with randomized order; supplementary-only."""
    rng = random.SystemRandom()
    stimuli = [("wet", wet), (compare_kind, compare)]
    treatment = {"method": "none_native_levels"}
    if level_match_on:
        # Pair RMS match to the louder stimulus. This normalizes the pair and
        # is therefore supplementary-only per the fidelity policy.
        target = max(wav_rms(wet), wav_rms(compare))
        treatment = {"method": "rms_match_pair_max",
                     "target_rms": round(target, 8)}
        prepared = []
        for kind, path in stimuli:
            if abs(wav_rms(path) - target) > 1e-9:
                path, gain = level_match(path, target, cache_dir,
                                         f"{kind}-lm")
                treatment[f"{kind}_gain_applied"] = round(gain, 6)
            prepared.append((kind, path))
        stimuli = prepared

    order = [(kind, path) for kind, path in stimuli]
    rng.shuffle(order)

    print(f"  BLIND pair for: {cand['path']}"
          + ("  [LEVEL-MATCHED — supplementary only]" if level_match_on
             else "  [native levels — supplementary only]"))
    labels = {}
    for label, (kind, path) in zip(("A", "B"), order):
        labels[label] = kind
        print(f"    stimulus {label}:")
        play(path, play_mode)
    pref = ask("    preference [A|B|tie]: ", ask_choice(("a", "b", "tie")))
    pref = pref.upper() if pref in ("a", "b") else "tie"
    confidence = ask("    confidence [1-5]: ", conf_1_5)
    notes = input("    notes (free text, may be empty): ").strip()
    unblind = {"A": labels["A"], "B": labels["B"]}
    print(f"    unblinded: A={unblind['A']}, B={unblind['B']}")
    return {
        "ratings": {
            "preference": pref,
            "confidence_1to5": confidence,
            "notes": notes,
        },
        "counts_toward_acceptance": False,
        "blind": True,
        "blind_assignment": unblind,
        "level_treatment": treatment,
    }


def placeholder_record():
    """Machine dry-run: plumbing verified, NO human ratings."""
    return {
        "ratings": {
            "fidelity_wet_vs_comparison_1to5": None,
            "timbre_match_1to5": None,
            "artifacts": None,
            "tail_ok": None,
            "confidence_1to5": None,
            "notes": "PLACEHOLDER: machine dry-run, no human listening "
                     "occurred; ratings are deliberately absent",
        },
        "counts_toward_acceptance": False,
        "blind": False,
        "is_placeholder": True,
        "level_treatment": {"method": "none_native_levels"},
    }


def next_session_path(sessions_dir, base):
    sessions_dir.mkdir(parents=True, exist_ok=True)
    candidate = sessions_dir / f"{base}.json"
    n = 2
    while candidate.exists():
        candidate = sessions_dir / f"{base}-{n}.json"
        n += 1
    return candidate


def slugify(text):
    keep = [c if (c.isalnum() and c.isascii()) else "-" for c in text.lower()]
    return "".join(keep).strip("-")[:40] or "operator"


def run_session(args):
    census = load_census(args.census)
    slate = load_slate(args.slate)
    candidates = slate["candidates"]
    if args.limit:
        if args.limit > len(candidates):
            raise Refuse(f"--limit {args.limit} exceeds slate size "
                         f"({len(candidates)})")
        if args.pick == "spread":
            step = len(candidates) / args.limit
            candidates = [candidates[min(int(i * step), len(candidates) - 1)]
                          for i in range(args.limit)]
        else:
            candidates = candidates[: args.limit]
    compare_kind = args.compare
    if compare_kind.startswith("custom:"):
        custom = Path(compare_kind[len("custom:"):]).resolve()
        if not custom.exists():
            raise Refuse(f"custom comparison audio not found: {custom}")
        compare_kind = f"custom:{custom}"

    if args.dry_run:
        operator = "machine-dry-run (scripted; NOT human listening)"
        mode = "dry-run"
    else:
        operator = args.operator
        if not operator:
            raise Refuse("--operator NAME is required (or use --dry-run)")
        mode = args.mode

    session_base = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
        + ("machine-dryrun" if args.dry_run else slugify(operator))
        + ("" if args.dry_run else f"-{mode}"))
    session_path = next_session_path(Path(args.sessions_dir), session_base)

    print(f"SXT-013 listening session — slate {slate['artifact']}, "
          f"{len(candidates)} candidate(s), mode={mode}")
    if args.dry_run:
        print("*** DRY RUN: scripted machine operator; placeholder ratings; "
              "this is NOT human listening ***")
    else:
        print(ACCEPTANCE_RULE)

    records = []
    cache_dir = Path(args.audio_cache).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for idx, cand in enumerate(candidates, 1):
        print(f"[{idx}/{len(candidates)}] {cand['path']} "
              f"({cand['bank']}/{cand['category']})")
        preset_abs = verify_candidate(cand, census)
        wet, dry, render_info = render_wet_dry(
            preset_abs, args.sequence, cache_dir)
        if isinstance(compare_kind, str) and compare_kind == "dry":
            compare, compare_label = dry, "dry"
        else:
            compare = Path(compare_kind.split("custom:", 1)[1])
            compare_label = "custom"
        record = {
            "candidate_id": cand["id"],
            "path": cand["path"],
            "bank": cand["bank"],
            "category": cand["category"],
            "census_blob_sha1": cand["census_blob_sha1"],
            "sequence_id": args.sequence,
            "audio": {
                "wet": stim_record("wet", wet, "native"),
                "comparison": stim_record(compare_label, compare, "native"),
                "rendered_this_session": render_info.get("rendered", False),
            },
        }
        if args.dry_run:
            record.update(placeholder_record())
        elif mode == "open":
            record.update(rate_open(cand, wet, compare, compare_label,
                                    args.play))
        else:
            record.update(rate_blind(cand, wet, compare, compare_label,
                                     args.play, args.level_match, cache_dir))
        records.append(record)

    session = {
        "schema_version": SCHEMA_VERSION,
        "issue": ISSUE,
        "session_id": session_path.stem,
        "claim_scope": CLAIM_SCOPE,
        "acceptance_rule": ACCEPTANCE_RULE,
        "status": ("DRY_RUN_NOT_HUMAN_LISTENING" if args.dry_run
                   else "HUMAN_LISTENING_SESSION"),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "operator": operator,
        "mode": mode,
        "level_policy": ("not applicable (machine dry-run; audio at native "
                         "render levels)" if args.dry_run else
                         "level-correct native render levels; no per-clip "
                         "normalization" if mode == "open" else
                         "blind pair; " + ("RMS level-matched (supplementary "
                                           "only)" if args.level_match
                                           else "native levels")),
        "sequence_id": args.sequence,
        "slate": {
            "artifact": slate["artifact"],
            "path": str(Path(args.slate).resolve()),
            "sha256": sha256_file(args.slate),
            "profile": (slate.get("profile") or {}).get("name"),
        },
        "comparison": compare_label,
        "harness": {
            "tool": "tools/listening_session.py",
            "tool_sha256": sha256_file(Path(__file__).resolve()),
            "repo_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                capture_output=True, text=True).stdout.strip(),
            "renderer": "fixtures/render_fixture.py (SXT-012, unmodified)",
        },
        "counts": {
            "candidates": len(records),
            "counting_toward_acceptance": sum(
                1 for r in records if r.get("counts_toward_acceptance")),
        },
        "records": records,
    }
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"session written: {session_path}")
    if args.dry_run:
        print("REMINDER: dry-run sessions demonstrate plumbing only and must "
              "never be cited as listening evidence.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="SXT-013 structured listening-session harness "
                    "(records human judgments; computes nothing)")
    ap.add_argument("--slate", required=True,
                    help="pilot/slate JSON from tools/select_candidates.py")
    ap.add_argument("--operator", help="human operator name (required unless "
                                       "--dry-run)")
    ap.add_argument("--mode", choices=("open", "blind"), default="open",
                    help="open = unblinded level-correct (acceptance mode); "
                         "blind = randomized A/B (supplementary)")
    ap.add_argument("--level-match", action="store_true",
                    help="blind mode only: RMS-match the pair (supplementary "
                         "only; policy forbids this for acceptance)")
    ap.add_argument("--compare", default="dry",
                    help="'dry' (diagnostic bypass render) or 'custom:<path>'")
    ap.add_argument("--sequence", default=DEFAULT_SEQUENCE,
                    help=f"fixture sequence id (default {DEFAULT_SEQUENCE})")
    ap.add_argument("--limit", type=int, default=0,
                    help="only N slate candidates (0 = all)")
    ap.add_argument("--pick", choices=("first", "spread"), default="first",
                    help="with --limit: first N, or N spread evenly across "
                         "the slate (deterministic)")
    ap.add_argument("--play", choices=("auto", "off"), default="auto",
                    help="attempt platform playback or print paths only")
    ap.add_argument("--audio-cache", default=str(DEFAULT_CACHE_DIR),
                    help="render cache directory (default .listening-cache/)")
    ap.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR),
                    help="where session JSONs are written")
    ap.add_argument("--census", default=str(DEFAULT_CENSUS_CSV))
    ap.add_argument("--dry-run", action="store_true",
                    help="scripted machine operator: renders real audio, "
                         "records PLACEHOLDER ratings, not human listening")
    args = ap.parse_args()
    try:
        return run_session(args)
    except Refuse as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
