# Per-leaf `spectral_corr` copies: migrate or rename (issue #165)

**Parent:** #12 (SXT-017 pilot freeze) · **Depends on:** #110 / PR #166 (merged
2026-09-30) · **Routes out to:** #270

## 0. Claim scope — read this before any number below

This record establishes **one thing**: that nothing in this repository grades a
metric *named* `spectral_corr` against the frozen 0.98 budget using a
definition other than the frozen one, and that the change which achieved that
moved no verdict it was not entitled to move.

It establishes **nothing** about:

- model-vs-pinned-Surge fidelity (every budget named here is
  `[PROPOSED-TO-BE-FROZEN-AT-PILOT]`, gated on SXT-017 / #12),
- RTL-vs-frozen-model exactness,
- preset support, effect completeness, or sound quality.

Every verdict quoted below is the **leaf's own**, carried or re-derived; this
record creates no new verdict. No budget value is chosen, tuned, or frozen
here — the issue's stop condition forbids it, and leg 3 fails if any declared
budget value moved.

## 1. Outcome

| Verdict | Status |
|---|---|
| No tool grades anything called `spectral_corr` against the frozen budget with a definition other than the frozen one | **PASS** (leg 1) |
| Every verdict flip is named | **PASS** — 0 overall verdict/control-ok flips; 2 *spectral-leg* flips, both named in §4 (leg 3) |
| The L2 rename moved no measured value | **PASS** (leg 4: 27 artifacts, every diff RENAME-#165 or DEFINITION) |
| Six committed sxt-028a / SXT-028e-sse records left pre-#110 | **STALE**, routed to #270 (§6) — not reported as a pass |

Reproduce:

```sh
python3 tools/spectral_corr_per_leaf_checks.py --legs 1,2,3,4,5,6
python3 tools/regrade_spectral_corr.py \
    --out-dir reports/spectral-corr-per-leaf-migration/artifacts
python3 -m pytest tests/test_spectral_corr_single_definition.py
```

Artifacts: `artifacts/single-definition-scan.*`, `migrated-rerun.*`,
`migration-flips.*`, `l2-rename.*`, `l2-producer-rerun.*`,
`rename-idempotency.*`, `checks-summary.json`, `regrade-ledger.*`.

## 2. The six sites, and the decision recorded per site

`git grep -n "def spectral_corr"` on `origin/main` @ `b71edf4` returned ten
definitions: the shared one plus its retired-but-kept
`spectral_corr_legacy_log1p` in `tools/compare_audio_reference.py`, the two
delegating wrappers #110 already migrated (`compare_chorus_reference.py`,
`compare_fx_reference.py`), and **six** per-leaf native-unit copies. That
matches the issue's hand-written enumeration exactly. Two findings about the
enumeration itself are in §7.

### MIGRATED — same 0.98 effect-slice budget family

A tool that grades the *same nominal budget* must not grade it with a
different measurement. All three migrated to
`compare_audio_reference.spectral_corr(..., full_scale=<this bus's FS>)`.

| # | Site | Leaf | Declared full scale | Reason |
|---|---|---|---|---|
| 1 | `tools/compare_aw49_reference.py` | SXT-028a | `FULL_SCALE_F32` = 1.0 (engine float32 Airwindows bus) | grades `spectral_corr >= 0.98`, the same family #110 migrated |
| 2 | `tools/distortion_negative_controls.py` | SXT-028e **and SXT-028e-sse** | `FULL_SCALE_LSB` = 2^20 (Q10.21) | same; `distortion_sse_negative_controls.py` loads this module and reuses its `metrics`/`spectral_corr`, so one migration covers both leaves — confirmed: neither the SSE control script nor either distortion model defines a second copy |
| 3 | `tools/reverb2_negative_controls.py` | SXT-028f | `FULL_SCALE` = 2^21 (Q10.21) | same |

The retired copy was `log1p(|X|)` in the caller's **native unit**, so its log
knee sat at full scale on a float bus and at one LSB on an integer bus: the
same name and the same 0.98 budget meant two measurements about 50 dB apart.
Leg 1 shows this directly. On an input pair whose residual is the *same
fraction of full scale* on every bus, the **shared** definition scores
0.99964 (aw-49, float32), 0.99976 (distortion, Q10.21) and 0.99960 (reverb2,
Q10.21) — i.e. the same answer on all three, which is the point. The
**retired** definition scores 0.99997 on the float32 bus but 0.5563 and 0.5345
on the two integer buses: under the old name, an identical relative residual
was graded as a comfortable pass on one bus and a gross failure on another.

Two declared changes ride along on site 2 and are **not** hidden:

- **Frame 1024 -> the shared 4096.** Over the 6144-sample control render that
  is one graded frame instead of six. Its measured effect on every control is
  the BASE -> NOW column in §4.
- **`verdict()` now fails closed on a non-finite spectral leg.** The pre-#165
  code returned `nan` when numpy was absent and `verdict()` treated `nan` as
  "ignore" — a leg that never ran counted as a pass, which `AGENTS.md`
  forbids outright. numpy is a hard requirement of the shared definition, and
  `tests/test_spectral_corr_single_definition.py
  ::test_distortion_controls_fail_closed_on_a_non_finite_spectral_leg` is the
  live control for the new behaviour.

### RENAMED — a different metric against a different budget family

| # | Site | Leaf |
|---|---|---|
| 4 | `tools/compare_lpmoog_model.py` | SXT-039 |
| 5 | `model/voice/filter_lp12/run_filter_leg.py` | SXT-037 |
| 6 | `model/voice/filter_lp24/run_filter_leg.py` | SXT-038 |

`spectral_corr` -> **`l2_spectral_corr`**, budget key -> `l2_spectral_corr_min`,
each producer carrying an explicit `L2_SPECTRAL_CORR_DEFINITION` stamp that
says in words *"NOT compare_audio_reference.spectral_corr"*. The computation
is unchanged.

**Why renamed and not migrated** — and specifically why this is not the
stop-condition dodge the issue warns about:

1. The 0.999 floor was proposed **against this definition**, in Q10.21 LSB, on
   a filter stage's own output — not against the 0.98 effect-slice budget the
   shared definition serves. They are different budget families, not two
   spellings of one.
2. SXT-037 has **already recorded this sub-budget as mis-scaled** for
   filtered-voice spectra (`reports/sxt-037/EVIDENCE.md` §3): the L2b
   attribution legs hold kernel error at −76…−98 dB while scoring 0.95–0.99.
   SXT-039 records the same shape (`reports/SXT-039/EVIDENCE.md`, finding
   F-039-1: 9 of 11 rows miss `corr >= 0.999` while their L2 max/rms pass).
   Re-grading a budget that is already recorded as mis-scaled, under a new
   definition, while leaving the floor at 0.999, would change *what is
   measured* without touching *the proposal it is measured against*.
3. Choosing a different floor for this family here is exactly what the
   issue's stop condition forbids. **The L2 family's metric and its floor are
   the SXT-013 / #12 freeze's decision, not this issue's.**

So the rename removes the name collision — the whole acceptance criterion —
**without** silently re-grading a second budget family. What it does not do is
resolve whether 0.999-on-native-log1p is the right L2 proposal; that remains
open against #12 and is untouched by this record.

## 3. Reproduction of the migrated records (leg 2)

Both migrated producers were re-run on this host and must reproduce their
committed artifact exactly, modulo run metadata:

| Artifact | Producer | Reproduces |
|---|---|---|
| `reports/SXT-028e/negative-controls/negative-controls.json` | `tools/distortion_negative_controls.py` | **yes** |
| `reports/SXT-028f/negative-controls/negative-controls.json` | `tools/reverb2_negative_controls.py` | **yes** |

A producer that cannot run here is recorded NOT_RUN and **fails** the leg; it
is never reported as a pass.

## 4. Every value change, and every flip (leg 3)

The floor each row is graded against is **read from the record** under the key
that leaf's own producer declares (`proposed` / `proposed_budgets`); this
record supplies no floor. `spectral_corr_min` = **0.98 at the base and 0.98
now** in both records — leg 3 fails if a declared budget value moves.

### `reports/SXT-028e/negative-controls/negative-controls.json`

| Block | control | BASE | NOW | spectral leg |
|---|---|---|---|---|
| `/controls[0]/metrics` | NC-0 baseline-sanity | 1.000000 | 1.000000 | pass -> pass |
| `/controls[1]/metrics` | NC-A generic-substitute | 0.854046 | 0.740722 | fail -> fail |
| `/controls[2]/metrics` | NC-C wrong-order | 0.973332 | 0.987404 | **fail -> pass (FLIP)** |
| `/controls[3]/benign_stimulus_leg/metrics` | NC-F benign leg | 0.999901 | 0.999292 | pass -> pass |
| `/controls[3]/metrics` | NC-F halfband-phase | 0.982879 | 0.975438 | **pass -> fail (FLIP)** |
| `/controls[4]/metrics/a` | NC-D shared-state (a) | 0.959869 | 0.955069 | fail -> fail |
| `/controls[4]/metrics/b` | NC-D shared-state (b) | 0.898024 | 0.891233 | fail -> fail |

### `reports/SXT-028f/negative-controls/negative-controls.json`

| Block | BASE | NOW | spectral leg |
|---|---|---|---|
| `/baseline_self_agreement` | 1.000000 | 1.000000 | pass -> pass |
| `/controls[0]/metrics` | 0.608120 | 0.604250 | fail -> fail |
| `/controls[2]/metrics` | 0.975943 | 0.977083 | fail -> fail |

**Overall verdict / control-ok statuses moved: 0, in both records.** Every
negative control that was CONTROL-OK is still CONTROL-OK; NC-0 is still PASS;
the ledger reports **0 VERDICT flips** repo-wide.

### The two spectral-leg flips, named

Both are in SXT-028e, both are *sub-leg* flips inside a control whose overall
verdict is unchanged (`FAIL`, which for a negative control is CONTROL-OK):

- **NC-F `halfband-phase`, spectral leg pass -> fail.** A **strengthening**: the
  shared definition detects the swapped halfband polyphase branches
  spectrally, where the native-unit copy did not. NC-F was already detected by
  its max/rms legs, so its CONTROL-OK status does not depend on this.
- **NC-C `wrong-order`, spectral leg fail -> pass.** A **bounded weakening,
  recorded not papered over**: the shared definition no longer flags the
  pre-EQ/post-EQ swap spectrally. NC-C remains detected — verdict `FAIL`,
  CONTROL-OK — on `max_abs_diff_lsb` (247 051 LSB vs a 8 192 budget) and
  `rms_diff_dbfs` (−18.91 dBFS vs −46), i.e. by two legs that fail by three
  and one-and-a-half orders of magnitude respectively. So the control still
  demonstrably fails the check it targets, but **its spectral leg no longer
  contributes resolving power for this mutant class.**

  The tempting fix — nudge the floor for this tool so NC-C's spectral leg
  keeps failing — is precisely the issue's stop condition, and it is not done.
  Whether 0.98-on-the-shared-definition is the right effect-slice floor is
  SXT-013 / #12's call; this finding is input to that freeze, recorded here
  and nowhere resolved.

## 5. The L2 rename moved no measurement (legs 4 and 5)

**Leg 4 — value preservation, mechanical.** Every difference this branch makes
to an SXT-037 / SXT-038 / SXT-039 artifact, 27 files including the three
gzipped SXT-037 traces, classifies as `RENAME-#165` or `DEFINITION` under
`tools/regrade_spectral_corr.py`. `RENAME-#165` only classifies when the
counterpart under the *other* name carries the **same** value, so a moved
value cannot hide in the class — it falls through and fails the leg. That the
class cannot launder a moved value is itself pinned by a live control
(`::test_the_ledger_rename_class_cannot_launder_a_moved_value`).

`tools/rename_l2_spectral_corr_key.py` performed the artifact-side rename
in-position, value untouched, in the producer's own formatting. It is
idempotent and `--check`-clean over all 27 declared targets (leg 6).

**Leg 5 — the renamed producers emit the renamed key.** Coverage reported
separately from agreement:

| Leaf | Re-run | NOT_RUN | Worst relative difference |
|---|---|---|---|
| SXT-039 (`compare_lpmoog_model.py` over re-run lpmoog legs) | 11 / 11 cases | 0 | 1.15e-12 (host float ordering) |
| SXT-038 (`filter_lp24/run_filter_leg.py`) | 4 / 11 bundles | 7 | 4.1e-07 — the committed value is rounded to 6 dp by `compare_lp24_model.py` |
| SXT-037 (`filter_lp12/run_filter_leg.py`) | 3 / 3 traces (6 instance values) | 0 | 5 of 6 bit-identical; worst 2.4e-13 |

The 7 SXT-038 bundles that hold `meta.json` only need the external
pinned-filter harness and are **NOT_RUN**, not a pass.

## 6. Left pre-#110, with a reason (STALE, routed to #270)

Seven committed records still carry pre-#110 values under the now-migrated
tools. They are **STALE**, listed in the ledger with a reason, and **not**
re-graded here:

- **`reports/sxt-028a/artifacts/compare-*.json` (6).** Two independent
  reasons, both verified: (a) five of the six cases have no committed
  `-aw49-taps.npz` (only `temple__seq-notes-coverage-v1` does), so they cannot
  run without the DR-0006 oracle renders; (b) **all six, including the
  runnable one**, carry `model_frozen_revision` `1901510e…` while the
  committed model's `frozen_revision()` is `569bff13…` (the
  `docs/byte-frozen-sources.json` pin for `model/effects/aw-49/
  galactic_model.py`). Re-emitting even the runnable case would therefore
  republish a **model-revision** change that is not #165's. The leaf must be
  republished as one set on the oracle host.
  *This second reason is a finding in its own right* — those `compare-*.json`
  are not in the registry's `recorded_in` list, so nothing currently detects
  their stale revision word. See §7.
