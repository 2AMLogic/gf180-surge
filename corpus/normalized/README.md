# SXT-011 — Normalized patch graphs (`graphs.jsonl`)

One compact single-line JSON object per census entry (3,561 lines for 3,561
`.fxp` files), produced by the **pinned native loader**. This is normalized
*data export only* — it makes no audio-support, fidelity, or preset-quality
claim, and no support claim of any kind.

- Engine pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  (surgepy self-reports `1.4.HEAD.58914e59c`), 48 kHz, submodules per
  `oracle/manifest.json` (SXT-010).
- Status per entry: `"st":"normalized"` or `"st":"analysis_failure"` with
  `"why":{phase, reason, detail}`. **Every** census entry has a line; unknown
  behavior is an explicit failure entry, never a guess and never a silent
  omission.
- Field-by-field reference: [`schema.json`](schema.json) in this directory.

## Reproduce

```sh
python3 tools/export_normalized_graphs.py --out reproduced/
diff corpus/normalized/graphs.jsonl reproduced/graphs.jsonl && echo IDENTICAL
```

The exporter is deterministic: same corpus bytes + same engine pin give a
byte-identical `graphs.jsonl` (sorted keys, fixed iteration order, floats
rounded to 6 decimals, **no timestamps inside the per-preset lines**). Run
metadata (timestamp, wall time, counts) goes to `--summary` /
`reports/sxt-011/export-summary.json`, which is *not* part of the
reproducible output. Requirements: the pinned python (auto re-exec via
`oracle/oracle_common.py`), the built surgepy module (SXT-010 layout), and
`SURGE_DATA_HOME` pinned to the engine tree's `resources/data` (set by the
exporter through `oracle_common.apply_engine_env`).

## What "normalized" means here

Raw `.fxp` values are pre-migration: the loader migrates them while streaming
(`SurgePatch::load_xml`, `src/common/SurgePatch.cpp`, `ff_revision = 30` in
`src/common/SurgeStorage.h`), and oscillator/effect classes apply their own
streaming-mismatch fixes afterwards (`update_controls(from_streaming=true)` →
`handleStreamingMismatches(streamingRevision, ...)`). Only the state read
back from the engine **after** `SurgeSynthesizer::loadPatch` at 48 kHz is
exported as graph state. The pinned corpus spans stored revisions 4–30, so
migrations are observable in bulk.

## Normalization rules

1. **Values**: every exported value comes from a surgepy getter
   (`getParamVal`, `getParamValType`, `getParamDisplay`, `getAllModRoutings`)
   on the loaded patch. Int/bool-valtype params are exported as ints,
   float-valtype params rounded to 6 decimals.
2. **Names** (`*n` fields) are the engine's own `get_display()` strings for
   the loaded state — not lookup tables copied into this repository. Id
   ranges live-derive from `getParamMin/getParamMax` at validation time.
3. **Raw sidecar**: a structural read of the `.fxp` (chunk layout per
   `corpus/census-v0.1/census.py`; XML parameter names as written by
   `SurgePatch::save_xml`) supplies *pre-migration* int ids **only** for
   migration comparison, raw-missing/raw-uninterpretable records, wavetable
   display-name provenance, embedded wavetable sizes, and the stored
   revision. Raw values never produce or replace exported state.
4. **Loader defaults**: a migration-prone int field absent from the raw XML
   is listed in `g.rwm` (raw_missing); the exported value is the loader
   default the engine actually applied.
5. **Reset policy (order-independence)**: the loader does not stream params
   that a preset file does not contain — such params keep the engine's
   previous value. Before every load the exporter therefore resets the known
   non-streamed globals to engine defaults: `volume` (element deleted from
   presets with revision<17 by `load_xml`), `fx_bypass` (deleted from EVERY
   preset — the value shipped in `.fxp` files is ignored by the loader), and
   `character`/`polylimit` (absent from the oldest revisions). With this
   policy a preset's exported graph is independent of what was loaded before
   it, and a fresh-engine re-load reproduces it exactly (spot-check).
   Consumers must treat exported `volume` and `fx_bypass` of rev<17 presets
   as harness/loader defaults, not preset content (`volume` is flagged in
   `g.rwm`); `fx_bypass` is a loader-level control for all presets by
   construction. Residual scope note: a scene- or FX-level parameter that
   some very old revision stops streaming could in principle still inherit a
   previous value; no such case was observed (the negative-control subjects
   — the oldest revisions in the corpus — re-extract identically on a fresh
   engine), and a full per-param streaming audit belongs to the SXT-012
   reset-policy work.
6. **Uninterpretable raw values**: very old files store some float params as
   IEEE bit patterns under int tags (e.g. `1062552025` = 0.8f). Values
   outside any plausible id range (bound 127; largest real id range is
   filter types 0..35) are recorded in `g.rwu` — visible, never compared,
   never dropped.
7. **Failure discipline**: `loadPatch` returning false/throwing, extraction
   exceptions, validation violations, or non-finite floats produce an
   `analysis_failure` line with a machine-readable reason. Validation
   violations should be impossible by construction; if one ever fires it is
   a finding, not something to route around.

## Loader migrations (observable, recorded per entry in `g.mi`)

Observed across the corpus (counts in `reports/sxt-011/export-summary.json`):

