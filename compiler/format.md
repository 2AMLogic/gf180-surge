# Patch image format v1 — `sxt-020-patch-image/1.1.0` (DRAFT)

Issue: #13 (SXT-020) · Plan:
`docs/surge-xt-chip-plan-v0.1-2026-09-20.md` §3 (host preset compiler row),
§6 (SXT-020 row) · Compiler: `compiler/compile.py` · Verifier:
`compiler/verify.py` · Rejection catalog: [`rejections.json`](rejections.json)
· Field reference: [`schema/image-header.schema.json`](schema/image-header.schema.json),
[`schema/image-body.schema.json`](schema/image-body.schema.json)

## 0. Status and claim discipline

**DRAFT, versioned explicitly.** This format is compiled against
`profile-v1-DRAFT` bundle **B4-broad** (`contracts/profile-v1-bundle-DRAFT.json`,
status `DRAFT-NOT-FROZEN`). Nothing here is a frozen profile, a support
claim, a fidelity claim, or a preset-quality claim. Freezing the profile
stays BLOCKED on SXT-013 listening, SXT-014 labels, and SXT-016 probes
(profile-v1-DRAFT §0); a format or bundle freeze is a visible contract
revision with a version bump, never a silent change.

A patch image is a **structural artifact**: it says "the complete original
normalized graph fits this DRAFT bundle's gates and is expressible as an
image". It does **not** say the preset sounds like the reference, is worth
playing, or fits any measured budget — every allocation number is an SXT-015
bookkeeping placeholder **[PENDING-SXT-016]**.

