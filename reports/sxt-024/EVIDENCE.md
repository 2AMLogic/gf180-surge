# SXT-024 evidence record — Reverb1: frozen fixed model, exact RTL, measured buffers, tail + stability controls

Branch: `loom/sxt-024-reverb1` · Issue: #17 (SXT-024) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`).
Reverb1 algorithm authority: pinned `sst-effects` `include/sst/effects/Reverb1.h`
via the surge wrapper `src/common/dsp/effects/Reverb1Effect.cpp` (structure
read and cited, never copied).

**Claim discipline.** This record advances: (1) *RTL matches the frozen
fixed-point model exactly* (iverilog-simulated; demonstrated), and (2) *the
model reproduces the pinned reference within [PROPOSED] budgets* (measured,
PENDING-FREEZE; one bounded budget finding recorded below). It establishes
**no** preset-support claim, **no** musical-quality claim (no human listening
has occurred), and **no** FPGA/gf180mcu synthesis, timing, area, or hardware
playback claim. The RTL is an iverilog-simulated schedule, not
synthesis-closed. No generic reverb is used under any support claim — NC-A
proves the reference budget rejects one.

## Preset and sequence (SXT-014 comparability)

**`Basses/Behemoth.fxp`** + fixture `fixtures/sequences/seq-notes-coverage-v1`
— the same carrier the SXT-014 ablation apparatus bypassed as
`seq-notes-coverage-v1-bypass-slot04-Reverb1` (slot 4 = send 1, the preset's
only active FX; wet = dry + return·reverb1(send·dry) with
`amp_to_linear(x)=x³`, verified from the normalized graph; send
0.707143³ = 0.3536077, return 1.0). Engine params post-load (normalized
state, authoritative): shape 3, roomsize 0.8777, decaytime 1.8795 (t60 ≈
2^1.8795 = 3.68 s nominal), damping 0.7420, predelay −5.4929, lowcut
−46.16, peak −2.025 st/+10.80 dB, highcut +27.20, **mix 1.0**, width 0.
Re-rendered wet buses are **bit-identical** across oracle runs
(engine determinism).

## Deliverables

| Deliverable | Artifact |
|---|---|
| Frozen fixed-point model | `model/effects/reverb1/reverb1_fixed.py` (+ freeze doc `model/effects/reverb1/README.md`) |
| Coefficient plane (control rate) | `model/effects/reverb1/coefficient_plane.py` |
| Fixed-point stability analysis | `model/effects/reverb1/stability_analysis.py` → `stability-analysis.json` |
| Reference captures | `tools/render_reverb_reference.py` → `traces/` (12 s tails, int16 WAV + float32 npy bus) |
| Model-vs-reference comparison | `tools/compare_reverb_model.py` → `comparison/*.json` |
| RTL + harness | `rtl/effects/reverb1/reverb1_core.sv`, `tb_reverb1.sv`, `reverb1_broken_mutant.sv` |
| RTL-vs-model exactness runner | `tools/run_reverb_rtl.py` → `rtl-exactness.json` |
| Buffer/traffic report | `model/effects/reverb1/buffer_report.py` → `buffer-requirement.json` |
| Negative controls | `tools/reverb_negative_controls.py` → `negative-controls/nc-{a,b,c,d}-*.json` |

## 1. Frozen model (word lengths, op order)

Frozen Q4.28 in 32-bit containers (sign + 3 headroom bits; headroom is
load-bearing), c31/c30/c29 coefficients, 80-bit biquad state, round-half-up
`rnd_f`, per-sample op order and per-block filter chain exactly as cited from
the pinned `Reverb1.h processBlock()` — full tables in
[`model/effects/reverb1/README.md`](../../model/effects/reverb1/README.md).
Known bounded deviations: float32 `powf`/table interpolation replicated in
numpy (≤1 ulp); mix/width lipol lags modeled at converged values (control
plane; the transient is *measured* in the reset case, see §3); block size 32.

