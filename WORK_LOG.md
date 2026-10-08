# Work log

Recent merged pull requests and closed issues. Entries record forge events only; acceptance and claim limits remain in each committed evidence record. Initial history window: 2026-09-30 onward.

### 2026-10-08

- **PR #357**: docs: README Status points to generated DAG (#346)
- **PR #350**: ci: widen python-compile gate to all repository python
- **PR #349**: CI: add rtl-sim job with Icarus Verilog and simulator-skip gate
- **Issue #347** (closed): CI python-compile gate covers only tools and census; compiler, probes, fixtures, oracle, model, tests are uncompiled
- **Issue #346** (closed): README Status says Planning/only SXT-000 done while the generated board shows 14 PASS nodes
- **Issue #345** (closed): CI: iverilog-gated tests are silently skipped on the PR runner, so RTL-vs-model harness tests never run in CI

### 2026-10-07

- **PR #344**: audit(#318): live A/B/C settle-boundary measurements on the pinned oracle
- **PR #343**: Remove duplicate flat rtl/*.hex copies in reports/sxt-025
- **Issue #342** (closed): Remove duplicate flat rtl/*.hex copies in reports/sxt-025 (~15.5 MB)
- **PR #341**: SXT-028e-sse: live parity test for census static-screen mirror (#336)
- **PR #340**: docs(SXT-036): document O10, ten oracle-status controls
- **PR #339**: SXT-030: simulation-verified external-memory stall instrumentation (#316)
- **PR #338**: #318: cross-runner settle-boundary audit (A/B BLOCKED off-oracle; C measured; SXT-023 240-block pre-roll finding)
- **PR #337**: SXT-043 fixture revision 2: clear osc-1 p[] routes before the Sine type switch (#329)
- **Issue #336** (closed): SXT-028e-sse: live parity test between the census static-screen mirror and the oracle render_screens (#314 follow-up)
- **Issue #327** (closed): SXT-036 EVIDENCE.md says nine oracle-status controls; tool and artifact have ten (O10 undocumented)
- **Issue #316** (closed): SXT-030: Implement and simulation-verify the external-memory service/stall instrumentation (hardware-independent)

### 2026-10-05

- **PR #335**: SXT-028e-sse: per-slot corpus census; no admissible Distortion SSE carrier (#314)
- **PR #334**: docs(byte-frozen): fix registry count, SLFO cost caveat, ninth-entry note (#326)
- **Issue #326** (closed): byte-frozen registry: correct three bookkeeping defects introduced by PR #321's conflict resolution
- **Issue #314** (closed): SXT-028e-sse follow-up (F-028e-sse-8): find an admissible CORPUS carrier for the Distortion SSE branch, or establish that none exists

### 2026-10-04

- **PR #333**: test(SXT-028l): pin carrier/live-record agreement with mutation controls (#325)
- **Issue #325** (closed): SXT-028l: a non-oracle re-run of extract_rf_send34_inputs.py silently downgrades the seven carrier records' live-oracle blocks, and no test detects the contradiction

### 2026-10-03

- **PR #332**: feat(SXT-028l): restore a drift-0 same-class dual-instance render carrier; Strynth finding retained (#322)
- **Issue #322** (closed): SXT-028l: the same-class dual-instance carrier (Strynth.fxp) fails the engine-side drift determinism gate — restore render coverage for that shape or record a bounded gap

### 2026-10-02

