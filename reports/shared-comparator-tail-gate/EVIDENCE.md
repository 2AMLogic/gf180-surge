# Shared-comparator wet-path tail gate — evidence record

Issue: #93 (SXT-028c follow-up) · Parent: #21 (SXT-028 expansion) · Follows the
SXT-028c judge review (PR #91) and the SXT-040 review (PR #92) · Date:
2026-09-25

Tool under change: `tools/compare_audio_reference.py` (the **shared** audio
comparator used by the dry voice/oscillator leaf lines).
Checks runner: `tools/tail_gate_checks.py`. Tests: `tests/test_tail_gate.py`.

**Claim discipline.** This record establishes exactly one thing: *the shared
comparator now refuses to grade a wet-path comparison without a declared tail
region, and its wet verdict requires tail-pass as well as budget-pass.* It is a
**tooling/verification-mechanism** record.

It establishes **no** model-vs-reference fidelity result (the control "model"
renders below are derived from the reference render itself), **no** RTL-vs-model
claim, **no** preset-support or coverage claim, **no** musical-quality claim (no
human listening), and it **freezes no budget** — the tail budget added here is
a `[PROPOSED-TO-BE-FROZEN-AT-PILOT]` placeholder in the same sense as the
existing three.

## Headline results

| Claim | Status | Evidence |
|---|---|---|
| Wet verdict requires budget-pass **and** tail-pass | **PASS** (8/8 controls behaved as required) | `artifacts/negative-controls.txt`, `artifacts/tailgate-*.json` |
| Drop-tail control FAILS the verdict (2 presets) | **CONTROL-OK** | `artifacts/tailgate-drop-full-tail.json`, `…-second-preset.json` |
| Gate is load-bearing (budgets pass, gate alone fails) | **CONTROL-OK** (2 controls) | `artifacts/tailgate-tail-decays-too-fast.json`, `…-truncate-at-tail-start.json` |
| Wet comparison without a declared tail region is refused | **CONTROL-OK** (3 refusals, exit 2 / NO_VERDICT) | `artifacts/tailgate-undeclared-wet-path.json`, `…-no-sidecar.json`, `…-stale-sidecar.json` |
| Dry cases unchanged (no silent re-grade) | **PASS** (36/36 byte-identical vs the pre-change tool) | `artifacts/rerun-dry-cases.txt` |
| pytest regression guard | **PASS** (17 cases) | `tests/test_tail_gate.py` |
| Any fidelity / support / quality claim | **none made** | this section |

## 1. What changed in the comparator

1. **`--path {dry,wet}`** (default `dry`). `dry` is byte-for-byte the pre-#93
   behaviour: no gate, no new JSON keys.
2. **`--sidecar <fixture>.json`** — the *declared* tail region for a wet
   comparison, auto-discovered next to the reference when it follows the
   committed `<seq>-wet.wav` → `<seq>.json` convention.
3. **Declared tail region, never silence-inferred:**
   `[last_event_sample, last_event_sample + tail_s * sample_rate)` read from the
   sidecar. Both committed sidecar shapes are accepted: the SXT-012 fixture
   shape (`fixtures/audio/<preset>/<seq>.json`: per-bus `frames`,
   `last_event_sample`, `tail_s`, `engine.sample_rate`) and the effect-slice
   shape (`reports/*/fixtures/*.json`: `render.frames`, `render.tail_s`,
   `render.sample_rate`, region then taken as `frames - tail`). If neither
   shape declares the extent, the tool **refuses** (below) instead of guessing.
4. **`tail_check` in the JSON**, shape-compatible with the chorus tool
   (`tail_present`, `tail_rms_rel_db`, `ok`) plus the provenance and model-side
   legs that tool lacks: `tail_offset`, `tail_frames`, `tail_region_source`,
   `tail_region_sidecar`, `tail_region_covered`, `model_tail_present`,
   `tail_max_abs_diff_lsb`, `tail_rms_diff_lsb`, `tail_ref_rms_lsb`,
   `tail_model_rms_lsb`, `tail_budget`, `reason`.
5. **Wet verdict = budget-pass AND tail-pass.** Tail-pass requires: region
   fully covered by both renders; reference tail carries energy; model tail
   carries energy; and tail residual RMS ≥ 20 dB below the reference tail RMS.
6. **Fail-closed refusals** (exit 2, `verdict: "NO_VERDICT (refused)"`, nothing
   graded): a reference/model filename that declares a wet bus while `--path
   wet` was not passed; `--path wet` with no usable sidecar; a sidecar whose
   declared `frames`/`sha256` do not describe the reference render; `--path
   wet` against a `-dry`-named reference.
7. **Exit status**: 0 = PASS or any dry verdict (unchanged for every existing
   caller), 1 = wet FAIL, 2 = refusal.

### 1.1 Proposed tail budget (NOT frozen)

```
PROPOSED_TAIL = {"tail_rms_rel_db": -20.0}
```

The criterion is **relative to the reference tail RMS** deliberately: a
full-scale criterion goes vacuous as a tail decays, which is exactly the
loophole a dropped or stubbed tail passes through. −20 dB means "the tail is
reproduced to within 10 % RMS". The value has **never been exercised against a
real model wet render** — no model wet render exists through this comparator
yet (SXT-028c's wet slice is graded by `tools/compare_chorus_reference.py` on
stereo float32 buses) — so it is a proposal only, recorded in
`contracts/fidelity-policy-DRAFT.md` §2.5 as a placeholder and gated on the
SXT-017 (#12) freeze like every other budget.

## 2. Negative controls (live; each fails the check it targets)

Run: `python3 tools/tail_gate_checks.py` → `artifacts/negative-controls.txt`
(full transcript with every number), `artifacts/tailgate-<control>.json` (the
comparator's own output per control), `artifacts/checks-summary.json`.

Control fixtures (committed SXT-012 mono int16 wet buses, both with declared
region `[153600, 273600)` = `last_event_sample 153600 + tail_s 2.5 × 48000`):

* **A** `fixtures/audio/koala2/seq-notes-coverage-v1-wet.wav`
* **B** `fixtures/audio/behemoth/seq-notes-coverage-v1-wet.wav`

**Claim-scope note:** every control "model" is constructed FROM the reference
render, so the PASS control is a comparator self-test — not a model-vs-reference
result.

| Control | Construction | Required | Observed |
|---|---|---|---|
| `full-tail-within-budget` | A + deterministic ±1 LSB inside the first half of the declared tail | PASS | **PASS** (max 1 LSB, rms −98.66 dBFS, corr 0.9997, tail residual −50.27 dB) |
| `drop-full-tail` | A with the declared tail region zeroed | FAIL | **FAIL** (`model_tail_present=false`, tail residual 0.00 dB; budgets also fail: max 3831 LSB, corr 0.9115) |
| `tail-decays-too-fast` | A with an extra exp decay (τ = 0.4 s) inside the tail | FAIL | **FAIL** — *all three global budgets PASS* (max 415 LSB, rms −58.61 dBFS, corr 0.9896); tail residual −10.22 dB > −20 dB |
| `truncate-at-tail-start` | A's model render ends at the tail offset | FAIL | **FAIL** — *all three global budgets pass vacuously* (compared window bit-exact); `tail_region_covered=false` |
| `undeclared-wet-path` | wet reference graded with the default dry path | REFUSE | **NO_VERDICT, exit 2** |
| `no-sidecar` | `--path wet`, reference with no sidecar beside it | REFUSE | **NO_VERDICT, exit 2** |
| `stale-sidecar` | sidecar declares 273600 frames, reference holds 213600 | REFUSE | **NO_VERDICT, exit 2** (STALE) |
| `drop-full-tail-second-preset` | B with the declared tail region zeroed | FAIL | **FAIL** (`model_tail_present=false`, tail residual 0.00 dB) |

The two middle rows are the decisive ones: **the verdict flips to FAIL while
every pre-existing budget still passes**, so the gate — not the budgets — is
doing the work. `truncate-at-tail-start` is the exact loophole named in
`contracts/fidelity-policy-DRAFT.md` §5 rule 4 ("must fail §2.5 decay, not pass
by truncated-window comparison"): before this change the comparator truncated
both renders to the shorter length and reported a perfect match.

The runner asserts these outcomes and exits non-zero if any control stops
failing what it targets; `tests/test_tail_gate.py` re-checks the committed
summary, so a stale record fails rather than passing.

## 3. Dry re-run parity (no silent re-grade)

Leg 1 of the runner re-runs **every committed dry comparison case whose
reference and model renders are both committed** (36 cases across SXT-033,
SXT-034, SXT-040, sxt-022, sxt-026, sxt-032, sxt-035) with two tools: the
pre-change comparator materialized from `origin/main` (`git show`) and the
working-tree comparator.

* **36/36 byte-identical** stdout, JSON, and exit status → the tail gate
  changes no dry grading and adds no dry field.
  (`artifacts/rerun-dry-cases.txt`, `artifacts/checks-summary.json`.)
* Supplementary comparison against the *committed* per-case JSONs (20 of the 36
  cases have one): 20 differ, and the runner **attributes each differing key**:
  `ULP(spectral_corr)` (last-ULP float/BLAS ordering on this host — the same
  measurement) and `RMS-FLAG-#95(…)` (the pre-2026-09-24 inverted
  `rms_diff_dbfs` flag, and the verdict that followed from it).
  **Unexplained committed differences: 0.**
* This change does **not** rewrite any other leaf's committed artifact. The
  rms-flag lineage remains the business of issue #95; no number in any record
  above rests on those historical flags.
* Two cases are **NOT_RUN** for lack of a committed counterpart render
  (`reports/sxt-026/artifacts/kick-original__seq-wt-base-v1-ref.wav`,
  `reports/sxt-026a/artifacts/model-smoke-bells-dry.wav`), and the stereo
  float32 effect-slice comparisons (SXT-028c, sxt-023, sxt-026a wet) are
  NOT_RUN here because they are graded by their own tools, not this one. A leg
  that did not run is not a pass.

## 4. pytest regression guard

`tests/test_tail_gate.py` — 17 cases, 6.1 s, no oracle and no iverilog needed:

* the declared region is taken from metadata (`last_event_sample` + `tail_s`),
  and a long silent stretch inside the *body* does not move it;
* **a silent-tail waveform FAILS where a full-tail waveform PASSES** (the
  guard the issue asks for);
* a truncated model render fails while all global budgets pass;
* the relative tail residual budget catches a present-but-too-fast tail;
* dry comparisons emit no `tail_check` / `path` / `proposed_tail_budget` keys,
  and `--path dry` is byte-identical to omitting the flag;
* all four refusal paths (undeclared wet bus, missing sidecar, stale sidecar,
  sha256 mismatch) return exit 2 / NO_VERDICT;
* the committed wet fixture's own sidecar arithmetic is self-consistent
  (`last_event_sample + tail_s*sr == frames == wav frames`);
* the committed control record is re-asserted (stale evidence fails).

Run: `python3 -m pytest tests/test_tail_gate.py -q` → `17 passed`.

## 5. Scope, and what remains unproved

* **Covered:** the shared mono-int16 comparator. Its wet path is now gated and
  cannot be entered accidentally (the wet-filename tripwire refuses).
* **Not covered (unchanged, by design):** `tools/compare_chorus_reference.py`
  keeps its own (weaker) `tail_check` — it gates on reference-tail presence
  only. Bringing the stereo float32 effect-slice comparators onto this stronger
  gate (model-side presence + relative residual + covered-region check) is
  follow-up work, filed separately; SXT-028c's committed verdicts are **not**
  re-graded here.
* **No wet case is graded yet.** The tail gate has never met a real model wet
  render through this comparator, so the `-20.0 dB` value is unexercised
  against model output. First real use is the first wet leaf to render through
  this tool; expect the budget to be re-argued there, in public, not silently.
* **Stop/escalate clause (issue #93) was not triggered:** the tail region is
  fully derivable from committed fixture data (`last_event_sample` + `tail_s`,
  and `last_event_sample + tail_s*sr == frames` holds exactly for all 30
  committed SXT-012 wet fixtures), so the gate did not have to stay
  chorus-only. Sidecars that do *not* declare the extent are refused, not
  guessed.
* **Known cosmetic artifact:** `tailgate-truncate-at-tail-start.json` (and any
  bit-exact comparison) records `rms_diff_dbfs: -Infinity`, which Python's
  `json` reads back but strict JSON parsers reject. That is a pre-existing
  property of the metric under exact agreement; it was **not** "fixed" here
  because clamping it would change the dry metric definition, which §3's
  byte-identity claim forbids. Routed to the follow-up issue with the
  `spectral_corr` silent-frame sensitivity observed while building the controls
  (±1 LSB dither in silent frames can drop `spectral_corr` to ~0.93).

## 6. Reproduction

```bash
python3 tools/tail_gate_checks.py                 # both legs; exits non-zero on any miss
python3 tools/tail_gate_checks.py --legs 2        # controls only
python3 -m pytest tests/test_tail_gate.py -q      # 17 regression cases
```

Scratch renders are written under `/tmp/sxt-tail-gate-checks/` and are never
committed; the committed evidence is the transcripts, the per-control
comparator JSONs, and `checks-summary.json`.
