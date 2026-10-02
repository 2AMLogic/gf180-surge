// SXT-041 RTL SCENE-LFO control-plane slice: the six per-scene instances
// (modsources ms_slfo1..ms_slfo6, pinned ids 23..28) implementing the SAME
// integer schedule as the frozen fixed-point scene-LFO model
// (model/voice/slfo_model.py on the SXT-032 frozen instance arithmetic),
// driven by the same block stream as the SXT-022 voice testbench.
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared block-boundary checkpoint; enforced by
// tools/compare_slfo_rtl_model.py). NOT synthesis-closed, NOT timing-closed;
// no gf180mcu/FPGA claim of any kind.
//
// Scene scope is the subject of this leaf and is structural here:
//   * ONE instance array (NSLFO), not an array per voice slot -- the pinned
//     engine's SurgeVoice ctor copies the SCENE's modsource pointers into
//     each voice (SurgeVoice.cpp lines 325..330);
//   * attack/release arrive as per-BLOCK scene events (the model evaluates
//     the engine's getNonReleasedVoices(scene) == 0 gate and streams the
//     result), never as per-note events;
//   * the route sums for block N are formed from `route_out`, the latch
//     written at the END of block N-1, because processControl applies
//     modulation_scene BEFORE the n_lfos_scene process loop;
//   * all six instances advance every block, including the declared settle
//     blocks replayed before block 0.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/SurgeSynthesizer.cpp  (ctor / playVoice / releaseNote /
//                                     processControl ordering)
//   src/common/dsp/SurgeVoice.cpp    (scene modsource pointer copy)
//   src/common/dsp/modulators/LFOModulationSource.cpp/.h
//   src/common/SurgeStorage.cpp lookup_waveshape_warp
//   libs/sst/sst-waveshapers WaveshaperTables.h (wst_sine construction)
//
// Stimulus (declared control-plane boundary; emitted by run_slfo_model.py):
//   rtl/init.hex          SXT-022 voice init words (cfg[22] = total_blocks)
//   rtl/slfo_init.hex     6 instances x 14 config words (SLFO_INIT_ORDER)
//   rtl/slfo_routes.hex   n_routes, settle_blocks, then
//                         (instance, dest, depth_q21) per route
//   rtl/slfo_ctrl.hex     per block: [b, flags(b0 attack, b1 release)]
//   rtl/slfo_wssine.hex   wst_sine table ROM (1024 words, Q10.21)
`timescale 1ns/1ps

module tb_slfo;

  localparam int FQ       = 21;
  localparam int F_PHASE  = 29;
  localparam int F_WAVE   = 27;
  localparam int NSLFO    = 6;

  localparam logic signed [31:0] PH_ONE = 32'sd536870912;  // 1.0 Q2.29
  localparam logic signed [31:0] W_ONE  = 32'sd134217728;  // 1.0 Q4.27

  // lfoeg states (LFOModulationSource.h)
  localparam logic [31:0] EG_DELAY = 1, EG_ATTACK = 2, EG_HOLD = 3,
      EG_DECAY = 4, EG_RELEASE = 5, EG_STUCK = 7;

  // lt_* shapes
  localparam logic [31:0] LT_SINE = 0, LT_TRI = 1, LT_SQUARE = 2, LT_RAMP = 3;

  int unsigned qmul_count = 0;
  int unsigned advance_count = 0;

  function automatic signed [31:0] qmul_sh(input signed [31:0] a,
                                           input signed [31:0] b,
                                           input integer sh);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << (sh-1))) >>> sh;
    if      (r > 64'sd2147483647)  qmul_sh = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul_sh = -32'sd2147483648;
    else                           qmul_sh = r[31:0];
  endfunction

  // ------------------------------------------------------------------ state
  logic [31:0] slfo_init [0:(NSLFO*14)-1];
  logic [31:0] slfo_route [0:63];
  logic [31:0] wssine     [0:1023];
  logic [31:0] ctrl_mem   [0:1200000];
  logic [31:0] vinit      [0:39];

  // ONE per-scene instance set (scene scope: not indexed by voice slot)
  logic signed [31:0] phase    [NSLFO];
  logic        phinit   [NSLFO];
  logic [31:0] eg_state [NSLFO];
  logic signed [31:0] env_val  [NSLFO];
  logic signed [31:0] env_ph   [NSLFO];
  logic signed [31:0] relstart [NSLFO];
  logic        ever_att [NSLFO];
  logic signed [31:0] output21 [NSLFO];
  // the ONE-BLOCK route latch: what modulation_scene consumes next block
  logic signed [31:0] route_out [NSLFO];

  logic signed [31:0] cf [14];

  integer fd;
  integer b, i, k, n_routes, settle_blocks;
  logic signed [31:0] rate, t, io2, out27, cut_sum, reso_sum, x27, yv, thr;
  logic signed [31:0] t_q21, eidx, afrac, iout21;

  initial begin
    $readmemh("rtl/init.hex",        vinit);
    $readmemh("rtl/slfo_init.hex",   slfo_init);
    $readmemh("rtl/slfo_routes.hex", slfo_route);
    $readmemh("rtl/slfo_wssine.hex", wssine);
    $readmemh("rtl/slfo_ctrl.hex",   ctrl_mem);
    fd = $fopen("tb_slfo_trace.txt", "w");
    n_routes      = int'(slfo_route[0]);
    settle_blocks = int'(slfo_route[1]);
    run();
    $fclose(fd);
    $display("DONE slfo-qmuls=%0d advances=%0d", qmul_count, advance_count);
    $finish;
  end

  task automatic run;
    int total_blocks, ci;
    logic [31:0] flags;
    total_blocks = int'(vinit[22]);
    for (i = 0; i < NSLFO; i++) begin
      phase[i] = 0; phinit[i] = 0; eg_state[i] = EG_STUCK;
      env_val[i] = 0; env_ph[i] = 0; relstart[i] = 0;
      ever_att[i] = 0; output21[i] = 0; route_out[i] = 0;
    end
    // declared settle replay: all six advance, no scene events, the route
    // sums of these blocks are discarded with the audio (see the fixture
    // sidecar's settle_blocks)
    for (b = 0; b < settle_blocks; b++) advance_all();
    ci = 0;
    for (b = 0; b < total_blocks; b++) begin
      // Stimulus-load guard (issues #188/#193): an ABSENT slfo_ctrl.hex is
      // caught by the harness's pre-flight check, but a PRESENT-and-empty or
      // short one opens fine and leaves the control memory all-x, which
      // Icarus reports on stdout while still exiting 0. Fatal here so that
      // shape surfaces as a simulator failure (non-zero vvp exit) instead of
      // a wall of RTL-vs-model "mismatches".
      if (ctrl_mem[ci] === 32'hxxxxxxxx)
        $fatal(1, "slfo ctrl memory not loaded at block %0d (rtl/slfo_ctrl.hex empty or shorter than the %0d declared blocks)", b, total_blocks);
      if (int'(ctrl_mem[ci]) != b)
        $fatal(1, "slfo ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      flags = ctrl_mem[ci+1];
      ci += 2;
      // 1. scene events (the model streams the engine's gated-voice-count
      //    verdict, already evaluated with playVoice/releaseNote ordering)
      if (flags[0]) for (i = 0; i < NSLFO; i++) attack_inst(i);
      if (flags[1]) for (i = 0; i < NSLFO; i++) release_inst(i);
      // 2. modulation_scene apply, from the PREVIOUS block's outputs
      cut_sum = 0; reso_sum = 0;
      for (k = 0; k < n_routes; k++) begin
        i = int'(slfo_route[2 + k*3]);
        t = qmul_sh(32'(slfo_route[4 + k*3]), route_out[i], FQ);
        if (slfo_route[3 + k*3] == 0) cut_sum = cut_sum + t;
        else                          reso_sum = reso_sum + t;
      end
      // 3. the unconditional six-instance advance, then re-latch
      advance_all();
      // 4. declared checkpoints
      for (i = 0; i < NSLFO; i++)
        $fwrite(fd, "L %0d %0d %0d %0d %0d %0d %0d\n",
                b, i, phase[i], eg_state[i], env_ph[i], env_val[i],
                output21[i]);
      $fwrite(fd, "S %0d %0d %0d\n", b, cut_sum, reso_sum);
      $fwrite(fd, "O %0d %0d %0d %0d %0d %0d %0d\n", b, route_out[0],
              route_out[1], route_out[2], route_out[3], route_out[4],
              route_out[5]);
    end
  endtask

  task automatic advance_all;
    advance_count++;
    for (i = 0; i < NSLFO; i++) process_inst(i);
    for (i = 0; i < NSLFO; i++) route_out[i] = output21[i];
  endtask

  function automatic logic [31:0] cfgw(input integer inst, input integer w);
    cfgw = slfo_init[inst*14 + w];
  endfunction

  task automatic attack_inst(input integer inst);
    logic [31:0] flags;
    for (k = 0; k < 14; k++) cf[k] = 32'(cfgw(inst, k));
    flags = cf[5];
    if (!phinit[inst]) phinit[inst] = 1;
    // instant-envelope detection (quantized min flags from the model)
    eg_state[inst] = EG_DELAY;
    env_val[inst]  = 0;
    env_ph[inst]   = 0;
    if ((flags & 4) != 0) begin
      eg_state[inst] = EG_ATTACK;
      if ((flags & 8) != 0) begin
        eg_state[inst] = EG_HOLD;
        env_val[inst] = PH_ONE;
        if ((flags & 16) != 0) eg_state[inst] = EG_DECAY;
      end
    end
    // trigmode: keytrigger (bit1) restarts at start_phase; freerun at the
    // pinned offline songpos == 0 also starts at start_phase (lm_random is
    // refused upstream). NOTE: "keytrigger" for a SCENE LFO means the
    // first-gated-note restart, not a per-note restart (the model's gate).
    phase[inst] = cf[2] % PH_ONE;
    // the shape switch in attackFrom runs for ALL trigger modes
    if (cf[0] == LT_TRI && (flags & 1) == 0)
      phase[inst] = (phase[inst] + (PH_ONE >> 2)) % PH_ONE;
    else if (cf[0] == LT_SINE && (flags & 1) != 0)
      phase[inst] = (phase[inst] + 3*(PH_ONE >> 2)) % PH_ONE;
    ever_att[inst] = 1;
  endtask

  task automatic release_inst(input integer inst);
    for (k = 0; k < 14; k++) cf[k] = 32'(cfgw(inst, k));
    if (cf[13] != 0) begin
      relstart[inst] = env_val[inst];
      env_ph[inst]   = 0;
      eg_state[inst] = EG_RELEASE;
    end
  endtask

  task automatic process_inst(input integer inst);
    logic [31:0] flags;
    for (k = 0; k < 14; k++) cf[k] = 32'(cfgw(inst, k));
    flags = cf[5];
    if (!phinit[inst]) begin
      phase[inst] = cf[2];
      phinit[inst] = 1;
    end
    // phase += frate (ratemult == 1 outside stepseq); single wrap declared
    phase[inst] = phase[inst] + cf[1];
    if ($signed(phase[inst]) >= $signed(PH_ONE))
      phase[inst] = phase[inst] - PH_ONE;

    // LFO EG state machine
    if (eg_state[inst] != EG_STUCK) begin
      case (eg_state[inst])
        EG_DELAY:   rate = cf[6];
        EG_ATTACK:  rate = cf[7];
        EG_HOLD:    rate = cf[8];
        EG_DECAY:   rate = cf[9];
        EG_RELEASE: rate = cf[10];
        default:    rate = 0;
      endcase
      env_ph[inst] = env_ph[inst] + rate;
      if ($signed(env_ph[inst]) > $signed(PH_ONE)) begin
        if (eg_state[inst] == EG_DELAY) begin
          eg_state[inst] = EG_ATTACK; env_ph[inst] = 0;
        end else if (eg_state[inst] == EG_ATTACK) begin
          eg_state[inst] = EG_HOLD; env_ph[inst] = 0;
        end else if (eg_state[inst] == EG_HOLD) begin
          eg_state[inst] = EG_DECAY; env_ph[inst] = 0;
        end else if (eg_state[inst] == EG_DECAY) begin
          eg_state[inst] = EG_STUCK; env_ph[inst] = 0;
          env_val[inst] = cf[11];
        end else if (eg_state[inst] == EG_RELEASE) begin
          eg_state[inst] = EG_STUCK; env_ph[inst] = 0;
          env_val[inst] = 0;
        end
      end
      if (eg_state[inst] == EG_DELAY)
        env_val[inst] = 0;
      else if (eg_state[inst] == EG_ATTACK)
        env_val[inst] = env_ph[inst];
      else if (eg_state[inst] == EG_HOLD)
        env_val[inst] = PH_ONE;
      else if (eg_state[inst] == EG_DECAY)
        env_val[inst] = (PH_ONE - env_ph[inst])
                      + qmul_sh(env_ph[inst], cf[11], F_PHASE);
      else if (eg_state[inst] == EG_RELEASE)
        env_val[inst] = qmul_sh(PH_ONE - env_ph[inst], relstart[inst],
                                F_PHASE);
    end

    // waveform evaluation (control rate, Q4.27)
    case (cf[0])
      LT_SINE: begin
        // x = 2 - 4*phase; Q4.27 word of x is 2^28 - phase (exact)
        x27 = (W_ONE <<< 1) - phase[inst];
        // t = x*256 + 512; Q10.21 word of x*256 is x27 <<< 2 (exact)
        t_q21 = (x27 <<< 2) + (32'sd512 <<< FQ);
        eidx  = t_q21 >>> FQ;
        afrac = t_q21 - (eidx <<< FQ);
        iout21 = qmul_sh((32'sd1 <<< FQ) - afrac, 32'(wssine[eidx & 1023]), FQ)
               + qmul_sh(afrac, 32'(wssine[(eidx + 1) & 1023]), FQ);
        io2 = iout21 <<< (F_WAVE - FQ);
      end
      LT_TRI: begin
        yv = ($signed(phase[inst]) > $signed(PH_ONE >> 1))
             ? (PH_ONE - phase[inst]) : phase[inst];
        io2 = -W_ONE + (yv >>> 2);
      end
      LT_SQUARE: begin
        thr = (W_ONE >>> 1) + (cf[4] >>> 1);
        io2 = (($signed(phase[inst]) >>> (F_PHASE - F_WAVE)) > $signed(thr))
              ? -W_ONE : W_ONE;
      end
      default: begin // LT_RAMP
        io2 = W_ONE - (phase[inst] >>> (F_PHASE - F_WAVE - 1));
      end
    endcase

    // unipolar fold (non-stepseq)
    if ((flags & 1) != 0) io2 = (W_ONE + io2) >>> 1;

    // output_multi[0] = env_val * magnf * io2 (envelopeStart == 0)
    out27 = qmul_sh(io2, env_val[inst], F_WAVE + F_PHASE - F_WAVE);
    out27 = qmul_sh(out27, cf[3], F_WAVE);
    output21[inst] = (out27 + (32'sd1 <<< (F_WAVE - FQ - 2)))
                     >>> (F_WAVE - FQ);
  endtask

endmodule
