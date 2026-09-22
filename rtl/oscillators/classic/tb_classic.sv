// SXT-033 RTL Classic oscillator family: audio-rate schedule for the
// declared parameter classes (shape/width/sub mix ranges, hard-sync machine,
// unison stacking) extending the landed SXT-022 voice slice, implementing
// the SAME integer schedule as the frozen fixed-point model
// (model/oscillators/classic/classic_model.py).
//
// Claim scope: this RTL is simulated with iverilog and must match the frozen
// model EXACTLY (integer equality at every declared checkpoint; enforced by
// tools/compare_classic_rtl_model.py). It is NOT synthesis-closed, NOT
// timing-closed, and makes no gf180mcu FPGA/ASIC claim of any kind. The
// schedule is a sequential operation stream (the landed SXT-022 tb_voice.sv
// harness style); cost accounting is reported separately in
// reports/SXT-033/EVIDENCE.md under the declared 1-MAC cost model.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/dsp/oscillators/ClassicOscillator.cpp (convolute with the
//     syncstate restart branch / process_block / update_lagvals)
//   OscillatorBase.h prepare_unison + sst-basic-blocks UnisonSetup
//   sst-basic-blocks OscillatorDriftUnisonCharacter.h CharacterFilter
//   src/common/dsp/modulators/ADSRModulationSource.h (digital mode)
//   sst-filters HalfRateFilter.h (M=6, steep) process_block_D2
//
// Stimulus (declared control-plane boundary; emitted by
// model/oscillators/classic/run_model.py):
//   init.hex   one-time constants: unison words, lag targets, character
//              filter, aeg rate words, halfband coefficients
//   ctrl.hex   per-block control words: header [b, slotmask, master, 0..]
//              + one 12-word record per processed slot (+48 creation words:
//              per-voice t_u/t_sync_u/t_inv_u arrays latched on voice
//              creation)
//   sinc_main.hex / sinc_deriv.hex   sinctable ROM (model-generated)
`timescale 1ns/1ps

module tb_classic;

  localparam int FQ       = 21;
  localparam int F_PHASE  = 29;
  localparam int PMI_F    = 18;
  localparam int BLOCK    = 32;
  localparam int BLOCK_OS = 64;
  localparam int OB_LEN   = 128;
  localparam int FIRN     = 12;
  localparam int FIROFF   = 6;
  localparam int NSLOTS   = 8;
  localparam int MAXUNI   = 16;
  localparam int REC      = 12;
  localparam int REC_NEW  = REC + 48;

  localparam logic signed [31:0] ONE      = 32'sd2097152;    // 1.0 Q10.21
  localparam logic signed [31:0] PH_ONE   = 32'sd536870912;  // 1.0 Q2.29
  localparam logic [31:0] S_ATTACK = 0, S_DECAY = 1, S_RELEASE = 3, S_IDLE = 6;

  int unsigned qmul_count = 0;

  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << 20)) >>> 21;
    if      (r > 64'sd2147483647)  qmul = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  function automatic signed [31:0] sat32(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = v[31:0];
  endfunction

  function automatic signed [31:0] clamp_q(input signed [31:0] v); // 0.001..0.999
    if      ($signed(v) < 32'sd2097)    clamp_q = 32'sd2097;
    else if ($signed(v) > 32'sd2097151) clamp_q = 32'sd2097151;
    else clamp_q = v;
  endfunction

  function automatic signed [31:0] clamp8(input signed [31:0] v); // +-8.0
    if      ($signed(v) >  32'sd16777216) clamp8 =  32'sd16777216;
    else if ($signed(v) < -32'sd16777216) clamp8 = -32'sd16777216;
    else clamp8 = v;
  endfunction

  function automatic signed [31:0] clamp1(input signed [31:0] v);
    if      ($signed(v) >  ONE) clamp1 = ONE;
    else if ($signed(v) < -ONE) clamp1 = -ONE;
    else clamp1 = v;
  endfunction

  // ------------------------------------------------------------------ ROMs
  logic [31:0] sinc_main  [0:(257*FIRN)-1];
  logic [31:0] sinc_deriv [0:(256*FIRN)-1];
  // init word map (INIT ORDER in run_model.py):
  //  0 n_unison   1 out_attenuation
  //  2..17 t_u  18..33 t_sync_u  34..49 t_inv_u (probe defaults)
  //  50..54 lag targets shape/pw/pw2/sub/sync  55 lag_rate
  //  56..58 char a1/b0/b1  59 hpf_init  60 integrator_hpf
  //  61 total_blocks  62..65 aeg rate a/d/r + sustain(Q2.29)
  //  66 aeg_r_s  67 inst_att_aeg  68..73 halfband B0..B5  74..79 A0..A5
  logic [31:0] cfg [0:81];
  logic [31:0] ctrl_mem [0:4200000];

  // --------------------------------------------------------- per-slot state
  logic signed [31:0] ob    [NSLOTS][OB_LEN + FIRN];
  logic signed [31:0] dcb   [NSLOTS][OB_LEN + FIRN];
  // per unison voice
  logic signed [63:0] oscstate  [NSLOTS][MAXUNI];
  logic signed [63:0] syncstate [NSLOTS][MAXUNI];
  logic signed [31:0] last_level [NSLOTS][MAXUNI];
  logic signed [31:0] pwidth  [NSLOTS][MAXUNI];
  logic signed [31:0] pwidth2 [NSLOTS][MAXUNI];
  logic signed [31:0] dc_uni  [NSLOTS][MAXUNI];
  logic [31:0]  ustate [NSLOTS][MAXUNI];
  // per voice instance rate words (latched at creation)
  logic signed [31:0] t_u      [NSLOTS][MAXUNI];
  logic signed [31:0] t_sync_u [NSLOTS][MAXUNI];
  logic signed [31:0] t_inv_u  [NSLOTS][MAXUNI];
  // shared per-slot osc state
  logic signed [31:0] dc_mdc [NSLOTS], osc_out [NSLOTS], osc_out2 [NSLOTS];
  logic [31:0]  bufpos [NSLOTS], hpf_prev [NSLOTS];
  logic signed [31:0] l_shape [NSLOTS], l_pw [NSLOTS], l_pw2 [NSLOTS],
      l_sub [NSLOTS], l_sync [NSLOTS];
  logic signed [31:0] osout [NSLOTS][BLOCK_OS];
  // slice (envelope + gain) state
  logic signed [31:0] aeg_phase [NSLOTS], aeg_out_r [NSLOTS], aeg_scale [NSLOTS];
  logic [31:0]  aeg_state [NSLOTS], aeg_idle [NSLOTS];
  logic signed [31:0] prev_gain [NSLOTS], prev_outl [NSLOTS];
  logic [31:0] slot_ckpt [NSLOTS], slot_key [NSLOTS];

  // scene + decimator state
  logic signed [31:0] scene_l [BLOCK_OS];
  logic signed [31:0] hbx1_b [6], hbx2_b [6], hby1_b [6], hby2_b [6];
  logic signed [31:0] hbx1_a [6], hbx2_a [6], hby1_a [6], hby2_a [6];

  // control words for the slot being processed
  // 0 key  1 flags(b0 gate,b1 ckpt,b2 created,b3 released)
  // 2 pmi  3 pitchmult  4 a_cov  5 hpf_start  6 hpf_d
  // 7 lvl  8 pfg  9 gain_start  10 d_gain  11 outl
  logic signed [31:0] cw [REC];
  logic signed [31:0] nw [48];

  integer fd;
  integer b, s, u, k, i, w;
  logic [31:0] ipos, delay, m_idx, lipol, base;
  logic signed [63:0] prod64;
  logic signed [31:0] t_rate, g, tg, olddc, rate, term, hpf_start,
      hpf_d, hpf_v, acc, obv, last_oo, mdc, oa, wf, sub, om1, pw, pw2v;
  logic sync_on, sync_branch;

  initial begin
    $readmemh("rtl/sinc_main.hex",  sinc_main);
    $readmemh("rtl/sinc_deriv.hex", sinc_deriv);
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ctrl.hex", ctrl_mem);
    fd = $fopen("tb_trace.txt", "w");
    for (i = 0; i < 6; i++) begin
      hbx1_b[i]=0; hbx2_b[i]=0; hby1_b[i]=0; hby2_b[i]=0;
      hbx1_a[i]=0; hbx2_a[i]=0; hby1_a[i]=0; hby2_a[i]=0;
    end
    run();
    $fclose(fd);
    $display("DONE qmuls=%0d blocks=%0d", qmul_count, int'(cfg[61]));
    $finish;
  end

  task automatic run;
    int total_blocks, ci;
    logic [31:0] master_amp, slotmask;
    total_blocks = int'(cfg[61]);
    ci = 0;
    for (b = 0; b < total_blocks; b++) begin
      if (ctrl_mem[ci] !== 32'hxxxxxxxx && int'(ctrl_mem[ci]) != b)
        $fatal(1, "ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      slotmask   = ctrl_mem[ci+1];
      master_amp = ctrl_mem[ci+2];
      ci += 10;
      for (k = 0; k < BLOCK_OS; k++) scene_l[k] = 0;
      for (s = 0; s < NSLOTS; s++) begin
        if (slotmask[s]) begin
          for (i = 0; i < REC; i++) cw[i] = ctrl_mem[ci + i];
          slot_ckpt[s] = cw[1][1];
          slot_key[s]  = cw[0];
          if (cw[1][2]) begin
            // creation record: latch per-voice rate words + init state
            for (i = 0; i < 48; i++) nw[i] = ctrl_mem[ci + REC + i];
            for (u = 0; u < MAXUNI; u++) begin
              t_u[s][u]      = nw[u];
              t_sync_u[s][u] = nw[16 + u];
              t_inv_u[s][u]  = nw[32 + u];
            end
            init_voice();
            ci += REC_NEW;
          end else begin
            ci += REC;
          end
          process_slot();
        end
      end
      decimate_and_output(master_amp);
    end
  endtask

  // --------------------------------------------------------------- envelope
  task automatic adsr_tick;
    logic signed [31:0] ph, rate_a, rate_d, rate_r, sus, l_lo, l_hi, ov, scl;
    logic [31:0] st, r_s;
    rate_a=cfg[62]; rate_d=cfg[63]; rate_r=cfg[64]; sus=cfg[65];
    r_s=cfg[66];
    st=aeg_state[s]; ph=aeg_phase[s]; ov=aeg_out_r[s]; scl=aeg_scale[s];
    if (st == S_ATTACK) begin
      ph = ph + rate_a;
      if ($signed(ph) >= $signed(PH_ONE)) begin ph = PH_ONE; st = S_DECAY; end
      ov = ph >>> (F_PHASE - FQ);
    end else if (st == S_DECAY) begin
      if (cfg[80] == 0) begin
        l_lo = ph - rate_d; l_hi = ph + rate_d;
      end else begin
        // d_s == 1 (sqrt-domain decay), frozen SXT-026 form:
        // sx = floor(sqrt(phase/2^29)*2^29 + 0.5);
        // l_lo = ph -/+ 2*sx*rate + rate^2 (with the sustain gates below)
        logic signed [63:0] prod64d;
        logic signed [31:0] sx, two_sx_rate, rr, rate_w;
        real phr;
        rate_w = rate_d;
        phr = $itor(ph) / 536870912.0;
        sx = $rtoi($sqrt(phr) * 536870912.0 + 0.5);
        prod64d = $signed(sx) * $signed(rate_w);
        two_sx_rate = 32'((prod64d + (64'sd1 << 28)) >>> 29) << 1;  // qround(2*q,0) = 2*q
        prod64d = $signed(rate_w) * $signed(rate_w);
        rr = 32'((prod64d + (64'sd1 << 28)) >>> 29);
        l_lo = ph - two_sx_rate + rr;
        l_hi = ph + two_sx_rate + rr;
        if (($signed(sus) < 32'sd2097 && $signed(ph) < 32'sd210) ||
            ($signed(sus) == 0 && $signed(32'(cfg[81])) < -32'sd14680064))
          l_lo = 0;
        if ($signed(rate_w) > $signed(PH_ONE) && $signed(l_lo) > $signed(sus))
          l_lo = sus;
      end
      if      ($signed(sus) < $signed(l_lo)) ph = l_lo;
      else if ($signed(sus) > $signed(l_hi)) ph = l_hi;
      else                                   ph = sus;
      ov = ph >>> (F_PHASE - FQ);
    end else if (st == S_RELEASE) begin
      ph = ph - rate_r;
      ov = ph >>> (F_PHASE - FQ);
      for (i = 0; i < int'(r_s); i++) ov = qmul(ov, ph >>> (F_PHASE - FQ));
      ov = qmul(ov, scl);
      if ($signed(ph) < 0) begin st = S_IDLE; ov = 0; end
    end else if (st == S_IDLE) begin
      aeg_idle[s] = aeg_idle[s] + 1;
    end
    if ($signed(ov) < 0) ov = 0;
    if ($signed(ov) > $signed(ONE)) ov = ONE;
    aeg_state[s]=st; aeg_phase[s]=ph; aeg_out_r[s]=ov;
  endtask

  // ------------------------------------------------------------------ voice
  task automatic init_voice;
    begin
      l_shape[s]=32'(cfg[50]); l_pw[s]=32'(cfg[51]); l_pw2[s]=32'(cfg[52]);
      l_sub[s]=32'(cfg[53]); l_sync[s]=32'(cfg[54]);
      for (w = 0; w < OB_LEN + FIRN; w++) begin ob[s][w] = 0; dcb[s][w] = 0; end
      for (u = 0; u < int'(cfg[0]); u++) begin
        oscstate[s][u]=0; syncstate[s][u]=0; ustate[s][u]=0;
        last_level[s][u]=0; dc_uni[s][u]=0; pwidth2[s][u]=0;
        pwidth[s][u]=clamp_q(l_pw[s]);
      end
      dc_mdc[s]=0; osc_out[s]=0; osc_out2[s]=0; bufpos[s]=0;
      hpf_prev[s]=32'(cw[5]) + 32'(cw[6]);  // hpf_start + hpf_d (constant params)
      aeg_phase[s]=0; aeg_out_r[s]=0; aeg_idle[s]=0; aeg_scale[s]=ONE;
      aeg_state[s]=S_ATTACK;
      if (cfg[67] != 0) begin aeg_state[s]=S_DECAY; aeg_out_r[s]=ONE; aeg_phase[s]=PH_ONE; end
      // (the frozen model's constructor does NOT step the envelope)
      prev_gain[s] = 32'(cw[9]) + 32'(cw[10]);  // block-0 gain target
      prev_outl[s] = 32'(cw[11]);
    end
  endtask

  task automatic process_slot;
    begin
      if (cw[1][3]) begin  // note_off: release (carried in the record flags)
        aeg_scale[s] = aeg_out_r[s]; aeg_phase[s] = PH_ONE;
        aeg_state[s] = S_RELEASE;
      end
      adsr_tick();
      osc_block();
      output_stage();
      if (slot_ckpt[s]) dump_slot();
      if (aeg_state[s] == S_IDLE && aeg_idle[s] > 0) begin
        // voice death: the model drops the slot after this block
      end
    end
  endtask

  // -------------------------------------------------- classic osc (1 slot)
  task automatic osc_block;
    logic signed [31:0] lag_rate;
    logic [31:0] a_cov, pmi;
    lag_rate = 32'(cfg[55]);
    l_shape[s] = l_shape[s] + qmul(lag_rate, 32'(cfg[50]) - l_shape[s]);
    l_pw[s]    = l_pw[s]    + qmul(lag_rate, 32'(cfg[51]) - l_pw[s]);
    l_pw2[s]   = l_pw2[s]   + qmul(lag_rate, 32'(cfg[52]) - l_pw2[s]);
    l_sub[s]   = l_sub[s]   + qmul(lag_rate, 32'(cfg[53]) - l_sub[s]);
    l_sync[s]  = l_sync[s]  + qmul(lag_rate, 32'(cfg[54]) - l_sync[s]);
    hpf_start  = hpf_prev[s];
    hpf_d      = 32'(cw[6]);
    hpf_prev[s]= 32'(cw[5]) + 32'(cw[6]);
    pmi   = cw[2];
    a_cov = cw[4];
    sync_on = $signed(l_sync[s]) > 0;
    for (u = 0; u < int'(cfg[0]); u++) begin
      while ((sync_on && $signed(syncstate[s][u]) < $signed(a_cov)) ||
             ($signed(oscstate[s][u]) < $signed(a_cov)))
        convolute(pmi, u);
      oscstate[s][u] = oscstate[s][u] - a_cov;
      if (sync_on) syncstate[s][u] = syncstate[s][u] - a_cov;
    end
    oa  = qmul(32'(cfg[1]), 32'(cw[3]));
    mdc = dc_mdc[s];
    for (k = 0; k < BLOCK_OS; k++) begin
      hpf_v = hpf_start + ((hpf_d * (k+1) + 32'sd32) >>> 6);
      acc = qmul(osc_out[s], hpf_v);
      mdc = mdc + dcb[s][bufpos[s] + k];
      obv = ob[s][bufpos[s] + k] - qmul(mdc, oa);
      last_oo = osc_out[s];
      osc_out[s] = sat32(acc + obv);
      osc_out2[s] = qmul(osc_out2[s], 32'(cfg[56]))
                  + qmul(osc_out[s], 32'(cfg[57]))
                  + qmul(last_oo, 32'(cfg[58]));
      osout[s][k] = osc_out2[s];
    end
    dc_mdc[s] = mdc;
    for (k = 0; k < BLOCK_OS; k++) begin
      ob[s][bufpos[s] + k] = 0; dcb[s][bufpos[s] + k] = 0;
    end
    bufpos[s] = (bufpos[s] + BLOCK_OS) & (OB_LEN - 1);
    if (bufpos[s] == 0) begin
      for (k = 0; k < FIRN; k++) begin
        ob[s][k] = ob[s][OB_LEN + k];  ob[s][OB_LEN + k] = 0;
        dcb[s][k] = dcb[s][OB_LEN + k]; dcb[s][OB_LEN + k] = 0;
      end
    end
  endtask

  task automatic convolute(input logic [31:0] pmi, input integer u);
    sync_branch = ($signed(l_sync[s]) > 0) &&
                  ($signed(syncstate[s][u]) < $signed(oscstate[s][u]));
    if (sync_branch) begin
      // hard-sync restart: rewind the cycle to syncstate (ipos from
      // syncstate; the branch-local t advances syncstate only — the
      // impulse RATE stays the outer t in both branches)
      prod64 = $signed(syncstate[s][u]) * $signed({1'b0, pmi});
      ipos   = prod64 >>> (FQ + PMI_F - 24);
      ustate[s][u] = 0;
      last_level[s][u] = sat32($signed(last_level[s][u]) +
          qmul(dc_uni[s][u], 32'(oscstate[s][u] - syncstate[s][u])));
      oscstate[s][u]  = syncstate[s][u];
      syncstate[s][u] = ($signed(syncstate[s][u] + t_sync_u[s][u]) > 0) ?
          syncstate[s][u] + t_sync_u[s][u] : 64'sd0;
    end else begin
      prod64 = $signed(oscstate[s][u]) * $signed({1'b0, pmi});
      ipos   = prod64 >>> (FQ + PMI_F - 24);
    end
    ipos &= 32'hFFFFFFFF;
    t_rate = t_u[s][u];
    delay  = ipos[29:24];
    m_idx  = ipos[23:16];
    lipol  = ipos[15:0];
    wf  = l_shape[s]; sub = l_sub[s]; om1 = ONE - sub;
    if (ustate[s][u] == 0) begin
      pwidth[s][u]  = clamp_q(l_pw[s]);
      pwidth2[s][u] = qmul(2*ONE, l_pw2[s]);
    end
    pw = pwidth[s][u]; pw2v = pwidth2[s][u];
    case (ustate[s][u])
      0: begin
        // tg = ((1+wf)*0.5 + (1-pw)*(-wf))*(1-sub) + 0.5*sub*(2-pw2)
        tg = qmul(((ONE + wf + 32'sd1) >>> 1) + qmul(ONE - pw, -wf), om1)
           + qmul((sub + 32'sd1) >>> 1, 2*ONE - pw2v);
        g = tg - last_level[s][u];
        last_level[s][u] = tg;
        last_level[s][u] = last_level[s][u] - qmul(qmul(pw, pw2v), qmul(ONE + wf, om1));
      end
      1: begin
        g = qmul(wf, om1) - sub;
        last_level[s][u] = last_level[s][u] + g;
        last_level[s][u] = last_level[s][u] - qmul(qmul(ONE - pw, 2*ONE - pw2v), qmul(ONE + wf, om1));
      end
      2: begin
        g = ONE - sub;
        last_level[s][u] = last_level[s][u] + g;
        last_level[s][u] = last_level[s][u] - qmul(qmul(pw, 2*ONE - pw2v), qmul(ONE + wf, om1));
      end
      default: begin
        g = qmul(wf, om1) + sub;
        last_level[s][u] = last_level[s][u] + g;
        last_level[s][u] = last_level[s][u] - qmul(qmul(ONE - pw, pw2v), qmul(ONE + wf, om1));
      end
    endcase
    g = qmul(g, 32'(cfg[1]));   // g *= out_attenuation (engine op order)
    base = bufpos[s] + delay;
    for (k = 0; k < FIRN; k++) begin
      term = 32'(sinc_main[m_idx*FIRN + k])
           + qmul(32'(lipol), 32'(sinc_deriv[m_idx*FIRN + k]));
      ob[s][base + k] = sat32(ob[s][base + k] + qmul(term, g));
    end
    olddc = dc_uni[s][u];
    dc_uni[s][u] = qmul(qmul(t_inv_u[s][u], ONE + wf), om1);
    dcb[s][base + FIROFF] = sat32(dcb[s][base + FIROFF] + (dc_uni[s][u] - olddc));
    if ((ustate[s][u] & 1) != 0) rate = qmul(t_rate, ONE - pw);
    else                         rate = qmul(t_rate, pw);
    if (((ustate[s][u] + 1) & 2) != 0) rate = qmul(rate, 2*ONE - pw2v);
    else                               rate = qmul(rate, pw2v);
    oscstate[s][u] = ($signed(oscstate[s][u] + rate) > 0) ? oscstate[s][u] + rate : 64'sd0;
    ustate[s][u] = (ustate[s][u] + 1) & 3;
  endtask

  // ------------------------------------- output stage (serial-1, filters off)
  // x = (osc * lvl) * pfg ; scene += x * gain_ramp * outl
  task automatic output_stage;
    logic signed [31:0] x, gainv;
    begin
      for (k = 0; k < BLOCK_OS; k++) begin
        x = qmul(qmul(osout[s][k], 32'(cw[7])), 32'(cw[8]));
        gainv = 32'(cw[9]) + ((32'(cw[10]) * (k+1) + 32'sd32) >>> 6);
        scene_l[k] = scene_l[k] + qmul(qmul(x, gainv), 32'(cw[11]));
      end
      prev_gain[s] = 32'(cw[9]) + 32'(cw[10]);
      prev_outl[s] = 32'(cw[11]);
    end
  endtask

  // ------------------------------------------- halfband D2 + master output
  task automatic decimate_and_output(input logic [31:0] master_amp);
    logic signed [31:0] xb, xa, yb, ya;
    logic signed [31:0] chainb [BLOCK_OS];
    logic signed [31:0] chaina [BLOCK_OS];
    logic signed [31:0] bl, mm;
    for (k = 0; k < BLOCK_OS; k++) begin
      xb = scene_l[k]; xa = scene_l[k];   // mono bus: the R lane is identical
      for (i = 0; i < 6; i++) begin
        yb = hbx2_b[i] + qmul(32'(cfg[68+i]), xb - hby2_b[i]);
        hbx2_b[i] = hbx1_b[i]; hbx1_b[i] = xb;
        hby2_b[i] = hby1_b[i]; hby1_b[i] = yb;
        xb = yb;
        ya = hbx2_a[i] + qmul(32'(cfg[74+i]), xa - hby2_a[i]);
        hbx2_a[i] = hbx1_a[i]; hbx1_a[i] = xa;
        hby2_a[i] = hby1_a[i]; hby1_a[i] = ya;
        xa = ya;
      end
      chainb[k] = xb; chaina[k] = xa;
    end
    for (k = 0; k < BLOCK; k++) begin
      bl = clamp8(qround1(chaina[2*k] + chainb[2*k+1]));
      mm = clamp8(qmul(bl, 32'(master_amp)));   // L == R on the mono bus
      mm = clamp1(mm);
      $fwrite(fd, "M %0d %0d\n", b, mm);
    end
  endtask

  function automatic signed [31:0] qround1(input signed [31:0] v);
    qround1 = (v + 32'sd1) >>> 1;
  endfunction

  // checkpoint dump (mirrors the model trace "after" fields)
  task automatic dump_slot;
    begin
      $fwrite(fd, "T %0d %0d %0d %0d %0d %0d %0d", b, s, slot_key[s],
              aeg_state[s], aeg_phase[s], aeg_out_r[s], int'(cfg[0]));
      for (u = 0; u < MAXUNI; u++) begin
        if (u < int'(cfg[0]))
          $fwrite(fd, " %0d %0d %0d %0d %0d %0d %0d",
                  $signed(oscstate[s][u]), $signed(syncstate[s][u]),
                  ustate[s][u], last_level[s][u], pwidth[s][u],
                  pwidth2[s][u], dc_uni[s][u]);
        else
          $fwrite(fd, " 0 0 0 0 0 0 0");
      end
      $fwrite(fd, " %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
              l_shape[s], l_pw[s], l_pw2[s], l_sub[s], l_sync[s],
              dc_mdc[s], osc_out[s], osc_out2[s], bufpos[s], hpf_prev[s],
              prev_gain[s], prev_outl[s]);
      $fwrite(fd, "O %0d %0d", b, s);
      for (k = 0; k < BLOCK_OS; k++) $fwrite(fd, " %0d", osout[s][k]);
      $fwrite(fd, "\n");
    end
  endtask

endmodule
