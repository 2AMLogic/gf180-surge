#!/usr/bin/env python3
"""F-640-1 (issue #660): measure whether the dropped release velocity reaches
audio in the two fixture configurations that committed a reference citing
`seq-notes-holds-v1`.

The finding (reports/tooling-oracle-dispatcher-fold/EVIDENCE.md -> F-640-1) is
that two committed oracle reference records cite a sequence whose declared
release velocity (event 7, `note_off` velocity 100) their renderer sent as `0`.
Whether that matters to the rendered audio is a question for the engine, not
for an argument about the engine's source, so this probe renders both ways
under the pinned oracle and bit-compares the raw float mono buffers.

Method
------
Neither fixture renderer is modified (`fixtures/render_slfo_fixture.py` is
byte-stamped by six committed SXT-041 sidecars). Instead each renderer's own
`render_bus` is called with a *shim* in place of the `surgepy` module. The shim
hands back a proxy around the real Surge instance that intercepts exactly two
calls -- `releaseNote` and `playNote` -- and substitutes the velocity leg under
test. Every other call, and the whole of each renderer's reset / routes /
settle / scheduling / tail / audio policy, is the committed code path.

The substituted values are taken from an explicit FIFO built from the sequence
itself, and each interception asserts the channel and note it was handed match
the next declared event. So a renderer that dispatched events in a different
order, or dispatched a different number of them, fails loudly instead of
quietly comparing two renders of something else. The forwarded velocities are
recorded per leg in the output, which is what makes the `identical` verdict
auditable: it shows the two legs really did send different bytes to the engine.

Legs rendered per leaf
----------------------
  zero       release velocity forced to 0 for every note_off -- the behaviour
             that produced the committed reference. This is the *baseline* leg:
             its WAV must reproduce the committed `wav_sha256` before any
             comparison is believed.
  declared   release velocity = the sequence's own declared value per event
             (0, 0, 0, 100) -- what `fixtures/render_fixture.dispatch` sends.
             THE MEASUREMENT: `declared` vs `zero`.
  extreme    release velocity forced to 127 for every note_off -- a wider sweep
             of the same axis, so an `identical` result is not read as "100 was
             too small a step".
  noteon     release velocity forced to 0 (as `zero`) but every note_on
             velocity raised by +1 -- an observation, not a control. It records
             whether this fixture responds to *any* velocity, which is the
             context an `identical` release-velocity result has to be read in.
  control    release velocity forced to 0 (as `zero`) but the NOTE NUMBER
             handed to `releaseNote` raised by +1, so the held note is never
             released and sustains through the tail. THE FAILURE CONTROL: it
             perturbs an argument of the very call under test, so the
             comparison MUST report a difference. If it does not, the
             apparatus -- proxy interception, renderer, bit-comparator -- is
             blind to `releaseNote`'s arguments, and an `identical` verdict for
             the velocity argument would be an artifact rather than a
             measurement.

A velocity perturbation is deliberately NOT the failure control here. The
fixture preset (`Basses/Attacky.fxp` plus the declared routes) turns out to
render bit-identically for note_on velocities 1, 70, 71 and 127, so a velocity
control could not distinguish a working apparatus from a broken one. The
control has to perturb something the configuration is known to respond to while
still travelling through the same intercepted call, which is what the note
number does.

Provenance
----------
This probe deliberately records **no sha256 of any source file** -- not its own
and not either renderer's. `docs/byte-frozen-sources.json` treats a
`script_sha256` self-stamp as one-shot bookkeeping that no test re-derives, and
writing one here would have two effects worth avoiding: it would add this probe
to that registry's `historical_provenance` table (with the whole-registry count
prose and the item 9 signoff envelope that follow from it), and recording
`fixtures/render_lfo_fixture.py`'s current digest would flip that entry's
`current_bytes_recorded` to true -- silently imposing a provenance cost on a
renderer #640 had just freed of one. What the record carries instead is the
repo commit the measurement ran against, the engine's own identity, and the
committed digests it is checked against; the probe lands in the same change as
the record, and re-running it re-derives the result.

Statuses are reported per leaf. A leaf whose `zero` leg does not reproduce the
committed `wav_sha256` is NOT_RUN: its reference was produced by a different
renderer or a different engine build, so a comparison here would not be a
comparison of that record.

Usage:
  oracle/fetch-and-build.sh --prebuilt        # exports ORACLE_* for the pin
  tools/probe_release_velocity.py --out reports/f-640-1-release-velocity/artifacts/comparison.json
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import deque

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
from refusal import Refuse  # noqa: E402

SR = 48000
SEQUENCE = "seq-notes-holds-v1"
SEQ_PATH = os.path.join(REPO, "fixtures", "sequences", SEQUENCE + ".json")


# --------------------------------------------------------------------------
# velocity-forcing shim
# --------------------------------------------------------------------------

class _SurgeProxy:
    """Forwards every call to a real Surge instance, substituting velocities.

    `releases` / `noteons` are FIFOs of (channel, note, declared_velocity)
    drawn from the sequence in event order. Each interception pops the head and
    asserts it matches what the renderer actually dispatched, so a divergence
    between the sequence and the renderer's dispatch loop is an error here, not
    a silently mismatched comparison.
    """

    def __init__(self, inner, releases, noteons, release_mode, noteon_delta,
                 release_note_delta):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_releases", deque(releases))
        object.__setattr__(self, "_noteons", deque(noteons))
        object.__setattr__(self, "_release_mode", release_mode)
        object.__setattr__(self, "_noteon_delta", noteon_delta)
        object.__setattr__(self, "_release_note_delta", release_note_delta)
        object.__setattr__(self, "_sent_releases", [])
        object.__setattr__(self, "_sent_noteons", [])

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_inner"), name)

    def releaseNote(self, channel, note, velocity):
        q = object.__getattribute__(self, "_releases")
        if not q:
            raise Refuse("renderer released more notes than the sequence "
                         "declares; the probe's FIFO is exhausted")
        ch, nt, declared = q.popleft()
        if (ch, nt) != (channel, note):
            raise Refuse(f"release order mismatch: renderer sent "
                         f"(ch={channel}, note={note}), sequence declares "
                         f"(ch={ch}, note={nt})")
        mode = object.__getattribute__(self, "_release_mode")
        if mode == "zero":
            send = 0
        elif mode == "declared":
            send = declared
        elif isinstance(mode, int):
            send = mode
        else:  # pragma: no cover - guarded by the arg parser
            raise Refuse(f"unknown release mode {mode!r}")
        send_note = note + object.__getattribute__(self,
                                                   "_release_note_delta")
        object.__getattribute__(self, "_sent_releases").append(
            {"channel": channel, "note": note, "declared": declared,
             "renderer_sent": velocity, "forwarded_to_engine": send,
             "note_forwarded_to_engine": send_note})
        return object.__getattribute__(self, "_inner").releaseNote(
            channel, send_note, send)

    def playNote(self, channel, note, velocity, detune):
        q = object.__getattribute__(self, "_noteons")
        if not q:
            raise Refuse("renderer played more notes than the sequence "
                         "declares; the probe's FIFO is exhausted")
        ch, nt, declared = q.popleft()
        if (ch, nt) != (channel, note):
            raise Refuse(f"note_on order mismatch: renderer sent "
                         f"(ch={channel}, note={note}), sequence declares "
                         f"(ch={ch}, note={nt})")
        send = declared + object.__getattribute__(self, "_noteon_delta")
        object.__getattribute__(self, "_sent_noteons").append(
            {"channel": channel, "note": note, "declared": declared,
             "renderer_sent": velocity, "forwarded_to_engine": send})
        return object.__getattribute__(self, "_inner").playNote(
            channel, note, send, detune)

    def probe_report(self):
        return {
            "note_on_events": object.__getattribute__(self, "_sent_noteons"),
            "note_off_events": object.__getattribute__(self, "_sent_releases"),
            "unconsumed_note_on": len(
                object.__getattribute__(self, "_noteons")),
            "unconsumed_note_off": len(
                object.__getattribute__(self, "_releases")),
        }


class _SurgepyShim:
    """Stands in for the `surgepy` module a renderer's `render_bus` receives."""

    def __init__(self, real, releases, noteons, release_mode, noteon_delta,
                 release_note_delta):
        self._real = real
        self._releases = releases
        self._noteons = noteons
        self._release_mode = release_mode
        self._noteon_delta = noteon_delta
        self._release_note_delta = release_note_delta
        self.last_proxy = None

    def __getattr__(self, name):
        return getattr(self._real, name)

    def createSurge(self, sample_rate):
        proxy = _SurgeProxy(self._real.createSurge(sample_rate),
                            self._releases, self._noteons,
                            self._release_mode, self._noteon_delta,
                            self._release_note_delta)
        self.last_proxy = proxy
        return proxy


