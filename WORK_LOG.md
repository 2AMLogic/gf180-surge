# Work log

Recent merged pull requests and closed issues. Entries record forge events only; acceptance and claim limits remain in each committed evidence record. Initial history window: 2026-09-30 onward.

### 2026-10-22

- **PR #530**: test: pin NC-B RTL mip-mutant control to the -hi-v1 fixture and correct its evidence
- **Issue #529** (closed): wavetable RTL negative control --mutant (WAVETABLE_MUTANT_MIP) does not fail on seq-wt-base-v1 / seq-wt-pitch-extremes-v1
- **PR #519**: fix(rtl): load wavetable_core sinc ROM through a write port
- **Issue #471** (closed): RTL: wavetable_core has 2 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **PR #516**: refactor(rtl): make rf_bins12_core config and block inputs module ports
- **Issue #476** (closed): RTL: rf_bins12_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **PR #518**: refactor(rtl): expose reverb1_core coefficient plane and block inputs as ports
- **Issue #472** (closed): RTL: reverb1_core has 17 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **PR #512**: fix(rtl): drive rf_global34_core config and block inputs through ports
- **Issue #478** (closed): RTL: rf_global34_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)

### 2026-10-21

- **PR #525**: fix: default Surge oracle paths to repo-local oracle/build/surge
- **PR #523**: fix(rtl): remove initial drive of logical4_core block_done and its MULTIDRIVEN waiver
- **PR #522**: fix(rtl-lint): refresh waivers and keep latch control live without a LATCH waiver
- **PR #521**: Bump Repo Skills 0.24.3 -> 0.24.7
- **PR #513**: fix(rtl): make rf_global2_core config and block inputs real ports
- **PR #511**: fix(rtl): promote galactic_core coefficient and block inputs to ports
- **Issue #524** (closed): Remove hard-coded user-home paths: build or resolve the Surge XT oracle engine in-repo
- **Issue #520** (closed): rtl-lint: negative controls report CONTROL-BROKEN (baseline did not PASS) on main since #437
- **Issue #477** (closed): RTL: rf_global2_core has 9 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **Issue #474** (closed): RTL: galactic_core has 11 non-port signals read but undriven in standalone elaboration (Verilator UNDRIVEN)
- **Issue #470** (closed): RTL: logical4_core `block_done` driven from both an initial block and always_ff (Verilator MULTIDRIVEN, logical4_core.sv:226)

### 2026-10-20

- **PR #499**: ci: gate committed klt signoff T1 verdict with byte-compare workflow
- **Issue #498** (closed): T1: commit a klt signoff block manifest and gate its verdict in CI
- **PR #437**: Add static Verilator RTL lint gate and RTL classification manifest (#434)
- **Issue #434** (closed): Add static RTL lint gate (Verilator) and classify product vs sim-only/mutant RTL
- **PR #508**: docs(sxt-023): Delay reference contract and substitute-build qualification report
- **Issue #507** (closed): Define and qualify the canonical Delay reference contract (#16 / #12)

### 2026-10-18

- **PR #503**: SXT-028j: run oracle legs on prebuilt oracle, confirm declared contracts, record carriers REFUSED

### 2026-10-17

- **PR #414**: CI hardening: job timeouts, PR-only concurrency cancel, SHA-pinned actions
- **Issue #410** (closed): CI hardening: job timeouts, PR-run concurrency cancel, and SHA-pinned actions

### 2026-10-16

- **PR #480**: fix(rtl): assign dp_tmp by default in reverb1_core request block
- **Issue #469** (closed): RTL: reverb1_core infers a latch for dp_tmp (Verilator LATCH, reverb1_core.sv:130)
- **PR #491**: test(SXT-043): record native fixture-revision-2 results for Digibass
- **Issue #329** (closed): SXT-043 fixture: clear osc-1 p[] modulation routings before Sine override so Digibass reference is valid (follow-up to #311)
- **PR #487**: docs(evidence): record NC-2 artifacts as not reproducible (#484)
- **PR #482**: Bump Repo Skills 0.19.5 -> 0.24.3
- **Issue #484** (closed): SXT-034: record NC-2 spectral_corr artifacts as not reproducible (missing mutant input)
- **PR #431**: Add GPL-boundary register and register cross-check (#370)
- **PR #481**: fix(rtl): promote logical4 cfg/in_l/in_r to core ports
- **Issue #370** (closed): GPL-boundary register: list every GPL-derived constant table with its source and provenance

### 2026-10-13