- **PR #330**: docs(SXT-043): root cause of Digibass silent Sine reference render (#311)
- **PR #328**: chore: remove unused list_files and records_containing_word helpers
- **Issue #324** (closed): Remove two unused helper functions: list_files and records_containing_word
- **PR #323**: SXT-028l item 1a: run the live oracle extraction leg + the engine-side drift gate on linux-x86_64
- **PR #321**: SXT-041: freeze scene-LFO (slfo) scheduling, exact RTL control plane, live negative controls
- **PR #320**: SXT-028e-sse (#136): model-vs-pinned-engine reference leg, measured on the prebuilt oracle
- **PR #319**: refactor: share the report-assembly skeleton across 5 RTL-vs-model leaves
- **PR #315**: docs(SXT-030): FPGA board-selection record + capture/calibration procedure (hardware-independent)
- **PR #313**: Implement playmode submode pm_mono_st_fp voice leaf (SXT-043)
- **PR #312**: feat(SXT-028f): run the Reverb 2 class reference leg on the pinned oracle
- **Issue #311** (closed): Digibass.fxp renders silent in pinned oracle when osc1 forced to Sine (found while building SXT-043 / #77)
- **PR #309**: SXT-036: accept prebuilt oracle provisioning; run blob-verify-carriers
- **PR #306**: SXT-028l (#155): record pinned-source re-read of declared send-routing contracts; oracle legs NOT_RUN
- **Issue #303** (closed): Remove duplicated main() skeleton across 5 compare_*_rtl_model.py harnesses
- **PR #302**: ci: gate pull requests on per-commit provenance declaration
- **PR #301**: SXT-019: audit the set a clone carries — the commits a branch publishes (#25 increment 17)
- **Issue #300** (closed): SXT-019 follow-up: decide whether CI gates PR branches on per-commit provenance declaration (--commits)
- **PR #299**: oracle: install a prebuilt pinned Surge oracle per user (--prebuilt, #232)
- **PR #289**: SXT-019: correct increment 8's record (word-filter revert, control counts) and make the unwrap budget global
- **Issue #283** (closed): SXT-019: correct increment 8's evidence record (word-filter revert, control counts) and make the unwrap budget global
- **Issue #232** (closed): Prebuilt pinned Surge oracle for dispatch workers (fetch-and-build.sh --prebuilt, sha256-verified, per-user install)
- **Issue #136** (closed): SXT-028e-sse follow-up (F-028e-sse-1/3/4/5): oracle-host reference leg for the Distortion SSE quad-waveshaper branch
- **Issue #126** (closed): SXT-028f follow-up (F-028f-1): oracle-host reference leg for the Reverb 2 leaf
- **Issue #77** (closed): SXT-043: voice leaf — playmode submode: Mono (Single Trigger & Fingered Portamento)
- **Issue #75** (closed): SXT-041: voice leaf — modulation behavior: slfo
- **Issue #23** (closed): SXT-030: Select FPGA board and define capture/calibration procedure (hardware-independent)

### 2026-10-01

- **PR #298**: SXT-019: read a bookkeeping judgement's evidence from the bytes a commit publishes (#25 increment 16)
- **PR #297**: SXT-019: answer a carriage finding from the bytes a commit publishes — close the answer-set mask (#25 increment 15)
- **PR #296**: docs(#269): record the lint disposition for the eight self-stamping provenance scripts
- **PR #295**: chore(sxt-022): delete unimported rtl/voice/voice_pkg.sv
- **Issue #294** (closed): Remove unused rtl/voice/voice_pkg.sv: dead package, never imported
- **PR #293**: SXT-019: judge the bytes a commit publishes — close the staged-content mask (#25 increment 14)
- **PR #292**: SXT-019/#25: make a by-reference provenance row describe the reference it answers (R1-R4)
- **PR #291**: feat(sxt-019): read the FNAME of every member of a concatenated gzip
- **PR #290**: feat(sxt-019): disclose the git-index boundary in the provenance audit
- **PR #288**: SXT-019/#25: read the payload in a wide encoding — close the UTF-16/32 notice mask
- **PR #287**: Remove duplicated sh(cmd, cwd=None) helper in vel tools
- **Issue #286** (closed): SXT-019/#25: wrapper member names are read for only the FIRST member of a concatenated multi-member gzip
- **PR #285**: SXT-019/#25: judge the names inside the wrapper the last increment opened
- **Issue #284** (closed): Remove duplicated sh(cmd, cwd=None) helper: 3 copies, one already importable
- **PR #282**: SXT-019/#25: unwrap the payload — close the wrapper and embedded-notice masks
- **Issue #281** (closed): Remove dead code: unused imports/locals in three historical-provenance scripts
- **PR #280**: docs: declare six superseded-basis artifacts frozen, with a live audit
- **Issue #279** (closed): SXT-019/#25: four residuals in the discovery-layer provenance rules (optional pinned_commit, environment-dependent symlink corroboration, gitlink under an exclusion, class not tied to rule)
- **PR #278**: SXT-019/#25: judge the entry, not just its bytes — close the discovery-layer mask
- **PR #276**: SXT-015/#247: currency check keeps reports/sxt-015/ byte-current
- **PR #275**: fix(sxt-019): a named exemption occurrence must match exactly once
- **PR #274**: Migrate or rename the six per-leaf native-unit spectral_corr copies
- **PR #273**: SXT-019: read the file before reading the line — close the decode-layer mask on the non-exemptible rule
- **PR #271**: Refresh pinned EVIDENCE prose and leaf-verification notes quoting pre-#110 spectral_corr values (re-pin)
- **Issue #269** (closed): Decide the disposition of the lint findings in the eight self-stamping provenance scripts
- **PR #268**: test: gate SXT-028a record freshness and register the byte-frozen sources
- **PR #267**: SXT-019/#25: close the same-line holder-list mask on the license tripwire
- **PR #266**: SXT-019/#25: eight more masks off the non-exemptible license tripwire
- **Issue #260** (closed): provenance audit: an occurrences-scoped exemption also passes a foreign quote with identical wording; EVIDENCE count off by one
- **Issue #254** (closed): Make the byte-frozen source files machine-discoverable, and add the missing SXT-028a revision-freshness test
- **Issue #247** (closed): No currency check keeps reports/sxt-015/ fresh: two known-stale deltas rode into the #239 re-export undetected
- **Issue #246** (closed): Three committed image snapshots record the superseded SXT-015 accounting basis after the #239 shape decision
- **Issue #241** (closed): Remove 8 unused functions across tools/ and model/: zero in-repo references
- **Issue #165** (closed): Migrate or rename remaining per-leaf native-unit spectral_corr copies (aw-49, distortion/reverb2 NCs, L2 filter legs) after #110
- **Issue #164** (closed): Refresh pinned EVIDENCE prose and leaf-verification notes quoting pre-#110 spectral_corr values (re-pin)

