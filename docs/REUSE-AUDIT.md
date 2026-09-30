# Reusable substrate survey

Audit date: **2026-09-19**. Input to the adoption decision owned by
[#25](https://github.com/2AMLogic/gf180-surge/issues/25). This is a
**survey-level audit**: repository listings and the named files were
inspected in local checkouts; no sibling test suite, bench, or flow was
rerun, and no implementation is vendored by this document. Each adopting
issue must re-pin and verify what it actually uses.

Method and precedent: the TorchSynth reuse audit
([docs/REUSE-AUDIT.md](https://github.com/2AMLogic/gf180-torchsynth/blob/6532ec08eee7c79fd642f95d77bc086507a05f79/docs/REUSE-AUDIT.md))
established this organization's bar — pinned identities, explicit
adapt/reject decisions, negative findings, and a separate governance issue.
This survey applies that bar at planning depth.

## Source boundary and identity

Default-branch states as of this audit (local `origin/main` or API); adopters
re-pin at adoption time.

| Key | Repository | Audited commit | Declared license |
|---|---|---|---|
| P | [`2AMLogic/gf180-parasynth`](https://github.com/2AMLogic/gf180-parasynth) | `cbcc8b9e10e49c84f630550e2e145cc6da8a659c` | Apache-2.0 |
| Y | [`2AMLogic/gf180-torchsynth`](https://github.com/2AMLogic/gf180-torchsynth) | `6532ec08eee7c79fd642f95d77bc086507a05f79` | Apache-2.0 |
| D | [`2AMLogic/gf180-dx7`](https://github.com/2AMLogic/gf180-dx7) | `e8615a765e7c1c583eccbafab8bc1a89aa23606c` | Apache-2.0 |
| K | [`2AMLogic/klayout-tools`](https://github.com/2AMLogic/klayout-tools) | `d5893304afc2bfa6228609740e83292c44b854f3` | MIT |
| S1 | `turian/surge-python-demo` (user-owned, local) | not pinned | **GPL-3.0** |
| S2 | `turian/surge-python` (user-owned, local) | not pinned | **GPL** |
| S3 | `turian/surge-python-docker` (user-owned, local) | not pinned | Apache-2.0 |
| S4 | `turian/random-surgepy-patch` (user-owned, local) | not pinned | **none** |

The pinned Surge engine itself
(`surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`,
GPL-3.0-or-later) is the **reference**, not substrate; it lives outside this
Apache-2.0 repository by the license rule in `AGENTS.md`.

## Standing rules carried into every row

- **Sibling DSP is rejected on principle** (voice models, drum models,
  envelope/oscillator/filter/ROM arithmetic, measurement rubrics). The only
  DSP oracle for this instrument is the pinned Surge engine (plan section 4).
- Sibling evidence and tooling never transfer qualification: a Parasynth
  bench result or TorchSynth estimator says nothing about Surge fidelity.
- Nothing is adopted without a recorded decision in #25; adoption pins
  sources, adapts interfaces, and retains attribution and license notices.

## Verification and evidence apparatus

| Candidate (source, license) | What it is | Recommendation |
|---|---|---|
| TorchSynth apparatus contracts: `spec/VOICE-CONTRACT.md`, `CORPUS-RUNNER.md`, `DIRECTED-FIXTURES.md`, `TRACE-CAPTURE.md`, `TRACE-ARTIFACTS.md`, `PAIRED-METRICS.md`, `SCORECARD-CONTRACT.md`, `ARTIFACT-STORAGE.md`, `decision-records/` (Y @ `6532ec08`, Apache-2.0) | Written contract method: pinned fixtures, artifact hashing, coverage-vs-agreement separation, PASS/FAIL/NOT_RUN vocabulary | **Adapt the method**, already reflected in our leaf-issue template; consult when writing `contracts/` (SXT-012/013, SXT-029). Not code. |
| TorchSynth tools: `render_reference.py`, `render_corpus.py`, `generate_directed_fixtures.py`, `capture_float_sources.py`, `compare_control_path.py`, `qualify_*.py`, `check_contract.py` (Y, Apache-2.0) | Renderer/fixture/comparator harness patterns for float→fixed→RTL pipelines | **Adapt patterns per issue**; any copied file goes through #25 with tests. Their estimators were themselves flagged with gaps in Y's own audit — re-derive, don't inherit tolerances. |
| Parasynth process runner + tests: `tools/run_all.py`, `tools/test_run_all.py` (P @ `cbcc8b9`, Apache-2.0) | Shell → per-command state, timeouts, bounded 0/1/2 exit; Y's audit reran **18/18 tests green** | **Adopt-candidate** when this repo has multi-command evidence runs (SXT-012+). Copy pinned with tests via #25. |
| Parasynth provenance/refusal + scorecard: `tools/run_case.py`, `tools/scorecard.py` (P, Apache-2.0) | Commit/input provenance, `allow_stale` refusal, pass/fail/no-verdict/not-run reporting | **Adapt concepts** (SXT-015/029). Y's audit found concrete gaps: truncated hashes, NaN-tolerance pass-through, no STALE state — fix those classes locally, don't inherit them. |
| Parasynth repeatability/profile: `tools/measure_repeatability.py`, `refprofile.py`, `refaudio_fetch.py` (P, Apache-2.0) | Reference-audio fetch, repeatability measurement discipline | **Adapt pattern** for SXT-012 reference-vs-reference repeatability. |

## Transport, control, and board

| Candidate (source, license) | What it is | Recommendation |
|---|---|---|
| Parasynth SPI control link: `rtl-sketch/spi_ctl.v` + bench/verifier, DR 0007 (`spec/decision-records/0007-control-interface-spi-register-writes.md`) (P, Apache-2.0) | Mode-0 SPI, CS-framed `{CTL,A,D}`, write queue, status MISO | **Adapt as transport starting point** for SXT-021 only after this instrument's register/event protocol is decided (with DX7 H03, `gf180-dx7#25`, as the shared seam). Recompute CDC/overflow bounds at our rates; reject their register map. |
| Parasynth I2S serializer: `rtl-sketch/i2s_tx.v` + benches; Polysynth variant documented in Y's audit (P/Y, Apache-2.0) | 48 kHz stereo I2S output framing | **Adapt** for SXT-030 output stage after width/handshake/reset decisions; requalify at our exact clocking. |
| Parasynth FPGA bring-up: `fpga/rtl/ulx3s_top.v`, `fpga/boards/ulx3s.lpf`, `fpga/spi_host.py` (cocotb), `fpga/link_budget.py`, `fpga/scripts/pll_search.py` (P, Apache-2.0) | Board wrappers, host SPI, link budget, ECP5 divider search | **Adapt after board selection** (SXT-030). Y's audit cautions: vendor-derived pin attribution unresolved, board wrappers rejected for verbatim copying; regenerate constraints against the chosen board and measure before claiming playback. |
| DX7 shared seams (D, Apache-2.0): issues `gf180-dx7#25` (H03 interface/schedule), `gf180-dx7#29` (H07 integrated core), `gf180-dx7#30` (H08 pin-level), `gf180-dx7#31` (H09 FPGA capture) | The declared sibling for event transport, audio output, external-memory arbitration, verification tooling (plan section 7) | **Co-design** these seams rather than importing; keep both instruments' declared routing/gain independent. |

## Listening and audition

| Candidate (source, license) | What it is | Recommendation |
|---|---|---|
| Parasynth audition harness: `audition/render.py`, `play.py`, `rt.py`, `listen.sh`, A/B scripts (`ladder_ab.py`, `filter_ab.py`) (P, Apache-2.0) | Continuous-audio render/listen/A-B infrastructure | **Adapt** for SXT-013 listening sets and later effect A/B ablations (SXT-014); interfaces adapted to corpus/FXP workflow. This is transport/plumbing, not DSP. |
| TorchSynth explorer contracts: `spec/EXPLORER-MVP.md`, `EXPLORER-SESSION.md`, `EXPLORER-FAVORITES.md`; DX7 `gf180-dx7#34`/`#35` (U01/U02) (Apache-2.0) | Audition/save/favorites session method, reviewed listening bank | **Adapt the method** for the 32→256 favorites pipeline; DX7 is the sibling listening procedure. |

## ASIC flow

| Candidate (source, license) | What it is | Recommendation |
|---|---|---|
| `klayout-tools` (`klt`) (K @ `d589330`, MIT) | Organization's ASIC-flow interface: structured synth/P&R requests, tool/PDK provenance | **Use as the flow interface** when ASIC work begins (SXT-016/031), per the TorchSynth convention. Pin a dependency, record provenance, report friction upstream. MIT attribution preserved. |
| Parasynth flow evidence: `pnr/klt/ladder_dp/*` requests/logs, `pnr/orfs/evidence/*` reports, `docs/pnr-synth-top.md` (P, Apache-2.0; ORFS-derived techmaps' original terms unresolved) | A placed-and-routed gf180mcu chip's evidence bundle and its honest limits (no LVS/signoff) | **Checklist only**: use as the format example for SXT-031 evidence contents. Reject verbatim wrapper/techmap copying; ORFS attribution must be traced before any copy. |

## Surge-specific prior art (user-owned)

| Candidate (license) | What it is | Recommendation |
|---|---|---|
| `surge-python-demo` (S1, **GPL-3.0**) | surgepy preset loading/rendering experiments, FXP handling, API-capability notes | **Do not copy into this repo** (GPL). Consult as external prior art for SXT-010 oracle automation; API-usage knowledge is not copyrightable, code is. |
| `surge-python` (S2, **GPL**) | surgepy packaging/automation | Same as S1. |
| `surge-python-docker` (S3, **Apache-2.0**) | Dockerized surgepy runner, example/random-patch scripts | **Adopt-candidate with attribution** via #25 if its scripts fit the SXT-010 harness; verify content and keep the Apache notice. |
| `random-surgepy-patch` (S4, **no license**) | surgepy parameter metadata gathering, randomization | No license = no adoption right. Owner may license it in #25's decision; otherwise use as prior art only. |
| Parasynth Surge mapping prior art: `docs/surge-waveform-mapping.txt`, `model/reference_rigs.py` (P, Apache-2.0; fixed by Parasynth PR #87) | Documented pitfalls mapping Surge waveforms in an external rig | **Read before SXT-011/SXT-022**; their conclusions inform our native-normalization tests but do not substitute for them. |

## Negative findings

- **No sibling DSP of any kind is adopted** — including "just the envelope
  structure" or table formats. Surge's own implementations at the pinned
  commit are the only algorithm authority (plan section 4; TorchSynth's audit
  reached the same rejection for its target).
- **Sibling PASS/FAIL states, scorecards, and placed-and-routed results do
  not transfer.** They evidence the sibling instrument at its pinned commit.
- The user's surgepy scripts are unplanned exploratory code: none was rerun
  here, none is pinned, and only the Apache-2.0 one is even eligible for
  adoption.
- Parasynth's ORFS techmaps carry unresolved upstream attribution; that
  blocks copying independent of Apache-2.0 repo declaration.

## Adoption mechanics (owned by #25)

1. Adopting issue opens with the exact files/lines, source commit re-pinned,
   license/notice file, and the local adaptation.
2. Copied code lands with its tests and gains at least one local negative
   control that fails when the substrate is misused.
3. Divergence from the source is recorded in the adopting PR.
4. Any GPL/Surge-derived artifact requires a license decision record before
   merge (see `AGENTS.md`).
5. The adopted file gets a row in
   [`decision-records/provenance.json`](../decision-records/provenance.json)
   naming its class, upstream source, re-pinned commit, upstream license and
   decision record. `python3 tools/check_provenance.py` fails on a file that
   carries a third-party carriage signal without such a row, on a stale or
   uncorroborated row, and on a decision record missing from the index;
   `--negative-control` proves each of its rules still fires. Both run in CI
   (job `provenance-audit`). The tool enforces bookkeeping — read its
   `--limits` output before quoting a PASS as evidence: it is not proof that
   nothing was copied.

Recorded decisions live in [`decision-records/`](../decision-records/);
[0001](../decision-records/0001-oracle-automation-source.md) (oracle
automation source policy, SXT-010) is the first.
