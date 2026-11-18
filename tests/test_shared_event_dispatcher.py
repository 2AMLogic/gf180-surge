#!/usr/bin/env python3
"""#640: every oracle renderer dispatches events through ONE dispatcher.

PINS, with a recording stub synthesizer and no engine:

  1. `fixtures/render_fixture.dispatch`, read from the committed bytes of the
     byte-frozen file itself, forwards all five event types it claims to --
     note_on, note_off WITH its declared velocity, cc, pitch_bend,
     channel_pressure -- and ignores `tempo` (surgepy cannot apply it).
  2. FAILURE CONTROL: a deliberately lossy dispatcher (the pre-#640 body of
     `fixtures/render_slfo_fixture.py` -- drops pitch_bend and
     channel_pressure, hard-codes note_off velocity 0) FAILS check 1.
  3. The renderers folded onto the shared dispatcher call it and keep no
     private per-event dispatch of their own.
  4. The two files NOT folded are exactly the two with a recorded reason, and
     neither silently drops an event type it does not forward.

DOES NOT: run the pinned oracle, render audio, re-derive any committed
reference, or say anything about model-vs-reference agreement.  Checks 3 and 4
are source-level pins; check 1 and 2 are behavioural.
"""

import ast
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join("fixtures", "render_fixture.py")

# The nine private copies issue #640 names, and their disposition.
FOLDED = (
    "fixtures/render_lfo_fixture.py",
    "fixtures/render_mw_fixture.py",
    "model/voice/render_uni_reference.py",
    "tools/_render_reference_common.py",
    "tools/render_lp12_reference.py",
    "tools/render_pm_reference.py",
    "tools/render_wt_reference.py",
)
# path -> why it still carries its own note dispatch.  Keep this table and the
# reasons in step with docs/byte-frozen-sources.json; a file leaving the table
# must be folded, and a file entering it needs a reason recorded here.
EXEMPT = {
    "fixtures/render_slfo_fixture.py": (
        "stop condition: the six reports/SXT-041/artifacts/reference-*.json "
        "sidecars stamp this file's current bytes, so folding it is only "
        "valid in a change that re-renders them under the pinned oracle"
    ),
    "tools/render_lp24_tap_reference.py": (
        "importing fixtures/render_fixture.py enforces the manifest-pinned "
        "interpreter; this tool's interpreter must stay the one its external "
        "--engine-dir surgepy module was built for.  It REFUSES a non-note "
        "event instead of forwarding or dropping it"
    ),
}


def _src(rel):
    with open(os.path.join(REPO, rel), "r", encoding="utf-8") as f:
        return f.read()


def _func_source(rel, name):
    """Source of one top-level function, taken from the file's own bytes."""
    tree = ast.parse(_src(rel))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(_src(rel), node)
    raise AssertionError(f"{rel} has no top-level def {name}")


def shared_dispatch():
    """`dispatch` from the committed bytes of fixtures/render_fixture.py.

    Compiled in isolation on purpose: the function is pure (it touches only
    its four arguments), while importing the module would pull in the
    ABI-specific numpy the pinned oracle build needs and this test does not.
    """
    ns = {}
    exec(compile(_func_source(SHARED, "dispatch"), SHARED, "exec"), ns)
    return ns["dispatch"]


def lossy_dispatch_control(s, events, block, quant):
    """FAILURE CONTROL -- the pre-#640 private copy, verbatim in behaviour.

    This is what `fixtures/render_slfo_fixture.py` line 155-163 did on main at
    a18de1b: note_on / note_off / cc only, and note_off velocity hard-coded to
    0 regardless of what the sequence declares.
    """
    i = 0
    while i < len(events) and quant(events[i]["t"]) <= block:
        e = events[i]
        if e["type"] == "note_on":
            s.playNote(e["channel"], e["note"], e["velocity"], 0)
        elif e["type"] == "note_off":
            s.releaseNote(e["channel"], e["note"], 0)
        elif e["type"] == "cc":
            s.channelController(e["channel"], e["controller"], e["value"])
        i += 1
    return i


class RecordingSynth:
    """Records the event-facing surgepy calls a dispatcher makes, in order."""

    def __init__(self):
        self.calls = []

    def playNote(self, ch, note, vel, detune):
        self.calls.append(("playNote", ch, note, vel, detune))

    def releaseNote(self, ch, note, vel):
        self.calls.append(("releaseNote", ch, note, vel))

    def channelController(self, ch, cc, value):
        self.calls.append(("channelController", ch, cc, value))

    def pitchBend(self, ch, value):
        self.calls.append(("pitchBend", ch, value))

    def channelAftertouch(self, ch, value):
        self.calls.append(("channelAftertouch", ch, value))


