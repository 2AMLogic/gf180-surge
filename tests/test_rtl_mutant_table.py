"""The shared copy-style RTL mutant table (#620, #623) is live and drift-tight.

tools/make_rtl_mutants.py declares each committed copy-style negative-control
mutant as "base file + optional banner + exact replacements" and gates the
committed bytes with `--check`. Since #623 it is the ONLY declaration: the
three generators that carried their own rules
(tools/compare_rtl_model_conditioner.py, tools/make_control_mutant.py,
tools/make_sxt030_mutants.py) now read this table. This module asserts:

  1. `--check` exits 0 and every one of the twenty-one committed mutants
     reproduces byte-for-byte from its base plus its declared replacements.
  2. Every declared anchor occurs in the base exactly as many times as the
     table says, and every replacement actually changes the text -- so a
     replacement that stopped anchoring is an error, never a silent no-op.
  3. The two KNOWN-DRIFT entries are exactly the two named voice mutants,
     each declaring the drift reason and the same three stale SXT-036 hunks.
     This records the drift; it makes no claim about either control's
     verdict, which only its comparator can establish.
  4. The single-line-revert property that tests/test_halfband_d2_voice.py
     asserts line-wise for rtl/voice/voice_halfband_order_mutant.sv also
     holds byte-exactly through the table (that bespoke check is kept: its
     file's bytes are attested in signoff/t1-item9-attestation.json, so
     removing it belongs in the change that re-derives that envelope).
  5. The fold itself (#623): the five absorbed entries declare the `strip`
     composition shape (a banner ending in its own `timescale line + the
     base with that line removed) and reproduce their committed bytes
     through it; the three folded generators are views onto this table, not
     second definitions; and no tools/*.py other than make_rtl_mutants.py
     contains a declared mutation anchor at all.

  6. Failure controls: editing one line of a base without regenerating makes
     `--check` exit non-zero and name the affected mutants -- including each
     base absorbed in #623 -- and a declared anchor that no longer occurs
     (a mutation site, or a `strip` line) raises instead of silently doing
     nothing.

Coverage only: nothing here runs a simulator or a comparator, so this module
establishes no RTL-vs-model exactness claim and no negative-control verdict.
"""

import contextlib
import glob
import importlib.util
import io
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools import make_rtl_mutants as mk  # noqa: E402

SCRIPT = os.path.join(REPO, "tools", "make_rtl_mutants.py")
DRIFTED = ("rtl/voice/voice_broken_mutant.sv", "rtl/voice/voice_uni_mutant.sv")
HALFBAND = "rtl/voice/voice_halfband_order_mutant.sv"
CONDITIONER = (
    "rtl/effects/type-conditioner/tb_conditioner_mutant_shared.sv",
    "rtl/effects/type-conditioner/tb_conditioner_mutant_nolimiter.sv",
)
CONTROL = "rtl/control/control_broken_mutant.sv"
SXT030 = tuple(sorted(
    p for p, spec in mk.MUTANTS.items() if spec["base"] == mk.EXT_MEM_BASE))
