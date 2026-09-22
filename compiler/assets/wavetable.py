#!/usr/bin/env python3
"""SXT-026 wavetable ASSET COMPILER (`compiler/assets/wavetable.py`).

From an external `.wt` file (path passed at compile time; the payload itself
STAYS EXTERNAL — it is never copied into this repository) this module emits an
**asset manifest record** embedded into the SXT-020 patch image under
`derived.wavetable_asset_manifests`:

  * identity        — SHA-256 + size + asset-root-relative path (hashes only
                      are stored in-repo; decision-records/0004),
  * dims            — frame length (wave_size), frame count (wave_count),
                      sample format (float32 / int15 / int16), sample flags,
                      frame period dt = 1/wave_size,
  * mip/AA structure— engine mip-map construction levels, the oscillator's
                      selectable mip levels 0..6 with the pinned selection
                      thresholds, and the required interpolation modes,
  * residency       — classification per the model/resources policy: the
                      payload is a read-only external flash asset; the on-chip
                      working set is the mip level in play.

Identity is load-bearing: `verify` re-hashes every asset referenced by an
image against the external tree and ABORTS (exit 2) on any mismatch or
missing file. A substituted/flipped table therefore cannot enter a build
(negative control NC-A in reports/sxt-026/).

Structure is READ from the pinned engine (cited, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71
  src/common/dsp/Wavetable.cpp            BuildWT / MipMapWT / RequiredWTSize
  src/common/dsp/Wavetable.h              wt flags, max_wtable_size/subtables
  src/common/dsp/oscillators/WavetableOscillator.cpp  convolute mip selection
  src/common/dsp/vembertech/basic_dsp.h   i152float_block / i162float_block
  resources/data/wavetables/WT fileformat.txt         .wt container layout
No engine source, table bytes, or asset bytes are reproduced here.
"""

import argparse
import hashlib
import json
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WT_MAGIC = b"vawt"

# wt flag bits — resources/data/wavetables/WT fileformat.txt and
# src/common/dsp/Wavetable.h (wtf_is_sample etc.)
WTF_IS_SAMPLE = 0x0001
WTF_LOOP_SAMPLE = 0x0002
WTF_INT16 = 0x0004
WTF_INT16_IS_16 = 0x0008
WTF_HAS_METADATA = 0x0010

# Pinned engine limits — src/common/dsp/Wavetable.h
MAX_WTABLE_SIZE = 4096
MAX_SUBTABLES = 512
MAX_MIPMAP_LEVELS = 16

# Oscillator mip selection — WavetableOscillator::convolute (pinned):
#   a = wt.dt * pitchmult_inv; wtbias = 1.8; mipmap = k when
#   a < 2^-k * wtbias (k = 6..1) and the FULL table size ts >= 2^(k+1)
#   (mip 6 needs ts >= 128, mip 1 needs ts >= 4); mipmap 0 otherwise.
# Thresholds below are precomputed in float32 exactly as the engine
# evaluates them (0.015625f * 1.8f ...).
WTBIAS = 1.8
MIP_THRESHOLDS = []  # level -> (threshold_a_f32, min_full_table_size)
for _k in (6, 5, 4, 3, 2, 1):
    _thr = struct.unpack("f", struct.pack("f", (2.0 ** -_k) * WTBIAS))[0]
    MIP_THRESHOLDS.append((_k, _thr, 1 << (_k + 1)))

MORPH_MODES = {
    "xt14_continuous": "deformContinuous (FeatureDeform::XT_14; default for "
                       "newly-saved patches; tableipol is a continuous frame "
                       "position, 2-entry linear blend into tid/tid+1)",
    "xt134_legacy": "deformLegacy (FeatureDeform::XT_134_EARLIER; patches "
                    "saved by XT 1.3.4 or earlier; integer tableid plus "
                    "frame fraction, same 2-entry linear blend)",
}
TABLE_READ_INTERPOLATION = (
    "per-frame LINEAR 2-entry blend between tableid and tableid+1 "
    "(deformContinuous/deformLegacy, WavetableOscillator.cpp); the impulse "
    "train is band-limited by the 12-tap / 256-phase windowed-sinc FIR "
    "(FIRipol_M=256, FIRipol_N=12, SurgeStorage.h) shared with SXT-022"
)


