"""#438: ablation_delta must validate both WAVs before any identity shortcut.

Also pins, since #654, that `--ablations` and `--out` govern both ends of a
run: a scratch `--out` writes its own summary and leaves the committed
reports/sxt-014/ablation-summary.json byte-unchanged.

Temporary 48 kHz mono int16 WAVs only; committed reports are never touched.
Diagnostic tooling only: no fidelity, support, or listening claim.
"""
import hashlib
import json
import math
import os
import struct
import sys
import wave

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import ablation_delta as ad
from refusal import Refuse


def write_wav(path, n=9600, rate=48000, amp=3000, phase=0.0, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        fr = b"".join(
            struct.pack("<h", int(amp * math.sin(phase + 0.05 * i))) * channels
            for i in range(n))
        w.writeframes(fr)
    return str(path)


def sidecar(path):
    raw = open(path, "rb").read()
    return {"wav": {"path": str(path), "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest()}}


def old_shortcut(anchor_sc, variant_sc):
    """The pre-#438 behavior: trust equal declared digests, open nothing."""
    if anchor_sc["wav"]["sha256"] == variant_sc["wav"]["sha256"]:
        return "BIT-IDENTICAL"
    return None


def run(a, b, asc, bsc):
    return ad.compare(a, b, asc, bsc, False)


@pytest.fixture
def committed_summary(tmp_path, monkeypatch):
    """Stand-in for the committed reports/sxt-014/ablation-summary.json.

    Every main()-driving test installs it. A run pointed at a scratch --out
    must never write here (#654); installing it also means that if that ever
    regresses, the write lands in tmp_path instead of the repository.
    """
    sentinel = tmp_path / "committed-ablation-summary.json"
    monkeypatch.setattr(ad, "SUMMARY", str(sentinel))
    return sentinel


def test_valid_identical_is_bit_identical(tmp_path):
    a = write_wav(tmp_path / "a.wav")
    b = write_wav(tmp_path / "b.wav")
    m = run(a, b, sidecar(a), sidecar(b))
    assert m["bit_identical"] is True and m["verdict"] == "BIT-IDENTICAL"


def test_valid_differing_gives_numeric_diagnostic(tmp_path):
    a = write_wav(tmp_path / "a.wav")
    b = write_wav(tmp_path / "b.wav", amp=2000)
    m = run(a, b, sidecar(a), sidecar(b))
    assert m["bit_identical"] is False
    assert m["verdict"] == "MEASURABLE-DIFFERENCE"
    assert m["max_abs_sample_diff"] > 0 and "band_delta_db" in m


def test_changed_bytes_with_unchanged_declared_digest_refuses(tmp_path):
    a = write_wav(tmp_path / "a.wav")
    b = write_wav(tmp_path / "b.wav")
    asc, bsc = sidecar(a), sidecar(b)
    write_wav(tmp_path / "b.wav", amp=1000)  # bytes change, sidecar unchanged
    with pytest.raises(Refuse, match="bytes changed"):
        run(a, b, asc, bsc)


def test_missing_wav_behind_equal_declared_digests_refuses(tmp_path):
    a = write_wav(tmp_path / "a.wav")
    b = write_wav(tmp_path / "b.wav")
    asc, bsc = sidecar(a), sidecar(b)
    os.remove(b)
    with pytest.raises(Refuse, match="missing"):
        run(a, b, asc, bsc)


def test_44k1_refuses(tmp_path):
    a = write_wav(tmp_path / "a.wav", rate=44100)
    b = write_wav(tmp_path / "b.wav", rate=44100)
    with pytest.raises(Refuse, match="44100"):
        run(a, b, sidecar(a), sidecar(b))


def test_empty_audio_refuses(tmp_path):
    a = write_wav(tmp_path / "a.wav", n=0)
    b = write_wav(tmp_path / "b.wav", n=0)
    with pytest.raises(Refuse, match="empty"):
        run(a, b, sidecar(a), sidecar(b))


def test_stereo_refuses(tmp_path):
    a = write_wav(tmp_path / "a.wav", channels=2)
    b = write_wav(tmp_path / "b.wav", channels=2)
    with pytest.raises(Refuse, match="mono"):
        run(a, b, sidecar(a), sidecar(b))


@pytest.mark.parametrize("mutate", ["alter", "delete"])
def test_failure_control_old_shortcut_wrongly_passes(tmp_path, mutate):
    """Equal declared sha256 held constant; alter or delete one WAV.

    The old shortcut still reports BIT-IDENTICAL (the defect); the new path
    refuses. This control demonstrably fails the old behavior.
    """
    a = write_wav(tmp_path / "a.wav")
    b = write_wav(tmp_path / "b.wav")
    asc, bsc = sidecar(a), sidecar(b)
    assert asc["wav"]["sha256"] == bsc["wav"]["sha256"]
    if mutate == "alter":
        write_wav(tmp_path / "b.wav", amp=500)
    else:
        os.remove(b)
    assert old_shortcut(asc, bsc) == "BIT-IDENTICAL"
    with pytest.raises(Refuse):
        run(a, b, asc, bsc)


def test_refusal_leaves_no_pair_record_or_summary(tmp_path, monkeypatch, capsys,
                                                 committed_summary):
    abl = tmp_path / "abl"
    out = tmp_path / "deltas"
    abl.mkdir()
    a = write_wav(abl / "orig.wav")
    b = write_wav(abl / "var.wav")
    for name, wav, kind, aid in (("orig", a, "original", "0"), ("var", b, "ablation", "1")):
        sc = sidecar(wav)
        sc["wav"]["path"] = os.path.relpath(wav, ad.REPO)
        sc.update({"preset": {"slug": "p", "path": "p.fxp"}, "sequence": {"id": "s"},
                   "kind": kind, "label": "x", "ablation_id": aid})
        (abl / f"{name}.json").write_text(json.dumps(sc))
    write_wav(abl / "var.wav", amp=1)  # stale: declared digest no longer matches
    # Since #654 the two flags are enough to keep the run inside tmp_path:
    # no ABLATIONS/SUMMARY monkeypatching is needed to stay out of the repo.
    monkeypatch.setattr(sys, "argv", ["ablation_delta", "--ablations", str(abl),
                                      "--out", str(out)])
    with pytest.raises(Refuse):
        ad.main()
    assert not (out / "ablation-summary.json").exists()
    assert not committed_summary.exists()
    assert not list(out.rglob("*.json"))


# --- #628: the SXT-012 repeatability reference is read fail-closed ----------
#
# `repeatability_bounds()` used to swallow every exception and return `{}`, so
# an unread reference still produced `"wet_repeat_relative_max_diff": null` --
# byte-for-byte what a legitimately bit-identical fixture produces. These
# tests pin the refusals that separate the two.

BIT_IDENTICAL_FIXTURE = {"fixture_id": "p__s", "preset": "p", "sequence": "s",
                         "dry": {"bit_identical": True},
                         "wet": {"bit_identical": True}}
FREE_PHASE_FIXTURE = {"fixture_id": "p__s", "preset": "p", "sequence": "s",
                      "dry": {"bit_identical": False, "relative_max_diff": [1.1, 1.2]},
                      "wet": {"bit_identical": False, "relative_max_diff": [1.72701, 1.583799]}}


def write_repeatability(path, fixtures):
    path.write_text(json.dumps({"schema_version": 1, "issue": "SXT-012",
                                "fixtures": fixtures}))
    return str(path)


def old_blanket_except_bounds():
    """The pre-#628 loader: any failure becomes an empty index."""
    try:
        with open(ad.REPEATABILITY, encoding="utf-8") as f:
            rep = json.load(f)
        return {fx["fixture_id"]: fx for fx in rep["fixtures"]}
    except Exception:
        return {}


def note_from_bounds(bounds, fixture_id, repeatability_class):
    """The pre-#628 note construction, including its `(fx or {})` tolerance."""
    fx = bounds.get(fixture_id)
    return {"class": repeatability_class,
            "expect_bit_identity": repeatability_class == "bit-identical",
            "reference": "reports/sxt-012/repeatability.json",
            "wet_repeat_relative_max_diff": (fx or {}).get("wet", {}).get("relative_max_diff")}


def offslot_group(tmp_path, repeatability_class="bit-identical", identical=True):
    """One original anchor plus one offslot-ctrl variant, on disk."""
    abl = tmp_path / "abl"
    abl.mkdir()
    a = write_wav(abl / "orig.wav")
    b = write_wav(abl / "ctrl.wav", amp=3000 if identical else 2000)
    for name, wav, kind, aid, label in (
            ("orig", a, "original", "0", "original render"),
            ("ctrl", b, "offslot-ctrl", "1", "negative control: already-Off slot bypassed")):
        sc = sidecar(wav)
        sc["wav"]["path"] = os.path.relpath(wav, ad.REPO)
        sc.update({"preset": {"slug": "p", "path": "p.fxp"}, "sequence": {"id": "s"},
                   "kind": kind, "label": label, "ablation_id": aid, "adapted": False,
                   "slot": 0, "mutated_slots": []})
        if kind == "offslot-ctrl":
            sc["repeatability_class"] = repeatability_class
        (abl / f"{name}.json").write_text(json.dumps(sc))
    return abl


def drive_main(monkeypatch, abl, out):
    """Run main() with scratch --ablations/--out and nothing else redirected.

    Since #654 those two flags govern what is read and where both the pair
    records and the summary are written, so the run needs no monkeypatching
    of ABLATIONS/SUMMARY to stay out of the repository.
    """
    monkeypatch.setattr(sys, "argv", ["ablation_delta", "--ablations", str(abl),
                                      "--out", str(out)])
    return ad.main()


def test_missing_repeatability_reference_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "REPEATABILITY", str(tmp_path / "absent.json"))
    with pytest.raises(Refuse, match="missing/unreadable"):
        ad.repeatability_bounds()


def test_unparseable_repeatability_reference_refuses(tmp_path, monkeypatch):
    bad = tmp_path / "repeatability.json"
    bad.write_text('{"fixtures": [')
    monkeypatch.setattr(ad, "REPEATABILITY", str(bad))
    with pytest.raises(Refuse, match="unparseable"):
        ad.repeatability_bounds()


@pytest.mark.parametrize("payload", ['{}', '{"fixtures": []}', '[]',
                                     '{"fixtures": [{"preset": "p"}]}'])
def test_mis_shaped_repeatability_reference_refuses(tmp_path, monkeypatch, payload):
    """A renamed `fixtures` / `fixture_id` key refuses instead of indexing to {}."""
    bad = tmp_path / "repeatability.json"
    bad.write_text(payload)
    monkeypatch.setattr(ad, "REPEATABILITY", str(bad))
    with pytest.raises(Refuse, match="fixture"):
        ad.repeatability_bounds()


def test_valid_reference_indexes_by_fixture_id(tmp_path, monkeypatch):
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [BIT_IDENTICAL_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    bounds = ad.repeatability_bounds()
    assert set(bounds) == {"p__s"}
    ad.require_repeatability_fixtures(bounds, ["p__s"])  # does not raise


def test_absent_fixture_key_refuses(tmp_path, monkeypatch):
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [BIT_IDENTICAL_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    with pytest.raises(Refuse, match="has no fixture 'other__s'"):
        ad.require_repeatability_fixtures(ad.repeatability_bounds(), ["other__s"])


def test_fixture_without_wet_object_refuses(tmp_path, monkeypatch):
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [{"fixture_id": "p__s", "dry": {"bit_identical": True}}])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    with pytest.raises(Refuse, match="no 'wet' object"):
        ad.require_repeatability_fixtures(ad.repeatability_bounds(), ["p__s"])


def test_missing_reference_leaves_no_offslot_record_or_summary(tmp_path, monkeypatch,
                                                               committed_summary):
    abl = offslot_group(tmp_path)
    out = tmp_path / "deltas"
    monkeypatch.setattr(ad, "REPEATABILITY", str(tmp_path / "absent.json"))
    with pytest.raises(Refuse, match="missing/unreadable"):
        drive_main(monkeypatch, abl, out)
    assert not committed_summary.exists()
    assert not out.exists()


def test_absent_fixture_key_leaves_no_offslot_record_or_summary(tmp_path, monkeypatch,
                                                                committed_summary):
    abl = offslot_group(tmp_path)
    out = tmp_path / "deltas"
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [dict(BIT_IDENTICAL_FIXTURE, fixture_id="other__s")])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    with pytest.raises(Refuse, match="has no fixture 'p__s'"):
        drive_main(monkeypatch, abl, out)
    assert not committed_summary.exists()
    assert not out.exists()


def test_note_carries_wet_relative_max_diff_when_the_reference_records_one(tmp_path,
                                                                          monkeypatch, capsys,
                                                                          committed_summary):
    abl = offslot_group(tmp_path, repeatability_class="free-phase", identical=False)
    out = tmp_path / "deltas"
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [FREE_PHASE_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    assert drive_main(monkeypatch, abl, out) == 0
    assert not committed_summary.exists()
    note = json.loads((out / "p" / "ctrl.json").read_text())["repeatability_note"]
    assert note["wet_repeat_relative_max_diff"] == [1.72701, 1.583799]
    assert note["expect_bit_identity"] is False


def test_note_null_now_means_only_a_bit_identical_repeat(tmp_path, monkeypatch, capsys,
                                                         committed_summary):
    """`null` survives -- but only when the fixture was read and records no diff."""
    abl = offslot_group(tmp_path)
    out = tmp_path / "deltas"
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [BIT_IDENTICAL_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    assert drive_main(monkeypatch, abl, out) == 0
    assert not committed_summary.exists()
    note = json.loads((out / "p" / "ctrl.json").read_text())["repeatability_note"]
    assert note["wet_repeat_relative_max_diff"] is None
    assert note["expect_bit_identity"] is True


def test_failure_control_blanket_except_cites_a_reference_it_never_read(tmp_path, monkeypatch):
    """The old loader emits a note indistinguishable from a legitimate one.

    Control for "an emitted record must not cite a reference that was never
    successfully read". The pre-#628 path passes this check only because its
    output is wrong in a way nothing can see; the current path refuses.
    """
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [BIT_IDENTICAL_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    legitimate = note_from_bounds(old_blanket_except_bounds(), "p__s", "bit-identical")
    assert legitimate["wet_repeat_relative_max_diff"] is None

    monkeypatch.setattr(ad, "REPEATABILITY", str(tmp_path / "absent.json"))
    unread = note_from_bounds(old_blanket_except_bounds(), "p__s", "bit-identical")
    assert unread == legitimate                      # the defect: same bytes, no error
    with pytest.raises(Refuse):                      # the fix: refuses instead
        ad.repeatability_bounds()


# --- #654: --out and --ablations govern both ends of a run -----------------
#
# `main()` used to write the module constant `SUMMARY` unconditionally and
# `load_sidecars()` used to walk the module constant `ABLATIONS`, so a
# "read-only" re-run into a scratch directory
# (`python3 tools/ablation_delta.py --out /tmp/x`) rewrote the committed
# reports/sxt-014/ablation-summary.json in place, with scratch-relative
# `delta_json` paths in it, and `--ablations <dir>` silently read the
# committed sidecars instead of <dir>.


def scratch_run(tmp_path, monkeypatch, out, argv_out=None, ablations_constant=None):
    """One anchor+offslot-ctrl group and a readable reference; run main().

    `ablations_constant` is what `ad.ABLATIONS` is pinned to; it defaults to
    the same scratch group `--ablations` names. Pinning it keeps each test
    below a control for exactly one defect: the summary-path tests then fail
    against the pre-#654 `main()` on the summary write itself, not on the
    sibling `--ablations` defect reaching the committed corpus first. That
    sibling is pinned on its own by
    `test_ablations_flag_governs_the_directory_walked`, which overrides it.
    """
    abl = offslot_group(tmp_path)
    monkeypatch.setattr(ad, "ABLATIONS",
                        str(abl if ablations_constant is None else ablations_constant))
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [BIT_IDENTICAL_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    argv = ["ablation_delta", "--ablations", str(abl)]
    if argv_out is not None:
        argv += ["--out", argv_out]
    elif out is not None:
        argv += ["--out", str(out)]
    monkeypatch.setattr(sys, "argv", argv)
    return ad.main()


def test_scratch_out_writes_its_own_summary_not_the_committed_one(tmp_path, monkeypatch,
                                                                  committed_summary):
    """Failure control for #654: the committed summary must stay untouched.

    Against the pre-#654 `main()` this fails on both halves -- the
    unconditional `open(SUMMARY, "w")` creates the sentinel standing in for
    reports/sxt-014/ablation-summary.json, and no summary is written beside
    the per-pair records in the scratch directory.
    """
    out = tmp_path / "scratch"
    assert scratch_run(tmp_path, monkeypatch, out) == 0

    summary = out / "ablation-summary.json"
    assert summary.exists(), "a scratch --out must carry its own summary"
    aggregate = json.loads(summary.read_text())
    assert aggregate["totals"]["pairs_compared"] == 1
    assert [r["variant"] for r in aggregate["rows"]] == ["ctrl"]
    assert (out / "p" / "ctrl.json").exists()
    assert not committed_summary.exists(), "the committed record was rewritten"


def test_default_out_targets_the_committed_summary_and_deltas(tmp_path, monkeypatch,
                                                              committed_summary):
    """No --out: the documented default layout does not move (#654).

    DELTAS/SUMMARY are redirected into tmp_path so the assertion is about the
    resolved path, not about rewriting committed evidence.
    """
    deltas = tmp_path / "committed-deltas"
    monkeypatch.setattr(ad, "DELTAS", str(deltas))
    assert scratch_run(tmp_path, monkeypatch, None) == 0

    assert committed_summary.exists(), "the default run must write the committed summary"
    assert json.loads(committed_summary.read_text())["totals"]["pairs_compared"] == 1
    assert (deltas / "p" / "ctrl.json").exists()
    assert not (deltas / "ablation-summary.json").exists()


@pytest.mark.parametrize("spelling", ["trailing-slash", "relative"])
def test_default_directory_spelled_otherwise_still_resolves_to_committed_summary(
        tmp_path, monkeypatch, committed_summary, spelling):
    """`--out reports/sxt-014/deltas/` is the default directory, not a scratch one."""
    deltas = tmp_path / "committed-deltas"
    monkeypatch.setattr(ad, "DELTAS", str(deltas))
    if spelling == "trailing-slash":
        argv_out = str(deltas) + os.sep
    else:
        monkeypatch.chdir(tmp_path)
        argv_out = os.path.join(".", "committed-deltas")

    assert scratch_run(tmp_path, monkeypatch, None, argv_out=argv_out) == 0

    assert committed_summary.exists()
    assert not (deltas / "ablation-summary.json").exists()


def test_ablations_flag_governs_the_directory_walked(tmp_path, monkeypatch,
                                                     committed_summary):
    """Failure control for the sibling defect: ABLATIONS is not the source.

    `ad.ABLATIONS` is pointed at an empty directory -- the pre-#654
    `load_sidecars()` walks it, finds nothing and compares no pairs, so no
    `<out>/ablation-summary.json` exists to read.
    """
    unread = tmp_path / "constant-dir"
    unread.mkdir()
    out = tmp_path / "scratch"

    assert scratch_run(tmp_path, monkeypatch, out, ablations_constant=unread) == 0

    rows = json.loads((out / "ablation-summary.json").read_text())["rows"]
    assert [r["variant"] for r in rows] == ["ctrl"]
    assert not list(unread.iterdir()), "the constant directory was never an output either"
    assert not committed_summary.exists()
