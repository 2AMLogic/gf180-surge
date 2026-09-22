# DR-0005 — Oracle tap instrumentation for the SXT-037 filter leaf

- **Status:** Accepted (leaf-scoped)
- **Date:** 2026-09-22
- **Decides:** how the LP 12 dB filter leaf obtains filter-stage reference
  evidence from the pinned engine, given that the voice filter is an
  internal per-voice stage with no surgepy exposure.

## Context

SXT-024 bridged an exposure gap without touching the engine (reverb
lowcut/highcut deactivated flags read from the raw `.fxp` XML). The LP 12 dB
leaf (#71) needs the filter unit's **input and output signals** plus its
**per-block coefficient plane** on real carrier presets. No surgepy API
exposes these; no equivalence render can reconstruct them (the surrounding
voice chain — lowcut, pan, mix ramps, feedback routing — is outside the
leaf's scope and preset-dependent).

## Decision

1. The pinned engine tree is instrumented **externally, on the oracle
   host**, on a local branch `sxt037-tap` of the pinned checkout. The
   instrumentation adds:
   - a read-only tap sink (`sxt037_tap.h`) enabled only when the
     environment variable `SXT037_TAP_DIR` is set;
   - two calls in `SurgeVoice.cpp` that dump each LP12 unit's
     `(cutoff, reso, FirstRun, type, subtype, C[8], dC[8])` around the
     engine's own `MakeCoeffs` calls;
   - two kernel-pointer wraps in `SurgeSynthesizer.cpp` that write, per OS
     sample and active SIMD lane, the LP12 unit's input and output floats.
2. **No GPL-derived code enters this repository.** The patch script and the
   patched tree stay on the oracle host. This record pins their hashes;
   the repository stores method prose only.
3. **DSP neutrality is an enforced gate, not an assumption:** every render
   is performed twice in the same patched build (taps enabled vs
   environment unset) and the tool REFUSES unless the two WAVs are
   bit-identical. The patched build is additionally cross-checked against
   pre-patch committed reference renders (bit-identical sha).
4. The tap is **observation-only**: it changes no arithmetic, no branch,
   and no data path; it adds file writes on the oracle host only.
5. Record hashes (SHA-256):
   - patch script `~/oracle/sxt037_tap_patch.py` (final revision):
     `0712926beb62651e50f3e5ccd39cec0586e20244077f25b6427ff1ce0a5cfbad`
   - generated header `src/common/sxt037_tap.h` (in the external tree): a
     deterministic output of the pinned script revision; its content sha is
     pinned on the oracle host next to the script. The resulting engine
     build is pinned here by the version string the engine itself reports in
     every committed `reports/sxt-037/artifacts/bundle-*/meta.json`:
     `1.4.sxt037-tap.ff8b4dba4` (single commit on top of the engine pin).

## Outcome (evidence)

- Same-host, same-toolchain neutrality: the patched build renders Attacky
  `seq-notes-repeated-v1` dry **bit-identically** to a fresh unpatched-source
  rebuild (both `e86f79af0a2a1afb…`); tapped-vs-untapped same-build renders
  are bit-identical on the deterministic preset (`bundle-attacky-neutrality`).
- Mac-vs-box render shas differ (`9966433b…` vs `e86f79af…`) — cross-platform
  codegen variance of the pinned source, documented here to pre-empt
  misreading it as a tap effect.

## Alternatives rejected

- **Differential renders through `setParamVal` (filter Off):** requires
  modeling the downstream chain (scene lowcut is active on two of the three
  carriers — a different filter type outside this leaf) and inverts a
  nonlinear path for Driven carriers; unsound.
- **Full voice models of the carriers:** that is SXT-026a/#48 (second voice
  slice); it would expand this leaf's scope far beyond one filter algorithm
  and duplicate #48.
- **Synthetic oscillator drives instead of real presets:** violates the
  leaf's "real normalized corpus entries" fixture requirement.

## Consequences

- Reference legs compare the leaf model against the engine **at the exact
  leaf boundary** (filter-unit in/out + coefficient plane), keeping the
  leaf scoped to "one algorithm per leaf".
- Evidence renders are only reproducible on the oracle host with the
  patched build; `tools/render_lp12_reference.py` fails closed (exit 3)
  elsewhere, and every artifact embeds the patch marker and neutrality
  proof.
- The pin rule (engine HEAD == pinned commit) is enforced by the patch
  script; the patched branch is a single commit on top of the pin.
