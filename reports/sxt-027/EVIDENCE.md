# SXT-027 evidence record — voice-feature leaf generator + first recovery-ordered leaves filed

Branch: `loom/sxt-027-voice-leaves` · Issue: #20 (SXT-027) · Date: 2026-09-21

Engine facts cited (external, GPL-3.0-or-later, read and cited — never
copied): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
— `src/common/SurgeStorage.h` (`play_mode`, `fm_routing`, `scene_mode`
enums), `src/common/ModulationSource.h` (`modsources` enum),
`src/common/dsp/oscillators/*`, `src/common/FilterConfiguration.h`,
`src/common/dsp/` (voice/modulators), `libs/sst/sst-filters`,
`libs/sst/sst-waveshapers` (pinned submodules).

**Claim discipline.** This record establishes exactly one thing: a
deterministic **issue generator ran over committed analysis data and its
output was filed as planning issues**. It establishes **no** RTL or model
result, **no** fidelity result, **no** preset-support or preset-quality
claim, **no** cost-fit claim (every SXT-015/016 number cited in leaves is
a placeholder-class planning number or marked [ESTIMATE]), and **no**
FPGA/gf180mcu synthesis or hardware claim. Filing a leaf issue is not
progress on the claim ladder; only the leaves' own evidence records are.

## Deliverables

| Deliverable | Artifact |
|---|---|
| Deterministic generator | `tools/generate_voice_leaves.py` (`sxt-027-leaf-gen/1.0.0`) |
| Full leaf plan + SXT allocation table | `reports/sxt-027/leaf-plan.json` |
| Committed backlog (filed later, in recovery order) | `reports/sxt-027/leaf-backlog.json` |
| Filing record | `reports/sxt-027/leaves-filed.json` |
| Generator negative controls + transcript | `reports/sxt-027/negative-control-generator.py`, `reports/sxt-027/negative-controls.txt` |

## Method (and its bounded findings)

- **Inputs (all committed, hash-pinned):** `corpus/normalized/graphs.jsonl`
  (sha256 `c90424d9…`), B4-broad predictions (SXT-017), compile-corpus scan
  (SXT-020), three slate-256 proposal slates (SXT-013), F-1 finding
  (`model/integration/selection-scan.json`, SXT-025). The run refuses on
  any hash/integrity mismatch.
- **One leaf per algorithm/submode/topology** (issue #20; no family-wide
  leaves): oscillator family (incl. its submode selector), filter `fut_`
  type (incl. its engine-declared subtype set; observed subtype inventory
  embedded), waveshaper `wst_` type, scene mode, FM routing form,
  playmode submode, unison-stack boundary, modulator behavior class (with
  explicit per-instance-state rules).