| Kind | Meaning | Pinned-source gate |
|---|---|---|
| `filter_remap` | Raw (type,subtype) pair differs from normalized pair. Raw ids of rev<15 files are `fut_14` ids (`FilterConfiguration.h`), not current `fut_` ids. | rev<15 "The Great Filter Remap" (SurgePatch.cpp `load_xml`, upstream issue #3006); rev<8 subtype defaults; rev<=26 subtype adjustments |
| `sine_shape_remap` | Raw Sine `Shape` (p[0]) differs from normalized. Includes the rev<=27 remap of odd shapes 1..7 → 28..31 **and** the rev<=12 `SineOscillator::handleStreamingMismatches` wave_remap, whose 20-entry range check resets out-of-range shapes (e.g. rev<=12 file with stored 7: load_xml maps 7→31, then handleStreamingMismatches finds 31 ≥ 20 and resets to 0 — the engine's authoritative result, which we record as raw 7 → normalized 0). | SurgePatch.cpp `load_xml` rev<=27 block; `SineOscillator.cpp` `handleStreamingMismatches` |
| `ringmod_shape_remap` | Ringmod FX p[0] shape id remap (rev<=27). | SurgePatch.cpp `load_xml` rev<=27 block |
| `polylimit_default` | rev<=15 files storing polylimit 8 are reset to `DEFAULT_POLYLIMIT` (16). | SurgePatch.cpp `load_xml` |
| `character_default` | rev<10 files normalize character to 0. | SurgePatch.cpp `load_xml` |
| `osc_type_diff` / `fx_type_diff` | Not known migrations: an unexplained raw-vs-normalized difference that must be investigated before use. (Zero occurrences in the committed export.) | — |

These fields are compared: filter type/subtype (both units, both scenes),
Sine p[0], Ringmod p[0], polylimit, character, osc types, FX types. The
rev<=27 Twist oscillator pitch adjustment is a float migration and is
deliberately **not** compared (the raw sidecar does not interpret floats);
it is listed here as a known, unexercised-by-this-schema migration.

## Mapping notes for raw parameter ids (surgepy API gaps and how we bridge them)

The binding exposes some state only as raw ids or not at all. What we rely
on, with the pinned functions consulted (read, not copied):

- **Modulation destination ids** (`md` rows, index 3): the raw synth-side id
  from `SurgeSynthesizer::ID::getSynthSideId()` of the destination
  Parameter, as returned by the binding's `getAllModRoutings()`
  (`src/surge-python/surgepy.cpp`). For scene-bus routes the binding adds
  `storage.getPatch().scene_start[sc]` so ids are absolute across scenes;
  voice routes likewise. The destination's human name
  (`getParameterName`/`SurgePyNamedParam` name) is stored alongside every id
  (row index 4), so consumers never need the id map. Ids are stable *within
  this pin only*.
- **FX parameter names**: `getPatch().fx[i].p[j]` is a
  `SurgePyNamedParam` whose name is engine-defined per effect type at
  runtime (`Parameter::get_name`); names are not duplicated into this
  schema. The Airwindows algorithm id is `fx[i].p[0]`
  (`AirwindowsEffect`'s selector param), exported as `aw` with the engine's
  display name for that algorithm as `awn`.
- **FX slot roles and processing order**: fixed by the engine
  (`SurgeStorage.h` `fxslot_positions`/`fxslot_order`,
  `SurgeSynthesizer::process`): A1→A4 and B1→B4 insert chains, scene sum,
  send buses S1..S4 (each sums `scene[0].send_level[k]` and
  `scene[1].send_level[k]`, applied when `fx_bypass==fxb_all_fx`, scaled by
  the slot's `return_level`), then G1→G4 on the main output. Per-slot
  disable is `fx_disable & (1<<slot)`; the section-level bypass id is
  `fx_bypass` (0=All FX, 1=No Send FX, 2=No Send and Global FX, 3=All FX
  Off).
- **Wavetable identity**: the engine keeps `wavetable_display_name`
  (streamed from raw `<extraoscdata>`; fallbacks "(Patch Wavetable)" /
  "(Patch Sample)" when absent — `SurgePatch.cpp`), which surgepy does not
  expose. We therefore record the raw-side name (provenance-flagged in the
  schema), the per-osc embedded byte size from the .fxp chunk header, and —
  when the name matches a file stem in the pinned `resources/data/wavetables`
  tree (engine `wt_list` names are file stems,
  `SurgeStorage::refreshPatchOrWTListAddDir`) — the relative path(s) and
  sha256. Unresolvable names are recorded as unresolved (the engine's own
  default-table fallback applies); nothing is guessed.
- **Send levels 3/4**: the engine has 4 send buses but stores only 2 per
  scene in `.fxp` files and the binding exposes only `send_level[0..1]`
  (`surgepy.cpp` `makeScene`). Buses 3/4 (slots S3/S4) therefore run at
  loader defaults for every corpus entry; recorded as a documented exposure
  gap, not extracted.
- **MSEG / Formula LFO contents**: not exposed through surgepy; LFO records
  with shape MSEG/Formula carry
  `gap:"modulator_contents_not_exposed_by_surgepy"`. This is the SXT-011
  stop/escalate note: if a later milestone needs those curves, the
  instrumentation approach must be extended (or the testrunner path used);
  we did not work around it with raw-XML guessing.

## Schema tiers and size

`graphs.jsonl` is ~17.8 MB (guard: < 150 MB), ~5 KB/preset median. Tiers, in
reduction order if the guard were ever exceeded: (1) drop `*n` display-name
fields (recoverable from the pin), (2) drop `md` dest names (ids suffice
within the pin), (3) drop Off-slot records to bare indices. None of these
are applied in the committed output.

## Licensing / provenance

The exporter (`tools/export_normalized_graphs.py`) is original to this
repository (Apache-2.0 per `LICENSE`). It imports the external GPL-3.0-or-
later engine at runtime through the official surgepy binding and copies no
Surge source, tables, algorithm lists, or preset payloads into this
repository. No preset payloads are committed: graph lines reference corpus
entries by census path + blob sha only. Upstream functions cited above were
read in the pinned tree to document mappings; where the engine exposes
names, they are queried live at runtime rather than embedded here.
