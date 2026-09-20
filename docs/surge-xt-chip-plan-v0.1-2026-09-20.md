# Surge XT subset chip: product contract, evidence, and implementation ladder

Version: 0.1  
Prepared: 2026-09-20  
Status: proposed design; reproducible static preset census completed. No Surge audio rendering, listening evaluation, native-loader normalization, RTL implementation, or silicon measurements have been performed for this plan.

## Recommendation

Create a companion project, provisionally `gf180-surge`, alongside `gf180-dx7`. Use the contract, pinned-reference, and executable-backlog method from `gf180-torchsynth`, plus audited continuous-audio and physical-integration infrastructure from `gf180-parasynth`. Use Surge's own engine as the sound reference.

The product is a **live, polyphonic hardware instrument preserving a selected set of complete Surge presets, including their effects**. Its scope is a bounded synthesis and effects profile. It is not a promise to run every Surge feature or arbitrary future presets.

The user's latest requirement is explicit: **effects belong in the implementation ladder and are important to the sound**. Therefore effects processing is part of the chip target. An external processor running effects is a separately named fallback product profile, not the default or an invisible dependency. External memory for effect buffers and wavetables is compatible with this chip target.

Choose the 80/20 cut by **complete preferred presets recovered for the incremental hardware cost**, rather than the fraction of menu entries implemented. “20% of features” and “20% of silicon” are not established quantities.

## 1. What has actually been measured

The exploratory corpus is the source snapshot at [`58914e59c608ed4384ba6002e44c3465c58b2e71`](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71), dated 2026-09-18. This is a pinned main-branch snapshot, not a claimed stable release. A production reference can be changed deliberately at the source-selection milestone; doing so requires a new census and baseline.

The census includes every `.fxp` under the two bundled preset directories and excludes test fixtures. All **3,561 input files** were checked against their Git blob identities and sizes in the repository tree.

| Corpus | Presets | Read by this static XML parser | Total FXP bytes |
|---|---:|---:|---:|
| `patches_factory` | 641 | 640 | 24,096,384 |
| `patches_3rdparty` — bundled contributor presets | 2,920 | 2,920 | 245,250,542 |
| Combined | 3,561 | 3,560 | 269,346,926 |

One file, `patches_factory/Percussion/Snare Tight.fxp`, contains a character reference rejected by Python's XML parser. Its bytes match the pinned source. It remains unresolved, rather than being silently repaired, excluded from the total, or described as unplayable in Surge.

### Oscillator-family screen

The following counts use stored scene mode, mute/solo state, inter-oscillator FM, and ring-modulation dependencies to follow the pinned voice-processing branches. A muted oscillator can still be needed as a modulation source. Single mode inspects the selected scene; Dual and Split inspect both scenes.

Percentages use the **full fixed corpus denominators**, including the unresolved file.

| Allowed oscillator families | Factory screen passes / 641 | Contributor screen passes / 2,920 |
|---|---:|---:|
| Classic + Sine | 387 — 60.4% | 851 — 29.1% |
| Classic + Sine + Wavetable | 569 — 88.8% | 1,619 — 55.4% |
| Above + S&H Noise + FM2 + FM3 | 609 — 95.0% | 2,153 — 73.7% |

These are **preliminary necessary-feature screens, not working-preset coverage**. They do not qualify oscillator submodes, filters, waveshapers, modulation, unison, resource limits, or effects. Mixer noise paths are separate from the S&H Noise oscillator family. Scenes needing no oscillator process call can pass this screen without establishing that the rest of their signal path is supported.

This is enough evidence to investigate Classic/Sine/Wavetable early. It is not evidence that three simple oscillators reproduce 89% of Surge. Across both banks the six-family screen passes 2,762/3,561, or 77.6%, before the remaining requirements are considered.

### Effects and scene observations

Among parsed presets, 561/640 factory presets and 2,659/2,920 contributor presets store at least one non-Off effect. These are configured-slot counts, not proof that an effect is audible or indispensable: disabled slots, inactive scenes, sends, and routing still need native analysis and listening.