# One sequence carrying every event type the shared loader admits, including a
# NONZERO note_off velocity (the case reports/SXT-041 and reports/sxt-032 each
# rendered as 0) and a `tempo` event (no surgepy call exists for it).
ALL_TYPES_EVENTS = [
    {"type": "note_on", "channel": 0, "note": 60, "velocity": 100, "t": 0},
    {"type": "cc", "channel": 0, "controller": 1, "value": 64, "t": 10},
    {"type": "pitch_bend", "channel": 0, "value": -4096, "t": 20},
    {"type": "channel_pressure", "channel": 0, "value": 77, "t": 30},
    {"type": "tempo", "bpm": 140, "t": 40},
    {"type": "note_off", "channel": 0, "note": 60, "velocity": 100, "t": 50},
]

EXPECTED_CALLS = [
    ("playNote", 0, 60, 100, 0),
    ("channelController", 0, 1, 64),
    ("pitchBend", 0, -4096),
    ("channelAftertouch", 0, 77),
    ("releaseNote", 0, 60, 100),
]


def _drive(dispatch, events, block=10 ** 9):
    """Run `dispatch` once with t==block identity quantization."""
    s = RecordingSynth()
    consumed = dispatch(s, events, block, lambda t: t)
    return s.calls, consumed


# --------------------------------------------------------------- behaviour ---

def test_shared_dispatcher_forwards_all_five_event_types():
    calls, consumed = _drive(shared_dispatch(), ALL_TYPES_EVENTS)
    assert calls == EXPECTED_CALLS
    assert consumed == len(ALL_TYPES_EVENTS)      # tempo consumed, not played


def test_shared_dispatcher_defaults_only_note_off_velocity():
    """note_off velocity defaults to 0; a note_on without one is an error.

    "Surface, do not default": three of the folded copies read
    `e.get("velocity", 100)` on note_on, so folding them turns a sequence with
    no declared attack velocity into a visible KeyError instead of a silent
    100.  No sequence under fixtures/sequences/ relies on either default.
    """
    dispatch = shared_dispatch()
    calls, _ = _drive(dispatch, [
        {"type": "note_on", "channel": 0, "note": 60, "velocity": 1, "t": 0},
        {"type": "note_off", "channel": 0, "note": 60, "t": 1},
    ])
    assert calls[-1] == ("releaseNote", 0, 60, 0)
    with pytest.raises(KeyError):
        _drive(dispatch, [{"type": "note_on", "channel": 0, "note": 60, "t": 0}])


def test_shared_dispatcher_stops_at_the_block_boundary():
    calls, consumed = _drive(shared_dispatch(), ALL_TYPES_EVENTS, block=20)
    assert consumed == 3
    assert calls == EXPECTED_CALLS[:3]


def test_failure_control_lossy_dispatcher_does_not_forward_all_five():
    """REQUIRED FAILURE CONTROL: the pre-#640 copy must FAIL the check above."""
    calls, consumed = _drive(lossy_dispatch_control, ALL_TYPES_EVENTS)
    assert calls != EXPECTED_CALLS, (
        "the lossy control matched the shared dispatcher; it can no longer "
        "demonstrate the drift #640 removed"
    )
    # and name the three specific losses, so the control cannot rot into
    # passing for an unrelated reason
    assert ("pitchBend", 0, -4096) not in calls
    assert ("channelAftertouch", 0, 77) not in calls
    assert ("releaseNote", 0, 60, 0) in calls        # declared 100, sent 0
    assert consumed == len(ALL_TYPES_EVENTS)


# ------------------------------------------------------------------ source ---

def _dispatch_call_names(rel):
    """Every `<something>.dispatch(...)` callee attribute chain in the file."""
    names = []
    for node in ast.walk(ast.parse(_src(rel))):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "dispatch":
                names.append(fn.attr)
            elif isinstance(fn, ast.Name) and fn.id == "dispatch":
                names.append(fn.id)
    return names


# `playNote` / `releaseNote` are the marker of a private note dispatch: they
# appear in a dispatch loop and nowhere else.  pitchBend / channelController /
# channelAftertouch deliberately are NOT markers -- the RESET policy every
# renderer implements calls all three on a fresh instance (bend 0, CC64/CC1/
# CC11 0, pressure 0), which is not event dispatch.
NOTE_DISPATCH_API = ("playNote", "releaseNote")


