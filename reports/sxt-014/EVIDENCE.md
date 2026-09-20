# SXT-014 evidence record — FX ablation apparatus (automatable portion)

Branch: `loom/sxt-014-ablation-apparatus` · Issue: #9 (SXT-014) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
surgepy build `1.4.HEAD.58914e59c`, 48 kHz, compiled block size 32, tempo 120
(`oracle/manifest.json`; `engine` block in every sidecar).

**Claim discipline.** This record covers the *automatable* portion of SXT-014 only:
one-effect-at-a-time ablation renders of the pinned engine under the SXT-012 render
policies, plus coarse numeric deltas. It establishes **no essential/optional/unresolved
effect labels** (those are listening judgments → BLOCKED-on-human), **no preset-support
claim**, **no model/RTL fidelity claim**, and **no musical-quality claim**. Numeric
deltas are diagnostic. Substituted-effect renders are labeled ADAPTED and are excluded
from original-preset coverage by construction.

## Deliverables

| Deliverable | Artifact |
|---|---|
| Ablation render tool | `tools/ablate_fx.py` — modes: `ablate` (original + per-active-slot bypass + all-off dry), `offslot-control`, `permute`, `substitute` (ADAPTED tree), `verify` |
| Diagnostic delta tool | `tools/ablation_delta.py` — block-RMS + band + tail metrics, stdlib-first (numpy FFT fallback), per-pair JSON + `ablation-summary.json` |
| Pilot ablation matrix | `reports/sxt-014/ablations/<preset>/` — 6 factory presets × 2 sequences, 61 WAVs (mono 16-bit), 28,389,884 bytes ≈ 27.1 MiB of WAVs (28,577,072 bytes ≈ 27.3 MiB tree total), **no trim needed** (under the ~50 MB budget) |
| Per-render metadata | one JSON sidecar per WAV: preset census blob SHA-1 + file SHA-256, slot (index, role, type id/name, Airwindows id/name), sequence id + SHA-256, engine pin, WAV SHA-256/bytes, per-render non-perturbation proof, tool identity |
| Numeric deltas | `reports/sxt-014/deltas/<preset>/<variant>.json` (47 pairs) + `reports/sxt-014/ablation-summary.json` |
| Negative controls | `reports/sxt-014/negative-controls.txt` + offslot/permuted/adapted renders in the tree |
| Run manifests | `reports/sxt-014/ablations/run-*.json` (append-only render records) |

Pilot presets (factory bank, census-blob verified at every load; types cross-checked
engine↔`corpus/normalized/graphs.jsonl` per slot):

| slug | preset | active FX slots (engine readback = graphs) |
|---|---|---|
| doomsday | `Basses/Doomsday.fxp` | 0 EQ, 4 Reverb 1, 5 Delay, 6 Conditioner |
| width | `Basses/Width.fxp` | 0 EQ, 4 Delay, 5 Reverb 1 |
| behemoth | `Basses/Behemoth.fxp` | 4 Reverb 1 |
| koala2 | `Leads/Koala 2.fxp` | 4 Delay |
| fmcombo | `Basses/FM Combo.fxp` | 0 EQ, 1 Chorus |
| fmod09 | `Tutorials/Formula Modulator/09 …Crossfading Oscillators.fxp` | 0 Flanger, 4 Delay, 5 Airwindows (algorithm **Galactic**) |

Coverage includes the plan-section-3 ladder carriers: **Reverb 1, Delay, EQ** and an
**Airwindows** carrier (exact algorithm recorded), plus Conditioner, Chorus, Flanger.
Sequences: `seq-notes-coverage-v1`, `seq-poly-8-v1` (SXT-012 library, SHA-256-pinned).

## Harness parity with SXT-012

Reset/scheduling/tail/audio policies are inherited from `fixtures/render_fixture.py`
(imported, not re-implemented). Parity is demonstrated bit-exactly: the ablation
`original` and `dry-allfxoff` renders for the bit-identical repeatability class
reproduce the committed SXT-012 fixture WAVs SHA-for-SHA, e.g. behemoth `seq-poly-8-v1`
original `648ea6f3…` = `fixtures/audio/behemoth/seq-poly-8-v1-wet.wav`, dry
`4d690bb1…` = `…-dry.wav`; sub4 `seq-notes-coverage-v1` original
`e6d88742…` = `fixtures/audio/sub4/seq-notes-coverage-v1-wet.wav`.

**Repeatability classes apply** (`reports/sxt-012/repeatability.json`): only
`sub4`/`behemoth` renders are bit-reproducible across instances; all other pilot
presets are free-phase (engine RNG at voice start), so their numeric deltas are
single-instance values with a class variation floor (koala2 wet repeat
`relative_max_diff` ≈ 1.7×peak) and must not be over-read. Fine-grained numeric
attribution for free-phase presets awaits a declared freeze/retrigger comparison
policy (SXT-017 territory).

## Ablation matrix (mean |block-RMS Δ| in dB vs each preset's own original)

