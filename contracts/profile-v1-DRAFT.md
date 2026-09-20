# Product profile v1 — DRAFT bundle comparison + predictions (NOT FROZEN)

Issue: #12 (SXT-017, **bundle stage only**) · Plan:
`docs/surge-xt-chip-plan-v0.1-2026-09-20.md` §2, §3, §5, §6 ·
Spec: [`profile-v1-bundle-DRAFT.json`](profile-v1-bundle-DRAFT.json) ·
Predictor: `tools/profile_predict.py` · Predictions:
`reports/sxt-017/predictions/`

## NOT FROZEN — pending SXT-013 listening, SXT-014 labels, SXT-016 numbers

**Nothing in this document is a frozen product profile, a support claim, a
fidelity claim, a preset-quality claim, or a hardware claim.** Freezing
requires, per issue #12's premise and plan §6:

1. **SXT-013** (#8): a human listening selection of the favorites set and a
   frozen fidelity policy. Only proposal slates exist
   (`reports/sxt-013/candidates/`); **essentiality of every preset is
   UNVERIFIED**. BLOCKED on human listening.
2. **SXT-014** (#9): listening labels (essential / optional-by-adaptation /
   unresolved) for effect contribution. Only numeric ablation deltas exist
   (`reports/sxt-014/`); labels are BLOCKED on human listening.
3. **SXT-016** (#11): measured cost probes. **`reports/sxt-016/` does not
   exist yet**; every cycle number below is SXT-015's `placeholder-v0` cost
   profile and every such cell is marked **[PENDING-SXT-016]**.

This document implements only the *bundle stage* of SXT-017: a versioned
candidate-bundle comparison, per-preset predictions, and a selected DRAFT
bundle with explicit contract-revision triggers.

Claim discipline (AGENTS.md): "supported" below means only **"the original
normalized patch graph fits this DRAFT bundle's declared structural
gates/budgets"**. It is not a fit claim on cycles (no measured clock basis —
[PENDING-SXT-016]), not a fidelity outcome, and not a listening outcome. The
three claims (RTL≡model, model≈reference, sounds good) are never inferred
from one another here.

---

## 1. Method

`tools/profile_predict.py` evaluates every one of the 3,561 SXT-011
normalized graphs (641 factory + 2,920 contributor) against a bundle spec
and emits exactly one predicted status per entry:

| Predicted status | Meaning | Counts as supported? |
|---|---|---|
| `supported` | all gates pass on the original graph | yes |
| `adapted-not-predicted` | runs only with a disclosed edit class (unison or polylimit reduction, per plan §2/fidelity-policy §1) | **never** |
| `unsupported` | a required feature/resource is outside the bundle (machine-readable reason) | no |
| `unresolved` | not evaluable today (loader failure, or MSEG/Formula LFO contents not exposed — SXT-011 gap) | no |

Gates (bundle spec keys, all validated fail-closed): oscillator family
allowlist (by engine display name, active slots only), wavetable asset
support, filter type allowlist, waveshaper policy, FX class allowlist
(enabled instances; routing-inactive scene-B slots hold state but gate
nothing, matching SXT-015), Airwindows algorithm selection, FX **instance**
limit (enabled instances — two Delay slots are two instances, never merged),
scene modes, voice-pool (scene-voice polyphony) limit, unison cap, audio
input dependency, on-chip RAM / external writable capacity / external
bandwidth budgets, and declared data-gap policies. **Cycle closure is NOT a
gate** — the placeholder-v0 cost profile supports no technology claim; cycles
are published as columns marked [PENDING-SXT-016] instead.

Fail-closed controls: unknown bundle keys, unknown allowlist names, unknown
scene modes, non-pinned sample rates, and tampered slate hashes **refuse the
run** (exit 2); nothing is silently ignored or squeezed.

Reason codes (machine-readable, in every excluded preset's record):
`loader_analysis_failure`, `mseg_or_formula_contents_not_exported`,
`audio_input_dependency`, `scene_mode_not_in_bundle`,
`oscillator_family_not_in_bundle`, `wavetable_assets_not_in_bundle`,
`filter_algorithm_not_in_bundle`, `waveshaper_not_in_bundle`,
`effect_class_not_in_bundle`, `airwindows_algorithm_not_selected`,
`fx_instance_overflow`, `event_queue_overflow`, `scene_mode_unaccountable`,
`on_chip_ram_exceeded`, `external_writable_capacity_exceeded`,
`external_bandwidth_exceeded`, `polylimit_reduction_required` (adapted),
`unison_reduction_required` (adapted).

## 2. Candidate bundles

Five bundles are defined in `profile-v1-bundle-DRAFT.json` (all
`DRAFT-NOT-FROZEN`): four product-shaped candidates **B1–B4** and one
non-product reference row **R0** (the "no further feature cut" ceiling, used
only to bound the comparison). Shared constants: 48 kHz (engine pin; a rate
change requires a new census — plan §3), float32 model word width
(placeholder pending SXT-016/023 re-derivation), poly policy
`adapted_beyond_pool` (a preset whose stored polylimit exceeds the
scene-voice pool is predicted `adapted-not-predicted`: playing it with full
stored polyphony needs a disclosed polyphony reduction — the conservative
reading of plan §2's "reduced unison"-class edits), unison cap 16
(MAX_UNISON), MSEG/Formula gap → `unresolved`, SLFO definition gap →
recorded budget-risk caveat (state counted at engine constants per SXT-015;
a preset is not excluded on it — re-examine at freeze).

| Bundle | Osc families | Filter types | FX classes | Airwindows | Waveshaper | FX instances | Scene modes | Voice pool |
|---|---|---|---|---|---|---|---|---|
| **B1-core-narrow** (floor) | Classic, Sine, Wavetable | 9 core multimode/ladder types | Delay, EQ, Reverb 1 | none | none | 4 | single | 8 |
| **B2-core-wet-plan3** (plan §3 shape) | Classic, Sine, Wavetable | 9 core types | + Chorus, Conditioner | none | none | 8 | all (shared pool) | 8 |
| **B3-ext-voice-fx** | + FM2, FM3, S&H Noise | all 32 observed | + Chorus, Conditioner | none | all | 8 | all | 16 |
| **B4-broad** | + FM2, FM3, S&H Noise | all 32 observed | + Phaser, Distortion, Reverb 2 | top-12 by preset coverage (ids 49, 4, 46, 42, 24, 5, 30, 21, 35, 15, 41, 3) | all | 8 | all | 16 |
| **R0-ceiling-reference** (non-product) | all observed except Audio Input | all 32 observed | all 29 observed except Audio In | all 60 observed | all | 8 | all | 16 |

Single-dimension variants (committed, summary artifacts):
`VAR-B1-inst8`, `VAR-B2-pool16`, `VAR-B3-pool8`, `VAR-B4-inst4`,
`VAR-B4-aw-all`, `VAR-B4-fu-narrow`, `VAR-B4-uni8`.

Bundle selection is **complete-preset recovery per feature set**, never
individual feature frequency: a preset counts for a bundle only if *every*
active feature of its original graph fits the bundle at once.

## 3. Predicted coverage (all 3,561 entries; favorites slates highlighted)

Predictor output, committed per preset with reasons in
`reports/sxt-017/predictions/<bundle>.json`. Adapted presets are never
counted as supported.

### 3.1 Corpus coverage per bundle

| Bundle | Supported (factory /641) | Supported (contributor /2,920) | Adapted-not-predicted | Unsupported | Unresolved |
|---|---:|---:|---:|---:|---:|
| B1-core-narrow | 0 | 6 | 427 | 2,546 | 582 |
| B2-core-wet-plan3 | 0 | 8 | 564 | 2,407 | 582 |
| B3-ext-voice-fx | 464 | 808 | 133 | 1,574 | 582 |
| **B4-broad** | **549** | **1,136** | 164 | 1,130 | 582 |
| R0-ceiling-reference | 600 | 2,116 | 190 | 73 | 582 |

The 582 unresolved are the MSEG/Formula LFO exposure gap (SXT-011) plus the
one loader-failure class (0 in the committed export); they stay in the
denominator.

### 3.2 Favorites-slate coverage per SXT-013 quota profile

**Essentiality is UNVERIFIED**: these are *proposal* slates built by
deterministic diversity-maximization — no human listening has ranked any
preset, and the SXT-013 machine dry-run is explicitly not listening
evidence. Coverage numbers below are structural predictions, not musical
value.

| Bundle | balanced slate /256 | factory-lean /256 | contributor-lean /256 |
|---|---:|---:|---:|
| B1-core-narrow | 0 | 0 | 0 |
| B2-core-wet-plan3 | 0 | 0 | 1 |
| B3-ext-voice-fx | 53 | 98 | 53 |
| **B4-broad** | **72** | **127** | **77** |
| R0-ceiling-reference | 184 | 202 | 189 |

The 80%-goal threshold is **205/256**. **No candidate — not even the R0
ceiling — reaches it on any proposal slate.** See §6 (feasibility statement)
and §8 (revision triggers); this gap is a *finding*, not a redefinition of
"supported".

### 3.3 Cost/RAM/bandwidth columns — SXT-015 accounting, ALL [PENDING-SXT-016]

From `accounting.py` under each bundle's voice-pool override; cost profile
`placeholder-v0` (named placeholders; supports no technology claim).

| Bundle (supported set) | max on-chip state B | max ext writable state B | max ext traffic B/s | max cycles/frame (placeholder-v0) |
|---|---:|---:|---:|---:|
| B1 (n=6) | 118,272 | 4,325,376 | 8,064,000 | 9,280 |
| B2 (n=8) | 159,232 | 4,325,376 | 8,064,000 | 10,290 |
| B3 (n=1,272) | 493,056 | 35,356,672 | 19,584,000 | 166,025 |
| B4 (n=1,685) | 523,264 | 44,646,400 | 33,408,000 | 166,025 |
| R0 (n=2,716) | 697,856 | 60,358,656 | 33,408,000 | 165,085 |

Every one of these numbers inherits SXT-015's named placeholders: 480 MHz
placeholder clock, 4-byte word, 1 MiB conservative state for unverified FX
classes, 800 MB/s placeholder bandwidth budget. They are **comparative
columns, not budgets met**. Placeholder-v0 cycle closure reports OVERFLOW
for 3,477/3,561 graphs — a statement about the placeholder numbers, which is
why cycles gate nothing in this DRAFT [PENDING-SXT-016]. Declared candidate
budgets in the spec (4 MiB on-chip, 64 MiB external writable, 800 MB/s) sit
above the modeled maxima so structural gates bind first; they are candidates
pending SXT-016, not claims.

## 4. Pareto table (uncombined — no single score, plan §5)

| Bundle | Predicted supported total | balanced slate | Δ vs previous (corpus) | Added feature set vs previous | FX instances | Voice pool | Unverified-class FX state? | Notes |
|---|---:|---:|---:|---|---:|---:|---|---|
| B1 | 6 | 0 | — | (floor) | 4 | 8 | no | floor; poly-8 makes nearly everything adapted (3,212) |
| B2 | 8 | 0 | +2 | +Chorus/Conditioner, 8 inst, all scenes | 8 | 8 | no | plan §3 shape; pool 8 dominates the loss |
| B3 | 1,272 | 53 | +1,264 | +FM2/FM3/S&H, all filters, waveshapers, pool 16 | 8 | 16 | no | single biggest jump: pool 8→16 (see variants) |
| **B4** | **1,685** | **72** | **+413** | +Phaser/Distortion/Reverb 2/AW-top-12 | 8 | 16 | AW only (1 MiB placeholder/instance) | **selected DRAFT** (§5) |
| R0 | 2,716 | 184 | +1,031 | all classes + all 60 AW + Modern/Twist/Alias/String/Window | 8 | 16 | 11 classes unpinned | non-product ceiling; not credible for v1 silicon |

Variant isolations (corpus supported / balanced slate):

| Variant vs base | Supported | Balanced slate | Dimension reading |
|---|---:|---:|---|
| VAR-B2-pool16 vs B2 | 530 vs 8 | 21 vs 0 | voice pool 8→16 is the dominant voice-dimension lever |
| VAR-B3-pool8 vs B3 | 21 vs 1,272 | 0 vs 53 | (inverse) pool 16 is load-bearing for B3+ |
| VAR-B4-inst4 vs B4 | 1,645 vs 1,685 | 68 vs 72 | instance limit 8→4 costs 40 presets / 4 slate presets |
| VAR-B4-fu-narrow vs B4 | 1,336 vs 1,685 | 57 vs 72 | a 9-type filter allowlist costs 349 presets / 15 slate presets |
| VAR-B4-uni8 vs B4 | 1,550 vs 1,685 | 59 vs 72 | unison cap 8 costs 135 presets |
| VAR-B4-aw-all vs B4 | 1,685 vs 1,685 | 72 vs 72 | AW top-12 vs all-60 changes reasons on 256 presets but flips no status inside tier C — the class allowlist binds first (at R0 context AW selection binds: 2,716→2,554) |
| VAR-B1-inst8 vs B1 | 6 vs 6 | 0 vs 0 | instance dimension not binding in the B1 context (other gates dominate) |

These are comparative **predictions** under one static model; the
area/power/cycle leg of every row is [PENDING-SXT-016].

## 5. SELECTED DRAFT bundle: **B4-broad** (NOT FROZEN)

```json
{"oscillator_allowlist": ["Classic","Sine","Wavetable","FM2","FM3","S&H Noise"],
 "filter_type_allowlist": "all (32 observed types; subtypes at engine-declared set)",
 "fx_type_allowlist": ["Delay","EQ","Reverb 1","Chorus","Conditioner",
                       "Phaser","Distortion","Reverb 2"],
 "airwindows": "top-12 algorithms by preset coverage: 49,4,46,42,24,5,30,21,35,15,41,3",
 "waveshaper_policy": "all", "fx_instance_limit": 8,
 "scene_modes": "all (shared scene-voice pool)", "voice_pool_limit": 16,
 "unison_cap": 16, "poly_gate": "adapted_beyond_pool",
 "sample_rate_hz": 48000, "word_length_policy": "float32 placeholder [PENDING-SXT-016]",
 "budgets": {"on_chip_ram": "4 MiB candidate", "external_writable": "64 MiB candidate",
             "ext_bandwidth": "800 MB/s candidate", "cycle_closure": "NOT GATED [PENDING-SXT-016]"}}
```

Rationale (complete-preset recovery reasoning, not feature frequency):

1. **Predicted complete-preset recovery dominates the smaller candidates at
   bounded increments**: B4 recovers 1,685 corpus presets (549 factory) and
   72/127/77 per slate profile vs B3's 1,272/53/98/53 — the increment is
   exactly the tier-C FX set + AW selection, whose classes have pinned or
   bounded buffer structure in the SXT-015 table (Reverb 2 pinned; Phaser,
   Distortion verified no-long-buffer; Airwindows the one unverified-tier
   admission, per-instance 1 MiB conservative placeholder, external).
2. **Voice pool 16 is load-bearing**: the plan §3 "8 scene voices"
   hypothesis collapses predicted recovery (VAR-B3-pool8: 21 supported; 3,212
   presets would carry a polylimit-reduction adaptation at pool 8). B4
   therefore carries pool 16 as the working hypothesis, explicitly flagged
   as the highest-risk line item for SXT-016/021 to confirm or kill.
3. **B4 is the broadest bundle whose state structure is mostly pinned.** R0
   recovers more (2,716) but requires 11 FX classes whose buffers are not
   pinned at all (1 MiB placeholders each) plus the long-tail of 60
   Airwindows algorithms — not a credible v1 hardware scope; R0 is kept as a
   reference row only.
4. **Filters and waveshapers stay open (all observed) in the DRAFT** because
   no measured per-type cost exists to close them with ([PENDING-SXT-016]);
   the variant row shows closing them is expensive (fu-narrow: −349
   presets). The freeze decision must name the real allowlist.

**This selection is provisional three times over**: it can be overturned by
SXT-013 listening (the favorites set may not need tier C at all — or may
need classes B4 excludes), by SXT-014 labels (if Delay/EQ/Reverb 1 turn out
optional on many favorites, cheaper tiers rise), and by SXT-016 (if any
included kernel misses its budget, §8 triggers a visible revision).

## 6. The 80%-goal feasibility statement (honest)

Against the three committed proposal slates, **B4's predicted structural
coverage (72/256 balanced, 127/256 factory-lean, 77/256 contributor-lean)
and even the R0 ceiling (184/202/189) fall short of the 205/256 goal.** The
shortfall is dominated by: 582 corpus entries with unexportable
MSEG/Formula LFO contents (unresolved, SXT-011 gap), 212 presets storing
polylimit >16 (adapted at pool 16), 87 audio-input dependencies, and the
slates' deliberate diversity spread across long-tail FX classes, Airwindows
algorithms, and filter types that any bounded bundle excludes.

Two readings, kept separate:

- **What this does NOT show**: that the product goal is unreachable. The
  slates are diversity-maximized *proposals*, not listening-ranked
  favorites; essentiality is unverified (SXT-013 BLOCKED, SXT-014 labels
  BLOCKED). A human-selected favorites set concentrated in the
  structurally-supported region would score differently. Predicted
  structural coverage of a proposal slate is not a musical outcome.
- **What this DOES show**: that on the current committed proposals, no
  bundle inside (or above) B4's scope meets the 80% target, so **freezing
  profile v1 without either (a) a favorites set that fits, or (b) an
  explicit, visible revision of the goal/scope, is impossible.** Per issue
  #12's stop/escalate clause this is recorded now as a bounded finding for
  the freeze stage; the stop/escalate decision itself belongs to the product
  owner once #8/#9/#11 land. Feature cuts, if any, will be recorded here as
  contract revisions — "supported" will not be redefined.

## 7. Publishing rule

- Predictions cover **all 3,561 entries: 641 factory + 2,920 contributor**
  (one status + reasons each; byte-deterministic artifacts).
- Favorites are highlighted separately: each artifact carries per-slate
  status counts and the predicted-supported path list for each of the three
  SXT-013 quota profiles, each stamped `essentiality: UNVERIFIED`.
- `adapted-not-predicted` is reported and counted **separately, never as
  supported** (enforced by the aggregator; NC6 in
  `reports/sxt-017/negative-controls.txt`; tested in
  `tests/test_sxt017_predict.py`).

## 8. Contract-revision triggers (what would change this bundle)

1. **SXT-016 cost misses** on Reverb 2, Chorus, Phaser, Distortion, or
   per-voice waveshapers → drop the offending class(es) to a B3-class scope;
   recorded here with the newly-unsupported preset lists from a predictor
   re-run.
2. **Voice pool 16 unaffordable** (scheduler/RAM/clock evidence) → the
   pool decision flips and with it ~85% of predicted corpus coverage
   (cf. VAR-B3-pool8); this is a *product-goal-level* revision requiring the
   owner's explicit sign-off, never a silent limit change.
3. **SXT-013 favorites need a class/algorithm outside the allowlists**
   (long-tail Airwindows, Nimbus/Tape/…, MSEG curves) → extend the
   allowlist through a bundle version bump, or revise the favorites choice;
   MSEG/Formula exposure needs SXT-011 instrumentation work, not guessing.
4. **SXT-014 labels mark Delay/EQ/Reverb 1 optional on many favorites** →
   a cheaper FX tier may dominate; the Pareto table is re-run with the
   frozen favorites as the coverage basis.
5. **SXT-016 word-length/clock results** → cycle closure becomes a real
   gate (replacing `not_gated_pending_sxt_016`), budgets re-derived from
   measured kernels, and the whole comparison is re-run.
6. **Filter/waveshaper allowlist closure** must happen at freeze: "all
   observed" is a prediction stance, not a per-algorithm cost decision.

## 9. Reproduce

```sh
# full prediction for a bundle (byte-deterministic; slates optional)
python3 tools/profile_predict.py \
  --bundle contracts/profile-v1-bundle-DRAFT.json --bundle-id B4-broad \
  --slate reports/sxt-013/candidates/slate-256-balanced.json \
  --slate reports/sxt-013/candidates/slate-256-factory-lean.json \
  --slate reports/sxt-013/candidates/slate-256-contributor-lean.json \
  --out /tmp/B4.json
cmp /tmp/B4.json reports/sxt-017/predictions/B4-broad.json && echo IDENTICAL
python3 tests/test_sxt017_predict.py            # or: pytest tests/
```

Inputs: `corpus/normalized/graphs.jsonl`
(sha256 `c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715`),
`model/resources/` accounting (SXT-015, `placeholder-v0`),
`reports/sxt-013/candidates/slate-256-*.json` (proposals). Negative controls:
`reports/sxt-017/negative-controls.txt`.

## 10. Provenance / licensing

Original to this repository (Apache-2.0 per `LICENSE`); Python stdlib only.
The predictor imports this repository's own SXT-015 accounting model and
reads the committed SXT-011 graphs; engine facts (MAX_UNISON, polylimit,
scene-mode ids, FX buffer structure) are **read and cited** from the pinned
GPL-3.0-or-later tree via SXT-015 — no Surge source, tables, algorithm
lists, or preset payloads are copied into this repository. Slate data is
this repository's own SXT-013 output. Method note: the versioned-contract +
decision-record format follows the issue-#12 reusable-substrate pointer
(gf180-dx7#4, gf180-torchsynth@6532ec08) as *method only*; no sibling code
was copied (docs/REUSE-AUDIT.md).

## 11. What this document does NOT establish

- Any frozen profile, budget, or product decision (freeze BLOCKED: SXT-013
  listening, SXT-014 labels, SXT-016 numbers).
- Any fidelity result, preset-quality judgment, or musical usefulness.
- Any FPGA/gf180mcu synthesis, area, timing, power, or hardware playback
  result; every cycle/RAM/bandwidth number is a placeholder-based column
  [PENDING-SXT-016].
- Any claim that predicted-supported presets actually sound like the
  reference; that requires the frozen fidelity policy and renders.
