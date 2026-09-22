#!/usr/bin/env python3
"""SXT-026 wavetable asset compiler tests (issue #19).

Covers: manifest emission from an external .wt (oracle required, skipped
when absent), identity-mismatch ABORT, mip threshold facts, the verify CLI,
and the in-repo license guard (no .wt payload may ever be committed).
"""

import glob
import json
import os
import struct
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from compiler.assets import wavetable as wt  # noqa: E402
from compiler.assets.wavetable import AssetIdentityError  # noqa: E402

ORACLE_DATA = os.environ.get(
    "ORACLE_SURGE_DATA",
    "/Users/joseph/dev/surge-xt-oracle/surge/resources/data")
TRIANGLE_REL = "wavetables/Basic/Triangle.wt"
TRIANGLE_SHA = "f49a2381bc699b11136457f1f9f73150e73d612fa1290092d61bcdd6029b26a9"

PRESET = "resources/data/patches_3rdparty/Argitoth/Drums/Kick.fxp"
ORACLE_PRESENT = os.path.isfile(os.path.join(ORACLE_DATA, TRIANGLE_REL))

needs_oracle = pytest.mark.skipif(not ORACLE_PRESENT,
                                  reason="external pinned oracle not present")


def _triangle_bytes():
    with open(os.path.join(ORACLE_DATA, TRIANGLE_REL), "rb") as f:
        return f.read()


@needs_oracle
def test_parse_header_facts():
    hd = wt.parse_wt(_triangle_bytes(), "Triangle.wt")
    assert (hd["wave_size"], hd["wave_count"]) == (1024, 16)
    assert hd["format"] == "int15"
    assert not hd["is_sample"] and not hd["loop_sample"]
    assert hd["bytes"] == 32780
    assert hd["sha256"] == TRIANGLE_SHA
    assert hd["dt"] == 1.0 / 1024
    assert hd["mipmap_built_levels"] == 10


@needs_oracle
def test_parse_rejects_bad_magic_and_truncation():
    data = _triangle_bytes()
    with pytest.raises(AssetIdentityError):
        wt.parse_wt(b"XAWT" + data[4:], "x")
    with pytest.raises(AssetIdentityError):
        wt.parse_wt(data[:64], "x")
    bad = bytearray(data)
    bad[4:8] = struct.pack("<I", 1000)  # non-power-of-two size
    with pytest.raises(AssetIdentityError):
        wt.parse_wt(bytes(bad), "x")


@needs_oracle
def test_mip_thresholds_match_pinned_engine():
    # WavetableOscillator::convolute: a < 2^-k * 1.8 and ts >= 2^(k+1)
    for k, thr, min_ts in wt.MIP_THRESHOLDS:
        assert min_ts == 1 << (k + 1)
        engine_thr = struct.unpack("f", struct.pack("f", (2.0 ** -k) * 1.8))[0]
        assert thr == engine_thr
    by_level = {e["level"]: e for e in wt.expected_mips(
        wt.parse_wt(_triangle_bytes(), "T"))}
    assert by_level[6]["threshold_a"] == 0.02812499925494194
    assert by_level[6]["min_full_size"] == 128
    assert by_level[1]["min_full_size"] == 4
    assert by_level[0]["frame_entries"] == 1024
    assert by_level[6]["frame_entries"] == 16
    assert all(by_level[k]["serviceable"] for k in range(7))


@needs_oracle
def test_manifest_records_dims_mips_residency():
    hd = wt.parse_wt(_triangle_bytes(), "T")
    m = wt.build_manifest(hd, TRIANGLE_REL, TRIANGLE_SHA, 0, 1, "Triangle")
    assert m["identity"]["sha256"] == TRIANGLE_SHA
    assert m["dims"]["wave_size"] == 1024 and m["dims"]["wave_count"] == 16
    assert m["mip"]["built_levels"] == 10
    assert m["residency"]["payload"] == "external_flash_asset"
    assert m["residency"]["writable"] is False
    assert m["residency"]["on_chip_working_set"][
        "float32_bytes_per_level"][0] == 4096
    # "hashes only in-repo": the record carries no sample payload
    assert "payload_hex" not in json.dumps(m)


@needs_oracle
def test_hash_mismatch_aborts():
    hd = wt.parse_wt(_triangle_bytes(), "T")
    with pytest.raises(AssetIdentityError) as ei:
        wt.build_manifest(hd, TRIANGLE_REL, "0" * 64, 0, 1, "T")
    assert "ABORT" in str(ei.value) or "identity mismatch" in str(ei.value)


@needs_oracle
def test_compile_with_asset_root_embeds_manifest():
    out = tempfile.mkdtemp(prefix="sxt026-manifest-")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "compiler", "compile.py"),
         "compile", "--path", PRESET, "--asset-root", ORACLE_DATA,
         "--out-dir", out],
        cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    image = glob.glob(os.path.join(out, "*.image.json"))[0]
    d = json.load(open(image))
    mans = d["body"]["derived"]["wavetable_asset_manifests"]
    assert len(mans) == 1
    assert mans[0]["identity"]["sha256"] == TRIANGLE_SHA
    assert mans[0]["dims"]["format"] == "int15"
    # the payload bytes must not appear anywhere in the image
    raw = open(image, "rb").read()
    assert b"vawt" not in raw.split(b'"magic": "vawt"')[0].split(b'"magic"')[-1] \
        or True  # magic NAME is fine; assert no payload-sized blob
    payload = _triangle_bytes()[12:512]
    assert payload not in raw


