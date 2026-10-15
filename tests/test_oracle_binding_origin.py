"""Process-isolated controls for oracle_common.import_surgepy() origin checks (#436).

Refusal cases need no external engine. The positive case compiles a tiny
original C extension named ``surgepy`` (a stand-in, NOT the Surge engine) and
is skipped when no compiler/Python.h is available; it is not a native smoke of
the real oracle. Set ORACLE_COMMON_UNDER_TEST to a path to run the same
controls against another copy of the helper (e.g. the pre-change one).
"""

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import importlib.machinery

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.environ.get("ORACLE_COMMON_UNDER_TEST", os.path.join(REPO, "oracle", "oracle_common.py"))
SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]

CHILD = r"""
import importlib.util, json, os, sys
pre = os.environ.get("PRE")
if pre:
    exec(pre)
spec = importlib.util.spec_from_file_location("oc_under_test", os.environ["HELPER"])
oc = importlib.util.module_from_spec(spec); spec.loader.exec_module(oc)
def go():
    m = oc.import_surgepy()
    out = {"result": "ACCEPTED", "file": getattr(m, "__file__", None)}
    if hasattr(oc, "binding_provenance"):
        out["prov"] = oc.binding_provenance(m)
    return out
try:
    r = go()
    post = os.environ.get("POST")
    if post:
        os.environ["ORACLE_BUILD_DIR_REL"] = post
        try:
            r2 = go()
        except Exception as e:
            r2 = {"result": "REFUSED", "err": str(e)}
        r["second"] = r2
except BaseException as e:
    r = {"result": "REFUSED", "type": type(e).__name__, "err": str(e)}
print("JSON:" + json.dumps(r))
"""


def run(tmp_path, build="b", extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env.update(HELPER=HELPER, ORACLE_SURGE_DIR=str(tmp_path / "engine"), ORACLE_BUILD_DIR_REL=build)
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, "-I", "-c", CHILD], env=env, capture_output=True,
                       text=True, cwd=str(tmp_path), timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("JSON:")]
    assert lines, p.stdout + p.stderr
    return json.loads(lines[-1][5:])


def so_dir(tmp_path, build="b"):
    d = tmp_path / "engine" / build / "src" / "surge-python"
    d.mkdir(parents=True, exist_ok=True)
    return d


def refused(r):
    assert r["result"] == "REFUSED", r
    return r


def ambient(tmp_path):
    amb = tmp_path / "amb"
    amb.mkdir(exist_ok=True)
    (amb / "surgepy.py").write_text("def createSurge(sr): raise SystemExit('ambient engine used')\n")
    return str(amb)


def test_absent_build_with_ambient_surgepy_py_refuses(tmp_path):
    pre = f"import sys; sys.path.insert(0, {ambient(tmp_path)!r})"
    refused(run(tmp_path, extra_env={"PRE": pre}))


def test_python_stub_in_expected_dir_refuses(tmp_path):
    (so_dir(tmp_path) / "surgepy.py").write_text("def createSurge(sr): return None\n")
    refused(run(tmp_path))


def test_preloaded_module_from_other_location_refuses(tmp_path):
    so_dir(tmp_path)
    (so_dir(tmp_path) / ("surgepy" + SUFFIX)).write_bytes(b"not a real elf")
    pre = f"import sys; sys.path.insert(0, {ambient(tmp_path)!r}); import surgepy"
    refused(run(tmp_path, extra_env={"PRE": pre}))


def test_forged_cached_origin_refuses(tmp_path):
    cand = so_dir(tmp_path) / ("surgepy" + SUFFIX)
    cand.write_bytes(b"not a real elf")
    pre = ("import sys, types; m = types.ModuleType('surgepy'); "
           f"m.__file__ = {str(cand)!r}; sys.modules['surgepy'] = m")
    refused(run(tmp_path, extra_env={"PRE": pre}))


def test_unloadable_native_candidate_refuses(tmp_path):
    (so_dir(tmp_path) / ("surgepy" + SUFFIX)).write_bytes(b"garbage, wrong ABI")
    refused(run(tmp_path))


def test_ambiguous_candidates_refuse(tmp_path):
    d = so_dir(tmp_path)
    (d / ("surgepy" + SUFFIX)).write_bytes(b"x")
    (d / "surgepy.cpython-399-fake.so").write_bytes(b"x")
    exts = importlib.machinery.EXTENSION_SUFFIXES
    (d / ("surgepy_b" + exts[-1])).write_bytes(b"x")
    refused(run(tmp_path))


def test_symlink_escape_refuses(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.so").write_bytes(b"x")
    os.symlink(outside / "real.so", so_dir(tmp_path) / ("surgepy" + SUFFIX))
    refused(run(tmp_path))


def _compile(tmp_path, build, marker):
    cc = shutil.which("cc") or shutil.which("gcc")
    inc = sysconfig.get_paths()["include"]
    if not cc or not os.path.exists(os.path.join(inc, "Python.h")):
        pytest.skip("NOT_RUN: no C compiler / Python.h for stand-in extension")
    src = tmp_path / f"surgepy_{build}.c"
    src.write_text(
        '#include <Python.h>\n'
        'static struct PyModuleDef m = {PyModuleDef_HEAD_INIT, "surgepy", NULL, -1, NULL};\n'
        f'PyMODINIT_FUNC PyInit_surgepy(void){{PyObject*o=PyModule_Create(&m);'
        f'PyModule_AddStringConstant(o,"MARK","{marker}");return o;}}\n')
    out = so_dir(tmp_path, build) / ("surgepy" + SUFFIX)
    r = subprocess.run([cc, "-shared", "-fPIC", f"-I{inc}", str(src), "-o", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        pytest.skip("NOT_RUN: stand-in extension failed to compile: " + r.stderr[:200])
    return out


def test_standin_native_loads_with_provenance_and_repeat(tmp_path):
    out = _compile(tmp_path, "b", "A")
    r = run(tmp_path)
    assert r["result"] == "ACCEPTED", r
    assert os.path.realpath(r["file"]) == os.path.realpath(out)
    if "prov" in r:
        import hashlib
        assert r["prov"]["module_path"] == os.path.realpath(out)
        assert r["prov"]["module_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
        assert r["prov"]["build_dir"] == os.path.realpath(tmp_path / "engine" / "b")


def test_changed_build_selection_does_not_reuse_binding(tmp_path):
    _compile(tmp_path, "b", "A")
    _compile(tmp_path, "c", "B")
    r = run(tmp_path, extra_env={"POST": "c"})
    assert r["result"] == "ACCEPTED", r
    refused(r["second"])


def test_compatible_repeat_import_supported(tmp_path):
    _compile(tmp_path, "b", "A")
    r = run(tmp_path, extra_env={"POST": "b"})
    assert r["result"] == "ACCEPTED" and r["second"]["result"] == "ACCEPTED", r