# the five entries absorbed in #623 -- exactly those in the `strip` shape
STRIP = (CONTROL,) + SXT030
# every base a #623 entry mutates -> the mutants that must go STALE with it
ABSORBED_BASES = {}
for _p in STRIP + CONDITIONER:
    ABSORBED_BASES.setdefault(mk.MUTANTS[_p]["base"], []).append(_p)


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------- 1. the committed bytes
def test_check_mode_exits_zero_on_the_committed_tree():
    r = subprocess.run([sys.executable, SCRIPT, "--check"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STALE:" not in r.stdout
    assert "%d/%d" % (len(mk.MUTANTS), len(mk.MUTANTS)) in r.stdout


@pytest.mark.parametrize("path", sorted(mk.MUTANTS))
def test_committed_mutant_reproduces_from_its_base(path):
    assert os.path.exists(os.path.join(REPO, path)), path
    assert _read(path) == mk.render(path), path


def test_table_covers_the_twenty_one_committed_mutants():
    """16 copy-style (#620) + the four SXT-030 and the SXT-021 control
    absorbed in #623. Scope guard: the multi-mutant modules and reverb1 are
    NOT copies of one base file and are deliberately absent (#620 'Out of
    scope')."""
    assert len(mk.MUTANTS) == 21
    assert len(STRIP) == 5 and CONTROL in mk.MUTANTS
    assert len(SXT030) == 4
    for excluded in ("rtl/effects/aw-4/logical4_mutants.sv",
                     "rtl/effects/reverb1/reverb1_broken_mutant.sv",
                     "rtl/effects/rf-rf-global34/rf_global34_mutants.sv"):
        assert excluded not in mk.MUTANTS
    for path, spec in mk.MUTANTS.items():
        assert os.path.exists(os.path.join(REPO, spec["base"])), path
        assert spec["base"] != path


def test_list_mode_names_every_entry():
    r = subprocess.run([sys.executable, SCRIPT, "--list"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    for path, spec in mk.MUTANTS.items():
        assert path in r.stdout
        assert spec["exercised_by"] in r.stdout


# --------------------------------------------- 2. the anchors are declared
@pytest.mark.parametrize("path", sorted(mk.MUTANTS))
def test_declared_anchors_occur_exactly_as_many_times_as_declared(path):
    spec = mk.MUTANTS[path]
    base = _read(spec["base"])
    for rep in mk.replacements(spec):
        old, new = rep[0], rep[1]
        want = rep[2] if len(rep) > 2 else 1
        assert base.count(old) == want, (path, old[:60])
        assert old != new, (path, old[:60])
    # the mutant is genuinely a mutation of its base, not a copy of it
    assert mk.render(path, base) != base
    assert mk.render(path, base) != spec.get("prefix", "") + base


@pytest.mark.parametrize("path", sorted(mk.MUTANTS))
def test_committed_mutant_carries_its_targeted_mutation(path):
    """Each targeted mutation's replacement text is in the committed file."""
    mutant = _read(path)
    for rep in mk.MUTANTS[path]["mutation"]:
        assert rep[1] in mutant, (path, rep[1][:60])


# ------------------------------------------------------- 3. known drift
def test_known_drift_is_exactly_the_two_named_voice_mutants():
    assert mk.DRIFTED == tuple(sorted(DRIFTED))
    for path in DRIFTED:
        spec = mk.MUTANTS[path]
        assert spec["base"] == "rtl/voice/tb_voice.sv"
        assert spec["stale"] == mk.SXT036_STALE
        assert len(spec["stale"]) == 3
        assert "SXT-036" in spec["drift"]
    for path, spec in mk.MUTANTS.items():
        if path not in DRIFTED:
            assert not spec.get("stale"), path
            assert "drift" not in spec, path


def test_check_mode_reports_the_known_drift_by_name():
    r = subprocess.run([sys.executable, SCRIPT, "--check"],
                       capture_output=True, text=True, cwd=REPO)
    for path in DRIFTED:
        assert "KNOWN-DRIFT: %s" % path in r.stdout
    assert "2 declared known-drift" in r.stdout


def test_the_stale_hunks_are_reverts_of_logic_the_base_still_has():
    """The bounded finding itself: the base carries the SXT-036 gain-anchor
    logic that both drifted copies drop."""
    base = _read("rtl/voice/tb_voice.sv")
    base_lines = base.splitlines(True)
    for old, new in mk.SXT036_STALE:
        assert old in base, "the base no longer carries this SXT-036 text"
        # the reverted form is not a line of the base (it is a substring of
        # the base's wider `else prev_gain[s] = ...` line, so compare lines)
        for line in new.splitlines(True):
            assert line not in base_lines, line
    for path in DRIFTED:
        mutant = _read(path)
        for old, new in mk.SXT036_STALE:
            assert new in mutant, path
            assert old not in mutant, path


# ------------------------------- 4. the halfband single-line-revert property
def test_halfband_order_mutant_is_a_single_line_revert_of_tb_voice():
    """The same property tests/test_halfband_d2_voice.py asserts line-wise
    (#123) -- the control must differ from tb_voice.sv only in the branch
    order plus its own banner, since a control that changed two things would
    not isolate the thing it targets -- here byte-exactly, via the table."""
    spec = mk.MUTANTS[HALFBAND]
    assert spec["base"] == "rtl/voice/tb_voice.sv"
    assert not spec.get("stale")
    assert len(spec["mutation"]) == 1
    old, new = spec["mutation"][0]
    assert old == "      bl = qround1(chainb[2*k] + chaina[2*k+1]);\n"
    assert new == "      bl = qround1(chaina[2*k] + chainb[2*k+1]);\n"
    banner = spec["prefix"]
    assert banner.count("\n") == 4 and banner.endswith("\n")
    committed = _read(HALFBAND)
    base = _read("rtl/voice/tb_voice.sv")
    assert committed == banner + base.replace(old, new, 1)
    body = committed.splitlines(True)[4:]
    assert len(body) == len(base.splitlines(True))
    assert [(a, b) for a, b in zip(base.splitlines(True), body)
            if a != b] == [(old, new)]


# ------------------------------- 5. the fold: one declaration, three views
def _conditioner_module():
    for p in (REPO, os.path.join(REPO, "tools"),
              os.path.join(REPO, "model", "effects", "type-conditioner")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "_cond_cmp", os.path.join(REPO, "tools",
                                  "compare_rtl_model_conditioner.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("path", STRIP)
def test_absorbed_entry_uses_the_strip_composition_shape(path):
    """#623's shape: the banner ends in its own `timescale line and the base's
    own timescale line is removed from the body. Asserted against the
    committed bytes, independently of the table's own render()."""
    spec = mk.MUTANTS[path]
    assert spec["strip"] == [mk.TIMESCALE]
    assert spec["prefix"].endswith(mk.TIMESCALE)
    base = _read(spec["base"])
    assert base.count(mk.TIMESCALE) == 1
    committed = _read(path)
    assert committed.count(mk.TIMESCALE) == 1
    assert committed.startswith(spec["prefix"])
    body = mk.apply_replacements(base.replace(mk.TIMESCALE, "", 1),
                                 list(spec["mutation"]), path)
    assert committed == spec["prefix"] + body


def test_only_the_absorbed_entries_declare_a_strip():
    """The other sixteen are the plain shape and must stay that way."""
    for path, spec in mk.MUTANTS.items():
        if path not in STRIP:
            assert "strip" not in spec, path


def test_no_other_generator_declares_a_mutation_rule():
    """The acceptance criterion of #623: no file defines a mutation rule for
    a mutant the shared table also declares. Scanned over tools/*.py, where
    the generators live -- a hit means a second definition came back."""
    for py in sorted(glob.glob(os.path.join(REPO, "tools", "*.py"))):
        if os.path.basename(py) == "make_rtl_mutants.py":
            continue
        with open(py, encoding="utf-8") as f:
            text = f.read()
        for path, spec in mk.MUTANTS.items():
            for rep in spec["mutation"]:
                for literal in (rep[0].strip("\n"), rep[1].strip("\n")):
                    if literal:
                        assert literal not in text, \
                            (os.path.relpath(py, REPO), path, literal[:60])


def test_conditioner_comparator_delegates_to_the_shared_table():
    """Before #623 the comparator rewrote both mutants on every run from its
    own private replacement list, so whichever ran last decided what the
    committed control contained. It must now return exactly the table's two
    files and leave their committed bytes untouched."""
    mod = _conditioner_module()
    assert not hasattr(mod, "make_mutant"), \
        "the comparator's private mutation rule is back"
    before = {p: _read(p) for p in CONDITIONER}
    try:
        paths = mod.mutants()
        assert sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                      for p in paths.values()) == sorted(CONDITIONER)
        for path in CONDITIONER:
            assert _read(path) == mk.render(path), path
            assert _read(path) == before[path], \
                "%s: the comparator rewrote the committed bytes" % path
    finally:
        for path, text in before.items():
            if _read(path) != text:
                with open(os.path.join(REPO, path), "w",
                          encoding="utf-8") as f:
                    f.write(text)


def test_sxt030_generator_is_a_view_onto_the_shared_table():
    """tests/test_sxt030_stall_instrumentation.py (attested, unedited) uses
    MUTANTS / render / RTL_DIR / HOLD / COUNT / LATCH, so the shim must keep
    them -- derived from the table, never re-declared."""
    from tools import make_sxt030_mutants as s30
    assert sorted(s30.MUTANTS) == sorted(os.path.basename(p) for p in SXT030)
    assert (s30.HOLD, s30.COUNT, s30.LATCH) == (
        mk.EXT_MEM_HOLD, mk.EXT_MEM_COUNT, mk.EXT_MEM_LATCH)
    assert s30.RTL_DIR == os.path.join(REPO, mk.EXT_MEM_DIR)
    src = _read(mk.EXT_MEM_BASE)
    for name, spec in s30.MUTANTS.items():
        shared = mk.MUTANTS[s30.PATHS[name]]
        assert spec["replacements"] == list(shared["mutation"]), name
        assert spec["must"] == shared["must"]
        assert s30.render(name, src) == mk.render(s30.PATHS[name], src)
        assert s30.render(name) == _read(s30.PATHS[name]), name
    r = subprocess.run([sys.executable,
                        os.path.join(REPO, "tools", "make_sxt030_mutants.py"),
                        "--check"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STALE:" not in r.stdout


def test_control_generator_is_a_view_onto_the_shared_table():
    """#623 Work step 2, decided: keep the control mutant's banner verbatim
    (zero byte change, gains the --check gate it never had) and make the
    generator a shim. Running it stays a no-op against the committed file."""
    from tools import make_control_mutant as mc
    assert mc.MUTANT == CONTROL
    assert mc.HEADER == mk.MUTANTS[CONTROL]["prefix"]
    assert "Regenerate with: python3 tools/make_control_mutant.py" in mc.HEADER
    assert mc.DST == os.path.join(REPO, CONTROL)
    before = _read(CONTROL)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mc.main()
    assert "already up to date" in out.getvalue(), out.getvalue()
    assert _read(CONTROL) == before


# ------------------------------------------------- 6. failure controls
def _scratch_repo(tmp_path):
    """A minimal copy of the tree the script needs: itself plus every base
    and mutant file, at the same relative paths."""
    root = tmp_path / "repo"
    rels = {"tools/make_rtl_mutants.py"}
    for path, spec in mk.MUTANTS.items():
        rels.add(path)
        rels.add(spec["base"])
    for rel in rels:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(REPO, rel), dst)
    return root


def _check(root):
    return subprocess.run(
        [sys.executable, str(root / "tools" / "make_rtl_mutants.py"), "--check"],
        capture_output=True, text=True)


def test_failure_control_one_edited_base_line_makes_check_fail(tmp_path):
    """The control this gate exists for: a base testbench edited without
    regenerating its mutants must make `--check` exit non-zero."""
    root = _scratch_repo(tmp_path)
    healthy = _check(root)
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr

    base = root / "rtl" / "voice" / "tb_lp12.sv"
    text = base.read_text(encoding="utf-8")
    edited = text.replace("    qmul_count++;\n",
                          "    qmul_count++;   // drifting edit\n", 1)
    assert edited != text, "the control's own edit did not apply"
    base.write_text(edited, encoding="utf-8")

    r = _check(root)
    assert r.returncode != 0, r.stdout
    assert "STALE: rtl/voice/lp12_broken_mutant.sv" in r.stdout
    assert "20/21" in r.stdout


def test_failure_control_an_edited_mutant_also_makes_check_fail(tmp_path):
    """The other direction: hand-editing the committed mutant itself."""
    root = _scratch_repo(tmp_path)
    mutant = root / "rtl" / "oscillators" / "sine" / "sine_broken_mutant.sv"
    mutant.write_text(mutant.read_text(encoding="utf-8") + "// hand edit\n",
                      encoding="utf-8")
    r = _check(root)
    assert r.returncode != 0, r.stdout
    assert "STALE: rtl/oscillators/sine/sine_broken_mutant.sv" in r.stdout


@pytest.mark.parametrize("base", sorted(ABSORBED_BASES))
def test_failure_control_each_absorbed_base_is_gated(tmp_path, base):
    """#623's own failure control: a one-line edit to a base absorbed by the
    fold, without regenerating, must make `--check` exit non-zero and name
    every mutant that depends on it. Before the fold neither
    rtl/control/control_top.sv nor the two conditioner mutants had such a
    gate at all."""
    root = _scratch_repo(tmp_path)
    healthy = _check(root)
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr

    f = root / base
    text = f.read_text(encoding="utf-8")
    edited = text.replace("\nendmodule", "\n  // drifting edit\nendmodule", 1)
    assert edited != text, "the control's own edit did not apply"
    f.write_text(edited, encoding="utf-8")

    r = _check(root)
    assert r.returncode != 0, r.stdout
    for path in ABSORBED_BASES[base]:
        assert "STALE: %s" % path in r.stdout, r.stdout
    assert "%d/21" % (21 - len(ABSORBED_BASES[base])) in r.stdout


def test_failure_control_a_lost_strip_anchor_raises():
    """The `strip` line is anchored like any mutation: a base that lost its
    timescale line is an error, not a mutant silently gaining a second one
    (the banner already carries it)."""
    base = _read(mk.EXT_MEM_BASE)
    gone = base.replace(mk.TIMESCALE, "", 1)
    assert gone != base
    for path in STRIP:
        if mk.MUTANTS[path]["base"] != mk.EXT_MEM_BASE:
            continue
        with pytest.raises(ValueError) as e:
            mk.render(path, gone)
        assert "occurs 0 times" in str(e.value)


def test_failure_control_a_lost_anchor_raises_instead_of_no_op():
    """A replacement whose `old` no longer occurs must be an error, not a
    silent no-op that would quietly un-mutate the control."""
    base = _read("rtl/voice/tb_lp12.sv")
    gone = base.replace("    r = (p + (64'sd1 << 20)) >>> 21;\n", "", 1)
    assert gone != base
    with pytest.raises(ValueError) as e:
        mk.render("rtl/voice/lp12_broken_mutant.sv", gone)
    assert "occurs 0 times" in str(e.value)


def test_failure_control_a_duplicated_anchor_raises():
    """A count-pinned anchor that gained a site must be reported, not pooled
    silently (the conditioner entry's counts)."""
    base = _read("rtl/effects/type-conditioner/tb_conditioner.sv")
    extra = base + "// bufpos[inst]\n"
    with pytest.raises(ValueError) as e:
        mk.render(
            "rtl/effects/type-conditioner/tb_conditioner_mutant_shared.sv",
            extra)
    assert "expected 4" in str(e.value)
