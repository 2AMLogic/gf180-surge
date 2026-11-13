"""#438: ablation_delta must validate both WAVs before any identity shortcut.

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


def test_refusal_leaves_no_pair_record_or_summary(tmp_path, monkeypatch, capsys):
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
    summary = tmp_path / "summary.json"
    monkeypatch.setattr(ad, "ABLATIONS", str(abl))
    monkeypatch.setattr(ad, "SUMMARY", str(summary))
    monkeypatch.setattr(sys, "argv", ["ablation_delta", "--ablations", str(abl),
                                      "--out", str(out)])
    with pytest.raises(Refuse):
        ad.main()
    assert not summary.exists()
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


def drive_main(monkeypatch, abl, out, summary):
    monkeypatch.setattr(ad, "ABLATIONS", str(abl))
    monkeypatch.setattr(ad, "SUMMARY", str(summary))
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


def test_missing_reference_leaves_no_offslot_record_or_summary(tmp_path, monkeypatch):
    abl = offslot_group(tmp_path)
    out, summary = tmp_path / "deltas", tmp_path / "summary.json"
    monkeypatch.setattr(ad, "REPEATABILITY", str(tmp_path / "absent.json"))
    with pytest.raises(Refuse, match="missing/unreadable"):
        drive_main(monkeypatch, abl, out, summary)
    assert not summary.exists()
    assert not out.exists()


def test_absent_fixture_key_leaves_no_offslot_record_or_summary(tmp_path, monkeypatch):
    abl = offslot_group(tmp_path)
    out, summary = tmp_path / "deltas", tmp_path / "summary.json"
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [dict(BIT_IDENTICAL_FIXTURE, fixture_id="other__s")])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    with pytest.raises(Refuse, match="has no fixture 'p__s'"):
        drive_main(monkeypatch, abl, out, summary)
    assert not summary.exists()
    assert not out.exists()


def test_note_carries_wet_relative_max_diff_when_the_reference_records_one(tmp_path,
                                                                          monkeypatch, capsys):
    abl = offslot_group(tmp_path, repeatability_class="free-phase", identical=False)
    out, summary = tmp_path / "deltas", tmp_path / "summary.json"
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [FREE_PHASE_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    assert drive_main(monkeypatch, abl, out, summary) == 0
    note = json.loads((out / "p" / "ctrl.json").read_text())["repeatability_note"]
    assert note["wet_repeat_relative_max_diff"] == [1.72701, 1.583799]
    assert note["expect_bit_identity"] is False


def test_note_null_now_means_only_a_bit_identical_repeat(tmp_path, monkeypatch, capsys):
    """`null` survives -- but only when the fixture was read and records no diff."""
    abl = offslot_group(tmp_path)
    out, summary = tmp_path / "deltas", tmp_path / "summary.json"
    ref = tmp_path / "repeatability.json"
    write_repeatability(ref, [BIT_IDENTICAL_FIXTURE])
    monkeypatch.setattr(ad, "REPEATABILITY", str(ref))
    assert drive_main(monkeypatch, abl, out, summary) == 0
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
