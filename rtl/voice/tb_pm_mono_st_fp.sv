// SXT-043 RTL control-plane slice: playmode submode pm_mono_st_fp ("Mono,
// Single Trigger & Fingered Portamento") -- voice allocation / articulation
// state machine, implementing the SAME integer schedule as the frozen
// fixed-point model (model/voice/playmode/pm_mono_st_fp.py,
// model/voice/playmode/run_model.py).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared block-boundary checkpoint, every pool
// slot; enforced by tools/compare_pm_rtl_model.py). NOT synthesis-closed,
// NOT timing-closed; no gf180mcu FPGA/ASIC claim of any kind.
//
// DECLARED MODEL/RTL BOUNDARY (see run_model.py docstring): this RTL is the
// ARTICULATION LAYER only -- allocation/legato/reclaim/release, the
// amp-envelope state machine (including attackFrom(level) and uber_release),
// the SLOW_EXP velocity smoother, and the portamento ramp. It does NOT
// reimplement the oscillator/filter/output-staging audio datapath, which is
// already covered integer-exactly by the landed SXT-022/026a/034/040 RTL
// (rtl/voice/tb_voice.sv) and is unchanged by this leaf.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/SurgeStorage.h       play_mode, MonoVoicePriorityMode,
//                                   MonoVoiceEnvelopeMode, porta_curve
//   src/common/SurgeStorage.cpp     table_glide_log/table_glide_exp,
//                                   glide_log/glide_exp, envelope_rate_linear
//   src/common/SurgeSynthesizer.cpp playNote/playVoice (pm_mono_st*),
//                                   releaseNote/releaseNotePostHoldCheck,
//                                   reclaimVoiceFor
//   src/common/dsp/SurgeVoice.cpp/.h legato, update_portamento,
//                                   resetPortamentoFrom,
//                                   retriggerPortaIfKeyChanged, release/
//                                   uber_release, getAEGFEGLevel/
//                                   restartAEGFEGAttack, resetVelocity
//   src/common/dsp/modulators/ADSRModulationSource.h attackFrom, release,
//                                   uber_release, s_uberrelease(-6.5)
//   src/common/ModulationSource.h   ControllerModulationSource
//                                   processSmoothing (SLOW_EXP)
//
// Per-instance state: one full {gate, uberrelease, key, aeg, velocity
// smoother, keytrack word, portamento} register set PER VOICE SLOT (POOL=8).
// Nothing is shared across slots. The declared negative control
// (--nc-share-portamento-state, model/voice/playmode/run_model.py) replaces
// every voice's portamento state with one shared object in the MODEL only,
// to probe the reference-budget check; this RTL always keeps per-slot state.
//
// The one genuinely per-block transcendental (the portamento glide-curve
// lerp, `glide_phase`) is reproduced by evaluating the SAME pinned table
// FORMULA with SystemVerilog real-math functions ($ln), rounded with the
// same round-half-up `qint_r` pattern tb_voice.sv already uses for the Sine
// oscillator's $cos/$sin path (SXT-026a) -- not a pre-quantized ROM
// interpolated in fixed point, which would double-round. See run_model.py's
// docstring "DECLARED MODEL / RTL BOUNDARY" for the rationale. The three
// named carriers (Bass 2/5, Digibass) all pin porta_curve=LINEAR, so this
// branch is implemented but not load-bearing for the leaf's accepted
// evidence.
//
// Stimulus (declared control-plane boundary; emitted by run_model.py):
//   rtl/init.hex   one-time constants, in model/voice/playmode/run_model.py
//                  INIT_WORD_ORDER order (25 words, index 0..24)
//   rtl/ev.hex     block-quantized note events: per event, 4 words
//                  [block, kind(1=note_on,2=note_off), key, velocity]
`timescale 1ns/1ps

module tb_pm_mono_st_fp;

  localparam int FQ      = 21;
  localparam int F_PHASE = 29;
  localparam int POOL    = 8;
  localparam int MAX_EVENTS = 8192;
  localparam int MAX_CFG    = 32;

  localparam logic signed [31:0] ONE       = 32'sd2097152;     // 1.0 Q10.21
  localparam logic signed [31:0] PHASE_ONE = 32'sd536870912;   // 1.0 Q2.29
  localparam logic signed [31:0] KEYTRACK_ROOT_Q = 32'sd125829120; // 60<<21

  // AegMono / Adsr state encoding (model/voice/voice_model.py Adsr.S_*)
  localparam logic [31:0] S_ATTACK = 0, S_DECAY = 1, S_RELEASE = 3,
                           S_UBER = 4, S_IDLE = 6;

  // MonoVoicePriorityMode
  localparam int PRI_NOTE_ON_LATEST_RETRIGGER_HIGHEST = 0;
  localparam int PRI_ALWAYS_LATEST  = 1;
  localparam int PRI_ALWAYS_HIGHEST = 2;
  localparam int PRI_ALWAYS_LOWEST  = 3;
  // MonoVoiceEnvelopeMode
  localparam int ENV_RESTART_FROM_ZERO = 0;
  // porta_curve codes (run_model.py CURVE_CODE)
  localparam int CURVE_LIN = 0, CURVE_LOG = 1, CURVE_EXP = 2;

  int unsigned qmul_count = 0;
  int unsigned voice_block_count = 0;

  // --------------------------------------------------------------- helpers
  function automatic signed [31:0] sat64(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat64 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat64 = -32'sd2147483648;
    else                           sat64 = v[31:0];
  endfunction

  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << (FQ-1))) >>> FQ;
    qmul = sat64(r);
  endfunction

  function automatic signed [31:0] sat_add(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] s;
    s = $signed({{32{a[31]}}, a}) + $signed({{32{b[31]}}, b});
    sat_add = sat64(s);
  endfunction

  function automatic signed [31:0] limit_i(input signed [31:0] x,
                                           input signed [31:0] lo,
                                           input signed [31:0] hi);
    if      (x < lo) limit_i = lo;
    else if (x > hi) limit_i = hi;
    else             limit_i = x;
  endfunction

  // floor_half(x) = ((x + ONE/2) // ONE) * ONE  (x always >= 0 in this leaf:
  // every portamento/pitch quantity here is derived from a MIDI key >= 0)
  function automatic signed [31:0] floor_half(input signed [31:0] x);
    logic signed [31:0] y;
    y = x + (ONE >>> 1);
    floor_half = (y >>> FQ) <<< FQ;
  endfunction

  // qround(x, s): round-half-up arithmetic shift by s (left shift if s<0)
  function automatic signed [31:0] qround_rtl(input signed [31:0] x, input integer s);
    logic signed [63:0] v;
    begin
      v = $signed({{32{x[31]}}, x});
      if (s <= 0) qround_rtl = sat64(v <<< (-s));
      else        qround_rtl = sat64((v + (64'sd1 <<< (s-1))) >>> s);
    end
  endfunction

  function automatic signed [31:0] qint_phase_r(input real v);
    integer q;
    q = $floor(v * 536870912.0 + 0.5);
    qint_phase_r = sat64(64'(q));
  endfunction

  function automatic signed [31:0] qint_r(input real v);
    integer q;
    q = $floor(v * 2097152.0 + 0.5);
    qint_r = sat64(64'(q));
  endfunction

  // qdiv(ONE, b) with fa=fb=fq=FQ (b always > 0 in this leaf's usage)
  function automatic signed [31:0] qdiv_one(input signed [31:0] b);
    logic signed [63:0] num, half, q;
    begin
      num = $signed({{32{ONE[31]}}, ONE}) <<< FQ;
      half = $signed({{32{b[31]}}, b}) >>> 1;
      q = (num + half) / $signed({{32{b[31]}}, b});
      qdiv_one = sat64(q);
    end
  endfunction

  // vel_rom(midi) = round-half-up(midi/127 * 2^FQ), the same formula as
  // tb_vel.sv's event-rate velocity ROM (SXT-036)
  function automatic signed [31:0] vel_rom(input integer midi);
    logic [63:0] n;
    n = (64'(midi) << (FQ+1)) + 64'd127;
    vel_rom = 32'(n / 64'd254);
  endfunction

  // -------------------------------------------- glide curve (pinned tables)
  function automatic real tbl_glide_log_r(input integer i);
    tbl_glide_log_r = $ln(1.0 + ((real'(i)) * (1.0/512.0)) * 10.0) / $ln(11.0);
  endfunction

  function automatic real tbl_glide_exp_r(input integer i);
    tbl_glide_exp_r = 1.0 - tbl_glide_log_r(511 - i);
  endfunction

  function automatic signed [31:0] glide_phase_rtl(input integer curve,
                                                   input signed [31:0] portaphase_q29);
    real x, a, lo, hi;
    integer e;
    begin
      if (curve == CURVE_LIN) begin
        glide_phase_rtl = qround_rtl(portaphase_q29, F_PHASE - FQ);
      end else begin
        x = ($itor(portaphase_q29) / 536870912.0) * 511.0;
        e = $floor(x);
        a = x - $itor(e);
        if (curve == CURVE_LOG) begin
          lo = tbl_glide_log_r(e & 'h1ff);
          hi = tbl_glide_log_r((e+1) & 'h1ff);
        end else begin
          lo = tbl_glide_exp_r(e & 'h1ff);
          hi = tbl_glide_exp_r((e+1) & 'h1ff);
        end
        glide_phase_rtl = qint_r((1.0 - a) * lo + a * hi);
      end
    end
  endfunction

  // ----------------------------------------------------------- cfg / event
  logic [31:0] cfg [0:MAX_CFG-1];
  logic [31:0] ev_mem [0:MAX_EVENTS*4-1];

  logic signed [31:0] porta_rate_q29;
  integer porta_curve_code;
  logic porta_gliss, porta_constrate, porta_retrigger, fingered, porta_active;
  integer priority_mode, envelope_mode;
  logic signed [31:0] aeg_a_rate_q29, aeg_d_rate_q29, aeg_r_rate_q29, aeg_uber_rate_q29;
  logic signed [31:0] aeg_sustain_q29;
  integer aeg_a_s, aeg_r_s;
  logic aeg_inst_attack;
  logic signed [31:0] vel_coeff_q21, vel_sigma_q21, one_twelfth_q21, const_rate_eps_q21;
  logic signed [31:0] scene_octave_term_q21;
  integer total_blocks, n_events, pool_cfg;

  // ---------------------------------------------------------- voice arrays
  logic        active     [0:POOL-1];
  logic        gate_r     [0:POOL-1];
  logic        uber_r     [0:POOL-1];
  integer      key_r      [0:POOL-1];
  logic [31:0] aeg_state  [0:POOL-1];
  logic signed [31:0] aeg_phase [0:POOL-1];
  logic signed [31:0] aeg_out   [0:POOL-1];
  logic signed [31:0] aeg_scale [0:POOL-1];
  logic [31:0] aeg_idle   [0:POOL-1];
  logic signed [31:0] vel_val   [0:POOL-1];
  logic signed [31:0] vel_tgt   [0:POOL-1];
  logic signed [31:0] kt_word   [0:POOL-1];
  logic signed [31:0] porta_phase [0:POOL-1];
  logic signed [31:0] porta_src   [0:POOL-1];
  logic signed [31:0] porta_pkey  [0:POOL-1];
  logic signed [31:0] porta_prior [0:POOL-1];
  logic        porta_doretrig [0:POOL-1];

  // ------------------------------------------------------------ scene state
  integer keystate  [0:127];     // 0 = up, else last note-on velocity
  integer key_order [0:127];
  integer voice_counter;
  logic signed [31:0] last_key_q;
  integer ord_slot [0:POOL-1];   // insertion-ordered list of active slots
  integer n_voices;

  integer fd;
  integer b, ei, oi, slot, k;

  initial begin
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ev.hex", ev_mem);
    fd = $fopen("tb_pm_trace.txt", "w");

    porta_rate_q29    = 32'(cfg[0]);
    porta_curve_code  = int'(cfg[1]);
    porta_gliss       = cfg[2][0];
    porta_constrate   = cfg[3][0];
    porta_retrigger   = cfg[4][0];
    fingered          = cfg[5][0];
    porta_active      = cfg[6][0];
    priority_mode     = int'(cfg[7]);
    envelope_mode     = int'(cfg[8]);
    aeg_a_rate_q29    = 32'(cfg[9]);
    aeg_d_rate_q29    = 32'(cfg[10]);
    aeg_r_rate_q29    = 32'(cfg[11]);
    aeg_uber_rate_q29 = 32'(cfg[12]);
    aeg_sustain_q29   = 32'(cfg[13]);
    aeg_a_s           = int'(cfg[14]);
    aeg_r_s           = int'(cfg[15]);
    aeg_inst_attack   = cfg[16][0];
    vel_coeff_q21     = 32'(cfg[17]);
    vel_sigma_q21     = 32'(cfg[18]);
    one_twelfth_q21   = 32'(cfg[19]);
    const_rate_eps_q21 = 32'(cfg[20]);
    scene_octave_term_q21 = 32'(cfg[21]);
    total_blocks      = int'(cfg[22]);
    n_events          = int'(cfg[23]);
    pool_cfg          = int'(cfg[24]);
    if (pool_cfg != POOL) $fatal(1, "declared pool %0d != RTL POOL %0d", pool_cfg, POOL);
    if (n_events > MAX_EVENTS) $fatal(1, "n_events %0d exceeds RTL capacity %0d", n_events, MAX_EVENTS);

    for (slot = 0; slot < POOL; slot = slot + 1) active[slot] = 1'b0;
    for (k = 0; k < 128; k = k + 1) begin keystate[k] = 0; key_order[k] = 0; end
    voice_counter = 1;
    last_key_q = 32'sd0;
    n_voices = 0;

    run();
    $fclose(fd);
    $display("DONE pm-qmuls=%0d voice-blocks=%0d", qmul_count, voice_block_count);
    $finish;
  end

  task automatic run;
    ei = 0;
    for (b = 0; b < total_blocks; b = b + 1) begin
      while (ei < n_events && int'(ev_mem[ei*4]) <= b) begin
        automatic integer kind, key, velo;
        kind = int'(ev_mem[ei*4+1]);
        key  = int'(ev_mem[ei*4+2]);
        velo = int'(ev_mem[ei*4+3]);
        if (kind == 1) note_on(key, velo);
        else           note_off(key, velo);
        ei = ei + 1;
      end
      process_block_all();
      dump_block();
    end
  endtask

  // ----------------------------------------------------- allocation (note_on)
  task automatic find_gated_or_recycle(output integer recycle_slot,
                                       output integer found_slot);
    automatic integer oi2, s2, done;
    done = 0; recycle_slot = -1; found_slot = -1;
    for (oi2 = 0; oi2 < n_voices; oi2 = oi2 + 1) begin
      if (!done) begin
        s2 = ord_slot[oi2];
        if (gate_r[s2]) begin
          found_slot = s2;
          done = 1;
        end else if (!uber_r[s2]) begin
          if (envelope_mode != ENV_RESTART_FROM_ZERO) recycle_slot = s2;
          else uber_release_voice(s2);
        end
      end
    end
  endtask

  task automatic note_on(input integer key, input integer velocity);
    automatic logic create_voice;
    automatic integer kk, recycle_slot, found_slot;
    create_voice = 1'b1;
    if (priority_mode == PRI_ALWAYS_HIGHEST || priority_mode == PRI_ALWAYS_LOWEST) begin
      for (kk = 0; kk < 127; kk = kk + 1) begin
        if (keystate[kk] != 0) begin
          if (priority_mode == PRI_ALWAYS_HIGHEST && kk > key) create_voice = 1'b0;
          if (priority_mode == PRI_ALWAYS_LOWEST  && kk < key) create_voice = 1'b0;
        end
      end
    end
    if (!create_voice) begin
      key_order[key] = voice_counter;
      voice_counter = voice_counter + 1;
    end else begin
      find_gated_or_recycle(recycle_slot, found_slot);
      if (found_slot >= 0) begin
        legato_voice(found_slot, key, velocity);
        last_key_q = key <<< FQ;
      end else if (recycle_slot >= 0) begin
        reclaim_voice(recycle_slot, key, velocity);
        key_order[key] = voice_counter;
        voice_counter = voice_counter + 1;
      end else begin
        create_voice_slot(key, velocity);
      end
    end
    keystate[key] = velocity;
  endtask

  task automatic create_voice_slot(input integer key, input integer velocity);
    automatic logic used [0:POOL-1];
    automatic integer i2, j2, free_slot;
    for (i2 = 0; i2 < POOL; i2 = i2 + 1) used[i2] = 1'b0;
    for (j2 = 0; j2 < n_voices; j2 = j2 + 1) used[ord_slot[j2]] = 1'b1;
    free_slot = -1;
    for (i2 = 0; i2 < POOL; i2 = i2 + 1)
      if (!used[i2] && free_slot < 0) free_slot = i2;
    if (free_slot < 0) $fatal(1, "voice pool %0d exhausted", POOL);
    init_voice(free_slot, key, velocity);
    ord_slot[n_voices] = free_slot;
    n_voices = n_voices + 1;
    key_order[key] = voice_counter;
    voice_counter = voice_counter + 1;
    last_key_q = key <<< FQ;
  endtask

  task automatic init_voice(input integer slot_, input integer key, input integer velocity);
    automatic logic signed [31:0] own_pitch;
    own_pitch = key <<< FQ;
    key_r[slot_] = key;
    gate_r[slot_] = 1'b1;
    uber_r[slot_] = 1'b0;
    active[slot_] = 1'b1;
    vel_val[slot_] = vel_rom(velocity);
    vel_tgt[slot_] = vel_val[slot_];
    kt_word[slot_] = 32'sd0;
    aeg_attack_from(slot_, 32'sd0);
    if (fingered || !porta_active) porta_src[slot_] = own_pitch;
    else                           porta_src[slot_] = last_key_q;
    porta_prior[slot_] = porta_src[slot_];
    porta_phase[slot_] = 32'sd0;
    porta_pkey[slot_]  = own_pitch;
    porta_doretrig[slot_] = 1'b0;
  endtask

  task automatic reclaim_voice(input integer slot_, input integer key, input integer velocity);
    automatic logic signed [31:0] aeg_start, prior_key_q, own_pitch;
    aeg_start = (envelope_mode == ENV_RESTART_FROM_ZERO) ? 32'sd0 : aeg_out[slot_];
    prior_key_q = key_r[slot_] <<< FQ;
    gate_r[slot_] = 1'b1;
    uber_r[slot_] = 1'b0;
    active[slot_] = 1'b1;
    key_r[slot_] = key;
    vel_tgt[slot_] = vel_rom(velocity);
    aeg_attack_from(slot_, aeg_start);
    own_pitch = key <<< FQ;
    if (fingered || !porta_active) porta_src[slot_] = own_pitch;
    else                           porta_src[slot_] = prior_key_q;
    porta_prior[slot_] = porta_src[slot_];
    porta_phase[slot_] = 32'sd0;
  endtask

  task automatic legato_voice(input integer slot_, input integer new_key, input integer velocity);
    automatic logic signed [31:0] old_pitch;
    old_pitch = key_r[slot_] <<< FQ;
    porta_legato(slot_, old_pitch);
    key_r[slot_] = new_key;
  endtask

  task automatic porta_legato(input integer slot_, input signed [31:0] own_pitch_q);
    automatic logic signed [31:0] phase;
    if (porta_phase[slot_] > PHASE_ONE) begin
      porta_src[slot_] = own_pitch_q;
    end else begin
      phase = glide_phase_rtl(porta_curve_code, porta_phase[slot_]);
      porta_src[slot_] = sat_add(qmul(ONE - phase, porta_src[slot_]),
                                 qmul(phase, own_pitch_q));
      if (porta_gliss) porta_pkey[slot_] = floor_half(porta_pkey[slot_]);
      porta_doretrig[slot_] = 1'b0;
      if (porta_retrigger) retrigger_if_key_changed(slot_);
    end
    porta_phase[slot_] = 32'sd0;
  endtask

  task automatic retrigger_if_key_changed(input integer slot_);
    automatic logic signed [31:0] f;
    f = floor_half(porta_pkey[slot_]);
    if (f != porta_prior[slot_]) begin
      porta_prior[slot_] = f;
      porta_doretrig[slot_] = 1'b1;
    end
  endtask

  task automatic release_voice(input integer slot_);
    aeg_scale[slot_] = aeg_out[slot_];
    aeg_phase[slot_] = PHASE_ONE;
    aeg_state[slot_] = S_RELEASE;
    gate_r[slot_] = 1'b0;
  endtask

  task automatic uber_release_voice(input integer slot_);
    aeg_scale[slot_] = aeg_out[slot_];
    aeg_phase[slot_] = PHASE_ONE;
    aeg_state[slot_] = S_UBER;
    gate_r[slot_] = 1'b0;
    uber_r[slot_] = 1'b1;
  endtask

  task automatic aeg_attack_from(input integer slot_, input signed [31:0] start);
    automatic real sq;
    aeg_phase[slot_] = 32'sd0;
    aeg_out[slot_]   = 32'sd0;
    aeg_idle[slot_]  = 32'd0;
    aeg_scale[slot_] = ONE;
    if (start > 0) begin
      aeg_out[slot_] = start;
      case (aeg_a_s)
        0: aeg_phase[slot_] = qround_rtl(qmul(start, start), FQ - F_PHASE);
        1: aeg_phase[slot_] = qround_rtl(start, FQ - F_PHASE);
        2: begin
             sq = $sqrt($itor(start) / 2097152.0);
             aeg_phase[slot_] = qint_phase_r(sq);
           end
        default: $fatal(1, "attack shape %0d not in the SXT-043 slice", aeg_a_s);
      endcase
    end
    aeg_state[slot_] = S_ATTACK;
    if (aeg_inst_attack) begin
      aeg_state[slot_] = S_DECAY;
      aeg_out[slot_] = ONE;
      aeg_phase[slot_] = PHASE_ONE;
    end
  endtask

  // ----------------------------------------------------------- note_off
  function automatic integer pick_key(input integer exclude);
    automatic integer highest, lowest, latest, lt, kk;
    highest = -1; lowest = 128; latest = -1; lt = 0;
    for (kk = 127; kk >= 0; kk = kk - 1) begin
      if (kk != exclude && keystate[kk] != 0) begin
        if (kk >= highest) highest = kk;
        if (kk <= lowest)  lowest  = kk;
        if (key_order[kk] >= lt) begin latest = kk; lt = key_order[kk]; end
      end
    end
    case (priority_mode)
      PRI_ALWAYS_HIGHEST, PRI_NOTE_ON_LATEST_RETRIGGER_HIGHEST:
        pick_key = (highest >= 0) ? highest : -1;
      PRI_ALWAYS_LATEST: pick_key = (latest >= 0) ? latest : -1;
      PRI_ALWAYS_LOWEST: pick_key = (lowest <= 127) ? lowest : -1;
      default: begin
        $fatal(1, "monoVoicePriorityMode %0d outside the pinned enum", priority_mode);
        pick_key = -1;
      end
    endcase
  endfunction

  task automatic note_off(input integer key, input integer velocity);
    automatic integer oi2, s2, kpick;
    keystate[key] = 0;
    for (oi2 = 0; oi2 < n_voices; oi2 = oi2 + 1) begin
      s2 = ord_slot[oi2];
      if (key_r[s2] == key) begin
        kpick = pick_key(key);
        if (kpick >= 0) begin
          legato_voice(s2, kpick, velocity);
          last_key_q = kpick <<< FQ;
        end else begin
          release_voice(s2);
        end
      end
    end
  endtask

  // ------------------------------------------------------- per-block update
  task automatic aeg_tick(input integer slot_);
    automatic logic signed [31:0] ph, ov, l_lo, l_hi;
    automatic integer ii;
    case (aeg_state[slot_])
      S_ATTACK: begin
        if (aeg_a_s != 1)
          $fatal(1, "attack shape %0d reached mid-attack (base Adsr restriction)", aeg_a_s);
        ph = sat_add(aeg_phase[slot_], aeg_a_rate_q29);
        if (ph >= PHASE_ONE) begin
          ph = PHASE_ONE;
          aeg_state[slot_] = S_DECAY;
        end
        ov = ph >>> (F_PHASE - FQ);
        aeg_phase[slot_] = ph;
      end
      S_DECAY: begin
        l_lo = aeg_phase[slot_] - aeg_d_rate_q29;
        l_hi = aeg_phase[slot_] + aeg_d_rate_q29;
        if      (aeg_sustain_q29 < l_lo) ph = l_lo;
        else if (aeg_sustain_q29 > l_hi) ph = l_hi;
        else                             ph = aeg_sustain_q29;
        aeg_phase[slot_] = ph;
        ov = ph >>> (F_PHASE - FQ);
      end
      S_RELEASE: begin
        ph = aeg_phase[slot_] - aeg_r_rate_q29;
        ov = ph >>> (F_PHASE - FQ);
        for (ii = 0; ii < aeg_r_s; ii = ii + 1) ov = qmul(ov, ph >>> (F_PHASE - FQ));
        ov = qmul(ov, aeg_scale[slot_]);
        aeg_phase[slot_] = ph;
        if (ph < 0) begin aeg_state[slot_] = S_IDLE; ov = 32'sd0; end
      end
      S_UBER: begin
        ph = aeg_phase[slot_] - aeg_uber_rate_q29;
        ov = ph >>> (F_PHASE - FQ);
        for (ii = 0; ii < aeg_r_s; ii = ii + 1) ov = qmul(ov, ph >>> (F_PHASE - FQ));
        ov = qmul(ov, aeg_scale[slot_]);
        aeg_phase[slot_] = ph;
        if (ph < 0) begin aeg_state[slot_] = S_IDLE; ov = 32'sd0; end
      end
      S_IDLE: begin
        aeg_idle[slot_] = aeg_idle[slot_] + 1;
        ov = aeg_out[slot_];
      end
      default: begin
        $fatal(1, "unexpected aeg_state %0d", aeg_state[slot_]);
        ov = 32'sd0;
      end
    endcase
    aeg_out[slot_] = limit_i(ov, 32'sd0, ONE);
  endtask

  task automatic vel_tick(input integer slot_);
    automatic logic signed [63:0] diffw;
    automatic logic signed [31:0] diff32, aacc;
    diffw = $signed({{32{vel_tgt[slot_][31]}}, vel_tgt[slot_]})
          - $signed({{32{vel_val[slot_][31]}}, vel_val[slot_]});
    if (diffw < 0) diffw = -diffw;
    if (diffw < $signed({{32{vel_sigma_q21[31]}}, vel_sigma_q21})) begin
      vel_val[slot_] = vel_tgt[slot_];
    end else begin
      diff32 = diffw[31:0];
      aacc = limit_i(qmul(vel_coeff_q21, diff32), 32'sd0, ONE);
      vel_val[slot_] = sat_add(qmul(ONE - aacc, vel_val[slot_]),
                               qmul(aacc, vel_tgt[slot_]));
    end
  endtask

  function automatic signed [31:0] const_rate_factor(input integer slot_,
                                                      input signed [31:0] own_pitch_q);
    automatic logic signed [31:0] d, t;
    d = own_pitch_q - porta_src[slot_];
    if (d < 0) d = -d;
    t = sat_add(qmul(one_twelfth_q21, d), const_rate_eps_q21);
    const_rate_factor = qdiv_one(t);
  endfunction

  task automatic porta_update(input integer slot_, input signed [31:0] own_pitch_q,
                              output signed [31:0] pkey_out);
    automatic logic signed [31:0] crf, inc, phase;
    crf = porta_constrate ? const_rate_factor(slot_, own_pitch_q) : ONE;
    inc = (crf == ONE) ? porta_rate_q29 : qmul(porta_rate_q29, crf);
    porta_phase[slot_] = sat_add(porta_phase[slot_], inc);
    if (porta_phase[slot_] < PHASE_ONE && porta_active) begin
      phase = glide_phase_rtl(porta_curve_code, porta_phase[slot_]);
      pkey_out = sat_add(qmul(ONE - phase, porta_src[slot_]), qmul(phase, own_pitch_q));
      if (porta_gliss) pkey_out = floor_half(pkey_out);
      porta_pkey[slot_] = pkey_out;
      porta_doretrig[slot_] = 1'b0;
      if (porta_retrigger) retrigger_if_key_changed(slot_);
    end else begin
      pkey_out = own_pitch_q;
      porta_pkey[slot_] = pkey_out;
    end
  endtask

  task automatic process_voice(input integer slot_, output logic keep);
    automatic logic signed [31:0] own_pitch, pkey, kt_pitch;
    voice_block_count = voice_block_count + 1;
    vel_tick(slot_);
    aeg_tick(slot_);
    keep = !(aeg_state[slot_] == S_IDLE && aeg_idle[slot_] > 0);
    own_pitch = key_r[slot_] <<< FQ;
    porta_update(slot_, own_pitch, pkey);
    kt_pitch = sat_add(pkey, scene_octave_term_q21);
    kt_word[slot_] = qmul(kt_pitch - KEYTRACK_ROOT_Q, one_twelfth_q21);
  endtask

  task automatic process_block_all;
    automatic logic keep [0:POOL-1];
    automatic integer new_ord [0:POOL-1];
    automatic integer new_n, s2;
    automatic logic keep_tmp;
    for (oi = 0; oi < n_voices; oi = oi + 1) begin
      s2 = ord_slot[oi];
      process_voice(s2, keep_tmp);
      keep[s2] = keep_tmp;
    end
    new_n = 0;
    for (oi = 0; oi < n_voices; oi = oi + 1) begin
      s2 = ord_slot[oi];
      if (keep[s2]) begin
        new_ord[new_n] = s2;
        new_n = new_n + 1;
      end else begin
        active[s2] = 1'b0;
      end
    end
    n_voices = new_n;
    for (oi = 0; oi < n_voices; oi = oi + 1) ord_slot[oi] = new_ord[oi];
  endtask

  task automatic dump_block;
    for (slot = 0; slot < POOL; slot = slot + 1) begin
      if (active[slot]) begin
        $fwrite(fd, "T %0d %0d 1 %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
          b, slot,
          gate_r[slot], uber_r[slot], key_r[slot],
          aeg_state[slot], aeg_phase[slot], aeg_out[slot], aeg_scale[slot],
          vel_val[slot], vel_tgt[slot], kt_word[slot],
          porta_phase[slot], porta_src[slot], porta_pkey[slot], porta_prior[slot],
          porta_doretrig[slot]);
      end else begin
        $fwrite(fd, "T %0d %0d 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n", b, slot);
      end
    end
  endtask

endmodule