- **PR #368**: LP24 full-engine observation tap, external host route (#307)
- **PR #397**: SXT-020: reject contradictory/unsupported patch-image versions (#391)
- **PR #467**: SXT-028g: Phaser same-shape carrier drift screen (live run NOT_RUN) (#426)
- **PR #442**: Refuse non-finite float audio in wet comparator (#439)
- **PR #422**: SXT-028: re-run effect RTL-vs-model comparators against committed rtl-exactness verdicts
- **PR #441**: ablation_delta: validate WAV pair before BIT-IDENTICAL shortcut (#438)
- **PR #403**: fix(#401): honest package.json test/check/lint scripts
- **PR #466**: SXT-028h: screen same-shape drift-zero rf-bins12 carriers
- **PR #465**: SXT-028d: screen same-shape drift-zero rf-global2 carriers (#425)
- **Issue #391** (closed): SXT-020: reject contradictory binary and JSON patch-image versions
- **Issue #439** (closed): SXT-023: refuse non-finite wet audio and emit strict comparison JSON
- **Issue #416** (closed): Triage RTL-vs-model comparators with no CI execution and re-run the effect comparators against their committed rtl-exactness verdicts
- **Issue #438** (closed): SXT-014: validate live WAV identity and 48 kHz format before ablation diagnostics
- **Issue #401** (closed): package.json test/check:ci/check:all scripts exit 0 with no checks run (NOT_RUN reads as PASS)
- **Issue #424** (closed): SXT-028h: screen same-shape drift-zero rf-bins12 carriers
- **Issue #425** (closed): SXT-028d: screen same-shape drift-zero rf-global2 carriers

### 2026-10-12

- **PR #464**: fix: gate slow-controls JUnit on full (classname, name) identity
- **PR #461**: fix(tools): report-status audit fails on unreadable JSON, refuses empty coverage (#460)
- **PR #427**: SXT-023: state Delay ext-mem traffic on one basis (#367)
- **PR #458**: SXT-024: require decay-sweep coverage before successful comparison exit (#456)
- **PR #459**: SXT-331 prerequisite: reusable shape-preserving carrier drift screen (#423)
- **PR #453**: Reject shortened voice checkpoint records before RTL exactness PASS
- **PR #457**: Reject duplicate and unowned LFO checkpoint keys before RTL exactness PASS
- **Issue #463** (closed): Slow-controls JUnit gate: reject duplicate and wrong-class required testcases
- **Issue #460** (closed): Report vocabulary audit: fail on unreadable JSON and refuse empty input coverage
- **Issue #462** (closed): Champion: Merge-Risk Hold Digest
- **Issue #367** (closed): SXT-023: correct Delay ext-mem traffic basis (EVIDENCE.md A6, ext_mem_if.md) and frames_rendered 8550 vs 8790 blocks
- **Issue #456** (closed): SXT-024: require decay-sweep coverage before successful comparison exit
- **Issue #423** (closed): SXT-331 prerequisite: reusable shape-preserving carrier drift screen
- **Issue #451** (closed): Reject shortened voice checkpoint records before RTL exactness PASS
- **Issue #455** (closed): Reject duplicate and unowned LFO checkpoint keys before RTL exactness PASS

### 2026-10-11

- **PR #454**: SXT-023: refuse invalid comparison windows and empty exactness coverage
- **PR #450**: feat: gate SXT-013 acceptance ratings on recorded audition (#447)
- **PR #449**: Declare velocity live-control simulator dependency and report missing tools
- **PR #448**: Pin CI numpy/pytest via requirements-ci.txt (#354)
- **PR #443**: docs: classify every committed NumPy version stamp for the #354 CI pin decision
- **PR #440**: Reject ambient and cached surgepy bindings before reference rendering
- **PR #435**: Add review packets for the 15 pending decision records (#371)
- **Issue #452** (closed): SXT-023: refuse invalid comparison windows and empty exactness coverage
- **Issue #447** (closed): SXT-013: gate acceptance ratings on recorded audition after playback failures
- **Issue #400** (closed): Declare velocity live-control simulator dependency and report missing tools
- **Issue #430** (closed): tests/test_report_status_tokens.py: 4 failures on main (unlisted status tokens in reports/)
- **Issue #411** (closed): main: tests/test_report_status_tokens.py fails on sxt-013 listening-cache sample report tokens
- **Issue #354** (closed): Pin Python test dependencies (numpy/pytest) so CI numerics are reproducible
- **Issue #373** (closed): Classify the four NumPy versions stamped in committed evidence records (live vs historical) before #354 pins CI
- **Issue #436** (closed): Reject ambient and cached surgepy bindings before reference rendering
- **Issue #371** (closed): Prepare review packets for the 15 pending decision records ahead of the two-key ceremony

### 2026-10-10

- **PR #421**: SXT-025: run integrated wet-path negative controls through the live registry
- **PR #433**: SXT-029: require evidence-backed readiness for every coverage leaf (#432)
- **PR #429**: Census bookkeeping: reconcile every CSV preset identity with the manifest
- **PR #420**: SXT-029: refuse coverage control overrides at the publication destination
- **PR #417**: CI: slow-controls workflow runs NC_LIVE_SLOW negative controls (#415)
- **Issue #419** (closed): SXT-025: execute integrated wet-path negative controls through the live registry
- **Issue #432** (closed): SXT-029: require evidence-backed readiness for every coverage leaf
- **Issue #428** (closed): Census bookkeeping: reconcile every CSV preset identity with the manifest
- **Issue #418** (closed): SXT-029: refuse coverage control overrides at the publication destination
- **Issue #415** (closed): CI: run the NC_LIVE_SLOW negative controls (Chorus, Reverb, velocity, budget no-op) on a schedule so they stop being permanently NOT_RUN

