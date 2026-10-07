#!/usr/bin/env python3
"""SXT-043 valid-reference probe and retained-route negative controls (#329).

Requires the external pinned oracle (oracle/manifest.json, 48 kHz).  Renders
ONE declared probe note (`reference_validity.DECLARED`) on a FRESH engine
instance and applies the declared valid-reference gate
(`model/voice/playmode/reference_validity.py`).  One mode per process (the
pinned surgepy build does not support several live instances):

  --mode revised             the production fixture sequence
                             (`fixture_config.build_instance`, fixture
                             revision 2).  Expected: gate PASS.
  --mode nc-retained-routes  NEGATIVE CONTROL: the pre-#329 order -- loadPatch,
                             type switch WITHOUT clearing the osc-slot p[]
                             routes, remaining declared overrides.  Expected:
                             gate FAIL (silence, #311).
  --mode nc-stale-buffer     NEGATIVE CONTROL: as above, but one note is
                             played and released BEFORE the switch so the
                             untouched oscillator buffer holds leftover
                             non-Sine data.  Expected: gate FAIL (nonzero but
                             not pitched at the probe key).

The controls reach the retained-route order only through the private
`_nc_record_stale` hook of `apply_overrides`; no production entry point
offers it, and this script never writes a reference artifact name.

Exit status: 0 when the outcome matches the mode's expectation, 1 when it
does not (a control that does not fail is a broken control), 2 on REFUSE.
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice", "playmode"))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402
import reference_validity as rv  # noqa: E402

oc.reexec_under_pinned_python(REPO)

EXPECT = {"revised": "PASS", "nc-retained-routes": "FAIL",
          "nc-stale-buffer": "FAIL"}


def _render_probe(s):
    bs = int(s.getBlockSize())
    s.allNotesOff()
    s.processMultiBlock(s.createMultiBlock(int(rv.PROBE_SETTLE_S * rv.SR)
                                           // bs))
    hold_b = -(-int(rv.PROBE_HOLD_S * rv.SR) // bs)
    tail_b = -(-int(rv.PROBE_TAIL_S * rv.SR) // bs)
    buf = s.createMultiBlock(hold_b + tail_b)
    s.playNote(0, rv.PROBE_KEY, rv.PROBE_VELOCITY, 0)
    s.processMultiBlock(buf, 0, hold_b)
    s.releaseNote(0, rv.PROBE_KEY, 0)
    s.processMultiBlock(buf, hold_b, tail_b)
    st = np.asarray(buf)
    return 0.5 * (st[0] + st[1])


def _old_order_instance(surgepy, carrier, preroll_note):
    s = surgepy.createSurge(48000.0)
    path = fc.preset_abs(oc, carrier)
    if not s.loadPatch(path):
        raise fc.Refuse("loadPatch failed: %s" % carrier)
    slot = fc.CARRIERS[carrier][1]
    targets = fc.osc_param_targets(s, slot)
    before = [{"src": r.getSource().getName(), "dest": r.getDest().getName(),
               "depth": float(r.getDepth())}
              for _sc, _si, r in fc._route_rows(s)
              if fc._param_id(r.getDest()) in targets]
    if preroll_note:
        bs = int(s.getBlockSize())
        s.playNote(0, rv.PROBE_KEY, rv.PROBE_VELOCITY, 0)
        s.processMultiBlock(s.createMultiBlock(int(0.5 * rv.SR) // bs))
        s.releaseNote(0, rv.PROBE_KEY, 0)
        s.processMultiBlock(s.createMultiBlock(int(1.0 * rv.SR) // bs))
    stale = []
    d, _pinned = fc.apply_overrides(s, slot, _nc_record_stale=stale)
    return s, d, {"osc_p_routes_at_load": before,
                  "stale_after_switch": stale,
                  "classify_and_pin_routes": "not run (it would REFUSE on "
                                             "the stale routes under "
                                             "fixture revision 2)"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", required=True, choices=fc.FIXTURE_CARRIERS)
    ap.add_argument("--mode", required=True, choices=sorted(EXPECT))
    ap.add_argument("--out", required=True, help="JSON record path")
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    if args.mode == "revised":
        s, d, routes = fc.build_instance(surgepy, oc, args.carrier)
    else:
        s, d, routes = _old_order_instance(
            surgepy, args.carrier, args.mode == "nc-stale-buffer")
    try:
        mono = _render_probe(s)
    finally:
        del s

    f0 = rv.expected_f0(rv.PROBE_KEY, d["scene_octave"], d["octave"],
                        d["pitch_param"])
    gate = rv.check(mono, 0, f0)
    expect = EXPECT[args.mode]
    rec = {
        "issue": 329, "leaf": "SXT-043",
        "fixture_revision": fc.FIXTURE_REVISION,
        "carrier": args.carrier, "mode": args.mode,
        "expected_gate_verdict": expect,
        "outcome_matches_expectation": gate["verdict"] == expect,
        "engine": {"commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
                   "surgepy": surgepy.getVersion(),
                   "sample_rate": rv.SR},
        "preset_path": fc.preset_rel(args.carrier),
        "preset_blob_sha1": oc.git_blob_sha1(fc.preset_abs(oc, args.carrier)),
        "readback": {k: d[k] for k in ("osc_type", "shape", "octave",
                                       "scene_octave", "pitch_param",
                                       "keytrack", "polymode",
                                       "portamento")},
        "routes": routes,
        "render_sha256": hashlib.sha256(
            np.ascontiguousarray(mono).tobytes()).hexdigest(),
        "gate": gate,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps({"carrier": args.carrier, "mode": args.mode,
                      "gate": gate["verdict"], "expected": expect,
                      "dominant_hz": gate["dominant_hz"],
                      "expected_f0_hz": round(f0, 3),
                      "peak_abs": gate["peak_abs"],
                      "fails": gate["fails"]}, indent=1))
    return 0 if gate["verdict"] == expect else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except fc.Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
