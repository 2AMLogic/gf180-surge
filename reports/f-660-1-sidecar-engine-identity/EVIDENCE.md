# F-660-1 evidence record — reference sidecar engine identity

Issue: #671 (finding F-660-1, discovered in #660) · Date: 2026-11-14 ·
Decision: `decision-records/0021-reference-sidecar-engine-identity.md`

Engine (external, GPL-3.0-or-later):
`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, surgepy
`1.4.HEAD.58914e59c`, 48 kHz, block size 32 (`oracle/manifest.json`), via the
sha256-verified prebuilt artifact (`d2cc702913c4b2d4…`, linux-x86_64,
CPython 3.11.16 / numpy 1.26.4).

**Claim discipline.** This record advances reference-vs-reference evidence
bookkeeping only: what each committed render sidecar's `engine` block can and
cannot establish, and what the fixed producers record from now on. It
establishes **no** fidelity claim, **no** preset-support claim, **no**
musical-quality claim, and **no** claim that the `sxt037-tap` and stock
builds differ (or do not differ) in audio. No committed WAV, reference or
record was re-graded, relabelled or deleted; no committed sidecar was
re-rendered (decision-records/0021, decision 3).

## Statuses

| Check | Status |
|---|---|
| Acceptance item 1 — enumeration of inherited-`engine` sidecars | PASS (`artifacts/sidecar-inventory.json`; guard test live) |
| Acceptance item 2 — per-sidecar agreement verdicts | PASS — upgraded from unknown to measured: 13/13 committed WAVs reproduce byte-identically under the stock pinned oracle (`artifacts/confirmation-render.json`) |
| Acceptance item 3 — decision (option (a) at producers + recorded non-re-render) | PASS (`decision-records/0021`; split recorded visibly, not silently) |
| Failure control — producer under an engine whose `getVersion()` differs from its inputs file | PASS — red on `origin/main` @ `83bbc5a` producers (fresh sidecar carried only `{commit, version_string}`; `KeyError: 'engine_version_string'`), green after the fix (`tests/test_sidecar_engine_provenance.py`) |
| `tests/test_byte_frozen_sources.py` incl. both reworded prose mutants | PASS (28/28) |
| T1 item 9 re-attestation | see the PR; envelope re-derived in the same change |
| Tap-vs-stock audio equivalence | NO_VERDICT — out of scope, deliberately not claimed |

## Acceptance item 1 — enumeration

Method: every committed `reports/**/*.json` read; an `engine` object whose
keys all fall inside the extractor-inputs vocabulary `{commit, version_string,
block_size, sample_rate}` — i.e. with no field a live engine reading is known
to produce — is classified inherited-only. Machine-readable:
`artifacts/sidecar-inventory.json`. Live guard:
`tests/test_sidecar_engine_provenance.py::test_committed_reports_have_no_undeclared_inherited_only_engine_block`.

| Group | Count | Producer | Disposition |
|---|---|---|---|
| Pattern A render sidecars | 13 | `render_lfo_fixture.py` (4, sxt-032), `render_mw_fixture.py` (3, sxt-035), `render_slfo_fixture.py` (6, SXT-041) | the defect (F-660-1); producers fixed; committed records annotated, not re-rendered (DR-0021) |
| SXT-034 uni references | 5 | `render_uni_reference.py` — `version_string` was read live via `getVersion()` at write time, `commit` is a literal | not a Pattern A defect; shape cannot prove liveness; annotated; out of scope |
| sxt-037 bundle metas | 9 | DR-0005 tap extraction bundle describing its own run | not render sidecars; annotated; out of scope |

The issue body named two producers; the enumeration found the third
(`render_mw_fixture.py`) with the identical two-line copy. It is fixed here.

## Acceptance item 2 — agreement verdicts (measured, not inferred)

All 13 committed sidecar WAVs were re-rendered under the **stock** pinned
oracle with the fixed producers (3-repeat determinism gate green on every
render; scratch out-dirs; committed reports untouched): **13/13
byte-identical** to the committed `wav_sha256`
(`artifacts/confirmation-render.json`, which also records each fresh sidecar's
live `engine` block and inherited `inputs_engine` sibling).

- sxt-032 (4) and sxt-035 (3): the committed audio is byte-identical to the
  stock oracle's output for these presets. The tap strings their sidecars
  carried (`01b20d0b8`, `ff8b4dba4`) were not evidence of the rendering
  engine — that is now moot for the audio: whatever rendered it produces
  exactly what stock produces, on these dry fixtures. This is consistent
  with DR-0005's evidenced-neutral finding for the sxt037 tap on
  `seq-notes-repeated-v1`.
- SXT-041 (6): previously "probably agrees, not established by the sidecar"
  (inferred from the registry note). Now measured: byte-identical under
  stock.
- Byte-identity cannot distinguish "rendered by stock" from "rendered by a
  build that outputs the same bytes" — that residual is inherent to the
  method and is exactly why the sidecar now records the live engine instead
  of an inherited claim.

## Acceptance item 3 — the decision

Recorded in `decision-records/0021-reference-sidecar-engine-identity.md`:
option (a) at the producers (live `engine_identity()` + `inputs_engine`
sibling), with the 13 committed sidecars deliberately not re-rendered, stated
visibly. The alternative — re-rendering — was impossible for the 7
tap-attributed sidecars: `1.4.sxt037-tap.ff8b4dba4` is pinned only by the
version string it reports and DR-0005 keeps its patch script and generated
header on the oracle host, and **`1.4.sxt037-tap.01b20d0b8` has no recorded
identity anywhere in this repository** (`git grep 01b20d0b8
decision-records/` → nothing; bounded finding, adjacent to #565 and
#305/#307 — not this issue's to fix). Re-rendering the others on the stock
oracle would have been the relabel #671's stop/escalate forbids.

## The confirmation render — how it was run

```bash
oracle/fetch-and-build.sh --prebuilt   # sha256-verified prebuilt oracle
export ORACLE_SURGE_DIR=~/.cache/gf180-surge-oracle/58914e59c…/linux-x86_64
<oracle-venv>/bin/python fixtures/render_lfo_fixture.py \
    --sequence <seq> --out-dir /tmp/confirm671/lfo --repeats 3   # (mw, slfo likewise)
