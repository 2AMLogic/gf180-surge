# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

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

