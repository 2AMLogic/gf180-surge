# Decision records

Numbered, one-decision-per-file records in the style of
`2AMLogic/gf180-parasynth` `spec/decision-records/` (Status / Context /
Decision / Consequences). **What belongs here:** every visible license
decision (anything GPL-, Surge-, or third-party-derived that touches this
Apache-2.0 repository — `AGENTS.md` requires such a record before merge),
every substrate adoption/rejection decision made under the reuse-audit
process (`docs/REUSE-AUDIT.md`, governance issue
[#25](https://github.com/2AMLogic/gf180-surge/issues/25)), and every visible
contract revision. Survey evidence recommends; only a record here installs.
Use the next unused number, never reuse or renumber; a superseded record
stays and is marked in its Status line.

**Machine-checked bookkeeping.** [`provenance.json`](provenance.json) carries
one row per in-repo file that holds third-party-derived content (or whose
build/run boundary touches the pinned GPL trees), each naming its upstream
source, re-pinned commit, upstream license and the record that authorizes it.
`python3 tools/check_provenance.py` fails when a record on disk is missing
from the index below, when a status keyword or date drifts from the record,
when a citation names a record that does not exist, when a provenance row is
stale or uncorroborated by its file, and when a file carries a third-party
carriage signal (foreign license text, upstream asset payload,
foreign-language source, self-declared quotation) with no row.
`--negative-control` demonstrates that every one of those rules still fires;
both run in CI. A PASS is bookkeeping, not proof that nothing was copied, and
never a ratification — each record's own Status line is authoritative.

## Index

| Number | Title | Status | Date |
|---|---|---|---|
| [0001](0001-oracle-automation-source.md) | Oracle automation source policy (SXT-010) | ratified | 2026-09-19 |
| [0002](0002-halfband-coefficients.md) | Halfband decimator coefficient constants (SXT-022) | ratified | 2026-09-20 |
| [0003](0003-reverb1-delay-time-tables.md) | Reverb1 DELAY_TIME_TABLES constants (SXT-024) | PROPOSED — pending owner ratification | 2026-09-20 |
| [0004](0004-wavetable-asset-boundary.md) | Wavetable asset boundary + mip halfband constants (SXT-026) | PROPOSED — pending owner ratification | 2026-09-21 |
| [0005](0005-oracle-tap-instrumentation.md) | Oracle tap instrumentation for the filter leaves (SXT-037) | Accepted (leaf-scoped) | 2026-09-22 |
| [0006](0006-airwindows-galactic-constants-and-taps.md) | Airwindows "Galactic" delay-length constants + oracle taps (SXT-028a) | PROPOSED — pending owner ratification | 2026-09-22 |
| [0007](0007-chorus-constant-inventory.md) | Chorus constant inventory — no opaque designed constants (SXT-028c) | PROPOSED — pending owner ratification | 2026-09-23 |
| [0008](0008-sine-wave-remap-table.md) | Sine wave_remap streaming-migration table (SXT-040) | PROPOSED — pending owner ratification | 2026-09-24 |
| [0009](0009-pinned-kernel-reference-harness.md) | Pinned-kernel reference harness for the SXT-039 filter leaf | PROPOSED — pending owner ratification | 2026-09-25 |
| [0010](0010-lp24-pinned-kernel-harness.md) | LP 24 dB pinned-kernel reference harness (SXT-038) | PROPOSED — pending owner ratification | 2026-09-25 |
| [0011](0011-profile-v1-budget-escalation.md) | Profile v1 cannot be frozen at the plan-section-3 budgets (SXT-017) | ESCALATED — pending product-owner decision | 2026-09-25 |
| [0012](0012-distortion-halfband-and-waveshaper-tables.md) | Distortion halfband coefficients (order 6) and waveshaper table provenance (SXT-028e) | PROPOSED — pending owner ratification | 2026-09-25 |
| [0013](0013-fx-modulation-rng-stream.md) | FX modulation RNG streams cannot be pinned: RNG-driven effect shapes excluded, coverage reduction published (#122 → SXT-017) | RECORDED CONTRACT REVISION — owner ratification pending | 2026-09-26 |
| [0014](0014-distortion-sse-quad-waveshaper-constants.md) | Distortion SSE quad-waveshaper constant inventory (SXT-028e-sse) | PROPOSED — pending owner ratification | 2026-09-26 |
| [0015](0015-airwindows-logical-quoted-constants.md) | Airwindows "Logical" (id 4) quoted constants, and the MIT licence of the vendored `libs/airwindows` subtree (SXT-028k) | PROPOSED — pending owner ratification | 2026-09-26 |
| [0016](0016-int16-tail-shape-leg-floor.md) | Tail-shape leg keeps one declared floor (−100.0 dBFS) for every bus; the int16 quantization-dominated regime is documented, not floored away (#160 → SXT-017) | RECORDED — pilot-freeze input, owner ratification pending; F-E disposed of by [0017](0017-int16-wet-tail-shape-grading-fixture.md) | 2026-09-27 |
| [0017](0017-int16-wet-tail-shape-grading-fixture.md) | int16 wet tail-SHAPE leg grades on a designated committed fixture clear of the quantization band; F-E fixture-side arm taken, bus-side arm rejected (#187 → SXT-017) | RECORDED — pilot-freeze input, amends 0016, owner ratification pending | 2026-09-27 |
| [0018](0018-wavetable-scene-decimation-placement.md) | The SXT-026 wavetable decimator and master stage move to a per-SCENE stage, and RTL coverage extends to the 48 kHz output (#180 → SXT-017) | RECORDED CONTRACT REVISION — owner ratification pending | 2026-09-28 |
