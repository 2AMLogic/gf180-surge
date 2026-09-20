# SXT-011 evidence record — normalized patch graphs

Branch: `loom/sxt-011-normalized-graphs` · Issue: #6 (SXT-011) · Date: 2026-09-20

Engine (external, GPL-3.0-or-later): `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
at `/Users/joseph/dev/surge-xt-oracle/surge` (SXT-010 layout), surgepy self-report
`1.4.HEAD.58914e59c`, 48 kHz. Exporter: `tools/export_normalized_graphs.py`.
Schema: `corpus/normalized/schema.json` (rev 1.0.0) + `corpus/normalized/README.md`.

**Claim discipline:** this work exports *normalized state data* only — loader
behavior after migration. It makes NO audio-support, fidelity, preset-quality,
resource, or hardware claim, and no listening record exists. Counts below are
data-coverage counts, not support claims.

## Headline result

- `corpus/normalized/graphs.jsonl`: **3,561 lines for 3,561 census entries**
  (641 factory + 2,920 contributor), every entry with an explicit status.
- Status counts: **normalized 3,561; analysis_failure 0.** Every line carries
  census path, bank, re-verified git blob SHA-1 + size, engine pin, and the
  normalized graph.
- Size: **17,841,829 bytes (~17.8 MB)** — under the 150 MB repo-size guard; no
  verbosity reduction tiers were needed.
- Determinism: a second full run into a scratch directory is **byte-identical**
  (`cmp` clean). No timestamps inside per-preset lines; run metadata lives in
  `export-summary.json` only.
- Loader migrations observed (recorded per entry in `g.mi`, evidence = raw
  stored id vs live normalized value):
  `filter_remap` 301 · `polylimit_default` 890 · `sine_shape_remap` 109 ·
  `ringmod_shape_remap` 2 · `osc_type_diff`/`fx_type_diff` 0.
- `Percussion/Snare Tight.fxp` (the static census's unresolved file): status
  **normalized natively** — FM3 oscillators, LP24/HP12 filters, Delay +
  Conditioner + Reverb 1, 31 modulation routes. Its raw XML remains unreadable
  (the same invalid character reference the static parser hit); the waiver is
  recorded in `g.raw_note` and the normalized state is complete without it.
- Raw-XML storage quirks are explicit data, not failures: 53 presets carry
  `g.rwu` (75 entries) of raw float bit-pattern values under int tags that are
  excluded from id comparison by a documented bound and never silently
  interpreted.

## Acceptance checklist (issue #6)

| # | Acceptance item | Status | Evidence |
|---|---|---|---|
| 1 | All 3,561 entries have a status; unknown behavior produces an explicit analysis failure, never a guess | **PASS** | `corpus/normalized/graphs.jsonl` — one compact JSON line per census entry in census-manifest order; `st` ∈ {normalized, analysis_failure}; failure lines carry `why:{phase, reason, detail}`. Failure paths exercised by construction: load_false/exception (load), extraction exception, validation violation, migration-compare exception — each is recorded, never guessed. 0 failures occurred in the committed run. |
| 2 | Loader migrations observable: filter remapping / Sine waveform changes normalize to current semantics, and the change is recorded | **PASS** | `g.mi` events with raw-vs-normalized values and pinned-source citations: 301 filter remaps (rev<15 Great Filter Remap, `fut_14` → current ids; e.g. `Kalimba Attempt.fxp` raw (6,4) → (23,1) 'BP 24 dB'/'Driven'), 109 sine shape remaps (rev<=27 remap plus the rev<=12 `SineOscillator::handleStreamingMismatches` wave_remap reset; e.g. `Funky Gate.fxp` raw 7 → normalized 0), 2 ringmod remaps, 890 polylimit defaults. Notes cite `SurgePatch.cpp load_xml` / `FilterConfiguration.h` / `SineOscillator.cpp`. |
| 3 | FX fields capture exact algorithm selection (incl. Airwindows algorithm IDs), slot routing, bypass, and send/return placement | **PASS** | All 16 engine FX slots exported per preset with role (`ains1..global4`), engine type id + display name, all 12 normalized param values, `on` state; Airwindows slots carry the exact algorithm id (`aw`) + engine algorithm name (`awn`), e.g. `Harmonic Blast.fxp`: aw 49 'Galactic' (global2), aw 5 'Mojo' (ains4). Routing: section bypass id `fxb` + `fxbn` (0='All FX'), per-slot disable bitmask `fxd`, send-slot `rl` return levels, per-scene `send` levels, and send/return modulation routes visible in `g.md` (e.g. slfo→'Send FX 1 Return' rows). Processing order (A1→A4, B1→B4, scene sum, S1..S4 with return_level, G1→G4) documented in schema/README from `SurgeSynthesizer::process`. |
| 4 | Spot-check: normalized state of ≥3 presets matches live native state queried through `surgepy` | **PASS** | `reports/sxt-011/spot-check/` — 5 presets (both banks): Sub 4 (factory, simple), Drum One (factory, rev 4 legacy filters), 10 Example - Both Time And Space (factory, DUAL scene, FX-heavy, Formula LFO), Amen Polska (contributor, embedded wavetables + Wavetable/Sine/FM2 + 18 routes), Harmonic Blast (contributor, 9 configured slots incl. 2 Airwindows). Per preset: full-graph canonical-JSON equality against a fresh-engine re-extraction **IDENTICAL**, plus 75–81 independent live surgepy getter checks per preset (getParamVal/getParamDisplay/getAllModRoutings vs committed fields) — **0 mismatches**, 5/5 PASS. Transcript: `spot-check/spot-check-transcript.txt`; machine summary: `spot-check/spot-check-summary.json`. |
| 5 | Negative control: a pre-migration numeric ID routed through without normalization must be detected as an analysis failure | **PASS** | `reports/sxt-011/negative-control/unnormalized_control.py` — builds the un-normalized graphs (raw ids exported as current state) for `Kalimba Attempt.fxp` (raw fut_14 (6,4) misread as 'BP 12 dB'/'Clean (Legacy)' vs live (23,1) 'BP 24 dB'/'Driven') and `Funky Gate.fxp` (raw sine 7 'Wave 8 (TX 8)' vs live 0 'Wave 1 (TX 1)'). Both are DETECTED by (1) live-equality vs a fresh native re-extraction and (2) the migration-consistency invariant (raw≠live with no recorded event). Had the exporter emitted such state, these layers gate the entry to `analysis_failure` (`schema_validation_failed`). Transcript + summary in the same directory. Honest scope note recorded there: plain range validation alone would NOT catch these (raw ids fall inside current numeric ranges) — the two operative layers are live-equality and migration-consistency. |

Additional evidence properties (not acceptance-gated):

- **Reproducibility:** `python3 tools/export_normalized_graphs.py --out DIR` then
  `cmp` against the committed file → byte-identical (executed twice).
- **Migration detection is value-based, not assumed:** events fire only when a
  raw stored id actually differs from the live normalized value; equal-value
  migrations (e.g. `Drum One.fxp` fut_14 comb 8 → comb_pos 8) are correctly
  silent. An early detector bug (key-name mismatch) hid 301 filter events from
  a first run; the committed run was regenerated after the fix and cross-checked
  against an independent corpus scan.
- **Harness finding recorded:** params not streamed from a preset (volume for
  rev<17, `fx_bypass` stripped from ALL presets, `character` for rev<10) inherit
  the engine's previous value; the exporter applies a declared reset policy
  (reset to engine defaults before each load) making graphs load-order
  independent. This is also a finding for SXT-012's reset-policy work.

## Method summary

1. Census manifest → per entry: blob SHA-1 + size re-verified (mismatch aborts).
2. Raw structural sidecar read (chunk layout per `census.py`; XML parameter
   names per `SurgePatch::save_xml`; int tags only — valtype attribute gate).
3. `SurgeSynthesizer::loadPatch` at 48 kHz through surgepy (the native loader
   with all migrations) after the declared reset policy + `allNotesOff`.
4. Normalized extraction via `getPatch`, `getParamVal/ValType/Display`,
   `getAllModRoutings` (normalized depths), mixer/LFO/filter/FX structures.
5. Validation against live-derived param ranges + structural counts + Airwindows
   id range; violations → analysis_failure (none occurred).
6. Targeted raw-vs-normalized migration comparison (evidence-based events only).
7. One compact deterministic JSON line per preset (`sort_keys`, 6-decimal
   floats, ensure_ascii, no NaN, flushed per line, `--start/--end` resume).

## Licensing / provenance

- `tools/export_normalized_graphs.py`, `reports/sxt-011/*` scripts: original to
  this repository (Apache-2.0 per `LICENSE`). They import the external GPL
  engine at runtime via surgepy and copy no Surge source, tables, assets, or
  preset payloads into this repository.
- `graphs.jsonl` contains only derived normalized state + census identities
  (paths, blob SHAs, sizes) — no preset payloads.
- Wavetable records reference engine-tree files by relative path + sha256;
  no asset bytes are committed. Display names queried live from the engine;
  upstream functions are cited in `corpus/normalized/README.md`, not copied.

## Explicitly NOT established by this work

- NO_VERDICT on sound fidelity, preset quality, or musical usefulness — no
  listening record exists.
- NOT_RUN: render fixtures (SXT-012), effects' contribution measurement
  (SXT-014), resource accounting (SXT-015), any RTL/model work.
- MSEG/Formula modulator **contents** are not exposed by surgepy; affected LFO
  records carry an explicit `gap` marker. This is the issue's stop/escalate
  note for that class: the curves themselves remain unexported, and any future
  need for them requires an instrumentation decision, not raw-XML guessing.
- Scene send buses 3/4 levels are not exposed by surgepy and not stored in
  `.fxp` files (loader defaults apply); documented gap in schema/README.
- "normalized 3,561/3,561" means the native loader produced fully extractable,
  validated state for every entry — it does not mean the presets sound
  anything, or that any feature is supported.