### 2026-09-29

- **PR #235**: SXT-036: account for #70's declared inputs (sequences + carriers) — declared-sequence exactness, precondition-aware controls, carrier audit
- **PR #233**: SXT-036: velocity/release-velocity modulation - frozen model, RTL==model exactness, controls (items 2 and 5 NOT_RUN)
- **Issue #96** (closed): Builder infra gap: pinned Surge oracle (surgepy) unavailable on Loom dispatch workers

### 2026-09-28

- **PR #231**: ci: move short and scheduled jobs off Blacksmith to GitHub-hosted
- **PR #230**: docs: re-measure and stamp the full-suite row in WT-harness EVIDENCE.md
- **PR #228**: docs: re-measure the wavetable-harness control counts in the #194 evidence record
- **PR #227**: chore: stop tracking local .env; ignore .env files
- **PR #226**: fix: make the wavetable harness exit status agree with its FAIL verdict
- **PR #222**: Migrate compare_classic_rtl_model.py, compare_sine_rtl_model.py to report_sim_fails
- **PR #224**: Carry stimulus_lengths status into the SXT-026 exactness transcripts
- **PR #225**: feat(halfband): generate the F-176-2 failure-control transcript and re-derive it in CI
- **PR #223**: fix: report the crashed case-D pre-migration run as NO_VERDICT, not a stale FAIL
- **PR #213**: measure the shared HalfbandD2 zero-input limit cycle and declare its bound (F-176-2)
- **PR #220**: fix(sxt-026): name an unparseable tb_traffic.txt / traffic.json instead of discarding the comparison by traceback
- **PR #219**: fix(tooling): report stimulus-load failures in the kt/mw/lfo RTL harnesses (#207)
- **PR #217**: chore: remove stray committed tb_traffic.txt from repo root
- **PR #212**: SXT-017 revision #180: move the wavetable decimator to a per-scene stage and extend RTL exactness to the 48 kHz output
- **PR #214**: fix(tooling): stimulus-load reporting for the lowpass RTL harnesses (lp12/lp24/lpmoog) — #209
- **PR #204**: fix(sxt-026): detect a truncated RTL stimulus file before the simulator runs
- **PR #210**: refactor: consolidate 17 duplicate sha256_file copies on oracle_common
- **PR #202**: fix(tooling): opt-in stimulus-load reporting in _rtl_compile_common; migrate voice+control harnesses (#193)
- **PR #200**: fix(sxt-026): a present-but-unreadable model_trace.json is a named sim failure, not a traceback
- **Issue #229** (closed): EVIDENCE.md's "Full repository suite" row is stale (799 passed claimed, 966 measured)
- **Issue #215** (closed): EVIDENCE.md and PR #204 body understate tests/test_sxt026_wt_rtl_harness.py's pass count (16 claimed, 20 actual)
- **Issue #201** (closed): Migrate the remaining 8 RTL-vs-model harnesses to _rtl_compile_common's report_sim_fails mode (#193 follow-up)
- **Issue #218** (closed): compare_wt_rtl_model.py: a FAIL verdict whose only reason is a traffic failure still exits 0
- **Issue #208** (closed): Migrate compare_classic_rtl_model.py, compare_sine_rtl_model.py (oscillator family) to _rtl_compile_common's report_sim_fails mode (#201 decomposition)
- **Issue #203** (closed): rtl-exactness.txt does not record the stimulus-length status the verdict JSON now carries (a PASS transcript still cannot state its stimulus was complete)
- **Issue #221** (closed): make the F-176-2 failure-control transcript generated and re-derived, like the splice provenance
- **Issue #216** (closed): Evidence artifact: PART 1 case-D reports a stale-read verdict for a pre-migration run that crashed (NO_VERDICT) — reports/tooling-lowpass-harness-stimulus-load
- **Issue #181** (closed): F-176-2: the shared fixed-point HalfbandD2 holds a non-decaying zero-input limit cycle (~26 Q10.21 LSB at Nyquist)
- **Issue #205** (closed): compare_wt_rtl_model.py: an unparseable tb_traffic.txt or traffic.json still exits by traceback, discarding an already-computed comparison
- **Issue #207** (closed): Migrate compare_kt_rtl_model.py, compare_mw_rtl_model.py, compare_lfo_rtl_model.py (voice family) to _rtl_compile_common's report_sim_fails mode (#201 decomposition)
- **Issue #211** (closed): Remove stray committed tb_traffic.txt from repo root
- **Issue #180** (closed): SXT-017 proposal: move the wavetable slice's decimator to a per-scene stage and extend RTL coverage to the 48 kHz output
- **Issue #209** (closed): Migrate compare_rtl_model_lp12.py, compare_rtl_model_lp24.py, compare_rtl_model_lpmoog.py (lowpass family) to _rtl_compile_common's report_sim_fails mode (#201 decomposition)
- **Issue #194** (closed): compare_wt_rtl_model.py: a TRUNCATED stimulus file is still reported as a model disagreement (needs a healthy-run warning baseline first)
- **Issue #206** (closed): Remove duplicate sha256_file implementations: consolidate on oracle_common.sha256_file
- **Issue #193** (closed): _rtl_compile_common.compile_and_run: the exit-0 $readmemh blind spot #188 fixed for the wavetable harness is shared by 11 importers
- **Issue #197** (closed): compare_wt_rtl_model.py: a malformed or unreadable model_trace.json still exits by traceback with no verdict JSON

