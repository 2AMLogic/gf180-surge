"""Shared helpers for the SXT-010 native oracle harness.

This module is original to the gf180-surge repository (Apache-2.0). It imports
the externally pinned Surge XT engine (GPL-3.0-or-later, kept outside this
repository) through its official surgepy binding and copies no engine source,
tables, or assets into this repository.
"""

import hashlib
import json
import os
import struct
import sys
import wave

DEFAULT_ENGINE_DIR = "/Users/joseph/dev/surge-xt-oracle/surge"
DEFAULT_PYTHON_BUILD_DIR = "build-py311"
CENSUS_DIR = os.path.join("corpus", "census-v0.1")


def reexec_under_pinned_python(repo_root):
    """Re-exec under the manifest-pinned interpreter if we are not on it.

    The surgepy module is built for one CPython ABI (cpython-311 here); the
    ambient `python3` may be anything (3.14, anaconda, ...), so enforce the
    pinned runtime instead of failing with a confusing ABI error.
    """
    mp = os.path.join(repo_root, "oracle", "manifest.json")
    with open(mp, "r", encoding="utf-8") as f:
        pinned = json.load(f)["build"]["python_interpreter"]
    if os.path.realpath(sys.executable) != os.path.realpath(pinned) and os.path.exists(pinned):
        os.execv(pinned, [pinned, os.path.abspath(sys.argv[0])] + sys.argv[1:])


def engine_dir():
    return os.environ.get("ORACLE_SURGE_DIR", DEFAULT_ENGINE_DIR)


def build_dir():
    d = engine_dir()
    b = os.environ.get(
        "ORACLE_BUILD_DIR_REL", DEFAULT_PYTHON_BUILD_DIR
    )
    return os.path.join(d, b)


def import_surgepy():
    """Import the surgepy binding built from the pinned engine tree.

    Import the built .so directly (as upstream surgepy tests do). The
    src/surge-python/surgepy/ package wrapper is only for scikit-build wheels;
    putting it on sys.path here would shadow the native module with an empty
    namespace package.
    """
    so_dir = os.path.join(build_dir(), "src", "surge-python")
    if so_dir not in sys.path:
        sys.path.insert(0, so_dir)
    import surgepy  # noqa: PLC0415

    return surgepy


def data_home():
    """Factory data root inside the pinned engine tree (passed via env)."""
    return os.path.join(engine_dir(), "resources", "data")


def apply_engine_env():
    """Pin the engine's asset root to the pinned source tree.

    SurgeStorage::getOverrideDataHome reads SURGE_DATA_HOME; this keeps
    wavetable/patch asset resolution inside the pinned checkout instead of any
    machine-global Surge install.
    """
    os.environ["SURGE_DATA_HOME"] = data_home()


def git_blob_sha1(path):
    """Git blob SHA-1 of a file on disk (matches census git_blob_sha1)."""
    data = open(path, "rb").read()
    blob = b"blob %d\x00" % len(data) + data
    return hashlib.sha1(blob).hexdigest()


def load_census_manifest(repo_root):
    p = os.path.join(repo_root, CENSUS_DIR, "corpus-manifest.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_wav_mono16(path, mono_samples, sample_rate):
    """Write mono 16-bit PCM WAV from float samples in [-1, 1]."""
    frames = bytearray()
    for x in mono_samples:
        xi = int(max(-1.0, min(1.0, float(x))) * 32767.0)
        frames += struct.pack("<h", xi)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
