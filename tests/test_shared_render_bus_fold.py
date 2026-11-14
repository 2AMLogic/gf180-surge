#!/usr/bin/env python3
"""#663: one render loop serves the wavetable and classic/sine families.

`tools/render_wt_reference.py` carried a private `render_bus` that was
`tools/_render_reference_common.render_bus` with a different constructor call.
The fold replaced the duplicate with a zero-argument instance factory, so the
one surviving loop is now reached by two different `build_instance`
signatures.

PINS, with a recording stub synthesizer and no engine:

  1. The shared `render_bus` makes exactly the SXT-012 loop-policy call
     sequence -- controller reset, settle block count, block-quantized event
     positions, render span -- against hand-computed literals.
  2. A wavetable-shaped factory `(surgepy, oc, overrides, preset_rel)` and a
     classic-shaped factory `(surgepy, oc, carrier)` drive that loop to the
     SAME call sequence and the SAME `info` keys, which is the claim the fold
     rests on.
  3. A fresh instance per repeat: the factory is called once per repeat and
     each repeat drives its own instance.
  4. FAILURE CONTROLS: the same policy assertion run against the real loop
     body with one policy line mutated out -- settle not processed, tail
     dropped, instance shared across repeats -- FAILS.

DOES NOT: run the pinned oracle, import `fixtures/render_fixture.py` (its
`dispatch` is compiled from the committed bytes in isolation, as
tests/test_shared_event_dispatcher.py does), render audio, re-derive any
committed SXT-026 reference, or say anything about model-vs-reference
agreement or bit-identity of a real render.  Call-sequence and `info`-key
equality only.
"""

import ast
import hashlib
import importlib.util
import os

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join("tools", "_render_reference_common.py")
SHARED_DISPATCHER = os.path.join("fixtures", "render_fixture.py")

SR = 48000
BLOCK_SIZE = 32


def _src(rel):
    with open(os.path.join(REPO, rel), "r", encoding="utf-8") as f:
        return f.read()


def _func_source(rel, name):
    """Source of one top-level function, taken from the file's own bytes."""
    src = _src(rel)
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    raise AssertionError(f"{rel} has no top-level def {name}")


def committed_dispatch():
    """`dispatch` from the committed bytes of fixtures/render_fixture.py.

    Compiled in isolation on purpose: importing the module enforces the
    manifest-pinned interpreter and pulls in the ABI-specific numpy the
    pinned oracle build needs and this test does not.
    """
    ns = {}
    exec(compile(_func_source(SHARED_DISPATCHER, "dispatch"),
                 SHARED_DISPATCHER, "exec"), ns)
    return ns["dispatch"]


def imported_render_bus():
    """The real `render_bus`, imported, with its dispatcher stubbed out."""
    spec = importlib.util.spec_from_file_location(
        "render_reference_common_for_fold_test", os.path.join(REPO, HARNESS))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SR == SR, f"harness SR is {mod.SR}, this test assumes {SR}"
    mod.shared_dispatch = committed_dispatch
    return mod.render_bus


def mutant_render_bus(find, replace):
    """The real loop body with one policy line replaced -- FAILURE CONTROL.

    Built from the harness's committed bytes rather than hand-written, so a
    control cannot quietly stop resembling the function it is controlling: if
    the policy line it mutates is reworded, the count assertion below fails
    instead of the control rotting into a vacuous pass.
    """
    src = _func_source(HARNESS, "render_bus")
    assert src.count(find) == 1, (
        f"the control's target line is no longer uniquely present in "
        f"{HARNESS}'s render_bus ({src.count(find)} occurrences of {find!r}); "
        f"re-anchor this control rather than deleting it"
    )
    cache = []

    def shared_instance(make):
        """One instance for every repeat -- the per-instance-state control."""
        if not cache:
            cache.append(make())
        return cache[0]

    ns = {"np": np, "hashlib": hashlib, "SR": SR,
          "shared_dispatch": committed_dispatch,
          "shared_instance": shared_instance}
    exec(compile(src.replace(find, replace, 1),
                 HARNESS + " [MUTANT CONTROL]", "exec"), ns)
    return ns["render_bus"]


