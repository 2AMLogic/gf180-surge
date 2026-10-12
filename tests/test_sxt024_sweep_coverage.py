#!/usr/bin/env python3
"""SXT-024 decay-sweep coverage gate (issue #456).

Covers `tools/compare_reverb_model.py sweep`'s exit contract: sweep success
now REQUIRES declared case coverage and graded agreement.

  * the declared required case set is the committed generator policy
    (tools/render_reverb_reference.py cmd_sweep default grid and its trace
    naming rule) and matches the committed traces exactly;
  * a missing required case, an empty trace directory, or an unusable
    required sidecar REFUSES (NO_VERDICT, exit 2) BEFORE any evidence file
    is written;
  * a sweep where no mandatory check could be graded (every check None) is
    NO_VERDICT with a nonzero exit -- the old vacuous all(...) over non-None
    values can no longer masquerade as success;
  * a graded false check remains FAIL;
  * a complete sweep with the documented short-decay t60 exception and
    graded mandatory tail tracking retains its legitimate PASS, with
    coverage (required / discovered / graded / unmeasurable, plus reasons)
    reported separately from the graded checks.

Claim scope: comparator behaviour only. Nothing here is a model-vs-reference,
RTL-exactness, preset-support, or sound claim.

Original to this repository (Apache-2.0).
"""

import argparse
import copy
import hashlib
import json
import os
import sys
import wave

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_reverb_model as crm  # noqa: E402

COMMITTED = crm.TRACES
# Both cases grade the mandatory tail_level_tracking check on a short
# synthetic render; decay -2 additionally exercises the documented
# short-decay t60 exception (nominal t60 0.25 s < the structure's own
# echo/loop delays, so t60_w_vs_pred is NOT_RUN there by design).
GRID_SUBSET = ("sweepmdecaym0", "sweepmdecaymm2")
SUBSET_DECAY = {"sweepmdecaym0": 0.0, "sweepmdecaymm2": -2.0}
# Short render: tail from the declared 13200-sample click offset still holds
# >= 8 analysis windows for the t60 fit and > 4 windows above the tracking
# floor for these decays.
SYNTH_FRAMES = 48000


def _ns(traces_dir, out_dir):
    return argparse.Namespace(traces_dir=str(traces_dir), out_dir=str(out_dir))


