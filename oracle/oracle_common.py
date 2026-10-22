"""Shared helpers for the SXT-010 native oracle harness.

This module is original to the gf180-surge repository (Apache-2.0). It imports
the externally pinned Surge XT engine (GPL-3.0-or-later, kept outside this
repository) through its official surgepy binding and copies no engine source,
tables, or assets into this repository.
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import struct
import sys
import types
import wave

# Repo-local, git-ignored checkout of the pinned engine (oracle/fetch-and-build.sh).
DEFAULT_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "oracle", "build", "surge")
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


def data_dir():
    """Asset root (resources/data): ORACLE_SURGE_DATA, else under engine_dir()."""
    return os.environ.get("ORACLE_SURGE_DATA") or os.path.join(engine_dir(), "resources", "data")


def build_dir():
    d = engine_dir()
    b = os.environ.get(
        "ORACLE_BUILD_DIR_REL", DEFAULT_PYTHON_BUILD_DIR
    )
    return os.path.join(d, b)


class OracleBindingError(ImportError):
    """The selected native surgepy binding could not be established."""


_BINDING_STATE = {}


def _binding_dir():
    return os.path.realpath(os.path.join(build_dir(), "src", "surge-python"))


def _select_candidate(so_dir):
    """Return the single native extension candidate in so_dir, or refuse."""
    if not os.path.isdir(so_dir):
        raise OracleBindingError(
            f"selected surgepy build directory does not exist: {so_dir} "
            f"(build_dir={build_dir()})"
        )
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    names = sorted(os.listdir(so_dir))
    native = [n for n in names if n.startswith("surgepy") and n.endswith(suffixes)
              and os.path.isfile(os.path.join(so_dir, n))]
    stubs = [n for n in names if n in ("surgepy.py", "surgepy.pyc")]
    if not native:
        raise OracleBindingError(
            f"no native surgepy extension (suffixes {list(suffixes)}) in {so_dir}; "
            f"python stubs present: {stubs or 'none'}; refusing ambient fallback"
        )
    if len(native) > 1:
        raise OracleBindingError(f"ambiguous native surgepy candidates in {so_dir}: {native}")
    if stubs:
        raise OracleBindingError(
            f"python stub {stubs} alongside native candidate {native[0]} in {so_dir}"
        )
    cand = os.path.realpath(os.path.join(so_dir, native[0]))
    if os.path.commonpath([cand, so_dir]) != so_dir:
        raise OracleBindingError(
            f"native candidate {native[0]} resolves to {cand}, escaping selected directory {so_dir}"
        )
    return cand


def _check_cached(mod, cand, so_dir):
    spec = getattr(mod, "__spec__", None)
    loader = getattr(spec, "loader", None)
    if not isinstance(mod, types.ModuleType) or not isinstance(
        loader, importlib.machinery.ExtensionFileLoader
    ):
        raise OracleBindingError(
            f"cached sys.modules['surgepy'] is not a natively loaded extension "
            f"(loader={type(loader).__name__}, __file__={getattr(mod, '__file__', None)!r}); "
            f"selected build {so_dir}"
        )
    origin = getattr(mod, "__file__", None)
    if not origin or os.path.realpath(origin) != cand or os.path.realpath(
        getattr(loader, "path", "") or ""
    ) != cand:
        raise OracleBindingError(
            f"cached surgepy origin {origin!r} differs from selected candidate {cand} "
            f"(selected build {so_dir}); refusing in-process reload"
        )


def import_surgepy():
    """Load the surgepy native extension from the selected external build.

    The extension is loaded explicitly from build_dir()/src/surge-python (as
    upstream surgepy tests build it) with the native extension loader; no
    sys.path search is used, so an ambient module cannot satisfy the import.
    Missing/ambiguous/stub-only/unloadable candidates, a candidate escaping the
    selected directory, and a cached module of any other origin all raise
    OracleBindingError before any engine is created.
    """
    _BINDING_STATE.clear()
    so_dir = _binding_dir()
    cand = _select_candidate(so_dir)
    mod = sys.modules.get("surgepy")
    if mod is not None:
        _check_cached(mod, cand, so_dir)
    else:
        loader = importlib.machinery.ExtensionFileLoader("surgepy", cand)
        spec = importlib.util.spec_from_file_location("surgepy", cand, loader=loader)
        try:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["surgepy"] = mod
            loader.exec_module(mod)
        except BaseException as e:
            sys.modules.pop("surgepy", None)
            raise OracleBindingError(
                f"failed to load native surgepy {cand} from {so_dir}: {type(e).__name__}: {e}"
            ) from e
    _BINDING_STATE.update(
        module=mod,
        module_path=cand,
        module_sha256=sha256_file(cand),
        build_dir=os.path.realpath(build_dir()),
    )
    return mod


def binding_provenance(module):
    """Provenance dict for a module returned by a successful import_surgepy().

    module_sha256 identifies the loaded binary only; it is not proof of the
    engine source commit.
    """
    if not _BINDING_STATE or _BINDING_STATE.get("module") is not module:
        raise OracleBindingError("module was not validated by import_surgepy()")
    return {k: _BINDING_STATE[k] for k in ("module_path", "module_sha256", "build_dir")}


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
