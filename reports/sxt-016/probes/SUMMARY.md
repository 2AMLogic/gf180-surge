# SXT-016 probe summary (machine-generated; deterministic)

All values are ESTIMATES under named assumptions (each record embeds them). No gf180mcu synthesis/PnR/signoff has been run. clocks: 48 MHz, 96 MHz, 192 MHz, 480 MHz x Fs = 48 kHz; gross cycles/frame = 1000, 2000, 4000, 10000.

## Records

| record | kernel | xMult | phase | cyc/sample | cyc/frame | state RAM bits | ext B/frame | replaces (SXT-015) |
|---|---|---|---:|---:|---:|---:|---:|---|
| `probe_filter__k35_ladder_tanh_lut__a24__m18__onchip` | k35_ladder_tanh_lut | M18 | - | 144.0 | 6912000 | 584 | 0 | cyc_filter_unit_frame |
| `probe_filter__k35_ladder_tanh_lut__a24__m32__onchip` | k35_ladder_tanh_lut | M32 | - | 72.0 | 3456000 | 584 | 0 | cyc_filter_unit_frame |
| `probe_filter__k35_ladder_tanh_poly__a24__m18__onchip` | k35_ladder_tanh_poly | M18 | - | 170.0 | 8160000 | 584 | 0 | cyc_filter_unit_frame |
| `probe_filter__k35_ladder_tanh_poly__a24__m32__onchip` | k35_ladder_tanh_poly | M32 | - | 80.0 | 3840000 | 584 | 0 | cyc_filter_unit_frame |
| `probe_filter__svf_tdf2_block_coeffs__a24__m18__onchip` | svf_tdf2_block_coeffs | M18 | - | 80.0 | 3840000 | 192 | 0 | cyc_filter_unit_frame |
| `probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip` | svf_tdf2_block_coeffs | M32 | - | 32.0 | 1536000 | 192 | 0 | cyc_filter_unit_frame |
| `probe_filter__svf_tdf2_per_sample_coeffs__a24__m18__onchip` | svf_tdf2_per_sample_coeffs | M18 | - | 110.0 | 5280000 | 192 | 0 | cyc_filter_unit_frame |
| `probe_filter__svf_tdf2_per_sample_coeffs__a24__m32__onchip` | svf_tdf2_per_sample_coeffs | M32 | - | 44.0 | 2112000 | 192 | 0 | cyc_filter_unit_frame |
| `probe_fx_delay__delay_stereo_ext_E1__a24__m18__e1` | delay_stereo_ext_E1 | M18 | - | - | 1598 | 1106 | 16 | cyc_fxdelay_frame + ext traffic re-pin for delay |
| `probe_fx_delay__delay_stereo_ext_E1__a24__m32__e1` | delay_stereo_ext_E1 | M32 | - | - | 1406 | 1106 | 16 | cyc_fxdelay_frame + ext traffic re-pin for delay |
| `probe_fx_delay__delay_stereo_ext_E2__a24__m18__e2` | delay_stereo_ext_E2 | M18 | - | - | 528 | 1106 | 16 | cyc_fxdelay_frame + ext traffic re-pin for delay |
| `probe_fx_delay__delay_stereo_ext_E2__a24__m32__e2` | delay_stereo_ext_E2 | M32 | - | - | 336 | 1106 | 16 | cyc_fxdelay_frame + ext traffic re-pin for delay |
| `probe_fx_delay__delay_stereo_ext_E3__a24__m18__e3` | delay_stereo_ext_E3 | M18 | - | - | 422 | 1106 | 16 | cyc_fxdelay_frame + ext traffic re-pin for delay |
| `probe_fx_delay__delay_stereo_ext_E3__a24__m32__e3` | delay_stereo_ext_E3 | M32 | - | - | 230 | 1106 | 16 | cyc_fxdelay_frame + ext traffic re-pin for delay |
| `probe_fx_delay__delay_stereo_onchip_line__a24__m18__onchip` | delay_stereo_onchip_line | M18 | - | - | 376 | 12583250 | 0 | cyc_fxdelay_frame |
| `probe_fx_delay__delay_stereo_onchip_line__a24__m32__onchip` | delay_stereo_onchip_line | M32 | - | - | 184 | 12583250 | 0 | cyc_fxdelay_frame |
| `probe_fx_eq__eq3band_tdf2_block_coeffs__a24__m18__onchip` | eq3band_tdf2_block_coeffs | M18 | - | - | 171 | 768 | 0 | cyc_fxgeneric_frame (for the EQ class instance) |
| `probe_fx_eq__eq3band_tdf2_block_coeffs__a24__m32__onchip` | eq3band_tdf2_block_coeffs | M32 | - | - | 81 | 768 | 0 | cyc_fxgeneric_frame (for the EQ class instance) |
| `probe_fx_eq__eq3band_tdf2_per_sample_coeffs__a24__m18__onchip` | eq3band_tdf2_per_sample_coeffs | M18 | - | - | 321 | 768 | 0 | cyc_fxgeneric_frame (for the EQ class instance) |
| `probe_fx_eq__eq3band_tdf2_per_sample_coeffs__a24__m32__onchip` | eq3band_tdf2_per_sample_coeffs | M32 | - | - | 141 | 768 | 0 | cyc_fxgeneric_frame (for the EQ class instance) |
| `probe_fx_reverb1__reverb1_composite_ext_E1__a24__m18__e1` | reverb1_composite_ext_E1 | M18 | - | - | 3223 | 2223 | 136 | cyc_fxreverb1_frame + reverb1 traffic confirmation |
| `probe_fx_reverb1__reverb1_composite_ext_E1__a24__m32__e1` | reverb1_composite_ext_E1 | M32 | - | - | 2875 | 2223 | 136 | cyc_fxreverb1_frame + reverb1 traffic confirmation |
| `probe_fx_reverb1__reverb1_composite_ext_E2__a24__m18__e2` | reverb1_composite_ext_E2 | M18 | - | - | 1183 | 2223 | 136 | cyc_fxreverb1_frame + reverb1 traffic confirmation |
| `probe_fx_reverb1__reverb1_composite_ext_E2__a24__m32__e2` | reverb1_composite_ext_E2 | M32 | - | - | 835 | 2223 | 136 | cyc_fxreverb1_frame + reverb1 traffic confirmation |
| `probe_fx_reverb1__reverb1_composite_ext_E3__a24__m18__e3` | reverb1_composite_ext_E3 | M18 | - | - | 911 | 2223 | 136 | cyc_fxreverb1_frame + reverb1 traffic confirmation |
| `probe_fx_reverb1__reverb1_composite_ext_E3__a24__m32__e3` | reverb1_composite_ext_E3 | M32 | - | - | 563 | 2223 | 136 | cyc_fxreverb1_frame + reverb1 traffic confirmation |
| `probe_osc__classic_blit__ph16__a24__m18__onchip` | classic_blit | M18 | 16 | 352.7 | 16929600 | 10258 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph16__a24__m32__onchip` | classic_blit | M32 | 16 | 175.8 | 8438400 | 10258 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph18__a24__m18__onchip` | classic_blit | M18 | 18 | 352.7 | 16929600 | 10262 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph18__a24__m32__onchip` | classic_blit | M32 | 18 | 175.8 | 8438400 | 10262 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph24__a24__m18__onchip` | classic_blit | M18 | 24 | 352.7 | 16929600 | 10274 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph24__a24__m32__onchip` | classic_blit | M32 | 24 | 175.8 | 8438400 | 10274 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph32__a24__m18__onchip` | classic_blit | M18 | 32 | 352.7 | 16929600 | 10290 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_blit__ph32__a24__m32__onchip` | classic_blit | M32 | 32 | 175.8 | 8438400 | 10290 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__classic_naive_plus_lp__ph16__a24__m18__onchip` | classic_naive_plus_lp | M18 | 16 | 25.0 | 1200000 | 64 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph16__a24__m32__onchip` | classic_naive_plus_lp | M32 | 16 | 13.0 | 624000 | 64 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph18__a24__m18__onchip` | classic_naive_plus_lp | M18 | 18 | 25.0 | 1200000 | 66 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph18__a24__m32__onchip` | classic_naive_plus_lp | M32 | 18 | 13.0 | 624000 | 66 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph24__a24__m18__onchip` | classic_naive_plus_lp | M18 | 24 | 25.0 | 1200000 | 72 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph24__a24__m32__onchip` | classic_naive_plus_lp | M32 | 24 | 13.0 | 624000 | 72 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph32__a24__m18__onchip` | classic_naive_plus_lp | M18 | 32 | 25.0 | 1200000 | 80 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__classic_naive_plus_lp__ph32__a24__m32__onchip` | classic_naive_plus_lp | M32 | 32 | 13.0 | 624000 | 80 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__sine_poly_fastmath__ph16__a24__m18__onchip` | sine_poly_fastmath | M18 | 16 | 78.8 | 3782400 | 208 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph16__a24__m32__onchip` | sine_poly_fastmath | M32 | 16 | 33.3 | 1598400 | 208 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph18__a24__m18__onchip` | sine_poly_fastmath | M18 | 18 | 78.8 | 3782400 | 210 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph18__a24__m32__onchip` | sine_poly_fastmath | M32 | 18 | 33.3 | 1598400 | 210 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph24__a24__m18__onchip` | sine_poly_fastmath | M18 | 24 | 78.8 | 3782400 | 216 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph24__a24__m32__onchip` | sine_poly_fastmath | M32 | 24 | 33.3 | 1598400 | 216 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph32__a24__m18__onchip` | sine_poly_fastmath | M18 | 32 | 78.8 | 3782400 | 224 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_poly_fastmath__ph32__a24__m32__onchip` | sine_poly_fastmath | M32 | 32 | 33.3 | 1598400 | 224 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph16__a24__m18__onchip` | sine_table | M18 | 16 | 47.8 | 2294400 | 208 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph16__a24__m32__onchip` | sine_table | M32 | 16 | 23.3 | 1118400 | 208 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph18__a24__m18__onchip` | sine_table | M18 | 18 | 47.8 | 2294400 | 210 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph18__a24__m32__onchip` | sine_table | M32 | 18 | 23.3 | 1118400 | 210 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph24__a24__m18__onchip` | sine_table | M18 | 24 | 47.8 | 2294400 | 216 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph24__a24__m32__onchip` | sine_table | M32 | 24 | 23.3 | 1118400 | 216 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph32__a24__m18__onchip` | sine_table | M18 | 32 | 47.8 | 2294400 | 224 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__sine_table__ph32__a24__m32__onchip` | sine_table | M32 | 32 | 23.3 | 1118400 | 224 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph16__a24__m18__onchip` | wavetable_blit | M18 | 16 | 262.3 | 12590400 | 49266 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph16__a24__m32__onchip` | wavetable_blit | M32 | 16 | 139.9 | 6715200 | 49266 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph18__a24__m18__onchip` | wavetable_blit | M18 | 18 | 262.3 | 12590400 | 49268 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph18__a24__m32__onchip` | wavetable_blit | M32 | 18 | 139.9 | 6715200 | 49268 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph24__a24__m18__onchip` | wavetable_blit | M18 | 24 | 262.3 | 12590400 | 49274 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph24__a24__m32__onchip` | wavetable_blit | M32 | 24 | 139.9 | 6715200 | 49274 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph32__a24__m18__onchip` | wavetable_blit | M18 | 32 | 262.3 | 12590400 | 49282 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_blit__ph32__a24__m32__onchip` | wavetable_blit | M32 | 32 | 139.9 | 6715200 | 49282 | 0 | cyc_osc_unison_voice_frame |
| `probe_osc__wavetable_direct_interp__ph16__a24__m18__onchip` | wavetable_direct_interp | M18 | 16 | 39.0 | 1872000 | 49290 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph16__a24__m32__onchip` | wavetable_direct_interp | M32 | 16 | 21.0 | 1008000 | 49290 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph18__a24__m18__onchip` | wavetable_direct_interp | M18 | 18 | 39.0 | 1872000 | 49292 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph18__a24__m32__onchip` | wavetable_direct_interp | M32 | 18 | 21.0 | 1008000 | 49292 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph24__a24__m18__onchip` | wavetable_direct_interp | M18 | 24 | 39.0 | 1872000 | 49298 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph24__a24__m32__onchip` | wavetable_direct_interp | M32 | 24 | 21.0 | 1008000 | 49298 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph32__a24__m18__onchip` | wavetable_direct_interp | M18 | 32 | 39.0 | 1872000 | 49306 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_osc__wavetable_direct_interp__ph32__a24__m32__onchip` | wavetable_direct_interp | M32 | 32 | 21.0 | 1008000 | 49306 | 0 | none (adaptation candidate; NOT a pin of cyc_osc_unison_voice_frame) |
| `probe_scheduler__event_queue_and_control__a24__m18__onchip` | event_queue_and_control | M18 | - | - | 818 | 512 | 0 | cyc_event_frame |
| `probe_scheduler__event_queue_and_control__a24__m32__onchip` | event_queue_and_control | M32 | - | - | 776 | 512 | 0 | cyc_event_frame |

