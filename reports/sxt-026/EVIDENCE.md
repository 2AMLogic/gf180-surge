# SXT-026 evidence record — Wavetable assets + playback: compiler manifest, frozen fixed model, exact RTL, external-residency traffic

Branch: `loom/sxt-026-wavetable` · Issue: #19 (SXT-026) · Date: 2026-09-21

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, mono (L+R)/2 evidence bus. Wavetable
authority: pinned `src/common/dsp/oscillators/WavetableOscillator.cpp`,
`src/common/dsp/Wavetable.cpp` (structure read and cited, never copied;
the 63 mip halfband constants are quoted as data under
[decision-records/0004](../../decision-records/0004-wavetable-asset-boundary.md)).

**Claim discipline.** This record advances: (1) *RTL matches the frozen
fixed-point model exactly* (iverilog-simulated; integer equality,
demonstrated), and (2) *the model reproduces the pinned reference within
[PROPOSED] budgets on the workhorse and morph fixtures* (measured,
PENDING-FREEZE) — with **one bounded budget finding at deep-mip pitch
extremes** (section 4) that is NOT silently absorbed. It establishes
**no** preset-support claim, **no** musical-quality claim (no human
listening has occurred), **no** FPGA/gf180mcu synthesis, timing, area, or
hardware-playback claim, and **no** distribution-license determination
(#25). The RTL is an iverilog-simulated behavioral schedule with declared
traffic accounting, not synthesis-closed RTL.

## 0. Real presets (graphs.jsonl, not synthetic)

| Fixture carrier | wta record (normalized graph, authoritative) | Notes |
|---|---|---|
| `Argitoth/Drums/Kick.fxp` | `Basic/Triangle.wt` (`f49a2381…`), osc 1, scene 0 | All 16 FX slots are **Off in the patch's own state** — its wet sound is FX-free by patch data; nothing was substituted or bypassed. WT slice isolated by declared overrides (`mute_o1`, `mute_noise`, `fu1_off`) — test configuration, never an adapted preset, never a coverage claim. |
| `Argitoth/FX/Monster Feedback.fxp` | `Sampled/Banjo 1.wt` (`d610b7ca…`), osc 1 | Second carrier from a different bank; FX are present in the preset and are muted via the declared SXT-012 dry-bypass mechanism in `mf-*` fixtures only. |

Both appear in `corpus/normalized/graphs.jsonl` with resolved `res`
`[path, sha256]` records; the compiler verifies the external file against
the graph's hash at compile time (ABORT on mismatch).

## 1. Issue-#19 acceptance mapping

| # | Acceptance item (issue #19) | Status | Evidence |
|---|---|---|---|
| 1 | Asset identity verified by hash end-to-end; residency matches the accounting model (#10) | **PASS** | Manifest (`derived.wavetable_asset_manifests`: sha256, size, dims, mip/AA structure, interpolation, residency class) embedded in the patch image at compile; end-to-end `verify` re-hashes the external file (`manifest-image-verify.txt`, assets_checked=1 failures=0). NC-A: flipped payload → compile ABORT (exit 2, no image) AND verify ABORT (`nc-a-hash-abort.txt`). Payloads stay external (DR 0004); repo keeps hashes/manifests only (`test_no_wt_payload_committed_in_repo` guard). Residency: external asset memory + per-core frame cache — reconciled against SXT-016 `probe_osc__wavetable_*` rows in section 5. |
| 2 | Interpolation/morph/AA within declared budgets vs the pinned reference at pitch extremes | **PARTIAL — bounded budget finding recorded** | Workhorse + morph variants PASS the proposed bounds (section 3). Pitch extremes: low/mid (mip 0/2) track the reference; deep mips (5/6, notes 96/120) decorrelate immediately (corr −0.19/−0.01) — mechanism verified against pinned source as the engine's float32 phase pipeline (`WavetableOscillator.cpp:278–291,474`), NOT mip-table content (forced-mip0 control also decorrelates; model deep-vs-mip0 corr 0.995). Status vs proposed bounds: **MISS at deep-mip extremes**; escalation in section 4. |
| 3 | Maximum supported unison validated; beyond-limit rejected explicitly | **PASS** | `kick-wtfix-uni16` (MAX_UNISON=16) renders through the model and the RTL with 16 sub-voices; RTL matches the model exactly over the full fixture (section 2). `unison=17` → `run_model` exits 1 with an explicit "explicitly rejected (no clamp)" message (`nc-c-unison-overflow.txt`); the engine clamps silently (SXT-015 flagged 58 presets) — this product contract rejects, per the frozen-model README. |
| 4 | Sustained playback bandwidth measured with effects active; no underruns | **PASS (declared behavioral model)** | uni16 (worst case) full 2250 blocks with concurrent Reverb1 background bus traffic (SXT-016 pattern, 34 words/frame): `reverb_words=76500`, `underrun_blocks=0`, `max_frame_bus_cost` ≤ 32000 (`sustained-concurrent.txt`). Physical external traffic = frame fills + reverb ≈ 1.05 MB/s at the 48 MHz A-CLK candidate — within the SXT-016 E1 floor (8 MB/s). The logical 2-words/impulse demand is served by the on-chip frame cache, not the external bus. The bus/underrun model is DECLARED (behavioral costs), not cycle-accurate RTL — no timing claim. |
| 5 | Negative control: hash mismatch aborts; substituted table fails the reference-budget check | **PASS** | NC-A (above); NC-B model-side: forced deep-mip (`SXT026_NC_B_FORCE_MIP6`) fails the proposed budget on the workhorse while the correct model passes (`nc-b-mip-mutant.txt`); NC-B RTL: the committed mip-threshold mutant (`-DWAVETABLE_MUTANT_MIP`) FAILS RTL-vs-model exactness on the pitch-extreme fixture while the clean RTL passes (`rtl-exactness.txt`). All controls are live — each demonstrably fails the check it targets. |

## 2. RTL-vs-frozen-model exactness (integer equality)

`tools/compare_wt_rtl_model.py` compiles `rtl/oscillators/wavetable/`
with iverilog 11, runs `tb_wavetable.sv` from the model runner's stimulus
(init/ctrl/sinc-ROM/derived-table hex) and requires INTEGER EQUALITY of:
per-voice impulse-engine state at every declared checkpoint (oscstate,
state, last_level, mipmap), morph machinery (tableid, tableipol,
last_tableipol, l_shape), the hpf/output stage (osc_out, bufpos, hpf_prev),
every 64-sample oscillator output block, and the external-traffic
accounting (reads+fills must equal the model's declared words exactly;
any underrun block fails).

Transcript: `rtl-exactness.txt` (regenerated by
`tools/run_sxt026_checks.py` steps 6–7). Coverage: the full 4125-block
pitch-extreme fixture (notes 24/60/96/120 → mips **0/2/5/6** — the mip
window is what makes the RTL mutant control effective; the committed
sequence previously claimed mip5/6 coverage but its mip-2 window was not
exercised — fixed this branch, sequence re-rendered) and the full
2250-block MAX_UNISON fixture. Verdicts: base **PASS** with 0 mismatches
(kt: 2325 checkpoint records + 25575 state fields + 148800 oscillator
output samples + exact external-traffic reconciliation; uni16: 18736
checkpoint records + 74944 output samples under concurrent Reverb1
background traffic); the mip-threshold mutant **FAILS** the same
comparison (first divergence at the mip-2 window's first checkpoint,
block 768).

Determinism: identical reruns produce identical traces (pure integer
model + fixed stimulus; no time dependence).

## 3. Model-vs-reference budgets (PENDING-FREEZE, measured)

Comparator: `tools/compare_audio_reference.py` (dry policy; no
normalization, no time-warping, shift-0 primary). Full matrix in
`budget-metrics.json`. Proposed SXT-026 bounds on the workhorse
(max_abs ≤ 8000 LSB, rms ≤ −30 dBFS, spectral corr ≥ 0.92) and the
pre-registered SXT-022 proposal (3500 / −46 / 0.98) are BOTH evaluated;
neither is frozen.

| Fixture | max_abs LSB | rms dBFS | corr | sxt-026 bounds | sxt-022 proposal |
|---|---|---|---|---|---|
| kick-wtfix / base (workhorse) | 5841 | −36.0 | 0.927 | **PASS** | max_abs MISS |
| kick-wtfix-morph25 / base | 5841 | −36.0 | 0.927 | **PASS** | max_abs MISS |
| kick-wtfix-morph75 / base | 5841 | −36.0 | 0.927 | **PASS** | max_abs MISS |
| kick-wtfix-uni16 / unison16 | 63579 | −11.6 | 0.955 | MISS | MISS |
| kick-wtfix-kt / pitch-extremes-hi | 47262 | −20.3 | 0.938 | MISS | MISS |
| kick-wtfix / pitch-extremes | 18447 | −24.7 | 0.906 | MISS | MISS |
| mf-wtfix / base | 48993 | −12.7 | 0.972 | MISS | MISS |
| mf-wtfix-morph25 / base | 39321 | −12.7 | 0.966 | MISS | MISS |
| mf-wtfix-morph75 / base | 11628 | −19.6 | 0.971 | MISS | MISS |

Per-segment decomposition of the pitch-extreme fixture (new kt sequence):
n24 corr 0.930, n60 (mip 2) corr 0.956, n96 (mip 5) corr −0.189, n120
(mip 6) corr −0.006 — the collapse is confined to deep-mip segments and
is immediate within the note (first 2000 samples of n96: corr −0.398).

## 4. Bounded budget finding: deep-mip pitch extremes (escalation)

**Finding.** Model-vs-reference at deep mips (5/6) decorrelates beyond
any credible sample-domain budget. Discriminating experiments (all local,
/tmp, none committed as artifacts):

- Forced-mip0 model at n96 vs the same reference segment: corr −0.142 —
  **mip-table content is ruled out** as the dominant cause.
- Model deep-mips vs model mip0 at n96: corr 0.995 — on this carrier the
  AA tables barely change the audible result, so the divergence is in
  **phase/rate arithmetic at high pitch**, not AA table construction.
- Pinned source verification: the engine accumulates `oscstate` and forms
  `ipos` in **float32** (`WavetableOscillator.cpp:278,289–291,474–475`);
  at high pitch the per-sample impulse count is ~27×, so float32
  mantissa quantization of the phase pipeline dominates. The frozen model
  is exact-integer by contract (declared deviation 3 in
  `model/oscillators/wavetable/README.md`) and cannot track float32
  truncation without a visible contract revision.

**Status: recorded, not absorbed.** The acceptance item "within declared
budgets at pitch extremes" is NOT established at deep mips under the
proposed bounds. Options belong to the budget-freeze owner (SXT-017
visible contract revision, per plan section 6 and the SXT-022
pre-registration discipline): (a) reproduce the engine's float32 phase
pipeline in the frozen model (word-length and RTL consequences must be
re-frozen), or (b) declare a deep-mip comparison methodology (e.g.
envelope/spectral-domain budgets) instead of sample-domain correlation.
Neither is chosen here. The uni16 and mf misses on the wider fixture set
(same section 3 table) are the same class of finding at lower magnitude
and stay recorded against the SXT-022 proposal rather than silently
widening any budget.

## 5. Traffic: measured numbers, logical vs physical, SXT-016 reconciliation

Declared model (normative, `run_model.py` / tb header): external asset
reads = 2 words/impulse (morph frame pair: both `tid` and `target`
frames) + on-demand frame fills of frames actually read (4-byte f32
words, counted once per (mip, table) per slot; the frame cache persists
across voices — a new note on a loaded table does not re-fetch it). The
RTL reconciles EXACTLY (harness gate): `core_reads_words + core_fill_words
== ext_read_words` on every run. **Fixes this branch** (audio verified
unchanged; render equality checked byte-for-byte on every fixture):
(1) the model's fill accounting previously counted only the `tid` frame
of the pair (and keyed on `tableid` rather than the continuous-mode
interpolated `tid`); (2) the ctrl stream carried released voices'
records without their slotmask bit, desyncing the RTL stream at the
first note release; (3) ctrl records were emitted in creation order
while the testbench consumes slot-number order, pairing records to the
wrong slots once a new voice reuses a lower slot; (4) the testbench
never reset a core on voice creation — a reused slot inherited stale
state (now: `c_newvoice` re-latches init and zeroes slice state, and
the model's fill cache is per-slot persistent to match the physically
persistent on-chip frame cache). (5) the core's `frame_touched` cache-tag
array was declared and initialized for 6×16 entries while mip-6 table
tags index up to 7×16 — the out-of-range tags stayed X, so every mip-6
frame fill went uncounted (outputs were unaffected; traffic was short by
exactly the mip-6 pair).

Full-fixture totals (committed `traffic-*.json`):

| Fixture | blocks | impulses | ext words | fills words | reverb words | underruns | max frame bus cost |
|---|---|---|---|---|---|---|---|
| kick-wtfix / base | 3750 | 65589 | 133226 | 2048 | — | — | — |
| kick-wtfix-kt / pitch-extremes-hi | 4125 | 270303 | 543262 | 2656 | — | 0 | 790/32000 |
| kick-wtfix-uni16 / unison16 | 2250 | 859781 | 1723658 | 4096 | 76500 (34/frame) | **0** | 3052/32000 |

Logical-vs-physical: the logical demand (up to ~764 words/block at 16
unison) is served by the per-core frame cache; the EXTERNAL bus sees
only cache-cold frame fills + Reverb1 background (34 words/frame per the
SXT-016 Reverb1 pattern: 16 composite-tap r/w pairs + predelay 1r/1w) ≈
35.8 words/frame = 1.07 MB/s at the 48 MHz A-CLK candidate (2 cycles/
word, 7500 frames/s) — within the SXT-016 E1 floor (8 MB/s @48 MHz).
The frame budget constant (32000 bus-slots/frame) is a DECLARED harness
constant, not an achievable-clock claim — clock closure remains
SXT-016/SXT-017 scope.

Residency vs SXT-016 probe rows (`probe_osc__wavetable_blit…`):
`osc_state_bytes_per_unison` 512 B and `wt_working_set_bytes` 65536 B
(= 8 KiB mip0 for a 1024×2 f32 table — the probe's generic
49152 b/6 KiB estimate is per- mip0-frame; the measured active set here
is the 2-frame morph pair, 8 KiB) — same order, reconciled rather than
asserted; per-asset working sets are in the manifest (`mips`, `dims`).

## 6. Negative controls (all live; each fails the check it targets)

| Control | Transcript | Mechanism | Outcome |
|---|---|---|---|
| NC-A: substituted/flipped asset | `nc-a-hash-abort.txt` | `Triangle.wt` bytes flipped in a scratch root → compile `ABORT` (exit 2, no image emitted) and `verify` `HASH MISMATCH` ABORT (exit 2) | **PASS** (fails as designed) |
| NC-B model: wrong mip under budget | `nc-b-mip-mutant.txt` | `SXT026_NC_B_FORCE_MIP6` vs correct model on identical inputs; correct PASSES proposed corr/rms bounds, forced-mip6 corr falls below | **PASS** (fails as designed) |
| NC-B RTL: mip-threshold mutant | `rtl-exactness.txt` | `-DWAVETABLE_MUTANT_MIP` (mip-2 threshold halved) vs clean RTL on the pitch-extreme fixture (mip 2 window exercised) | **PASS** (mutant FAILS exactness; clean PASSes) |
| NC-C: unison overflow | `nc-c-unison-overflow.txt` | `unison=17` → explicit rejection exit 1, never clamped | **PASS** (fails as designed) |

## 7. Reproducibility

`python3 tools/run_sxt026_checks.py --asset-root <pinned resources/data>`
regenerates: the manifest image + end-to-end verify transcript (1), NC-A
(2), NC-B (3), NC-C (4), the budget matrix (5, reuses committed
reference renders), the RTL exactness pair (6, regenerates stimulus in
/tmp — never committed), and the sustained concurrent run (7). Requires
the external pinned oracle for steps 1–5 reference re-checks; committed
`*-ref.wav` renders were produced by `tools/render_wt_reference.py`
(deterministic, 3 bit-identical repeats, sidecar JSONs committed).
`python3 -m pytest tests/test_sxt026_wavetable.py` — 13 tests,
deterministic, no oracle required.

Environment: 48 kHz; engine pin above; iverilog 11; python 3.11+.
Executed against the pinned oracle tree (identical pin
`58914e59c608ed4384ba6002e44c3465c58b2e71`; the provisioned remote box
was unreachable for the entire session — deviation recorded in the PR —
so renders, simulations, and checks ran on the local pinned clone;
every artifact carries its identity sidecar and the checks script is
the environment-independent reproducer).

## 8. What this record does NOT establish

- No preset-support claim for `Kick.fxp`, `Monster Feedback.fxp`, or any
  preset: coverage claims require complete wet-preset fidelity
  (effects included) plus listening records. The fixture overrides are
  test configurations, not adapted presets, and count toward nothing.
- No musical-quality claim (no human listening has occurred).
- No gf180mcu/FPGA synthesis, timing, area, or hardware-playback claim;
  the RTL is a behavioral exactness schedule with declared traffic costs.
- No distribution-license determination: `.wt` payloads and the quoted
  mip halfband constants remain flagged into the open determination
  (#25) via decision-records/0004.
- Budget freeze: the proposed bounds and the SXT-022 proposal both remain
  PENDING-FREEZE; the section-4 finding must be resolved by the freeze
  owner, not by widening numbers here.
