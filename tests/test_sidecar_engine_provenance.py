#!/usr/bin/env python3
"""#671 (F-660-1) -- a render sidecar's `engine` block identifies the renderer.

What went wrong: `fixtures/render_lfo_fixture.py`, `render_slfo_fixture.py`
and `render_mw_fixture.py` wrote their sidecar `engine` block by copying two
fields out of the extractor *inputs* file (`model/voice/attacky_*_inputs.json`)
instead of reading the engine they were running on. #660 demonstrated it live:
a fresh sidecar rendered under the stock pinned oracle recorded a
`sxt037-tap` version string, because that is what the inputs file said.

What this file enforces:

  * the failure control -- one Pattern A producer (`render_slfo_fixture.py`,
    the only one whose inputs path is a CLI flag, so the test can generate
    the inputs file) runs under a compiled stand-in `surgepy` extension
    (explicitly NOT the Surge engine; the same pattern
    `tests/test_oracle_binding_origin.py` uses) whose `getVersion()` differs
    from the inputs file. The sidecar must make the difference visible:
    `engine` carries the live reading, `inputs_engine` carries the inherited
    one. Before the #671 fix the control fails -- the sidecar had only the
    inherited fields and no live reading anywhere.
  * the agreement edge -- when the inputs file and the running engine agree,
    both fields are still recorded under their distinct keys. Agreement is a
    finding, not a licence to collapse the two into one.
  * the fast-variant edge -- `--slfo-inputs` may select
    `attacky_slfo_fast_inputs.json`; both variants carry the live block.
  * the enumeration guard -- no committed `reports/**/*.json` sidecar may
    carry an `engine` object drawn only from the extractor-inputs vocabulary
    (`commit` / `version_string` / `block_size` / `sample_rate`), i.e. with
    no field that could only have come from a live engine reading. The 27
    files DETECTED_2026_11_14 declares are the measured, annotated exception
    list as of this change; a 28th file (or a changed shape in one of the 27)
    fails here and must be declared in the same change that produced it.

Environment: the stand-in needs a C compiler with Python.h and a numpy
importable by the interpreter that runs the producer subprocess (this
interpreter). Without either, the run-based tests skip (NOT_RUN); the
enumeration guard is pure stdlib and always runs.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import importlib.machinery

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]
REPORTS = os.path.join(REPO, "reports")
SEQ = "seq-notes-repeated-v1"

# getVersion() of the stand-in extension. Deliberately unlike any engine
# string the repo pins (stock 1.4.HEAD.58914e59c, taps 1.4.sxt037-tap.*).
STUB_VERSION = "0.0.0.standin-not-surge"

# The extractor-inputs engine vocabulary. An `engine` object whose keys all
# live here carries nothing a live engine reading is known to produce
# (`engine_version_string`, `engine_commit`, `surgepy`, `surgepy_module`,
# `surgepy_version`, `module_sha256`, `binding`, `provenance`).
INHERITED_VOCAB = {"commit", "version_string", "block_size", "sample_rate"}

# Measured on 2026-11-14 (DR-0021): every committed reports/**/*.json whose
# `engine` object draws only from INHERITED_VOCAB. Three annotated groups:
#  - sxt-032 / sxt-035 / SXT-041 (13): written by the three Pattern A
#    producers from their inputs files; the producers now record the live
#    engine and these committed sidecars are deliberately NOT re-rendered
#    (7 of the 13 name tap builds this repo cannot reach; re-rendering the
#    others here would be the relabel issue #671 forbids). DR-0021 decides
#    this; the *producers* are fixed, these records stay as committed.
#  - SXT-034 uni references (5): `tools/render_uni_reference.py` reads
#    `version_string` live via getVersion() at render time and writes the
#    `commit` literal beside it, so a live field existed at write time even
#    though the shape cannot prove it. The literal-commit sites are a
#    separate, unfiled cleanup (#671 out of scope).
#  - sxt-037 bundle metas (9): written by the DR-0005 tap extraction bundle
#    about its own extraction run, not by a render-sidecar producer.
DETECTED_2026_11_14 = {
    "pattern_a_render_sidecars_committed_unrerendered": sorted([
        "reports/SXT-041/artifacts/reference-seq-modwheel-v1-slfo-fixture.json",
        "reports/SXT-041/artifacts/reference-seq-notes-coverage-v1-slfo-fixture.json",
        "reports/SXT-041/artifacts/reference-seq-notes-holds-v1-slfo-fixture.json",
        "reports/SXT-041/artifacts/reference-seq-notes-repeated-v1-slfo-fixture.json",
        "reports/SXT-041/artifacts/reference-sxt041-slfo-overlap-v1-slfo-fast.json",
        "reports/SXT-041/artifacts/reference-sxt041-slfo-overlap-v1-slfo-fixture.json",
        "reports/sxt-032/artifacts/reference-seq-modwheel-v1.json",
        "reports/sxt-032/artifacts/reference-seq-notes-coverage-v1.json",
        "reports/sxt-032/artifacts/reference-seq-notes-holds-v1.json",
        "reports/sxt-032/artifacts/reference-seq-notes-repeated-v1.json",
        "reports/sxt-035/artifacts/reference-seq-modwheel-v1.json",
        "reports/sxt-035/artifacts/reference-seq-notes-coverage-v1.json",
        "reports/sxt-035/artifacts/reference-seq-notes-repeated-v1.json",
    ]),
    "uni_reference_live_getversion_at_write": sorted([
        "reports/SXT-034/artifacts/reference-seq-notes-coverage-v1-uni2.json",
        "reports/SXT-034/artifacts/reference-seq-notes-repeated-v1-uni1.json",
        "reports/SXT-034/artifacts/reference-seq-notes-repeated-v1-uni4.json",
        "reports/SXT-034/artifacts/reference-seq-poly-8-v1-uni2.json",
        "reports/SXT-034/artifacts/reference-sxt034-smoke-v1-uni16.json",
    ]),
    "sxt037_tap_extraction_bundle_metas": sorted([
        "reports/sxt-037/artifacts/bundle-attacky-neutrality/meta.json",
        "reports/sxt-037/artifacts/bundle-badnews-cut-hi/meta.json",
        "reports/sxt-037/artifacts/bundle-badnews-cut-lo/meta.json",
        "reports/sxt-037/artifacts/bundle-badnews-reso1/meta.json",
        "reports/sxt-037/artifacts/bundle-badnews-toggle/meta.json",
        "reports/sxt-037/artifacts/bundle-badnews/meta.json",
        "reports/sxt-037/artifacts/bundle-rainy/meta.json",
        "reports/sxt-037/artifacts/bundle-t9-substd/meta.json",
        "reports/sxt-037/artifacts/bundle-t9/meta.json",
    ]),
}


# ------------------------------------------------------------------ helpers
def numpy_available():
    return importlib.util.find_spec("numpy") is not None


def inherited_only_sidecars(root):
    """*.json under root whose engine object is inherited-only (root-rel)."""
    hits = []
    base = os.path.abspath(root)
    for dirpath, _dirs, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            eng = data.get("engine")
            if (isinstance(eng, dict) and eng
                    and set(eng) <= INHERITED_VOCAB):
                hits.append(os.path.relpath(path, base))
    return sorted(hits)


def git_blob_sha1(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


# ------------------------------------------------- the stand-in extension
# A tiny ORIGINAL C extension named `surgepy` (a stand-in, NOT the Surge
# engine): its module init runs this Python block, so the stand-in can
# satisfy the producer's render path with numpy buffers while reporting a
# getVersion() that differs from any inputs file.
STUB_PY = r'''
import sys, types
import numpy as np

VERSION = "0.0.0.standin-not-surge"

class _Auto(dict):
    def __missing__(self, k):
        v = _Auto()
        self[k] = v
        return v

class _Synth:
    def __init__(self, sr=48000.0):
        self._sr = float(sr)
        self._bs = 32
        self._depths = {}
        self._vals = {}
    def loadPatch(self, path): return True
    def getSampleRate(self): return self._sr
    def getBlockSize(self): return self._bs
    def createMultiBlock(self, n):
        return np.zeros((2, int(n) * self._bs), dtype=np.float32)
    def processMultiBlock(self, buf, *a): return None
    def getPatch(self): return _Auto()
    def getModSource(self, i): return int(i)
    def isValidModulation(self, target, ms): return True
    def setModDepth01(self, target, ms, depth, s, c):
        self._depths[(id(target), ms)] = depth
    def getModDepth01(self, target, ms, s, c):
        return self._depths.get((id(target), ms), 0.0)
    def setParamVal(self, p, v): self._vals[id(p)] = v
    def getParamVal(self, p): return self._vals.get(id(p), 0)
    def getAllModRoutings(self): return {"scene": [{"voice": []}]}
    def pitchBend(self, *a): pass
    def channelController(self, *a): pass
    def channelAftertouch(self, *a): pass
    def allNotesOff(self): pass
    def playNote(self, *a): pass
    def releaseNote(self, *a): pass

def createSurge(sr=48000.0): return _Synth(sr)
def getVersion(): return VERSION

const = types.ModuleType("surgepy.constants")
const.ms_lfo1 = 100
const.ms_slfo1 = 200
const.ms_modwheel = 300
const.fxt_off = 0
sys.modules["surgepy.constants"] = const
'''

STUB_C_TEMPLATE = '''#include <Python.h>
static const char PYSRC[] =
"%s";
static struct PyModuleDef mdef = {PyModuleDef_HEAD_INIT, "surgepy", NULL,
                                  -1, NULL};
PyMODINIT_FUNC PyInit_surgepy(void) {
    PyObject *mod = PyModule_Create(&mdef);
    if (!mod) return NULL;
    PyObject *res = PyRun_String(PYSRC, Py_file_input,
                                 PyModule_GetDict(mod),
                                 PyModule_GetDict(mod));
    if (!res) { PyErr_Print(); Py_DECREF(mod); return NULL; }
    Py_DECREF(res);
    return mod;
}
'''


def compile_stub(so_dir):
    cc = shutil.which("cc") or shutil.which("gcc")
    inc = sysconfig.get_paths()["include"]
    if not cc or not os.path.exists(os.path.join(inc, "Python.h")):
        pytest.skip("NOT_RUN: no C compiler / Python.h for stand-in extension")
    if not numpy_available():
        pytest.skip("NOT_RUN: numpy is not importable by this interpreter, "
                    "so the producer subprocess cannot run")
    src = os.path.join(so_dir, "surgepy_standin.c")
    with open(src, "w", encoding="utf-8") as f:
        f.write(STUB_C_TEMPLATE % (
            STUB_PY.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")))
    out = os.path.join(so_dir, "surgepy" + SUFFIX)
    r = subprocess.run([cc, "-shared", "-fPIC", "-I" + inc, src, "-o", out],
                       capture_output=True, text=True)
    if r.returncode:
        pytest.skip("NOT_RUN: stand-in extension failed to compile: "
                    + r.stderr[:200])
    return out


def make_fake_engine(tmp_path):
    """ORACLE_SURGE_DIR tree: the stand-in build + a synthetic preset file.

    The preset is stand-in bytes written here, not a Surge asset; the inputs
    file the test generates carries ITS blob sha1, so the producer's
    census-blob gate passes without any oracle install.
    """
    engine = tmp_path / "engine"
    so_dir = engine / "build-py311" / "src" / "surge-python"
    so_dir.mkdir(parents=True)
    so = compile_stub(str(so_dir))
    fxp = engine / "resources" / "data" / "patches_factory" / "Basses" / \
        "Attacky.fxp"
    fxp.parent.mkdir(parents=True)
    fxp.write_bytes(b"#671 stand-in preset payload (not a Surge asset)\n")
    return engine, fxp, so


def make_inputs(tmp_path, fxp, version_string, source):
    """A inputs file whose census blob matches the stand-in preset."""
    with open(os.path.join(REPO, source), encoding="utf-8") as f:
        data = json.load(f)
    data["preset"]["census_blob_sha1"] = git_blob_sha1(fxp)
    data["engine"]["version_string"] = version_string
    path = tmp_path / (os.path.basename(source))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def run_slfo_producer(tmp_path, engine, inputs_path, tag):
    out_dir = tmp_path / ("out-" + tag)
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "ORACLE_SURGE_DIR", "ORACLE_PYTHON",
                        "ORACLE_SURGE_DATA", "ORACLE_BUILD_DIR_REL",
                        "SURGE_DATA_HOME")}
    env["ORACLE_SURGE_DIR"] = str(engine)
    env["ORACLE_BUILD_DIR_REL"] = "build-py311"
    p = subprocess.run(
        [sys.executable,
         os.path.join(REPO, "fixtures", "render_slfo_fixture.py"),
         "--sequence", SEQ, "--out-dir", str(out_dir),
         "--slfo-inputs", str(inputs_path), "--tag", tag, "--repeats", "1"],
        env=env, capture_output=True, text=True, cwd=str(tmp_path),
        timeout=300)
    sidecar_path = out_dir / f"reference-{SEQ}-{tag}.json"
    sidecar = None
    if sidecar_path.exists():
        with open(sidecar_path, encoding="utf-8") as f:
            sidecar = json.load(f)
    return p, sidecar


@pytest.fixture(scope="module")
def stub_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("f-660-1")
    engine, fxp, so = make_fake_engine(tmp)
    return tmp, engine, fxp, so


# --------------------------------------------------------- failure control
def test_control_sidecar_records_live_engine_and_inherited_inputs(stub_env):
    """The #671 control: producer run under an engine whose getVersion()
    differs from its inputs file -- the sidecar must make BOTH visible.

    On the pre-#671 producers this fails: the sidecar's engine block holds
    only the copied inputs fields and no live reading anywhere.
    """
    tmp, engine, fxp, so = stub_env
    inputs = make_inputs(tmp, fxp, "1.4.HEAD.58914e59c",
                         "model/voice/attacky_slfo_inputs.json")
    p, sidecar = run_slfo_producer(tmp, engine, inputs, "disagree")
    assert p.returncode == 0, p.stdout + p.stderr
    assert sidecar is not None, "producer wrote no sidecar"
    assert sidecar["engine"]["engine_version_string"] == STUB_VERSION, sidecar
    assert sidecar["engine"]["engine_version_string"] != \
        sidecar["inputs_engine"]["version_string"]
    assert sidecar["inputs_engine"]["version_string"] == "1.4.HEAD.58914e59c"
    assert sidecar["inputs_engine"]["commit"] == \
        json.load(inputs.open())["engine"]["commit"]


def test_agreement_still_records_both_fields(stub_env):
    """Inputs file and running engine agree: both keys still recorded."""
    tmp, engine, fxp, so = stub_env
    inputs = make_inputs(tmp, fxp, STUB_VERSION,
                         "model/voice/attacky_slfo_inputs.json")
    p, sidecar = run_slfo_producer(tmp, engine, inputs, "agree")
    assert p.returncode == 0, p.stdout + p.stderr
    assert sidecar["engine"]["engine_version_string"] == STUB_VERSION
    assert sidecar["inputs_engine"]["version_string"] == STUB_VERSION
    assert set(sidecar["engine"]) & set(sidecar["inputs_engine"]) == set()


def test_fast_variant_inputs_also_carry_the_live_block(stub_env):
    """--slfo-inputs selecting the fast variant records the live block too."""
    tmp, engine, fxp, so = stub_env
    inputs = make_inputs(tmp, fxp, "1.4.sxt037-tap.ff8b4dba4",
                         "model/voice/attacky_slfo_fast_inputs.json")
    p, sidecar = run_slfo_producer(tmp, engine, inputs, "fast")
    assert p.returncode == 0, p.stdout + p.stderr
    assert sidecar["engine"]["engine_version_string"] == STUB_VERSION
    assert sidecar["inputs_engine"]["version_string"] == \
        "1.4.sxt037-tap.ff8b4dba4"


# ------------------------------------------------------- enumeration guard
def test_committed_reports_have_no_undeclared_inherited_only_engine_block():
    """Acceptance item 1, as a guard: the inherited-only set is exactly the
    declared list. A 28th file, a removed file, or a shape change in one of
    them must land in the same change that caused it (DR-0021).
    """
    detected = ["reports/" + p
                for p in inherited_only_sidecars(REPORTS)]
    declared = sorted(sum(DETECTED_2026_11_14.values(), []))
    assert detected == declared, (
        "inherited-only engine blocks drifted from the declared list:\n"
        "+ new: %s\n- gone: %s\ndeclare any change in the same change that "
        "produced it (see tests/test_sidecar_engine_provenance.py "
        "DETECTED_2026_11_14 and decision-records/0021)"
        % (sorted(set(detected) - set(declared)),
           sorted(set(declared) - set(detected))))


def test_control_the_detector_flags_a_new_inherited_sidecar(tmp_path):
    """The guard's teeth: a synthetic Pattern-A sidecar is detected."""
    art = tmp_path / "reports" / "fake-leaf" / "artifacts"
    art.mkdir(parents=True)
    with open(art / "reference-x.json", "w", encoding="utf-8") as f:
        json.dump({"engine": {"commit": "c", "version_string": "v"}}, f)
    with open(art / "reference-live.json", "w", encoding="utf-8") as f:
        json.dump({"engine": {"engine_commit": "c",
                              "engine_version_string": "v"}}, f)
    flagged = inherited_only_sidecars(tmp_path)
    assert flagged == ["reports/fake-leaf/artifacts/reference-x.json"]