### 2026-09-27

- **PR #198**: Re-grade rms-leg polarity residuals in sxt-026a/EVIDENCE.md (#189)
- **PR #199**: chore: gitignore Repo Skills guard-hook logs (#191)
- **PR #195**: fix(sxt-026): report a stimulus that never loaded as a simulator failure, not a model disagreement
- **PR #196**: decide(#187): int16 wet tail-shape leg grades on a designated fixture clear of the quantization band (0016 F-E, fixture-side arm)
- **PR #183**: SXT-026/#176: declare the wavetable leaf's oscillator-only RTL boundary and measure per-slice vs per-scene decimation
- **PR #190**: fix: report a vvp failure as the wavetable harness's own FAIL verdict
- **PR #186**: #160: pilot-freeze decision — one declared tail-shape floor (-100.0 dBFS) for every bus, int16 quantization band declared
- **PR #185**: #177: verify + record the sxt-032 rms-polarity re-grade (already landed via #145)
- **PR #184**: fix: republish leaf renders, budget JSONs and coverage-v1 invalidated by the #123 halfband fix
- **PR #179**: SXT-032/SXT-035: fix run_lfo_model.py/run_mw_model.py stimulus, re-run voice-datapath pairing
- **PR #178**: Re-grade coverage-v1 ledger notes for the #95/#97 rms-polarity fix
- **PR #173**: SXT-028g/#140: correct the phaser carrier verdicts and re-select the queued carriers
- **PR #174**: SXT-035/#163: control-plane discriminator for the C2 smoothing-bypass negative control
- **PR #170**: SXT-024/#112: pin send_gain to explicit float32; regenerate the STALE comparison/negative-control records once (verdicts unchanged)
- **PR #171**: #127 (F-028f-2): SXT-015 Reverb 2 traffic row — declared conservative hold, 29/17 correction routed to #12
- **PR #169**: #154: census-vs-graphs FX type cross-check compares content (type id), not spelling
- **PR #168**: SXT-028b/#119: derive the Conditioner tail gate from the schedule, not a constant
- **PR #161**: feat: add windowed decay-curve tail-shape leg to the wet-path tail gate
- **Issue #189** (closed): Re-grade the rms-leg polarity flips in sxt-026/, SXT-033/, and sxt-026a/ EVIDENCE.md (untracked gap from #157/#177)
- **Issue #191** (closed): gitignore: add .claude/skills/repo/logs/ so guard-hook logs don't block fleet resync (2am#1184)
- **Issue #188** (closed): compare_wt_rtl_model.py: an Icarus $readmemh open failure is invisible (vvp exits 0, ERROR on discarded stdout)
- **Issue #187** (closed): int16 wet tail-shape grading is fixture-limited: the shape leg's sensitivity and its quantization noise overlap (#160 option F-E, NOT_RUN)
- **Issue #176** (closed): SXT-026 follow-up: wavetable post-oscillator path has no RTL, and the model decimates per voice slice instead of per scene
- **Issue #182** (closed): compare_wt_rtl_model.py: a vvp failure raises NameError instead of reporting FAIL, and its message is discarded
- **Issue #160** (closed): Pilot-freeze input: tail-shape leg floor sits in the int16 quantization-dominated region (0.79 dB of 1.0 dB on a +-1 LSB control)
- **Issue #177** (closed): Re-grade reports/sxt-032/EVIDENCE.md rms-leg prose for the #95 polarity fix (mod:lfo, same class as #97)
- **Issue #145** (closed): SXT-022 follow-up: republish the leaf renders and budget JSONs invalidated by the #123 halfband branch-order fix
- **Issue #175** (closed): SXT-032/SXT-035 follow-up: LFO/modwheel runners emit pre-SXT-034 tb_voice stimulus, so the voice-datapath RTL pairing is BLOCKED at HEAD
- **Issue #157** (closed): Coverage ledger follow-up: re-grade leaf-verification.json notes that depend on the seq-notes-repeated-v1 / uni1 rms-polarity PASS (from #97)
- **Issue #140** (closed): SXT-028g: two of three queued phaser carriers are refused by the repaired FX-modulation screen
- **Issue #163** (closed): SXT-035 C2 smoothing-bypass negative control is not live under the #110 spectral_corr definition
- **Issue #112** (closed): SXT-024: committed click/preset comparison records are STALE vs the current tool (NumPy-2 float32 send_gain; fields added after commit)
- **Issue #127** (closed): SXT-028f finding (F-028f-2): SXT-015 Reverb 2 per-sample traffic row over-estimates (40/18 vs measured 29/17)
- **Issue #154** (closed): Tooling: census-vs-graphs FX type cross-check refuses on NAME SPELLING, not content (FrequencyShifter/Freq Shift, RingModulator/Ring Mod)
- **Issue #119** (closed): SXT-028b evidence precision: derive tail-gate span from schedule; NC-3 coverage gate is a local predicate
- **Issue #111** (closed): Tooling: wet-path tail gate misses late-tail truncation (whole-region relative RMS); add a tail-shape leg