## Worked bundles (Pareto-style; alternatives uncombined - no single score)

| Bundle | xMult | total cyc/frame | @48M | @96M | @192M | @480M | RAM bits | ext B/frame |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| july | M18 | 16230 | OVERFLOW (1623%) | OVERFLOW (811%) | OVERFLOW (406%) | OVERFLOW (162%) | 26097824 | 24 |
| july | M32 | 11581 | OVERFLOW (1158%) | OVERFLOW (579%) | OVERFLOW (290%) | OVERFLOW (116%) | 26097824 | 24 |
| supersaw | M18 | 550845 | OVERFLOW (55085%) | OVERFLOW (27542%) | OVERFLOW (13771%) | OVERFLOW (5508%) | 125778880 | 252 |
| supersaw | M32 | 279085 | OVERFLOW (27908%) | OVERFLOW (13954%) | OVERFLOW (6977%) | OVERFLOW (2791%) | 125778880 | 252 |
| covered_worst_synth | M18 | 282890 | OVERFLOW (28289%) | OVERFLOW (14144%) | OVERFLOW (7072%) | OVERFLOW (2829%) | 215923 | 168 |
| covered_worst_synth | M32 | 143862 | OVERFLOW (14386%) | OVERFLOW (7193%) | OVERFLOW (3597%) | OVERFLOW (1439%) | 215923 | 168 |