class RecordingSynth:
    """Records the surgepy calls the render loop makes, in order.

    `createMultiBlock` returns a zeroed stereo buffer of the width the real
    binding would allocate, so `np.asarray(buf)[0] + [1]` downmixes and the
    hash/peak/clip arithmetic runs for real.
    """

    def __init__(self, log):
        self.log = log

    def pitchBend(self, ch, value):
        self.log.append(("pitchBend", ch, value))

    def channelController(self, ch, cc, value):
        self.log.append(("channelController", ch, cc, value))

    def channelAftertouch(self, ch, value):
        self.log.append(("channelAftertouch", ch, value))

    def allNotesOff(self):
        self.log.append(("allNotesOff",))

    def getBlockSize(self):
        self.log.append(("getBlockSize",))
        return BLOCK_SIZE

    def createMultiBlock(self, nblocks):
        self.log.append(("createMultiBlock", nblocks))
        return np.zeros((2, nblocks * BLOCK_SIZE), dtype=np.float32)

    def processMultiBlock(self, buf, *span):
        # the settle pass processes the whole buffer; the render loop always
        # passes (start_block, n_blocks).  Recorded distinctly so a skipped
        # settle cannot look like a render segment.
        self.log.append(("processMultiBlock", "settle" if not span else span))

    def playNote(self, ch, note, vel, detune):
        self.log.append(("playNote", ch, note, vel, detune))

    def releaseNote(self, ch, note, vel):
        self.log.append(("releaseNote", ch, note, vel))


# A sequence whose block arithmetic is small enough to state as literals.
# settle_s 0.01 -> int(0.01*48000)=480 samples -> 480//32 = 15 settle blocks.
# notes end at t=1000; tail_s 0.01 -> +480 -> total_samples 1480
#                                  -> total_blocks = ceil(1480/32) = 47.
# quant(t) = ceil(t/32):  quant(0)=0, quant(300)=10, quant(1000)=32.
SEQ = {
    "id": "seq-fold-stub-v1",
    "settle_s": 0.01,
    "tail_s": 0.01,
    "events": [
        {"type": "note_on", "channel": 0, "note": 60, "velocity": 100, "t": 0},
        {"type": "cc", "channel": 0, "controller": 11, "value": 77, "t": 300},
        {"type": "note_off", "channel": 0, "note": 60, "velocity": 90,
         "t": 1000},
    ],
}

SETTLE_BLOCKS = 15
TOTAL_BLOCKS = 47
TOTAL_SAMPLES = 1480

# Hand-computed from the SXT-012 loop policy, not re-derived from the code.
EXPECTED_CALLS = [
    # RESET: bend 0, CC64/CC1/CC11 0, pressure 0, allNotesOff
    ("pitchBend", 0, 0),
    ("channelController", 0, 64, 0),
    ("channelController", 0, 1, 0),
    ("channelController", 0, 11, 0),
    ("channelAftertouch", 0, 0),
    ("allNotesOff",),
    ("getBlockSize",),
    # SETTLE: 15 blocks allocated and processed, then discarded
    ("createMultiBlock", SETTLE_BLOCKS),
    ("processMultiBlock", "settle"),
    # RENDER SPAN: 47 blocks
    ("createMultiBlock", TOTAL_BLOCKS),
    # t=0 dispatched before block 0, then process up to the cc's block 10
    ("playNote", 0, 60, 100, 0),
    ("processMultiBlock", (0, 10)),
    # t=300 (block 10) dispatched, then process up to the note_off's block 32
    ("channelController", 0, 11, 77),
    ("processMultiBlock", (10, 22)),
    # t=1000 (block 32) dispatched with its DECLARED release velocity, then
    # the tail runs to the end of the span
    ("releaseNote", 0, 60, 90),
    ("processMultiBlock", (32, 15)),
]