| Stored effect type | Factory presets containing it | Contributor presets containing it |
|---|---:|---:|
| Delay | 431 | 1,348 |
| Reverb1 | 202 | 1,165 |
| EQ | 188 | 1,037 |
| Phaser | 54 | 211 |
| Distortion | 46 | 385 |
| Conditioner | 43 | 676 |
| Chorus | 26 | 563 |
| Reverb2 | 1 | 707 |
| Airwindows | 3 | 709 |

Delay, Reverb1, and EQ are strong first candidates for the narrow factory-bank objective. Contributor sounds change the priority substantially: for example, Reverb2 and Airwindows appear much more often. An Airwindows slot also has an algorithm selection; counting its top-level type does not make it one small hardware primitive.

| Maximum configured non-Off effect slots | Factory presets within limit / 641 | Contributor presets within limit / 2,920 |
|---|---:|---:|
| 2 | 507 — 79.1% | 1,320 — 45.2% |
| 4 | 635 — 99.1% | 2,178 — 74.6% |
| 8 | 640 — 99.8% | 2,870 — 98.3% |

This supports testing a **four-logical-instance effects budget** first. It is only a slot-count observation. Four expensive effects may cost much more than eight cheap ones, and inactive configured slots may be removable after native normalization.

Single scene mode appears in 604/640 parsed factory presets and 2,357/2,920 contributor presets. A one-scene implementation would exclude additional sounds: the Classic/Sine/Wavetable screen drops from 569 to 541 factory candidates and from 1,619 to 1,396 contributor candidates when Single mode is also required. Prefer a shared scene-voice pool that can accommodate layers and splits if the measured overhead is reasonable.

### Why this census is preliminary

The corpus spans stored patch revisions 4 through 30. Surge's loader performs migrations, including filter remapping and Sine waveform changes. Raw numeric IDs and parameter values cannot all be interpreted as current settings. The next census must load patches through the pinned native engine and inspect normalized state. The supplied script is an auditable inventory and prioritization aid, not a replacement loader.