### 2026-09-26

- **PR #158**: Re-grade seq-notes-repeated-v1 rms leg to FAIL in SXT-022/034/035 evidence (#97)
- **PR #159**: SXT-037 amendment (F-038-3/F-038-4): correct LP12 coefficient-maker rate and clipscale dB conversion
- **PR #153**: SXT-028l/#64: Routing-form leaf: Send buses 3-4 (send3/send4, extended rack half) -- frozen model, exact RTL, per-instance state + gain plane, 4 live RTL mutants, SXT-011 send-level gap routed to #12
- **PR #156**: SXT-028k/#63: Airwindows "Logical" (id 4) algorithm leaf — frozen fixed model, exact RTL, per-instance state, reference leg NOT_RUN
- **PR #51**: .github/workflows: Migrate workflows to Blacksmith runners
- **PR #152**: chore: remove unused imports and dead local variables (pyflakes-confirmed)
- **PR #151**: SXT-028i/#61: Routing-form leaf: Scene-A insert FX slots 3-4 (ains3/ains4, extended rack half) — frozen model, exact RTL, per-instance state, 3 live RTL mutants
- **PR #149**: SXT-028j: extended-rack global FX slots 3-4 routing form — frozen model, exact RTL, live negative controls, oracle legs NOT_RUN
- **PR #142**: SXT tooling: extract shared iverilog compile/run helper from the 10 RTL-vs-model exactness harnesses
- **PR #148**: SXT-028h/#60: Routing-form leaf: Scene-B insert FX bus, slots 1-2 (bins1/bins2) — frozen model, exact RTL, per-instance state + lifecycle, live RTL mutants
- **PR #146**: fix: halfband D2 samples the B branch at the even index, per the pinned kernel
- **PR #137**: SXT-028e-sse: Distortion SSE quad-waveshaper branch (FX models 3..7) — frozen fixed model, exact RTL, per-instance QuadWaveshaperState
- **PR #143**: #122: FX modulation RNG streams are not pinnable — exclusion recorded as a contract revision (DR-0013), coverage reduction published
- **PR #139**: SXT-029/#22: re-pin 3 drifted leaf evidence records, republish coverage-v1, and assert republishability
- **PR #138**: SXT-028b: regenerate stale artifact + rewrite hardcoded finding text
- **PR #141**: fix: phaser extractor FX-modulation screen walks md.g/md.s[*].s/md.s[*].v
- **PR #133**: SXT-015/017: Conditioner state = SXT-028b measured 2,444 B, not the shared 8,192 B placeholder
- **Issue #97** (closed): SXT-022/SXT-034/SXT-035: re-grade seq-notes-repeated-v1 baseline PASS -> FAIL under corrected rms_diff_dbfs polarity
- **Issue #102** (closed): SXT-037 follow-up (F-038-3/F-038-4): landed LP 12 dB model deviates from the pin in coefficient-maker sample rate and clipscale dB conversion
- **Issue #64** (closed): SXT-028l: Routing-form leaf: Send buses 3-4 (send3/send4, extended rack half)
- **Issue #63** (closed): SXT-028k: Airwindows algorithm leaf: Logical (id 4)
- **Issue #147** (closed): Remove unused imports and dead local variables (pyflakes-confirmed)
- **Issue #61** (closed): SXT-028i: Routing-form leaf: Scene-A insert FX slots 3-4 (ains3/ains4, extended rack half)
- **Issue #62** (closed): SXT-028j: Routing-form leaf: Global FX slots 3-4 (global3/global4, extended rack half)
- **Issue #130** (closed): Extract shared iverilog build/run helper from RTL-vs-model comparison scripts
- **Issue #60** (closed): SXT-028h: Routing-form leaf: Scene-B insert FX bus, slots 1-2 (bins1/bins2)
- **Issue #123** (closed): SXT-022: voice HalfbandD2 polyphase A/B branch assignment disagrees with the pinned HalfRateFilter
- **Issue #121** (closed): SXT-028e-sse: Distortion SSE quad-waveshaper branch (FX models 3..7)
- **Issue #122** (closed): FX modulation RNG waveforms (Noise / Sample & Hold): pin the stream or record the exclusion as a contract revision
- **Issue #144** (closed): SXT-029 tooling integrity: six stale evidence pins in reports/coverage-v1/leaf-verification.json silently disabled the coverage negative controls
- **Issue #125** (closed): SXT-029/#22 apparatus: reports/coverage-v1/ is no longer republishable from its committed inputs (4 stale evidence pins)
- **Issue #134** (closed): SXT-028b artifact no longer byte-reproducible by its own generator (sxt015_reconciliation snapshot + stale justification_text_finding)
- **Issue #132** (closed): Tooling: extract_phaser_inputs.py modulation screen is the same silent no-op (iterates md dict keys)
- **Issue #117** (closed): SXT-015/017 accounting: replace Conditioner no_long_buffer placeholder with SXT-028b measured state; fix 'no delay line' and 'gate/LFO' labels