**The never-trims contract (issue #13).** For every input the compiler emits
exactly one of:

- a **complete image** — the verbatim normalized graph plus derived views,
  allocations, event-timing requirements, and checksums; or
- a **rejection record** — outcome `rejected` or `unresolved` with one or
  more cataloged machine-readable codes.

There is no third outcome. The compiler never drops a feature, substitutes
an effect, defaults an unexportable value, or otherwise "simplifies" a patch
to make it fit. Anything that would require an edit (adaptation-class codes
included) is a rejection of the original graph.

## 1. Source and gate semantics

Input: one line of `corpus/normalized/graphs.jsonl` (SXT-011 normalized
graph; engine pin `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
48 kHz; raw `.fxp` values are pre-migration and never authoritative — the
normalized post-loader state is).

Feature/resource gates are evaluated by the **SXT-017 DRAFT predictor's own
evaluator** (`tools/profile_predict.py::predict_line`), imported unmodified,
so compile outcomes reconcile with `reports/sxt-017/predictions/` by
construction rather than by a parallel re-implementation that could drift.
On top, the compiler applies the gates an *image emitter* must apply:

| Compiler-only gate | Why the predictor can stay silent |
|---|---|
| `asset_unresolved` — a wavetable record with neither embedded bytes nor a resolved file | The predictor predicts structural fit; the image must *reference* the asset, and referencing a missing asset would silently ship the engine's default-table fallback in its place |
| `send_levels_not_exported` — an enabled FX instance in send slot 3/4 | SXT-011 does not export scene send levels for buses 3/4 (binding exposes `send_level[0..1]`); an image without them would implicitly trim the routing |
| `routing_form_unsupported` — role outside the engine's 16-role set or role/slot-index inconsistency | The predictor never sees malformed roles in the committed corpus; the compiler must fail closed on any future/malformed input |

The compiler's gate set is therefore a strict **superset** of the
predictor's: it can reject more, never less. Every delta against the SXT-017
predictions is enumerated in the corpus scan
(`reports/sxt-020/compile-corpus-scan.json`, `reconciliation.deltas`).

Outcome classes (issue #13 vocabulary):

| Outcome | Meaning |
|---|---|
| `compiled` | complete image emitted |
| `rejected` | the graph carries something outside the DRAFT bundle / not expressible — cataloged codes attached |
| `unresolved` | the graph cannot be evaluated *today* (loader failure, MSEG/Formula contents not exported, unaccountable scene mode, event-queue closure) — cataloged codes attached |

Adaptation-class codes (`polylimit_reduction_required`,
`unison_reduction_required`) are **compile rejections**: the compiler
compiles original graphs only. An adapted preset becomes compilable only
through a future explicit adaptation path with its own visible record —
never by a silent edit at compile time, and adapted presets never count as
compiled coverage.

## 2. Container layout (binary, little-endian)

```
offset  size  field
0       4     magic "SXP1"
4       1     format_major (=1)
5       1     format_minor (=0)
6       2     header_len (u16, bytes of canonical header JSON)
8       4     body_len   (u32, bytes of canonical body JSON)
12      H     header JSON  (UTF-8, canonical: sorted keys, separators ',':')
12+H    B     body JSON    (UTF-8, canonical, same rules)
12+H+B  64    container_digest = ASCII hex SHA-256 over bytes [0, 12+H+B)
```

Canonical JSON: `json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=True, allow_nan=False)`.

**Checksums (two independent layers):**

1. `header.body_sha256` = SHA-256 (hex) of the canonical body bytes — the
   strong hash over the canonical body (issue #13 acceptance).
2. `container_digest` = SHA-256 (hex) over the entire preceding container —
   detects any corruption anywhere (header included).

Verification (`compiler/verify.py image`) re-parses the container, checks
both checksums, re-serializes the parsed body and requires byte equality
(canonicality), and — strongest — **rebuilds the normalized graph from the
body's verbatim sections and requires its SHA-256 to equal
`header.normalized_graph_sha256`** (losslessness; DX7 P01-style
round-trip discipline, method only).

## 3. Header (identity + provenance — small, immutable)

| Field | Contents |
|---|---|
| `format`, `format_major`, `format_minor` | format identity |
| `compiler_version` | `sxt-020-compile/x.y.z` |
| `body_sha256` | checksum layer 1 |
| `source` | census `path`, `bank`, `census_blob_sha1` (git blob SHA-1 of the source `.fxp`), `size_bytes` |
| `pin` | engine commit, sample rate (48 000), graph schema version — repeated per image so every image is independently checkable |
| `normalized_graph_sha256` | SHA-256 of the canonical normalized graph `g` (checksum layer 3: pins the exact source graph) |
| `profile` | `artifact` (`profile-v1-DRAFT`), `bundle_id`, `bundle_status` (`DRAFT-NOT-FROZEN`), `bundle_file_sha256`, the full `bundle_spec` the gates were evaluated against, and a `claim_scope` note |

No timestamps, wall-clock, machine paths, or environment values anywhere in
header or body. Same graph bytes + same bundle file + same compiler version
⇒ byte-identical image (verified in the golden suite and CI).

## 4. Body

Two top-level sections: `graph` (verbatim, lossless) and `derived`
(compiler views). Every field of the source graph appears exactly once —
the image adds annotations, it never rewrites or drops patch content.

### 4.1 `graph` (verbatim source)

| Section | Carries |
|---|---|
| `scalars` | `sm` (scene mode id), `smn`, `sa`, `spl`, `poly` (polylimit), `ch`/`chn` (character), `fxb`/`fxbn` (FX section bypass), `fxd` (per-slot disable mask), `vol` — whichever the graph stores |
| `scenes` | `g.sc` verbatim: both scenes (scene B carries state even when routing-inactive), each with playmode, pitch/octave/bend/keytrack/porta, filter-block config, mixer (`mix`), FM routing, sends, the 3 oscillator slots (type id/name, the 7 params — **p[0] is the family submode**, unison, detune), the 2 filter units (type/subtype/cutoff/res/EG/keytrack), the waveshaper (type id/name/drive), and the 6 LFO records (MSEG/Formula records carry their `gap` marker verbatim) |
| `fx_slots` | `g.fx` verbatim: all 16 slots — role (`ains1..4`, `bins1..4`, `send1..4`, `global1..4`), type id/name, `on`, the 12 params, `rl` (return level), `aw`/`awn` (Airwindows algorithm id = `p[0]`) when present |
| `modulation` | `g.md` verbatim: global + per-scene scene-bus/voice-bus routing rows `[source_id, source_scene, source_index, dest_synthside_id, dest_name, depth, normalized_depth]` |
| `wavetable_assets` | `g.wta` verbatim: per scene/osc display name (raw-side provenance), embedded byte size, script name, resolved `[[path, sha256], ...]` |
| `dependencies`, `migration_events`, `raw_missing`, `raw_uninterpretable`, `raw_note` | `g.dep`, `g.mi`, `g.rwm`, `g.rwu`, `g.raw_note` verbatim when present |

### 4.2 `derived` (compiler views; recomputable from `graph` + pinned model)

| Section | Contents |
|---|---|
| `voice_graph` | scene mode, active scenes, `voices_per_note` (dual = 2 pool voices/note), worst-case voices (`min(polylimit, pool)`), per-scene oscillator slot activity/unison-effective annotations (engine clamps unison to MAX_UNISON=16; out-of-range raw values are annotated, never rewritten), unison load, filter-unit activity, waveshaper activity, MSEG/Formula gap lists, LFO/envelope instance counts |
| `fx_section` | per-slot: phase (`scene_A_insert` → `scene_B_insert` → `send_bus` → `global_insert`), `order_in_phase`, `engine_order` (the engine's fixed processing rank: A1→A4, B1→B4, scene sum, S1..S4 with per-slot return level, G1→G4), enabled-by-`fxd`, routing-active, processes-this-frame, state tier; section bypass + disable mask; enabled/processing/distinct-type counts. **Per-instance discipline:** two Delay slots are two instances with separate state, always; `fxd`-disabled slots hold state but neither process nor gate |
| `allocations` | see §5 |
| `event_timing` | required event queue depth, worst coincident events per frame, peak events/s, source (SXT-012 fixture profile) |
| `caveats` | the SXT-015 accounting anomalies verbatim (unison out of range, SLFO/MSEG exposure notes, unverified-class flags) — recorded observations that never alter patch content |
| `wavetable_asset_manifests` | **(SXT-026, format 1.1)** one manifest record per resolved `wavetable_assets` entry, emitted only when the compile is invoked with `--asset-root` (the external pinned tree's `resources/data`; the payload is read in place and never copied): identity (`path`, `sha256`, `bytes` — hashes only in-repo per `decision-records/0004`), dims (`wave_size`, `wave_count`, sample format, `dt`), mip/AA structure (engine mip construction levels, the oscillator's selectable levels 0..6 with the pinned `a = dt·pitchmult_inv` thresholds, required linear-frame + sinc impulse interpolation), and residency classification (read-only external flash asset; on-chip working set = the mip level in play). A hash mismatch between the external file and the graph's resolved record **aborts the compile** (`compiler/assets/wavetable.py`) |
| `losslessness` | `normalized_graph_sha256` + the exact reconstruction rule used by `verify.py` |

## 5. Allocations (`derived.allocations`)

Computed by the repository's own SXT-015 model
(`model/resources/accounting.py`) under the bundle's voice-pool override —
the same account the predictor used, so numbers agree by construction.

- **Regions:** `on_chip` (base 0x0), `external_writable` (separate address
  space, base 0x0), `flash_assets` (read-only). Classification rule:
  writable class > 64 KiB ⇒ external writable. **Flash is assets only and
  is never writable delay/reverb storage** (plan §3).
- **Blocks:** `voice_state` is one aggregate block until SXT-016/023 pin a
  per-voice layout (declared in `basis.note`); every configured FX instance
  gets its **own** block (`fx_slot_N`) in slot order — per-instance effect
  state is preserved even when arithmetic is shared; each wavetable record
  with embedded bytes gets a `flash_assets` block. Offsets are cumulative in
  that fixed order (deterministic).
- **`fx_instances`:** per instance — class, enabled/routing-active/
  processing flags, region + offset + size, per-frame external reads/writes,
  verification-tier flags. Routing-inactive scene-B instances are allocated
  state but contribute no traffic (SXT-015 rule).
- **`bandwidth`:** modeled external traffic bytes/frame and bytes/s at 48 kHz
  (processing instances only).
- **`cycles_placeholder_v0`:** cost columns and closure status. **NOT a
  gate** — the profile is `placeholder-v0` [PENDING-SXT-016]; the bundle's
  `cycle_closure` is `not_gated_pending_sxt_016`.
- **`budgets`:** the bundle's declared candidate budgets (4 MiB on-chip,
  64 MiB external writable, 800 MB/s external bandwidth — candidates, not
  claims). Memory/bandwidth capacity codes
  (`on_chip_ram_exceeded`, `external_writable_capacity_exceeded`,
  `external_bandwidth_exceeded`) compare against these and **do** gate,
  exactly as in SXT-017.
- **`basis`:** accounting model version, params digest, cost profile — so
  every number can be re-derived and any drift is visible.

## 6. Rejections (catalog summary)

`rejections.json` is the single source of every code (22 codes: 18 shared
with SXT-017 under the same name and meaning for reconciliation, plus
`asset_unresolved`, `send_levels_not_exported`, `routing_form_unsupported`,
and the reserved `oscillator_submode_not_in_bundle`, which is not evaluable
under the current spec schema). Every emitted code is validated against the
catalog at emit time — an uncataloged code aborts the compile. The catalog
also declares the **non-gates**: oscillator submodes (`p[0]`), filter
subtypes, waveshaper algorithms, and cycles are carried verbatim and not
gated under this DRAFT (spec revisions required to gate any of them).

A rejection record carries: compiler version, source identity, profile
identity, outcome, the full code list (each with class + detail), and the
never-trims note. For real presets the record's codes are asserted in the
golden suite; a rejection never ships an image beside it (checked live).

## 7. Determinism rules

1. Canonical JSON everywhere (sorted keys, tight separators, ASCII, no NaN).
2. No timestamps, wall-clock, random, or machine-dependent values.
3. Fixed iteration orders: graph arrays in engine order, FX slots by index,
   allocation blocks by (voice, then slot order), codes in
   (predictor order, then compiler-gate order).
4. Floats are carried as exported by SXT-011 (6-decimal rounding already
   applied at the source) or rounded by the SXT-015 model (`_r6`).
5. Same inputs ⇒ byte-identical `.image.bin` / `.image.json` /
   `.rejection.json` / scan JSON. Golden suite + CI enforce this.

## 8. Golden suite

`compiler/golden/` pins real corpus cases (compiled images byte-for-byte +
expected rejection codes) plus clearly-labeled synthetic inputs. Recorded
finding: the DRAFT B4-broad spec's `fx_type_allowlist` excludes the
Airwindows **class** entirely, so no Airwindows-carrying image can compile
under it (the class allowlist binds before the algorithm selection —
profile-v1-DRAFT §4); a synthetic Airwindows-carrying graph is therefore
pinned as a *rejection* case carrying both Airwindows-related codes.
`verify.py golden` recompiles every case against the current graphs +
bundle and requires byte identity; a graphs/bundle SHA drift fails the
suite and demands regeneration, never silent acceptance.

## 9. Versioning policy

- **Patch** (`1.0.z`): compiler fixes that provably cannot change bytes.
- **Minor** (`1.y`): additive body/derived fields; golden regeneration with
  a visible diff; scan reconciliation re-run. **Applied: 1.0.0 → 1.1.0
  (SXT-026, issue #19)** — additive optional derived section
  `wavetable_asset_manifests`, emitted only under `--asset-root`; the golden
  suite stays oracle-free (compiled without the flag), and a
  manifest-carrying image is pinned as evidence in `reports/sxt-026/`
  with its verification transcript.
- **Major** (`2.0.0`): any header/container/layout change, any gate or
  outcome-class change, any catalog class change. Requires a format revision
  note, golden regeneration, and a scan re-run — the issue-#13
  stop/escalate clause: if the format cannot express some dynamic behavior
  the profile promises, BLOCK and revise the format before any RTL consumes
  it.
- Gate-semantics changes to the *profile* are bundle-spec revisions
  (profile-v1-DRAFT §8) with a new `bundle_file_sha256`; images record which
  bundle they were compiled against, so old images stay interpretable.

## 10. What this format does NOT establish

- That any compiled preset sounds like the pinned Surge reference (that
  needs the frozen fidelity policy + renders).
- That any compiled preset is musically useful (listening records only).
- Any measured cost: every allocation number is an SXT-015 placeholder
  [PENDING-SXT-016]; budgets are candidates.
- Any FPGA/gf180mcu synthesis, signoff, or hardware playback result.
- A frozen profile: `DRAFT-NOT-FROZEN` is carried in every image header and
  rejection record.