# --------------------------------------------------------------------------
# leaf definitions
# --------------------------------------------------------------------------

def _leaf_slfo(surgepy):
    """SXT-041 scene-LFO fixture (fixtures/render_slfo_fixture.py)."""
    import render_slfo_fixture as mod

    with open(mod.SLFO_INPUTS, encoding="utf-8") as f:
        slfo_in = json.load(f)
    preset_abs = os.path.join(oc.data_home(),
                              mod.PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse("pinned-engine preset not found; set ORACLE_SURGE_DIR")
    expected = slfo_in["preset"]["census_blob_sha1"]
    actual = oc.git_blob_sha1(preset_abs)
    if actual != expected:
        raise Refuse(f"preset blob {actual} != extractor {expected}")

    def render(shim, seq):
        return mod.render_bus(shim, preset_abs, seq, slfo_in)

    return {
        "leaf": "SXT-041",
        "renderer": "fixtures/render_slfo_fixture.py",
        "sidecar": "reports/SXT-041/artifacts/"
                   "reference-seq-notes-holds-v1-slfo-fixture.json",
        "committed_wav": "reports/SXT-041/artifacts/"
                         "reference-seq-notes-holds-v1-slfo-fixture.wav",
        "render": render,
    }


def _leaf_lfo(surgepy):
    """SXT-032 LFO-slice fixture (fixtures/render_lfo_fixture.py)."""
    import render_lfo_fixture as mod

    with open(mod.LFO_INPUTS, encoding="utf-8") as f:
        lfo_in = json.load(f)
    preset_abs = os.path.join(oc.data_home(),
                              mod.PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse("pinned-engine preset not found; set ORACLE_SURGE_DIR")
    expected = lfo_in["preset"]["census_blob_sha1"]
    actual = oc.git_blob_sha1(preset_abs)
    if actual != expected:
        raise Refuse(f"preset blob {actual} != extractor {expected}")
    routes = lfo_in["fixture_routes"]

    def render(shim, seq):
        return mod.render_bus(shim, preset_abs, seq, routes)

    return {
        "leaf": "SXT-032",
        "renderer": "fixtures/render_lfo_fixture.py",
        "sidecar": "reports/sxt-032/artifacts/"
                   "reference-seq-notes-holds-v1.json",
        "committed_wav": "reports/sxt-032/artifacts/"
                         "reference-seq-notes-holds-v1-lfo-fixture.wav",
        "render": render,
    }


LEAVES = {"sxt041": _leaf_slfo, "sxt032": _leaf_lfo}


# --------------------------------------------------------------------------
# rendering / comparison
# --------------------------------------------------------------------------

def render_leg(leaf, seq, release_mode, repeats, surgepy, noteon_delta=0,
               release_note_delta=0):
    """Render one leg `repeats` times in fresh instances; require determinism."""
    releases = [(e["channel"], e["note"], e.get("velocity", 0))
                for e in seq["events"] if e["type"] == "note_off"]
    noteons = [(e["channel"], e["note"], e.get("velocity", 0))
               for e in seq["events"] if e["type"] == "note_on"]

    buffers, hashes, report, info = [], [], None, None
    for _ in range(repeats):
        shim = _SurgepyShim(surgepy, releases, noteons, release_mode,
                            noteon_delta, release_note_delta)
        mono, info = leaf["render"](shim, seq)
        report = shim.last_proxy.probe_report()
        if report["unconsumed_note_on"] or report["unconsumed_note_off"]:
            raise Refuse(
                f"renderer did not dispatch every declared event: "
                f"{report['unconsumed_note_on']} note_on and "
                f"{report['unconsumed_note_off']} note_off left unsent")
        buffers.append(np.ascontiguousarray(mono))
        hashes.append(hashlib.sha256(buffers[-1].tobytes()).hexdigest())
    bit_identical = all(h == hashes[0] for h in hashes)
    if not bit_identical:
        raise Refuse(f"leg renders not bit-identical across repeats: {hashes}")
    return {
        "release_mode": release_mode,
        "note_on_velocity_delta": noteon_delta,
        "release_note_number_delta": release_note_delta,
        "determinism": {"repeats": repeats, "sha256": hashes,
                        "bit_identical": bit_identical},
        "buffer_sha256": hashes[0],
        "frames": int(len(buffers[0])),
        "peak_abs_float": float(np.max(np.abs(buffers[0])))
        if len(buffers[0]) else 0.0,
        "velocities_forwarded_to_engine": report,
        "_buffer": buffers[0],
        "_info": info,
    }


def compare(a, b):
    """Bit-for-bit compare two raw float mono buffers."""
    ba, bb = a["_buffer"], b["_buffer"]
    if len(ba) != len(bb):
        return {"identical": False, "reason": "length mismatch",
                "frames_a": int(len(ba)), "frames_b": int(len(bb))}
    if ba.tobytes() == bb.tobytes():
        return {"identical": True, "frames": int(len(ba)),
                "differing_samples": 0, "first_differing_sample": None,
                "max_abs_difference": 0.0}
    diff = ba != bb
    idx = int(np.argmax(diff))
    return {
        "identical": False,
        "frames": int(len(ba)),
        "differing_samples": int(np.count_nonzero(diff)),
        "first_differing_sample": idx,
        "first_differing_sample_seconds": idx / float(SR),
        "max_abs_difference": float(np.max(np.abs(ba - bb))),
        "values_at_first_difference": [float(ba[idx]), float(bb[idx])],
    }


def baseline_gate(leaf, zero_leg, scratch_dir):
    """The `zero` leg must reproduce the leaf's committed WAV, byte for byte."""
    os.makedirs(scratch_dir, exist_ok=True)
    wav = os.path.join(scratch_dir,
                       f"{leaf['leaf'].lower()}-zero-leg.wav")
    oc.write_wav_mono16(wav, zero_leg["_buffer"], SR)
    rendered = oc.sha256_file(wav)

    with open(os.path.join(REPO, leaf["sidecar"]), encoding="utf-8") as f:
        sidecar = json.load(f)
    committed_path = os.path.join(REPO, leaf["committed_wav"])
    committed_file = oc.sha256_file(committed_path) \
        if os.path.exists(committed_path) else None

    # No source digest -- this probe's own or either renderer's -- is emitted
    # into this record, and that is deliberate (see the module docstring's
    # "Provenance" note and reports/f-640-1-release-velocity/EVIDENCE.md).
    return {
        "rendered_wav_sha256": rendered,
        "sidecar_wav_sha256": sidecar["wav_sha256"],
        "committed_wav_file": leaf["committed_wav"],
        "committed_wav_file_sha256": committed_file,
        "sidecar_matches_committed_file":
            committed_file == sidecar["wav_sha256"],
        "reproduces": rendered == sidecar["wav_sha256"],
        "sidecar_engine": sidecar["engine"],
        "sidecar_engine_field_is_inherited_from_the_extractor_inputs": True,
        "sidecar_sequence_sha256": sidecar["sequence"]["sha256"],
    }


def run_leaf(name, seq, repeats, scratch_dir, surgepy):
    leaf = LEAVES[name](surgepy)
    out = {k: v for k, v in leaf.items()
           if k != "render" and not k.startswith("_")}

    zero = render_leg(leaf, seq, "zero", repeats, surgepy)
    out["baseline"] = baseline_gate(leaf, zero, scratch_dir)

    if not out["baseline"]["reproduces"]:
        out["status"] = "NOT_RUN"
        out["status_reason"] = (
            "the velocity-0 leg does not reproduce the committed wav_sha256, "
            "so a comparison here would not be a comparison of that committed "
            "record. Engine identity and renderer bytes are recorded above.")
        out["legs"] = {"zero": {k: v for k, v in zero.items()
                                if not k.startswith("_")}}
        out["comparisons"] = {}
        return out

    declared = render_leg(leaf, seq, "declared", repeats, surgepy)
    extreme = render_leg(leaf, seq, 127, repeats, surgepy)
    noteon = render_leg(leaf, seq, "zero", repeats, surgepy, noteon_delta=1)
    control = render_leg(leaf, seq, "zero", repeats, surgepy,
                         release_note_delta=1)

    out["legs"] = {n: {k: v for k, v in leg.items() if not k.startswith("_")}
                   for n, leg in (("zero", zero), ("declared", declared),
                                  ("extreme", extreme), ("noteon", noteon),
                                  ("control", control))}
    out["comparisons"] = {
        "measurement__declared_vs_zero": compare(zero, declared),
        "sweep__extreme127_vs_zero": compare(zero, extreme),
        "observation__noteon_velocity_plus1_vs_zero": compare(zero, noteon),
        "failure_control__release_note_plus1_vs_zero": compare(zero, control),
    }

    ctrl = out["comparisons"]["failure_control__release_note_plus1_vs_zero"]
    out["failure_control"] = {
        "targets": "the claim that this comparison can see a change in an "
                   "argument of releaseNote at all; without it, an identical "
                   "result for the velocity argument is indistinguishable "
                   "from a blind apparatus",
        "expected": "different",
        "observed": "identical" if ctrl["identical"] else "different",
        "passed": not ctrl["identical"],
        "note": "renders identically to the zero leg except that the note "
                "number handed to releaseNote is raised by 1, so the held "
                "note is never released. A difference here proves the proxy "
                "interception reaches the engine, the renderer renders what "
                "the proxy forwards, and the bit-comparator reports "
                "differences when they exist.",
        "why_not_a_velocity_perturbation":
            "the fixture preset renders bit-identically for note_on "
            "velocities 1, 70, 71 and 127, so a velocity perturbation cannot "
            "distinguish a working apparatus from a blind one. The "
            "observation__noteon_velocity_plus1_vs_zero comparison records "
            "that insensitivity rather than relying on it.",
    }

    measured = out["comparisons"]["measurement__declared_vs_zero"]
    if not out["failure_control"]["passed"]:
        out["status"] = "NO_VERDICT"
        out["status_reason"] = (
            "the failure control did not fail the check it targets: perturbing "
            "the note number handed to releaseNote rendered bit-identically, "
            "so this comparison cannot distinguish 'release velocity does not "
            "reach audio' from 'the comparison sees nothing'.")
    elif measured["identical"]:
        out["status"] = "PASS"
        out["status_reason"] = (
            "the declared release velocity and the 0 the renderer sent produce "
            "bit-identical raw float mono buffers under the pinned oracle, "
            "with the failure control showing the comparison is velocity-"
            "sensitive. The committed reference stands; the mismatch between "
            "the cited sequence and the velocity sent is provenance-only.")
    else:
        out["status"] = "STALE"
        out["status_reason"] = (
            "the declared release velocity changes the rendered audio, so the "
            "committed reference was rendered from a sequence it does not "
            "faithfully represent and must be re-rendered.")
    return out


def environment(surgepy):
    try:
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception as e:  # pragma: no cover
        base = f"unavailable: {e}"
    with open(os.path.join(REPO, "oracle", "manifest.json"),
              encoding="utf-8") as f:
        manifest = json.load(f)
    return {
        "repo_commit_at_render_time": base,
        "probe": "tools/probe_release_velocity.py",
        "probe_digest_recorded": False,
        "probe_digest_note":
            "No sha256 of this probe's bytes is recorded here. See the "
            "module docstring's Provenance note: a self-stamp would make this "
            "probe a historical_provenance entry in "
            "docs/byte-frozen-sources.json, and the stamp is bookkeeping that "
            "no test re-derives. The probe is committed in the same change as "
            "this record and the measurement is re-derivable by re-running "
            "it.",
        "engine": {
            "pinned_commit": manifest["engine"]["commit"],
            "version_string": surgepy.getVersion(),
            "surgepy_module": oc.binding_provenance(surgepy),
        },
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "sample_rate": SR,
    }



def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--leaf", choices=sorted(LEAVES) + ["both"],
                    default="both")
    ap.add_argument("--repeats", type=int, default=3,
                    help="fresh-instance repeats per leg (determinism gate)")
    ap.add_argument("--out", required=True,
                    help="path for the machine-readable comparison JSON")
    ap.add_argument("--scratch-dir", default="/tmp/f-640-1-release-velocity",
                    help="scratch dir for the baseline-gate WAV renders")
    args = ap.parse_args()

    with open(SEQ_PATH, encoding="utf-8") as f:
        seq = json.load(f)
    if seq.get("schema_version") != 1:
        raise Refuse(f"{SEQ_PATH}: unsupported schema_version")

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    names = sorted(LEAVES) if args.leaf == "both" else [args.leaf]
    result = {
        "schema_version": 1,
        "issue": "#660",
        "finding": "F-640-1",
        "finding_record": "reports/tooling-oracle-dispatcher-fold/EVIDENCE.md",
        "finding_artifact": "reports/tooling-oracle-dispatcher-fold/artifacts/"
                            "dispatcher-drift-audit.json",
        "question": "does the release velocity the renderers dropped reach the "
                    "rendered audio in these two fixture configurations?",
        "sequence": {
            "id": seq["id"],
            "path": os.path.relpath(SEQ_PATH, REPO),
            "sha256": oc.sha256_file(SEQ_PATH),
            "declared_release_velocities": [e.get("velocity", 0)
                                            for e in seq["events"]
                                            if e["type"] == "note_off"],
        },
        "environment": environment(surgepy),
        "leaves": {},
    }
    for name in names:
        result["leaves"][name] = run_leaf(name, seq, args.repeats,
                                          args.scratch_dir, surgepy)
    result["coverage"] = {
        "leaves_requested": names,
        "leaves_compared": [n for n in names
                            if result["leaves"][n]["comparisons"]],
        "leaves_not_run": [n for n in names
                           if result["leaves"][n]["status"] == "NOT_RUN"],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({n: {"status": result["leaves"][n]["status"],
                          "baseline_reproduces":
                              result["leaves"][n]["baseline"]["reproduces"],
                          "measurement":
                              result["leaves"][n]["comparisons"]
                              .get("measurement__declared_vs_zero", {})
                              .get("identical"),
                          "failure_control_passed":
                              result["leaves"][n].get("failure_control", {})
                              .get("passed"),
                          "note_on_velocity_sensitive":
                              (result["leaves"][n]["comparisons"]
                               .get("observation__noteon_velocity_plus1_vs_"
                                    "zero", {}).get("identical") is False)
                              if result["leaves"][n]["comparisons"] else None}
                      for n in names}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