```

All 13 committed sidecar sequences re-rendered (4 lfo, 3 mw, 6 slfo incl.
both `--slfo-inputs` variants for the overlap sequence); no committed
`reports/` path written. The render output is retained in
`artifacts/confirmation-render.json`: per sidecar, the committed and fresh
WAV sha256 values with the byte-identity verdict, the fresh sidecar's live
`engine` block (`engine_version_string: 1.4.HEAD.58914e59c`,
`engine_commit: 58914e59c…`, `surgepy_module:
surgepy.cpython-311-x86_64-linux-gnu.so`) and its inherited
`inputs_engine` sibling, and the determinism-gate outcome. The raw fresh
sidecars are deliberately NOT committed: each one stamps its producer's
current `script_sha256`, and committing them would make the post-fix
producer digests resolvable through these artifacts — flipping the
`current_bytes_recorded` flags this change states as spent (DR-0021) and
breaking `test_historical_provenance_carries_no_live_equality_claim`,
which is exactly what that test caught in the attestation cold start. The
sidecars are reproducible from the committed producers plus the pinned
oracle.

## The failure control

`tests/test_sidecar_engine_provenance.py` compiles a tiny **original**
stand-in C extension named `surgepy` (explicitly not the Surge engine; the
`tests/test_oracle_binding_origin.py` pattern) whose `getVersion()` returns
`0.0.0.standin-not-surge`, generates an inputs file whose blob matches a
stand-in preset payload (so no oracle install is needed), and runs
`fixtures/render_slfo_fixture.py` — the only Pattern A producer whose inputs
path is a CLI flag — end-to-end. The sidecar must record the stand-in version
live under `engine` and the inherited value under `inputs_engine`. Agreement
and fast-variant edge cases are covered by the same mechanism. On the
pre-fix producers the control failed with `KeyError: 'engine_version_string'`
(the red leg of the TDD cycle, recorded here as evidence it bites).

## Registry / attestation ceremony

Editing `fixtures/render_slfo_fixture.py` spent its resolvable
`script_sha256` stamp (its SXT-041 records stamped the file as committed).
Same-change bookkeeping: registry flag flipped `false` with a disposition
stating the lost resolvability (the #126 precedent's alternative route),
`historical_provenance_note` and `docs/byte-frozen-sources.md` counts moved
(2 true/8 false → 1 true/9 false) and both prose mutants reworded so the
negative controls still fire, and the T1 item 9 envelope re-derived
(`tests/` changed). `fixtures/render_lfo_fixture.py` and
`render_mw_fixture.py` entries already read `false`; their edits move their
digests no further from resolvability.
