"""#145: every budget JSON republished after the #123 halfband branch-order
fix must be re-derivable from the committed model render and the committed
reference render with the shared comparator, byte-for-byte in its metrics.

This is the check whose absence let the #123 fallout sit invisibly: the
committed JSONs measured renders that no longer reproduced at HEAD, and
nothing re-derived them. It asserts bookkeeping only -- that each committed
budget JSON describes the committed bytes next to it. It establishes no
fidelity verdict (every budget here is [PROPOSED], owned by #12), no
preset-support claim, and nothing about how the renders sound.

It does NOT re-render the models (minutes per render); the byte-identity of
the committed renders with a fresh HEAD render, and the legacy-ordering
attribution, are recorded in reports/halfband-republication/.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMP = os.path.join(REPO, "tools", "compare_audio_reference.py")


def _cases():
    out = []
    a = "reports/sxt-022/artifacts"
    for s in ("seq-notes-coverage-v1", "seq-notes-repeated-v1",
              "seq-modwheel-v1"):
        out.append((f"{a}/reference-{s}-dry.wav", f"{a}/model-{s}.wav",
                    f"{a}/audio-{s}.json"))
    a = "reports/sxt-032/artifacts"
    for s, j in (("seq-notes-coverage-v1", "coverage"),
                 ("seq-notes-repeated-v1", "repeated"),
                 ("seq-notes-holds-v1", "holds"),
                 ("seq-modwheel-v1", "modwheel")):
        out.append((f"{a}/reference-{s}-lfo-fixture.wav", f"{a}/model-{s}.wav",
                    f"{a}/audio-{j}.json"))
    a = "reports/SXT-033/artifacts"
    for c in ("edges", "horn", "tentacles", "crush"):
        for s in ("seq-notes-coverage-v1", "seq-notes-repeated-v1"):
            out.append((f"{a}/{c}__{s}-ref.wav", f"{a}/model-{c}-{s}.wav",
                        f"{a}/budget-{c}-{s}.json"))
    a = "reports/SXT-034/artifacts"
    for s, u, j in (("seq-notes-repeated-v1", "uni1", "uni1-rep"),
                    ("seq-notes-coverage-v1", "uni2", "uni2-cov"),
                    ("seq-notes-repeated-v1", "uni4", "uni4-rep")):
        out.append((f"{a}/reference-{s}-{u}.wav", f"{a}/model-{s}-{u}.wav",
                    f"{a}/{j}.json"))
    a = "reports/sxt-035/artifacts"
    for s in ("seq-notes-coverage-v1", "seq-notes-repeated-v1",
              "seq-modwheel-v1"):
        out.append((f"{a}/reference-{s}-mw-fixture.wav", f"{a}/model-{s}.wav",
                    f"{a}/audio-{s}.json"))
    a = "reports/SXT-040/artifacts"
    for c in ("badnews", "tentacles", "popcorn2k"):
        for s in ("seq-notes-coverage-v1", "seq-notes-repeated-v1"):
            out.append((f"{a}/{c}__{s}-ref.wav", f"{a}/model-{c}-{s}.wav",
                        f"{a}/budget-{c}-{s}.json"))
    # SXT-042 / SXT-026a canonical bells: the baseline row of the keytrack
    # negative-control set is the leaf's budget JSON (it also carries a
    # windowed_rms_lsb field, which the comparator does not emit).
    a = "reports/SXT-042/artifacts"
    out.append((f"{a}/reference-sxt025-accept-v1-bells-dry.wav",
                f"{a}/model-sxt025-accept-v1-bells-dry.wav",
                f"{a}/audio-nc-baseline.json"))
    return out


CASES = _cases()
NUMERIC = ("frames", "ref_peak_lsb", "model_peak_lsb", "max_abs_diff_lsb",
           "rms_diff_lsb", "rms_diff_dbfs", "best_shift", "spectral_corr")


def test_case_list_is_complete():
    assert len(CASES) == 28
    for ref, model, js in CASES:
        for p in (ref, model, js):
            assert os.path.exists(os.path.join(REPO, p)), p


@pytest.mark.parametrize("ref,model,js", CASES,
                         ids=[c[2].split("reports/")[1] for c in CASES])
def test_budget_json_is_rederivable_from_committed_renders(ref, model, js):
    r = subprocess.run([sys.executable, CMP, "--ref", ref, "--model", model],
                       cwd=REPO, capture_output=True, text=True)
    fresh = json.loads(r.stdout)
    with open(os.path.join(REPO, js), encoding="utf-8") as f:
        committed = json.load(f)
    for k in NUMERIC:
        assert fresh[k] == pytest.approx(committed[k], rel=1e-12, abs=1e-12), (
            f"{js}: {k} committed {committed[k]} but the committed render "
            f"re-measures {fresh[k]} -- the JSON is STALE against its render")
    assert fresh["proposed_budget_results"] == \
        committed["proposed_budget_results"], js
    assert fresh["verdict"] == committed["verdict"], js