INFO_KEYS = ["blocks", "frames", "peak_abs_float", "clipped_samples",
             "repeats", "repeat_hashes", "bit_identical_repeats"]


def wavetable_shaped_factory(log, seen):
    """`fc.build_instance(surgepy, oc, overrides, preset_rel)` -- SXT-026.

    `seen` collects one `(constructor_args, instance)` pair per call, so both
    the constructor SHAPE and the instance IDENTITY are observable: the call
    log alone cannot see instance reuse, because a reused instance still runs
    the full reset/settle/render body on every repeat.
    """
    surgepy, oc = object(), object()
    overrides = [("mute_o1", 1), ("mute_noise", 1), ("fu1_off", 1)]
    preset_rel = "resources/data/patches_3rdparty/Argitoth/Drums/Kick.fxp"

    def make_instance():
        s = RecordingSynth(log)
        seen.append(((surgepy, oc, overrides, preset_rel), s))
        return s

    return make_instance


def classic_shaped_factory(log, seen):
    """`fc.build_instance(surgepy, oc, carrier)` -- SXT-033 / SXT-040."""
    surgepy, oc = object(), object()
    carrier = "saw"

    def make_instance():
        s = RecordingSynth(log)
        seen.append(((surgepy, oc, carrier), s))
        return s

    return make_instance


def assert_fresh_instance_per_repeat(render_bus, repeats=3):
    """The per-instance policy, as a function of the loop under test.

    "Fresh instance per render" is the factory's contract after #663: the
    loop must CALL the factory once per repeat and drive a distinct instance
    each time.  Run against the real loop this passes; run against a loop
    that builds once and reuses it, it FAILS.
    """
    log, seen = [], []
    monos, info = render_bus(SEQ, wavetable_shaped_factory(log, seen), repeats)
    assert len(seen) == repeats, (
        f"the loop called the instance factory {len(seen)} times for "
        f"{repeats} repeats; one fresh instance per repeat is the policy"
    )
    assert len({id(inst) for _args, inst in seen}) == repeats, (
        "the repeats did not each drive a distinct instance"
    )
    assert len(monos) == repeats
    assert info["repeats"] == repeats
    return monos, info


def assert_loop_policy(render_bus):
    """The acceptance assertion, as a function of the loop under test.

    Run against the real `render_bus` it must pass; run against a loop with
    one policy line mutated out it must FAIL.  That is what makes the
    controls below live rather than decorative.
    """
    log, seen = [], []
    monos, info = render_bus(SEQ, wavetable_shaped_factory(log, seen),
                             1)
    assert log == EXPECTED_CALLS
    assert info["blocks"] == TOTAL_BLOCKS
    assert info["frames"] == TOTAL_SAMPLES
    assert len(monos) == 1
    return monos, info


# ----------------------------------------------------------- the real loop ---

def test_shared_render_bus_makes_the_declared_loop_policy_calls():
    monos, info = assert_loop_policy(imported_render_bus())
    assert list(info) == INFO_KEYS
    assert info["repeats"] == 1
    assert info["clipped_samples"] == 0
    assert info["peak_abs_float"] == 0.0
    assert monos[0].shape == (TOTAL_BLOCKS * BLOCK_SIZE,)


