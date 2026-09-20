# Reproducible preliminary Surge XT preset census

Source pin: `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`.

This package supports the companion chip plan. It is a **static inventory**, not a
native Surge loader, sound-quality test, supported-patch list, or silicon estimate.
Effects are part of the proposed chip's implementation ladder and wet-preset
acceptance goal; the inventory alone does not qualify any effect implementation.

## Included files

- `census.py`: Python 3 standard-library census; no third-party packages needed.
- `corpus-manifest.json`: all 3,561 bundled FXP paths, Git blob SHA-1 identities, and sizes.
- `source-lock.json`: upstream commit, archive URL, and submodule pins.
- `results/summary.json`: aggregate results and explicit limitations/failure records.
- `results/per-preset.csv`: one row per manifest entry, including unresolved entries.

The companion contract and implementation ladder live at
[docs/surge-xt-chip-plan-v0.1-2026-09-20.md](../../docs/surge-xt-chip-plan-v0.1-2026-09-20.md).

No upstream preset payloads, wavetables, source archive, or rendered audio are
included. Input FXP sizes are file/container sizes, not chip-memory estimates.

## Reproduce

From this directory, obtain the exact upstream archive (approximately 349 MiB):

```sh
curl -fL https://codeload.github.com/surge-synthesizer/surge/tar.gz/58914e59c608ed4384ba6002e44c3465c58b2e71 -o surge-source.tar.gz
python3 census.py surge-source.tar.gz --out reproduced
diff -u results/summary.json reproduced/summary.json
```

The script reads archive members without extracting paths. Each preset must match
the manifest's size and Git blob identity before it is analyzed; missing,
duplicate, or changed inputs fail the run. A parser failure remains a result row
and part of the corpus denominator. One such failure is expected in this version:
`resources/data/patches_factory/Percussion/Snare Tight.fxp`, whose stored XML has a
character reference rejected by Python ElementTree. This does not establish that
Surge cannot play it.

The source archive does not include the contents of Git submodules. It is enough
for this inventory, but a native Surge build needs the pinned submodules and the
upstream build requirements. Use `source-lock.json` and upstream instructions for
that next milestone.

## Interpretation

The two denominators are 641 presets in `patches_factory` and 2,920 in
`patches_3rdparty`. Both are bundled; the second is not an unrelated downloaded
sound pack. Test-data presets are excluded. Output paths and hashes are the
stable identifiers; similarly named presets are not merged.

`conditional_oscillator_*` fields follow selected processing branches in the
pinned `src/common/dsp/SurgeVoice.cpp`, including required FM/ring-modulation
sources and scene selection. They use **stored** controls. The native patch loader
and legacy migrations have not run. Screens ending in `_oscillator_screen` only
mean that this analysis did not encounter an oscillator family outside the
specified allowlist. They do not establish playable compatibility, submode
support, or coverage of the rest of the graph.

`stored_nonoff_fx_*` fields count configured non-Off slots across the stored patch,
including slots that may be inactive, bypassed, or inaudible. They do not identify
which effects are essential to the sound. Type names use the pinned source enum;
native normalization and per-algorithm analysis are still required. A configured
Airwindows type, for example, is not one uniform small effect implementation.

The script does not prune zero-level paths, infer dynamic modulation reachability,
interpret historical filter IDs as current algorithms, infer Lua usage from tag
presence, render audio, or measure hardware cost. Wavetable byte fields include
all stored scenes and are not a runtime residency estimate. Route counts include
all stored parameter routes and are not an active modulation-work estimate.

Next step: build the native reference, normalize the complete corpus, then render
and audition original wet presets and diagnostic ablations before freezing the
hardware feature profile.
