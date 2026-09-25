#!/usr/bin/env python3
"""Shared-comparator wet-path tail-gate tests (issue #93).

Covers, on synthetic mono int16 renders written into tmp_path plus the
committed SXT-012 wet fixtures:
  * the declared tail region is read from fixture metadata (note-off offset +
    declared tail length), never inferred from silence;
  * a wet comparison whose model tail is silent FAILS where the same
    comparison with a full tail PASSES (the regression guard the issue asks
    for);
  * a model render truncated before the declared tail region FAILS instead of
    passing on a truncated-window comparison;
  * dry comparisons are unaffected: no gate, no new JSON fields, and a
    byte-identical verdict/JSON when the same pair is graded with --path dry;
  * fail-closed refusals (NO_VERDICT, exit 2): a wet-named reference graded
    without --path wet, --path wet without a sidecar, a sidecar that does not
    describe the reference render, and a sidecar with no declarable tail.

Claim scope: these tests exercise COMPARATOR behaviour only. The "model"
renders are synthetic or derived from the reference itself, so nothing here is
a model-vs-reference, RTL, preset-support, or sound claim.
"""

import json
import os
import subprocess
import sys
import wave

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "compare_audio_reference.py")
SR = 48000

FIXTURE_WET = os.path.join(REPO, "fixtures", "audio", "koala2",
                           "seq-notes-coverage-v1-wet.wav")
FIXTURE_SIDECAR = os.path.join(REPO, "fixtures", "audio", "koala2",
                               "seq-notes-coverage-v1.json")


# ---------------------------------------------------------------- helpers ---

def write_wav(path, data):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.asarray(np.clip(data, -32768, 32767),
                                 dtype="<i2").tobytes())
    return str(path)


def read_wav(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()),
                             dtype="<i2").astype(np.int64)


def run(ref, model, out_json=None, path=None, sidecar=None):
    cmd = [sys.executable, TOOL, "--ref", str(ref), "--model", str(model)]
    if out_json:
        cmd += ["--json", str(out_json)]
    if path:
        cmd += ["--path", path]
    if sidecar:
        cmd += ["--sidecar", str(sidecar)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return r, (json.loads(r.stdout) if r.stdout.strip() else {})


def synth_case(tmp_path, tail_frames=48000, body_frames=96000, tag="case"):
    """A synthetic 'wet' render plus a sidecar declaring its tail region.

    Body: a decaying tone under a note; tail: a slow decay after the declared
    note-off, i.e. the effect tail the gate must see. Values are int16 LSB.
    """
    t_body = np.arange(body_frames) / float(SR)
    body = 8000.0 * np.sin(2 * np.pi * 220.0 * t_body) * np.exp(-t_body * 0.8)
    t_tail = np.arange(tail_frames) / float(SR)
    tail = (body[-1] + 3000.0) * np.sin(
        2 * np.pi * 220.0 * (t_tail + t_body[-1])) * np.exp(-t_tail * 1.2)
    ref = np.round(np.concatenate([body, tail]))
    d = tmp_path / tag
    d.mkdir(exist_ok=True)
    ref_path = write_wav(d / "seq-x-wet.wav", ref)
    sidecar = {
        "engine": {"sample_rate": SR, "block_size_samples": 32},
        "fixture_id": "synthetic__seq-x",
        "wet": {"frames": int(body_frames + tail_frames),
                "last_event_sample": int(body_frames),
                "tail_s": tail_frames / float(SR),
                "wav": os.path.basename(ref_path)},
        "schema_version": 1,
    }
    sc_path = d / "seq-x.json"
    sc_path.write_text(json.dumps(sidecar, indent=2) + "\n")
    return ref, ref_path, str(sc_path), int(body_frames), int(tail_frames)


# --------------------------------------------------- tail region provenance --

def test_tail_region_comes_from_declared_metadata(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="region")
    model = write_wav(tmp_path / "model-region.wav", ref)
    r, j = run(ref_path, model, path="wet", sidecar=sc)
    assert r.returncode == 0, r.stdout + r.stderr
    tc = j["tail_check"]
    assert tc["tail_offset"] == off
    assert tc["tail_frames"] == tail
    assert "last_event_sample" in tc["tail_region_source"]
    assert tc["tail_region_covered"] is True


def test_tail_region_not_inferred_from_silence(tmp_path):
    """A silent gap in the body must not be mistaken for the tail region."""
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="silence")
    gapped = ref.copy()
    gapped[20000:40000] = 0            # long silent stretch inside the body
    ref_path = write_wav(tmp_path / "silence" / "seq-x-wet.wav", gapped)
    model = write_wav(tmp_path / "model-silence.wav", gapped)
    r, j = run(ref_path, model, path="wet", sidecar=sc)
    assert r.returncode == 0, r.stdout + r.stderr
    assert j["tail_check"]["tail_offset"] == off


