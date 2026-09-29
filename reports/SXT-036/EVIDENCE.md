# SXT-036 evidence record — voice leaf: modulation behavior velocity

Issue: #70 (SXT-036) · Branch `feature/issue-70` · Date: 2026-09-29
Pinned engine (cited only, external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz.

**Scope and claim discipline.** Landed under the #96 re-queue policy: only
the oracle-independent acceptance items. The pinned oracle (`surgepy`,
`oracle/manifest.json`, `ORACLE_SURGE_DIR`) is **not available on this
dispatch host** (`import surgepy` fails). This record establishes claim (1)
only for the declared fixture: **RTL == frozen model, exactly**, in
iverilog simulation. It establishes **no** model-vs-reference agreement
(claim 2: NOT_RUN), **no** fidelity, **no** preset support (supported delta
0), **no** musical-quality claim (claim 3), and **no** FPGA/gf180mcu
synthesis, timing or hardware playback. No Surge code/tables/assets are
copied; the model and RTL are original (Apache-2.0).

## Acceptance status

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order | **PASS** (documented + implemented) | `model/voice/run_vel_model.py`; freeze section "SXT-036 velocity / release-velocity route extension" in `model/voice/README.md`. Q10.21 words, `vel_q=(midi*2^22+127)//254`, route order, destination class {308,309,310,298}, per-instance state. Scope: classic voice class on the declared Attacky carrier only (see Boundaries). |
| 2 | Model-vs-pinned-engine dry-render budgets on carrier fixtures | **NOT_RUN** | pinned oracle unavailable on dispatch host (#96). No numbers estimated or tuned. |
| 3 | RTL-vs-model exact at declared checkpoints (integer equality) | **PASS** | `artifacts/exactness-vel-sxt036-vel-overlap-v1.json`: 2,940 voice-block checkpoints, 5,880 source words, 11,760 route sums, 0 mismatches (`tb_vel.sv`). `artifacts/exactness-voice-sxt036-vel-overlap-v1.json`: unchanged-datapath `tb_voice.sv` on the same run: 279 checkpoints / 9,765 fields / 17,856 oscout / 103,200 mono samples, 0 mismatches. Landed regression (SXT-022 seq-notes-repeated-v1, run_model.py stimulus): 403 / 14,105 / 25,792 / 196,800, 0 mismatches (`exactness-voice-landed-regression-*.json`); landed model wav is sha256-identical to `--strip-vel-routes` output (`9b7e7f90...`; was `6a73bb9a...` before main's halfband D2 fix #146, republished in `reports/halfband-republication/`). |
| 4 | Cycle/state costs vs SXT-016 probes / SXT-015 | **PASS (recorded, divergence noted)** | `artifacts/costs.txt`: 6 qmul per running-voice block (0.171 MAC/sample control plane), 512 state bits for the per-slot source registers; SXT-016 scheduler probe has no per-source row (88 cycles/event, 512 state bits = different quantity). Not reconciled. |
| 5 | Negative controls fail the reference-budget check (routing-zeroed per destination class; source-swap modwheel) | **NOT_RUN** | Requires the pinned-engine render (#96). What did run is a different check, below. |

### Oracle-independent controls that DID run (exactness check, not item 5)

`tools/vel_negative_controls.py` → `artifacts/negative-control.txt`,
`negative-controls.json` (overall PASS: every control failed or held as required):

* E1 zero-route for each of the six routes (velocity→cutoff/reso/fegmod/vca,
  release velocity→cutoff/vca), E2 source-swap (scene modwheel in place of
  velocity/release velocity), E3 shared (scene-wide) velocity register: a
  mutated model trace against the unmodified RTL **FAILS** integer equality
  (41–44 mismatches each), and each mutated model render differs from the
  unmutated one (16 to 15,309 LSB max abs) so the routes are observable.
* E-rtl mutants (`artifacts/tb_vel_*_mutant.sv`): shared-slot register,
  round→truncate in qmul, velocity ROM floor instead of round: each **FAILS**
  against the unmodified model (41/45/44 mismatches).
* M2 invariance: routes stripped reproduces the landed SXT-022 model wav
  bit-identically. R1 refusals: velocity→'A Highpass' (303) and zeroing a
  nonexistent route both exit 2.
* These controls are the exactness-side analogue. They do **not** replace
  the required reference-budget controls (item 5), which stay NOT_RUN.

## Commands (reproduce)

```
python3 model/voice/run_vel_model.py --sequence sxt036-vel-overlap-v1 --out-dir RUN
python3 tools/compare_vel_rtl_model.py --run-dir RUN
python3 tools/compare_rtl_model.py --run-dir RUN
python3 tools/vel_negative_controls.py --artifacts reports/SXT-036/artifacts
```
Run-dir sha256 (baseline): model.wav `14b04618...a5b18`, model_trace.json
`e2a11ee5...9fe53` (after rebase onto main incl. the halfband D2 fix #146;
pre-rebase baseline was `11b6d081...4e624` / `4dee6405...acb341`).

## Boundaries and what remains unproved

* **Fixture provenance.** The issue's named carriers (Bad News, Rainy Day
  Dreamaway, House Of Chords) are outside the landed classic-voice class
  (Bad News, for example, routes velocity to Osc 2 Volume (275), outside the
  frozen destination class; carrier class membership was not otherwise audited here); per the SXT-035/SXT-032 convention the
  fixture is Attacky plus DECLARED synthetic velocity/release-velocity
  routes (`model/voice/attacky_vel_inputs.json`). Depths are hand-declared,
  **not** engine readbacks, and the preset blob was not re-verified against
  the census by an extractor on this host (`blob_verified: false`). The
  sequence `sxt036-vel-overlap-v1` is model/voice-local; the issue's named
  `fixtures/sequences/seq-notes-*` sequences were not run through the new
  runner. Supported delta from this leaf: 0 presets.
* **Unproved:** model-vs-engine agreement for velocity and release
  velocity (whether the engine's release-velocity source timing, SLOW_EXP
  smoothing identity, and route order match the cited reading is untested
  here); reference-budget negative controls; fidelity; sound quality;
  synthesis/timing/hardware.
* **Backfill.** The issue remains open until items 2 and 5 pass on an
  oracle host (#232). Existing scripts to reuse there: `tools/render_fixture.py`,
  `tools/compare_audio_reference.py`, and an extractor modelled on
  `model/voice/extract_mw_inputs.py` to replace `attacky_vel_inputs.json`.
* Also recorded, not reconciled: the SXT-016 probe divergence (see costs).
