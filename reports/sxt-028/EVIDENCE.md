# SXT-028 evidence record — effects leaf generator + first recovery-ordered leaves filed

Branch: `loom/sxt-028-effects-leaves` · Issue: #21 (SXT-028, issue
generator) · Date: 2026-09-21

**Claim discipline.** This record covers the *issue-generation* portion of
SXT-028 only: a deterministic generator and 12 filed leaf issues plus a
10-leaf backlog. It establishes **no model/RTL existence or equality claim**
(no effects model or RTL was written), **no fidelity claim** (reference
budgets in the leaves are [PROPOSED], not frozen), **no essentiality label**
(numeric deltas are diagnostic; listening is BLOCKED-on-human in #9), **no
cost claim** (all ext-mem/cycle numbers are [PENDING-SXT-016] markers), and
**no support/coverage/quality claim** (newly-enabled counts are FX-scope
accounting, not support). No oracle run was needed; every input is
committed data.

## Deliverables

| Deliverable | Artifact |
|---|---|
| Deterministic generator | `tools/generate_effect_leaves.py` (stdlib-only; inputs: `corpus/normalized/graphs.jsonl` sha256 `c90424d9…`, `reports/sxt-014/ablation-summary.json`, `contracts/profile-v1-bundle-DRAFT.json#B4-broad`) |
| Allocation table | `reports/sxt-028/allocation.json` — SXT-028a–028v reserved by this run (22 leaves; parent-id + letter convention, SXT-026a precedent; SXT-027 leaves own 027a… independently) |
| Per-leaf specs (22) | `reports/sxt-028/leaves/SXT-028<x>.json` |
| Issue bodies (filed 12) | `reports/sxt-028/leaves/SXT-028<x>.md` |
| Newly-enabled hash lists (22) | `reports/sxt-028/leaves/SXT-028<x>/newly-enabled.json` (full path + git blob SHA-1 per preset) |
| Backlog (10) | `reports/sxt-028/leaf-backlog.json` (SXT-028m…v) |
| Filing record | `reports/sxt-028/leaves-filed.json` |
| Generator negative controls | `reports/sxt-028/negative-controls.txt` |
| Reproduce/verify | `python3 tools/generate_effect_leaves.py --verify` (byte-compares all 58 committed artifacts) |

## Issue-#21 acceptance mapping

| #21 acceptance item | Status | Evidence |
|---|---|---|
| One algorithm (or routing form) per leaf; Airwindows leaves per algorithm, not one block | **PASS** | 12 AW leaves filed individually (SXT-028a, 028k; backlog 028m–v), one per selected algorithm id/name/header file; 5 type leaves; 5 routing-form leaves keyed to role sets from graphs. Generator refuses multi-feature leaves (NC2). |
| Every leaf preserves per-instance state (independent histories) under shared arithmetic | **PASS** (as an acceptance clause of every leaf) | `state_and_cost.per_instance_state` + a dedicated acceptance item: dual-slot model-level fixture, per-instance RTL/model equality, shared-state mutant must FAIL (`tb_fx_shared_line` pattern). Implementation is the leaves' business — no claim made here. |
| Every leaf's acceptance includes tails and patch-change/reset behavior | **PASS** | `acceptance` item 4 in all 22 specs: tail-span renders, mid-tail patch change, reset/panic, dropped-tail renders FAIL. |
| Ordering by #9 recovery labels; optional-by-adaptation flagged | **PARTIAL — labels BLOCKED-on-human** | Ordering uses SXT-014 numeric deltas first (measured: AW Galactic 10.093 dB, Conditioner 2.245, Chorus 2.083), then B4-scope carrier counts; every artifact carries "essentiality UNVERIFIED — listening pending (#9)". Unmeasured leaves are explicitly stamped as frequency-ordered. Re-ordering after #9 labels land is a regeneration away; no label is claimed. |
| Negative control: each leaf's check demonstrably fails a known-bad variant | **PASS** (as leaf text + live generator controls) | Every leaf ships 5 named controls (wrong order, shared state, generic substitute→ADAPTED-excluded, dropped tail, stale stub). The generator's own controls ran live this run (below). |

## Filed leaves (12) — `leaves-filed.json` is the authoritative record

| Leaf | Issue | Basis (diagnostic) | B4-scope candidates | strict-FX-complete |
|---|---|---|---|---|
| SXT-028a AW Galactic | #53 | 10.093 dB ablation | 81 | 38 |
| SXT-028b Conditioner | #54 | 2.245 dB ablation | 365 | 175 |
| SXT-028c Chorus | #55 | 2.083 dB ablation | 331 | 175 |
| SXT-028d routing global2 | #56 | frequency | 445 | 60 |
| SXT-028e Distortion | #57 | frequency | 304 | 158 |
| SXT-028f Reverb 2 | #58 | frequency | 232 | 101 |
| SXT-028g Phaser | #59 | frequency | 155 | 97 |
| SXT-028h routing bins1/2 | #60 | frequency | 131 | 16 |
| SXT-028i routing ains3/4 | #61 | frequency | 55 | 4 |
| SXT-028j routing global3/4 | #62 | frequency | 48 | 1 |
| SXT-028k AW Logical | #63 | frequency | 30 | 0 |
| SXT-028l routing send3/4 | #64 | frequency | 18 | 0 |

Backlog (not filed): SXT-028m To Tape, 028n Capacitor, 028o NC-17, 028p
Mojo, 028q DeRez, 028r Bright Ambience, 028s Pocket Verbs, 028t
Compresaturator, 028u Drive, 028v Iron Oxide. All counts are FX-scope
accounting against the DRAFT B4-broad gates — not support predictions and
not favorites-set coverage (favorites: BLOCKED-on-human, #8/#13).

## Generator negative controls (live this run, `negative-controls.txt`)

| Control | Targeted failure | Result |
|---|---|---|
| NC1 zero-newly-enabled leaf refused | filing leaves that enable nothing | **PASS** — probe leaf AW id 47 "Slew 1" (real corpus algorithm, out of B4 selection → zero in-scope presets) refused with named reason |
| NC2 cross-type merged leaf refused | one "Chorus+Delay"-style monolith | **PASS** — multi-feature leaf spec refused: "one algorithm (or routing form) per leaf" |
| Byte-determinism | non-reproducible output | **PASS** — `--verify` re-run byte-compares all 58 artifacts OK |

## Coordination notes

- **#16 (SXT-023, Delay/EQ):** SXT-028c (Chorus) carries an explicit
  "SXT-017 decision required" marker: Chorus shares the LFO-modulated
  delay-line semantics of the open delay-budget finding
  (`reports/sxt-023/delay-budget-diagnosis.md` — LFO-term presence, options
  1–3). No Chorus budget may freeze before #12 decides. Delay/EQ are also
  counted as in-flight coverage in the strict newly-enabled rule, with that
  caveat recorded.
- **#12 (SXT-017):** all leaves gate reference-budget freezing on the #12
  freeze; SXT-028f (Reverb 2) additionally flags its tank state as the
  batch's largest external-memory candidate [PENDING-SXT-016]; SXT-028l
  (send3/4) flags the documented SXT-011 send-level data gap (buses 3/4)
  as needing an engine-behavior probe + SXT-017 data-gap policy decision.
- **#9 (SXT-014):** ordering input; listening labels remain the missing
  half of recovery ordering. Regeneration after labels land is
  deterministic and cheap.
- Routing-form leaves derive strictly from graphs role data minus the
  roles already exercised by fixtures of record (ains1, ains2, send1,
  send2, global1 — SXT-014/SXT-023/SXT-025 provenance recorded in the
  generator).

## What remains unproved / NOT_RUN

- Everything implementation-side: no effects model, no RTL, no fixtures
  rendered, no fidelity result, no cost measurement (all leaves' business).
- Essentiality of every ordered effect (listening, #9).
- Any support/preset-quality claim; coverage publication is #22.
- The backlog leaves (SXT-028m–v) are generated but not filed; filing them
  is a `--filed N` regeneration away, with the allocation table reserving
  their letters.
