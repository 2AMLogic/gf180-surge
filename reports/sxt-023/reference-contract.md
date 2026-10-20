# SXT-023 / issue #507: Delay reference contract and qualification report

Dated 2026-10-20. Tree: `main` @ `5214cd0` (worktree `feature/issue-507`).
Docs/evidence only. No model, RTL, tool, fixture, budget, manifest, or
decision-record file is changed; `EVIDENCE.md` (sha256-pinned) is not edited.
This report does **not** freeze profile v1, close #16 or #12, or ratify
anything. Decision-record Status fields are untouched; ratification of this
contract is left to normal PR review.

Claim scope: Delay model-vs-reference (claim 2) for the committed `metallic`
and `dexie` fixtures against their exact pinned reference, and the status of
the RTL-vs-model (claim 1) receipts. Claim 3 (musical quality) is not
addressed. No preset-support, synthesis, timing, area, power, or hardware
claim.

Statuses use PASS / FAIL / NOT_RUN / BLOCKED / NO_VERDICT / STALE.

## 1. The canonical Delay reference

The canonical reference is **the recorded build that rendered the committed
fixtures**, not "Darwin/ARM" in general.

### 1.1 Pinned identities (each traced to a committed file)

| identity | value | source |
|---|---|---|
| engine | `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`, version string `1.4.HEAD.58914e59c` | `oracle/manifest.json` `engine`; fixture sidecars `.engine` |
| submodules | 22 + 5 nested, each commit listed | `oracle/manifest.json` `submodules`, `nested_submodules_observed` |
| rate / block / tempo | 48000 Hz, block 32, 120 BPM, ppq 0 | manifest `runtime`; sidecars `.engine`, `.render` |
| reset / settle | `allNotesOff()` before load, `loadPatch` into a fresh patch; settle 0.25 s = `int(0.25*48000)//32` = **375** silent blocks; tail 2.5 s; 273,600 frames | manifest `runtime.reset_policy`; sidecars `.render`; `delay-dt-probe.md` §1 |
| render module | `surgepy.cpython-311-darwin.so` (arm64) | sidecars `.engine.surgepy_module` |
| build recipe | Release, Ninja, `cmake ... -DPYBIND11_FINDPYTHON=OFF`, python 3.11.16 / numpy 1.26.4 | manifest `build`, `environment` |
| toolchain | macOS 26.5.1 arm64, Xcode 26.6, Apple clang 21.0.0 (clang-2100.1.1.101), cmake 4.4.3, ninja 1.11.1 | manifest `environment` |
| determinism | 3 repeats, bit-identical, per fixture | sidecars `.determinism_gate` |
| presets | `Plucks/Metallic.fxp` census blob sha1 `75383658c7c448f140a7e3c08ccd4e50a1ab0de0`; `John Valentine/Keys/Dexie Swirly E-Piano.fxp` blob sha1 `1dafae1015ad5f455702eef36f44049670195125` | sidecars `.preset` |
| sequence | `seq-notes-coverage-v1`, sha256 `f819f9ac...c03016` | sidecars `.sequence` |
| metallic dry / wet sha256 | `f2183ef0...14158d20b` / `3131dfca...cc10b397` | sidecar; re-derived live (below) |
| dexie dry / wet sha256 | `e8e9e3da...c6c44fb` / `7065d58d...a20aa` | sidecar; re-derived live (below) |

Live re-derivation (2026-10-20, `sha256sum` of the committed WAVs): all four
Delay fixture WAVs and the two `fm_bass_1` WAVs equal their sidecar hashes
(**PASS**, hash equality only).

### 1.2 Identities that are MISSING (reported, not filled in)

1. **sha256 of the Darwin `surgepy.cpython-311-darwin.so` that rendered the
   fixtures.** Not in the manifest, sidecars, or any record. The manifest
   describes the build recipe, not a binary hash, and no reproducible-build
   check against the fixtures exists.
