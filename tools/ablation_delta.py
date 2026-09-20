#!/usr/bin/env python3
"""SXT-014: coarse numeric deltas for FX ablation renders (DIAGNOSTIC ONLY).

Compares every ablation variant against its preset+sequence ORIGINAL render
(never against a re-normalized or time-warped copy) and reports:

  - bit-identity (SHA-256 of the WAV) -- exactness, not magnitude;
  - sample-level max/mean absolute difference;
  - block-RMS envelope deltas (10 ms blocks): mean/max |dB| difference and
    envelope correlation;
  - coarse band energies (four bands via windowed FFT): per-band delta dB;
  - tail RMS delta (last 2.0 s) -- where delay/reverb differences concentrate.

Outputs per-pair JSON under reports/sxt-014/deltas/, an aggregate
reports/sxt-014/ablation-summary.json, and a printed summary table.

 CAVEAT (normative, issue #9): these numeric deltas are DIAGNOSTIC. They do
 NOT establish essential/optional/unresolved effect labels, preset support,
 fidelity, or musical usefulness. Labels require listening records and are
 BLOCKED-on-human. "near-zero-delta" flags are heuristic candidates for
 configured-but-inaudible slots, left unresolved by this tool.

Backend: Python stdlib by default; numpy is used for the FFT only when
importable (the backend is recorded in every JSON; cross-backend float
agreement is not claimed beyond the reported roundings).
"""

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ABLATIONS = os.path.join(REPO, "reports", "sxt-014", "ablations")
DELTAS = os.path.join(REPO, "reports", "sxt-014", "deltas")
SUMMARY = os.path.join(REPO, "reports", "sxt-014", "ablation-summary.json")
REPEATABILITY = os.path.join(REPO, "reports", "sxt-012", "repeatability.json")

BLOCK = 480          # 10 ms at 48 kHz
FFT_SIZE = 4096
BANDS_HZ = [(0.0, 150.0), (150.0, 1000.0), (1000.0, 6000.0), (6000.0, 24000.0)]
FLOOR = 1e-12
NEAR_ZERO_MAX_ABS_DIFF = 2.0 ** -13
NEAR_ZERO_RMS_DELTA_DB = -60.0
NEAR_ZERO_BAND_DELTA_DB = 0.5
SR = 48000
TAIL_S = 2.0


class Refuse(Exception):
    pass


def backend():
    try:
        import numpy  # noqa: F401
        return "numpy+stdlib"
    except Exception:
        return "stdlib"


def tool_version():
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception as e:  # pragma: no cover
        commit = f"unavailable: {e}"
    return {"repo_commit": commit, "script_sha256": _sha(os.path.abspath(__file__)),
            "fft_backend": backend()}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise Refuse(f"{path}: expected mono 16-bit WAV")
        frames = w.readframes(w.getnframes())
    n = len(frames) // 2
    samples = list(struct.unpack("<%dh" % n, frames))
    return [s / 32768.0 for s in samples], n


def rms(x, lo, hi):
    if hi <= lo:
        return 0.0
    acc = 0.0
    for v in x[lo:hi]:
        acc += v * v
    return math.sqrt(acc / (hi - lo))


def block_rms_curve(x):
    out = []
    for lo in range(0, len(x), BLOCK):
        out.append(rms(x, lo, min(lo + BLOCK, len(x))))
    return out


def pearson(a, b):
    if len(a) != len(b) or len(a) < 2:
        return None
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0.0 or db == 0.0:
        return None
    return num / (da * db)


def db(x):
    return 10.0 * math.log10(max(x, FLOOR))


def hann(n):
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * k / (n - 1)) for k in range(n)]


