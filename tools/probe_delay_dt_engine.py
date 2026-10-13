#!/usr/bin/env python3
"""SXT-023 / issue #16 deliverable 1: engine-side impulse-train probe of the
Delay's effective read position d(t), per instance and per channel, diffed
against the model's delay-time lag trajectory.

Extends the tools/diagnose_delay_engine_probe.py pattern (fresh instance,
loadPatch of the census-verified preset, the fixture harness's reset calls,
its 375-block silent settle, 3x bit-identical determinism gate per render).
The pinned engine is imported at RUNTIME only; no Surge code, table or asset
is copied (Apache-2.0 tooling over the external GPL-3.0-or-later oracle).

Method (per Delay instance):

* Scene A is turned into a linear audio-input path (osc 1 = Audio Input,
  other oscillators/noise/ring muted, filters and waveshaper off, amp EG
  attack 0 / sustain 1, one held note) and an impulse train (one 0.25
  impulse every PERIOD samples) is fed through processMultiBlockWithInput.
* The probed instance is neutralised AFTER its read so that its output is
  exactly its interpolated read of its own input: feedback 0, crossfeed 0,
  highcut at max (LP above Nyquist = passthrough), lowcut at min, width
  0 dB (mid/side identity), mix 1. Only FX parameter VALUES change
  (setParamVal); FX type changes, which would re-init the effect, are not
  used, so the LFO/lag timeline is the fixture's (SurgeSynthesizer::
  setParameter01 reloads FX only for ct_fxtype).
* The instance's input x is recovered exactly from a companion render
  (ains: the instance at mix 0; send: W/X/Z differencing with the send
  level at 0), and its output y from the wet render.
* For every pulse the wet window is fitted, by least squares over integer
  delays and all 256 sinc phases, with y[n] = sum_t T[ph][t] x[n-i-12+t]
  (Delay.h processBlock read: rp = wpos - i_dtime + k - FIRipol_N, sinc
  phase (int)(FIRipol_M*(i_dtime+1 - v))); T is the repository's own
  table, recomputed from the cited construction formula
  (model/effects/delay/sinc_table.py). The fit gives (i_dtime, phase) and
  v_est = i + 1 - (ph + 0.5)/256, timestamped at the wet pulse's energy
  centroid. Resolution: 1/256 sample.

The model side replays the DelayModel control plane + time lags over the
same block schedule (v does not depend on audio). Variants are reported so
each mechanism is visible, and the pre-revision model is a live negative
control for the probe (it must fail the declared d(t) check).

Diagnostic evidence, not a fixture of record and not a support claim.
"""
import argparse
import copy
import hashlib
import json
import os
import platform
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "fixtures"))

import numpy as np  # noqa: E402

import oracle_common as oc  # noqa: E402
import model.effects.delay.delay_model as dm  # noqa: E402
from model.effects.qmath import qadd, qmul, FRAC  # noqa: E402
from model.effects.delay.sinc_table import TABLE_Q, FIRIPOL_M, FIRIPOL_N  # noqa: E402

SR = 48000
BLOCK = 32
FIXTURE_SETTLE = 375          # int(0.25 * 48000) // 32 (fixture harness)
PRE_REVISION_SETTLE = 240     # run_fx_model.py before issue #16
PERIOD = 512                  # impulse spacing (samples)
FIRST_IMPULSE = 1024
AMP = 0.25
WINDOW = 48
# Declared d(t) check (fixed before measuring): replaying the engine's read
# with the model's per-sample v(n) must rebuild EVERY wet pulse to within
# -40 dB relative energy, i.e. no pulse may carry a read-position error of
# the one-sinc-phase-bin class (1/256 sample on a band-limited pulse is
# ~ -40 dB) or worse.
REPLAY_CHECK_DB = -40.0
PRESETS = {
    "metallic": "resources/data/patches_factory/Plucks/Metallic.fxp",
    "dexie": "resources/data/patches_3rdparty/John Valentine/Keys/Dexie Swirly E-Piano.fxp",
}
P_FEEDBACK, P_CROSSFEED, P_LOWCUT, P_HIGHCUT = 2, 3, 4, 5
P_DEPTH, P_MIX, P_WIDTH = 7, 10, 11
T_SINC = (np.array(TABLE_Q[:FIRIPOL_M * FIRIPOL_N], dtype=np.float64)
          / float(1 << 29)).reshape(FIRIPOL_M, FIRIPOL_N)