class AssetIdentityError(Exception):
    """Asset identity/residency verification failed — the build must ABORT."""


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def parse_wt(data, origin):
    """Parse a .wt container (header + dims; payload digest only).

    Fail-closed: any structural problem raises AssetIdentityError.
    """
    if len(data) < 12:
        raise AssetIdentityError("%s: truncated header (%d bytes)" % (origin, len(data)))
    if data[:4] != WT_MAGIC:
        raise AssetIdentityError("%s: bad magic %r (expected 'vawt')" % (origin, data[:4]))
    wave_size, = struct.unpack("<I", data[4:8])
    wave_count, flags = struct.unpack("<HH", data[8:12])
    if wave_size <= 0 or wave_size & (wave_size - 1):
        raise AssetIdentityError("%s: wave_size %d is not a power of two" % (origin, wave_size))
    if wave_size > MAX_WTABLE_SIZE:
        raise AssetIdentityError("%s: wave_size %d > max_wtable_size %d"
                                 % (origin, wave_size, MAX_WTABLE_SIZE))
    if wave_count <= 0 or wave_count > MAX_SUBTABLES:
        raise AssetIdentityError("%s: wave_count %d outside 1..max_subtables %d"
                                 % (origin, wave_count, MAX_SUBTABLES))
    bytes_per_frame = 2 if (flags & WTF_INT16) else 4
    need = 12 + wave_size * wave_count * bytes_per_frame
    if len(data) < need:
        raise AssetIdentityError("%s: truncated payload (%d < %d bytes)"
                                 % (origin, len(data), need))
    if flags & WTF_INT16:
        fmt = "int16_full" if (flags & WTF_INT16_IS_16) else "int15"
    else:
        fmt = "float32"
    levels = 1
    while (1 << levels) < wave_size and levels < MAX_MIPMAP_LEVELS:
        levels += 1
    return {
        "wave_size": wave_size,
        "wave_count": wave_count,
        "flags": flags,
        "format": fmt,
        "is_sample": bool(flags & WTF_IS_SAMPLE),
        "loop_sample": bool(flags & WTF_LOOP_SAMPLE),
        "has_metadata": bool(flags & WTF_HAS_METADATA),
        "bytes": len(data),
        "payload_bytes": wave_size * wave_count * bytes_per_frame,
        "sha256": sha256_bytes(data),
        # BuildWT: dt = 1/size (Wavetable.cpp) — exactly representable
        "dt": 1.0 / wave_size,
        "mipmap_built_levels": levels,  # MipMapWT(): 1 + built levels 1..levels-1
    }


def expected_mips(hd):
    """Mip levels the oscillator can select, with pinned thresholds.

    convolute() selects mip k (6..1) when a < thr_k AND full size >= min_ts;
    mip 0 is unconditional. A level is serviceable only if the table has
    data at that level (size >> k >= 1 for built levels; the engine builds
    levels 1..mipmap_built_levels-1).
    """
    ts = hd["wave_size"]
    out = [{"level": 0, "frame_entries": ts, "threshold_a": None,
            "min_full_size": None, "serviceable": True}]
    for k, thr, min_ts in MIP_THRESHOLDS:
        out.append({"level": k, "frame_entries": ts >> k,
                    "threshold_a": thr, "min_full_size": min_ts,
                    "serviceable": bool(k < hd["mipmap_built_levels"])})
    return out


def working_set_bytes(hd):
    """On-chip working set per mip level in the declared audio word.

    The engine reads tables through TableF32WeakPointers (float32 words);
    SXT-016 probe_osc counts the active-mip working set as the state-RAM
    resident part (24-bit words declared for the audio path). Both the
    float32-byte and declared-24-bit-word figures are recorded so the
    SXT-015/016 accounting can be reconciled without re-deriving either.
    """
    f32, w24 = [], []
    for k in range(hd["mipmap_built_levels"]):
        n = hd["wave_size"] >> k
        f32.append(n * 4)
        w24.append(n * 3)
    return {"float32_bytes_per_level": f32, "declared_24bit_words_bytes_per_level": w24}


