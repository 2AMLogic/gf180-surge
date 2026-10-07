# SXT-036 evidence record — voice leaf: modulation behavior velocity

Issue: #70 (SXT-036) · Branch `feature/issue-70` · Date: 2026-10-02
(seventh increment)
Pinned engine (cited only, external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, 48 kHz.

**Scope and claim discipline.** Increments 1–6 landed under the #96 re-queue
policy: only the oracle-independent acceptance items, with the pinned oracle
unavailable on every dispatch host tried. **#232 ("Prebuilt pinned Surge
oracle for dispatch workers") closed 2026-10-02**, and a sha256-verified
prebuilt install is genuinely present on this seventh increment's host
(`surgepy.getVersion()` reports the pinned commit; `.installed-sha256`
matches `oracle/manifest.json`). `tools/vel_oracle_status.py`'s strict gate
previously recognized a git-worktree checkout only — structurally unable to
accept a prebuilt install, which has no `.git` — so it still measured
`UNAVAILABLE` even with the oracle reachable. This increment extends the
gate to accept BOTH provisioning shapes (additively; see "Prebuilt oracle
provisioning accepted" below) and runs the one leg that needs the checkout
only (`blob-verify-carriers`, **PASS**). **Measured gate on this host:
`AVAILABLE`**; acceptance items 2 and 5 move to **`RUNNABLE`** (the gate is
open) but stay **`NOT_RUN`** (no number produced) — the remaining four legs
all need a built `surgepy` AND, done naively, would invalidate this leaf's
already-committed frozen evidence (see the seventh-increment section below
for why), so they are deferred to a follow-up issue (#308) rather than attempted
here. This record establishes claim (1) only, for the declared fixture on
the leaf-local sequence, on the three sequences named by #70, and at the
declared parameter corners: **RTL == frozen model, exactly**, in iverilog
simulation, PLUS the fixture carrier's and the three named carriers' `.fxp`
payload bytes now genuinely verified against the pinned checkout. It
establishes **no** model-vs-reference agreement (claim 2: NOT_RUN), **no**
fidelity, **no** preset support (supported delta 0), **no** musical-quality
claim (claim 3), and **no** FPGA/gf180mcu synthesis, timing or hardware
playback. No Surge code/tables/assets are copied; the model and RTL are
original (Apache-2.0).

## Acceptance status

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Frozen fixed-point model, word lengths + op order | **PASS** (documented + implemented) | `model/voice/run_vel_model.py`; freeze section "SXT-036 velocity / release-velocity route extension" in `model/voice/README.md`. Q10.21 words, `vel_q=(midi*2^22+127)//254`, route order, destination class {308,309,310,298}, per-instance state. Scope: classic voice class on the declared Attacky carrier only (see Boundaries). **Parameter corners now frozen too** (third increment, README point 7): derived destination extents, the declared corner set, and the 32-bit checkpoint-word precondition with its measured headroom — `artifacts/param-corners.{txt,json}`. **State rules now frozen with controls** (fourth increment, README point 8): construction re-initialization of the release-velocity register on slot reuse, the same-block release-latch timing, and the scene-A-only destination class with its refusal control — `artifacts/state-coverage.{txt,json}`. **Fixture provenance partially upgraded** (seventh increment, README point 11): `blob-verify-carriers` hashes the fixture carrier and the three named carriers against the pinned checkout — **PASS, 4/4 byte-identical**; `attacky_vel_inputs.json.preset.blob_verified` now `true` (was `false`). The `fixture_routes` depths themselves remain hand-declared — a separate, not-yet-done re-extraction (see item 2). |
| 2 | Model-vs-pinned-engine dry-render budgets on carrier fixtures | **NOT_RUN** | pinned oracle unavailable on every dispatch host tried through the sixth increment (#96/#232). No numbers estimated or tuned. **Measured, not asserted, since the sixth increment**: `artifacts/oracle-status.json` → `oracle_gate.status`. **Seventh increment: the gate now measures `AVAILABLE`** (prebuilt provisioning, #232 closed) and this item's legs (`render-reference`, `compare-budgets`) move to `RUNNABLE` — but stay `NOT_RUN`: running them as specified would replace `attacky_vel_inputs.json`'s hand-declared depths with engine readbacks, which risks invalidating every already-committed comparison artifact that embeds today's depth values unless the re-extraction is first shown to round-trip them exactly. Deferred to a follow-up issue (#308) rather than attempted hastily; the emitter cannot express `PASS` for a leg it did not run regardless (control O6). |
| 3 | RTL-vs-model exact at declared checkpoints (integer equality) | **PASS** | `artifacts/exactness-vel-sxt036-vel-overlap-v1.json`: 2,940 voice-block checkpoints, 5,880 source words, 11,760 route sums, 0 mismatches (`tb_vel.sv`). `artifacts/exactness-voice-sxt036-vel-overlap-v1.json`: unchanged-datapath `tb_voice.sv` on the same run: 279 checkpoints / 9,765 fields / 17,856 oscout / 103,200 mono samples, 0 mismatches. Landed regression (SXT-022 seq-notes-repeated-v1, run_model.py stimulus): 403 / 14,105 / 25,792 / 196,800, 0 mismatches (`exactness-voice-landed-regression-*.json`); landed model wav is sha256-identical to `--strip-vel-routes` output (`9b7e7f90...`; was `6a73bb9a...` before main's halfband D2 fix #146, republished in `reports/halfband-republication/`). **Extended to the three sequences named by #70** (`artifacts/declared-sequence-coverage.{txt,json}`): `seq-notes-coverage-v1` / `seq-notes-repeated-v1` / `seq-notes-holds-v1`, control plane 3,132 / 1,944 / 4,392 checkpoints and datapath 467 / 403 / 255 checkpoints, **0 mismatches everywhere**. Coverage of that PASS is reported separately below, including one recorded gap (declared set is monophonic ⇒ per-instance-state not discriminated there). **Extended again to the declared parameter corners and to the whole source-word domain** (third increment, `artifacts/param-corners.{txt,json}`): six declared corners × (2,088 control-plane checkpoints / 4,176 source words / 8,352 route sums) and (312 datapath checkpoints / 10,920 fields / 19,968 oscout / 36,800 mono) each, **0 mismatches everywhere**; all **128** velocity-ROM entries exact. Survey run `seq-poly-8-v1` (8 concurrent voices): 14,784 control-plane checkpoints, 0 mismatches. |
| 4 | Cycle/state costs vs SXT-016 probes / SXT-015 | **PASS (recorded, divergences noted)** | `artifacts/costs.txt`: 6 qmul per running-voice block (0.171 MAC/sample control plane), 512 state bits for the per-slot source registers; SXT-016 scheduler probe has no per-source row (88 cycles/event, 512 state bits = different quantity). Not reconciled. **Per-route linearity measured** (third increment): every corner run uses an 8-route table and reports `DONE vel-qmuls=16704` = 8 × 2,088 voice-blocks exactly, confirming the "one qmul per route per running-voice block" cost rule the accounting states rather than assuming it. State is unchanged (route table is fixture-constant; the per-slot registers do not grow with routes). **The SXT-015 half of this item is recorded for the first time** (fifth increment): `tools/vel_cost_accounting.py` → `artifacts/cost-accounting.{txt,json}` — measured op profile per route evaluation, the 0..6 route-table sweep, the per-frame-vs-per-live-voice **shape divergence** against `cyc_modroute_frame` on the named carriers (12.25× / 4.46× / 7.00×), the missing modulation-state row, and a fail-closed pin on the SXT-015 cost model. Both recorded divergences were then **dispositioned in #239** (shape changed to per-evaluation charging; modulation-source state declared inside `voice_base_state_bytes`), and this tool now cross-checks the shape rather than recording a gap; the per-evaluation constant is still an unpinned placeholder. See "Cost accounting against the SXT-015 accounting" below. |
| 5 | Negative controls fail the reference-budget check (routing-zeroed per destination class; source-swap modwheel) | **NOT_RUN** | Requires the pinned-engine render (#96/#232). What did run is a different check, below. **Measured, not asserted, since the sixth increment**: `artifacts/oracle-status.json` leg `reference-budget-controls`. **Seventh increment: gate now `AVAILABLE`, leg now `RUNNABLE`** — but stays `NOT_RUN` for the same reason as item 2 (running it needs the same at-risk re-extraction); deferred to the same follow-up issue (#308). |

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

**What SXT-015 charges.** `model/resources/accounting.py`, since the shape
decision this increment fed (**#239**, merged after this record was first
written): `mod_cycles = _modroute_evaluations(g, worst_voices) *
REG.cyc_modroute_frame`, i.e. **15 cycles per modulation row EVALUATION**,
with a global/scene-list row evaluated once per frame and a voice-list row
once per worst-case live voice per frame. (As first recorded here it was
`_count_modroutes(g) * REG.cyc_modroute_frame` — every row once per frame,
regardless of how many voices are live; that is the shape the measurement
below retired.) `cyc_modroute_frame` is a `placeholder` param whose
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
bracket the accounted constant (15 cycles per row evaluation) is 1.88×–7.50×
conservative *per evaluation*, and since #239 it is applied to the measured
number of evaluations rather than to the row count.
No probe claim, no technology, timing, synthesis or hardware claim.

**Divergence 1 — shape: recorded here, DISPOSITIONED in #239.** Both sources
of this leaf are PER-VOICE, so their routes are voice-list rows, and the
measured schedule evaluates a voice row once per **live voice** per frame. At
the accounting's own worst-case voice count:

| carrier named by #70 | global / scene / voice rows | rows charged | accounted mod cycles/frame (before → now) | worst voices | measured evals/frame | shape × |
|---|---|---|---|---|---|---|
| `Bad News.fxp` | 0 / 1 / 3 | 4 | 60 → **735** | 16 | 49 | **12.25** |
| `Rainy Day Dreamaway.fxp` | 0 / 10 / 3 | 13 | 195 → **870** | 16 | 58 | **4.46** |
| `House Of Chords.fxp` | 2 / 4 / 4 | 10 | 150 → **1050** | 16 | 70 | **7.00** |
| `Attacky.fxp` (fixture carrier) | 0 / 2 / 0 | 2 | 30 → **30** | 16 | 2 | 1.00 |

`shape ×` is evaluations ÷ rows — a property of the graph, not of the
accounting, so it does not change when the accounting does. The row split is
cross-checked against SXT-015's own `_count_modroutes` (the tool REFUSES if
the two disagree), and the accounted term is read from `account_graph`, never
recomputed. **Since #239 the tool CROSS-CHECKS the shape** instead of
recording a gap: `accounted mod cycles == evals/frame × cyc_modroute_frame`
must hold on every carrier (`shape_resolution.per_carrier` in
`cost-accounting.json`) or the run FAILS. What is still recorded as a
divergence is the per-evaluation **constant** (15 vs the derived 2..8
bracket), which only an SXT-016 probe may pin; #239 explicitly did not, and
nothing here is tuned to agree.

**Scope limits stated rather than glossed:** the modulation term is a small
part of these accounts (voice cost dominates) and every carrier above is
already `rejected` (`budget_overflow`) under `placeholder-v0`, so on **these
carriers** the correction changed a term and no fit verdict — as this record
first said. Corpus-wide it did move 9 of 3,561 `placeholder-v0` closures,
all `within_budget → OVERFLOW`, enumerated in `reports/sxt-015/EVIDENCE.md`
§8.3 and in `reports/sxt-015/decision-239-modroute-shape.json`; a
`placeholder-v0` closure is not a preset-support claim in either direction
and the supported-preset delta stays 0. Note also that the divergence was
**invisible on the fixture carrier** (no voice rows of its own, shape × =
1.00) — it only appears on the carriers #70 names, which is exactly why the
fixture adds declared synthetic voice routes.

**Divergence 2 — state scope (recorded, not resolved).** The leaf holds 8 slots
× {`vel_q`, `relvel_q`} × 32 b = **512 bits** of per-instance source state, and
that count is load-bearing rather than padding because the scene-wide-register
mutant FAILS exactness (K6 reads that verdict back from the committed
transcript: 45 mismatches; reported NOT_RUN, never assumed, if the transcript
is absent). SXT-015 has **no modulation-source state row at all**: modulation
rows feed cycles only, and on-chip state is `worst_voices ×
voice_base_state_bytes` (4096 B) + osc + filter + LFO rows. This leaf's 8 B
per voice was therefore *unnamed* in the accounting — inside that placeholder
bucket or missing from it, with the parameter's description silent on which.
**#239 decided it:** per-voice modulation-source registers are declared
INSIDE `voice_base_state_bytes`, whose `estimate_ref` now enumerates them
explicitly, with **no separate row** and **no re-tuned value** (still
4096 B). This leaf's 8 B/voice covers two sources only and is a lower bound
on a full source set, never a row value; SXT-016 re-derives that bucket at
the selected word lengths and may then split the row out
(`state.sxt015_modulation_state_disposition` in `cost-accounting.json`).

**Controls (each demonstrably fails the check it targets).**

| control | targets | verdict |
|---|---|---|
| K1 per-frame shape | predicting evaluations with the retired voice-count-independent shape (routes × frames, what SXT-015 charged before #239) | **MISPREDICTS** (19,350 vs measured 17,640) |
| K2 route-count-blind | predicting with a fixed route count | **MISPREDICTS** at R = 0..5 |
| K3 attribution | an empty route table must measure zero multiply work; a cost model that charges per frame regardless | **MISPREDICTS** (predicts 19,350 where the measurement is 0), so all measured multiply work is attributable to the routes |
| K4 pin drift | a mutated SXT-015 pin (profile / digest / `cyc_modroute_frame`) | **REFUSES** (exit 2); per-field in `tests/test_sxt036_vel_cost.py` |
| K5 probe-claim detector | a synthetic probe record claiming to replace `cyc_modroute_frame` | **DETECTED** (so "no probe pins this row" is falsifiable) |
| K6 state cross-check | the 512-bit figure without a live per-instance control | **PASS** via the committed shared-register mutant (45 mismatches) |

**Fail-closed pins.** The comparison is pinned to SXT-015
`sxt-015-accounting/1.1.0` / `placeholder-v0` / params digest `a639d3115ae1a0ca`
/ `cyc_modroute_frame = 15`, plus the `graphs.jsonl` sha256 #70 pins. Drift
refuses (exit 2) so the comparison is **re-recorded** against a new cost model
rather than silently carried forward, and `tests/test_sxt036_vel_cost.py`
(39 tests, CI-visible, no iverilog) fails if the live SXT-015 model moves away
from the pin. That tripwire fired exactly as designed when #239 moved the
model: the pin was **re-recorded from the live model** (version + digest) and
the artifacts re-run, never re-tuned — `cyc_modroute_frame` is still pinned at
15.

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

### Oracle gate and backfill plan (sixth increment, still oracle-independent)

Increments 1–5 reported items 2 and 5 `NOT_RUN` on the strength of a hand-run
`python3 -c "import surgepy"` plus the prose in this file. That is the right
verdict but the wrong kind of evidence: it is not committed, not
machine-readable, and not falsifiable. `tools/vel_oracle_status.py` →
`artifacts/oracle-status.json` + `artifacts/oracle-backfill.txt` makes it
measured, matching the convention the sibling leaves already use
(`tools/rf_send34_oracle_status.py`, `tools/rf_global34_oracle_status.py`,
`tools/phaser_oracle_status.py` → `reports/SXT-028*/artifacts/oracle-status.json`).
Nothing here runs an oracle-gated leg and nothing here can move an acceptance
item to PASS.

**Measured gate on this host: `UNAVAILABLE`** — no checkout at the probed
location (`/Users/joseph/dev/surge-xt-oracle/surge`, the SXT-010 manifest's
`expected_checkout`; `ORACLE_SURGE_DIR` unset), no importable `surgepy` under
either reading. Items 2 and 5 stay `NOT_RUN`.

**The gate is read strictly.** A bare `import surgepy` is *not* evidence of the
pinned oracle — any importable `surgepy` on `PYTHONPATH` satisfies it. The
probe additionally requires the checkout to exist, to be a git work tree, to
sit at the pinned commit `58914e59…`, and the imported module file to live
*inside* that checkout. Four statuses are distinguished rather than collapsed:
`AVAILABLE`, `PIN_MISMATCH` (a checkout at the wrong commit — refused, never
downgraded to "unavailable"), `UNPINNED_SURGEPY` (something imports, but not
from the pin — refused loudly), `UNAVAILABLE`.

**Legs are split by the gate each actually needs**, so the cheap one is not
bundled behind the expensive one:

| leg | item | gate | status |
|---|---|---|---|
| `blob-verify-carriers` | 1 (fixture provenance) | pinned **checkout only** | NOT_RUN |
| `extract-fixture-depths` | 1 (feeds 2 and 5) | checkout + built `surgepy` | NOT_RUN |
| `render-reference` | 2 | checkout + built `surgepy` | NOT_RUN |
| `compare-budgets` | 2 | checkout + built `surgepy` | NOT_RUN |
| `reference-budget-controls` | 5 | checkout + built `surgepy` | NOT_RUN |

`blob-verify-carriers` needs no `surgepy` build at all: it is a payload hash of
the four `.fxp` files against the census blob SHA-1s, which is exactly what
turns today's `blob_verified: false` into a real verification.

**Stale tool path corrected.** #70's "Fixtures and oracle" section names
`tools/render_fixture.py`, and this file repeated it under "Backfill". **That
path does not exist in this repository** — the SXT-012 harness is
`fixtures/render_fixture.py`, and the closest sibling for this leaf is
`fixtures/render_mw_fixture.py` (SXT-035). An oracle host following the prose
would have chased a missing file. The resolution table is now computed against
the tree on every run (`named_tool_resolution`), with a control that a bogus
name is reported `MISSING` rather than rubber-stamped.

**Predictions are consolidated from the committed artifacts, never restated.**
`oracle-status.json` → `backfill_predictions` reads the `graphs.jsonl` sha256,
the frozen destination class, the carrier-route prediction
(`Bad News.fxp` velocity → 308, normalized depth 0.218077) and the four derived
destination extents (130.007607 / 1.0 / 192.00662 / 95.9966) plus the observed
±1 source range out of `carrier-route-audit.json` and `param-corners.json`, and
**refuses (exit 2)** if the two disagree, if either is absent, or if the corpus
pin no longer matches. A disagreement on the oracle host is a finding about the
corpus pipeline or about the cited reading of the engine — never a tuning
opportunity.

**Negative controls** (`artifacts/oracle-backfill.txt`, all seven FIRED):

* **O1** — a bare `import surgepy` accepted as proof of the pin. A stub
  `surgepy.py` on `PYTHONPATH` makes the *naive* reading (the one increments
  1–5 used) report `True`; the strict reading classifies it `UNPINNED_SURGEPY`
  with `surgepy_under_engine_dir = False`. **This control demonstrably breaks
  the check the previous five increments relied on**, which is why the probe
  records both readings side by side.
* **O2** — an empty directory as `ORACLE_SURGE_DIR`: present, but not a git
  work tree ⇒ not `AVAILABLE`.
* **O3** — a *real* git checkout at a *different* commit ⇒ `PIN_MISMATCH`,
  refused. (The control repo's HEAD is recorded as the predicate
  `head_is_pin=False`, not the hash, so the artifact is reproducible.)
* **O4** — a mutated `oracle/manifest.json` engine pin ⇒ exit 2, "engine pin
  drift".
* **O5** — a mutated and an absent prediction artifact ⇒ exit 2, "prediction
  drift" / "prediction source missing".
* **O6** — an unrun leg injected as `PASS` ⇒ `validate_legs` raises. The
  permitted vocabulary is `{NOT_RUN, RUNNABLE, BLOCKED}`; `PASS` is not in it.
* **O7** — a bogus tool name ⇒ `MISSING`, while the real table reports
  `tools/render_fixture.py` as `CORRECTED`.

`tests/test_sxt036_vel_oracle_status.py` (36 tests, no iverilog, no oracle)
pins the same properties in CI, including that dropping *any single* one of the
four gate requirements loses `AVAILABLE`, that no `PASS`-like status survives
validation, and that the committed `oracle-status.json` (as of the sixth
increment) recorded items 2 and 5 as `NOT_RUN` with every control fired.
**Superseded by the seventh increment below**: the committed
`oracle-status.json` now reflects a genuinely `AVAILABLE` gate on the host
that produced it, and the test file was updated to check internal
consistency (gate status agrees with the gated items; no leg ever reads
`PASS`) rather than pin one specific gate value, since this file is a
snapshot of whichever host last ran the tool, not a live re-probe.

### Prebuilt oracle provisioning accepted; blob-verify-carriers run (seventh increment)

**#232 closed 2026-10-02** ("Prebuilt pinned Surge oracle for dispatch
workers"): `oracle/fetch-and-build.sh --prebuilt` installs a sha256-verified
prebuilt artifact per-user under `~/.cache/gf180-surge-oracle/<pin>/`, and
that install is genuinely present on this dispatch host
(`surgepy.getVersion()` reports `1.4.HEAD.58914e59c`, matching the pin;
`.installed-sha256` equals `oracle/manifest.json`'s
`prebuilt.linux-x86_64.sha256` `d2cc702913c4...`).

**The gap.** `tools/vel_oracle_status.py`'s strict reading (sixth increment)
required a git-worktree checkout: directory present, `git rev-parse HEAD`
succeeds, HEAD equals the pin. A prebuilt install is a build OUTPUT tree
(`build-py311/`, `resources/`) with no `.git` at all, so it structurally
could never satisfy that reading — re-running the probe with the prebuilt
env vars exported still reported `UNAVAILABLE`/`UNPINNED_SURGEPY` against an
unrelated default macOS path, even though the real, correct, pin-matching
engine was one directory away and genuinely importable.

**The fix.** `classify()` now accepts a SECOND provisioning shape,
additively (the git-worktree path is unchanged and still required to work on
its own): `.installed-sha256` under the probed `ORACLE_SURGE_DIR`, present
and equal to `oracle/manifest.json`'s `prebuilt.<platform>.sha256` (platform
auto-detected, matching `fetch-and-build.sh`'s own `uname -s`/`uname -m` case
statement), AND the imported `surgepy` module file lives inside that same
directory (the existing `surgepy_under_engine_dir` check, reused unchanged).
**Fails closed, verified by live controls (O8, O9, O10), not merely asserted:**

* **O8** — a directory shaped like a prebuilt install (`.installed-sha256`
  present) whose hash disagrees with the manifest: `prebuilt_sha256_matches`
  is `False` and the gate does NOT report `AVAILABLE` via this path (it falls
  through to the unchanged git-worktree logic, which correctly reports
  `UNAVAILABLE` for a non-git directory).
* **O9** — a directory whose `.installed-sha256` DOES match the manifest but
  carries no real `surgepy` build underneath it: `prebuilt_sha256_matches` is
  `True`, `surgepy_importable` is `False`, and the gate still does NOT report
  `AVAILABLE` — a matching hash alone is insufficient; the module must
  actually import from inside the verified directory too.
* **O10** — a forged prebuilt directory: `.installed-sha256` matches the
  manifest AND a present stub `surgepy.py` sits at the conventional
  `build-py311/src/surge-python/` path. The hash, bare-import, and
  under-engine-dir checks all pass (`prebuilt_sha256_matches` `True`,
  `surgepy_importable` `True`, `surgepy_under_engine_dir` `True`) but the
  version-pin check fails (`surgepy_version_matches_pin` `False`), so the
  committed outcome is `UNAVAILABLE` (committed `oracle-status.json`
  observed: `rc=0 prebuilt_sha256_matches=True surgepy_importable=True
  under_engine_dir=True version_matches_pin=False status=UNAVAILABLE`;
  `fired: true`). It differs from O9: O9 has an ABSENT module (import
  fails), O10 has a PRESENT stub (import succeeds). The copied public hash
  is insufficient because the expected value is committed plaintext in
  `oracle/manifest.json`, so matching it shows only that the writer could
  read the manifest. A successful bare import is insufficient because any
  file at the right path imports. The version-pin check is a stronger
  consistency requirement (a stub does not report the pinned commit), not
  cryptographic authentication: a version string does not authenticate
  arbitrary hostile code, and this control claims no such thing. Source:
  `tools/vel_oracle_status.py` (control O10) and
  `tests/test_sxt036_vel_oracle_status.py::test_prebuilt_sha256_match_with_fake_module_is_refused`
  (not executed for this documentation change).

**A real environment-leakage bug, found by running the full control suite in
the now-realistic environment** (the human re-run command this leaf's own
docs point at: `PYTHONPATH=.../surge-python $ORACLE_PYTHON tools/
vel_oracle_status.py`): three controls (O1, O3, and the new O9) spawn a
subprocess that overrides `ORACLE_SURGE_DIR` but, before this increment, left
`PYTHONPATH` inherited from the invoking shell unchanged. With a real oracle
genuinely on `PYTHONPATH` at the top level, that leaked the REAL engine's
`surgepy` into every control subprocess regardless of the `ORACLE_SURGE_DIR`
override under test, masking a wrong-commit checkout (O3) or an unbuilt
directory (O9) with a real import that did not come from the directory being
tested — a false `AVAILABLE`/pass on the control itself. `_self()` now
scrubs `PYTHONPATH` before applying each control's own overrides (only O1
re-adds it, deliberately, to its stub). Re-run after the fix: **all controls FIRE**
(nine at the time of that increment; the committed set is now ten, O1-O10, with O10 added later), in exactly the environment the sixth increment could not
reach (`PYTHONPATH` exported, prebuilt env vars exported, oracle genuinely
present).

**Measured gate on this host: `AVAILABLE`** (reason: "prebuilt provisioning
(#232): `.installed-sha256` matches manifest `prebuilt.linux-x86_64.sha256`
... surgepy imports from inside it"). Acceptance items 2 and 5 move from
`NOT_RUN` to **`RUNNABLE`** — the gate is open; the legs below still had to
be run (or deferred) separately, per the emitter's own O6 guarantee that it
can never itself emit `PASS` for a leg it did not run.

**`blob-verify-carriers` run for real, PASS.** This is the leg `tools/
vel_oracle_status.py` already identified as needing the pinned checkout only
(no built `surgepy`). New tool `model/voice/blob_verify_vel_carriers.py` ->
`reports/SXT-036/artifacts/blob-verify-carriers.json`: hashes the fixture
carrier (`Basses/Attacky.fxp`) and the three carriers #70 names
(`Bad News.fxp`, `Rainy Day Dreamaway.fxp`, `House Of Chords.fxp`) against
the actual bytes inside the pinned checkout's `resources/data/` tree (not a
cross-check between two committed artifacts, which is what the pre-existing
`audit_vel_carriers.py` does) — **all four byte-identical to the census
`git_blob_sha1`, PASS 4/4**. `model/voice/attacky_vel_inputs.json`'s
`preset.blob_verified` now reads `true` (was `false`), with
`blob_verified_against` naming the artifact.

**Deliberately NOT done in this increment (scope boundary, not an oversight).**
The remaining four legs (`extract-fixture-depths`, `render-reference`,
`compare-budgets`, `reference-budget-controls`) all need a built `surgepy`,
which is now genuinely available — but `extract-fixture-depths` as specified
replaces `attacky_vel_inputs.json`'s hand-declared `fixture_routes` depths
with engine readbacks, and this leaf's existing frozen evidence
(`state-coverage.json`, `param-corners.json`, `cost-accounting.json`,
`exactness-*.json`) was all produced against TODAY's hand-declared depth
values. Replacing them naively — even with genuinely-read-back numbers —
would silently invalidate every one of those committed PASS records unless
the re-extraction is first shown to round-trip the existing values exactly
(i.e. `normalized = depth_raw / live_engine_extent` reproduces each committed
`depth_raw` within the existing readback tolerance, confirming the
corpus-derived extents in `param-corners.json` against a live
`getModDepth01` reading rather than silently changing the frozen numbers).
That verification, the dry reference renders across the three named
sequences plus the two leaf-local sequences, the model-vs-reference budget
comparison, and the two reference-budget negative controls (routing-zeroed,
source-swap) are real, oracle-dependent work with a real blast-radius risk to
already-committed evidence if done hastily — tracked by a follow-up issue (#308)
filed from #70, not attempted in this probe/gate-fix increment. Items 2 and 5
stay **`NOT_RUN`** (not estimated, not inferred) pending that follow-up; only
the gate itself and the cheapest, lowest-risk leg moved.

**Invariance held.** No change to `model/voice/run_vel_model.py`,
`voice_model.py`, or any RTL/testbench file in this increment; the baseline
run-dir sha256s, the exactness/cost/corner/state artifacts, and every
previously-committed negative-control transcript are untouched byte-for-byte
except `oracle-status.json` / `oracle-backfill.txt` (re-measured, expected to
change) and the new `blob-verify-carriers.json` / the `attacky_vel_inputs.json`
provenance fields (both intentional, both documented above).

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

Oracle gate and backfill plan (added 2026-09-30, sixth increment):

```
python3 tools/vel_oracle_status.py --artifacts reports/SXT-036/artifacts
python3 tools/vel_oracle_status.py --dry-run --json      # probe only, no write
python3 -m pytest -q tests/test_sxt036_vel_oracle_status.py   # 36 passed
```
Exit codes seen: `vel_oracle_status.py` → 0 (gate recorded, all seven controls
fired); → 2 on a manifest engine-pin drift, on a drifted or absent prediction
artifact, or on a corpus pin that no longer matches #70; → 1 if a control does
not fire. The two artifacts it writes are byte-reproducible across runs
(verified by re-running and diffing).

Prebuilt oracle provisioning accepted; blob-verify-carriers run (added
2026-10-02, seventh increment; requires the pinned checkout, EITHER
provisioning shape -- git-worktree or a sha256-verified prebuilt install,
#232):

```
export ORACLE_SURGE_DIR=~/.cache/gf180-surge-oracle/<pin>/<platform>
python3 tools/vel_oracle_status.py --artifacts reports/SXT-036/artifacts
python3 -m pytest -q tests/test_sxt036_vel_oracle_status.py   # 44 passed
python3 model/voice/blob_verify_vel_carriers.py \
    --out reports/SXT-036/artifacts/blob-verify-carriers.json
```
Exit codes seen: `vel_oracle_status.py` → 0 (gate `AVAILABLE` on this host,
all ten controls fired); `blob_verify_vel_carriers.py` → 0 (4/4 carriers
byte-identical to the census); → 2 if `ORACLE_SURGE_DIR` is absent/unset or a
carrier is missing from the checkout.

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
  oracle host. **#232 closed 2026-10-02** (prebuilt provisioning now accepted
  by the gate, seventh increment); the blocker that remains is doing the
  render/extract/compare/negative-control work itself without invalidating
  this leaf's already-committed frozen evidence, tracked by a follow-up issue (#308)
  filed from #70. The plan is frozen and machine-readable in
  `artifacts/oracle-status.json` + `artifacts/oracle-backfill.txt` (sixth
  increment, gate logic extended seventh); run
  `python3 tools/vel_oracle_status.py` to re-measure the gate (now
  `AVAILABLE` on a host with either a git-worktree checkout or a
  sha256-verified prebuilt install, #232).
  Existing scripts to reuse there: **`fixtures/render_fixture.py`** (the
  SXT-012 harness — #70's body and earlier revisions of this file named
  `tools/render_fixture.py`, **which does not exist**; corrected by the
  sixth increment's `named_tool_resolution` table and control O7),
  `fixtures/render_mw_fixture.py` as the per-leaf render pattern,
  `tools/compare_audio_reference.py`, and an extractor modelled on
  `model/voice/extract_mw_inputs.py` to replace `attacky_vel_inputs.json`
  — **follow-up issue #308 must have that extractor round-trip today's
  hand-declared `depth_raw` values exactly before replacing them**, or
  re-run every comparison artifact that embeds them
  (`state-coverage.json`, `param-corners.json`, `cost-accounting.json`,
  every `exactness-*.json`) in the same change, not silently leave them
  stale. `artifacts/carrier-route-audit.json` carries the
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
  **Already done, oracle-independent and checkout-only:**
  `model/voice/blob_verify_vel_carriers.py` (seventh increment) — the
  fixture carrier and the three named carriers are byte-identical to the
  census in the pinned checkout; do not re-do this leg, extend it only if a
  new carrier is added.
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
* **The oracle gate is a gate, not a result.** The sixth increment measures
  whether the oracle-dependent legs *could* run and freezes how to run them.
  It runs none of them. `UNAVAILABLE` is a measured fact about this host, not
  a finding about the engine; `RUNNABLE` on an oracle host would still not be
  a pass of anything, and the emitter cannot express `PASS` for a leg it did
  not run (control O6). The strict gate is also **necessary, not sufficient**:
  it checks the checkout's HEAD against the SXT-010 commit, but it does not
  verify submodule SHAs, build flags, or the pinned interpreter — those stay
  `oracle/fetch-and-build.sh`'s job, and a probe that says `AVAILABLE` has not
  revalidated them.
* **The prediction set is not exhaustive.** `backfill_predictions` consolidates
  only what previous increments already derived and committed (one carrier
  route, four destination extents, the source range, the corpus pin). It is
  what the oracle host can *falsify cheaply*, not a complete specification of
  what items 2 and 5 require.
* Also recorded, not reconciled: the SXT-016 probe divergence (see costs).