def test_sidecar_without_declarable_tail_is_refused(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="nodecl")
    bad = json.loads(open(sc).read())
    del bad["wet"]["tail_s"]           # nothing declares the tail extent
    p = tmp_path / "nodecl" / "no-tail.json"
    p.write_text(json.dumps(bad) + "\n")
    model = write_wav(tmp_path / "model-nodecl.wav", ref)
    r, j = run(ref_path, model, path="wet", sidecar=p)
    assert r.returncode == 2
    assert j["verdict"].startswith("NO_VERDICT")
    assert "tail_s" in j["reason"]


# ------------------------------------------------------- the gate verdict ---

def test_silent_tail_fails_where_full_tail_passes(tmp_path):
    """The issue's regression guard: same body, tail present vs tail silent."""
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="gate")

    full = write_wav(tmp_path / "model-full-tail.wav", ref)
    r_full, j_full = run(ref_path, full, path="wet", sidecar=sc)
    assert r_full.returncode == 0, r_full.stdout + r_full.stderr
    assert j_full["verdict"].startswith("PASS")
    assert j_full["tail_check"]["ok"] is True
    assert j_full["tail_check"]["model_tail_present"] is True

    silent = ref.copy()
    silent[off:off + tail] = 0
    silent_p = write_wav(tmp_path / "model-silent-tail.wav", silent)
    r_sil, j_sil = run(ref_path, silent_p, path="wet", sidecar=sc)
    assert r_sil.returncode == 1
    assert j_sil["verdict"].startswith("FAIL")
    tc = j_sil["tail_check"]
    assert tc["ok"] is False
    assert tc["tail_present"] is True          # the reference DOES have a tail
    assert tc["model_tail_present"] is False   # the model does not
    assert "silent" in tc["reason"]


def test_truncated_model_render_fails_the_gate(tmp_path):
    """A truncated window must not pass: the compared span is bit-exact here,
    so every global budget passes and only the tail gate can catch it."""
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="trunc")
    trunc = write_wav(tmp_path / "model-trunc.wav", ref[:off])
    r, j = run(ref_path, trunc, path="wet", sidecar=sc)
    assert r.returncode == 1
    assert all(j["proposed_budget_results"].values()), \
        "the truncated window should satisfy every global budget"
    tc = j["tail_check"]
    assert tc["ok"] is False
    assert tc["tail_region_covered"] is False
    assert "not covered" in tc["reason"]


def test_tail_residual_budget_is_relative_to_the_reference_tail(tmp_path):
    """A tail that is present but decays far too fast fails on the relative
    tail residual while the whole-render budgets still pass."""
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="fast")
    fast = ref.astype(np.float64).copy()
    t = np.arange(tail) / float(SR)
    fast[off:off + tail] = np.round(ref[off:off + tail] * np.exp(-t / 0.15))
    fast_p = write_wav(tmp_path / "model-fast-decay.wav", fast)
    r, j = run(ref_path, fast_p, path="wet", sidecar=sc)
    tc = j["tail_check"]
    assert tc["model_tail_present"] is True
    assert tc["tail_rms_rel_db"] > j["proposed_tail_budget"]["tail_rms_rel_db"]
    assert tc["ok"] is False
    assert r.returncode == 1 and j["verdict"].startswith("FAIL")


def test_tail_check_shape_matches_the_chorus_tool():
    """The shared comparator's tail_check must carry the chorus tool's keys so
    evidence records stay comparable across leaves."""
    src = open(os.path.join(REPO, "tools",
                            "compare_chorus_reference.py")).read()
    for key in ("tail_present", "tail_rms_rel_db", '"ok"'):
        assert key in src
    mod = open(TOOL).read()
    for key in ("tail_present", "tail_rms_rel_db", "model_tail_present",
                "tail_region_covered"):
        assert key in mod