Full machine-readable matrix: `reports/sxt-014/ablation-summary.json` (47 pairs;
per-pair JSONs under `reports/sxt-014/deltas/`). Highlights:

| preset | sequence | slot (role) | effect (algorithm) | variant | mean ΔRMS dB | verdict |
|---|---|---|---|---|---|---|
| behemoth | notes-coverage | 4 (send1) | Reverb 1 | bypass | 34.196 | measurable |
| behemoth | notes-coverage | all | — | dry | 34.196 | measurable |
| behemoth | poly-8 | 4 (send1) | Reverb 1 | bypass | 47.868 | measurable |
| doomsday | notes-coverage | 0 (ains1) | EQ | bypass | 0.846 | measurable |
| doomsday | notes-coverage | 4 (send1) | Reverb 1 | bypass | 1.313 | measurable |
| doomsday | notes-coverage | 5 (send2) | Delay | bypass | 1.147 | measurable |
| doomsday | notes-coverage | 6 (global1) | Conditioner | bypass | 2.245 | measurable |
| doomsday | notes-coverage | all | — | dry | 36.194 | measurable |
| doomsday | poly-8 | 5 (send2) | Delay | bypass | 0.396 | measurable |
| doomsday | poly-8 | all | — | dry | 54.533 | measurable |
| width | notes-coverage | 0 (ains1) | EQ | bypass | 3.596 | measurable |
| width | notes-coverage | 4 (send1) | Delay | bypass | 2.610 | measurable |
| width | notes-coverage | 5 (send2) | Reverb 1 | bypass | 7.234 | measurable |
| width | poly-8 | all | — | dry | 64.513 | measurable |
| fmcombo | notes-coverage | 0 (ains1) | EQ | bypass | 2.273 | measurable |
| fmcombo | notes-coverage | 1 (ains2) | Chorus | bypass | 2.083 | measurable |
| fmod09 | notes-coverage | 5 (send2) | Airwindows (Galactic) | bypass | 9.796 | measurable |
| fmod09 | poly-8 | 5 (send2) | Airwindows (Galactic) | bypass | 10.093 | measurable |
| koala2 | notes-coverage | 4 (send1) | Delay | bypass | 25.509 | measurable |
| koala2 | poly-8 | 4 (send1) | Delay | bypass | 30.673 | measurable |
| fuji | notes-coverage | 0+4 swapped | Delay | permuted (control) | 18.481 | DETECTED |