Closure columns combine the plan-section-5 formula (gross F/Fs, minus 20% reserve, minus transfer 8 and contention 990 cyc/frame) with the bundle's total cycles/frame. Percentage is utilization of gross. Rows flagged with placeholder components carry SXT-015 placeholder-v0 values for uncovered classes (see `worked-bundles.json` `flags`); `covered_worst_synth` has none.

External-bandwidth fit per bundle (bytes/frame x 48k vs E-model sustained): see `closure_at_clocks` in `worked-bundles.json`.

## Headline findings (estimates, not measurements)

1. Under scalar single-lane arithmetic (A-SCHED-1) NO worked bundle closes at any candidate clock: the worst-pitch-corner BLIT oscillator cost dominates (classic 175.8-352.7 cyc/sample/instance, wavetable 139.9-262.3). Closure therefore requires parallel lanes, reduced unison (an adaptation), cheaper oscillator candidates (adaptations), or higher clocks - SXT-017 tradeoffs, quantified in the bundles.
2. Phase-word width moves state RAM, not cycles (24-bit audio muls dominate via the MAC decomposition): 16 vs 32-bit phase costs the same cycles/instance and differs by 32 state bits/instance (Classic).
3. Delay physical external traffic is model-dependent: 24 words/frame naive vs ~4 words/frame with the named sliding-window cache (A-EXT-BUF); SXT-015's 6r+2w was a logical count. Reverb1's 34 scattered words/frame are latency-bound, not bandwidth-bound (990 cyc/frame contention at E1).
4. Reverb1 fixed-point guard band: at max decay the zero-latency loop spectral radius approaches 1 (rho=0.99995), i.e. ~15 guard bits for quantization noise; internal reverb words need 24+15 bits or a shorter max-decay cap (SXT-024 decision input).
5. Scheduler: 91 cyc/event (worst 8 coincident events re-derived from fixtures, matching SXT-015), 90 cyc/frame fixed control - small vs voice cost.

## Negative control

`negative-control/nc-underspecified-record.json`: a record with unstated clock/memory/word-length assumptions is REFUSED by validate/write - the mechanical exclusion SXT-017 relies on.