# --------------------------------------------------------- dry unaffected ---

def test_dry_comparison_has_no_tail_gate_and_no_new_fields(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="dry")
    # dry-named copies of the same renders (the wet-name tripwire is separate)
    dry_ref = write_wav(tmp_path / "ref-dry.wav", ref)
    silent = ref.copy()
    silent[off:off + tail] = 0
    dry_model = write_wav(tmp_path / "model-dry.wav", silent)
    r, j = run(dry_ref, dry_model, path="dry")
    assert r.returncode == 0
    assert "tail_check" not in j and "path" not in j
    assert "proposed_tail_budget" not in j
    # the dry verdict is decided by the budgets alone (AGENTS.md dry rule)
    expected = ("PASS (PENDING-FREEZE: budgets are proposals, not frozen "
                "policy)" if all(j["proposed_budget_results"].values())
                else "FAIL against proposed budgets")
    assert j["verdict"] == expected


def test_dry_default_path_matches_explicit_dry(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="dry2")
    dry_ref = write_wav(tmp_path / "ref2-dry.wav", ref)
    model = write_wav(tmp_path / "model2.wav", ref + 3)
    a_json = tmp_path / "a.json"
    b_json = tmp_path / "b.json"
    ra, _ = run(dry_ref, model, out_json=a_json)
    rb, _ = run(dry_ref, model, out_json=b_json, path="dry")
    assert ra.returncode == rb.returncode == 0
    assert ra.stdout == rb.stdout
    assert a_json.read_bytes() == b_json.read_bytes()


# ------------------------------------------------------- fail-closed paths ---

def test_wet_named_reference_without_wet_path_is_refused(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="tripwire")
    model = write_wav(tmp_path / "model-tripwire.wav", ref)
    r, j = run(ref_path, model)          # no --path wet
    assert r.returncode == 2
    assert j["verdict"].startswith("NO_VERDICT")
    assert "--path wet" in j["reason"]


def test_wet_path_without_sidecar_is_refused(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="orphan")
    orphan_dir = tmp_path / "orphan-dir"
    orphan_dir.mkdir()
    orphan = write_wav(orphan_dir / "orphan-wet.wav", ref)
    model = write_wav(tmp_path / "model-orphan.wav", ref)
    r, j = run(orphan, model, path="wet")
    assert r.returncode == 2
    assert "sidecar" in j["reason"]