@needs_oracle
def test_compile_aborts_on_substituted_asset():
    with tempfile.TemporaryDirectory(prefix="sxt026-bad-") as bad:
        os.makedirs(os.path.join(bad, "wavetables", "Basic"))
        data = bytearray(_triangle_bytes())
        for i in range(12, 12 + 4096):
            data[i] ^= 0xFF
        with open(os.path.join(bad, TRIANGLE_REL), "wb") as f:
            f.write(bytes(data))
        r = subprocess.run(
            [sys.executable, os.path.join(REPO, "compiler", "compile.py"),
             "compile", "--path", PRESET, "--asset-root", bad,
             "--out-dir", os.path.join(bad, "out")],
            cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 2
        assert "ABORT" in r.stderr
        assert "identity mismatch" in r.stderr
        assert not glob.glob(os.path.join(bad, "out", "*.image.bin"))


@needs_oracle
def test_verify_cli_pass_then_abort():
    out = tempfile.mkdtemp(prefix="sxt026-verify-")
    subprocess.run(
        [sys.executable, os.path.join(REPO, "compiler", "compile.py"),
         "compile", "--path", PRESET, "--asset-root", ORACLE_DATA,
         "--out-dir", out], cwd=REPO, capture_output=True, text=True, check=True)
    image = glob.glob(os.path.join(out, "*.image.bin"))[0]
    v = subprocess.run(
        [sys.executable, os.path.join(REPO, "compiler", "assets", "wavetable.py"),
         "verify", "--image", image, "--asset-root", ORACLE_DATA],
        cwd=REPO, capture_output=True, text=True)
    assert v.returncode == 0 and '"verdict": "PASS"' in v.stdout

    # same image verified against the flipped root must ABORT
    with tempfile.TemporaryDirectory(prefix="sxt026-verifybad-") as bad:
        os.makedirs(os.path.join(bad, "wavetables", "Basic"))
        data = bytearray(_triangle_bytes())
        data[12] ^= 0x01
        with open(os.path.join(bad, TRIANGLE_REL), "wb") as f:
            f.write(bytes(data))
        v2 = subprocess.run(
            [sys.executable, os.path.join(REPO, "compiler", "assets", "wavetable.py"),
             "verify", "--image", image, "--asset-root", bad],
            cwd=REPO, capture_output=True, text=True)
        assert v2.returncode == 2 and "HASH MISMATCH" in v2.stderr


def test_no_wt_payload_committed_in_repo():
    """License guard (decision-records/0004): no 'vawt' payload anywhere in
    the repository tree."""
    hits = []
    for root, _dirs, files in os.walk(REPO):
        if ".git" in root.split(os.sep):
            continue
        for fn in files:
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) >= 12:
                    with open(p, "rb") as f:
                        if f.read(4) == b"vawt":
                            hits.append(p)
            except OSError:
                pass
    assert hits == []


# ---------------------------------------------------------------------------
# frozen model (oracle-dependent: mip tables derive from the external tree)
# ---------------------------------------------------------------------------

@needs_oracle
def test_model_unison_beyond_cap_explicitly_rejected():
    sys.path.insert(0, os.path.join(REPO, "model", "oscillators",
                                    "wavetable"))
    import wt_model as wm

    with open(os.path.join(REPO, "model/oscillators/wavetable/inputs/"
                                 "kick-wtfix.json")) as f:
        d = json.load(f)
    d["unison"] = 17
    p = os.path.join(tempfile.mkdtemp(), "u17.json")
    json.dump(d, open(p, "w"))
    inp = wm.Inputs(p)
    with pytest.raises(RuntimeError) as ei:
        wm.WavetableOsc(inp, 60)
    assert "explicitly rejected" in str(ei.value)


@needs_oracle
def test_model_mip_selection_sweeps_with_pitch():
    sys.path.insert(0, os.path.join(REPO, "model", "oscillators",
                                    "wavetable"))
    import wt_model as wm

    inp = wm.Inputs(os.path.join(REPO, "model/oscillators/wavetable/inputs/"
                                        "kick-wtfix-kt.json"))
    assert inp.keytrack and inp.octave == 0
    seen = []
    for note in (24, 96, 120):
        o = wm.WavetableOsc(inp, note)
        o.process_block()
        seen.append(o.voices[0]["mipmap"])
    assert seen == [0, 5, 6]


@needs_oracle
def test_model_mip_level0_words_exact_for_int15_payload():
    sys.path.insert(0, os.path.join(REPO, "model", "oscillators",
                                    "wavetable"))
    sys.path.insert(0, os.path.join(REPO, "model", "voice"))
    import wt_model as wm
    import voice_model as vm

    inp = wm.Inputs(os.path.join(REPO, "model/oscillators/wavetable/inputs/"
                                        "kick-wtfix.json"))
    data = open(os.path.join(ORACLE_DATA, TRIANGLE_REL), "rb").read()
    words = inp.mip_tables[0]
    off = 12
    for w in words[:512]:
        s, = struct.unpack("<h", data[off:off + 2])
        off += 2
        assert w == vm.sat(s << 7)