def build_manifest(hd, asset_rel, expected_sha256, scene, osc, name):
    """Manifest record for one wavetable asset reference.

    expected_sha256 comes from the normalized graph's resolved asset record
    (`res: [[path, sha256], ...]`); a mismatch ABORTS the compile.
    """
    if expected_sha256 is not None and hd["sha256"] != expected_sha256:
        raise AssetIdentityError(
            "asset identity mismatch for %s: external file sha256 %s != "
            "normalized-graph record %s — ABORT (a substituted or corrupted "
            "wavetable must never enter an image)" % (asset_rel, hd["sha256"],
                                                      expected_sha256))
    ws = working_set_bytes(hd)
    return {
        "scene": scene,
        "osc": osc,
        "name": name,
        "identity": {
            "path": asset_rel,
            "sha256": hd["sha256"],
            "bytes": hd["bytes"],
            "magic": WT_MAGIC.decode("ascii"),
            "note": "hashes/metadata only in-repo; the payload stays in the "
                    "external pinned tree (decision-records/0004)",
        },
        "identity_verified": True,
        "dims": {
            "wave_size": hd["wave_size"],
            "wave_count": hd["wave_count"],
            "format": hd["format"],
            "format_note": {
                "float32": "native float32 frames",
                "int15": "int16 frames, 15-bit (scale 1/16384; exact binary "
                         "scaling — the fixed model's Q10.21 table word is "
                         "s << 7)",
                "int16_full": "int16 frames, full 16-bit (scale 1/32768)",
            }[hd["format"]],
            "is_sample": hd["is_sample"],
            "loop_sample": hd["loop_sample"],
            "has_metadata": hd["has_metadata"],
            "dt": hd["dt"],
            "embedded_size_bytes": hd["bytes"],
        },
        "mip": {
            "built_levels": hd["mipmap_built_levels"],
            "construction": "MipMapWT(): per level a 63-tap halfband "
                            "(hrfilter[63], Wavetable.cpp) lowpass + decimate "
                            "of the previous level, float32; level 0 is the "
                            "file payload as converted by i15/i162float_block",
            "osc_selectable": expected_mips(hd),
            "selection_rule": "a = dt * pitchmult_inv; mip = highest k in "
                              "6..1 with a < threshold_k and wave_size >= "
                              "min_full_size_k, else 0 (convolute, pinned)",
            "anti_aliasing": TABLE_READ_INTERPOLATION,
        },
        "morph": {
            "modes": MORPH_MODES,
            "default": "xt14_continuous with extend_range=true (nointerp=0)",
            "unison_cap": 16,
        },
        "residency": {
            "payload": "external_flash_asset",
            "writable": False,
            "on_chip_working_set": ws,
            "active_mip_working_set_bytes_f32": ws["float32_bytes_per_level"],
            "full_built_f32_bytes": sum(ws["float32_bytes_per_level"]),
            "policy": "model/resources policy: read-only assets live in flash "
                      "(flash_assets block of the image); the on-chip working "
                      "set is the mip level in play (SXT-016 probe_osc row); "
                      "flash is never writable delay/reverb storage",
        },
    }


def resolve_asset_path(asset_root, graph_path):
    """Map a normalized-graph asset path ('wavetables/Basic/Triangle.wt' or
    legacy 'Basic/Triangle.wt') into the external asset root."""
    rel = graph_path.replace("\\", "/")
    for cand in (rel, os.path.join("wavetables", rel)):
        p = os.path.join(asset_root, cand)
        if os.path.isfile(p):
            return p, cand.replace(os.sep, "/")
    raise AssetIdentityError("asset file not found under root %s: %s"
                             % (asset_root, graph_path))