### 2026-09-25

- **PR #131**: #116: chorus extractor FX-modulation screen walks the real md structure (was a silent no-op)
- **PR #129**: SXT-028e/#57: Distortion effect leaf — frozen fixed model, exact RTL, per-instance state, reference leg NOT_RUN
- **PR #118**: SXT-028b (#54): Conditioner effect leaf - frozen model, exact RTL, live negative controls
- **PR #128**: SXT-028f/#58: Reverb 2 tank reverb — frozen fixed-point model, exact RTL, per-instance state, oracle leg named
- **PR #124**: SXT-028g/#59: Phaser effect leaf — frozen model, exact RTL, per-instance state, oracle gap named
- **PR #120**: SXT-028d/#56: Global FX slot 2 routing form — fixed model, exact RTL, per-instance state, oracle gap named
- **PR #115**: SXT-024/#108: keep the bespoke reverb tail window; NO_VERDICT refusal + model_tail_present transparency; regeneration sequenced behind #112
- **PR #113**: #100: wet-path tail gate on the stereo effect-slice comparators; rms_diff_dbfs floor; spectral_corr characterization
- **PR #109**: SXT-017 stage 2: gate candidate bundles on SXT-016 cost closure and escalate the profile-v1 freeze
- **PR #106**: feat: SXT-042/#76 keytrack modsource — frozen model, exact RTL
- **PR #103**: SXT-038/#72: LP 24 dB filter leaf — frozen model, exact RTL, pinned-kernel reference
- **PR #105**: SXT-039/#73: LP Legacy Ladder filter — frozen model, exact RTL, pinned-kernel reference (oracle-free)
- **PR #99**: #93: gate the tail region in the shared audio comparator (verdict, not advisory)
- **PR #98**: SXT-095: audit pre-fix shared-comparator rms_diff_dbfs polarity
- **Issue #116** (closed): Tooling: extract_chorus_inputs.py modulation screen is a silent no-op (iterates md dict keys)
- **Issue #57** (closed): SXT-028e: Distortion effect leaf (multiband + waveshaper drive)
- **Issue #54** (closed): SXT-028b: Conditioner effect leaf (gate/compressor/LFO)
- **Issue #58** (closed): SXT-028f: Reverb 2 effect leaf (sst-effects tank reverb)
- **Issue #59** (closed): SXT-028g: Phaser effect leaf (sst-effects Phaser)
- **Issue #56** (closed): SXT-028d: Routing-form leaf: Global FX slot 2 (second concurrent global FX instance)
- **Issue #108** (closed): Tooling: unify compare_reverb_model.py's tail check onto the shared declared_tail_region()/tail_check() shape
- **Issue #100** (closed): Tooling: extend the #93 wet-path tail gate to the stereo effect-slice comparators; decide the -Infinity / spectral_corr metric findings
- **Issue #76** (closed): SXT-042: voice leaf — modulation behavior: keytrack
- **Issue #73** (closed): SXT-039: voice leaf — filter algorithm: LP Legacy Ladder
- **Issue #93** (closed): SXT-028c follow-up: gate tail-region check in the shared audio comparator (verdict, not advisory)
- **Issue #95** (closed): Tooling: audit pre-fix shared-comparator outputs for inverted rms_diff_dbfs flags

### 2026-09-24

- **PR #92**: SXT-040/#74: Sine oscillator — fixed model, exact RTL, reference fixtures
- **PR #91**: SXT-028c/#55: Chorus — fixed model, exact RTL, per-instance state, shared-delay-semantics dependency noted
- **Issue #74** (closed): SXT-040: voice leaf — oscillator family: Sine
- **Issue #55** (closed): SXT-028c: Chorus effect leaf (sst-effects Chorus, delay-line class)

### 2026-09-23