def test_the_two_factory_shapes_drive_an_identical_call_sequence():
    """The fold's claim: the constructor signature is the ONLY difference.

    The wavetable family builds its instance from `(overrides, preset_rel)`
    and the classic/sine families from `(carrier)`.  Both reach the one loop
    through a zero-argument factory, so the engine-facing call sequence and
    the `info` key set must be identical.
    """
    render_bus = imported_render_bus()

    wt_log, wt_seen = [], []
    _, wt_info = render_bus(SEQ, wavetable_shaped_factory(wt_log, wt_seen), 1)
    cl_log, cl_seen = [], []
    _, cl_info = render_bus(SEQ, classic_shaped_factory(cl_log, cl_seen), 1)

    # the two factories really do have different constructor shapes ...
    assert len(wt_seen[0][0]) == 4 and len(cl_seen[0][0]) == 3
    # ... and the loop they drive is the same loop
    assert wt_log == cl_log == EXPECTED_CALLS
    assert list(wt_info) == list(cl_info) == INFO_KEYS
    assert wt_info["blocks"] == cl_info["blocks"] == TOTAL_BLOCKS
    assert wt_info["frames"] == cl_info["frames"] == TOTAL_SAMPLES


def test_one_fresh_instance_per_repeat():
    """"Fresh instance per render" is now the factory's contract."""
    _monos, info = assert_fresh_instance_per_repeat(imported_render_bus(), 3)
    # every repeat runs the full reset/settle/render body
    assert len(info["repeat_hashes"]) == 3
    # identical zeroed buffers hash identically, so determinism is reported
    assert info["bit_identical_repeats"] is True


def test_mutant_harness_without_a_mutation_reproduces_the_real_loop():
    """The control machinery is faithful: an unmutated rebuild still passes.

    Without this, a control that fails for an unrelated reason (a missing
    name in the exec namespace, say) would look like a biting control.
    """
    identity = mutant_render_bus("monos = []", "monos = []")
    assert_loop_policy(identity)


# ------------------------------------------------------- FAILURE CONTROLS ---

def test_failure_control_settle_skipped_fails_the_policy():
    """REQUIRED FAILURE CONTROL: a loop that discards no settle must FAIL."""
    control = mutant_render_bus(
        "s.processMultiBlock(sbuf)",
        "pass  # MUTANT: settle allocated but never processed")
    with pytest.raises(AssertionError):
        assert_loop_policy(control)


def test_failure_control_tail_dropped_fails_the_policy():
    """REQUIRED FAILURE CONTROL: a loop that renders no tail must FAIL."""
    control = mutant_render_bus(
        'total_samples = last_t + int(float(seq.get("tail_s", 1.5)) * SR)',
        "total_samples = last_t  # MUTANT: tail dropped")
    with pytest.raises(AssertionError):
        assert_loop_policy(control)
    # and name the specific loss, so the control cannot rot into passing for
    # an unrelated reason: the span shrinks to the last event's block.
    log, seen = [], []
    _, info = control(SEQ, wavetable_shaped_factory(log, seen), 1)
    assert info["frames"] == 1000 < TOTAL_SAMPLES
    assert info["blocks"] == 32 < TOTAL_BLOCKS


def test_failure_control_instance_shared_across_repeats_fails():
    """REQUIRED FAILURE CONTROL: one instance reused for every repeat.

    Note what this control establishes and what it does not: the CALL LOG is
    identical either way, because a reused instance still runs the full
    reset/settle/render body on every repeat.  Instance sharing is therefore
    invisible to the sequence assertion and visible only to the per-instance
    policy -- which is exactly why that policy has its own assertion.
    """
    mutation = ("s = make_instance()",
                "s = shared_instance(make_instance)  # MUTANT: one shared")
    with pytest.raises(AssertionError):
        assert_fresh_instance_per_repeat(mutant_render_bus(*mutation), 3)

    # name the specific loss: one construction for three repeats, and the
    # call sequence that the policy assertion cannot see.  A FRESH control --
    # each mutant carries its own one-shot cache, so reusing the one above
    # would observe that cache rather than this run.
    log, seen = [], []
    mutant_render_bus(*mutation)(SEQ, wavetable_shaped_factory(log, seen), 3)
    assert len(seen) == 1, "the control did not actually share the instance"
    assert log == EXPECTED_CALLS * 3, (
        "the shared-instance control is expected to be INVISIBLE to the call "
        "log; if that changed, re-derive which assertion catches it"
    )