def load_and_manifest(asset_root, graph_path, expected_sha256, scene, osc, name):
    p, rel = resolve_asset_path(asset_root, graph_path)
    with open(p, "rb") as f:
        hd = parse_wt(f.read(), p)
    return build_manifest(hd, rel, expected_sha256, scene, osc, name)


def manifests_for_graph(graph, asset_root):
    """All manifest records for one normalized graph (empty if no wta)."""
    out = []
    for w in graph.get("wta", []):
        res = w.get("res") or []
        if not res:
            raise AssetIdentityError(
                "wavetable record %r (scene %s osc %s) has no resolved asset "
                "path; an image must reference a verifiable asset"
                % (w.get("name"), w.get("sc"), w.get("osc")))
        gpath, sha = res[0][0], res[0][1]
        out.append(load_and_manifest(asset_root, gpath, sha,
                                     w.get("sc"), w.get("osc"), w.get("name")))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_image(path):
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from compiler import compile as C  # noqa: PLC0415 (import cycle guard)

    with open(path, "rb") as f:
        return C.parse_image(f.read())


def cmd_manifest(args):
    res = []
    for gp in args.asset:
        if ":" in os.path.basename(gp):
            gpath, sha = gp.rsplit(":", 1)
        else:
            gpath, sha = gp, None
        m = load_and_manifest(args.asset_root, gpath, sha, None, None,
                              os.path.basename(gpath))
        res.append(m)
    blob = json.dumps({"artifact": "sxt-026-wavetable-asset-manifest",
                       "asset_root_note": "payload read in place from the "
                                          "external pinned tree; nothing was "
                                          "copied", "manifests": res},
                      sort_keys=True, indent=1, allow_nan=False)
    print(blob)
    return 0


def cmd_verify(args):
    """End-to-end asset identity gate: image <-> external file.

    ABORTS (exit 2) on: missing file, hash mismatch, unparsable header, or a
    manifest embedded in the image disagreeing with the external file.
    """
    parsed = _load_image(args.image)
    body = parsed["body"]
    wta = body["graph"].get("wavetable_assets", [])
    manifests = body.get("derived", {}).get("wavetable_asset_manifests", [])
    checked, fails = 0, []
    for w in wta:
        for gpath, sha in (w.get("res") or []):
            checked += 1
            try:
                p, rel = resolve_asset_path(args.asset_root, gpath)
            except AssetIdentityError as e:
                fails.append(str(e))
                continue
            with open(p, "rb") as f:
                hd = parse_wt(f.read(), p)
            if hd["sha256"] != sha:
                fails.append("HASH MISMATCH %s: external %s != image record %s"
                             % (rel, hd["sha256"], sha))
                continue
            for m in manifests:
                if m.get("identity", {}).get("sha256") == sha:
                    if m["identity"]["path"] != rel:
                        fails.append("manifest path drift for %s: %s vs %s"
                                     % (sha, m["identity"]["path"], rel))
                    if m["dims"]["wave_size"] != hd["wave_size"] or \
                       m["dims"]["wave_count"] != hd["wave_count"]:
                        fails.append("manifest dims drift for %s" % rel)
    for f_ in fails:
        print("ABORT: %s" % f_, file=sys.stderr)
    print(json.dumps({"image": os.path.basename(args.image),
                      "assets_checked": checked, "failures": len(fails),
                      "verdict": "PASS" if not fails else "ABORT"},
                     sort_keys=True))
    return 2 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest", help="emit manifest records for .wt files")
    m.add_argument("--asset-root", required=True,
                   help="external asset root (resources/data of the pinned tree)")
    m.add_argument("--asset", action="append", required=True,
                   help="asset path (optionally 'path:expected_sha256')")
    m.set_defaults(func=cmd_manifest)

    v = sub.add_parser("verify", help="verify image asset identity end-to-end")
    v.add_argument("--image", required=True, help="patch image (.image.bin)")
    v.add_argument("--asset-root", required=True)
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssetIdentityError as e:
        print("ABORT: %s" % e, file=sys.stderr)
        sys.exit(2)