- **PR #88**: SXT-034/#68: unison stack — fixed model, exact RTL, declared max unison
- **PR #90**: SXT-028a/#53: Airwindows Galactic — fixed model, exact RTL, reference fixtures
- **PR #89**: SXT-035/#69: modwheel — control-path leaf, exact RTL, reference fixtures
- **Issue #68** (closed): SXT-034: voice leaf — unison stack topology (>1 voice)
- **Issue #53** (closed): SXT-028a: Airwindows algorithm leaf: Galactic (id 49)
- **Issue #69** (closed): SXT-035: voice leaf — modulation behavior: modwheel

### 2026-09-22

- **PR #87**: SXT-033/#67: Classic oscillator class — parameter coverage extension
- **PR #85**: SXT-037/#71: LP 12 dB filter — parameterized leaf, exact RTL, stability corners
- **PR #86**: SXT-026a/#48: voice-slice generality — parameterized class, 2 presets verified
- **PR #84**: SXT-032/#66: LFO modulation — fixed model, exact RTL, reference fixtures
- **PR #83**: DAG: mark SXT-021/SXT-024 PASS (bookkeeping catch-up)
- **PR #82**: DAG: final board refresh after waves 5-9
- **PR #81**: SXT-029: coverage v1 — per-preset statuses over committed evidence, honest denominators
- **PR #65**: SXT-028: effects leaf generator + first recovery-ordered leaves filed
- **PR #78**: SXT-027: voice-feature leaf generator + first recovery-ordered leaves filed
- **PR #80**: SXT-025: recompile integration image at format 1.1.0 (fixes #79)
- **PR #52**: SXT-026: wavetable assets + playback — compiler manifest, fixed model, exact RTL, external-residency traffic
- **PR #49**: SXT-025: one complete wet preset through the integrated model+RTL path
- **Issue #67** (closed): SXT-033: voice leaf — oscillator family: Classic
- **Issue #71** (closed): SXT-037: voice leaf — filter algorithm: LP 12 dB
- **Issue #48** (closed): SXT-026a: voice-leaf scope extension — second voice slice (blocks #18's supported-status row)
- **Issue #66** (closed): SXT-032: voice leaf — modulation behavior: lfo
- **Issue #22** (closed): SXT-029: Run full qualification and publish coverage
- **Issue #21** (closed): SXT-028: Expand effects by measured recovery
- **Issue #20** (closed): SXT-027: Generate remaining voice-feature leaf issues
- **Issue #79** (closed): SXT-020: pre-existing CI red on main — tests/test_sxt025_integration.py image-format mismatch (1.0.0 vs 1.1.0)
- **Issue #19** (closed): SXT-026: Add Wavetable asset and playback support
- **Issue #18** (closed): SXT-025: Pass one complete wet preset

### 2026-09-21

- **PR #47**: SXT-019: decision record 0003 — Reverb1 DELAY_TIME_TABLES constants
- **PR #46**: SXT-023 follow-up: delay tb exactness, budget diagnosis for SXT-017, NC-b provenance
- **PR #43**: SXT-024: Reverb1 — fixed model, exact RTL, measured buffers, tail + stability controls
- **PR #44**: SXT-023: Delay + EQ — fixed models, exact RTL, per-instance state, ext-mem interface
- **PR #42**: SXT-021: timed control + scheduling — event queues, voice alloc, worst-case accounting, RTL schedule equality
- **Issue #17** (closed): SXT-024: Implement Reverb1
- **Issue #14** (closed): SXT-021: Implement timed control and scheduling

### 2026-09-20

- **PR #41**: DAG: board refresh after waves 4-5
- **PR #40**: SXT-022: first dry voice slice — frozen fixed model, exact RTL equality, reference error report
- **PR #39**: SXT-020: patch-image compiler v1 — versioned IR, explicit rejections, golden suite, corpus scan
- **PR #38**: SXT-016: kernel cost probes — cycles/RAM/bandwidth under named assumptions
- **PR #37**: SXT-017 DRAFT: bundle comparison + per-preset predictions (freeze blocked on listening + probes)
- **PR #36**: DAG: board refresh after waves 2-3
- **PR #35**: SXT-014 apparatus: one-effect-at-a-time ablation renders + diagnostic deltas (labels blocked on listening)
- **PR #34**: SXT-015: resource accounting model — per-instance FX/voice state, memory transactions, budget closure
- **PR #33**: SXT-013 apparatus: candidate slates, listening harness, DRAFT fidelity policy (freeze blocked on human listening)
- **PR #32**: SXT-012: versioned render fixtures — sequences, wet/dry renders, repeatability evidence
- **PR #31**: SXT-011: normalized patch graphs — all 3,561 presets via native loader
- **PR #30**: SXT-018: backlog DAG + evidence-derived status board
- **PR #28**: SXT-010: pinned native oracle — manifest, drift-gated build, 3,561-preset load report, first note capture
- **PR #27**: Infra: CI — census consistency check, python compile gate
- **PR #26**: SXT-019: decision record 0001 — oracle automation source policy
- **Issue #15** (closed): SXT-022: Qualify a first dry voice slice
- **Issue #13** (closed): SXT-020: Compile patch images
- **Issue #11** (closed): SXT-016: Run representative cost probes
- **Issue #9** (closed): SXT-014: Measure effects' contribution
- **Issue #10** (closed): SXT-015: Create resource accounting
- **Issue #8** (closed): SXT-013: Freeze favorite selection and fidelity policy
- **Issue #7** (closed): SXT-012: Create render fixtures
- **Issue #6** (closed): SXT-011: Export normalized patch graphs
- **Issue #29** (closed): SXT-018: Backlog DAG + evidence-derived status board (README marker block)
- **Issue #5** (closed): SXT-010: Build the native oracle
- **Issue #4** (closed): SXT-000: Preliminary static census (DONE)