def test_stale_sidecar_is_refused(tmp_path):
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="stale")
    short_dir = tmp_path / "stale-short"
    short_dir.mkdir()
    short = write_wav(short_dir / "short-wet.wav", ref[: off + tail // 2])
    model = write_wav(tmp_path / "model-stale.wav", ref)
    r, j = run(short, model, path="wet", sidecar=sc)
    assert r.returncode == 2
    assert "STALE" in j["reason"]


def test_sidecar_sha256_mismatch_is_refused(tmp_path):
    """Committed sidecars declare a sha256; a reference that does not hash to
    it cannot supply the tail region."""
    ref, ref_path, sc, off, tail = synth_case(tmp_path, tag="sha")
    d = json.loads(open(sc).read())
    d["wet"]["sha256"] = "0" * 64
    p = tmp_path / "sha" / "sha.json"
    p.write_text(json.dumps(d) + "\n")
    model = write_wav(tmp_path / "model-sha.wav", ref)
    r, j = run(ref_path, model, path="wet", sidecar=p)
    assert r.returncode == 2
    assert "sha256" in j["reason"]


# ---------------------------------------- committed-fixture reconciliation ---

@pytest.mark.skipif(not os.path.exists(FIXTURE_WET),
                    reason="committed SXT-012 wet fixture not present")
def test_committed_fixture_tail_region_is_declared_and_consistent():
    """The committed wet fixture the controls use declares its own tail region:
    last_event_sample + tail_s*sr == frames (no inference anywhere)."""
    sc = json.loads(open(FIXTURE_SIDECAR).read())
    sr = sc["engine"]["sample_rate"]
    off = sc["wet"]["last_event_sample"]
    tail = int(round(sc["wet"]["tail_s"] * sr))
    assert off + tail == sc["wet"]["frames"]
    assert len(read_wav(FIXTURE_WET)) == sc["wet"]["frames"]


def test_every_committed_wet_fixture_declares_its_tail_region():
    """No committed SXT-012 wet fixture needs silence inference: each sidecar's
    last_event_sample + tail_s*sr equals its declared frame count."""
    import glob
    sidecars = sorted(glob.glob(os.path.join(REPO, "fixtures", "audio", "*",
                                             "*.json")))
    if not sidecars:
        pytest.skip("committed SXT-012 fixtures not present")
    checked = 0
    for p in sidecars:
        sc = json.loads(open(p).read())
        bus = sc.get("wet")
        if not isinstance(bus, dict) or "last_event_sample" not in bus:
            continue
        sr = sc["engine"]["sample_rate"]
        tail = int(round(bus["tail_s"] * sr))
        assert bus["last_event_sample"] + tail == bus["frames"], p
        checked += 1
    assert checked >= 1


@pytest.mark.skipif(not os.path.exists(FIXTURE_WET),
                    reason="committed SXT-012 wet fixture not present")
def test_committed_wet_fixture_dropped_tail_fails(tmp_path):
    """The drop-tail control on a committed wet fixture must FAIL the verdict
    (this is comparator behaviour, not a fidelity result)."""
    sc = json.loads(open(FIXTURE_SIDECAR).read())
    off = sc["wet"]["last_event_sample"]
    tail = int(round(sc["wet"]["tail_s"] * sc["engine"]["sample_rate"]))
    ref = read_wav(FIXTURE_WET)
    dropped = ref.copy()
    dropped[off:off + tail] = 0
    model = write_wav(tmp_path / "committed-drop-tail.wav", dropped)
    r, j = run(FIXTURE_WET, model, path="wet", sidecar=FIXTURE_SIDECAR)
    assert r.returncode == 1
    assert j["verdict"].startswith("FAIL")
    assert j["tail_check"]["ok"] is False
    assert j["tail_check"]["model_tail_present"] is False


@pytest.mark.skipif(not os.path.exists(FIXTURE_WET),
                    reason="committed SXT-012 wet fixture not present")
def test_committed_wet_fixture_sidecar_autodiscovery():
    """`<seq>-wet.wav` resolves to the committed `<seq>.json` sidecar without
    --sidecar, so a wet caller cannot skip the gate for convenience."""
    r, j = run(FIXTURE_WET, FIXTURE_WET, path="wet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert j["fixture_sidecar"].endswith("seq-notes-coverage-v1.json")
    assert j["tail_check"]["ok"] is True


# ------------------------------------------------------- committed evidence --

def test_committed_tail_gate_controls_record_the_required_outcomes():
    """The committed control artifacts must show the gate failing what it
    targets; a stale/absent record is a failure, never a pass."""
    art = os.path.join(REPO, "reports", "shared-comparator-tail-gate",
                       "artifacts")
    summary_p = os.path.join(art, "checks-summary.json")
    assert os.path.exists(summary_p), "committed checks summary missing"
    s = json.loads(open(summary_p).read())
    leg = s["legs"]["wet_tail_controls"]
    assert leg["status"] == "PASS"
    got = {c["control"]: c for c in leg["controls"]}
    assert got["full-tail-within-budget"]["got"] == "PASS"
    for name in ("drop-full-tail", "tail-decays-too-fast",
                 "truncate-at-tail-start", "drop-full-tail-second-preset"):
        assert got[name]["got"] == "FAIL", name
    for name in ("undeclared-wet-path", "no-sidecar", "stale-sidecar"):
        assert got[name]["got"] == "REFUSE", name
    assert all(c["as_required"] for c in leg["controls"])
    # the two decisive controls must be the gate-only ones
    assert {c["control"] for c in leg["controls"]
            if c.get("gate_only_required")} == {"tail-decays-too-fast",
                                                "truncate-at-tail-start"}
    dry = s["legs"]["dry_rerun_parity"]
    assert dry["status"] == "PASS"
    assert dry["unexplained_committed_diffs"] == []
    assert all(c["baseline_vs_current"] == "BYTE-IDENTICAL"
               for c in dry["cases"])