- **Recovery attribution:** a B4-predicted-supported preset counts for a
  leaf when its ORIGINAL normalized graph requires the leaf's feature on
  an active slot/route — the SXT-015 accounting rules, the same rules the
  SXT-017 predictor gated on. **Bounded finding (attribution):** this is
  requirement attribution, not marginal-gain accounting; shared presets
  attribute to multiple leaves (e.g. the lfo leaf's 122 basis presets and
  the unison leaf's 92 overlap). Per-leaf marginal gains require an
  ordering over feature subsets and are deliberately not invented here.
- **Recovery basis:** the union of the three SXT-013 proposal slates'
  B4-predicted-supported paths (**166 presets**); corpus context is the
  full B4-supported set (**1,685**). **Bounded finding (essentiality):**
  issue #20 asks for ordering "derived from the frozen favorites set
  (#8)". SXT-013 human listening is BLOCKED; #8 closed with deterministic
  diversity-maximized *proposal* slates only, essentiality UNVERIFIED.
  The slate union is therefore used as the declared proxy, the caveat is
  embedded in every leaf and in both plan artifacts, and re-running the
  generator against a real favorites set (same tool, same determinism) is
  the recorded path when #13's listening lands. Ordering is basis-recovery
  first — not raw corpus frequency.
- **F-1 first-class leaf:** the landed SXT-022 voice leaf covers only
  Attacky's exact arithmetic (SXT-025 finding F-1; census scan: exactly
  Attacky + Quickspit inside it, neither carrying FX). Voice-slice
  generalization is therefore the top item, and it is **already filed as
  #48 (SXT-026a)** — the generator lists it in the ledger with its
  recovery (166/1,683 outside the landed arithmetic), does not re-file it,
  and does not allocate an SXT number for it. Every filed leaf names #48
  as a dependency; every leaf's recovery count is a B4-model attribution,
  not an incremental gain over the landed slice.
- **Landed ledger:** `osc_family:Wavetable` is landed (SXT-026, #19,
  closed) and excluded from candidacy (attribution shown in the plan
  ledger: 99/663).
- **SXT allocation:** free numbering starts at SXT-032 (031 taken). The
  allocation table in `leaf-plan.json` reserves SXT-032…SXT-103 for this
  run's candidate leaves in recovery order; effects leaves (#21/SXT-028)
  are outside this allocation and should coordinate through the table
  before filing.
- **Cost notes:** each leaf carries a cost-note column — SXT-016 probe
  citation where a kernel-class probe exists (classic_blit, sine_table,
  sine_poly_fastmath, svf_tdf2, k35_ladder_tanh_lut, scheduler), else
  `[ESTIMATE]` + "SXT-016 probe required" (FM2, FM3, S&H Noise, most
  filter types, all waveshapers). Per AGENTS.md these support no
  technology claim.

## Filing record

**12 leaves filed now** (top of the recovery order; full data in
`leaves-filed.json`, bodies generated byte-exactly by the tool):

| Issue | Leaf | Basis recovery | Corpus (of 1,685) |
|---|---|---:|---:|
| #66 | SXT-032 modulation behavior: lfo (LFO1–6, per-instance state) | 122 | 1,223 |
| #67 | SXT-033 oscillator family: Classic (beyond the landed Attacky config) | 94 | 918 |
| #68 | SXT-034 unison stack topology (>1 voice) | 92 | 794 |
| #69 | SXT-035 modulation behavior: modwheel (arbitrary destinations) | 91 | 821 |
| #70 | SXT-036 modulation behavior: velocity (+release velocity) | 86 | 757 |
| #71 | SXT-037 filter algorithm: LP 12 dB (beyond Driven) | 70 | 515 |
| #72 | SXT-038 filter algorithm: LP 24 dB | 49 | 459 |
| #73 | SXT-039 filter algorithm: LP Legacy Ladder | 45 | 393 |
| #74 | SXT-040 oscillator family: Sine | 38 | 313 |
| #75 | SXT-041 modulation behavior: slfo (SLFO1–6) | 36 | 287 |
| #76 | SXT-042 modulation behavior: keytrack | 34 | 310 |
| #77 | SXT-043 playmode submode: Mono (Single Trigger & Fingered Portamento) | 29 | 159 |

**Backlog: 60 leaves** in `leaf-backlog.json` (recovery order, SXT-044+
pre-allocated in the plan's allocation table), of which **29 have zero
slate-basis recovery** and are explicitly marked deferred (corpus-only
recovery) — filed later only per issue #20's "or explicitly deferred"
clause, never silently dropped.

## Acceptance mapping (issue #20)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | Every leaf names the complete presets it newly enables; zero-recovery leaves not filed (or explicitly deferred) | **PASS** | Every filed leaf embeds its basis presets by path + census blob SHA (`leaves-filed.json`, issue bodies); backlog leaves carry the same in `leaf-backlog.json`; 29 zero-basis leaves explicitly deferred; the generator hard-refuses zero-recovery emission (NC-G1). |
| 2 | One algorithm/submode/topology per leaf; no family-wide leaves | **PASS** | Leaf granularity is declared in `leaf-plan.json` `method.leaf_granularity`; 72 candidates across 8 narrow dimensions; no dimension-wide or "port everything" leaf exists. |
| 3 | Each leaf carries a negative control that demonstrably fails its own check | **PASS (as requirements)** | Each filed leaf's acceptance includes a dimension-specific control (wrong-family/wrong-algorithm/wrong-subtype substitution, collapsed-scene, forced-Poly, fm-off, routing-zeroed, unison-collapsed, drive-dropped) plus the SXT-022-pattern RTL mutant, each with a committed-transcript requirement. The controls are unexecuted planning requirements — the leaves' own evidence records must demonstrate them. **NOT_RUN here by construction.** |
| 4 | Recovery ordering derived from the frozen favorites set (#8), not raw frequency | **PASS with bounded finding** | The listening-ranked favorites set does not exist (SXT-013 listening BLOCKED; #8 closed on proposal slates). Ordering uses the committed slate-union B4-supported proxy (166) with the essentiality caveat embedded in every artifact; corpus frequency is context only. Recorded as the essentiality bounded finding above; re-run path declared. |

## Negative controls (generator-level, live)

`reports/sxt-027/negative-controls.txt` — all five REFUSED (exit non-zero
/ `Refuse`), run via `negative-control-generator.py`:

- **NC-G1**: injected leaf emission with an empty newly-enabled set →
  refused ("enables zero presets … not filed").
- **NC-G2a–d**: unknown leaf keys/values/dimensions → refused.
- **NC-G3**: unknown oscillator family injected into the production
  feature extraction over real committed data → refused.
- **NC-G4**: unknown modsource id (99) injected likewise → refused.
- **NC-G5**: tampered graphs bytes through the full CLI → exit 2 (hash
  integrity gate).

These are live, executed controls of the generator's own guards. They
demonstrate nothing about any synthesis leaf.

## Determinism

Two runs of `tools/generate_voice_leaves.py` from the same inputs produced
byte-identical `leaf-plan.json`, `leaf-backlog.json`, and issue bodies
(`cmp`/`diff` clean; sorted keys, fixed separators, no timestamps). Same
input bytes ⇒ byte-identical outputs.

## What this work does NOT establish

- Any leaf implementation, RTL/model result, fidelity budget outcome, or
  preset-support change (the filed issues are planning artifacts).
- Any musical value judgment: essentiality of every slate preset is
  UNVERIFIED; recovery numbers say nothing about how anything sounds.
- Any cost/RAM/bandwidth fit: probe citations are planning numbers;
  [ESTIMATE] items have no measured basis at all.
- Any claim about effects leaves (#21), the wet acceptance gate (#18's
  supported-status row, blocked on #48), or profile freeze (#12).

## Licensing / provenance

`tools/generate_voice_leaves.py` and everything under `reports/sxt-027/`
are original to this repository (Apache-2.0 per `LICENSE`); Python stdlib
only, importing this repository's own SXT-015 accounting model. Engine
facts (enum ids/orderings, file/function paths, kernel-class probe names)
were read from the pinned GPL tree and cited; no Surge source, tables,
algorithm lists, or preset payloads are copied into this repository. No
sibling code was reused (method-level familiarity with the issue-#20
capability-node pointer only; per `docs/REUSE-AUDIT.md` no adoption was
needed for a stdlib generator).
