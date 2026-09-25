#!/usr/bin/env python3
"""Issue #93 negative control: the shared comparator's (tools/
compare_audio_reference.py) new wet-path tail-region gate, exercised
end-to-end against an EXISTING committed wet fixture (SXT-028c
alienappears / seq-notes-coverage-v1) -- not a synthetic waveform.

Two runs against the same committed reference:
  NC-baseline: --model is an exact copy of the reference wet WAV -> must
               PASS (both the whole-render budget and the tail-region gate).
  NC-drop-tail: --model is the SAME wet WAV truncated before the declared
               tail span (drop the last 1.5 s, mirroring the SXT-028c
               chorus-leaf NC-B pattern) -> must FAIL. Because the shared
               comparator's whole-render budget only ever looks at the
               overlapping min(len(ref), len(model)) samples, the truncated
               "model" is byte-identical to the reference over that overlap
               (it IS the same audio, just shorter) -- so the whole-render
               budget alone PASSES TRIVIALLY. Only the tail-region gate
               (this issue) catches the dropped tail. That gap is exactly
               what #93 closes.

Exits 0 iff both controls demonstrate the expected verdict (CONTROL-OK);
a control that does not fail the check it targets is a broken control.
Original to this repository (Apache-2.0).
"""
import json
import os
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

FIXTURES = os.path.join(REPO, "reports", "SXT-028c", "fixtures")
SLUG = "alienappears"
SEQ = "seq-notes-coverage-v1"
OUT = os.path.join(REPO, "reports", "SXT-028c", "negative-controls")
DROP_S = 1.5


def _read_stereo_f32(path):
    return car.read_wav_stereo_f32(path)


def _write_stereo_f32(path, stereo, sr=48000):
    nch, frames = stereo.shape
    data = np.ascontiguousarray(stereo.T, dtype="<f4").tobytes()
    byte_rate = sr * nch * 4
    block_align = nch * 4
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, nch, sr, byte_rate,
                                 block_align, 32)
    hdr += b"data" + struct.pack("<I", len(data))
    with open(path, "wb") as f:
        f.write(hdr + data)


class _Args:
    pass


def _run(ref_path, model_path, fixture_meta, out_json):
    a = _Args()
    a.ref, a.model, a.json, a.fixture_meta = (ref_path, model_path,
                                              out_json, fixture_meta)
    car.main_wet(a)
    with open(out_json) as f:
        return json.load(f)


def main():
    os.makedirs(OUT, exist_ok=True)
    ref_path = os.path.join(FIXTURES, f"{SLUG}__{SEQ}-wet.f32.wav")
    meta_path = os.path.join(FIXTURES, f"{SLUG}__{SEQ}.json")
    with open(meta_path) as f:
        meta = json.load(f)
    duration_s = meta["render"]["duration_s"]
    tail_s = meta["render"]["tail_s"]

    stereo, sr = _read_stereo_f32(ref_path)
    assert sr == 48000

    scratch = "/tmp/sxt93-tail-nc"
    os.makedirs(scratch, exist_ok=True)

    baseline_model = os.path.join(scratch, "baseline-model.f32.wav")
    _write_stereo_f32(baseline_model, stereo.copy(), sr)
    baseline_json = os.path.join(OUT, "shared-comparator-drop-tail-baseline.json")
    baseline = _run(ref_path, baseline_model, meta_path, baseline_json)

    drop_n = int(round(DROP_S * sr))
    truncated = stereo[:, : stereo.shape[1] - drop_n]
    drop_model = os.path.join(scratch, "drop-tail-model.f32.wav")
    _write_stereo_f32(drop_model, truncated, sr)
    drop_json = os.path.join(OUT, "shared-comparator-drop-tail.json")
    dropped = _run(ref_path, drop_model, meta_path, drop_json)

    baseline_ok = baseline["verdict"].startswith("PASS")
    drop_failed = (not dropped["verdict"].startswith("PASS")
                   and not dropped["tail_check"]["ok"])
    # the point of this control: the whole-render budget alone is fooled by
    # the truncation (it only ever sees the overlapping samples, which are
    # byte-identical to the reference) -- only the tail gate catches it.
    budget_fooled = dropped["proposed_budget_results"]["max_abs_diff_lsb"] and \
        dropped["proposed_budget_results"]["rms_diff_dbfs"]

    lines = [
        f"fixture: {SLUG}/{SEQ} (reports/SXT-028c/fixtures, committed); "
        f"duration_s={duration_s} tail_s={tail_s}",
        "NC-baseline (model = exact copy of the wet reference): "
        + ("CONTROL-OK (PASS, both budget and tail-region gate)"
           if baseline_ok and baseline["tail_check"]["ok"]
           else "CONTROL-BROKEN (baseline did not PASS!)"),
        f"NC-drop-tail (model truncated {DROP_S}s before the declared tail "
        "span): "
        + ("CONTROL-OK (FAILS the verdict via the tail-region gate)"
           if drop_failed else "CONTROL-BROKEN (truncation NOT detected!)"),
        "  whole-render budget alone on the truncated model: "
        + ("PASSED TRIVIALLY (overlap is byte-identical to the reference) "
           "-- confirms the tail gate is load-bearing, not redundant with "
           "the existing budget check"
           if budget_fooled else
           "also failed (does not by itself demonstrate the gap the tail "
           "check closes)"),
    ]
    status_ok = (baseline_ok and baseline["tail_check"]["ok"] and drop_failed)
    doc = {
        "schema_version": 1,
        "issue": 93,
        "claim": "negative control: drop-tail truncation on an existing "
                 "committed wet fixture must FAIL the shared comparator's "
                 "verdict via the new tail-region gate",
        "fixture": {"slug": SLUG, "sequence": SEQ,
                    "ref_wav": os.path.relpath(ref_path, REPO),
                    "fixture_meta": os.path.relpath(meta_path, REPO)},
        "drop_s": DROP_S,
        "baseline": baseline,
        "dropped_tail": dropped,
        "status": "PASS" if status_ok else "FAIL (broken control!)",
    }
    with open(os.path.join(OUT, "shared-comparator-drop-tail-summary.json"), "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(OUT, "shared-comparator-drop-tail-transcript.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
        f.write("status: " + doc["status"] + "\n")
    for l in lines:
        print(l)
    print("status:", doc["status"])
    return 0 if status_ok else 1


if __name__ == "__main__":
    sys.exit(main())