def _write_wav(path, wet):
    d = np.clip(np.round(np.asarray(wet) * 32768.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(d.T.tobytes())


def _synth_sidecar(name, decay_v, wav_path, frames):
    """Synthetic sweep sidecar: committed m0 state with the decay override
    applied; every declared wav/render field describes the ACTUAL synthetic
    artifact (frames, bytes, sha256), and the construction is labelled."""
    src = json.load(open(os.path.join(COMMITTED, "sweepmdecaym0.json")))
    side = copy.deepcopy(src)
    side["trace"] = name
    side["sweep"] = {"param": "fx4_p3 decaytime", "requested": decay_v}
    side["render"]["overrides_applied"] = {"3": decay_v}
    side["render"]["frames"] = frames
    side["render"]["blocks"] = frames
    with open(wav_path, "rb") as f:
        side["wav"] = {"bytes": os.fstat(f.fileno()).st_size, "channels": 2,
                       "frames": frames, "sample_rate": 48000,
                       "sha256": hashlib.sha256(f.read()).hexdigest()}
    side["engine_patch_state"]["params"]["decaytime"] = decay_v
    side["synthetic_test_fixture"] = ("pytest construction for the issue #456 "
                                      "comparator coverage tests; not an "
                                      "oracle render")
    with open(os.path.join(os.path.dirname(wav_path), name + ".json"), "w") as f:
        json.dump(side, f, indent=2, sort_keys=True)
        f.write("\n")


@pytest.fixture()
def subset_gate(monkeypatch):
    """Scope the declared required set to the synthetic two-case subset for
    end-to-end runs over the synthetic trace dirs (the full seven-case set is
    separately pinned against the committed traces above)."""
    monkeypatch.setattr(crm, "REQUIRED_SWEEP_CASES", GRID_SUBSET)


@pytest.fixture(scope="module")
def synth_sweeps(tmp_path_factory):
    """Three synthetic two-case sweep trace dirs (PASS / FAIL / ungraded)
    plus an output dir each, built from ONE model run per decay value.

    pass: wet := the frozen model's own prediction (written as int16 WAV) --
          the comparator must re-derive agreement and PASS.
    fail: wet := dry + 2 * reverb -- the reverb-only component is +6 dB
          against the prediction; tail_level_tracking must grade False.
    flat: wet := dry -- reverb-only component exactly zero; every check is
          unmeasurable (None), the exact all(...)-over-empty masquerade.
    """
    root = tmp_path_factory.mktemp("sweep-synth")
    dry = np.load(os.path.join(COMMITTED, "click-dry.npy")).astype(
        np.float64)[:, :SYNTH_FRAMES]
    preds = {}
    for name, decay_v in SUBSET_DECAY.items():
        src = json.load(open(os.path.join(COMMITTED, name + ".json")))
        side = copy.deepcopy(src)
        side["engine_patch_state"]["params"]["decaytime"] = decay_v
        model, _c, st = crm.build_model(side)
        send, ret = crm.send_return_gains(st)
        (pred_l, pred_r), (_ol, _orr) = crm.run_model_on_dry(
            model, dry[0], dry[1], send, ret)
        preds[name] = (pred_l, pred_r)

    def build(tag, wet_of):
        traces = root / tag
        traces.mkdir()
        np.save(traces / "click-dry.npy",
                dry.astype(np.float32))
        for name in GRID_SUBSET:
            wet = wet_of(name)
            wav = traces / (name + ".wav")
            _write_wav(wav, wet)
            _synth_sidecar(name, SUBSET_DECAY[name], str(wav), SYNTH_FRAMES)
        out = root / (tag + "-out")
        out.mkdir()
        return str(traces), str(out)

    def wet_pass(name):
        return preds[name]

    def wet_fail(name):
        pl, pr = preds[name]
        return (2.0 * pl - dry[0], 2.0 * pr - dry[1])

    def wet_flat(name):
        return (dry[0].copy(), dry[1].copy())

    built = {tag: build(tag, wet_of)
             for tag, wet_of in (("pass", wet_pass), ("fail", wet_fail),
                                 ("flat", wet_flat))}
    return {"root": str(root), "dry": dry, "preds": preds, **built}


# --------------------------------------------------------------------------
# the declared required set vs the committed generator policy and evidence
# --------------------------------------------------------------------------

def test_required_set_is_the_committed_generator_grid():
    assert crm.SWEEP_GRID_DEFAULT == ("-4", "-2", "0", "1.879465", "3",
                                      "4.5", "6")
    # the generator's exact naming rule: f"sweep-decay-{v}".replace(".", "_")
    # .replace("-", "m")
    assert crm.sweep_case_name("-4") == "sweepmdecaymm4"
    assert crm.sweep_case_name("1.879465") == "sweepmdecaym1_879465"
    assert crm.REQUIRED_SWEEP_CASES == (
        "sweepmdecaymm4", "sweepmdecaymm2", "sweepmdecaym0",
        "sweepmdecaym1_879465", "sweepmdecaym3", "sweepmdecaym4_5",
        "sweepmdecaym6")


def test_committed_traces_satisfy_the_declared_set_exactly():
    discovered = crm.discover_sweep_cases(COMMITTED)
    assert sorted(discovered) == sorted(crm.REQUIRED_SWEEP_CASES)
    for name in crm.REQUIRED_SWEEP_CASES:
        assert os.path.exists(os.path.join(COMMITTED, name + ".json")), name
        assert os.path.exists(os.path.join(COMMITTED, name + ".wav")), name


# --------------------------------------------------------------------------
# aggregation: verdict + coverage from per-case results
# --------------------------------------------------------------------------

def _res(name, checks):
    return {"trace": name, "checks": checks}


def test_aggregate_full_pass():
    cov = crm.aggregate_sweep_coverage(
        [_res("a", {"x": True, "y": None}), _res("b", {"x": True})],
        ("a", "b"), ["a", "b"])
    assert cov["verdict"] == "PASS" and cov["coverage"] == "full"
    assert cov["cases_graded"] == 2 and cov["cases_not_run"] == 0
    assert cov["checks_graded_true"] == 2 and cov["checks_not_run"] == 1


def test_aggregate_graded_false_remains_fail():
    cov = crm.aggregate_sweep_coverage(
        [_res("a", {"x": True}), _res("b", {"x": False})],
        ("a", "b"), ["a", "b"])
    assert cov["verdict"] == "FAIL" and cov["checks_graded_false"] == 1


def test_aggregate_all_ungraded_is_no_verdict_and_never_pass():
    cov = crm.aggregate_sweep_coverage(
        [_res("a", {"x": None}), _res("b", {"x": None, "y": None})],
        ("a", "b"), ["a", "b"])
    assert cov["verdict"] == "NO_VERDICT"
    assert cov["coverage"] == "none"
    assert cov["verdict"] != "PASS"


def test_aggregate_one_unmeasurable_case_is_explicit_partial():
    cov = crm.aggregate_sweep_coverage(
        [_res("a", {"x": True}), _res("b", {"x": None})],
        ("a", "b"), ["a", "b"])
    # the unmeasurable case is visible, not folded into the pass
    assert cov["verdict"] == "PASS" and cov["coverage"] == "partial"
    assert cov["cases_graded"] == 1 and cov["cases_not_run"] == 1


def test_aggregate_missing_required_is_refusal():
    cov = crm.aggregate_sweep_coverage([], ("a", "b"), ["a"])
    assert cov["verdict"] == "NO_VERDICT (refused)"
    assert cov["missing_required"] == ["b"]


def test_sweep_case_status():
    assert crm.sweep_case_status({"x": True, "y": None}) == "PASS"
    assert crm.sweep_case_status({"x": True, "y": False}) == "FAIL"
    assert crm.sweep_case_status({"x": None, "y": None}) == "NOT_RUN"


# --------------------------------------------------------------------------
# refusal paths: BEFORE any evidence write, with explicit coverage
# --------------------------------------------------------------------------

def test_sweep_refuses_an_empty_trace_dir(tmp_path, capsys):
    traces, out = tmp_path / "traces", tmp_path / "out"
    traces.mkdir()
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert payload["coverage"]["cases_discovered"] == 0
    assert sorted(payload["coverage"]["missing_required"]) == \
        sorted(crm.REQUIRED_SWEEP_CASES)
    # no evidence invented
    assert not out.exists() or not list(out.iterdir())


@pytest.mark.usefixtures("subset_gate")
def test_sweep_refuses_one_missing_required_case_and_overwrites_nothing(
        synth_sweeps, capsys):
    traces, out = synth_sweeps["pass"]
    victim = os.path.join(traces, "sweepmdecaymm2.json")
    saved = open(victim).read()
    try:
        os.remove(victim)
        # pre-existing committed evidence must survive a refusal untouched
        sentinel = os.path.join(out, "sweep-t60.json")
        with open(sentinel, "w") as f:
            f.write("[]\n")
        before = open(sentinel).read()
        rc = crm.cmd_sweep(_ns(traces, out))
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == "NO_VERDICT (refused)"
        assert payload["coverage"]["missing_required"] == ["sweepmdecaymm2"]
        assert open(sentinel).read() == before
        assert not os.path.exists(
            os.path.join(out, "sweep-t60-coverage.json"))
    finally:
        # the trace dirs are shared by the module-scoped fixture
        with open(victim, "w") as f:
            f.write(saved)


@pytest.mark.usefixtures("subset_gate")
def test_sweep_refuses_an_unusable_required_sidecar(tmp_path, capsys):
    traces, out = tmp_path / "traces", tmp_path / "out"
    traces.mkdir()
    for name in GRID_SUBSET:
        (traces / (name + ".json")).write_text('{"render": {}}\n')
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert "unusable" in payload["reason"]
    assert not out.exists() or not list(out.iterdir())


# --------------------------------------------------------------------------
# grading paths (live, end-to-end, synthetic short renders)
# --------------------------------------------------------------------------

@pytest.mark.usefixtures("subset_gate")
def test_complete_sweep_with_short_decay_exception_and_graded_tracking_passes(
        synth_sweeps):
    traces, out = synth_sweeps["pass"]
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 0
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    assert cov["schema"] == crm.SWEEP_COVERAGE_SCHEMA
    assert cov["verdict"] == "PASS" and cov["coverage"] == "full"
    assert cov["cases_graded"] == 2 and cov["cases_not_run"] == 0
    results = json.load(open(os.path.join(out, "sweep-t60.json")))
    by = {r["trace"]: r for r in results}
    assert by["sweepmdecaym0"]["status"] == "PASS"
    assert by["sweepmdecaymm2"]["status"] == "PASS"
    # the documented short-decay t60 exception stays a per-fit NOT_RUN with
    # its reason, and the mandatory tracking check is graded
    assert by["sweepmdecaymm2"]["checks"]["t60_w_vs_pred"] is None
    assert by["sweepmdecaymm2"]["t60_note"]
    assert by["sweepmdecaymm2"]["checks"]["tail_level_tracking"] is True


@pytest.mark.usefixtures("subset_gate")
def test_sweep_with_extra_discovered_case_still_passes_and_reports_it(
        synth_sweeps):
    traces, out = synth_sweeps["pass"]
    # a third, non-required case: same decay-0 prediction under a new name
    for suffix in (".json", ".wav"):
        src = os.path.join(traces, "sweepmdecaym0" + suffix)
        dst = os.path.join(traces, "sweepmdecaym9" + suffix)
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
    side = json.load(open(os.path.join(traces, "sweepmdecaym9.json")))
    side["trace"] = "sweepmdecaym9"
    with open(os.path.join(traces, "sweepmdecaym9.json"), "w") as f:
        json.dump(side, f, indent=2, sort_keys=True)
        f.write("\n")
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 0
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    assert cov["verdict"] == "PASS"
    assert cov["extra_discovered"] == ["sweepmdecaym9"]
    assert cov["cases_graded"] == 3


@pytest.mark.usefixtures("subset_gate")
def test_graded_false_check_fails_the_sweep(synth_sweeps):
    traces, out = synth_sweeps["fail"]
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 1
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    assert cov["verdict"] == "FAIL"
    assert cov["checks_graded_false"] >= 1
    results = json.load(open(os.path.join(out, "sweep-t60.json")))
    assert any(r["status"] == "FAIL" for r in results)


@pytest.mark.usefixtures("subset_gate")
def test_fully_ungraded_sweep_is_no_verdict_with_nonzero_exit(synth_sweeps):
    traces, out = synth_sweeps["flat"]
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 1
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    assert cov["verdict"] == "NO_VERDICT" and cov["coverage"] == "none"
    assert cov["cases_not_run"] == 2
    results = json.load(open(os.path.join(out, "sweep-t60.json")))
    assert all(all(v is None for v in r["checks"].values()) for r in results)
    # the negative control the gate exists for: the OLD aggregate -- all(...)
    # over only non-None check values -- evaluates True on exactly this
    # result set, i.e. the old tool returned 0 (success) here.
    old_all = all(v for r in results for v in r["checks"].values()
                  if v is not None)
    assert old_all is True
    assert cov["verdict"] != "PASS"


# --------------------------------------------------------------------------
# review follow-ups: dry input from the SELECTED directory; extra identities
# never enable success; malformed WAVs refuse instead of a traceback
# --------------------------------------------------------------------------

def _copy_dir(src, dst):
    os.makedirs(dst)
    for fn in os.listdir(src):
        with open(os.path.join(src, fn), "rb") as a, \
                open(os.path.join(dst, fn), "wb") as b:
            b.write(a.read())
    return str(dst)


def _add_extra(traces, src_traces, src_name, extra_name):
    for suffix in (".json", ".wav"):
        with open(os.path.join(src_traces, src_name + suffix), "rb") as a, \
                open(os.path.join(traces, extra_name + suffix), "wb") as b:
            b.write(a.read())
    p = os.path.join(traces, extra_name + ".json")
    side = json.load(open(p))
    side["trace"] = extra_name
    with open(p, "w") as f:
        json.dump(side, f, indent=2, sort_keys=True)
        f.write("\n")


def test_aggregate_graded_extra_cannot_rescue_ungraded_required_set():
    cov = crm.aggregate_sweep_coverage(
        [_res("a", {"x": None}), _res("b", {"x": None}),
         _res("extra", {"x": True})],
        ("a", "b"), ["a", "b", "extra"])
    assert cov["verdict"] == "NO_VERDICT" and cov["coverage"] == "none"
    assert cov["required_checks_graded"] == 0
    assert cov["extra_discovered"] == ["extra"]
    assert {c["trace"]: c["required"] for c in cov["cases"]} == {
        "a": True, "b": True, "extra": False}


def test_aggregate_false_extra_is_still_a_fail():
    cov = crm.aggregate_sweep_coverage(
        [_res("a", {"x": True}), _res("extra", {"x": False})],
        ("a",), ["a", "extra"])
    assert cov["verdict"] == "FAIL"


def test_aggregate_short_decay_exception_still_passes_partial():
    # the legitimate -4 shape: one required case grades nothing, others do
    cov = crm.aggregate_sweep_coverage(
        [_res("m4", {"t60": None, "track": None}),
         _res("m0", {"t60": True, "track": True})],
        ("m4", "m0"), ["m4", "m0"])
    assert cov["verdict"] == "PASS" and cov["coverage"] == "partial"
    assert cov["cases_not_run"] == 1


@pytest.mark.usefixtures("subset_gate")
def test_graded_extra_cannot_turn_ungraded_required_set_into_pass(
        synth_sweeps, tmp_path):
    traces = _copy_dir(synth_sweeps["flat"][0], tmp_path / "traces")
    out = tmp_path / "out"
    _add_extra(traces, synth_sweeps["pass"][0], "sweepmdecaym0",
               "sweepmdecaym9")
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 1
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    assert cov["verdict"] == "NO_VERDICT" and cov["coverage"] == "none"
    assert cov["extra_discovered"] == ["sweepmdecaym9"]
    # the extra really was graded -- it just cannot enable success
    assert cov["checks_graded_true"] >= 1
    assert cov["required_checks_graded"] == 0


@pytest.mark.usefixtures("subset_gate")
def test_sweep_refuses_a_missing_dry_input(synth_sweeps, tmp_path, capsys):
    traces = _copy_dir(synth_sweeps["pass"][0], tmp_path / "traces")
    os.remove(os.path.join(traces, "click-dry.npy"))
    out = tmp_path / "out"
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert "dry input" in payload["reason"]
    assert not out.exists() or not list(out.iterdir())


@pytest.mark.usefixtures("subset_gate")
@pytest.mark.parametrize("bad", ["nan", "mono", "empty"])
def test_sweep_refuses_an_unusable_dry_input(synth_sweeps, tmp_path, capsys,
                                             bad):
    traces = _copy_dir(synth_sweeps["pass"][0], tmp_path / "traces")
    dry = np.load(os.path.join(traces, "click-dry.npy"))
    if bad == "nan":
        dry = dry.copy()
        dry[0, 100] = np.nan
    elif bad == "mono":
        dry = dry[:1]
    else:
        dry = dry[:, :0]
    np.save(os.path.join(traces, "click-dry.npy"), dry)
    out = tmp_path / "out"
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert "dry input" in payload["reason"]
    assert not out.exists() or not list(out.iterdir())


@pytest.mark.usefixtures("subset_gate")
def test_sweep_uses_the_supplied_dry_bus_not_the_committed_one(
        synth_sweeps, tmp_path):
    base_traces, base_out = synth_sweeps["pass"]
    assert crm.cmd_sweep(_ns(base_traces, base_out)) == 0
    base = {r["trace"]: r for r in json.load(
        open(os.path.join(base_out, "sweep-t60.json")))}
    traces = _copy_dir(base_traces, tmp_path / "traces")
    dry = np.load(os.path.join(traces, "click-dry.npy"))
    # a DIFFERENT dry signal (-6 dB) in the supplied directory; the committed
    # click-dry.npy is untouched, so borrowing it would reproduce `base`
    np.save(os.path.join(traces, "click-dry.npy"),
            (0.5 * dry).astype(np.float32))
    out = tmp_path / "out"
    crm.cmd_sweep(_ns(traces, out))
    got = {r["trace"]: r for r in json.load(
        open(os.path.join(out, "sweep-t60.json")))}
    for name in GRID_SUBSET:
        assert got[name]["tail_level_tracking_mean_dev_db"] != \
            base[name]["tail_level_tracking_mean_dev_db"], name


@pytest.mark.usefixtures("subset_gate")
@pytest.mark.parametrize("bad", ["garbage", "truncated"])
def test_sweep_refuses_a_malformed_wav_without_traceback(
        synth_sweeps, tmp_path, capsys, bad):
    traces = _copy_dir(synth_sweeps["pass"][0], tmp_path / "traces")
    wav = os.path.join(traces, "sweepmdecaym0.wav")
    data = open(wav, "rb").read()
    with open(wav, "wb") as f:
        f.write(b"not a wav file at all" if bad == "garbage" else data[:30])
    out = tmp_path / "out"
    rc = crm.cmd_sweep(_ns(traces, out))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert "unusable" in payload["reason"]
    assert not out.exists() or not list(out.iterdir())
