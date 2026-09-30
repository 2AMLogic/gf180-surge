# SXT-036 evidence record — voice leaf: modulation behavior velocity

Issue: #70 (SXT-036) · Branch `feature/issue-70` · Date: 2026-09-30
(fifth increment)
Pinned engine (cited only, external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz.

**Scope and claim discipline.** Landed under the #96 re-queue policy: only
the oracle-independent acceptance items. The pinned oracle (`surgepy`,
`oracle/manifest.json`, `ORACLE_SURGE_DIR`) is **not available on this
dispatch host** (`import surgepy` → `ModuleNotFoundError`; re-verified
2026-09-30 for the fifth increment, as for the second, third and fourth;
`ORACLE_SURGE_DIR` unset, no prebuilt cache, #232 still open). This record establishes claim (1) only, for
the declared fixture on the leaf-local sequence, on the three sequences named
by #70, and at the declared parameter corners:
**RTL == frozen model, exactly**, in iverilog simulation. It establishes **no** model-vs-reference agreement
(claim 2: NOT_RUN), **no** fidelity, **no** preset support (supported delta
0), **no** musical-quality claim (claim 3), and **no** FPGA/gf180mcu
synthesis, timing or hardware playback. No Surge code/tables/assets are
copied; the model and RTL are original (Apache-2.0).

## Acceptance status

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order | **PASS** (documented + implemented) | `model/voice/run_vel_model.py`; freeze section "SXT-036 velocity / release-velocity route extension" in `model/voice/README.md`. Q10.21 words, `vel_q=(midi*2^22+127)//254`, route order, destination class {308,309,310,298}, per-instance state. Scope: classic voice class on the declared Attacky carrier only (see Boundaries). **Parameter corners now frozen too** (third increment, README point 7): derived destination extents, the declared corner set, and the 32-bit checkpoint-word precondition with its measured headroom — `artifacts/param-corners.{txt,json}`. **State rules now frozen with controls** (fourth increment, README point 8): construction re-initialization of the release-velocity register on slot reuse, the same-block release-latch timing, and the scene-A-only destination class with its refusal control — `artifacts/state-coverage.{txt,json}`. |
| 2 | Model-vs-pinned-engine dry-render budgets on carrier fixtures | **NOT_RUN** | pinned oracle unavailable on dispatch host (#96). No numbers estimated or tuned. |
| 3 | RTL-vs-model exact at declared checkpoints (integer equality) | **PASS** | `artifacts/exactness-vel-sxt036-vel-overlap-v1.json`: 2,940 voice-block checkpoints, 5,880 source words, 11,760 route sums, 0 mismatches (`tb_vel.sv`). `artifacts/exactness-voice-sxt036-vel-overlap-v1.json`: unchanged-datapath `tb_voice.sv` on the same run: 279 checkpoints / 9,765 fields / 17,856 oscout / 103,200 mono samples, 0 mismatches. Landed regression (SXT-022 seq-notes-repeated-v1, run_model.py stimulus): 403 / 14,105 / 25,792 / 196,800, 0 mismatches (`exactness-voice-landed-regression-*.json`); landed model wav is sha256-identical to `--strip-vel-routes` output (`9b7e7f90...`; was `6a73bb9a...` before main's halfband D2 fix #146, republished in `reports/halfband-republication/`). **Extended to the three sequences named by #70** (`artifacts/declared-sequence-coverage.{txt,json}`): `seq-notes-coverage-v1` / `seq-notes-repeated-v1` / `seq-notes-holds-v1`, control plane 3,132 / 1,944 / 4,392 checkpoints and datapath 467 / 403 / 255 checkpoints, **0 mismatches everywhere**. Coverage of that PASS is reported separately below, including one recorded gap (declared set is monophonic ⇒ per-instance-state not discriminated there). **Extended again to the declared parameter corners and to the whole source-word domain** (third increment, `artifacts/param-corners.{txt,json}`): six declared corners × (2,088 control-plane checkpoints / 4,176 source words / 8,352 route sums) and (312 datapath checkpoints / 10,920 fields / 19,968 oscout / 36,800 mono) each, **0 mismatches everywhere**; all **128** velocity-ROM entries exact. Survey run `seq-poly-8-v1` (8 concurrent voices): 14,784 control-plane checkpoints, 0 mismatches. |
| 4 | Cycle/state costs vs SXT-016 probes / SXT-015 | **PASS (recorded, divergences noted)** | `artifacts/costs.txt`: 6 qmul per running-voice block (0.171 MAC/sample control plane), 512 state bits for the per-slot source registers; SXT-016 scheduler probe has no per-source row (88 cycles/event, 512 state bits = different quantity). Not reconciled. **Per-route linearity measured** (third increment): every corner run uses an 8-route table and reports `DONE vel-qmuls=16704` = 8 × 2,088 voice-blocks exactly, confirming the "one qmul per route per running-voice block" cost rule the accounting states rather than assuming it. State is unchanged (route table is fixture-constant; the per-slot registers do not grow with routes). **The SXT-015 half of this item is recorded for the first time** (fifth increment): `tools/vel_cost_accounting.py` → `artifacts/cost-accounting.{txt,json}` — measured op profile per route evaluation, the 0..6 route-table sweep, the per-frame-vs-per-live-voice **shape divergence** against `cyc_modroute_frame` on the named carriers (12.25× / 4.46× / 7.00×), the missing modulation-state row, and a fail-closed pin on the SXT-015 cost model. See "Cost accounting against the SXT-015 accounting" below. |
| 5 | Negative controls fail the reference-budget check (routing-zeroed per destination class; source-swap modwheel) | **NOT_RUN** | Requires the pinned-engine render (#96). What did run is a different check, below. |

### Oracle-independent controls that DID run (exactness check, not item 5)

`tools/vel_negative_controls.py` → `artifacts/negative-control.txt`,
`negative-controls.json` (overall PASS: every control failed or held as required):

* E1 zero-route for each of the six routes (velocity→cutoff/reso/fegmod/vca,
  release velocity→cutoff/vca), E2 source-swap (scene modwheel in place of
  velocity/release velocity), E3 shared (scene-wide) velocity register,
  **E4 stale-slot release velocity** (fourth increment: construction does not
  clear the reused slot's release-velocity register): a mutated model trace
  against the unmodified RTL **FAILS** integer equality (41–44 mismatches
  each; E4 42, first `block 1200 slot 0 relvel_q: model=330260 rtl=0`), and
  each mutated model render differs from the unmutated one (16 to 15,309 LSB
  max abs; E4 3,287) so the routes and the re-initialization are observable.
* E-rtl mutants (`artifacts/tb_vel_*_mutant.sv`): shared-slot register,
  round→truncate in qmul, velocity ROM floor instead of round, **stale-slot
  re-initialization** and **release latch one block late** (both fourth
  increment): each **FAILS** against the unmodified model (45 / 41 / 44 /
  42 / 15 mismatches).
* M2 invariance: routes stripped reproduces the landed SXT-022 model wav
  bit-identically. R1 refusals: velocity→'A Highpass' (303) and zeroing a
  nonexistent route both exit 2. **R2 refusal** (fourth increment): the real
  scene-B route the named carrier `House Of Chords.fxp` carries
  (velocity→502 `B Osc 1 Sync`, scene index 1) exits 2 — a scene-B
  destination is refused, never folded into the scene-A class.
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

### Parameter-corner accounting (third increment, still oracle-independent)

Issue #70 names three declared input sets under "Fixtures and oracle": carrier
presets (accounted for above), sequences (above), and **parameter corners** —
"the leaf freezes the observed normalized parameter ranges of its carriers plus
the engine-declared ranges at the pin". That third set was previously
unaccounted for. `tools/vel_param_corners.py` →
`artifacts/param-corners.{txt,json}`, from `graphs.jsonl` + iverilog only. New
stimulus: `model/voice/sequences/sxt036-vel-corners-v1.json` (all MIDI source
corners on overlapping voices, including one voice at velocity 127 **and**
release velocity 127 — the only combination that drives both source words to
full scale at once). Overall verdict **PASS** (every declared corner exact,
every control fired).

**Ranges, derived not read back.** `depth_raw / depth_normalized` in
`graphs.jsonl` is the destination parameter's full extent; the ratio agrees
across hundreds of independent corpus rows, which is how the extents are
derived without an engine readback:

| dest | derived extent | rows | relative spread | corner uses |
|---|---|---|---|---|
| 308 `A Filter 1 Cutoff` | 130.0076 | 2,914 | 0.194 % | 130.0 |
| 309 `A Filter 1 Resonance` | 1.0 | 874 | 0.000 % | 1.0 |
| 310 `A Filter 1 FEG Mod Amount` | 192.0066 | 483 | 0.011 % | 192.0 |
| 298 `A VCA Gain` | 95.9966 | 838 | 0.025 % | 96.0 |

Observed normalized depth range of both sources over the whole corpus:
**[−1, +1]** (`ms_velocity` 5,212 route rows; `ms_releasevelocity` 162). In
class: velocity→308 576 rows, →309 127, →310 258, →298 62; release
velocity→308 12 rows, →309 2, and **zero** rows for →310 and →298 (that
fallback to full scale is printed in the transcript, not silent). These are
corpus-pipeline values, so they are **falsifiable predictions** for the oracle
host (#232), never reference values.

**Exhaustive source-word domain.** The corner sweep alone would touch six of
the 128 velocity-ROM entries, so the whole domain is checked: the `vel_rom`
function is lifted verbatim out of `rtl/voice/tb_vel.sv` into a generated
enumerating bench (`artifacts/tb_vel_rom_generated.sv`) and all **128** RTL
words match the frozen model quantizer exactly, **0 mismatches**. Control: the
`rom-floor` mutation (drop the `+127` rounding) makes that check **FAIL on 63
of 128 entries**.

**Declared corners (each PASS, 0 mismatches, control plane and datapath).**

| corner | worst \|route sum\| | 32-bit headroom | ties | note |
|---|---|---|---|---|
| `full-scale-positive` (norm +1) | 805,306,368 | 2.67× | 0 | worst declared corner |
| `full-scale-negative` (norm −1) | 805,306,368 | 2.67× | 0 | |
| `mixed-sign-full-scale` | 402,653,184 | 5.33× | 0 | per-destination cancellation |
| `one-lsb` (`depth_q` = ±1) | 1 | — | 0 | rounding floor of the qmul |
| `rounding-tie-half` (±0.5) | 1,048,576 | 2,048× | **6,144** | exact .5 products |
| `observed-corpus-extreme` | 805,306,368 | 2.67× | 0 | largest \|depth_raw\| in the corpus per pair |

Per corner: 2,088 control-plane checkpoints / 4,176 source words / 8,352 route
sums (`tb_vel.sv`) and 312 checkpoints / 10,920 fields / 19,968 oscout / 36,800
mono samples (`tb_voice.sv`, unchanged datapath). No qmul saturated at any
declared corner. The corner stimulus overlaps voices with distinct source words
in **498** blocks, so unlike the declared `seq-notes-*` set it *is* a
per-instance-state carrier — and that is shown rather than asserted: the whole
oracle-independent control set re-run on it
(`artifacts/negative-control-sxt036-vel-corners-v1.txt`,
`negative-controls-sxt036-vel-corners-v1.json`) reports **PASS for every
control that ran** — the six zero-route controls (41 mismatches each),
source-swap (44), E3 shared-state (44), the shared-slot / round-trunc /
rom-floor RTL mutants (45 / 41 / 42), all three refusals and the invariance
check fire there. **Amended by the fourth increment:** when this increment
added the construction-re-initialization controls, the corner stimulus turned
out NOT to reuse a voice slot after a nonzero release velocity, so those two
controls are `NOT_RUN` there and this transcript's exit code is now **3**, not
0. The third increment's "nothing NOT_RUN" wording was true of the control set
that existed then and is superseded here rather than left standing.

**Controls (each demonstrably fails the check it targets).**

* **Rounding rule.** At the ±0.5 corner, `depth × source` lands exactly on the
  .5 boundary 6,144 times (asserted, not assumed — a corner set with no tie
  would not be freezing the rounding rule). The `round-trunc` RTL mutant
  **FAILS** there: 44 mismatches.
* **Checkpoint-word boundary.** The per-destination route sum is a 32-bit
  signed word in the RTL and an unbounded Python integer in the model, so the
  frozen checkpoint definition holds only while |sum| ≤ 2^31−1. The declared
  corners keep **2.67× headroom**; the deliberately out-of-range
  `over-range-accumulator` corner (3× the derived extent) **FAILS** as
  required — 41 mismatches, first one `model=2415919104 rtl=-1879048192`, the
  exact 32-bit wrap. Recorded as a boundary of the freeze, **not** designed
  around and **not** used to loosen anything.
* `rom-floor` on the exhaustive ROM check (above).
* **Anchor drift.** `tests/test_sxt036_vel_corners.py` (20 tests, CI-visible, no
  iverilog needed) asserts that every RTL mutation anchor the controls use still
  exists in `rtl/voice/tb_vel.sv` — a mutant whose anchor drifted would silently
  become a no-op and a "passing" control — plus the quantizer over its whole
  128-word domain, the tie property, both range-derivation refusals, and the
  32-bit checkpoint accounting on both sides of the boundary. This leaf had no
  pytest coverage before this increment.

**Per-instance-state survey (closes an open question, not the gap).** The
second increment recorded that all three declared sequences are monophonic, so
the per-instance-state controls cannot fire there. `seq-poly-8-v1` — the only
polyphonic note fixture committed in `fixtures/sequences/` — is now rendered
and *measured* instead of assumed: 8 concurrent voices, control plane
**PASS** with 14,784 checkpoints / 29,568 source words / 59,136 route sums and
0 mismatches, but **all eight voices carry velocity 70 and release velocity 0**
(`concurrent_distinct_source_word_blocks = 0`), so a scene-wide shared register
would pass it too. **No committed shared fixture discriminates the
per-instance-state rule**; the leaf-local `sxt036-vel-overlap-v1` (and now the
overlapping corner stimulus) remains the only carrier for that control. The gap
is therefore narrowed in its description, not closed.

### Per-instance STATE accounting (fourth increment, still oracle-independent)

The first three increments froze the arithmetic (words, op order, rounding,
corners) and proved RTL==model on it. Two rules this leaf's own issue states
had **no live control at all**, and both are oracle-independent:
construction-time re-initialization of the per-slot release-velocity register
(cited: `SurgeVoice` ctor `releaseVelocitySource.set_output(0, 0)`) and the
"never shared across **scenes**" half of the per-instance rule. Addressed as
follows; nothing here touches items 2 or 5, which stay `NOT_RUN`.

**Three new live controls** (each demonstrably fails the check it targets;
transcripts in `artifacts/negative-control*.txt/.json`):

| control | targets | verdict on `sxt036-vel-overlap-v1` |
|---|---|---|
| E4 `--stale-slot-relvel` (model) | reused slot inherits the previous voice's release velocity | **FAILS** exactness, 42 mismatches; render differs by 3,287 LSB |
| E-rtl `stale-slot-reinit` | same rule, mutated on the RTL side (`tb_vel.sv` create branch) | **FAILS**, 42 mismatches (`model=0 rtl=330260`) |
| E-rtl `release-one-block-late` | release latch moved after the control pass (SXT-021 event timing) | **FAILS**, 15 mismatches |
| R2 `--cross-scene-route` | a scene-B destination silently folded into the scene-A class | **REFUSES** (exit 2) |

The re-initialization mutant deliberately leaves the power-on reset of all
eight slot register pairs alone — that is a different mechanism, and a mutant
that disturbed both would not isolate the ctor rule (asserted in
`tests/test_sxt036_vel_state.py`).

**Coverage census, reported separately from agreement.**
`tools/vel_state_coverage.py` → `artifacts/state-coverage.{txt,json}`
(model runs only; no iverilog, no oracle). Three stimulus preconditions decide
whether these controls can fire — `per_instance`, `slot_reuse`,
`release_word` — measured by **one** implementation that the control driver
imports, so census and controls cannot disagree. Over **all 22** committed
note sequences (static screen) plus six rendered (dynamic):

| stimulus | per_instance | slot_reuse | release_word |
|---|---|---|---|
| `seq-notes-coverage-v1` (declared) | no | no | no |
| `seq-notes-repeated-v1` (declared) | no | no | no |
| `seq-notes-holds-v1` (declared) | no | no | **yes** (1) |
| `seq-poly-8-v1` (only polyphonic shared fixture) | no | no | no |
| `sxt036-vel-overlap-v1` (leaf-local) | **yes** (1,071) | **yes** (2) | **yes** (5) |
| `sxt036-vel-corners-v1` (leaf-local) | **yes** (498) | no | **yes** (5) |

**Recorded coverage gaps (findings, not green ticks):**

* Exactly **one of the 18 shared fixtures** (`seq-notes-holds-v1`) carries any
  nonzero MIDI release velocity at all — one note-off out of four. For the
  other 17 both release-velocity preconditions are **impossible by inspection
  of the file**, which is why no render is needed to say so. `ms_release
  velocity` (id 30) is therefore almost entirely unexercised by the shared
  fixture set.
* **No shared fixture** satisfies `per_instance` or `slot_reuse`. The
  construction-re-initialization controls are consequently reported `NOT_RUN`
  on all three sequences named by #70 **and** on the corner stimulus, with the
  precondition named — never as a pass. `sxt036-vel-overlap-v1` is the only
  committed stimulus satisfying all three.
* Adding a polyphonic, distinct-velocity, slot-reusing sequence to
  `fixtures/sequences/` would be a change to shared fixtures and stays out of
  this leaf's scope.

**Scene boundary — refused, not demonstrated.** R2 shows a scene-B
destination is refused by the frozen class. It does **not** show that state is
never shared across scenes: this leaf's model instantiates **one scene**, so
that half of #70's per-instance rule has no live control here and is **not
claimed**. Making it testable needs a second scene in the model, which is
outside this leaf.

**Exit codes seen:** `vel_state_coverage.py` → 3 (census complete, two shared
fixture coverage gaps recorded — by design, not a failure);
`vel_negative_controls.py` → 0 on `sxt036-vel-overlap-v1` (every control fired),
3 on `seq-notes-holds-v1` (4 NOT_RUN) and 3 on `sxt036-vel-corners-v1` (2
NOT_RUN). `pytest tests/test_sxt036_vel_state.py tests/test_sxt036_vel_corners.py`
→ 35 passed.

**Invariance held:** normal-mode output is unchanged by this increment — the
baseline run-dir sha256s are still model.wav `14b04618…a5b18` and
model_trace.json `e2a11ee5…9fe53`, and M2 (`--strip-vel-routes` reproducing the
landed SXT-022 wav, `9b7e7f90…`) still holds.

### Cost accounting against the SXT-015 accounting (fifth increment, still oracle-independent)

Acceptance item 4 asks for costs "recorded against SXT-016 probes **and the
SXT-015 accounting**". Increments 1–4 recorded the SXT-016 half only
(`artifacts/costs.txt`: the scheduler probe has no per-source-evaluation row).
The SXT-015 half had never been recorded. `tools/vel_cost_accounting.py` →
`artifacts/cost-accounting.{txt,json}` records it, from iverilog and committed
corpus artifacts only. Overall verdict **PASS** (every measured law held, every
control fired).

**What SXT-015 charges.** `model/resources/accounting.py`:
`mod_cycles = _count_modroutes(g) * REG.cyc_modroute_frame`, i.e. **15 cycles
per modulation row per frame**, each row counted **once** regardless of how
many voices are live. `cyc_modroute_frame` is a `placeholder` param whose
`estimate_ref` names SXT-016 — and **no SXT-016 probe replaces it**: over all
**76** committed probe records, `sxt015_replacement.replaces` covers
`cyc_filter_unit_frame`, `cyc_fxdelay_frame`, `cyc_fxgeneric_frame`,
`cyc_fxreverb1_frame`, `cyc_osc_unison_voice_frame` and `cyc_event_frame`,
never `cyc_modroute_frame`. That claim is asserted by the tool (and reported
**STALE**, not silently dropped, if a probe ever pins the row).

**Measured cost law** (new `OPS` counters in `rtl/voice/tb_vel.sv`; the
`DONE vel-qmuls=` line and every traced value are unchanged, and the counters
are placed clear of every mutation anchor so the landed controls still work —
asserted in `tests/test_sxt036_vel_cost.py`):

| stimulus | R | frames | control passes | route evals | max live voices | exact |
|---|---|---|---|---|---|---|
| `sxt036-vel-overlap-v1` (leaf-local) | 6 | 3,225 | 2,940 | 17,640 | 3 | PASS |
| `seq-notes-coverage-v1` (declared) | 6 | 8,550 | 3,132 | 18,792 | 1 | PASS |
| `seq-notes-repeated-v1` (declared) | 6 | 6,150 | 1,944 | 11,664 | 1 | PASS |
| `seq-notes-holds-v1` (declared) | 6 | 9,300 | 4,392 | 26,352 | 1 | PASS |
| `seq-poly-8-v1` (only polyphonic shared fixture) | 6 | 5,550 | 14,784 | 88,704 | 8 | PASS |

`route evaluations = routes × per-voice control passes` on every run, with
exactly **1 mul32 + 1 add64 + 2 cmp64 + 1 add32** per evaluation, plus one
event-rate `vel_rom` read per note-on and per note-off (counted from the same
declared stimulus stream the bench consumes — the latch blocks are mutation
anchors and stay byte-identical). A **0..6 route-table sweep** on the
leaf-local stimulus (declared sidecar truncated, depths unchanged) holds the
law at every R, and every measured run is *also* checked exact against the
frozen model as a positive control, so the cost is measured on the frozen
schedule and not on some other one.

**Cycles are NOT measured.** Op counts are. A cycles figure appears only as a
bracket derived under two explicitly named readings of the SXT-016 assumptions
(A-DSP-1c, A-ALU-1): **2 .. 8 candidate cycles per evaluation**. Against that
bracket the accounted constant (15 cycles per row per frame) is 1.88×–7.50×
conservative *per evaluation* — while the shape below understates a voice row.
No probe claim, no technology, timing, synthesis or hardware claim.

**Divergence 1 — shape (recorded, not reconciled).** Both sources of this leaf
are PER-VOICE, so their routes are voice-list rows, and the measured schedule
evaluates a voice row once per **live voice** per frame. At the accounting's
own worst-case voice count:

| carrier named by #70 | global / scene / voice rows | rows charged | accounted mod cycles/frame | worst voices | measured evals/frame | shape × |
|---|---|---|---|---|---|---|
| `Bad News.fxp` | 0 / 1 / 3 | 4 | 60 | 16 | 49 | **12.25** |
| `Rainy Day Dreamaway.fxp` | 0 / 10 / 3 | 13 | 195 | 16 | 58 | **4.46** |
| `House Of Chords.fxp` | 2 / 4 / 4 | 10 | 150 | 16 | 70 | **7.00** |
| `Attacky.fxp` (fixture carrier) | 0 / 2 / 0 | 2 | 30 | 16 | 2 | 1.00 |

The row split is cross-checked against SXT-015's own `_count_modroutes` (the
tool REFUSES if the two disagree), and the accounted term is read from
`account_graph`, not recomputed. **Scope limits stated rather than glossed:**
the modulation term is a small part of these accounts (voice cost dominates),
every carrier above is already `rejected` (`budget_overflow`) under
`placeholder-v0`, so the correction changes a **term, not any fit verdict**;
re-pinning a cost row is SXT-016/SXT-017 work and this leaf is not a probe —
the finding is filed as bounded follow-up **#239** rather than fixed here.
Note also that the divergence is **invisible on the fixture carrier** (no voice
rows of its own, shape × = 1.00) — it only appears on the carriers #70 names,
which is exactly why the fixture adds declared synthetic voice routes.

**Divergence 2 — state scope (recorded, not resolved).** The leaf holds 8 slots
× {`vel_q`, `relvel_q`} × 32 b = **512 bits** of per-instance source state, and
that count is load-bearing rather than padding because the scene-wide-register
mutant FAILS exactness (K6 reads that verdict back from the committed
transcript: 45 mismatches; reported NOT_RUN, never assumed, if the transcript
is absent). SXT-015 has **no modulation-source state row at all**: modulation
rows feed cycles only, and on-chip state is `worst_voices ×
voice_base_state_bytes` (4096 B, whose own note enumerates "mixer/ring/FM
registers" and excludes filter state) + osc + filter + LFO rows. This leaf's
8 B per voice is therefore *unnamed* in the accounting — inside that
placeholder bucket or missing from it, and the parameter's description does not
say which.

**Controls (each demonstrably fails the check it targets).**

| control | targets | verdict |
|---|---|---|
| K1 per-frame shape | predicting evaluations with SXT-015's voice-count-independent shape (routes × frames) | **MISPREDICTS** (19,350 vs measured 17,640) |
| K2 route-count-blind | predicting with a fixed route count | **MISPREDICTS** at R = 0..5 |
| K3 attribution | an empty route table must measure zero multiply work; a cost model that charges per frame regardless | **MISPREDICTS** (predicts 19,350 where the measurement is 0), so all measured multiply work is attributable to the routes |
| K4 pin drift | a mutated SXT-015 pin (profile / digest / `cyc_modroute_frame`) | **REFUSES** (exit 2); per-field in `tests/test_sxt036_vel_cost.py` |
| K5 probe-claim detector | a synthetic probe record claiming to replace `cyc_modroute_frame` | **DETECTED** (so "no probe pins this row" is falsifiable) |
| K6 state cross-check | the 512-bit figure without a live per-instance control | **PASS** via the committed shared-register mutant (45 mismatches) |

**Fail-closed pins.** The comparison is pinned to SXT-015
`sxt-015-accounting/1.0.0` / `placeholder-v0` / params digest `646942e9c3887ecb`
/ `cyc_modroute_frame = 15`, plus the `graphs.jsonl` sha256 #70 pins. Drift
refuses (exit 2) so the recorded divergence is **re-recorded** against a new
cost model rather than silently carried forward, and
`tests/test_sxt036_vel_cost.py` (36 tests, CI-visible, no iverilog) fails if
the live SXT-015 model moves away from the pin.

**costs.txt is no longer unchecked.** The first increment's hand-assembled
`artifacts/costs.txt` quoted four numbers; all four are now re-derived by the
tool (6 qmul per running-voice block, 512 per-slot state bits, probe
`cycles_per_event` 88, probe `state_ram_bits` 512) and reported **OK** — a
change would be reported STALE rather than silently diverging.

**Invariance held:** this increment adds only write-only counters to
`rtl/voice/tb_vel.sv`. Re-running every landed driver against the modified
bench reproduces the committed transcripts byte-identically —
`negative-control{,-seq-notes-holds-v1,-sxt036-vel-corners-v1}.{txt,json}` and
`param-corners.txt`, same mismatch counts, same exit codes (0 / 3 / 3 / 0).
`param-corners.json` re-ran identical except for embedded run-tempdir paths, so
it keeps its committed content. The only committed files that change are the
generated mutant `.sv` artifacts, which are copies of the modified bench. The
model itself is untouched (no change to `run_vel_model.py` or the model
trace), so the baseline run-dir sha256s are still model.wav `14b04618…a5b18`
and model_trace.json `e2a11ee5…9fe53`.

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

Parameter-corner accounting (added 2026-09-29, third increment):

```
python3 tools/vel_param_corners.py --artifacts reports/SXT-036/artifacts
python3 tools/vel_negative_controls.py --artifacts reports/SXT-036/artifacts \
    --sequence sxt036-vel-corners-v1
python3 -m pytest -q tests/test_sxt036_vel_corners.py      # 20 passed, no iverilog
```
Exit codes seen: `vel_param_corners.py` → 0 (every declared corner exact, every
control fired); `vel_negative_controls.py --sequence sxt036-vel-corners-v1` → 3
since the fourth increment (the two construction-re-initialization controls are
NOT_RUN there; it was 0 against the third increment's smaller control set);
`vel_declared_coverage.py` → 3 (exact everywhere, one coverage gap recorded —
by design, not a failure).

Per-instance state accounting (added 2026-09-30, fourth increment):

```
python3 tools/vel_state_coverage.py --artifacts reports/SXT-036/artifacts
python3 tools/vel_negative_controls.py --artifacts reports/SXT-036/artifacts
python3 tools/vel_negative_controls.py --artifacts reports/SXT-036/artifacts \
    --sequence seq-notes-holds-v1
python3 tools/vel_negative_controls.py --artifacts reports/SXT-036/artifacts \
    --sequence sxt036-vel-corners-v1
python3 -m pytest -q tests/test_sxt036_vel_state.py \
    tests/test_sxt036_vel_corners.py      # 35 passed, no iverilog
```

Cost accounting against SXT-015 (added 2026-09-30, fifth increment):

```
python3 tools/vel_cost_accounting.py --artifacts reports/SXT-036/artifacts
python3 -m pytest -q tests/test_sxt036_vel_cost.py    # 36 passed, no iverilog
```
Exit codes seen: `vel_cost_accounting.py` → 0 (every measured law held, every
control fired, divergences recorded) when the committed control transcript is
present in the artifacts directory; → 3 when it is absent (K6 reported NOT_RUN
rather than assumed); → 2 if the SXT-015 cost model or the `graphs.jsonl`
sha256 pin moved.

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
  cannot fire on them and are reported `NOT_RUN` there; `seq-poly-8-v1`, the
  only polyphonic note fixture committed in `fixtures/sequences/`, was measured
  and does not discriminate either (eight voices, one velocity). The leaf-local
  `sxt036-vel-overlap-v1` and `sxt036-vel-corners-v1` sequences remain the only
  stimuli in this leaf that discriminate per-voice from scene-wide velocity
  state. Adding a polyphonic, distinct-velocity sequence to the shared
  `fixtures/sequences/` set would be a change to shared fixtures and is out of
  this leaf's scope. **Fourth increment**: this is now measured across *all*
  22 committed note sequences rather than the four previously spot-checked —
  exactly one shared fixture carries any nonzero release velocity, and none
  reuses a slot after one, so `sxt036-vel-overlap-v1` is the only committed
  stimulus on which the construction-re-initialization controls can fire
  (`artifacts/state-coverage.{txt,json}`).
* **Scene separation is not demonstrated.** #70's per-instance rule has two
  halves. Per-*voice* state is controlled (E3, E4, the shared-slot and
  stale-slot RTL mutants). "Never shared across **scenes**" is **not**: the
  landed model has a single scene, so the only thing shown is that a scene-B
  destination is REFUSED (control R2, replaying the real
  `House Of Chords.fxp` route velocity→502). Status for that half:
  **NO_VERDICT**, needs a two-scene model outside this leaf.
* **Checkpoint-word precondition (parameter corners).** The declared RTL/model
  checkpoint for a destination is the *unsaturated* sum of that destination's
  route terms: 32-bit signed in `tb_vel.sv`, unbounded in the Python model.
  Every declared corner fits with ≥ 2.67× headroom and is exact; beyond ≈2.67×
  full-scale depth the two definitions diverge (demonstrated, 41 mismatches,
  exact 32-bit wrap). The audio path itself is unaffected — the model saturates
  each destination parameter (`vm.sat`) as the RTL word does — so this is a
  boundary of the *checkpoint* definition, recorded here and in
  `model/voice/README.md` point 7 rather than tightened away. Whether the
  pinned engine can even present a modulation depth beyond normalized ±1 on
  these destinations is an engine question, not answerable on this host, and is
  left to the oracle backfill.
* **MIDI note-on velocity 0** is deliberately absent from the corner stimulus:
  in MIDI it is a note-off, and whether the pinned engine ever constructs a
  voice with `fvel = 0` needs the oracle. The `vel_q = 0` word is still
  exercised, via the release-velocity register the engine itself initializes to
  0 at construction (cited).
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
  `artifacts/param-corners.json` → `derived_ranges` adds a second prediction
  set for the same host: the four destination extents (130 / 1 / 192 / 96) and
  the observed normalized depth range [−1, +1] of both sources. A live
  `getModDepth01` / parameter-range readback on the pinned engine should
  reproduce them; a disagreement is again a corpus-pipeline finding, and the
  corner *depths* would then be re-derived from the engine rather than
  re-tuned to keep the corners green.
* **Cost accounting is bookkeeping, not a cost pin.** The fifth increment
  measures op counts on this leaf's own behavioral schedule and confronts them
  with the SXT-015 accounting. It does **not** pin `cyc_modroute_frame` (only an
  SXT-016 probe record does that), does not correct
  `model/resources/accounting.py` (SXT-016/SXT-017 work, deliberately out of
  this leaf), and every cycles figure in it is derived under a named assumption
  rather than measured — no synthesis, timing, area or hardware claim. The
  worst-case-voice factors use the accounting's own `worst_case_voices` (16),
  while this leaf's RTL has 8 slots: the shape factors are therefore statements
  about the *accounting model's* worst case, not measurements of a 16-voice
  RTL run.
* **Modulation rows outside this leaf are not measured.** The shape finding
  applies to voice-list rows of the two sources this leaf implements. Whether
  every other voice-list modsource (LFOs, envelopes, aftertouch, keytrack…)
  has the same per-live-voice shape is untested here, and the scene/global rows
  were not measured at all — the tool records their charge, not their cost.
* Also recorded, not reconciled: the SXT-016 probe divergence (see costs).