### 2026-10-09

- **PR #412**: Use oc.sha256_file instead of local copies in 8 reference scripts
- **PR #413**: DAG check: waivers for PASS nodes with non-PASS prerequisites (#409)
- **PR #407**: SXT-028f: reject unknown/empty reference-control selections (#405)
- **Issue #375** (closed): Auditor Capability Request: refresh origin/main when SSH host verification fails
- **Issue #272** (closed): Remove duplicated sha256_file(path) reimplementation: 7 copies already have a canonical oracle_common.sha256_file
- **Issue #409** (closed): DAG check: PASS nodes with BLOCKED prerequisites need an explicit waiver (7 today)
- **Issue #405** (closed): SXT-028f: reject unknown and empty standalone reference-control selections
- **PR #406**: SXT-013: bind listening-cache audio to preset and render identities
- **PR #399**: feat(#392): verify allocation offsets, overlap and slot ownership
- **PR #398**: test: enumerate profile_budget and reverb2 reference controls (#387)
- **PR #396**: SXT-023: Delay matches pinned-engine fixtures within budgets (d(t) probe + model revision)
- **PR #395**: SXT-029: require preset-scoped complete-wet integration evidence before supported (#384)
- **PR #394**: Deduplicate stereo WAV reader and channel metrics in Chorus comparator (#376)
- **PR #393**: Audit committed report verdict tokens against the six-status vocabulary (#365)
- **PR #389**: Publish current NOT_RUN refusal verdicts for shared RTL comparison input errors
- **PR #388**: test: AGENTS.md/CLAUDE.md parity outside marker blocks (#364)
- **PR #386**: SXT-028e-sse: arm64 macOS reference-leg attempt (control FAIL, rest NOT_RUN) (#317)
- **PR #385**: Reject stale trace outputs in shared RTL simulator runs (#360)
- **PR #383**: SXT-028e-sse: FuzzTable<1> libc++ observation on alternate arm64 host - MISMATCH at default flags; pinned-host leg NOT_RUN (#135)
- **PR #380**: docs(policy): option A for source-nonrepeatable carriers + census spec (#310)
- **Issue #404** (closed): SXT-013: bind listening-cache audio to preset and render identities
- **Issue #392** (closed): SXT-020: verify allocation intervals cannot alias per-instance effect state
- **Issue #387** (closed): Extend the negative-control enumerator to cover profile_budget_controls.py and reverb2_reference_controls.py (outside the *_negative_controls.py glob)
- **Issue #384** (closed): SXT-029: require preset-scoped complete-wet integration evidence before supported
- **Issue #376** (closed): Deduplicate stereo WAV reader and channel metrics in wet effect comparators
- **Issue #365** (closed): Audit committed report verdict tokens against the six-status vocabulary (REFUSED/VERIFIED/OK undeclared)
- **Issue #364** (closed): Enforce AGENTS.md/CLAUDE.md parity outside Loom marker blocks with a test
- **Issue #361** (closed): Write current refusal verdicts for shared RTL comparison input errors
- **Issue #360** (closed): Reject stale trace outputs in shared RTL simulator runs
- **Issue #265** (closed): Remove duplicated sha256(path) helper: 5 copies in tools/ instead of one shared module
- **Issue #261** (closed): Remove duplicated main()/revision_pin_ok() skeleton across rf_* RTL-model harnesses

### 2026-10-08

- **Issue #351** (closed): Auditor Capability Request: Python runtime for gf180-surge validation
- **PR #366**: docs(sxt-023): Delay word-length record; d(t) probe BLOCKED (no oracle) -- Part of #16
- **PR #362**: test: enumerate tools/*_negative_controls.py so no control goes unrun
- **Issue #355** (closed): Add a test that enumerates tools/*_negative_controls.py so no control goes unrun (14 of 25 unreferenced)
- **PR #363**: ci: require an explicit simulator-case inventory in the rtl-sim gate (#356)
- **Issue #356** (closed): Require an explicit simulator-case inventory in the RTL CI report gate
- **PR #358**: SXT-029: reconcile voice-scope ledger with landed SXT-026a evidence
- **Issue #353** (closed): SXT-029: reconcile the voice-scope coverage ledger with landed SXT-026a evidence
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