### 2026-09-30

- **PR #264**: SXT-019/#25: read the notice, not the line — four more masks off the non-exemptible provenance rule
- **PR #263**: SXT: consolidate 56 duplicate `Refuse` definitions into one shared class
- **PR #262**: SXT-019/#25: close an own-attribution mask on the non-exemptible license tripwire
- **PR #259**: SXT-028e-sse: delete the dead sse_tables helper and declare what the negative-control metrics are exact under (#243)
- **Issue #258** (closed): Consolidate 58 duplicate 'class Refuse(Exception)' definitions into one shared exception
- **PR #257**: Remove 2 unused functions in probes/
- **PR #256**: SXT-015: params_digest stays override-blind; every override records itself explicitly
- **PR #255**: chore: drop shadowed instantize() duplicates and three unused names
- **Issue #253** (closed): Remove 2 unused functions in probes/: zero in-repo references
- **Issue #252** (closed): Remove dead code confirmed by ruff: duplicate instantize() methods, unused imports, unused locals
- **PR #250**: Deduplicate render_classic_reference.py and render_sine_reference.py
- **PR #249**: SXT-015: charge modulation rows once per live voice, not once per frame
- **Issue #248** (closed): SXT-015 params_digest is blind to declared REG.override() experiments, contrary to the mechanism's own docstring
- **Issue #245** (closed): Deduplicate render_classic_reference.py and render_sine_reference.py
- **PR #244**: Remove 7 unused functions across tools/ and model/: zero in-repo references
- **Issue #243** (closed): Deleting unused _u32_of_f32 in sse_tables.py invalidates the SXT-028e-sse frozen-model revision pin
- **PR #242**: SXT-036: measure the oracle gate and freeze the backfill plan (oracle-independent)
- **PR #240**: SXT-036: record the SXT-015 half of the cost accounting (oracle-independent)
- **Issue #239** (closed): SXT-015 cost model: modulation rows are charged once per frame, but voice-list rows are evaluated once per live voice (measured in SXT-036)
- **PR #238**: SXT-036: freeze the per-instance state rules with live controls (oracle-independent)
- **PR #237**: Remove six unused functions in model/: dead code with zero in-repo references
- **PR #236**: SXT-036: freeze the declared parameter corners (oracle-independent)
- **Issue #234** (closed): Remove unused functions in model/: dead code with zero in-repo references
- **PR #166**: #110: shared full-scale log-floor spectral_corr (-100 dBFS/bin) with full regrade — SXT-017 freeze input
- **PR #114**: SXT-019/#25: provenance audit (acceptance item 4) + complete decision-record index
- **Issue #110** (closed): Pilot freeze input: spectral_corr is unit-dependent (native-unit log1p knee); recommend a full-scale log floor
