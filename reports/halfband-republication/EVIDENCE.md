# Republication after the #123 halfband branch-order fix (issue #145)

Issue: [#145](https://github.com/2AMLogic/gf180-surge/issues/145), the
follow-up that [#123](https://github.com/2AMLogic/gf180-surge/issues/123)
(`reports/halfband-branch-order/`) deliberately left open. Date: 2026-09-27.
Base: `origin/main` @ `38c8270`. Sequencing dependency
[#97](https://github.com/2AMLogic/gf180-surge/issues/97) (RMS-leg polarity)
was already merged (PR #158), so its comparator correction and the #123 delta
are separated below instead of one being absorbed into the other.

**Outcome.** Every committed leaf artifact whose model render passes through
the shared scene decimator `model/voice/voice_model.py::HalfbandD2` was
re-rendered at HEAD, re-compared with `tools/compare_audio_reference.py`
against the reference render that was **already committed** (no new engine
render was made), and republished together with the leaf's own
`EVIDENCE.md`. `reports/coverage-v1/` is re-pinned and republished.
Machine-readable record, one row per case with before/after metrics and
sha256s: `artifacts/republication-record.json`.

## Claim discipline (AGENTS.md)

This record advances exactly three things:

1. **Bookkeeping**: every republished budget JSON describes the committed
   model render next to it (re-derivable byte-for-byte in its metrics;
   `tests/test_halfband_republication.py`, 28 cases).
2. **Attribution**: each pre-#145 committed render is reproduced from the
   committed tree with the pre-#123 decimator ordering, so the recorded
   before -> after delta is the #123 fix alone (one exception, F-033-3, §3).
3. **RTL == frozen model, exact**, re-run at HEAD on every leaf whose RTL
   pairing can run (§4), and the disposition of the two open RTL questions
   (§5).

It establishes **no** fidelity verdict (every budget graded here is
`[PROPOSED-TO-BE-FROZEN-AT-PILOT]`, owned by SXT-017 /
[#12](https://github.com/2AMLogic/gf180-surge/issues/12)), **no**
preset-support claim, **no** listening claim, and **no** FPGA/gf180mcu
synthesis, timing, or hardware claim. A `PASS (PENDING-FREEZE)` budget row is
a number clearing a placeholder, nothing more.

## 1. Method

* **HEAD render**: each leaf's committed runner (`model/voice/run_model.py`,
  `run_lfo_model.py`, `run_mw_model.py`, `run_kt_model.py`,
  `model/oscillators/{classic,sine,wavetable}/run_model.py`) at the base
  commit; output replaces the committed `model-*.wav`.
* **Comparator**: `tools/compare_audio_reference.py` at the base commit (dry
  policy, no per-render normalization, no time-warping). References are the
  committed files, retained unmodified.
* **Attribution**: `tools/halfband_legacy_render.py` runs any runner with
  `HalfbandD2.process` reverted **in-process** to the pre-#123 `A-even`
  reconstruction (`out[n] = (A[2n] + B[2n+1])·0.5`); nothing in the tree is
  modified. Both module objects the runners import (`voice_model` and
  `model.voice.voice_model`) are patched — patching one silently measures
  nothing. If the legacy render equals the committed pre-#145 WAV
  byte-for-byte, the only difference between it and the HEAD render is #123.
* **Comparator isolation**: `pre145_render_current_comparator` re-measures
  the *old* render with the *current* comparator, so an RMS-leg flag flip
  caused by the PR #92 polarity correction (audited in
  `reports/tooling-rms-polarity-audit/`, graded in prose by #97) is visible
  as its own change and never booked to #123.

## 2. Results — model vs committed reference (numbers, not verdicts)

`before` = the pre-#145 committed JSON; `after` = HEAD render, current
comparator. Overall = the comparator's verdict against the `[PROPOSED]`
bounds (max ≤ 3,500 LSB, RMS ≤ −46 dBFS, spectral corr ≥ 0.98), or the
leaf's own proposed bounds where it declares them (SXT-026).

| Leaf | case | max LSB | spectral corr | overall |
|---|---|---|---|---|
| SXT-022 | seq-notes-coverage-v1 | 4,760 → 4,760 | 0.9753 → 0.9791 | FAIL → FAIL |
| SXT-022 | seq-notes-repeated-v1 | 2,321 → 2,328 | 0.9875 → 0.9921 | FAIL → FAIL |
| SXT-022 | seq-modwheel-v1 | 12,677 → 12,686 | 0.9784 → 0.9802 | FAIL → FAIL |
| SXT-026a / SXT-042 | canonical bells (SXT-042 projection ref.) | 16,721 → 16,740 | 0.9207 → 0.9212 | FAIL → FAIL |
| SXT-032 | coverage / repeated / holds / modwheel | 17,998 / 5,062 / 15,506 / 15,505 → 18,030 / 5,626 / 16,070 / 16,069 | 0.9837 / 0.9928 / 0.9834 / 0.9877 → 0.9884 / 0.9972 / 0.9874 / 0.9915 | FAIL → FAIL (all four) |
| SXT-033 | edges / coverage | 90 → 83 | 0.9635 → 0.9744 | FAIL → FAIL |
| SXT-033 | **edges / repeated** | 54 → 33 | 0.9728 → 0.9830 | **FAIL → PASS (PENDING-FREEZE)** |
| SXT-033 | horn / coverage | 10,189 → 4,298 (see F-033-3) | 0.7018 → 0.7535 | FAIL → FAIL |
| SXT-033 | horn / repeated | 3,801 → 3,634 | 0.8035 → 0.8086 | FAIL → FAIL |
| SXT-033 | **tentacles / coverage** | 239 → 242 | 0.9668 → 0.9802 | **FAIL → PASS (PENDING-FREEZE)** |
| SXT-033 | **tentacles / repeated** | 77 → 47 | 0.9723 → 0.9888 | **FAIL → PASS (PENDING-FREEZE)** |
| SXT-033 | crush / coverage, repeated | 65,534 / 22,759 → 65,534 / 22,460 | 0.9876 / 0.9944 → 0.9895 / 0.9961 | FAIL → FAIL |
| SXT-034 | uni1-regress / uni2-cov / uni4-rep | 2,321 / 22,767 / 27,455 → 2,328 / 21,876 / 27,455 | 0.9874 / 0.9624 / 0.9822 → 0.9921 / 0.9644 / 0.9841 | FAIL → FAIL |
| SXT-034 | uni2-poly, uni16-smoke | **STALE / NOT_RUN** | | reference render not committed (sidecar only) |
| SXT-035 | coverage / repeated / modwheel | 4,760 / 2,321 / 65,534 → 4,760 / 2,328 / 65,534 | 0.9754 / 0.9874 / 0.9870 → 0.9791 / 0.9921 / 0.9875 | FAIL → FAIL |
| SXT-040 | badnews coverage / repeated | 210 / 62 → 210 / 62 | 0.9298 / 0.9456 → 0.9306 / 0.9471 | FAIL → FAIL |
| SXT-040 | tentacles coverage / repeated | 3,458 / 3,164 → 3,458 / 3,165 | 0.9381 / 0.9731 → 0.9444 / 0.9773 | FAIL → FAIL |
| SXT-040 | popcorn2k coverage | 1,789 → 1,789 | 0.9606 → 0.9666 | FAIL → FAIL |
| SXT-040 | **popcorn2k repeated** | 888 → 906 | 0.9789 → 0.98002 | **FAIL → PASS (PENDING-FREEZE)** |
| SXT-026 | 9 wavetable rows (kick/mf, base/morph/uni16/pitch-extremes) | see `reports/sxt-026/EVIDENCE.md` change note | kick base 0.9268 → 0.9234; mf base 0.9720 → 0.9756 | no verdict moved (SXT-026 bounds and sxt-022 proposal) |

**Verdict movements (stated explicitly, per the issue's acceptance):** five
budget rows moved **FAIL → PASS (PENDING-FREEZE)** — SXT-033 edges/repeated
(the F-123-2 row #123 predicted), SXT-033 tentacles/coverage and
tentacles/repeated (first recorded here), and SXT-040 popcorn2k/repeated
(first recorded here). Every flip is carried by the spectral-corr leg
crossing the proposed 0.98 floor; margins are 0.0030, 0.0002, 0.0088 and
0.00002 respectively, and two of them are knife-edge. No leaf-level
`model_vs_reference` status moved (SXT-033 and SXT-040 stay `PARTIAL`),
and no row moved PASS → FAIL. SXT-022 seq-modwheel-v1's spectral leg also
crosses 0.98 but its overall stays FAIL.

**Comparator correction reaching the JSONs (not #123).** Regenerating the
JSONs applies the PR #92 RMS-leg polarity to files that were written before
it: `rms_diff_dbfs` flips on SXT-022 coverage/modwheel, SXT-032 ×4,
SXT-034 uni2/uni4, SXT-035 coverage/modwheel and the SXT-026 workhorse rows,
and several SXT-033 edges/tentacles rms legs now grade as passing. Each is
identified as such in the leaf's change note; #97 had already re-graded the
prose.

**Only leaf where agreement got worse on its headline rows:** SXT-026's
workhorse rows still pass the SXT-026 bounds, but the spectral margin
narrowed from 0.0068 to 0.0026–0.0034.

## 3. Attribution and findings

* Every pre-#145 committed render in the record — the 38 case rows (two of
  which, SXT-026a and SXT-042 canonical bells, are the same render) plus the
  SXT-026a integrated wet render `278de788…` — is reproduced
  **byte-identically** by the pre-#123 ordering at HEAD, **except one**
  (F-033-3 below). Those deltas are the #123 fix alone.
* **F-033-3 (new, bounded):** the committed pre-#145
  `reports/SXT-033/artifacts/model-horn-seq-notes-coverage-v1.wav`
  (`c3f5b1c0…`) is reproduced neither by the legacy ordering at HEAD nor by
  the committed tree at that leaf's landing commit `e6ea298` (both give
  `21272035…`, deterministic). Its committed budget row measured bytes the
  committed inputs do not produce. The source-reproducible pre-#123 metric is
  4,295 / −39.95 dBFS / 0.7469 at shift 0, so the true #123 delta on that
  row is 4,295 → 4,298 / 0.7469 → 0.7535; FAIL either way. The artifact is
  replaced by a render from the committed tree, and
  `tests/test_halfband_republication.py` now re-derives every budget JSON
  from its committed render so this class of drift is caught at commit time.
* **SXT-034 NC-1 lost its reference-domain discrimination.** After #123 the
  unison-collapsed control render is *closer* to the uni2 reference than the
  true model on max and RMS and only 0.0018 worse on spectral corr (was
  0.0070). It still FAILs the budget check (as does the true model) and its
  differential vs the true model is 18,238 LSB; recorded in
  `reports/SXT-034/EVIDENCE.md`, discrimination question left with #12.
* **Negative-control sets regenerated at HEAD** (every control still FAILs
  the check it targets; no DISCRIMINATING / NON-DISCRIMINATING / DEGENERATE
  label moved): SXT-022, SXT-026 NC-B, SXT-026a mutants, SXT-032, SXT-033,
  SXT-034 NC-1/2/4/5, SXT-040 (`run_sxt040_checks.py` steps 1–3) and SXT-042
  (`kt_negative_controls.py`). SXT-035's set was already regenerated by #163
  on a tree containing #123. One knife-edge worth naming: SXT-042's C2
  shared-word control now degrades spectral corr by only 1e-5 (its
  discrimination rests on max, RMS and the windowed keytrack metric).

## 4. RTL-vs-model exactness re-run at HEAD

`exactness_runs` in the record, plus the leaf records for the two leaves
whose checks run through their own runners. All clean runs **PASS, 0
mismatches**: SXT-022 ×3 (`tb_voice.sv`); SXT-026a smoke + v1-attacky-smoke;
SXT-032 LFO control plane ×4 (`tb_lfo.sv`); SXT-034
uni1/uni2-cov/uni2-poly/uni4-mech/uni4-rep/uni16-smoke; SXT-035 modwheel
control plane ×3 (`tb_mw.sv`); SXT-040 ×3 (`tb_sine.sv`, full 6,150-block
canonical runs); SXT-042 canonical, synthetic, smoke (`tb_kt.sv`); SXT-033
×4 (`tb_classic.sv`, `tools/run_sxt033_checks.py`, recorded in
`reports/SXT-033/EVIDENCE.md` §10); SXT-026 wavetable base
(`tools/run_sxt026_checks.py` steps 6–7, recorded in
`reports/sxt-026/EVIDENCE.md`). All mutants **FAIL** as required.

**BLOCKED (not a #123 effect, not re-run):** the SXT-032 and SXT-035
*voice-datapath* pairing. `run_lfo_model.py` / `run_mw_model.py` still emit
the pre-SXT-034 stimulus layout while `tb_voice.sv` requires the SXT-034
unison appendix (`FATAL: uni count 0 outside 1..16`). Their
`exactness-voice-*.json` are as-landed and **STALE**; routed to
[#175](https://github.com/2AMLogic/gf180-surge/issues/175).

## 5. The two RTL questions the issue asks to be answered in writing

**Wavetable RTL and the decimator — answered: outside the SXT-026 RTL
boundary; not implemented under other naming, not structurally unnecessary.**
`rtl/oscillators/wavetable/` (`wavetable_core.sv`, `tb_wavetable.sv`) has no
halfband/decimator logic under any name, and `tools/compare_wt_rtl_model.py`
never reads the model trace's 48 kHz `mono_block`: the leaf's RTL-vs-model
check ends at the 2×-rate oscillator output. The model's post-oscillator
stage (`wt_model.py` `Slice`: o2 level, VCA×AEG ramp, scene out, ±8 clip,
`HalfbandD2`, master, clip) therefore has no RTL counterpart today. In the
pinned engine the decimator is a per-**scene** stage, implemented in this
repository in `rtl/voice/tb_voice.sv`; `wt_model.py` instead instantiates one
`HalfbandD2` per voice slice and sums the decimated slices, which differs
from per-scene decimation in fixed-point rounding, the ±8 pre-decimator clip,
and dropped filter ring-out when a voice dies (size not measured). Both gaps
are routed to [#176](https://github.com/2AMLogic/gf180-surge/issues/176) and
stated in `reports/sxt-026/EVIDENCE.md` §2 and the coverage-v1 ledger note;
the wavetable renders were nevertheless republished (§2) because this host
has the pinned engine's external `resources/data/wavetables` asset root
(asset identity verified by the loader's sha256 gate).

**`rtl/voice/voice_wrongparam_mutant.sv` — REFRESHED, still a live FAIL.**
The committed file was a snapshot of `tb_voice.sv` at `4a5a1a5` (pre-SXT-034
cfg layout, pre-#123 decimator order). Measured at HEAD on the
`leaf48-smoke-bells-v1` trace: the snapshot FAILs (41 mismatches) — but its
**unmutated** base FAILs identically (41 mismatches), so it no longer
isolated the parameter it targets. It is regenerated as current
`tb_voice.sv` plus exactly one mutated line (`poles = 32'sd12`, ignoring the
declared `fu_poles`) and a 4-line banner. It FAILs (41 mismatches) while the
clean `tb_voice.sv` PASSes the same trace (193 checkpoints, 0 mismatches).
`tests/test_sxt026a_wrongparam_control.py` asserts the one-line diff and the
live FAIL, so the control cannot drift into a stale snapshot again. Retiring
it was rejected: it is the only SXT-026a parameter-sensitivity control.

## 6. What could not be produced here (NOT_RUN / STALE, with the gap named)

No pinned-oracle build (surgepy) exists on this host, so no reference render
could be produced; only already-committed references were used.

| Item | Status | Gap |
|---|---|---|
| `reports/sxt-026a/artifacts/audio-smoke-bells-dry.json` | **RETIRED (deleted)** | reference for `leaf48-smoke-bells-v1` never committed; metric degenerate by construction (3,904 frames < one 4,096 spectral frame). Smoke evidence stays RTL exactness + mutants. |
| SXT-026a canonical dry numbers 16,960 / −27.87 / 0.9205 | **STALE / NOT_RUN** | box-retained oracle render never committed; the canonical model is re-measured against the committed SXT-042 projection of the same pinned fixture instead (§2). |
| SXT-034 uni2-poly, uni16-smoke budget JSONs | **STALE / NOT_RUN** | `seq-poly-8-v1` uni2 and `sxt034-smoke-v1` uni16 references not committed. |
| SXT-032 / SXT-035 voice-datapath exactness | **BLOCKED** | runner stimulus format (#175). |
| SXT-026 per-segment decomposition and §4 experiments | **STALE** | pre-#123 numbers, not re-measured. |
| SXT-035 `costs.txt` voice qmul counts | **STALE** | come from the blocked pairing. |

## 7. Reproduce

```bash
# HEAD render + comparison (per leaf; example)
python3 model/voice/run_model.py --sequence seq-notes-repeated-v1 --out-dir /tmp/r
python3 tools/compare_audio_reference.py \
  --ref reports/sxt-022/artifacts/reference-seq-notes-repeated-v1-dry.wav \
  --model /tmp/r/model.wav
# the same runner under the pre-#123 ordering (attribution)
python3 tools/halfband_legacy_render.py model/voice/run_model.py \
  --sequence seq-notes-repeated-v1 --out-dir /tmp/legacy
# bookkeeping + control checks
python3 -m pytest tests/test_halfband_republication.py \
  tests/test_sxt026a_wrongparam_control.py tests/test_sxt029_publication.py -q
```

## 8. Explicitly NOT established

Any fidelity verdict or budget freeze (#12); any preset-support or
coverage increase (supported delta 0 on every leaf); any listening claim;
any FPGA/gf180mcu synthesis, place-and-route, timing, or hardware-playback
claim; that the corrected decimator improves musical quality.