- **`reports/SXT-028e-sse/negative-controls/negative-controls.json` (1).** The
  SSE controls reuse `distortion_negative_controls.metrics`, so the tool is
  migrated, but this record's metric fields are exact only under the glibc
  environment it declares (#243). Regenerating it on a different libm would
  republish 43 non-spectral max/rms fields, which is not #165's change.

Also in the ledger's not-regenerated list, and **not** this issue's:

- **100 `UNTOUCHED`** records. The ledger's base is `origin/main` @ `b71edf4`,
  which already contains #110/PR #166, so these are records main already
  regenerated under the shared definition; this branch changes none of them.
  73 of the 100 carry the shared `spectral_corr_definition` stamp. The other
  **27 carry no stamp at all** — a pre-existing property of #110's own records
  that this branch neither causes nor changes (see §7).
- **4 `STALE`** and **3 `HISTORICAL`** rows carried from #110's own record
  (`reports/spectral-corr-fs-floor/EVIDENCE.md` §4), unchanged.

The ledger text retains its `Issue #110 regrade ledger` header because
`tools/regrade_spectral_corr.py` is #110's tool, run here against this
branch's base; the base revision it attributes against is printed in the
header and in `regrade-ledger.json`.

## 7. Findings (bounded, each routed, none resolved here)

- **F-165-1 — NC-C's spectral leg lost resolving power for the wrong-order
  mutant.** §4. Input to SXT-013 / #12; no floor changed.
- **F-165-2 — the #110 ledger's own scan could not see a `spectral_corr`
  *object*.** `has_spectral_value()` tested only the **last** path component,
  so the eleven SXT-038 records — which nest the value in a `spectral_corr`
  object `{achieved, budget, pass, gating}` — were invisible to it, which is
  why `reports/spectral-corr-fs-floor/artifacts/regrade-ledger.txt` has zero
  SXT-038 rows while `reports/SXT-038/artifacts/compare-brass.json` was
  carrying a `spectral_corr` graded against 0.999. Fixed in this change and
  pinned by a live control
  (`::test_the_ledger_sees_a_spectral_corr_object_not_only_a_leaf`). A
  budget-only record still does not match, so the `BUDGET-ONLY` rows are
  unaffected. **Corollary: do not treat that ledger as a complete inventory of
  NOT-MIGRATED sites.** SXT-038 also declared its budget as
  `spectral_corr_min` where its siblings used `l2_spectral_corr_min`; both
  are now `l2_spectral_corr_min`, pinned by a test.
- **F-165-3 — the sxt-028a `compare-*.json` records carry a stale
  `model_frozen_revision` and nothing detects it.** §6. They are not in
  `docs/byte-frozen-sources.json`'s `recorded_in` list for
  `model/effects/aw-49/galactic_model.py`, whose freshness gate therefore does
  not reach them. Routed to **#270** with the re-grade.
- **F-165-4 — 27 of main's #110-era records carry a measured `spectral_corr`
  with no `spectral_corr_definition` stamp.** Pre-existing, unchanged by this
  branch, listed in `artifacts/regrade-ledger.txt`. A reader cannot tell which
  definition produced those values from the record alone. Not in scope here;
  recorded so it is not mistaken for a #165 regression.
- **F-165-5 — three `run_filter_leg.py` modules share one module name.**
  `model/voice/filter_lp12`, `filter_lp24` and `filter_lpmoog` each hold a
  different `run_filter_leg.py`. A bare `import run_filter_leg` after a
  `sys.path` insert resolves to whichever one `sys.modules` already holds, and
  during this work a guard test silently asserted against `filter_lpmoog`'s
  file — which has **no** spectral metric at all — instead of the file under
  test. The test now loads all three by explicit path and pins that
  `filter_lpmoog/run_filter_leg.py` defines neither name.

## 8. Live negative controls

Each check carries a control that demonstrably fails the condition it targets
(`tests/test_spectral_corr_single_definition.py`, 16 tests):

| Control | Targets |
|---|---|
| `::test_the_scan_detects_a_reintroduced_per_leaf_copy` | a per-leaf native-unit `log1p` copy re-introduced under the frozen name is reported; a delegating wrapper of the same name is not a false positive |
| leg 1 `differs-from-retired` column | a tool that silently reverted to its per-leaf copy would show a materially different number (0.556 vs 0.9998 on Q10.21) and fail |
| `::test_distortion_controls_fail_closed_on_a_non_finite_spectral_leg` | a spectral leg that did not run being graded as a pass |
| `::test_the_ledger_rename_class_cannot_launder_a_moved_value` | `RENAME-#165` absorbing a changed value instead of a changed name |
| `::test_the_ledger_rename_class_runs_before_the_verdict_class` | the nested `spectral_corr.pass` of the SXT-038 records being reported as a status flip |
| `::test_the_ledger_sees_a_spectral_corr_object_not_only_a_leaf` | the F-165-2 blind spot, with a budget-only record as the negative side |
| `::test_migrated_records_carry_the_definition_stamp` | a migrated value published without saying which definition produced it |
| leg 3's budget-value assertion | a floor quietly moved to preserve a verdict (the issue's stop condition) |