## 2. Fixed-point stability (confirms/corrects SXT-016)

`stability-analysis.json` (sha256
`3a68f94c7eb4175b96d12478d81eb6987d1985b49ae02332b09e10a6e4369dfa`):

- Conservative zero-latency loop model `M = D(I − J/8)`: **ρ < 1 over the
  whole shape × roomsize × decay grid**; worst reachable ρ = 0.9966 (shape 1,
  room 0.25, decay 6.0).
- SXT-016's "~15-bit guard band" (probe finding) was derived for a
  24-bit-audio-sized state grid at max decay. This analysis **confirms** the
  ρ<1 condition and the loop model, and shows the **frozen Q4.28 word covers
  the equivalent protection with a finer grid (2⁻²⁸ LSB) plus integer
  headroom: 4 guard bits vs the Q4.28 state LSB** at the worst reachable
  operating point (noise-gain amplitude 12.07).
- Empirical worst case: 140 s excitation at every shape, max decay, max room:
  peak internal state 354,444,106 (16.5% of s32i headroom), tails decay to
  silence, no energy growth.

## 3. Model vs pinned reference — [PROPOSED] budgets, achieved numbers

All tolerances are **PENDING-FREEZE** proposals (SXT-013 owns the fidelity
policy). Achieved, `comparison/*.json`:

| Case | wet_max_abs | wet_rms_rel | tail_rms_rel | decay curve | bands | stereo corr | Verdict |
|---|---|---|---|---|---|---|---|
| preset-notes-coverage-wet (product case) | 1.65e-6 (≤1e-3) | −55.0 dB (≤−50) | −52.6 dB | 0.0024 dB | 3.1e-5 dB | 2.4e-7 (≤0.02) | **PASS** |
| click-wet (impulse/decay carrier) | 5.9e-7 | −55.8 dB | −55.6 dB | 0.0014 dB | 1.4e-5 dB | 3.0e-7 | **PASS** |
| hardreset-midpatch-wet (type-toggle reset) | 3.2e-6 | −58.6 dB | −42.6 dB * | 0.0003 dB | 0.0044 dB | 5.8e-8 | **PASS with one recorded budget finding (*)** |
| sweep decay −4…6 (t60 vs 2^decay, diagnostic) | — | — | tail level tracking mean ≤0.64 dB, max ≤4.96 dB | — | — | — | **PASS** (t60 fits NOT_RUN where the tail is below the −100 dBFS floor; tracking carries the agreement) |

**(*) Bounded finding for the freeze.** In the factory-default parameter
regime (the post-rebuild state, see below) the tail error is −42.6 dB
*relative* to a tail that has decayed to −72 dBFS — while the **absolute**
tail error is **−157 dBFS, below the s24 device output LSB (−144 dBFS)**.
The proposed −50 dB relative budget was calibrated on the carrier preset's
regime; a regime-aware absolute-floor rule is a finding for the SXT-013
fidelity-policy freeze. Recorded honestly as a FAIL of the proposed
sub-budget inside `hardreset-midpatch-wet.json`
(`proposed_budget_finding`); never silently relaxed.

Method + limits (honest): the excitation is a 250 ms note click, **not a
mathematical impulse** (the note path cannot produce one); the comparison
remains exact because the model is driven by the same render's DRY bus. The
dry bus is captured float32 (npy preferred over int16 WAV). The lowcut/highcut
deactivated flags are not exposed by surgepy; they are read from the raw .fxp
XML attribute (documented exposure-gap bridge) and cross-checked by the
budget: a wrong hypothesis fails loudly. Reference-vs-reference repeatability:
wet re-render is bit-identical.

### Reset semantics (patch change / patch reset)

Two host paths were probed; they are *not* the same, and both results are
recorded:

