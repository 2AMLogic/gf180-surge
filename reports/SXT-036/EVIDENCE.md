# SXT-036 evidence record — voice leaf: modulation behavior velocity

Issue: #70 (SXT-036) · Branch `feature/issue-70` · Date: 2026-09-29
Pinned engine (cited only, external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz.

**Scope and claim discipline.** Landed under the #96 re-queue policy: only
the oracle-independent acceptance items. The pinned oracle (`surgepy`,
`oracle/manifest.json`, `ORACLE_SURGE_DIR`) is **not available on this
dispatch host** (`import surgepy` fails; re-verified 2026-09-29 for the
second increment). This record establishes claim (1) only, for the declared
fixture on the leaf-local sequence and on the three sequences named by #70:
**RTL == frozen model, exactly**, in iverilog simulation. It establishes **no** model-vs-reference agreement
(claim 2: NOT_RUN), **no** fidelity, **no** preset support (supported delta
0), **no** musical-quality claim (claim 3), and **no** FPGA/gf180mcu
synthesis, timing or hardware playback. No Surge code/tables/assets are
copied; the model and RTL are original (Apache-2.0).

## Acceptance status

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order | **PASS** (documented + implemented) | `model/voice/run_vel_model.py`; freeze section "SXT-036 velocity / release-velocity route extension" in `model/voice/README.md`. Q10.21 words, `vel_q=(midi*2^22+127)//254`, route order, destination class {308,309,310,298}, per-instance state. Scope: classic voice class on the declared Attacky carrier only (see Boundaries). |
| 2 | Model-vs-pinned-engine dry-render budgets on carrier fixtures | **NOT_RUN** | pinned oracle unavailable on dispatch host (#96). No numbers estimated or tuned. |
| 3 | RTL-vs-model exact at declared checkpoints (integer equality) | **PASS** | `artifacts/exactness-vel-sxt036-vel-overlap-v1.json`: 2,940 voice-block checkpoints, 5,880 source words, 11,760 route sums, 0 mismatches (`tb_vel.sv`). `artifacts/exactness-voice-sxt036-vel-overlap-v1.json`: unchanged-datapath `tb_voice.sv` on the same run: 279 checkpoints / 9,765 fields / 17,856 oscout / 103,200 mono samples, 0 mismatches. Landed regression (SXT-022 seq-notes-repeated-v1, run_model.py stimulus): 403 / 14,105 / 25,792 / 196,800, 0 mismatches (`exactness-voice-landed-regression-*.json`); landed model wav is sha256-identical to `--strip-vel-routes` output (`9b7e7f90...`; was `6a73bb9a...` before main's halfband D2 fix #146, republished in `reports/halfband-republication/`). **Extended to the three sequences named by #70** (`artifacts/declared-sequence-coverage.{txt,json}`): `seq-notes-coverage-v1` / `seq-notes-repeated-v1` / `seq-notes-holds-v1`, control plane 3,132 / 1,944 / 4,392 checkpoints and datapath 467 / 403 / 255 checkpoints, **0 mismatches everywhere**. Coverage of that PASS is reported separately below, including one recorded gap (declared set is monophonic ⇒ per-instance-state not discriminated there). |
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

### Declared-input accounting (second increment, still oracle-independent)

The first increment established exactness on the leaf-local
`sxt036-vel-overlap-v1` sequence only, and justified the fixture substitution
from a single example route. Both of the issue's *declared* input sets are now
accounted for from committed artifacts — no oracle involved.

**Declared sequences.** `tools/vel_declared_coverage.py` →
`artifacts/declared-sequence-coverage.{txt,json}`. All three sequences named
by #70 run through `run_vel_model.py` and both exactness harnesses; every
verdict is **PASS, 0 mismatches**:

| Declared sequence | `tb_vel.sv` control plane | `tb_voice.sv` datapath |
|---|---|---|
| `seq-notes-coverage-v1` | 3,132 ckpts / 6,264 source words / 12,528 route sums | 467 ckpts / 16,345 fields / 29,888 oscout / 273,600 mono |
| `seq-notes-repeated-v1` | 1,944 / 3,888 / 7,776 | 403 / 14,105 / 25,792 / 196,800 |
| `seq-notes-holds-v1` | 4,392 / 8,784 / 17,568 | 255 / 8,925 / 16,320 / 297,600 |

**Coverage, reported separately from that agreement.** The declared set
exercises three distinct `ms_velocity` words (`495390`, `1155911`, `1981561`
= velocities 30/70/120) and one nonzero `ms_releasevelocity` word (`1651301`
= release velocity 100, `seq-notes-holds-v1`), with a nonzero route term on
all four frozen destinations. **Recorded coverage gap:** every declared
sequence is strictly monophonic (`max_concurrent_voices = 1`, 0 blocks with
two concurrently-live voices carrying distinct source words), so the declared
set **does not discriminate the per-instance-state rule** — a scene-wide
shared `{vel, relvel}` register would pass all three runs. That is a property
of the stimuli, not of the implementation, so it does not turn the exactness
verdicts red; it is recorded, and the driver exits 3 rather than 0.

**The control set re-run on a declared sequence** (`--sequence
seq-notes-holds-v1` → `artifacts/negative-control-seq-notes-holds-v1.txt`,
`negative-controls-seq-notes-holds-v1.json`) confirms the above is a real
coverage limit and not a green tick: the six zero-route controls, the
source-swap control, the round→truncate and ROM-floor RTL mutants, both
refusals and the invariance check all **fail/hold as required there**, while
**E3 shared-state and the E-rtl shared-slot mutant are reported `NOT_RUN`**
with the precondition named ("stimulus never has two concurrently-live voices
with distinct source words"). They are *not* reported as passes. Those two
controls do fire on the overlapping leaf-local sequence (1,071 qualifying
blocks; 44/45 mismatches — see `negative-control.txt`), which is why that
sequence remains the per-instance-state carrier for this leaf.

**Declared carriers.** `model/voice/audit_vel_carriers.py` →
`artifacts/carrier-route-audit.{txt,json}`, from `graphs.jsonl` (sha256
re-verified equal to the value pinned in #70) and the census CSV only:

* `Bad News.fxp`: velocity → 275 `A Osc 2 Volume` (out of class) **and**
  velocity → 308 `A Filter 1 Cutoff` raw 28.350002 / norm 0.218077 (in class).
* `Rainy Day Dreamaway.fxp`: velocity → 275 only (out of class).
* `House Of Chords.fxp`: velocity → 502 `B Osc 1 Sync`, scene B (out of the
  frozen scene-A class).
* **No named carrier has any `ms_releasevelocity` route at all**, and the
  fixture carrier `Attacky.fxp` has no velocity route of its own — which is
  why the fixture adds declared synthetic routes instead of reusing preset
  routes. This replaces the previous single-example justification.
* Refusal control (in-process, committed in the transcript): sha256-pin
  mismatch, absent carrier, and census-vs-graphs blob disagreement each
  **refuse as required**.
* Claim limits held deliberately: the blob check is a *cross-check between two
  committed artifacts*, **not** a payload hash of the `.fxp` (that needs the
  pinned Surge tree), so `attacky_vel_inputs.json` keeps
  `blob_verified: false`; graphs depths are corpus-pipeline values, **not**
  engine readbacks, so the in-class depth above is recorded as a *falsifiable
  prediction* for the oracle host, never as a reference value. Supported-preset
  delta from this leaf stays **0**.

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

Declared-input accounting (added 2026-09-29, second increment):

```
python3 tools/vel_declared_coverage.py --artifacts reports/SXT-036/artifacts
python3 tools/vel_negative_controls.py --artifacts reports/SXT-036/artifacts \
    --sequence seq-notes-holds-v1
python3 model/voice/audit_vel_carriers.py --out-dir reports/SXT-036/artifacts
```

## Boundaries and what remains unproved

* **Fixture provenance.** The issue's named carriers (Bad News, Rainy Day
  Dreamaway, House Of Chords) are outside the landed classic-voice class; per
  the SXT-035/SXT-032 convention the fixture is Attacky plus DECLARED
  synthetic velocity/release-velocity routes
  (`model/voice/attacky_vel_inputs.json`). Carrier route membership is now
  audited rather than asserted from one example — see "Declared-input
  accounting" above and `artifacts/carrier-route-audit.txt`. Still true and
  unchanged: fixture depths are hand-declared, **not** engine readbacks, and
  the `.fxp` payload was not hashed on this host (`blob_verified: false` — the
  audit's census-vs-graphs agreement is strictly weaker). Supported delta from
  this leaf: 0 presets.
* **Stimulus coverage.** The issue's three named `fixtures/sequences/seq-notes-*`
  sequences now run through the new runner and both exactness harnesses (0
  mismatches). They are all monophonic, so the per-instance-state controls
  cannot fire on them and are reported `NOT_RUN` there; the leaf-local
  `sxt036-vel-overlap-v1` sequence remains the only stimulus in this leaf that
  discriminates per-voice from scene-wide velocity state.
* **Unproved:** model-vs-engine agreement for velocity and release
  velocity (whether the engine's release-velocity source timing, SLOW_EXP
  smoothing identity, and route order match the cited reading is untested
  here); reference-budget negative controls; fidelity; sound quality;
  synthesis/timing/hardware.
* **Backfill.** The issue remains open until items 2 and 5 pass on an
  oracle host (#232). Existing scripts to reuse there: `tools/render_fixture.py`,
  `tools/compare_audio_reference.py`, and an extractor modelled on
  `model/voice/extract_mw_inputs.py` to replace `attacky_vel_inputs.json`.
  `artifacts/carrier-route-audit.json` carries the
  `oracle_host_backfill_predictions` list for that host to confirm or
  contradict (currently one entry: `Bad News.fxp` velocity → 308, normalized
  depth 0.218077); a disagreement there is a finding about the corpus
  pipeline, not a tuning opportunity.
* Also recorded, not reconciled: the SXT-016 probe divergence (see costs).