Sources: [bundled factory data](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71/resources/data/patches_factory), [bundled contributor data](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71/resources/data/patches_3rdparty), [voice processing](https://github.com/surge-synthesizer/surge/blob/58914e59c608ed4384ba6002e44c3465c58b2e71/src/common/dsp/SurgeVoice.cpp), [patch loader and migrations](https://github.com/surge-synthesizer/surge/blob/58914e59c608ed4384ba6002e44c3465c58b2e71/src/common/SurgePatch.cpp).

## 2. Define “most of the good sounds” before choosing hardware cuts

Proposed product goal:

> Reproduce at least 80% of a predeclared 256-preset favorites set from the pinned bundled corpus, including the complete wet signal path and agreed performance controls, within a published chip resource and polyphony profile.

That means at least **205 of the original 256 selections** pass. This is a proposed target, not a demonstrated outcome. Select the favorites by listening before hardware exclusions are known; preserve the original list and rejected selections. Include basses, leads, keys, plucks, pads, rhythmic sounds, and textures from both bundled banks. Also publish results for all 641 factory and all 2,920 contributor presets, so the curated target does not hide general coverage.

“Good” needs a listening judgment. Popularity of an oscillator or effect is not a substitute. A first 32-preset listening set can establish the evaluation process, but it cannot be used to claim the 256-preset goal.

Each preset receives exactly one headline status:

| Status | Required meaning |
|---|---|
| Supported | Original normalized patch graph and resources fit; complete wet output and agreed performance tests pass the fidelity contract. |
| Adapted | Useful variant with specific disclosed edits, such as a replaced reverb, reduced unison, removed layer, or rescaled modulation. Does not count toward original-preset coverage. |
| Unsupported | Required behavior or resources are missing, or fidelity fails. Include machine-readable reasons. |
| Unresolved | Loader, analysis, or evaluation incomplete. Remains in the original denominator. |

Keep three independent checks: **RTL equals the fixed-point model**, **the model meets the upstream sound-fidelity contract**, and **the preset is musically useful**. Success in one does not imply the others.

## 3. Proposed architecture and 80/20 boundary

| Part | Responsibility |
|---|---|
| Host preset compiler | Use the native loader, resolve legacy settings and assets, compile a supported graph, allocate bounded resources, and emit a versioned patch image or explicit rejection. |
| Control host | Preset selection, MIDI/UI, browsing, asset loading, and low-rate commands with specified timing. No requirement to stream every oscillator sample or envelope value. |
| Chip voice engine | Scheduled oscillators, envelopes/LFOs, modulation, mixer/ring/FM paths, filters and per-voice waveshaping. |
| Chip effects engine | Scheduled scene inserts, sends/returns, and global effects with the supported original placement, order, stereo behavior, and feedback semantics. |
| External storage and working memory | Preset/wavetable assets in flash; writable delay/reverb buffers and any required working assets in an explicitly budgeted memory interface. |
| Audio interface | Continuous stereo digital output and external DAC. |

Do not put `.fxp` XML parsing, a preset browser, a GUI, or a general Lua runtime into the ASIC. Compile static structure on the host, while retaining all dynamic behavior promised by the selected profile. A lookup table is acceptable only when it reproduces the relevant behavior; arbitrary live formula modulation cannot simply be baked into a fixed waveform.

### Voice-engine candidate

- Use 48 kHz stereo as the working output-rate hypothesis. Preserve the reference's relevant internal rates and anti-aliasing behavior until measured alternatives pass.
- Investigate eight simultaneously allocated **scene voices** initially. A two-scene layered note consumes two scene voices. Unison consumes additional oscillator work and state; actual per-preset note capacity must be explicit.
- Preserve three logical oscillator positions with shared scheduled arithmetic. Do not start by reducing all patches to two oscillators or one unison voice.
- Start the oscillator work with Classic, Sine, and Wavetable, including the submodes actually required by selected presets. Add FM2/FM3/S&H Noise when whole-preset recovery justifies the cost.
- Preserve the two filter positions and needed topology, with a measured allowlist of filter algorithms/subtypes and waveshapers. A generic ladder filter is not automatically a substitute for every Surge filter.
- Choose envelope, LFO, step-sequencer, MSEG, routing, macro, and controller support from normalized reachable behavior. Stored inactive data is not a reason to implement a feature; an apparently zero level that can be modulated is not a reason to remove it.

Twist, String, Alias, Window, Modern, external audio input, specialized modulation, and expensive effects remain candidates in the cost/coverage comparison. They are not all promised, nor excluded forever by name. Some may recover favored sounds more cheaply than completing another broad family.

### Effects are an early hardware milestone

Start with separate numeric models for **Delay, EQ, and Reverb1**, followed by a complete wet preset through the scheduled hardware path. Rank Phaser, Distortion, Conditioner, Chorus, Reverb2, and particular Airwindows algorithms using preferred-preset recovery and effect-ablation listening results.

Use four logical effect instances as the first resource hypothesis, with independent state and time-shared arithmetic. An instance budget is different from a supported-type count: two Delay slots require two sets of delay state even if they share the same datapath. Permit the selected original placements and ordering; a fixed global `chorus → delay → reverb` chain is insufficient for arbitrary supported presets.

Most scene/send/global effects process summed audio rather than being duplicated for each note. This can make effects a good use of area. Per-voice filters, waveshapers, and modulation retain their original per-voice placement; moving a nonlinear process after the voice sum changes the sound.

Long buffers are the main reason to plan external writable memory early. At 48 kHz, one second of stereo samples stored in 32-bit words occupies **384,000 bytes (375 KiB)**. That is a buffer-size example, not a complete Surge Delay or reverb memory estimate. Interpolation reads, multiple taps, feedback, stereo paths, and concurrent effects determine the actual bandwidth and port requirements. Flash capacity is not a substitute for writable delay memory.

Effect qualification must include wet/dry levels, feedback stability, stereo width, tempo synchronization, parameter modulation, tails after note-off, reset/patch-change behavior, and transitions without unintended clicks. Bypass tests must retain the unmodified wet reference. A substitute generic reverb belongs in an adapted patch unless it passes the defined original-preset fidelity contract.

## 4. Reference hierarchy

| Reference | Use and reason |
|---|---|
| Pinned Surge engine and bundled data | Primary executable sound target and actual patch semantics. Pin sample rate, settings, assets, submodules, compiler, and relevant randomness. |
| Native patch loader | Authoritative migration/default behavior. Required before reliable feature extraction. |
| `surgepy` or upstream headless test infrastructure | Automated loading, MIDI playback, output/stem capture, and controller sweeps without implementing a new synthesizer first. |
| Surge oscillator/filter/effect implementations | Algorithm-specific numeric and state behavior. Read the actual algorithm used by the patch, including wrappers and parameter mapping. |
| Pinned SST libraries | Reusable algorithm references where Surge delegates to them; preserve exact submodule versions and wrapper behavior. |
| Surge XT manual | Explain scene modes, signal routing, controls, and expected musical operation; it is not a bit-exact numeric oracle. |
| Parasynth/TorchSynth/DX7 project infrastructure | Reuse proven transport, CI, model/RTL checks, and physical-flow seams after audit. Their DSP is not an oracle for Surge. |

The reference order matters. Generic DSP texts can explain a delay, filter, or reverb but do not determine Surge's exact parameter mapping, gain, tuning, feedback, or modulation behavior. Likewise, a DX7 six-operator FM core is not automatically a Surge FM2/FM3 implementation.

Relevant primary links:

- [Pinned repository README and build instructions](https://github.com/surge-synthesizer/surge/blob/58914e59c608ed4384ba6002e44c3465c58b2e71/README.md)
- [Python-binding tests](https://github.com/surge-synthesizer/surge/blob/58914e59c608ed4384ba6002e44c3465c58b2e71/src/surge-python/tests/test_surgepy.py)
- [Headless test utilities](https://github.com/surge-synthesizer/surge/blob/58914e59c608ed4384ba6002e44c3465c58b2e71/src/surge-testrunner/HeadlessUtils.cpp)
- [Oscillator implementations](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71/src/common/dsp/oscillators)
- [Effect implementations](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71/src/common/dsp/effects)
- [SST dependency pins](https://github.com/surge-synthesizer/surge/tree/58914e59c608ed4384ba6002e44c3465c58b2e71/libs/sst)
- [Official manual](https://surge-synthesizer.github.io/manual-xt/)

Record source and asset provenance and applicable license files in the build manifest. Surge source headers identify GPL-3.0-or-later; do not assume every dependency and preset has identical terms. This plan does not make a distribution-license determination for a future chip product.

## 5. Cost, fidelity, and acceptance gates

Before freezing the implementation profile, compare candidate bundles using:

1. Complete favorite-preset coverage, with every missing dependency counted.
2. Worst-case cycles per output frame, including unison, both scenes, modulation, effects, and memory waits.
3. On-chip state/table/buffer memory and actual available memory macros.
4. External memory capacity, sustained and burst bandwidth, latency tolerance, and interface pins.
5. Area and timing estimates for the selected GF180 flow, plus board components and power requirements.

A feature's value depends on the other features it unlocks. Count marginal **complete-preset** recovery for bundles; ranking individual oscillator or effect frequencies is insufficient. Keep a Pareto table of alternatives rather than combining area, bandwidth, and coverage into an unexplained score.

The profile must name hard budgets. With clock `F`, output rate `Fs`, and a single scheduled resource, the gross budget is `F/Fs` cycles per output frame; subtract control, transfer, contention, and a declared reserve before allocating DSP. No fit claim is valid without a clock, memory implementation, and measured schedule.

For fidelity, freeze a pilot-derived, versioned acceptance policy before expanding implementation. Include:

- Deterministic fixture resets/seeds where available; otherwise characterize the reference's own variation.
- Notes across low/mid/high registers, soft/medium/hard velocity, short/long holds, releases, repeated notes, and declared polyphony.
- Tempo changes, sustain, bend, modulation wheel, pressure, and exposed macro sweeps; include the controls a preset relies on.
- Both wet and diagnostic dry/stem captures. No per-clip peak normalization that hides gain or drive errors.
- Pitch/timing/gain measurements; envelopes and modulation; spectral/aliasing behavior; filter/feedback stability; stereo and effect-decay behavior.
- Listening comparisons that preserve performance intent. Blind level-matched listening can supplement, but must not replace, level-correct measurements.

Do not require raw waveform subtraction to succeed across uncontrolled noise, free-running phases, or nonlinear trajectories. Conversely, perceptual similarity cannot excuse dropped events or a fixed-point/RTL mismatch.

## 6. Implementation ladder and coder-ready backlog

Milestones: **inventory → native normalized corpus → qualified reference renders → frozen product profile → one complete wet patch → broader preset support → hardware qualification**. Effects enter at the first complete-preset milestone.

Repository structure should make the contract visible: `contracts/`, `corpus/`, `oracle/`, `compiler/`, `model/`, `rtl/`, `fixtures/`, `reports/`, and `decisions/`. Keep large upstream assets and rendered audio content-addressed rather than duplicating them in every issue.

| ID | Depends on | Deliverable and completion condition |
|---|---|---|
| SXT-000 | — | **Done: preliminary static census.** Pin source, verify all 3,561 preset blobs, publish per-preset CSV/summary and explicit parser failures. No audio-support claim. |
| SXT-010 | 000 | **Build the native oracle.** Reproduce pinned engine plus submodules; load all manifest entries; record normalized-load success/failure and environment identity. Resolve `Snare Tight` using native behavior. Capture one note through the real engine. |
| SXT-011 | 010 | **Export normalized patch graphs.** Emit scene/oscillator submodes, filter topology/subtypes, waveshapers, modulation, unison, assets, FX algorithms/slots/routing/bypass, and dynamic dependencies. Include loader defaults/migrations. Unknown behavior produces an explicit analysis failure. |
| SXT-012 | 010 | **Create render fixtures.** Version MIDI/controller/tempo sequences, reset policy, wet output, diagnostic stems, and audio metadata. Demonstrate repeatability or quantified reference variation. No hidden normalization. |
| SXT-013 | 012 | **Freeze favorite selection and fidelity policy.** Produce the 32-preset pilot, then a 256-preset named/hash-addressed listening selection with category coverage. Record ratings and tolerances before hardware cuts; retain all rejected selections. |
| SXT-014 | 011, 012 | **Measure effects' contribution.** For selected patches, render original and one-effect-at-a-time bypass/substitution variants without overwriting originals. Label effects essential, optional by accepted adaptation, or unresolved through listening. Report recovery by exact algorithm, not just FX family. |
| SXT-015 | 011 | **Create resource accounting.** Define per-scene/unison/FX-state accounting, effect-instance and routing limits, asset residency, event timing, bus widths, and memory transactions. Calculate complete-patch costs, not averages alone. |
| SXT-016 | 015 | **Run representative cost probes.** Synthesize or otherwise measure candidate oscillator/filter arithmetic, Delay/EQ/Reverb1 kernels, buffer interfaces, and scheduler overhead against named technology assumptions. Report state RAM separately from logic. These are experiments, not production blocks. |
| SXT-017 | 013, 014, 016 | **Freeze profile v1.** Compare feature bundles and select exact algorithms, submodes, controls, polyphony/unison, FX instance/graph limits, rates, word lengths under investigation, and hard resource budgets. Publish supported/adapted/unsupported predictions with reasons. If targets do not fit, revise the product contract visibly. |
| SXT-020 | 011, 017 | **Compile patch images.** Define a versioned IR/binary image with source hashes, dynamic routes, assets, allocations, and checksums. Compiler emits explicit rejection for every unsupported path or resource overflow; never silently drops a feature. |
| SXT-021 | 017, 020 | **Implement timed control and scheduling.** Define reset, event queues, note allocation/stealing, patch changes and audio framing. Demonstrate continuous output and worst-case schedule accounting using a simple stub engine. |
| SXT-022 | 012, 017 | **Qualify a first dry voice slice.** Choose one native-normalized real preset requiring a small supported voice graph. Implement its numeric model and scheduled RTL; compare internal states exactly to the model and audio to the upstream reference. This is a diagnostic milestone, not the wet product acceptance gate. |
| SXT-023 | 012, 017 | **Implement Delay and EQ as separate leaf tasks.** Each gets floating/reference fixtures, a fixed model, explicit state/parameter semantics, cycle/RAM costs, and RTL/model equality. Include feedback, interpolation, modulation, bypass, and stereo where applicable. |
| SXT-024 | 012, 017 | **Implement Reverb1.** Qualify impulse/decay and preset-audio behavior, damping/modulation/stereo, tail handling, memory traffic, and fixed-point stability. Report the measured buffer requirement; do not substitute a generic reverb under the same support claim. |
| SXT-025 | 020–024 | **Pass one complete wet preset.** Run original voice graph plus all its selected effects through the integrated chip model/RTL. Verify event-to-output timing, placement/order/gain, memory stalls, tails, and fidelity to the same upstream fixture. |
| SXT-026 | 017, 020, 021 | **Add Wavetable asset and playback support.** Preserve required interpolation, morphing, mip/anti-aliasing behavior and modulation. Validate asset identity and residency, pitch extremes, maximum supported unison, and bandwidth under concurrent effects. Split asset compiler and oscillator RTL into separate leaf issues. |
| SXT-027 | 017, 022 | **Generate remaining voice-feature leaf issues.** One algorithm/submode/topology per issue, ordered by whole-preset recovery. Include selected FM2/FM3/noise/filter/waveshaper/modulation behavior. Each must name exact newly enabled presets and use the template below. |
| SXT-028 | 014, 017, 023, 024 | **Expand effects by measured recovery.** Generate separate tasks for selected Phaser/Distortion/Conditioner/Chorus/Reverb2/Airwindows algorithms and missing routing forms. Preserve state and tails under the shared instance schedule. No monolithic “port all FX” task. |
| SXT-029 | 025–028 | **Run full qualification and publish coverage.** For every corpus entry emit one status, missing reasons, measured fidelity result where evaluated, patch adaptations, resource use, and actual polyphony. Report favorites, factory, and contributor denominators separately. |
| SXT-030 | 025, 026 | **Qualify FPGA and external memory.** Play live MIDI while effects and worst-case asset traffic run. Measure latency, underruns, memory stalls, long-tail stability, reset behavior, and power/interface assumptions. Additional selected features rerun their affected cases. |
| SXT-031 | 029, 030 | **Qualify the GF180 implementation.** Complete named area/timing/memory/pin and physical-flow gates at the selected corners; preserve the proven audio contract. Release only the measured support profile and reproducible manifest. |

Ranges in the dependency table mean all applicable generated leaves needed by the chosen profile, not every possible Surge algorithm. A row describing a family of leaf issues is an issue generator, not a coder's single implementation ticket.

### Leaf issue template

Every executable coding issue includes:

- **Behavior and scope:** one exact algorithm, subtype, routing form, or boundary; source commit and relevant functions.
- **Inputs/outputs/state:** widths, units, rates, initialization, reset, event timing, and memory ownership.
- **Fixtures and oracle:** named source presets, MIDI sequences, parameter corners, reference traces, and hashes.
- **Acceptance:** fixed-model/RTL equality where applicable, upstream fidelity thresholds, stability limits, cycle/state/memory bounds, and failure behavior.
- **Deliverables:** exact model/RTL/compiler/fixture/report paths and the command that verifies them.
- **Dependencies and recovery:** blocking issue IDs and the complete presets this change makes newly supportable.

The next executable task is **SXT-010**. SXT-000 is useful completed work but cannot justify announcing supported sounds.

## 7. Relationship to the DX7 effort

Keep DX7 as the smaller first synthesis core. Let Surge source normalization, listening selection, and effect investigations progress without waiting for DX7 silicon. Share only established seams such as event transport, audio output, external-memory arbitration, verification tooling, and a qualified effects service.

A common effects block could later serve both instruments, but must preserve each instrument's declared routing and gain. Do not delay either core while designing a universal synthesizer framework. The important commonality is the development contract: pinned sound reference, explicit hardware budget, real preset milestones, and measured support claims.

## 8. Reproducibility package

The companion ZIP contains `census.py`, `corpus-manifest.json`, `source-lock.json`, `results/summary.json`, `results/per-preset.csv`, and reproduction instructions. It contains no factory preset payloads, wavetables, source archive, or rendered audio. The static census uses Python's standard library and reads the pinned source archive without extracting its paths.

Verified here: all manifest file identities and sizes, deterministic census completion, fixed denominators, summary/CSV consistency, and retention of the one XML-parser failure. Still outstanding: every native-loader, sound-quality, cost, and hardware claim described in the backlog.