- **loadPatch(same preset) mid-render** — `comparison/reset-midpatch-wet.json`:
  **BLOCKED (oracle embedding limitation).** A host-thread `loadPatch()` via
  surgepy leaves the whole engine render **silent** from the reload boundary
  (wet bus exactly zero; voices killed; later notes never sound). The first
  attempt's captures were also corrupted (the host action re-armed FX in the
  fx-off dry instance); the capture tool was fixed (dry buses are now plain
  fx-off renders, asserted byte-identical to the preset dry — sha
  `31f57b41…` for all three). This probe exercises no observable reset
  semantics and is never counted as fidelity evidence.
- **FX type toggle (reverb1 → Off → reverb1 via setParamVal)** — the pinned
  realtime FX-rebuild path (`ct_fxtype` → deferred `fx_reload` → `loadFx`).
  Pinned semantics, now mirrored exactly by the model: the effect is rebuilt
  **with factory-default parameter values** (FXSync is primary;
  `fxsync.p` is not synced from the patch — measured: post-toggle params are
  Reverb1 defaults, recorded in `parameter_regimes`), the long buffers are
  cleared, and the engine's mix/width lipol lags reconverge over a
  ~32-block window (control-plane smoothing, outside the frozen model's
  converged-coefficient scope; max deviation in that window
  1.7e-3 ≤ 1e-2 proposed bound). Outside that window the model matches the
  engine at −58.6 dB full-render / 3.2e-6 max, and the across-reset boundary
  jump matches to 2.5e-7 (**no click added beyond the engine's own buffer
  clear**: engine 0.10594, model 0.10594).

**Change note (issue #100, 2026-09-25): additional `tail_gate` check;
verdicts unchanged.** `tools/compare_reverb_model.py case` now also applies
the shared wet-path tail gate (`checks.tail_gate`) over the trace
sidecar's declared region `[render.frames − render.tail_s × sr, frames)`,
on the mono sum and on L and R. It is added **alongside** the existing
`tail_rms_rel` (own window, −50 "dB" budget), which is unchanged. It was
re-run on this host with both the gated tool and the pre-#100 tool: gated
output minus the new `tail_gate` block is byte-identical to the pre-#100
output. click PASS (gate −110.1 dB), preset PASS (gate −106.0 dB),
hardreset FAIL on `tail_rms_rel` exactly as recorded above (gate PASS,
−88.3 dB). The committed `comparison/*.json` are **not rewritten** by #100.
The gated re-runs are at
`reports/stereo-comparator-tail-gate/artifacts/sxt024-rerun/`. Separately,
the committed click/preset records do not reproduce bit-for-bit with the
*pre-#100* tool on a NumPy 2 host (`send_gain` float32 cube, fields added
after the record). That is a pre-existing finding, filed as #112, and it
changes no verdict.

### Tail-window decision (issue #108): KEEP the bespoke window, report it explicitly

**Decision: the sequence-derived tail window stays.** `compare_reverb_model.py`
does **not** move `tail_rms_rel` / `decay_curve` / `band_energy` /
`stereo_corr` onto `compare_audio_reference.declared_tail_region()`. It now
grades **two declared windows**, and keeps both:

| Window | Used by | Source | click-wet | preset / hardreset |
|---|---|---|---|---|
| sequence-derived (bespoke) | `tail_rms_rel`, `decay_curve`, `band_energy`, `stereo_corr` | last declared `note_on`/`note_off` sample + 100 ms guard (`fixtures/sequences/seq-notes-coverage-v1.json`); click has no sequence fixture, so a declared fixed 100 ms offset from the render start | `[4800, 300000)` | `[158400, 729600)` |
| sidecar-declared (shared, added by #100) | `tail_gate` (shared `car.tail_check`, mono + L + R) | `render.frames − render.tail_s × sr` from the trace sidecar | `[12000, 300000)` | `[153600, 729600)` |

Rationale, in the order it decided the call:

1. **The shared shape is already present.** #100/#113 added `checks.tail_gate`
   — the literal `car.tail_check()` legs (region covered, reference tail
   present, **model tail present**, relative residual) over the sidecar's
   declared region, on the mono sum and on L and R. The field-shape parity the
   issue asked about therefore already exists in this tool's output; the only
   open question was the *bespoke* window, not the shared one.
2. **The two windows are complementary, not nested, so neither subsumes the
   other.** On `click-wet` the sequence-derived window starts **earlier**
   (4800 vs 12000): replacing it would drop 7200 frames of the carrier's
   fastest decay, the part where a wrong decay coefficient shows up first. On
   `preset`/`hardreset` it starts **later** (158400 vs 153600), inside the
   sidecar region. Swapping one for the other loses coverage either way, so
   both are kept and **neither budget was touched** (bespoke −50 "dB" on a
   10·log amplitude ratio, shared −20 dB on a 20·log RMS ratio — the unit
   mismatch between the two families is #112's freeze note, not changed here).
3. **The bespoke methodology is the stricter one on this fixture family.** Its
   budget is −50 "dB" where the shared gate's is −20 dB, and the other checks
   graded over the same window — `decay_curve`, `band_energy`, `stereo_corr`,
   and (hardreset only) `reset_boundary` / `rebuild_transient` — have no
   counterpart in `tail_check()` at all.

**Two scope items were implemented rather than declined:**

- **`NO_VERDICT` refusal path (was a crash).** The sequence-derived start is
  now computed by `sequence_tail_start()`, which raises `car.TailRegionError`
  — and so makes the case **REFUSE (`NO_VERDICT (refused)`, exit 2)** — when a
  window cannot be established from committed declared data: sequence fixture
  missing, no `note_on`/`note_off` declared (previously an unhandled
  `ValueError` from `max()` on an empty generator), a non-integral event
  index, or a start at/after the end of the loaded render (a **STALE**
  sequence, which previously produced an empty slice and `nan`-shaped metrics
  rather than a refusal). A refusal writes **no** comparison record, so it can
  never overwrite committed evidence with a NO_VERDICT stub.
  `tools/reverb_negative_controls.py` now derives its window from the same
  function, so the controls and the comparator cannot drift apart.
- **`model_tail_present` transparency field.** Each record now carries
  `tail_window` = `{tail_offset, tail_frames, tail_region_source,
  tail_region_sequence, last_event_sample, guard_samples, tail_present,
  model_tail_present, tail_budget}` — `tail_present` / `model_tail_present`
  named exactly as in `car.tail_check`. It is **deliberately not** an entry in
  `checks`: presence is the *weaker* leg here, and the committed
  `nc-b-tail-truncation` control proves it — that control keeps
  `model_tail_present: true` (energy survives for 1 s past the window start)
  while failing the graded `tail_rms_rel` at **−7.32 dB** against the −50 dB
  budget. Promoting presence to a check would add a leg that the already-graded
  residual subsumes.

**Verdicts: unchanged.** Before/after on the same host (python 3.12.3, numpy
1.26.4), full records and a line-level diff at
`artifacts/issue-108/` (`before/`, `after/`, `nc-before/`, `nc-after/`,
`DIFF.txt`): every hunk is an **addition** of the `tail_window` block; no
existing field changed value, no `checks` entry was added, removed or flipped.
Exit codes before → after: click `0 → 0` (PASS), preset `0 → 0` (PASS),
hardreset `1 → 1` (FAIL on `tail_rms_rel`, the finding recorded above), reset
`2 → 2` (BLOCKED), `reverb_negative_controls.py` `0 → 0` (SUITE PASS, all four
**CONTROL-OK**; nc-b still `tail_rms_rel: false`, `decay_curve: false`).
Comparator-behaviour scope only: this establishes reproducibility of the tool,
never a preset-support or sound claim.

**The committed `comparison/*.json` and `negative-controls/*.json` are NOT
rewritten here, on purpose (coordination with #112).** A regeneration would add
only the `tail_window` block from this change, but those records are already
STALE against the tool for the reasons #112 records — and the drift is wider
than #112 states:
`send_gain` is committed as the **float64** cube in `comparison/click-wet.json`
and `comparison/preset-notes-coverage-wet.json`, as the **float32** cube in
`comparison/hardreset-midpatch-wet.json` and every
`negative-controls/*.json`, and a current host (numpy 1.26.4) reproduces
**neither** (`0.35360773466102247`). Measured evidence:
`artifacts/issue-108/WHY-NOT-REGENERATED.txt`. Regenerating now would bake a
third value into committed evidence and force a second regeneration once #112
decides the precision, so regeneration is deferred to **#112**, which owns
that decision — and its regeneration set is `comparison/*.json` **plus**
`negative-controls/*.json`, not the two click/preset records alone. No verdict
moves under any of the three `send_gain` values.

**Not addressed here (bounded, out of this issue's scope).** When the analyzed
tail is shorter than four 50 ms windows, `decay_curve_max_dev_db` is `None`
and `checks.decay_curve` reports `false` — a NOT_RUN reported as a FAIL. It is
conservative (never a false pass) and unreachable on the committed traces
(≥ 571200-frame windows), so it was left alone rather than changed under a
"no verdict may move" constraint. Related open work on tail-shape grading is
#111.

## 4. RTL-vs-frozen-model EXACT (iverilog)

`rtl-exactness.json` (sha256
`4de2486e32f5a7d7bb14aaa402dd6b42b4a0f40a14196c44a1dfca29270bc367`),
Icarus Verilog 13.0. The RTL implements the frozen schedule with an explicit
external-memory port; the harness owns the 557,056-word writable memory and
logs every transaction. Compared with exact integer equality:
every s32i output word, every per-block checkpoint (delay_pos, out_tap[16],
12 biquad regs), every external-memory transaction (R/W addr+data in issue
order), and — case A — the full final external-memory image:

| Case | Blocks | Stimulus | outputs | checkpoints | txn log | memory image | Traffic |
|---|---|---|---|---|---|---|---|
| prs-256b-reset48 | 256 (state reset at 48) | deterministic PRS, s24 | EXACT | EXACT | EXACT (278,528 accesses + 1 reset marker) | **EXACT, all 557,056 words** | 34 words/frame ✓ |
| click-512b | 512 | committed click-dry send input (real preset params) | EXACT | EXACT | EXACT (557,056 = 512·32·34) | implied by write log | 34 words/frame ✓ |
| reverb1_broken_mutant (tap-7 write silently skipped) | 256 | = case A | — | — | — | — | **CONTROL-OK: FAILS the comparison** (stale-buffer stub detected) |

## 5. Measured buffer requirement (per instance)

`buffer-requirement.json` (sha256
`a8d77eb3fdcfc0fbbe514c03c9c48d8a4c0cac83753d9c22f53f42897017bcde`):

| Region | Words (32-bit) | Bytes |
|---|---|---|
| Composite taps (16 interleaved taps × 32768) | 524,288 | 2,097,152 |
| Predelay line | 32,768 | 131,072 |
| **Total external writable** | **557,056** | **2,228,224 (2.125 MiB)** |

- **External writable** (flash is never a substitute): the two long regions
  above. **On-chip small state: 4,031 bits (503 B)** (out_tap 512 b, biquad
  regs 960 b, coefficients 2,512 b [biquad 480 + delay_fb 512 + delay_time
  368 + pan 1,024 + damp 64 + mix/width lags 64], delay_pos 15 b, block/frame
  counters 32 b — per `buffer-requirement.json`). **All processing stays
  in-chip.**
- Traffic: **17 reads + 17 writes = 34 words = 136 B per frame** (6.528 MB/s
  per instance at 48 kHz), measured from the frozen model's transaction log
  and re-measured from the RTL harness (557,056 = 512·32·34).
- Reconciliation with SXT-015/016 (committed files untouched): SXT-015's
  logical 17r+17w agrees; SXT-016's probe priced state at 24-bit words
  (12,582,912 + 786,432 b); the frozen word is 32-bit, so capacity is
  16,777,216 + 1,048,576 b (+33%) while **traffic is unchanged at 136
  B/frame**. This record supersedes the SXT-016 Reverb1 capacity figure.
- Per-instance state is never shared (two Reverb1 slots = two buffer sets).

## 6. Negative controls (each must FAIL the check it targets)

| Control | Result |
|---|---|
| NC-A generic Schroeder 4-comb/2-allpass under the reference budget | **CONTROL-OK** — fails 6/6 checks (wet RMS +9.2 dB, decay curve 537 dB dev, stereo corr 0.999 vs 0.883). Adapted ≠ supported, proven. |
| NC-B tail truncated 1 s after input stop | **CONTROL-OK** — tail RMS −7.3 dB, decay curve 554 dB dev (dropped tail is above the floor for seconds). |
| NC-C patch-change/reset | **CONTROL-OK** — reset mirror passes the transition checks (boundary jump 0.1059388 vs 0.1059385, ≤1e-3; transient window bound met) and the **no-reset variant FAILS** (max err 0.312, tail RMS −20.1 dB) — the reset is observable and click-neutral. loadPatch limitation documented, not counted. |
| NC-D 24-bit storage words (no headroom, audio-LSB grid) | **CONTROL-OK** — −48.7 dB vs −50 dB budget / 1-LSB headroom exceeded ⇒ the frozen word choice is load-bearing. |
| RTL broken mutant (silent tap-7 buffer write) | **CONTROL-OK** — exactness comparison FAILS (txn log, outputs, memory image). |

## 7. What this record does NOT establish

- Any fidelity policy or frozen budget (SXT-013 BLOCKED on human listening);
  all numbers above are against [PROPOSED] tolerances, with one recorded
  budget finding (§3 (*)).
- Any preset-support or musical-quality claim; no human listening has occurred.
- Any FPGA/gf180mcu synthesis, place-and-route, timing, power, or hardware
  playback result; the RTL is an iverilog-simulated schedule.
- Engine reset semantics beyond the FX type-toggle path (the loadPatch probe
  is blocked by an oracle embedding limitation, documented in §3).
- Reverb2 or any other effect (#21).
- Field-for-field reproducibility of the committed `comparison/*.json` and
  `negative-controls/*.json`: those records carry the verdicts recorded above,
  but they are **STALE** with respect to the current tool (`send_gain`
  precision drift across NumPy regimes and fields added after they were
  written — #112; plus the additive `tail_window` block, §3's issue-#108
  note). Regeneration belongs to #112, which owns the precision decision.

## 8. Reproduce

```sh
python3 tools/render_reverb_reference.py preset|click|sweep|reset|hardreset
python3 tools/compare_reverb_model.py case --case preset-notes-coverage-wet
python3 tools/compare_reverb_model.py sweep
python3 tools/run_reverb_rtl.py            # needs iverilog; exactness + mutant
python3 tools/reverb_negative_controls.py  # exits 0 iff all controls fail their checks
python3 model/effects/reverb1/stability_analysis.py   # long (~40 min)
python3 model/effects/reverb1/buffer_report.py
python3 -m pytest -q tests/test_sxt024_reverb1.py tests/test_sxt024_tail_window.py
```

`--out-dir <dir>` writes the case record somewhere other than
`comparison/`; that is how the before/after pair in `artifacts/issue-108/`
was produced without touching the committed records.

## 9. Provenance / licensing

All files in this repository are original (Apache-2.0 per `LICENSE`). Reverb1
structure is read and cited from the pinned GPL-3.0-or-later tree
(`sst-effects` `Reverb1.h` via `surge@58914e59…`); the 16×4 `delay_time`
preset tables are transcribed as cited structural constants with file-level
provenance in `coefficient_plane.py`. No Surge source, tables beyond those
cited constants, or assets are copied; no distribution-license determination
has been made for Surge-derived material.