2. **Compiler floating-point flags of that build** (`-ffp-contract`,
   `-ffast-math`, `-mcpu`, CMake `CXX_FLAGS` as realised). The manifest
   records Release + Apple clang version only. The Delay lag's fused
   evaluation on Darwin is therefore an *inference* from audio agreement
   (section 2), not a recorded setting. The clang manual
   (<https://clang.llvm.org/docs/UsersManual.html#controlling-floating-point-behavior>,
   first 100k characters read) says `-ffp-contract=on` (fusion within a
   statement) is the default for languages other than CUDA/HIP; `off`
   disables fusion. That documents what the compiler is *permitted* to do; it
   does not prove what this binary did.
3. **A d(t) probe against the Darwin binary.** `tools/probe_delay_dt_engine.py`
   has only ever been run on the Linux x86_64 build (see 1.3). The Darwin
   trajectory is not directly measured.
4. **Linux prebuilt vs probe-host module mismatch.** The manifest's
   `prebuilt.linux-x86_64` is a cpython-3.11.16 artifact (tarball sha256
   `d2cc7029...b777f571`). The d(t) probe records
   `surgepy.cpython-313-x86_64-linux-gnu.so`, sha256
   `e72b5ed2768273d0b8c9c7515c23da6a1d06928a62a8311ec0c82cbd4c421e17`,
   python 3.13.16. These are different module builds; the probe's module is
   not described by any manifest entry. Its compiler/flags are likewise
   unrecorded.
5. **Fixture `tool.script_sha256`** (`b9b8f2b6...b185cdfe`) matches
   `fixtures/render_fixture.py` at `44c88b1` but not the current file
   (`13c3c77...`). Per `docs/byte-frozen-sources.md` this is a historical
   provenance stamp, not a live pin; it is not asserted live here.

### 1.3 Linux/x86 finding (kept separate)

The d(t) probe (`reports/sxt-023/artifacts-followup/dt-probe/dt-probe-{metallic,dexie}.json`,
3x bit-identical renders each, `REPLAY_CHECK_DB` = -40 dB) ran on the Linux
x86_64 build above. Recorded results for the frozen model (`revised`,
fused lag) against that engine:

| fixture / instance | revised (fused) | revised_unfused_lag | linux_x86_semantics |
|---|---|---|---|
| metallic ains1 (preset depth) L/R | FAIL (-31.2 / -31.4 dB) | PASS L / PASS R | PASS |
| metallic send1 (24,000-sample delay) L/R | **FAIL** (dv max 5.93 samples) | FAIL (dv 0.051, -21.2 dB) | PASS (dv 0.022) |
| dexie ains1 (preset depth) L/R | PASS (-40.9 / -40.1 dB) | PASS | PASS |
| depth-0 controls (metallic, dexie) | FAIL | PASS | PASS |

This is a **reference-vs-reference platform variance finding**, preserved as
is. It is not a model defect and not a pass for the Linux build.

## 2. Model-vs-reference claim (claim 2) — scope

