"""The shared copy-style RTL mutant table (#620) is live and drift-tight.

tools/make_rtl_mutants.py declares each committed copy-style negative-control
mutant as "base file + optional banner + exact replacements" and gates the
committed bytes with `--check`. This module asserts:

  1. `--check` exits 0 and every one of the sixteen committed mutants
     reproduces byte-for-byte from its base plus its declared replacements.
  2. Every declared anchor occurs in the base exactly as many times as the
     table says, and every replacement actually changes the text -- so a
     replacement that stopped anchoring is an error, never a silent no-op.
  3. No entry declares drift (#622 regenerated the two that did), `--check`
     says so, and the two rtl/voice/tb_voice.sv copies that carried the
     drift are each base + exactly their one targeted replacement -- with
     the SXT-036 gain-anchor logic their stale bytes used to revert now
     present in both. This records the file contents; it makes no claim
     about either control's verdict, which only its comparator can
     establish (reports/voice-mutant-regeneration/ holds those).
  4. The single-line-revert property that tests/test_halfband_d2_voice.py
     asserts line-wise for rtl/voice/voice_halfband_order_mutant.sv also
     holds byte-exactly through the table (that bespoke check is kept: its
     file's bytes are attested in signoff/t1-item9-attestation.json, so
     removing it belongs in the change that re-derives that envelope).
  5. tools/compare_rtl_model_conditioner.py still carries its own private
     copy of the two conditioner mutants' replacement rules (its bytes are
     attested, so it is not edited here) -- so this module asserts the two
     definitions agree byte-for-byte and cannot silently diverge.

  6. Failure controls: editing one line of a base without regenerating makes
     `--check` exit non-zero and name the affected mutants, and a declared
     anchor that no longer occurs raises instead of silently doing nothing.

Coverage only: nothing here runs a simulator or a comparator, so this module
establishes no RTL-vs-model exactness claim and no negative-control verdict.
"""

import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools import make_rtl_mutants as mk  # noqa: E402

SCRIPT = os.path.join(REPO, "tools", "make_rtl_mutants.py")
VOICE_MUTANTS = ("rtl/voice/voice_broken_mutant.sv",
                 "rtl/voice/voice_uni_mutant.sv")
# The three hunks the two VOICE_MUTANTS used to revert (#620's declared
# drift, removed by #622): the base's SXT-036 constructor gain-anchor
# branch and the two control-word comments that describe it. Spelled out
# here, not imported, so the table cannot re-declare the drift and still
# satisfy this module.
SXT036_TEXT = (
    "  //          b4 ctor gain anchor streamed in word 37 -- SXT-036)\n",
    "  //  37 ctor gain anchor (iff flags b4; SXT-036)  38..39 reserved\n",
    "    if (cw[0][4]) prev_gain[s] = 32'(cw[37]);\n",
)
HALFBAND = "rtl/voice/voice_halfband_order_mutant.sv"
CONDITIONER = (
    "rtl/effects/type-conditioner/tb_conditioner_mutant_shared.sv",
    "rtl/effects/type-conditioner/tb_conditioner_mutant_nolimiter.sv",
)


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


def test_table_covers_the_sixteen_copy_style_mutants():
    """Scope guard: the multi-mutant modules and reverb1 are NOT copies of one
    base file and are deliberately absent (#620 'Out of scope')."""
    assert len(mk.MUTANTS) == 16
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


# ------------------------------------------------- 3. the drift is gone
def test_no_entry_declares_drift():
    """#620 declared the two voice mutants' SXT-036 drift so it was reported
    rather than hidden; #622 regenerated them. A declared-drift entry is a
    bounded finding, not a resting state -- re-declaring one has to be a
    visible change here, not a silent table edit."""
    assert mk.DRIFTED == ()
    for path, spec in mk.MUTANTS.items():
        assert not spec.get("stale"), path
        assert "drift" not in spec, path


def test_check_mode_reports_zero_known_drift():
    r = subprocess.run([sys.executable, SCRIPT, "--check"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 declared known-drift" in r.stdout
    assert "KNOWN-DRIFT:" not in r.stdout


@pytest.mark.parametrize("path", VOICE_MUTANTS)
def test_voice_mutant_is_its_one_targeted_replacement_of_tb_voice(path):
    """Byte-exact minimality: each control differs from the testbench it
    mutates by exactly its targeted line and nothing else, so a FAIL is
    attributable to that line. This is the property the stale hunks broke."""
    spec = mk.MUTANTS[path]
    assert spec["base"] == "rtl/voice/tb_voice.sv"
    assert not spec.get("stale")
    assert "prefix" not in spec
    assert len(spec["mutation"]) == 1
    old, new = spec["mutation"][0]
    base = _read("rtl/voice/tb_voice.sv")
    committed = _read(path)
    assert committed == base.replace(old, new, 1)
    base_lines = base.splitlines(True)
    mutant_lines = committed.splitlines(True)
    assert len(mutant_lines) == len(base_lines)
    differing = [(a, b) for a, b in zip(base_lines, mutant_lines) if a != b]
    assert differing == [(ol, nl) for ol, nl
                         in zip(old.splitlines(True), new.splitlines(True))
                         if ol != nl]
    assert len(differing) == 1


@pytest.mark.parametrize("path", VOICE_MUTANTS)
def test_voice_mutant_carries_the_bases_sxt036_gain_anchor_logic(path):
    """The specific regression #622 closed: both copies used to revert the
    base's SXT-036 constructor gain-anchor branch. Keyed on the real text so
    the drift cannot come back unnoticed."""
    base = _read("rtl/voice/tb_voice.sv")
    mutant = _read(path)
    for text in SXT036_TEXT:
        assert text in base, "the base no longer carries this SXT-036 text"
        assert text in mutant, (path, text[:60])


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


# --------------------------------- 5. the conditioner comparator delegates
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


def test_conditioner_comparators_own_rule_agrees_with_the_shared_table():
    """The comparator writes these two mutants itself, from its own private
    replacement list; its bytes are attested, so it is not edited here. The
    two definitions must then produce identical files -- otherwise whichever
    ran last would decide what the committed control contains."""
    mod = _conditioner_module()
    before = {p: _read(p) for p in CONDITIONER}
    try:
        paths = mod.mutants()
        assert sorted(os.path.relpath(p, REPO).replace(os.sep, "/")
                      for p in paths.values()) == sorted(CONDITIONER)
        for path in CONDITIONER:
            assert _read(path) == mk.render(path), \
                "%s: the comparator and the shared table disagree" % path
            assert _read(path) == before[path], \
                "%s: the comparator rewrote the committed bytes" % path
    finally:
        for path, text in before.items():
            if _read(path) != text:
                with open(os.path.join(REPO, path), "w",
                          encoding="utf-8") as f:
                    f.write(text)


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
    assert "15/16" in r.stdout


def test_failure_control_an_edited_mutant_also_makes_check_fail(tmp_path):
    """The other direction: hand-editing the committed mutant itself."""
    root = _scratch_repo(tmp_path)
    mutant = root / "rtl" / "oscillators" / "sine" / "sine_broken_mutant.sv"
    mutant.write_text(mutant.read_text(encoding="utf-8") + "// hand edit\n",
                      encoding="utf-8")
    r = _check(root)
    assert r.returncode != 0, r.stdout
    assert "STALE: rtl/oscillators/sine/sine_broken_mutant.sv" in r.stdout


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