def sha256_buf(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def sha256_path(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------- engine side
def render(surgepy, preset_abs, n_blocks, fx_over, send_level=None, repeats=3):
    """One probe render (3x determinism gate). fx_over: {slot: {pidx: val}}."""
    C = surgepy.constants
    bufs = []
    for _ in range(repeats):
        s = surgepy.createSurge(float(SR))
        try:
            if not s.loadPatch(preset_abs):
                raise RuntimeError("loadPatch failed: " + preset_abs)
            p = s.getPatch()
            sc = p["scene"][0]
            s.setParamVal(sc["osc"][0]["type"], C.ot_audioinput)
            for k in ("mute_o2", "mute_o3", "mute_noise", "mute_ring_12", "mute_ring_23"):
                s.setParamVal(sc[k], 1)
            for f in range(2):
                s.setParamVal(sc["filterunit"][f]["type"], 0)
            s.setParamVal(sc["wsunit"]["type"], 0)
            s.setParamVal(sc["adsr"][0]["a"], -8.0)
            s.setParamVal(sc["adsr"][0]["s"], 1.0)
            for slot, ov in fx_over.items():
                for pidx, val in ov.items():
                    s.setParamVal(p["fx"][slot]["p"][pidx], val)
            if send_level is not None:
                s.setParamVal(sc["send_level"][0], send_level)
            # the fixture harness's reset calls, then its settle
            s.pitchBend(0, 0)
            s.channelController(0, 64, 0)
            s.channelController(0, 1, 0)
            s.channelController(0, 11, 0)
            s.channelAftertouch(0, 0)
            s.allNotesOff()
            z = np.zeros((2, FIXTURE_SETTLE * BLOCK), dtype=np.float32)
            s.processMultiBlockWithInput(z, s.createMultiBlock(FIXTURE_SETTLE))
            s.playNote(0, 60, 100, 0)
            inp = np.zeros((2, n_blocks * BLOCK), dtype=np.float32)
            inp[:, FIRST_IMPULSE::PERIOD] = AMP
            out = s.createMultiBlock(n_blocks)
            s.processMultiBlockWithInput(inp, out)
            bufs.append(np.asarray(out, dtype=np.float32).copy())
        finally:
            del s
    hs = [sha256_buf(b) for b in bufs]
    if any(h != hs[0] for h in hs):
        raise RuntimeError("determinism gate failed: %s" % hs)
    if float(np.abs(bufs[0]).max()) >= 1.0:
        raise RuntimeError("probe render reached full scale (hardclip risk)")
    return bufs[0], hs


def neutral(depth=None):
    ov = {P_FEEDBACK: 0.0, P_CROSSFEED: 0.0, P_LOWCUT: -60.0, P_HIGHCUT: 70.0,
          P_WIDTH: 0.0, P_MIX: 1.0}
    if depth is not None:
        ov[P_DEPTH] = depth
    return ov


def instance_io(surgepy, preset_abs, n_blocks, cfg, which, depth=None):
    """Return (x, y, render_records) for instance `which` (index into
    ains + sends of the fx_inputs chain)."""
    ains = cfg["chain"]["ains"]
    sends = cfg["chain"]["sends"]
    recs = []
    if which < len(ains):
        slot = ains[which]["slot"]
        sl = 0.0 if sends else None        # silence any send delay
        wet, h1 = render(surgepy, preset_abs, n_blocks, {slot: neutral(depth)}, sl)
        dry_ov = neutral(depth)
        dry_ov[P_MIX] = 0.0
        dry, h2 = render(surgepy, preset_abs, n_blocks, {slot: dry_ov}, sl)
        recs += [{"render": "W", "sha256": h1[0]}, {"render": "D", "sha256": h2[0]}]
        return dry.astype(np.float64), wet.astype(np.float64), recs
    e = sends[which - len(ains)]
    slot = e["slot"]
    pass_ains = {a["slot"]: {P_MIX: 0.0} for a in ains}
    ov_w = dict(pass_ains)
    ov_w[slot] = neutral(depth)
    ov_x = copy.deepcopy(ov_w)
    ov_x[slot][P_MIX] = 0.0
    w, h1 = render(surgepy, preset_abs, n_blocks, ov_w)
    x, h2 = render(surgepy, preset_abs, n_blocks, ov_x)
    z, h3 = render(surgepy, preset_abs, n_blocks, ov_w, send_level=0.0)
    recs += [{"render": "W", "sha256": h1[0]}, {"render": "X", "sha256": h2[0]},
             {"render": "Z", "sha256": h3[0]}]
    z64 = z.astype(np.float64)
    return x.astype(np.float64) - z64, w.astype(np.float64) - z64, recs


def hp_prefilter(x, lowcut_f):
    """The probed instance's lowcut biquad cannot be deactivated through
    surgepy, so the probe parks it at its minimum (lowcut -60 -> ~13.75 Hz)
    and folds it into the input: HP is LTI once its coefficient lag has
    converged in the settle and commutes with the slowly time-varying read.
    Coefficients: the model's cited coeff_HP formula (DelayModel._hp, Q 0.707),
    applied in double precision as a TDF2 biquad."""
    omega = 2 * np.pi * 440.0 * dm.note_to_pitch_ignoring_tuning_d(lowcut_f) / SR
    a1, a2, b0, b1, b2 = [c / float(1 << FRAC[dm.C_FMT])
                          for c in dm.DelayModel._hp(omega, 0.707)]
    y = np.empty_like(x)
    r0 = r1 = 0.0
    for n, v in enumerate(x):
        o = b0 * v + r0
        r0 = b1 * v - a1 * o + r1
        r1 = b2 * v - a2 * o
        y[n] = o
    return y


def fit_pulses(x, y, lo, hi):
    """Per-pulse (i_dtime, phase) fit; returns rows (t_centroid, i, ph,
    v_est, rel_err)."""
    rows = []
    n_total = x.shape[0]
    for n0 in range(FIRST_IMPULSE, n_total - hi - 2 * WINDOW, PERIOD):
        pk = n0 + int(np.argmax(np.abs(x[n0:n0 + 64])))
        xs = x[pk - WINDOW // 2: pk + WINDOW // 2]
        if not np.any(xs):
            continue
        best_c, dc = None, None
        for d in range(lo, hi):
            c = float(np.dot(xs, y[pk - WINDOW // 2 + d: pk + WINDOW // 2 + d]))
            if best_c is None or c > best_c:
                best_c, dc = c, d
        n = np.arange(pk - WINDOW // 2 + dc, pk + WINDOW // 2 + dc)
        yw = y[n]
        cand = []
        for i in range(dc - 10, dc):
            X = np.stack([x[n - i - FIRIPOL_N + t] for t in range(FIRIPOL_N)], axis=1)
            e = ((X @ T_SINC.T - yw[:, None]) ** 2).sum(axis=0)
            ph = int(np.argmin(e))
            cand.append((float(e[ph]), i, ph))
        err, i, ph = min(cand)
        en = yw * yw
        # the single-phase LS fit weights each sample by its sensitivity to
        # the read position, ~|dy/dn|^2: timestamp at that centroid
        dy = np.gradient(yw)
        sens = dy * dy
        tc = float((n * sens).sum() / sens.sum())
        rows.append((tc, i, ph, i + 1 - (ph + 0.5) / FIRIPOL_M,
                     err / float(en.sum()), int(n[0])))
    return rows


def replay_rel_residual(x, y, rows, v_model):
    """Timestamp-free check: rebuild every wet pulse with the engine's own
    read formula (Delay.h processBlock) driven by the model's per-sample
    v(n), and return the per-pulse residual energy relative to the pulse
    (dB). This is the decisive d(t) comparison; the fitted v_est is the
    trajectory measurement."""
    out = []
    for r in rows:
        n = np.arange(r[5], r[5] + WINDOW)
        v = v_model[n]
        i = np.clip(v.astype(np.int64), BLOCK, (1 << 18) - FIRIPOL_N - 1)
        ph = np.clip(((i + 1 - v) * FIRIPOL_M).astype(np.int64), 0, FIRIPOL_M - 1)
        X = np.stack([x[n - i - FIRIPOL_N + t] for t in range(FIRIPOL_N)], axis=1)
        yh = (X * T_SINC[ph]).sum(axis=1)
        e = float(((y[n] - yh) ** 2).sum())
        out.append(10.0 * np.log10(max(e, 1e-300) / float((y[n] ** 2).sum())))
    return np.array(out)


# -------------------------------------------------------------- model side
class _Q43Lag(dm.Lag):
    """Pre-revision lag: Q24.43 round-half-up (no float32 grid)."""

    def process(self):
        C = dm.C_FMT
        self.v = qadd(qmul(self.v, self.lpinv, C, C, C),
                      qmul(self.target, self.lp, C, C, C), C)


class _UnfusedF32Lag(dm.Lag):
    """float32 lag computed UNFUSED: (float)((float)(v*lpinv) +
    (float)(target*lp)) -- the linux x86_64 build's evaluation."""

    def process(self):
        f2 = 2 * FRAC[dm.C_FMT]
        a = dm.f32_round_q43(self.v * self.lpinv, f2)
        b = dm.f32_round_q43(self.target * self.lp, f2)
        self.v = dm.f32_round_q43(a + b, FRAC[dm.C_FMT])


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


class _X86F32Control(dm.DelayModel):
    """DIAGNOSTIC ONLY (not the frozen model): the Delay.h setvars LFO and
    time-target expressions evaluated per operation in float32, unfused,
    as the linux x86_64 build computes them (lforate float; lfophase
    double; lfo_increment = (1e-11f + powf(2, depth/12) - 1) * blockSize;
    LFOval = 0.99f*LFOval +- inc; target = sampleRate * ratioInv *
    noteToPitch +- LFOval - FIRoffset). The frozen model rounds the target
    once (darwin's contraction of this chain is not measured)."""

    def _lfo_advance(self, ts_ratio_mod):
        p, st = self.p, self.st
        if not hasattr(self, "_ph"):
            self._ph, self._lv = 0.0, 0.0
        rate = _f32(_f32(dm.envelope_rate_linear_d(-p.mod_rate_f)) * _f32(ts_ratio_mod))
        self._ph += rate
        if self._ph > 0.5:
            self._ph -= 1.0
            st.lfo_dir = not st.lfo_dir
        a = _f32(_f32(self._depth_extended()) * _f32(1.0 / 12.0))
        inc = _f32(_f32(_f32(_f32(1e-11) + _f32(2.0 ** a)) - 1.0) * float(BLOCK))
        ca_lv = _f32(_f32(0.99) * self._lv)
        self._lv = _f32(ca_lv + inc) if st.lfo_dir else _f32(ca_lv - inc)
        st.lfoval = dm.to_q(self._lv, dm.C_FMT)
        st.lfophase = dm.to_q(self._ph, dm.C_FMT)
        return rate, dm.to_q(inc, dm.C_FMT)

    def _control(self, init):
        ctrl = super()._control(init)
        p, st = self.p, self.st

        def tgt(tf, sign):
            t1 = _f32(48000.0 * _f32(p.ts_ratio))
            t2 = _f32(t1 * _f32(dm.note_to_pitch_ignoring_tuning_d(_f32(12.0 * tf))))
            t3 = _f32(t2 + sign * self._lv)
            return dm.to_q(_f32(t3 - float(dm.FIR_OFFSET)), dm.C_FMT)

        t_r = p.time_l_f if p.time_r_deactivated else p.time_r_f
        ctrl["time_l_tgt"] = tgt(p.time_l_f, 1.0)
        ctrl["time_r_tgt"] = tgt(t_r, -1.0)
        st.time_l.set_target(ctrl["time_l_tgt"])
        st.time_r.set_target(ctrl["time_r_tgt"])
        if init:
            st.time_l.instantize()
            st.time_r.instantize()
        return ctrl


VARIANTS = {
    # name: (settle, load_step, lag class, snap targets, model class)
    "revised": (FIXTURE_SETTLE, True, None, True, dm.DelayModel),
    "pre_revision": (PRE_REVISION_SETTLE, False, _Q43Lag, False, dm.DelayModel),
    "settle_only": (FIXTURE_SETTLE, False, _Q43Lag, False, dm.DelayModel),
    "settle_loadstep_q43lag": (FIXTURE_SETTLE, True, _Q43Lag, False, dm.DelayModel),
    "revised_unfused_lag": (FIXTURE_SETTLE, True, _UnfusedF32Lag, True, dm.DelayModel),
    "linux_x86_semantics": (FIXTURE_SETTLE, True, _UnfusedF32Lag, True, _X86F32Control),
}
LAG_LABEL = {None: "float32 grid, fused (frozen model)",
             _Q43Lag: "Q24.43 round-half-up (pre-revision)",
             _UnfusedF32Lag: "float32 grid, unfused"}


def model_v(params, variant, n_blocks, load_depth=None):
    """Per-sample time_l.v / time_r.v (samples) over settle + n_blocks,
    returned for the post-settle region only. load_depth: the LFO depth the
    load-time control pass saw (the preset's, when the probe overrides the
    depth with setParamVal after loadPatch)."""
    settle, load_step, lag_cls, snap, model_cls = VARIANTS[variant]
    m = model_cls(dm.DelayParams(params))
    if not load_step:
        m._load_time_control = lambda: None
    if lag_cls is not None:
        m.st.time_l.__class__ = lag_cls
        m.st.time_r.__class__ = lag_cls
    if load_depth is not None:
        run_depth = m.p.mod_depth_f
        m.p.mod_depth_f = load_depth
        m.initialize()
        m.p.mod_depth_f = run_depth
    else:
        m.initialize()
    nb = settle + n_blocks
    vl = np.zeros(nb * BLOCK)
    vr = np.zeros(nb * BLOCK)
    scale = float(1 << FRAC[dm.C_FMT])
    init = True
    for b in range(nb):
        if snap:
            m._control(init)
        else:
            _control_unsnapped(m, init)
        init = False
        for k in range(BLOCK):
            m.st.time_l.process()
            m.st.time_r.process()
            vl[b * BLOCK + k] = m.st.time_l.v / scale
            vr[b * BLOCK + k] = m.st.time_r.v / scale
    return vl[settle * BLOCK:], vr[settle * BLOCK:]


def _control_unsnapped(m, init):
    """Pre-revision control pass: targets NOT rounded to the float32 grid."""
    saved = dm.f32_round_q43
    dm.f32_round_q43 = lambda x, frac: x if frac == FRAC[dm.C_FMT] else saved(x, frac)
    try:
        m._control(init)
    finally:
        dm.f32_round_q43 = saved


def dt_metrics(x, y, rows, v_model):
    t = np.array([r[0] for r in rows])
    ve = np.array([r[3] for r in rows])
    vm = np.interp(t, np.arange(v_model.shape[0]), v_model)
    d = ve - vm
    rr = replay_rel_residual(x, y, rows, v_model)
    return {
        "pulses": int(len(rows)),
        "fitted_dv_max_abs_samples": float(np.abs(d).max()),
        "fitted_dv_rms_samples": float(np.sqrt((d ** 2).mean())),
        "fitted_dv_mean_samples": float(d.mean()),
        "fitted_dv_frac_within_1_bin": float(np.mean(np.abs(d) <= 1.0 / FIRIPOL_M)),
        "replay_rel_residual_db_max": float(rr.max()),
        "replay_rel_residual_db_p99": float(np.percentile(rr, 99)),
        "replay_rel_residual_db_median": float(np.median(rr)),
        "dt_check": "PASS" if float(rr.max()) <= REPLAY_CHECK_DB else "FAIL",
    }


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, choices=sorted(PRESETS))
    ap.add_argument("--surgepy-dir", default=None,
                    help="directory holding a surgepy*.so built from the pinned "
                         "commit (default: oracle_common.import_surgepy)")
    ap.add_argument("--data-home", default=None,
                    help="SURGE_DATA_HOME of the pinned tree (default: oracle_common)")
    ap.add_argument("--blocks", type=int, default=None,
                    help="post-settle blocks (default: the fixture's frames / 32)")
    ap.add_argument("--depth0-control", action="store_true",
                    help="also run the estimator-validation control: LFO depth 0 "
                         "on the probed instance, engine and model")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.surgepy_dir:
        sys.path.insert(0, os.path.abspath(args.surgepy_dir))
        import surgepy  # noqa: PLC0415
        so_dir = os.path.abspath(args.surgepy_dir)
    else:
        surgepy = oc.import_surgepy()
        so_dir = os.path.join(oc.build_dir(), "src", "surge-python")
    import surgepy.constants  # noqa: F401,PLC0415
    data_home = args.data_home or oc.data_home()
    os.environ["SURGE_DATA_HOME"] = data_home
    so = sorted(f for f in os.listdir(so_dir) if f.startswith("surgepy") and f.endswith(".so"))

    slug = args.slug
    cfg = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs", slug + ".json")))
    rel = PRESETS[slug]
    preset_abs = os.path.join(data_home, rel.split("resources/data/", 1)[1])
    blob = oc.git_blob_sha1(preset_abs)
    if blob != cfg["census_blob_sha1"]:
        raise SystemExit("preset blob %s != census %s" % (blob, cfg["census_blob_sha1"]))
    side = json.load(open(os.path.join(REPO, "reports", "sxt-023", "fixtures",
                                       slug + "__seq-notes-coverage-v1.json")))
    r = side["render"]
    if int(float(r["settle_s"]) * SR) // int(r["block_size"]) != FIXTURE_SETTLE:
        raise SystemExit("fixture settle is not %d blocks" % FIXTURE_SETTLE)
    n_blocks = args.blocks or -(-int(r["frames"]) // BLOCK)

    insts = cfg["chain"]["ains"] + cfg["chain"]["sends"]
    out = {
        "schema_version": 1,
        "kind": "sxt-023 issue #16 engine-side impulse-train d(t) probe "
                "(diagnostic, not a fixture of record, no support claim)",
        "slug": slug,
        "preset": rel,
        "preset_census_blob_sha1": blob,
        "environment": {
            "engine_version_string": surgepy.getVersion(),
            "pinned_commit": json.load(open(os.path.join(REPO, "oracle", "manifest.json")))
            ["engine"]["commit"],
            "surgepy_module": so,
            "surgepy_module_sha256": [sha256_path(os.path.join(so_dir, f)) for f in so],
            "python": platform.python_version(),
            "platform": "%s-%s" % (platform.system().lower(), platform.machine()),
        },
        "protocol": {
            "settle_blocks": FIXTURE_SETTLE, "post_settle_blocks": n_blocks,
            "impulse_period": PERIOD, "first_impulse": FIRST_IMPULSE, "amplitude": AMP,
            "fit_window": WINDOW, "phase_resolution_samples": 1.0 / FIRIPOL_M,
            "dt_check": "every wet pulse rebuilt by the engine read formula driven "
                        "by the model's per-sample v(n) to <= %.0f dB relative "
                        "residual energy (one-sinc-phase-bin class)" % REPLAY_CHECK_DB,
            "fitted_v_timestamp": "centroid of |dy/dn|^2 over the fit window "
                                  "(the single-phase LS fit's sensitivity weight)",
            "depth_override_replay": "load-time control pass at the preset depth, "
                                     "override thereafter (setParamVal runs after "
                                     "loadPatch's FX init)",
            "determinism_gate": "3x bit-identical per render",
        },
        "variants": {k: {"settle": v[0], "load_time_lfo_step": v[1],
                         "lag": LAG_LABEL[v[2]],
                         "targets_on_f32_grid": v[3],
                         "control_plane": ("float32 per operation, unfused "
                                           "(diagnostic, linux x86_64)"
                                           if v[4] is _X86F32Control else
                                           "frozen model (Q24.43 LFO, target "
                                           "rounded once)")}
                     for k, v in VARIANTS.items()},
        "instances": [],
    }
    runs = [(i, None) for i in range(len(insts))]
    if args.depth0_control:
        runs += [(i, 0.0) for i in range(len(insts))]
    for which, depth in runs:
        e = insts[which]
        params = dict(e["params"])
        if depth is not None:
            params["mod_depth_f"] = depth
        x, y, recs = instance_io(surgepy, preset_abs, n_blocks, cfg, which, depth)
        x = np.stack([hp_prefilter(x[c], -60.0) for c in (0, 1)])
        base = dm.DelayModel(dm.DelayParams(params))
        lfo_amp = 100.0 * ((2.0 ** (base._depth_extended() / 12.0) - 1.0) * BLOCK) + 24
        nominal = (SR * params.get("ts_ratio", 1.0)
                   * dm.note_to_pitch_ignoring_tuning_d(12.0 * params["time_l_f"]))
        lo = max(BLOCK, int(nominal - lfo_amp))
        hi = int(nominal + lfo_amp + 2 * FIRIPOL_N)
        rec = {"instance": e["role"], "slot": e["slot"], "lfo_depth_override": depth,
               "renders": recs, "channels": {}}
        load_depth = e["params"]["mod_depth_f"] if depth is not None else None
        vm = {k: model_v(params, k, n_blocks, load_depth) for k in VARIANTS}
        for ch, name in ((0, "L"), (1, "R")):
            rows = fit_pulses(x[ch], y[ch], lo, hi)
            rec["channels"][name] = {
                "fit_rel_err_max": float(max(rw[4] for rw in rows)),
                "v_engine_range": [float(min(rw[3] for rw in rows)),
                                   float(max(rw[3] for rw in rows))],
                "by_variant": {k: dt_metrics(x[ch], y[ch], rows, vm[k][ch]) for k in VARIANTS},
                "pulses_t_idtime_phase": [[round(rw[0], 3), rw[1], rw[2]] for rw in rows],
            }
        out["instances"].append(rec)
        print(json.dumps({"instance": e["role"], "depth": depth,
                          "summary": {c: {k: (v["dt_check"],
                                              round(v["replay_rel_residual_db_max"], 1),
                                              round(v["fitted_dv_max_abs_samples"], 4))
                                          for k, v in rec["channels"][c]["by_variant"].items()}
                                      for c in ("L", "R")}}), flush=True)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(out, f, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