Internal consistency: bypassing behemoth's only active slot is **bit-identical** to its
all-off dry render (both sequences) — the per-slot bypass composes exactly with the
all-off path. Coarse RMS deltas are non-additive across slots (phase interactions;
e.g. fmcombo's dry delta is smaller than some single-slot bypasses) — expected for
waveform-domain metrics; slot deltas must not be summed.

## Near-zero-delta candidates

Thresholds (documented in the summary JSON): not bit-identical AND max sample |Δ| <
2⁻¹³ AND mean block-RMS Δ < −60 dB AND all band |Δ| < 0.5 dB. **Result: 0 of 47 pairs
flag.** No configured-but-inaudible slot is claimed: the smallest measured slots
(doomsday EQ 0.396–0.846 dB, doomsday Delay 0.396–1.147 dB) are in free-phase presets
where a near-zero numeric claim is not supportable at single-instance precision, and
they remain **unresolved** — candidates for listening, not for automated de-labling.
No slot bypass ever rendered bit-identical to its original, i.e. every active slot in
the pilot measurably contributes under this harness.

## Issue-#9 acceptance mapping

| #9 acceptance item | Status | Evidence |
|---|---|---|
| Ablation keeps unmodified wet original; bypass/substitution variants are new files | **PASS** (automation) | `ablate`/`substitute` refuse to overwrite; originals are dedicated renders; substitutions written only to `ablations/doomsday/adapted/` with `adapted: true` |
| Labels decided by listening + measurements, not slot counts; inaudible slots identified | **BLOCKED-on-human** (labels); automation contributes deltas only | This record + `ablation-summary.json`; no listening record exists yet; near-zero scan ran with 0 flags (thresholds above) |
| Recovery reported per exact algorithm, not per top-level type | **SCAFFOLD PASS** (automation); recovery values NOT_RUN | Airwindows carriers carry `algorithm_id` + `algorithm_name` (e.g. Galactic) in sidecars/summary; per-algorithm recovery table below awaits SXT-028 |
| Substituted variants labeled adaptations, excluded from original coverage | **PASS** (automation) | `substitute` mode: ADAPTED label + `adapted/` tree only; smoke render `doomsday/adapted/seq-notes-coverage-v1-subst-slot04-Reverb1-to-reverb2__ADAPTED.{wav,json}` (Δ 1.372 dB — different, and still disqualified from coverage) |
| Negative control: wrong order flagged by comparator (and by listening) | **PASS** (comparator, with attribution caveat); **BLOCKED-on-human** (listening leg) | fuji permutation detected at 18.481 dB mean ΔRMS; caveat: `setParamVal` param transfer is not bit-exact (readback diffs recorded in the sidecar `mutation` block), so the render differs through order + transfer epsilon together; order-only numeric attribution → SXT-017 policy |

**Labels (essential / optional-by-adaptation / unresolved) for every slot: NOT_RUN →
BLOCKED-on-human.** No listening record exists in this repository; none is claimed.

## Negative controls (live)

| Control | Design | Result |
|---|---|---|
| (a) Off-slot bypass ≡ original | Bypass an already-Off slot; compare SHA-256 vs the preset's own original. sub4 (all 16 Off) slots 0/12; behemoth (Reverb 1 active) slots 0/12 | **PASS** — all four BIT-IDENTICAL. koala2 (free-phase class) offslot: not bit-identical by class; max |Δ| 0.2756 ≤ SXT-012 repeat-render bounds 0.2808–0.3062 → diagnostic non-perturbation only |
| (b) Metadata tamper → refuse | Sidecar hash overwritten; WAV byte flipped (temp copies); pristine tree | **PASS** — both tampers REFUSED (exit 2), pristine tree verified (61 sidecars); transcript `negative-controls.txt` |
| (c) Wrong-order render detected | Exchange contents of fuji's two Delay slots (ains1↔send1) | **PASS with caveat** — comparator flags at 18.481 dB; order-vs-transfer-epsilon attribution not separated numerically (sidecar records the transfer diffs); listening leg BLOCKED-on-human |
| Per-render non-perturbation | After every mutation + settle, all non-mutated slots' type + 12 params + return level must read back bit-identically to the pristine post-load state | **PASS** — enforced in every one of the 61 renders (refuses otherwise) |

Also exercised live and refusing as designed: overwrite protection ("originals never
overwritten"), graphs↔engine type mismatch guard, same-type requirement for
permutation, Off-slot requirement for offslot controls, adapted-tree placement.

## Recovery-by-exact-algorithm table (scaffold — feeds SXT-028)

Recovery is NOT_RUN (no model/RTL exists to recover with). The apparatus records every
ablated slot by exact algorithm so recovery rows can be appended without re-rendering.

| Exact algorithm | Exercised by (preset, slot) | Ablation Δ range (dB, diagnostic) | Recovery (SXT-028) | Status |
|---|---|---|---|---|
| Reverb 1 | doomsday/4, width/5, behemoth/4 | 1.0–47.9 | — | NOT_RUN |
| Delay | doomsday/5, width/4, koala2/4, fmod09/4 | 0.4–30.7 | — | NOT_RUN |
| EQ | doomsday/0, width/0, fmcombo/0 | 0.4–5.1 | — | NOT_RUN |
| Conditioner | doomsday/6 | 1.8–2.2 | — | NOT_RUN |
| Chorus | fmcombo/1 | 1.3–2.1 | — | NOT_RUN |
| Flanger | fmod09/0 | 1.0–2.3 | — | NOT_RUN |
| Airwindows / Galactic | fmod09/5 | 9.8–10.1 | — | NOT_RUN |

## Bytes accounting

61 WAVs, 28,389,884 bytes ≈ 27.1 MiB (28,577,072 bytes ≈ 27.3 MiB tree total including
sidecars and run manifests). No trim was applied: every render is the full
sequence span (last event + 2.5 s tail, settle discarded pre-t=0), under the ~50 MB
budget. Per-WAV SHA-256/bytes in sidecars; totals in `run-*.json`.

## Reproduce

```sh
python3 tools/ablate_fx.py ablate                 # full matrix (6 presets × 2 sequences)
python3 tools/ablate_fx.py offslot-control --preset sub4 --slots 0,12 --render-original-anchor
python3 tools/ablate_fx.py offslot-control --preset behemoth --slots 0,12
python3 tools/ablate_fx.py offslot-control --preset koala2 --slots 0
python3 tools/ablate_fx.py permute --preset fuji --slots 0,4 --render-original-anchor
python3 tools/ablate_fx.py substitute --preset doomsday --slot 4 --to-type fxt_reverb2
python3 tools/ablate_fx.py verify                 # integrity pass (refuses on tamper)
python3 tools/ablation_delta.py                   # deltas + ablation-summary.json
```

Requires the pinned oracle build (`oracle/fetch-and-build.sh`); tools re-exec under the
pinned interpreter. Renders are bit-reproducible only within the recorded environment
and only for the bit-identical repeatability class (see above).

## What remains unproved

- Any effect's essential/optional/unresolved label — requires listening records (#9).
- Wrong-order sensitivity attributable to order alone (transfer-epsilon entanglement).
- Model/RTL fidelity of any effect (SXT-023/024/028); recovery of any algorithm.
- Support/coverage claims for any preset; musical usefulness of anything here.
- Presets outside the pilot set; stereo-field deltas (mono (L+R)/2 committed per
  SXT-012 policy); tail lengths beyond the sequences' 2.5 s.
