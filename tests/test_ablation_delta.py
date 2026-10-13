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
