// SXT-022 RTL voice slice: audio-rate datapath + envelope state machines for
// factory preset `Basses/Attacky.fxp`, implementing the SAME integer schedule
// as the frozen fixed-point model (model/voice/voice_model.py).
//
// Claim scope: this RTL is simulated with iverilog and must match the frozen
// model EXACTLY (integer equality at every declared checkpoint; enforced by
// tools/compare_rtl_model.py). It is NOT synthesis-closed, NOT timing-closed,
// and makes no gf180mcu FPGA/ASIC claim of any kind. The schedule is a
// sequential operation stream; op counts are reported separately in
// reports/sxt-022/EVIDENCE.md under the declared 1-MAC cost model.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/dsp/oscillators/ClassicOscillator.cpp (convolute/process_block)
//   src/common/dsp/QuadFilterChain.cpp ProcessFBQuad (fc_serial1)
//   libs/sst/sst-filters QuadFilterUnit_Impl.h IIR12CFCquad
//   src/common/dsp/modulators/ADSRModulationSource.h (digital mode)
//   libs/sst/sst-filters HalfRateFilter.h (M=6, steep) process_block_D2
//   sst-basic-blocks OscillatorDriftUnisonCharacter.h CharacterFilter (Warm)
//
// Stimulus (declared control-plane boundary; emitted by model/voice/run_model.py):
//   init.hex   one-time constants: envelope RATES (rate-table outputs), lag
//              targets, character filter, vca/out/master gains, instant-attack
//              flags, lag rate, and the 12 halfband coefficients
//   ctrl.hex   per-block control words (coefficient plane: C/dC, gain/out
//              targets, pitchmult/a_cov/hpf target, slot flags)
//   sinc_main.hex / sinc_deriv.hex   sinctable ROM (model-generated)
`timescale 1ns/1ps

module tb_voice;

  localparam int FQ       = 21;
  localparam int F_PHASE  = 29;
  localparam int PMI_F    = 18;
  localparam int BLOCK    = 32;
  localparam int BLOCK_OS = 64;
  localparam int OB_LEN   = 128;
  localparam int FIRN     = 12;
  localparam int FIROFF   = 6;
  localparam int NSLOTS   = 8;

  localparam logic signed [31:0] ONE      = 32'sd2097152;    // 1.0 Q10.21
  localparam logic signed [31:0] PH_ONE   = 32'sd536870912;  // 1.0 Q2.29
  localparam logic [31:0] S_ATTACK = 0, S_DECAY = 1, S_RELEASE = 3, S_IDLE = 6;

  int unsigned qmul_count = 0;

  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << 19)) >>> 21;
    if      (r > 64'sd2147483647)  qmul = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  function automatic signed [31:0] sat32(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = v[31:0];
  endfunction

  function automatic signed [31:0] maxs(input signed [31:0] a, input signed [31:0] b);
    maxs = ($signed(a) > $signed(b)) ? a : b;
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
  // cfg word map (INIT_ORDER in run_model.py):
  //  0..2  aeg rate a/d/r (Q2.29)  3 aeg_s (Q2.29)  4 aeg_r_s (int)
  //  5..7  feg rate a/d/r (Q2.29)  8 feg_s (Q2.29)  9 feg_r_s (int)
  // 10..14 lag targets shape/pw/pw2/sub/sync (Q10.21)
  // 15..17 char a1/b0/b1  18 o1_level  19 vca_gain  20 outl_word
  // 21 master_amp  22 total_blocks  23 t_const  24 t_inv  25 lag_rate
  // 26 inst_att_aeg  27 inst_att_feg  28..33 halfband B0..B5  34..39 A0..A5
  logic [31:0] cfg [0:39];
  // ctrl block header: [b, ncreate, modwheel, master_amp]
  // ctrl slot record (32 words):
  //  0 flags(b0 active,b1 ckpt,b2 created,b3 released)  1 key  2 gate
  //  3 aeg_state 4 feg_state  5 pmi(Q13.18) 6 pitchmult 7 a_cov 8 hpf_target
  //  9..16 C0..C7  17..24 dC0..dC7  25 fbp_gain 26 fbp_outl
  //  27 aeg_phase 28 aeg_out 29 feg_phase 30 feg_out  31 reserved
  logic [31:0] ctrl_mem [0:4200000];

  // --------------------------------------------------------- per-slot state
  logic signed [31:0] ob    [NSLOTS][OB_LEN + FIRN];
  logic signed [31:0] dcb   [NSLOTS][OB_LEN + FIRN];
  logic signed [31:0] aeg_phase [NSLOTS], aeg_out_r [NSLOTS], aeg_scale [NSLOTS];
  logic [31:0]  aeg_state [NSLOTS], aeg_idle [NSLOTS];
  logic signed [31:0] feg_phase [NSLOTS], feg_out_r [NSLOTS], feg_scale [NSLOTS];
  logic [31:0]  feg_state [NSLOTS], feg_idle [NSLOTS];
  logic signed [31:0] oscstate [NSLOTS], last_level [NSLOTS], pwidth [NSLOTS],
      pwidth2 [NSLOTS], dc_uni [NSLOTS], dc_mdc [NSLOTS], osc_out [NSLOTS],
      osc_out2 [NSLOTS];
  logic [31:0]  osc_state [NSLOTS], bufpos [NSLOTS], hpf_prev [NSLOTS];
  logic signed [31:0] f_r0 [NSLOTS], f_r1 [NSLOTS], f_clip [NSLOTS];
  logic signed [31:0] prev_gain [NSLOTS], prev_outl [NSLOTS];
  logic signed [31:0] l_shape [NSLOTS], l_pw [NSLOTS], l_pw2 [NSLOTS],
      l_sub [NSLOTS], l_sync [NSLOTS];
  logic signed [31:0] osout [NSLOTS][BLOCK_OS];
  logic        active [NSLOTS];
  logic [31:0] slot_ckpt [NSLOTS], slot_key [NSLOTS], slot_gate [NSLOTS];

  // scene + decimator state
  logic signed [31:0] scene_l [BLOCK_OS];
  logic signed [31:0] hbx1_b [6], hbx2_b [6], hby1_b [6], hby2_b [6];
  logic signed [31:0] hbx1_a [6], hbx2_a [6], hby1_a [6], hby2_a [6];

  // control words for the slot being processed
  logic signed [31:0] cw [32];

  integer fd;
  integer b, s, k, i, w;
  logic [31:0] ipos, delay, m_idx, lipol, base;
  logic signed [63:0] prod64;
  logic signed [31:0] t_const, t_inv, g, tg, olddc, rate, term, hpf_start,
      hpf_d, hpf_v, acc, obv, last_oo, mdc, lvl, oa;
  logic signed [31:0] c [8];
  logic signed [31:0] gain_start, outl_start, d_gain, d_outl, gainv, outlv,
      outv, xv, y, s1v, s2v;

  initial begin
    $readmemh("rtl/sinc_main.hex",  sinc_main);
    $readmemh("rtl/sinc_deriv.hex", sinc_deriv);
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ctrl.hex", ctrl_mem);
    fd = $fopen("tb_trace.txt", "w");
    t_const = 32'(cfg[23]);
    t_inv   = 32'(cfg[24]);
    for (i = 0; i < 6; i++) begin
      hbx1_b[i]=0; hbx2_b[i]=0; hby1_b[i]=0; hby2_b[i]=0;
      hbx1_a[i]=0; hbx2_a[i]=0; hby1_a[i]=0; hby2_a[i]=0;
    end
    run();
    $fclose(fd);
    $display("DONE qmuls=%0d blocks=%0d", qmul_count, cfg[22]);
    $finish;
  end

  task automatic run;
    int total_blocks, ci;
    logic [31:0] master_amp;
    total_blocks = int'(cfg[22]);
    ci = 0;
    for (b = 0; b < total_blocks; b++) begin
      if (ctrl_mem[ci] !== 32'hxxxxxxxx && int'(ctrl_mem[ci]) != b)
        $fatal(1, "ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      master_amp = ctrl_mem[ci+3];
      ci += 4;
      for (k = 0; k < BLOCK_OS; k++) scene_l[k] = 0;
      for (s = 0; s < NSLOTS; s++) begin
        for (i = 0; i < 32; i++) cw[i] = ctrl_mem[ci + s*32 + i];
        slot_ckpt[s] = cw[0][1];
        slot_key[s]  = cw[1];
        slot_gate[s] = cw[2];
        process_slot();
      end
      ci += NSLOTS*32;
      decimate_and_output(master_amp);
    end
  endtask

  // --------------------------------------------------------------- envelope
  task automatic adsr_tick(input integer is_aeg);
    logic [31:0] rate_a, rate_d, rate_r, sus, r_s;
    logic signed [31:0] ph, l_lo, l_hi, ov, scl;
    logic [31:0] st, idl;
    if (is_aeg) begin
      rate_a=cfg[0]; rate_d=cfg[1]; rate_r=cfg[2]; sus=cfg[3]; r_s=cfg[4];
      st=aeg_state[s]; ph=aeg_phase[s]; ov=aeg_out_r[s]; scl=aeg_scale[s];
      idl=aeg_idle[s];
    end else begin
      rate_a=cfg[5]; rate_d=cfg[6]; rate_r=cfg[7]; sus=cfg[8]; r_s=cfg[9];
      st=feg_state[s]; ph=feg_phase[s]; ov=feg_out_r[s]; scl=feg_scale[s];
      idl=feg_idle[s];
    end
    if (st == S_ATTACK) begin
      ph = ph + rate_a;
      if ($signed(ph) >= $signed(PH_ONE)) begin ph = PH_ONE; st = S_DECAY; end
      ov = ph >>> (F_PHASE - FQ);
    end else if (st == S_DECAY) begin
      l_lo = ph - rate_d; l_hi = ph + rate_d;
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
      idl = idl + 1;
    end
    if ($signed(ov) < 0) ov = 0;
    if ($signed(ov) > $signed(ONE)) ov = ONE;
    if (is_aeg) begin
      aeg_state[s]=st; aeg_phase[s]=ph; aeg_out_r[s]=ov; aeg_idle[s]=idl;
    end else begin
      feg_state[s]=st; feg_phase[s]=ph; feg_out_r[s]=ov; feg_idle[s]=idl;
    end
  endtask

  // ------------------------------------------------------------------ voice
  task automatic process_slot;
    if (!cw[0][0]) begin active[s] = 0; return; end
    if (cw[0][2]) init_voice();
    if (cw[0][3]) begin
      aeg_scale[s] = aeg_out_r[s]; aeg_phase[s] = PH_ONE; aeg_state[s] = S_RELEASE;
      feg_scale[s] = feg_out_r[s]; feg_phase[s] = PH_ONE; feg_state[s] = S_RELEASE;
    end
    adsr_tick(1);
    adsr_tick(0);
    osc_block();
    filter_chain();
    if (slot_ckpt[s]) dump_slot();
    if (aeg_state[s] == S_IDLE && aeg_idle[s] > 0) active[s] = 0;
  endtask

  task automatic init_voice;
    for (w = 0; w < OB_LEN + FIRN; w++) begin ob[s][w] = 0; dcb[s][w] = 0; end
    oscstate[s]=0; osc_state[s]=0; last_level[s]=0;
    dc_uni[s]=0; dc_mdc[s]=0; osc_out[s]=0; osc_out2[s]=0; bufpos[s]=0;
    l_shape[s]=32'(cfg[10]); l_pw[s]=32'(cfg[11]); l_pw2[s]=32'(cfg[12]);
    l_sub[s]=32'(cfg[13]); l_sync[s]=32'(cfg[14]);
    pwidth[s]=clamp_q(l_pw[s]); pwidth2[s]=0;
    hpf_prev[s]=cw[8];
    f_r0[s]=0; f_r1[s]=0; f_clip[s]=ONE;
    aeg_phase[s]=0; aeg_out_r[s]=0; aeg_idle[s]=0; aeg_scale[s]=ONE;
    feg_phase[s]=0; feg_out_r[s]=0; feg_idle[s]=0; feg_scale[s]=ONE;
    aeg_state[s]=S_ATTACK; feg_state[s]=S_ATTACK;
    if (cfg[26] != 0) begin aeg_state[s]=S_DECAY; aeg_out_r[s]=ONE; aeg_phase[s]=PH_ONE; end
    if (cfg[27] != 0) begin feg_state[s]=S_DECAY; feg_out_r[s]=ONE; feg_phase[s]=PH_ONE; end
    adsr_tick(1); adsr_tick(0);              // constructor envelope step
    prev_gain[s] = qmul(32'(cfg[19]), aeg_out_r[s]);
    prev_outl[s] = 32'(cfg[20]);
    active[s] = 1;
  endtask

  // -------------------------------------------------- classic osc (1 voice)
  task automatic osc_block;
    logic signed [31:0] lag_rate;
    logic [31:0] a_cov, pmi;
    lag_rate = 32'(cfg[25]);
    l_shape[s] = l_shape[s] + qmul(lag_rate, 32'(cfg[10]) - l_shape[s]);
    l_pw[s]    = l_pw[s]    + qmul(lag_rate, 32'(cfg[11]) - l_pw[s]);
    l_pw2[s]   = l_pw2[s]   + qmul(lag_rate, 32'(cfg[12]) - l_pw2[s]);
    l_sub[s]   = l_sub[s]   + qmul(lag_rate, 32'(cfg[13]) - l_sub[s]);
    l_sync[s]  = l_sync[s]  + qmul(lag_rate, 32'(cfg[14]) - l_sync[s]);
    hpf_start  = hpf_prev[s];
    hpf_d      = $signed(cw[8]) - $signed(hpf_start);
    hpf_prev[s]= cw[8];
    pmi   = cw[5];
    a_cov = cw[7];
    while ($signed(oscstate[s]) < $signed(a_cov)) convolute(pmi);
    oscstate[s] = oscstate[s] - a_cov;
    oa  = qmul(ONE, 32'(cw[6]));
    mdc = dc_mdc[s];
    for (k = 0; k < BLOCK_OS; k++) begin
      hpf_v = hpf_start + ((hpf_d * (k+1) + 32'sd32) >>> 6);
      acc = qmul(osc_out[s], hpf_v);
      mdc = mdc + dcb[s][bufpos[s] + k];
      obv = ob[s][bufpos[s] + k] - qmul(mdc, oa);
      last_oo = osc_out[s];
      osc_out[s] = sat32(acc + obv);
      osc_out2[s] = qmul(osc_out2[s], 32'(cfg[15]))
                  + qmul(osc_out[s], 32'(cfg[16]))
                  + qmul(last_oo, 32'(cfg[17]));
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

  task automatic convolute(input logic [31:0] pmi);
    logic signed [31:0] wf, sub, om1, pw, pw2v, term1, term2;
    prod64 = $signed(oscstate[s]) * $signed({1'b0, pmi});
    ipos   = prod64 >>> (FQ + PMI_F - 24);
    delay  = ipos[29:24];
    m_idx  = ipos[23:16];
    lipol  = ipos[15:0];
    wf  = l_shape[s]; sub = l_sub[s]; om1 = ONE - sub;
    if (osc_state[s] == 0) begin
      pwidth[s]  = clamp_q(l_pw[s]);
      pwidth2[s] = qmul(2*ONE, l_pw2[s]);
    end
    pw = pwidth[s]; pw2v = pwidth2[s];
    case (osc_state[s])
      0: begin
        term1 = (ONE + wf + 32'sd1) >>> 1;             // (1+wf)/2, round-half-up
        term2 = qmul(ONE - pw, -wf);
        tg = qmul(term1 + term2, om1) + qmul((sub + 32'sd1) >>> 1, 2*ONE - pw2v);
        g = tg - last_level[s];
        last_level[s] = tg;
        last_level[s] = last_level[s] - qmul(qmul(pw, pw2v), qmul(ONE + wf, om1));
      end
      1: begin
        g = qmul(wf, om1) - sub;
        last_level[s] = last_level[s] + g;
        last_level[s] = last_level[s] - qmul(qmul(ONE - pw, 2*ONE - pw2v), qmul(ONE + wf, om1));
      end
      2: begin
        g = ONE - sub;
        last_level[s] = last_level[s] + g;
        last_level[s] = last_level[s] - qmul(qmul(pw, 2*ONE - pw2v), qmul(ONE + wf, om1));
      end
      default: begin
        g = qmul(wf, om1) + sub;
        last_level[s] = last_level[s] + g;
        last_level[s] = last_level[s] - qmul(qmul(ONE - pw, pw2v), qmul(ONE + wf, om1));
      end
    endcase
    base = bufpos[s] + delay;
    for (k = 0; k < FIRN; k++) begin
      term = 32'(sinc_main[m_idx*FIRN + k])
           + qmul(32'(lipol), 32'(sinc_deriv[m_idx*FIRN + k]));
      ob[s][base + k] = sat32(ob[s][base + k] + qmul(term, g));
    end
    olddc = dc_uni[s];
    dc_uni[s] = qmul(t_inv, qmul(ONE + wf, om1));
    dcb[s][base + FIROFF] = sat32(dcb[s][base + FIROFF] + (dc_uni[s] - olddc));
    if ((osc_state[s] & 1) != 0) rate = qmul(t_const, ONE - pw);
    else                         rate = qmul(t_const, pw);
    if (((osc_state[s] + 1) & 2) != 0) rate = qmul(rate, 2*ONE - pw2v);
    else                               rate = qmul(rate, pw2v);
    oscstate[s] = ($signed(oscstate[s] + rate) > 0) ? oscstate[s] + rate : 0;
    osc_state[s] = (osc_state[s] + 1) & 3;
  endtask

  // ----------------------------------------------- filter chain (serial 1)
  task automatic filter_chain;
    gain_start = prev_gain[s];
    outl_start = prev_outl[s];
    d_gain = $signed(cw[25]) - gain_start;
    d_outl = $signed(cw[26]) - outl_start;
    for (i = 0; i < 8; i++) c[i] = cw[9 + i];
    lvl = 32'(cfg[18]);
    for (k = 0; k < BLOCK_OS; k++) begin
      for (i = 0; i < 8; i++) c[i] = sat32(c[i] + cw[17 + i]);
      xv = qmul(osout[s][k], lvl);
      y  = qmul(c[4], f_r0[s]) + qmul(c[6], xv) + qmul(c[5], f_r1[s]);
      s1v = qmul(xv, c[2]) + qmul(c[0], f_r0[s]) - qmul(c[1], f_r1[s]);
      s2v = qmul(c[1], f_r0[s]) + qmul(c[0], f_r1[s]);
      f_r0[s] = qmul(s1v, f_clip[s]);
      f_r1[s] = qmul(s2v, f_clip[s]);
      f_clip[s] = maxs(32'sd209715, ONE - qmul(c[7], qmul(y, y)));
      gainv = gain_start + ((d_gain * (k+1) + 32'sd32) >>> 6);
      outlv = outl_start + ((d_outl * (k+1) + 32'sd32) >>> 6);
      outv = qmul(y, gainv);
      scene_l[k] = scene_l[k] + qmul(outv, outlv);
    end
    prev_gain[s] = cw[25];
    prev_outl[s] = cw[26];
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
        yb = hbx2_b[i] + qmul(32'(cfg[28+i]), xb - hby2_b[i]);
        hbx2_b[i] = hbx1_b[i]; hbx1_b[i] = xb;
        hby2_b[i] = hby1_b[i]; hby1_b[i] = yb;
        xb = yb;
        ya = hbx2_a[i] + qmul(32'(cfg[34+i]), xa - hby2_a[i]);
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

  // checkpoint dump (mirrors model trace "after" fields + block C_end)
  task automatic dump_slot;
    $fwrite(fd, "T %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
      b, s, slot_key[s], slot_gate[s],
      aeg_state[s], aeg_phase[s], aeg_out_r[s],
      feg_state[s], feg_phase[s], feg_out_r[s],
      oscstate[s], osc_state[s], last_level[s], pwidth[s], pwidth2[s],
      dc_uni[s], dc_mdc[s], osc_out[s], osc_out2[s], bufpos[s],
      f_r0[s], f_r1[s], f_clip[s],
      c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]);
    $fwrite(fd, "O %0d %0d", b, s);
    for (k = 0; k < BLOCK_OS; k++) $fwrite(fd, " %0d", osout[s][k]);
    $fwrite(fd, "\n");
  endtask

endmodule