The claim is exactly: *the frozen Delay model reproduces the committed
`metallic` and `dexie` wet fixtures, rendered by the recorded Darwin build,
within the declared budgets.* Re-run today (model WAVs and fixtures
unchanged, `tools/compare_fx_reference.py --per-channel-budgets`, current
comparator including the #439/#452 validity checks):

| fixture | verdict | notes |
|---|---|---|
| metallic | PASS (PENDING-FREEZE budgets) | tail gate ok; mono tail residual -77.4 dB |
| dexie | PASS | tail gate ok |
| fm_bass_1 (EQ regression) | PASS | |

Differences from the committed `audio-*.json` are last-ULP only (max relative
difference 3.4e-12 over the differing numeric leaves; verdicts and gate flags
identical). The committed records were not rewritten.

Limits that stay in force:

* Budgets (max 8,192 LSB, rms -46 dBFS, spectral_corr >= 0.98, tail -20 dB,
  per-channel legs) are the unchanged `[PROPOSED]` / PENDING-FREEZE values.
* Only two Delay parameterisations were measured. No claim for others.
* Control-plane float32 per-operation rounding of the LFO/target expressions
  is not mirrored (declared in `delay-dt-probe.md` §4).
* Agreement with the Darwin fixtures is the only direct evidence that the
  Darwin build uses the fused lag; see 1.2 item 2–3.
* The three claims stay separate: RTL-vs-model exactness (section 4),
  model-vs-reference (this section), and musical quality (no listening
  record; not claimed).

## 3. Substitute-reference qualification rule and finite check

Rule: a Linux or other build must pass the check below, against the canonical
fixtures' identities, **before** it generates any acceptance fixture. Until
then it generates diagnostics only. The reference is not switched per patch,
and committed baseline bytes are not replaced. A platform label (`darwin`,
`linux`, `arm64`, `x86_64`) does not establish arithmetic semantics.

Finite check (sourced from `tools/probe_delay_dt_engine.py`; no general
framework):

1. **Identity record.** Candidate engine commit and submodules equal the
   section 1.1 pins; record the candidate module sha256, python version,
   compiler id/version and the FP-relevant flags actually used (including
   `-ffp-contract` and any `-march`/`-mfma`). Missing items are reported as
   missing and the candidate is BLOCKED, not assumed.
2. **Paired inputs.** Same preset blob sha1s, same sequence sha256, same
   settle/block/rate as 1.1; report the dry-render sha256 of the candidate
   against the committed dry sha256 (a mismatch means the inputs differ and
   the check is NO_VERDICT).
3. **Repeats.** At least 3 renders per probe, bit-identical (the probe's
   existing gate).
4. **Trajectory.** Run the d(t) probe for `metallic` (both instances,
   including the 24,000-sample `send1`) and `dexie`; compare the candidate's
   per-pulse fitted v(t) against the frozen (fused) model replay. Pass bar:
   `dt_check` PASS (replay residual <= -40 dB) on every instance and channel
   for the fused variant.
5. **Audio.** Render the candidate wet bus and grade it against the committed
   wet fixture with `tools/compare_fx_reference.py --per-channel-budgets`;
   additionally require exact (or declared-tolerance, stated in advance)
   agreement of the candidate's dry bus with the committed dry hash.
6. **Defeating control.** The same procedure must be demonstrated to FAIL on
   the known mismatch: the recorded Linux x86_64 build (unfused lag) fails
   step 4 for the fused model on `metallic` `send1` (dv 5.93 samples,
   replay -> +3.7 dB) and on the depth-0 controls (table in 1.3). A
   qualification procedure that passes that build as equivalent is invalid.
   The probe's pre-revision model remains the second live negative control.
7. **Scope.** The result qualifies the candidate for these two fixtures'
   parameterisations only.

Status of the check on this tree: **NOT_RUN** for any substitute build. The
only recorded run is the Linux build's, which is the defeating control and
FAILS as required (**PASS as a control**, not as a qualification). Not rerun
here: no oracle is installed on this host (`ORACLE_SURGE_DIR` unset;
`surgepy*.so` not found), and fetching the prebuilt object store was not
required to define the check. A new live probe run needs a host with the
oracle provisioned.

## 4. #396 / SXT-023 receipt binding

Binding was checked by comparing the tree each record was produced from
(`c08841a`, 2026-10-09; the Verilator record names it) with `HEAD`.

| input | change since `c08841a` | consequence |
|---|---|---|
| `model/effects/delay/**`, `model/effects/qmath.py`, `model/effects/__init__.py` | none | model binding intact |
| `rtl/effects/tb_fx.sv`, `rtl/effects/fx_line_ext.sv` | none | RTL binding intact |
| `tools/run_fx_model.py`, `tools/probe_delay_dt_engine.py`, `tools/render_fx_fixtures.py`, `fixtures/render_fixture.py` | none | intact |
| `reports/sxt-023/fixtures/**` | none | intact (hashes re-derived above) |
| `reports/sxt-023/artifacts/*.json.gz`, `rtl/*.hex.gz` | bytes changed by `1cf1555` (gzip member names only) | decompressed content equals the `c08841a` content for all 9 files (sha256 compared): content binding intact |
| `tools/compare_fx_reference.py` | #439 non-finite refusal, strict JSON | verdict logic unchanged; record re-run today |
| `tools/compare_rtl_model_fx.py` | #452 window/coverage refusals | recorded runs predate it; **re-run today** |
| `oracle/` | `oracle_common.py`, `capture_first_note.py` (#436 binding selection) | does not affect committed fixtures; no oracle run is claimed |

Delay model, RTL and tools are not in the byte-frozen registry
(`docs/byte-frozen-sources.json` `live_pins`/`historical_provenance` list
neither), so binding above rests on git diff and content hashes, not on a
registry pin.

Receipt status (2026-10-20):

| receipt | status | basis |
|---|---|---|
| Delay model-vs-reference, metallic + dexie, darwin fixtures | PASS | re-run today (section 2) |
| EQ fm_bass_1 preservation | PASS | model-vs-reference re-run today; RTL leg: record only, EQ RTL not re-run (NOT_RUN today; inputs unchanged) |
| Delay RTL-vs-model, iverilog 13.0, full length (8,925 blocks incl. 375 settle; 8,550 compared) | PASS | re-run today on the current comparator: metallic 547,200 outputs / 272 checkpoints / 8,704 fields, 0 mismatches; dexie 547,200 / 136 / 4,352, 0 mismatches. Raw RTL trace sha256 equal the committed Verilator-record hashes (`643af13b...`, `56b0440e...`). `IVERILOG=/home/ubuntu/.local/bin/iverilog` (the tool defaults to `/opt/homebrew`). |
| Verilator full-length RTL-vs-model + sim-vs-sim | not re-run today (NOT_RUN); record `verilator-equivalence-issue16.json` bound to unchanged tb/model/trace content; the iverilog traces above are byte-equal to the Verilator record's hashes | no source change to inherit past |
| NC-a shared line | not re-run today (NOT_RUN); record `nc-a-followup-shared-line.json` predates comparator #452 changes | see below |
| NC-b nearest-neighbour model | NOT_RUN today; record in `followup.md`/`artifacts-followup/nc-b` | |
| NC-c max-feedback corner | NOT_RUN today; model-side only | |
| NC-d bypass | NOT_RUN today; record `nc-d-bypass-rerun-issue16.json` (model-side) | |
| NC-e comparator mutant | NOT_RUN today | |
| ext-mem counters | NOT_RUN today; `ext_mem_traffic-rerun-issue16.json` | covered by `tests/test_sxt023_delay_traffic_basis.py` PASS |

Negative controls were not re-run in this change. Their records are
historical PASS-as-control results whose inputs (model, tb, fixtures) are
unchanged; the comparator they used (`compare_rtl_model_fx.py`) has since
gained refusals, so they are **not inherited as current**: this report marks
them NOT_RUN and does not count them as fresh evidence. A reviewer who needs
them current should run them on a host with the simulators, which this host
has.

Targeted tests run today (`pytest`, single process, `LOOM_FORCE_SCOPE` and
`LOOM_GUARD_DECISION_LOG` unset): `tests/test_byte_frozen_sources.py`,
`tests/test_sxt023_delay_traffic_basis.py`,
`tests/test_compare_rtl_model_fx_window.py`,
`tests/test_frozen_artifact_basis.py`: **69 passed, PASS**.
No SPICE, no grids.

## 5. Corrections for reviewers (not applied here)

Prepared with provenance; none edited, since `EVIDENCE.md` is pinned and the
manifest is not wrong, only incomplete:

1. `oracle/manifest.json`: add the Darwin module sha256 and realised compiler
   flags **if** the original build host can supply them; otherwise leave them
   missing. Do not derive them from the Linux build.
2. `oracle/manifest.json` `prebuilt`: the d(t) probe's cpython-313 module
   (sha256 `e72b5ed2...c421e17`) has no manifest entry. Either add one with
   its provenance or stop citing it as the pinned prebuilt.
3. `delay-dt-probe.md` §3 says Verilator is NOT_RUN; superseded by
   `verilator-equivalence-issue16.json` (as `followup.md` already states).
   Preserve both; this report is the cross-reference.

## 6. Follow-through for #16 and #12 (stated, not performed)

* #16 can be reconciled against its remaining acceptance using this contract;
  profile v1 stays unfrozen.
* #12 still needs a qualified Delay result and an actual cost-closure rerun
  under the Oct 1 R-E ruling.
* Neither is closed or edited by this change.

## 7. What remains unproved

* Binary identity and FP flags of the Darwin reference (1.2).
* Any direct d(t) measurement of the Darwin reference.
* Qualification of any substitute build (section 3 is a specification;
  NOT_RUN).
* Current-tree negative controls (section 4, NOT_RUN).
* Delay behavior outside the two fixtures; preset support; musical quality;
  synthesis, timing, or hardware.
