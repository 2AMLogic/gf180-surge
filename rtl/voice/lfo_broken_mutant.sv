// SXT-032 RTL LFO control-plane slice: six per-instance scene voice LFOs
// (modsources ms_lfo1..6) implementing the SAME integer schedule as the
// frozen fixed-point LFO model (model/voice/lfo_model.py), driven by the
// same block stream as the SXT-022 voice testbench.
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared block-boundary checkpoint; enforced by
// tools/compare_lfo_rtl_model.py). NOT synthesis-closed, NOT timing-closed;
// no gf180mcu FPGA/ASIC claim of any kind.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/dsp/modulators/LFOModulationSource.cpp/.h
//       phase accumulator + wrap, lfoeg_* envelope machine, per-shape
//       waveform eval, unipolar fold, magnitude scaling, attack/release
//   src/common/SurgeStorage.cpp lookup_waveshape_warp
//   libs/sst/sst-waveshapers WaveshaperTables.h (wst_sine construction)
//
// Stimulus (declared control-plane boundary; emitted by run_lfo_model.py):
//   rtl/init.hex         SXT-022 voice init words (cfg[22] = total_blocks)
//   rtl/lfo_init.hex     6 instances x 14 config words (LFO_INIT_ORDER)
//   rtl/lfo_routes.hex   n_routes, then (instance, dest, depth_q21) per route
//   rtl/lfo_ctrl.hex     per block: [b] + per slot: 6 event words
//                        (b0 attack, b1 release, b2 process-enable)
//   rtl/lfo_wssine.hex   wst_sine table ROM (1024 words, Q10.21)
`timescale 1ns/1ps

module tb_lfo;

  localparam int FQ       = 21;
  localparam int F_PHASE  = 29;
  localparam int F_WAVE   = 27;
  localparam int NSLOTS   = 8;
  localparam int NLFO     = 6;

  localparam logic signed [31:0] PH_ONE = 32'sd536870912;  // 1.0 Q2.29
  localparam logic signed [31:0] W_ONE  = 32'sd134217728;  // 1.0 Q4.27

  // lfoeg states (LFOModulationSource.h)
  localparam logic [31:0] EG_DELAY = 1, EG_ATTACK = 2, EG_HOLD = 3,
      EG_DECAY = 4, EG_RELEASE = 5, EG_STUCK = 7;

  // lt_* shapes
  localparam logic [31:0] LT_SINE = 0, LT_TRI = 1, LT_SQUARE = 2, LT_RAMP = 3;

  int unsigned qmul_count = 0;

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
  logic [31:0] lfo_init  [0:(NLFO*14)-1];
  logic [31:0] lfo_route [0:63];
  logic [31:0] wssine    [0:1023];
  logic [31:0] ctrl_mem  [0:4200000];
  logic [31:0] vinit     [0:39];

  // per-slot per-instance state
  logic signed [31:0] phase    [NSLOTS][NLFO];
  logic        phinit   [NSLOTS][NLFO];
  logic [31:0] eg_state [NSLOTS][NLFO];
  logic signed [31:0] env_val  [NSLOTS][NLFO];
  logic signed [31:0] env_ph   [NSLOTS][NLFO];
  logic signed [31:0] relstart [NSLOTS][NLFO];
  logic        ever_att [NSLOTS][NLFO];
  logic signed [31:0] output21 [NSLOTS][NLFO];
  logic        active   [NSLOTS];

  // per-instance config words for the slot being processed
  logic signed [31:0] cf [14];
  logic signed [31:0] ev;

  integer fd;
  integer b, s, i, k, n_routes;
  logic signed [31:0] rate, t, io2, out27, cut_sum, reso_sum, x27, yv, thr;
  logic signed [31:0] t_q21, eidx, afrac, iout21;
  integer evbase;

  initial begin
    $readmemh("rtl/init.hex",        vinit);
    $readmemh("rtl/lfo_init.hex",    lfo_init);
    $readmemh("rtl/lfo_routes.hex",  lfo_route);
    $readmemh("rtl/lfo_wssine.hex",  wssine);
    $readmemh("rtl/lfo_ctrl.hex",    ctrl_mem);
    fd = $fopen("tb_lfo_trace.txt", "w");
    n_routes = int'(lfo_route[0]);
    run();
    $fclose(fd);
    $display("DONE lfo-qmuls=%0d", qmul_count);
    $finish;
  end

  task automatic run;
    int total_blocks, ci;
    total_blocks = int'(vinit[22]);
    ci = 0;
    for (s = 0; s < NSLOTS; s++) begin
      active[s] = 0;
      for (i = 0; i < NLFO; i++) begin
        phase[s][i] = 0; phinit[s][i] = 0; eg_state[s][i] = EG_STUCK;
        env_val[s][i] = 0; env_ph[s][i] = 0; relstart[s][i] = 0;
        ever_att[s][i] = 0; output21[s][i] = 0;
      end
    end
    for (b = 0; b < total_blocks; b++) begin
      if (ctrl_mem[ci] !== 32'hxxxxxxxx && int'(ctrl_mem[ci]) != b)
        $fatal(1, "lfo ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      ci += 1;
      for (s = 0; s < NSLOTS; s++) begin
        evbase = ci;
        ci += NLFO;
        process_slot(evbase);
      end
    end
  endtask

  function automatic logic [31:0] cfgw(input integer inst, input integer w);
    cfgw = lfo_init[inst*14 + w];
  endfunction

  task automatic attack_inst(input integer inst);
    logic signed [31:0] ph;
    logic [31:0] flags;
    for (k = 0; k < 14; k++) cf[k] = 32'(cfgw(inst, k));
    flags = cf[5];
    ph = 0;
    if (!phinit[s][inst]) begin
      ph = cf[2];                       // start_phase (clamped/quantized)
      phinit[s][inst] = 1;
    end else begin
      ph = phase[s][inst];
    end
    // instant-envelope detection (quantized min flags from the model)
    eg_state[s][inst] = EG_DELAY;
    env_val[s][inst]  = 0;
    env_ph[s][inst]   = 0;
    if ((flags & 4) != 0) begin
      eg_state[s][inst] = EG_ATTACK;
      if ((flags & 8) != 0) begin
        eg_state[s][inst] = EG_HOLD;
        env_val[s][inst] = PH_ONE;
        if ((flags & 16) != 0) eg_state[s][inst] = EG_DECAY;
      end
    end
    // trigmode: keytrigger (bit1) restarts at start_phase; freerun at the
    // pinned offline songpos == 0 also starts at start_phase (lm_random is
    // refused upstream)
    phase[s][inst] = cf[2] % PH_ONE;
    // the shape switch in attackFrom runs for ALL trigger modes
    if (cf[0] == LT_TRI && (flags & 1) == 0)
      phase[s][inst] = (phase[s][inst] + (PH_ONE >> 2)) % PH_ONE;
    else if (cf[0] == LT_SINE && (flags & 1) != 0)
      phase[s][inst] = (phase[s][inst] + 3*(PH_ONE >> 2)) % PH_ONE;
  endtask

  task automatic release_inst(input integer inst);
    for (k = 0; k < 14; k++) cf[k] = 32'(cfgw(inst, k));
    if (cf[13] != 0) begin
      relstart[s][inst] = env_val[s][inst];
      env_ph[s][inst]   = 0;
      eg_state[s][inst] = EG_RELEASE;
    end
  endtask

  task automatic process_inst(input integer inst);
    logic [31:0] flags;
    for (k = 0; k < 14; k++) cf[k] = 32'(cfgw(inst, k));
    flags = cf[5];
    if (!phinit[s][inst]) begin
      phase[s][inst] = cf[2];
      phinit[s][inst] = 1;
    end
    // phase += frate (ratemult == 1 outside stepseq); single wrap declared
    phase[s][inst] = phase[s][inst] + cf[1];
    if ($signed(phase[s][inst]) >= $signed(PH_ONE))
      phase[s][inst] = phase[s][inst] - PH_ONE;

    // LFO EG state machine
    if (eg_state[s][inst] != EG_STUCK) begin
      case (eg_state[s][inst])
        EG_DELAY:   rate = cf[6];
        EG_ATTACK:  rate = cf[7];
        EG_HOLD:    rate = cf[8];
        EG_DECAY:   rate = cf[9];
        EG_RELEASE: rate = cf[10];
        default:    rate = 0;
      endcase
      env_ph[s][inst] = env_ph[s][inst] + rate;
      if ($signed(env_ph[s][inst]) > $signed(PH_ONE)) begin
        if (eg_state[s][inst] == EG_DELAY) begin
          eg_state[s][inst] = EG_ATTACK; env_ph[s][inst] = 0;
        end else if (eg_state[s][inst] == EG_ATTACK) begin
          eg_state[s][inst] = EG_HOLD; env_ph[s][inst] = 0;
        end else if (eg_state[s][inst] == EG_HOLD) begin
          eg_state[s][inst] = EG_DECAY; env_ph[s][inst] = 0;
        end else if (eg_state[s][inst] == EG_DECAY) begin
          eg_state[s][inst] = EG_STUCK; env_ph[s][inst] = 0;
          env_val[s][inst] = cf[11];
        end else if (eg_state[s][inst] == EG_RELEASE) begin
          eg_state[s][inst] = EG_STUCK; env_ph[s][inst] = 0;
          env_val[s][inst] = 0;
        end
      end
      if (eg_state[s][inst] == EG_DELAY)
        env_val[s][inst] = 0;
      else if (eg_state[s][inst] == EG_ATTACK)
        env_val[s][inst] = env_ph[s][inst];
      else if (eg_state[s][inst] == EG_HOLD)
        env_val[s][inst] = PH_ONE;
      else if (eg_state[s][inst] == EG_DECAY)
        env_val[s][inst] = (PH_ONE - env_ph[s][inst])
                         + qmul_sh(env_ph[s][inst], cf[11], F_PHASE);
      else if (eg_state[s][inst] == EG_RELEASE)
        env_val[s][inst] = qmul_sh(PH_ONE - env_ph[s][inst],
                                   relstart[s][inst], F_PHASE);
    end

    // waveform evaluation (control rate, Q4.27)
    case (cf[0])
      LT_SINE: begin
        // x = 2 - 4*phase; Q4.27 word of x is 2^28 - phase (exact)
        x27 = (W_ONE <<< 1) - phase[s][inst];
        // t = x*256 + 512; Q10.21 word of x*256 is x27 <<< 2 (exact)
        t_q21 = (x27 <<< 2) + (32'sd512 <<< FQ);
        eidx  = t_q21 >>> FQ;
        afrac = t_q21 - (eidx <<< FQ);
        iout21 = qmul_sh((32'sd1 <<< FQ) - afrac, 32'(wssine[eidx & 1023]), FQ)
               + qmul_sh(afrac, 32'(wssine[(eidx + 1) & 1023]), FQ);
        io2 = iout21 <<< (F_WAVE - FQ);
      end
      LT_TRI: begin
        yv = ($signed(phase[s][inst]) > $signed(PH_ONE >> 1))
             ? (PH_ONE - phase[s][inst]) : phase[s][inst];
        io2 = -W_ONE + (yv >>> 2);
      end
      LT_SQUARE: begin
        thr = (W_ONE >>> 1) + (cf[4] >>> 1);
        io2 = (($signed(phase[s][inst]) >>> (F_PHASE - F_WAVE)) > $signed(thr))
              ? -W_ONE : W_ONE;
      end
      default: begin // LT_RAMP
        io2 = W_ONE - (phase[s][inst] >>> (F_PHASE - F_WAVE - 1));
      end
    endcase

    // unipolar fold (non-stepseq)
    if ((flags & 1) != 0) io2 = (W_ONE + io2) >>> 1;

    // output_multi[0] = env_val * magnf * io2 (envelopeStart == 0)
    out27 = qmul_sh(io2, env_val[s][inst], F_WAVE + F_PHASE - F_WAVE);
    out27 = qmul_sh(out27, cf[3], F_WAVE);
    output21[s][inst] = (out27 + (32'sd1 <<< (F_WAVE - FQ - 2)))
                        >>> (F_WAVE - FQ);
  endtask

  task automatic process_slot(input integer evbase);
    if (!ctrl_mem_active(evbase)) begin
      active[s] = 0;
      return;
    end
    // SurgeVoice ctor pass: attack all six, then the constructor's
    // calc_ctrldata<true> processes LFO1 + routed instances (routes skipped)
    for (i = 0; i < NLFO; i++) begin
      ev = 32'(ctrl_mem[evbase + i]);
      if (ev[0]) begin
        attack_inst(i);
        ever_att[s][i] = 1;
      end
    end
    for (i = 0; i < NLFO; i++) begin
      ev = 32'(ctrl_mem[evbase + i]);
      if (ev[0] && ev[2]) process_inst(i);
    end
    // block pass: release gate, then calc_ctrldata<false>
    for (i = 0; i < NLFO; i++) begin
      ev = 32'(ctrl_mem[evbase + i]);
      if (ev[1]) release_inst(i);
    end
    for (i = 0; i < NLFO; i++) begin
      ev = 32'(ctrl_mem[evbase + i]);
      if (ev[2]) process_inst(i);
    end
    // routed sums after the block pass (the recorded post-block values; the
    // constructor's first pass skips routes, but the block pass does not)
    cut_sum = 0; reso_sum = 0;
    for (k = 0; k < n_routes; k++) begin
      i = int'(lfo_route[1 + k*3]);
      t = qmul_sh(32'(lfo_route[3 + k*3]), output21[s][i], FQ);
      if (lfo_route[2 + k*3] == 0) cut_sum = cut_sum + t;
      else                         reso_sum = reso_sum + t;
    end
    // trace: model checkpoints process-enabled instances every block and all
    // six on the creation block
    for (i = 0; i < NLFO; i++) begin
      ev = 32'(ctrl_mem[evbase + i]);
      if (ev[2] || ev[0])
        $fwrite(fd, "L %0d %0d %0d %0d %0d %0d %0d %0d\n",
                b, s, i, phase[s][i], eg_state[s][i], env_ph[s][i],
                env_val[s][i], output21[s][i]);
    end
    $fwrite(fd, "S %0d %0d %0d %0d\n", b, s, cut_sum, reso_sum);
    active[s] = 1;
  endtask

  function automatic logic ctrl_mem_active(input integer evbase);
    ctrl_mem_active = ctrl_mem[evbase][0] || ctrl_mem[evbase][2]
                   || ctrl_mem[evbase][1];
  endfunction

endmodule
