# SXT-043 evidence record — voice leaf: playmode submode `pm_mono_st_fp`

Issue: #77 (SXT-043) · Branch `feature/issue-77` · Date: 2026-10-02

Pinned engine (cited only, external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz.
Installed on this dispatch host via the prebuilt-oracle path landed by #232
(PR #299): `~/.cache/gf180-surge-oracle/58914e59c608ed4384ba6002e44c3465c58b2e71/`.
`surgepy` imports and loads factory presets successfully from this host —
the oracle dependency this issue was previously blocked on (#96, #232) is
resolved, and every item below that needs the oracle was actually run here,
not reported as NOT_RUN by default.

**Scope and claim discipline** (CLAUDE.md): this record establishes claim
(1) RTL-vs-frozen-model exactness, and reports (not asserts PASS for) claim
(2) model-vs-pinned-engine agreement under declared, not-yet-frozen budgets.
It makes **no** claim (3) musical-quality / listening verdict, **no**
preset-support claim (the modeled configuration is a declared test
configuration, never an adapted preset), and **no** FPGA/gf180mcu
synthesis, timing, or hardware-playback claim. No Surge code, tables, or
assets are copied into this repository; the model and RTL are original
work (Apache-2.0).

## Acceptance status

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order documented | **PASS** | `model/voice/playmode/README.md` (word-length table, declared RTL/model boundary, declared bounds); `model/voice/playmode/pm_mono_st_fp.py` (module + per-method docstrings cite the pinned source lines for every articulation rule). |
| 2 | Model-vs-pinned-engine dry-render budgets reported on the carrier fixtures | **MEASURED, FAIL against the proposed (not-frozen) thresholds on all reportable carriers; achieved numbers recorded, not tuned** | `artifacts/budget-{bass2,bass5,digibass}-{seq-notes-coverage,repeated,holds}-v1.json` (9 runs). See "Model-vs-reference budgets" below — Digibass's reference render is silent (filed separately, #311) and is reported as a non-comparison, not a tuned result. |
| 3 | RTL-vs-model exact at declared checkpoints (integer equality) | **PASS, 0 mismatches, all 15 runs** | `artifacts/exactness-{carrier}-{sequence}.json` for all 3 carriers × all 5 sequences (the 3 declared + 2 added to reach legato/reclaim coverage). Checked fields: 1,094,400–1,190,400 per run; see table below. |
| 4 | Cycle/state costs recorded against SXT-016 probes / SXT-015 accounting | **PASS (recorded, divergence noted)** | See "Cost accounting" below. |
| 5 | Negative control: forced-Poly render of the mono fixture must FAIL the reference-budget check | **PASS (control fires as required)** | `artifacts/negative-control.txt` §1, `artifacts/neg-control-forced-poly-negative-control.json`: max_abs_diff 43,492 LSB (budget ≤3,500), rms_diff −12.48 dBFS (budget ≤−46.0), spectral_corr 0.846 (budget ≥0.98) — FAIL on every leg, by a wide margin. |

## RTL-vs-model exactness (claim 1), full table

`tools/compare_pm_rtl_model.py`, `rtl/voice/tb_pm_mono_st_fp.sv` (iverilog
13.0). Verdict **PASS, 0 mismatches** on all 15 runs:

| Carrier | Sequence | Block×slot checkpoints | Fields checked | Articulation events hit |
|---|---|---:|---:|---|
| bass2 | seq-notes-coverage-v1 | 68,400 | 1,094,400 | create, release |
| bass2 | seq-notes-repeated-v1 | 49,200 | 787,200 | create, release |
| bass2 | seq-notes-holds-v1 | 74,400 | 1,190,400 | create, release |
| bass2 | seq-mono-fingered-v1 | 61,200 | 979,200 | create, **legato, legato_down**, release |
| bass2 | seq-mono-reclaim-v1 | 35,280 | 564,480 | create, **reclaim**, release |
| bass5 | (same 5 sequences) | (same) | (same) | (same) |
| digibass | (same 5 sequences) | (same) | (same) | (same) |

(bass5 and digibass report byte-identical checkpoint/field counts per
sequence to bass2, since all three carriers share the same note sequences
and pool size; full per-run JSON in `artifacts/`.)

`seq-mono-fingered-v1` and `seq-mono-reclaim-v1`
(`fixtures/sequences/generate_pm_sequences.py`) are this leaf's own
addition: the three sequences #77 names are all strictly non-overlapping
note-on/note-off pairs and therefore cannot reach a legato or reclaim
transition at all (every note-off precedes the next note-on). Restricting
exactness evidence to the declared three would exercise only
`create`/`release` — half the submode. The added sequences drive
`legato` (including a mid-glide re-anchor and a same-key, zero-interval
case), `legato_down` (hand-down to a still-held key on release), and
`reclaim` (`RESTART_FROM_LATEST`, re-pressing inside the release tail) —
**0 mismatches** across all of it, on all three carriers.

## Model-vs-reference budgets (claim 2), full table

`tools/render_pm_reference.py` (pinned oracle) vs.
`model/voice/playmode/run_model.py`'s `model.wav`, compared with
`tools/compare_audio_reference.py` (dry path, default). Budgets are
`max_abs_diff_lsb <= 3500`, `rms_diff_dbfs <= -46.0`,
`spectral_corr >= 0.98` — PENDING-FREEZE proposals (not frozen policy);
this leaf reports achieved numbers, does not tune to pass, and does not
weaken them.

| Carrier | Sequence | max_abs_diff (LSB) | rms_diff (dBFS) | spectral_corr | ref_peak (LSB) | Verdict |
|---|---|---:|---:|---:|---:|---|
| bass2 | coverage | 9,352 | −26.85 | 0.9960 | 16,329 | FAIL |
| bass2 | repeated | 3,413 | −32.82 | 0.9983 | 16,329 | FAIL |
| bass2 | holds | 2,671 | −32.95 | 0.9978 | 12,784 | FAIL |
| bass5 | coverage | 50,783 | −16.97 | 0.9611 | 32,767 | FAIL |
| bass5 | repeated | 15,270 | −22.38 | 0.9461 | 32,767 | FAIL |
| bass5 | holds | 7,154 | −24.38 | 0.9930 | 32,767 | FAIL |
| digibass | coverage | 13,470 | −19.44 | 0.0 | **1** | **NOT A VALID COMPARISON** |
| digibass | repeated | 13,468 | −16.54 | 0.0 | **1** | **NOT A VALID COMPARISON** |
| digibass | holds | 6,027 | −21.14 | 0.0 | **1** | **NOT A VALID COMPARISON** |

Budget thresholds: `max_abs_diff_lsb <= 3500`, `rms_diff_dbfs <= -46.0`,
`spectral_corr >= 0.98`. Only `bass2 / seq-notes-repeated-v1`'s
`max_abs_diff_lsb` and `spectral_corr` legs individually clear their
threshold (3,413 ≤ 3,500; 0.9983 ≥ 0.98) — the `rms_diff_dbfs` leg misses
on every run, so every run's overall verdict is FAIL. Digibass's `ref_peak`
of 0–1 LSB (vs. 12,784–32,767 for the other two carriers on the same
sequences) is the silence described below, not a real comparison.

**Why bass2/bass5 fail the proposed budget, and why this is a recorded
finding rather than a bug fix target for this leaf.** `model/voice/
playmode/README.md` ("Declared model/RTL boundary") states explicitly that
this leaf's `model.wav` render is a simplified per-voice mix that does
**not** reproduce the landed `filter_chain` (fc_serial1 Mix1 blend /
IIR12-24 coupled-form state) `tb_voice.sv` models exactly for the leaves
that introduced it (SXT-022/026a/034/040) — that full-datapath-exactness
claim is explicitly out of this leaf's declared RTL boundary (it checks the
articulation layer only). The residual is consistent with that declared
simplification (onset-aligned sample comparison shows a small, early,
oscillating divergence from the very first note, not a drift that grows
monotonically — inconsistent with a gross pitch error, consistent with a
missing filter-chain stage). Per the issue's Stop/escalate clause: this
finding is recorded, not papered over by loosening the budget or
re-implementing the full audio datapath inside this leaf (which would
duplicate, not extend, the already-landed and already-qualified
`tb_voice.sv`).

**Digibass: the reference render is silent, independent of this leaf.**
Forcing Digibass's oscillator slot 1 to Sine (this leaf's declared isolation
override) makes the **pinned engine** render completely silent
(`peak_abs_float: 0.0`) at every MIDI key tested. Root-caused under **#311**
(investigation finding; no verdict above changes): Digibass carries
`Velocity` and `Filter EG` modulation routings into osc-1 `p[0]` (Morph on
its Wavetable osc); the engine's type switch via the Python binding leaves
them in place, they retarget the Sine oscillator's integer Shape selector,
the float modulation add corrupts the integer, and the Sine oscillator
produces no output. Bass 2 / Bass 5 have no osc-1 `p[]` routings and are
unaffected. Zeroing those two routings before the switch restores a normal
pitched render (peak 0.3869); adding a routing of the same kind to Bass 5
silences it (peak 0.0). Full evidence table, ruled-out hypotheses and the
caveat on intermittent nonzero results are in `model/voice/playmode/README.md`
("Known finding"). Digibass's budget leg stays recorded as NOT A VALID
COMPARISON; the fixture was not changed here. Digibass's RTL-vs-model
exactness (claim 1) is **unaffected**: it is a pure register-level
comparison that never touches rendered audio, and passed 0-mismatch
identically to the other two carriers.

## Negative control (claim 5), required

See `artifacts/negative-control.txt` §1 for the full command transcript and
`artifacts/neg-control-forced-poly-negative-control.json` for the measured
result. Summary: `bass2.fxp` + `seq-mono-fingered-v1`, pinned-engine
render at the declared pm_mono_st_fp configuration vs. the same render
forced to `play_mode = 0` (Poly). `tools/compare_audio_reference.py`
reports **FAIL against proposed budgets** on every metric (max_abs_diff
43,492 LSB vs. the 3,500 budget; rms_diff −12.48 dBFS vs. the −46.0 budget;
spectral_corr 0.846 vs. the 0.98 budget) — not a borderline miss. The
forced-Poly render also visibly clips (513 samples, peak 1.18) where the
correct mono render does not (peak 0.48), consistent with Poly allocating
independent per-note voices instead of single-trigger reuse.

`artifacts/negative-control.txt` §2 additionally records three
oracle-independent exactness-side controls (model/RTL-only, no pinned
engine needed):

- `--nc-anchor-last-key` (drops the pm_mono_st_fp-defining anchor-at-own-
  pitch branch): **REFUSES** — drives a declared fixture's pitch outside
  the [24, 148] bound. Fail-closed, not a silent wrong answer.
- `--nc-reset-osc-on-reclaim` (re-inits the oscillator on a mono reclaim,
  which the pinned engine does not do for a Sine slot): produces a
  different `model.wav` (sha256 differs) — observable, bites.
- `--nc-share-portamento-state` (one shared portamento register instead of
  per-instance): does **not** bite on any of this leaf's 3 carriers × 5
  sequences, because all three carriers use `monoVoiceEnvelopeMode =
  RESTART_FROM_LATEST`, under which this state machine never produces two
  concurrently-alive voices (`max_concurrent_voices == 1`, measured, every
  run). **Recorded coverage gap**, not a false pass — the identical,
  already-accepted limitation recorded for SXT-036
  (`reports/SXT-036/EVIDENCE.md`, "Recorded coverage gap"). Per-instance
  state IS implemented (every `MonoVoice` owns its own `Portamento`
  instance).

## Class-boundary refusal controls (extractor)

`artifacts/refusal-controls.txt`: `model/voice/playmode/extract_inputs.py`
run against the four real, normalized-corpus carriers
`fixture_config.REFUSAL_CONTROLS` names, each with scene-A playmode set to
a DIFFERENT member of the pinned `play_mode` enum (0 Poly, 1 Mono, 2 Mono
Single-Trigger, 3 Mono Fingered-Portamento — none of them 4,
`pm_mono_st_fp`). All four **REFUSE (exit 2)**, each citing the carrier's
own actual playmode id, confirming the extractor discriminates by the
specific submode rather than merely rejecting "not Poly".

## Cost accounting

`rtl/voice/tb_pm_mono_st_fp.sv`'s `$display` line
(`DONE pm-qmuls=<N> voice-blocks=<M>`), captured per
`artifacts/exactness-<carrier>-<sequence>.json`'s `rtl_done_line`. Example
(bass2, seq-notes-coverage-v1): `pm-qmuls=4833` over `voice-blocks=3132`
control passes — **≈1.54 qmul per running-voice block** for this leaf's
articulation layer (allocation bookkeeping is branch/compare-only; the
qmuls are the velocity smoother (≤2/block), the envelope tick (1–3/block
depending on release shape `r_s`), the portamento ramp (1–2/block), and the
keytrack-word refresh (1/block)). State: one `{gate, uberrelease, key,
aeg(4 words), vel(2 words), kt_word, porta(5 words)}` register set per pool
slot (8 slots declared) — 13 Q-words + a handful of control bits per slot,
independent of which carrier or sequence is running (fixture-constant pool
size). SXT-016's `probe_scheduler__event_queue_and_control` is the closest
existing probe (control-path basis) but has no per-playmode-submode row;
**not reconciled** against it, consistent with the issue's cost note
("articulation arithmetic is per-voice [ESTIMATE] pending SXT-016
refinement") — recorded here as a measured data point for that future
reconciliation, not asserted as agreement.

## Reproduce

```sh
# Oracle env (prebuilt, #232/#299):
export ORACLE_SURGE_DIR=~/.cache/gf180-surge-oracle/<commit>/linux-x86_64
export ORACLE_PYTHON=~/.cache/gf180-surge-oracle/<commit>/venv/bin/python
export LD_LIBRARY_PATH=~/.cache/gf180-surge-oracle/<commit>/cpython-3.11.16/lib

# Frozen model + RTL exactness (no oracle needed):
python3 model/voice/playmode/run_model.py --inputs model/voice/playmode/inputs/bass2.json \
    --sequence seq-notes-coverage-v1 --out-dir /tmp/run
python3 tools/compare_pm_rtl_model.py --run-dir /tmp/run

# Model-vs-reference budget (oracle needed):
"$ORACLE_PYTHON" tools/render_pm_reference.py --carrier bass2 \
    --sequence seq-notes-coverage-v1 --out-dir /tmp/ref --tag ref
python3 tools/compare_audio_reference.py --ref /tmp/ref/bass2__seq-notes-coverage-v1-ref.wav \
    --model /tmp/run/model.wav

# Negative control (oracle needed):
"$ORACLE_PYTHON" tools/render_pm_reference.py --carrier bass2 \
    --sequence seq-mono-fingered-v1 --out-dir /tmp/nc --tag forcedpoly --force-polymode 0
```

## Stop/escalate

Proposed budgets are not met on bass2/bass5 (declared, explained
simplification — see above) and cannot be measured at all on digibass
(engine-level silence, #311). Per the issue's stop/escalate clause, these
are recorded as bounded findings rather than resolved by weakening the
budget or expanding this leaf's scope to re-implement the full audio
datapath. No acceptance rule was loosened to land this PR: item 2 is
reported, not asserted PASS; item 5 (the only pass/fail-gated acceptance
item that depends on the budget check) demonstrably fires as required.

## Fixture revision 2 (#329), 2026-10-07: status of the revised Digibass reference

Everything above this heading is the dated record from #77 and #311. It is
kept verbatim, including the three Digibass **NOT A VALID COMPARISON** rows,
and it describes **fixture revision 1**. Every file currently in
`artifacts/` and `model/voice/playmode/inputs/` was produced under
revision 1.

**What changed.** `model/voice/playmode/fixture_config.py` now has
`FIXTURE_REVISION = 2` and the new override `osc_p_route_clear`. Routings
into the modeled osc slot's seven original `p[]` parameters are zeroed by
synth-side parameter id **before** the type switch, and the zeroing is
checked against both the 0..1 and the raw depth. A post-switch guard
refuses on any surviving routing, and `modpin_zero` now also checks the raw
depth. The extractor and reference renderer record the revision, and the
renderer refuses inputs from any other revision. Full description:
`model/voice/playmode/README.md`, "Fixture revision 2".

**Correction to the revision-1 record.** `inputs/digibass.json` (revision 1)
lists `Velocity -> A Osc 1 Shape` (depth 0.367) and `Filter EG -> A Osc 1
Shape` (depth 0.223) under `pinned` as "depth zeroed (modpin_zero)". That
statement is false. Both routings were still live, which is exactly the
#311 root cause. The revision-1 readback compared `getModDepth01`, which
reads 0 on the non-modulatable Sine Shape while the raw depth stays intact.
The sidecar is left byte-unchanged as historical evidence and is
**STALE** for revision 2.

| # | #329 acceptance item | Status | Evidence / reason |
|---|---|---|---|
| 1 | Native readback shows targeted osc-1 `p[]` route depths are 0 before the type switch; original and revised state plus revision retained | **Code + API-double PASS; native BLOCKED** | `tests/test_sxt043_fixture_rev2.py` (18 tests) runs on an API double that reproduces the #311 engine behaviors. It checks that zeroing comes before the switch, that source scene/index are preserved, that handles are re-fetched, that matching uses identity and not names, and that a failed readback refuses. A mutation that restores the old order makes 7 of the 18 tests fail. These tests verify ordering, not native sound. No native readback was recorded: the pinned oracle is not installed on this host (no `~/.cache/gf180-surge-oracle`, `ORACLE_PREBUILT_URL` not provisioned). |
| 2 | Pinned SXT-010 runtime at 48 kHz gives a nonzero Digibass reference pitched at key/scene octave/tuning, on a held segment | **BLOCKED** (oracle unavailable) | The gate and its window/tolerance were declared before any measurement (`reference_validity.py`: segment 0.30 to 0.80 s after note-on, ±25 cents, purity ≥ 0.5 within ±100 cents, peak ≥ 1e-3; Digibass f0 = 130.81 Hz). The runner `tools/probe_pm_reference_validity.py --mode revised` has **not run**. Synthetic-signal checks show the gate accepts a 130.81 Hz sine and rejects silence, 1.46 kHz, noise, the wrong octave and a 40-cent offset. That says nothing about the engine. |
| 3 | Re-extract inputs; re-render and compare the three carriers on `seq-notes-{coverage,repeated,holds}-v1` | **BLOCKED** (oracle unavailable) | Nothing was re-extracted or re-rendered. The budget table above is still the revision-1 measurement, and Digibass stays NOT A VALID COMPARISON. No new budget numbers exist yet. |
| 4 | RTL-vs-revised-model exact; forced-Poly and refusal controls re-run | **Partial: RTL-vs-model re-run PASS on revision-1 inputs; revised-inputs leg BLOCKED; oracle controls NOT_RUN** | The model, the RTL and the comparator were not changed by this revision. Re-run on 2026-10-07 for Digibass × {`seq-notes-coverage-v1`, `seq-mono-fingered-v1`, `seq-mono-reclaim-v1`}: 0 mismatches, with checkpoint/field counts identical to the committed records (68,400/1,094,400; 61,200/979,200; 35,280/564,480). This used the revision-1 inputs, because re-extraction needs the oracle. The forced-Poly and extractor refusal controls need the oracle and were NOT_RUN. |
| 5 | Live negative control in the old retained-routing order fails the valid-reference gate (silence), and a stale/non-pitched output also fails | **Runner + API-double done; native BLOCKED** | `tools/probe_pm_reference_validity.py --mode nc-retained-routes` and `--mode nc-stale-buffer` have **not run** on the pinned engine. On the double, the old order now refuses at the post-switch guard, and the revision-1 readback blind spot is reproduced and refused by the raw-depth check. The #311 native observations (peak 0.0 under the old order; ~1.46 kHz stale buffer) are the investigation input. They are not a re-measurement. |
| 6 | Historical NOT A VALID COMPARISON preserved; revised result appended with provenance; no stale artifact shown as current PASS | **PASS (record discipline)** | The historical rows are untouched. This section marks every committed SXT-043 artifact as revision 1, and the Digibass inputs as STALE for revision 2. The renderer refuses revision-1 inputs. No revised result exists to append yet. |

**To unblock** (on a host with the prebuilt oracle, #232):

```sh
for c in bass2 bass5 digibass; do
  "$ORACLE_PYTHON" model/voice/playmode/extract_inputs.py --carrier $c \
      --out model/voice/playmode/inputs/$c.json
done
for m in revised nc-retained-routes nc-stale-buffer; do       # one process each
  "$ORACLE_PYTHON" tools/probe_pm_reference_validity.py --carrier digibass \
      --mode $m --out reports/SXT-043/artifacts/validity-digibass-$m.json
done
# then the Reproduce block above for the 3 carriers x 3 declared sequences,
# the forced-Poly control, the refusal controls, and RTL exactness on the
# re-extracted inputs; record achieved numbers, do not tune thresholds.
```

Stop conditions still apply. If the revised Digibass probe is silent or
not pitched, or the old-order control does not fail, record a bounded
finding and do not adjust the gate.
