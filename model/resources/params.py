"""Named parameters for SXT-015 resource accounting.

Every number the accounting model uses lives here, with:
  - kind: "engine_constant"  value read as a fact from the pinned engine tree
                          (cited file:line in `estimate_ref`; GPL source is
                          READ, never copied into this repository);
          "policy"          a declared convention of this model (this
                          repository's own decision, not an engine fact);
          "placeholder"     a named default that exists only so the closure
                          machinery is executable; SXT-016 must replace it
                          with measured technology values (NO technology
                          claim is made by this issue);
          "corpus_derived"  computed from committed data (fixtures/graphs).
`estimate_ref` entries tagged ESTIMATE-REF mark items SXT-016/023 must
re-pin or replace.

Determinism: parameter iteration order is fixed (declaration order); the
JSON dump is sorted and stable for a given code version.
"""
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class Param:
    name: str
    value: Any
    unit: str
    kind: str  # engine_constant | policy | placeholder | corpus_derived
    estimate_ref: str
    note: str = ""


def _P(name, value, unit, kind, ref, note=""):
    return Param(name, value, unit, kind, ref, note)


PARAMS: List[Param] = [
    # --- engine pin / rates -------------------------------------------------
    _P("sample_rate_hz", 48000, "Hz", "engine_constant",
       "corpus/normalized/schema.json pin (surgepy self-report, SXT-010)"),
    _P("fx_frame_block_size", 32, "samples", "engine_constant",
       "SURGE_COMPILE_BLOCK_SIZE default 32 (src/CMakeLists.txt; oracle/manifest.json runtime)"),
    # --- voice / scene structure -------------------------------------------
    _P("max_unison", 16, "voices", "engine_constant",
       "MAX_UNISON=16 (src/common/globals.h:64)"),
    _P("polylimit_default", 16, "voices", "engine_constant",
       "DEFAULT_POLYLIMIT=16 (src/common/globals.h:68; SurgePatch.cpp:102)"),
    _P("voice_pool_limit", 32, "voices", "policy",
       "SXT-015 declared model cap on simultaneously allocated voices; "
       "plan section 3 starts at 8 scene voices; SXT-017 freezes the real pool"),
    _P("n_osc_slots_per_scene", 3, "slots", "engine_constant",
       "n_oscs=3 (src/common/globals.h; corpus schema sc[].osc items:3)"),
    _P("n_filter_units_per_scene", 2, "units", "engine_constant",
       "fu[] items:2 (schema); QuadFilterChainState FU[2]"),
    _P("n_lfos_voice", 6, "instances", "engine_constant",
       "n_lfos_voice=6 (src/common/SurgeStorage.h:74); per-voice LFO instances "
       "(SurgeVoice.cpp calc_ctrldata loops n_lfos_voice)"),
    _P("n_lfos_scene", 6, "instances", "engine_constant",
       "n_lfos_scene=6 (src/common/SurgeStorage.h:75); scene-level LFO (SLFO) "
       "state. SXT-011 exports only the 6 voice LFO defs per scene; the SLFO "
       "defs are an exposure gap counted here at the engine constant"),
    _P("n_envelopes_per_voice", 2, "instances", "engine_constant",
       "AEG+FilterEG (SurgeVoice modsources ms_ampeg/ms_filtereg)"),
    _P("n_mixer_paths_per_voice", 6, "paths", "engine_constant",
       "o1,o2,o3,ring_12,ring_23,noise (schema mix object)"),
    # --- per-instance FX state (long buffers; exact pinned constants) -------
    _P("delay_max_length_samples", 1 << 18, "samples", "engine_constant",
       "ESTIMATE-REF:sst max_delay_length{1<<18} per channel "
       "(libs/sst/sst-effects/include/sst/effects/Delay.h:200); SXT-023 must "
       "re-pin and confirm state/traffic semantics"),
    _P("floaty_delay_max_length_samples", 1 << 19, "samples", "engine_constant",
       "ESTIMATE-REF:sst max_delay_length{1<<19} "
       "(libs/sst/sst-effects/include/sst/effects/FloatyDelay.h:164)"),
    _P("delay_channels", 2, "channels", "engine_constant",
       "Delay.h line[2][...] stereo pair"),
    _P("delay_mod_margin_semitones", 12.0, "semitones", "placeholder",
       "ESTIMATE-REF: delay time is modulated "
       "(Delay.h setvars: time = sr*noteToPitchIgnoringTuning(12*f(time)) + LFOval; "
       "dly_mod_depth in the ±depth of that exponent). Margin on the exponent "
       "for param-derived sizing; SXT-023 must confirm the exact modulatable range"),
    _P("reverb1_revbits", 15, "bits", "engine_constant",
       "ESTIMATE-REF:sst Reverb1.h:122 revbits=15 => max_rev_dly=32768"),
    _P("reverb1_rev_taps", 16, "taps", "engine_constant",
       "ESTIMATE-REF:sst Reverb1.h:124-125 rev_taps=16; composite buffer "
       "delay[rev_taps*max_rev_dly] floats (Reverb1.h:129)"),
    _P("reverb2_max_allpass_len", 131072, "samples", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:66 MAX_ALLPASS_LEN=16384*8"),
    _P("reverb2_max_delay_len", 131072, "samples", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:67 MAX_DELAY_LEN=16384*8"),
    _P("reverb2_input_allpasses", 4, "instances", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:64 NUM_INPUT_ALLPASSES=4 (Reverb2.h:209)"),
    _P("reverb2_blocks", 4, "blocks", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:63 NUM_BLOCKS=4"),
    _P("reverb2_allpasses_per_block", 2, "instances", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:65 NUM_ALLPASSES_PER_BLOCK=2 (Reverb2.h:210)"),
    _P("reverb2_delays", 4, "instances", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:213 _delay[NUM_BLOCKS]"),
    _P("reverb2_predelay_samples", 1536000, "samples", "engine_constant",
       "ESTIMATE-REF:sst Reverb2.h:71-72 PREDELAY_BUFFER_SIZE=48000*8*4 "
       "(comment: max sample rate 48000*8); single shared predelay buffer"),
    _P("chorus_buffer_samples", (1 << 18) + 12, "samples", "engine_constant",
       "ESTIMATE-REF: ChorusEffect.h buffer[max_delay_length+FIRipol_N] with "
       "max_delay_length=1<<18 (src/common/dsp/Effect.h:137) and FIRipol_N=12 "
       "(src/common/SurgeStorage.h:87); mono shared buffer"),
    _P("chorus_voices", 4, "voices", "engine_constant",
       "Effect.cpp:86 instantiates ChorusEffect<4>"),
    _P("flanger_delay_size", 32768, "samples", "engine_constant",
       "ESTIMATE-REF:sst Flanger.h:162-168 InterpDelay::DELAY_SIZE=32768; "
       "idels[2] (one per channel)"),
    _P("flanger_combs_per_channel", 4, "combs", "engine_constant",
       "ESTIMATE-REF:sst Flanger.h:162 COMBS_PER_CHANNEL=4 (interpolated taps "
       "into the same per-channel line)"),
    _P("unverified_fx_state_bytes", 1048576, "bytes", "placeholder",
       "ESTIMATE-REF: default per-instance state for FX classes whose exact "
       "buffer structure is not yet pinned (Convolution/Nimbus/Vocoder/Tape/"
       "Spring and other small-state classes); deliberately conservative "
       "(1 MiB) so unknown classes do not silently look cheap; each such "
       "instance is flagged class_state_unverified. SXT-028 leaf issues must "
       "replace this with per-class pinned numbers"),
    # --- on-chip voice state sizing (placeholders; SXT-016 re-derives at the
    # --- selected word lengths) ---------------------------------------------
    _P("voice_base_state_bytes", 4096, "bytes", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per voice: envelopes, "
       "mixer/ring/FM registers, filter state excluded (counted separately)"),
    _P("osc_state_bytes_per_unison", 512, "bytes", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per unison voice per "
       "active oscillator slot (phase, feedback, interpolation state); "
       "SXT-016 re-derives at fixed-point word lengths"),
    _P("filter_unit_state_bytes", 256, "bytes", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per active filter unit "
       "per voice; SXT-016"),
    _P("lfo_state_bytes", 256, "bytes", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per LFO instance; "
       "MSEG/Formula curve storage is an SXT-011 exposure gap and is NOT "
       "included (flagged)"),
    _P("wt_working_set_bytes", 65536, "bytes", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, on-chip working set per "
       "active wavetable osc slot (shared across voices); table bytes "
       "themselves are flash assets; mip/morph behavior is SXT-026 work"),
    # --- memory classification ----------------------------------------------
    _P("mem_word_bytes", 4, "bytes", "policy",
       "float32 working word; fixed-point re-derivation is SXT-016/023 work"),
    _P("external_threshold_bytes", 65536, "bytes", "policy",
       "writable buffer class > 64 KiB is classified external writable "
       "(plan section 3: long buffers are the reason for external writable "
       "memory); flash is NEVER writable delay/reverb storage"),
    _P("flash_writable", 0, "bool", "policy",
       "plan section 3: 'Flash capacity is not a substitute for writable "
       "delay memory' — assets only"),
    _P("ext_bandwidth_budget_bytes_per_s", 800000000, "bytes/s", "placeholder",
       "ESTIMATE-REF: named placeholder external-memory sustained-bandwidth "
       "assumption for closure demonstrations; SXT-016 and the DX7 H01/H02 "
       "arbitration alignment (plan section 7) must replace it"),
    # --- budget closure (plan section 5) ------------------------------------
    _P("clock_hz", 480000000, "Hz", "placeholder",
       "ESTIMATE-REF: named placeholder clock F; gross budget F/Fs per output "
       "frame (plan section 5). SXT-016 must replace with a measured/assumed "
       "gf180mcu timing result"),
    _P("reserve_fraction", 0.2, "fraction", "policy",
       "plan section 5: subtract control, transfer, contention and a declared "
       "reserve before allocating DSP"),
    _P("cost_profile", "placeholder-v0", "-", "placeholder",
       "ALL per-frame cycle costs below are named placeholders so the closure "
       "machinery is executable; they support NO technology claim. SXT-016 "
       "replaces the profile with measured kernel costs"),
    _P("cyc_osc_unison_voice_frame", 200, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per unison voice per frame "
       "per active oscillator slot; SXT-016"),
    _P("cyc_filter_unit_frame", 150, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per active filter unit per "
       "voice per frame; SXT-016"),
    _P("cyc_waveshaper_frame", 50, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per voice with active "
       "waveshaper; SXT-016"),
    _P("cyc_lfo_frame", 30, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per LFO instance per frame; SXT-016"),
    _P("cyc_env_frame", 20, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per envelope per voice; SXT-016"),
    _P("cyc_modroute_frame", 15, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per mod routing row per "
       "frame; SXT-016"),
    _P("cyc_fxdelay_frame", 900, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per Delay/FloatyDelay "
       "instance per frame (stereo); SXT-016/SXT-023"),
    _P("cyc_fxreverb1_frame", 2600, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per Reverb1 instance "
       "(16 composite taps); SXT-016/SXT-024"),
    _P("cyc_fxreverb2_frame", 3200, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per Reverb2 instance "
       "(12 allpass + 4 delay blocks); SXT-016/SXT-028"),
    _P("cyc_fxchorus_frame", 1200, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per Chorus instance "
       "(4 voices); SXT-016"),
    _P("cyc_fxflanger_frame", 1000, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per Flanger instance; SXT-016"),
    _P("cyc_fxgeneric_frame", 800, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per any other FX class "
       "instance; SXT-016/SXT-028"),
    _P("cyc_event_frame", 40, "cycles", "placeholder",
       "ESTIMATE-REF: cost profile placeholder-v0, per queued MIDI event "
       "processed in the frame; SXT-016/SXT-021"),
    # --- event timing --------------------------------------------------------
    _P("event_queue_depth", 16, "events", "corpus_derived",
       "fixtures/sequences/: worst observed coincident events in one frame is "
       "8 (seq-poly-8-v1 note-ons at t=0); rounded up to the next power of "
       "two with headroom. Depth is a model requirement, not a measured "
       "hardware queue"),
    # --- candidate FX instance limits (NOT frozen product limits) ------------
    _P("fx_instance_limit_candidates", [4, 8], "instances", "policy",
       "plan section 3 tests a four-logical-instance budget first; the corpus "
       "scan reports fits for the candidate set {4,8}. SXT-017 freezes the "
       "actual limits; these are NOT support claims"),
]


class ParamRegistry:
    """Fixed-order parameter registry; JSON-stable."""

    def __init__(self):
        self._p: Dict[str, Param] = {}
        for prm in PARAMS:
            if prm.name in self._p:
                raise ValueError("duplicate param %s" % prm.name)
            self._p[prm.name] = prm

    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, "_p")[name].value
        except KeyError:
            raise AttributeError(name)

    def get(self, name):
        return self._p[name]

    def override(self, name, value):
        """Deterministic, scoped parameter override (context manager).

        Used by negative controls and experiments ONLY; every account that
        used an override must record it (params_digest changes accordingly).
        """
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            old = self._p[name]
            self._p[name] = Param(old.name, value, old.unit, old.kind,
                                  old.estimate_ref + " [OVERRIDDEN for a "
                                  "declared experiment/negative control]",
                                  old.note)
            try:
                yield
            finally:
                self._p[name] = old
        return _ctx()

    def to_json(self) -> List[Dict]:
        return [
            {
                "name": p.name,
                "value": p.value,
                "unit": p.unit,
                "kind": p.kind,
                "estimate_ref": p.estimate_ref,
                "note": p.note,
            }
            for p in PARAMS
        ]


REG = ParamRegistry()