def fft_magnitude2(x):
    """Iterative radix-2 FFT power spectrum (stdlib path)."""
    n = len(x)
    if n & (n - 1):
        raise Refuse("FFT size must be a power of two")
    re = list(x)
    im = [0.0] * n
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wr, wi = math.cos(ang), math.sin(ang)
        for start in range(0, n, length):
            cr, ci = 1.0, 0.0
            half = length // 2
            for k in range(start, start + half):
                k2 = k + half
                tr = re[k2] * cr - im[k2] * ci
                ti = re[k2] * ci + im[k2] * cr
                re[k2] = re[k] - tr
                im[k2] = im[k] - ti
                re[k] += tr
                im[k] += ti
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1
    return [re[k] * re[k] + im[k] * im[k] for k in range(n // 2)]


def band_energies(x, use_numpy):
    win = hann(FFT_SIZE)
    acc = [0.0] * len(BANDS_HZ)
    bin_hz = SR / FFT_SIZE
    edges = [max(1, int(lo / bin_hz)) for lo, _ in BANDS_HZ]
    edges = [e if i else 0 for i, e in enumerate(edges)]
    hi_edges = [int(hi / bin_hz) for _, hi in BANDS_HZ]
    if use_numpy:
        import numpy as np
        w = np.array(win)
        step = FFT_SIZE
        for lo in range(0, len(x) - FFT_SIZE + 1, step):
            seg = np.array(x[lo:lo + FFT_SIZE]) * w
            spec = np.abs(np.fft.rfft(seg)) ** 2
            for bi, (elo, ehi) in enumerate(zip(edges, hi_edges)):
                acc[bi] += float(np.sum(spec[elo:max(ehi, elo + 1)]))
    else:
        step = FFT_SIZE
        for lo in range(0, len(x) - FFT_SIZE + 1, step):
            seg = [x[lo + k] * win[k] for k in range(FFT_SIZE)]
            spec = fft_magnitude2(seg)
            for bi, (elo, ehi) in enumerate(zip(edges, hi_edges)):
                acc[bi] += sum(spec[elo:max(ehi, elo + 1)])
    return acc


def compare(anchor_path, variant_path, anchor_sc, variant_sc, use_numpy):
    if anchor_sc["wav"]["sha256"] == variant_sc["wav"]["sha256"]:
        return {"bit_identical": True, "verdict": "BIT-IDENTICAL",
                "near_zero_delta_candidate": False}
    a, na = read_wav(anchor_path)
    b, nb = read_wav(variant_path)
    if na != nb:
        raise Refuse(f"frame count mismatch: {na} vs {nb} ({variant_path})")
    max_abs = 0.0
    mean_abs = 0.0
    for xa, xb in zip(a, b):
        d = abs(xa - xb)
        if d > max_abs:
            max_abs = d
        mean_abs += d
    mean_abs /= na

    ra = block_rms_curve(a)
    rb = block_rms_curve(b)
    rms_deltas = [abs(db(y + FLOOR) - db(x + FLOOR)) for x, y in zip(ra, rb)]
    mean_rms_db = sum(rms_deltas) / len(rms_deltas)
    max_rms_db = max(rms_deltas)
    corr = pearson(ra, rb)

    ea = band_energies(a, use_numpy)
    eb = band_energies(b, use_numpy)
    band_db = {f"{int(lo)}-{int(hi)}Hz": round(db(eb[i]) - db(ea[i]), 3)
               for i, (lo, hi) in enumerate(BANDS_HZ)}

    tail_n = min(int(TAIL_S * SR), na // 2)
    ta = rms(a, na - tail_n, na)
    tb = rms(b, na - tail_n, na)
    tail_db = db(tb) - db(ta)

    near_zero = (max_abs < NEAR_ZERO_MAX_ABS_DIFF
                 and mean_rms_db < -NEAR_ZERO_RMS_DELTA_DB
                 and all(abs(v) < NEAR_ZERO_BAND_DELTA_DB for v in band_db.values()))

    return {
        "bit_identical": False,
        "max_abs_sample_diff": round(max_abs, 9),
        "mean_abs_sample_diff": round(mean_abs, 9),
        "block_rms": {"block_samples": BLOCK,
                      "mean_abs_delta_db": round(mean_rms_db, 3),
                      "max_abs_delta_db": round(max_rms_db, 3),
                      "envelope_correlation": round(corr, 6) if corr is not None else None},
        "band_delta_db": band_db,
        "tail_rms_delta_db": round(tail_db, 3),
        "near_zero_delta_candidate": near_zero,
        "verdict": ("NEAR-ZERO-CANDIDATE (unresolved; diagnostic only)" if near_zero
                    else "MEASURABLE-DIFFERENCE"),
    }


def load_sidecars():
    groups = {}
    for dirpath, _dirs, files in os.walk(ABLATIONS):
        for fn in sorted(files):
            if not fn.endswith(".json") or fn.startswith("run-"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as f:
                sc = json.load(f)
            key = (sc["preset"]["slug"], sc["sequence"]["id"])
            groups.setdefault(key, []).append((path, sc))
    for key in groups:
        groups[key].sort(key=lambda t: t[1]["ablation_id"])
    return groups


def repeatability_bounds():
    try:
        with open(REPEATABILITY, encoding="utf-8") as f:
            rep = json.load(f)
        return {fx["fixture_id"]: fx for fx in rep["fixtures"]}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ablations", default=ABLATIONS)
    ap.add_argument("--out", default=DELTAS)
    args = ap.parse_args()
    use_numpy = backend() == "numpy+stdlib"

    groups = load_sidecars()
    os.makedirs(args.out, exist_ok=True)
    summary_rows = []
    per_pair_written = 0

    for (slug, sid), entries in sorted(groups.items()):
        anchors = [p for p, sc in entries if sc["kind"] == "original"]
        if not anchors:
            print(f"SKIP {slug}/{sid}: no original anchor", file=sys.stderr)
            continue
        anchor_path, anchor_sc = next((p, sc) for p, sc in entries if sc["kind"] == "original")
        for path, sc in entries:
            if sc["kind"] == "original" and path == anchor_path:
                continue
            variant = os.path.basename(path)[: -len(".json")]
            metrics = compare(os.path.join(REPO, anchor_sc["wav"]["path"]),
                              os.path.join(REPO, sc["wav"]["path"]),
                              anchor_sc, sc, use_numpy)
            pair = {
                "schema_version": 1,
                "issue": "SXT-014",
                "caveat": "numeric deltas are DIAGNOSTIC ONLY; effect labels require "
                          "listening records (BLOCKED-on-human); near-zero flags are "
                          "heuristic candidates, left unresolved",
                "preset": {"slug": slug, "path": sc["preset"]["path"]},
                "sequence": sc["sequence"],
                "anchor": {"sidecar": os.path.relpath(anchor_path, REPO),
                           "wav": anchor_sc["wav"]},
                "variant": {"sidecar": os.path.relpath(path, REPO),
                            "wav": sc["wav"], "kind": sc["kind"], "label": sc["label"],
                            "adapted": sc.get("adapted", False),
                            "slot": sc.get("slot"),
                            "mutated_slots": sc.get("mutated_slots")},
                "metrics": metrics,
                "tool": tool_version(),
            }
            repeatability_note = None
            if sc["kind"] == "offslot-ctrl":
                fx = repeatability_bounds().get(f"{slug}__{sid}")
                repeatability_note = {
                    "class": sc.get("repeatability_class"),
                    "expect_bit_identity": sc.get("repeatability_class") == "bit-identical",
                    "reference": "reports/sxt-012/repeatability.json",
                    "wet_repeat_relative_max_diff": (fx or {}).get("wet", {}).get("relative_max_diff"),
                }
                pair["repeatability_note"] = repeatability_note
            out_dir = os.path.join(args.out, slug)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, variant + ".json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(pair, f, indent=2, sort_keys=True)
                f.write("\n")
            per_pair_written += 1
            m = pair["metrics"]
            row = {
                "preset": slug, "sequence": sid, "variant": variant,
                "kind": sc["kind"], "adapted": sc.get("adapted", False),
                "slot": sc.get("slot"),
                "bit_identical": m["bit_identical"],
                "near_zero_delta_candidate": m.get("near_zero_delta_candidate", False),
                "verdict": m["verdict"],
                "mean_block_rms_delta_db": (None if m["bit_identical"]
                                            else m["block_rms"]["mean_abs_delta_db"]),
                "max_block_rms_delta_db": (None if m["bit_identical"]
                                           else m["block_rms"]["max_abs_delta_db"]),
                "max_abs_sample_diff": (None if m["bit_identical"]
                                        else m["max_abs_sample_diff"]),
                "band_delta_db": (None if m["bit_identical"] else m["band_delta_db"]),
                "tail_rms_delta_db": (None if m["bit_identical"] else m["tail_rms_delta_db"]),
                "delta_json": os.path.relpath(out_path, REPO),
                "label_tool_side": sc["label"],
            }
            if repeatability_note:
                row["repeatability_note"] = repeatability_note
            summary_rows.append(row)
            print(f"{slug:>9} {sid:<22} {variant:<44} "
                  f"{'BIT-IDENT' if m['bit_identical'] else 'dX=%8.3f' % (m['block_rms']['mean_abs_delta_db'] if not m['bit_identical'] else 0):>10} dB "
                  f"{'NEAR-ZERO?' if m.get('near_zero_delta_candidate') else ''}")

    aggregate = {
        "schema_version": 1,
        "issue": "SXT-014",
        "claim_scope": "reference-vs-reference ablation deltas of the pinned engine under the "
                       "SXT-012 render policies. Diagnostic only: no essential/optional/"
                       "unresolved labels, no preset-support claim, no fidelity claim, no "
                       "musical-quality claim.",
        "caveat": "NUMERIC DELTAS ARE DIAGNOSTIC ONLY - LABELS REQUIRE LISTENING "
                  "(BLOCKED-ON-HUMAN). Near-zero-delta slots are flagged as candidates and "
                  "left unresolved.",
        "tool": tool_version(),
        "thresholds": {"near_zero_max_abs_sample_diff": NEAR_ZERO_MAX_ABS_DIFF,
                       "near_zero_mean_block_rms_delta_db": NEAR_ZERO_RMS_DELTA_DB,
                       "near_zero_band_delta_db": NEAR_ZERO_BAND_DELTA_DB},
        "rows": summary_rows,
        "totals": {"pairs_compared": per_pair_written,
                   "bit_identical": sum(1 for r in summary_rows if r["bit_identical"]),
                   "near_zero_candidates": sum(1 for r in summary_rows
                                               if r["near_zero_delta_candidate"]),
                   "measurable": sum(1 for r in summary_rows
                                     if not r["bit_identical"] and not r["near_zero_delta_candidate"])},
    }
    with open(SUMMARY, "w", encoding="utf-8") as f:
        json.dump(aggregate, f, indent=2, sort_keys=True)
        f.write("\n")
    print()
    print(json.dumps(aggregate["totals"], indent=2))
    print("CAVEAT: numeric deltas are diagnostic only -- essential/optional/unresolved "
          "labels require listening records and remain BLOCKED-on-human (issue #9).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