def _event_api_calls(rel):
    """Note-dispatch surgepy calls in the file -- the mark of a private copy."""
    found = set()
    for node in ast.walk(ast.parse(_src(rel))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in NOTE_DISPATCH_API:
                found.add(node.func.attr)
    return found


@pytest.mark.parametrize("rel", FOLDED)
def test_folded_renderer_calls_the_shared_dispatcher(rel):
    assert _dispatch_call_names(rel), (
        f"{rel} no longer calls a shared dispatch(); #640 folded it onto "
        f"{SHARED}"
    )
    assert "render_fixture" in _src(rel), (
        f"{rel} must resolve its dispatcher from {SHARED}"
    )


@pytest.mark.parametrize("rel", FOLDED)
def test_folded_renderer_keeps_no_private_event_dispatch(rel):
    assert _event_api_calls(rel) == set(), (
        f"{rel} calls the per-event surgepy API directly again: "
        f"{sorted(_event_api_calls(rel))}.  #640 removed that private copy; "
        f"route the events through {SHARED}'s dispatch instead."
    )


def test_exempt_renderers_are_exactly_the_documented_set():
    """The only files still carrying a private note dispatch are the two with
    a recorded reason.  Folding one without updating EXEMPT fails here, and so
    does regressing a folded file back to a private copy."""
    private = {rel for rel in tuple(EXEMPT) + FOLDED
               if "playNote" in _event_api_calls(rel)}
    assert private == set(EXEMPT), (
        f"private note dispatch found in {sorted(private)}, expected exactly "
        f"{sorted(EXEMPT)}"
    )
    for rel, reason in EXEMPT.items():
        assert reason.strip(), f"{rel} needs a recorded reason"


def test_lp24_refuses_non_note_events_instead_of_dropping_them():
    """The one exempt renderer that is NOT pending a re-render must surface an
    event type it does not forward, not filter it away."""
    import importlib.util

    rel = "tools/render_lp24_tap_reference.py"
    spec = importlib.util.spec_from_file_location(
        "lp24_tap_tool_for_dispatch_test", os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.non_note_event_types({"events": ALL_TYPES_EVENTS}) == [
        "cc", "channel_pressure", "pitch_bend", "tempo"]
    notes_only = [e for e in ALL_TYPES_EVENTS
                  if e["type"] in ("note_on", "note_off")]
    assert mod.non_note_event_types({"events": notes_only}) == []


def test_slfo_exemption_still_describes_the_file():
    """The stop-condition exemption is real: the SLFO copy still zeroes the
    release velocity its cited sequence declares.  Remove this assertion only
    in the change that re-renders the SXT-041 references."""
    src = _src("fixtures/render_slfo_fixture.py")
    assert 's.releaseNote(e["channel"], e["note"], 0)' in src, (
        "fixtures/render_slfo_fixture.py no longer hard-codes release "
        "velocity 0 -- drop it from EXEMPT and re-derive the six "
        "reports/SXT-041/artifacts/reference-*.json sidecars"
    )


# ------------------------------------------------- bounded finding (#640) ---
# reports/tooling-oracle-dispatcher-fold/EVIDENCE.md records a PROVENANCE
# mismatch: two committed reference sidecars cite a sequence whose declared
# release velocity their renderer sent as 0.  Nothing here re-renders, re-grades
# or relabels those records -- these assertions only keep the finding's factual
# basis from rotting while it waits for a human ruling.

RELEASE_VELOCITY_FINDING = {
    # sidecar -> (sequence id, the renderer it was rendered through)
    "reports/sxt-032/artifacts/reference-seq-notes-holds-v1.json":
        ("seq-notes-holds-v1", "fixtures/render_lfo_fixture.py"),
    "reports/SXT-041/artifacts/reference-seq-notes-holds-v1-slfo-fixture.json":
        ("seq-notes-holds-v1", "fixtures/render_slfo_fixture.py"),
}
HOLDS_SEQ = "fixtures/sequences/seq-notes-holds-v1.json"


def test_nonzero_release_velocity_is_still_unique_to_one_sequence():
    """The finding's premise: exactly one committed sequence declares one."""
    import glob
    import json as _json

    nonzero = {}
    for p in sorted(glob.glob(os.path.join(REPO, "fixtures", "sequences", "*.json"))):
        with open(p, encoding="utf-8") as f:
            seq = _json.load(f)
        vels = sorted({e.get("velocity", 0) for e in seq["events"]
                       if e["type"] == "note_off"} - {0})
        if vels:
            nonzero[os.path.relpath(p, REPO).replace(os.sep, "/")] = vels
    assert nonzero == {HOLDS_SEQ: [100]}, (
        "the release-velocity finding was scoped to seq-notes-holds-v1 alone; "
        f"nonzero release velocities now appear in {sorted(nonzero)}"
    )


@pytest.mark.parametrize("sidecar", sorted(RELEASE_VELOCITY_FINDING))
def test_finding_sidecar_still_cites_the_sequence_it_was_graded_against(sidecar):
    import json as _json

    seq_id, _renderer = RELEASE_VELOCITY_FINDING[sidecar]
    with open(os.path.join(REPO, sidecar), encoding="utf-8") as f:
        rec = _json.load(f)
    assert rec["sequence"]["id"] == seq_id
    # the cited sequence file is unchanged, so the mismatch is still live
    import hashlib

    with open(os.path.join(REPO, HOLDS_SEQ), "rb") as f:
        assert rec["sequence"]["sha256"] == hashlib.sha256(f.read()).hexdigest()
