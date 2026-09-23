// SXT-028a Airwindows "Galactic" (streamed id 49) core: sequential
// audio-rate datapath implementing the SAME integer schedule as the frozen
// fixed-point model (model/effects/aw-49/galactic_model.py, frozen
// Q6.25-in-32-bit word, c31/c30 coefficients, round-half-up, saturating).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality of every output word, every per-block checkpoint, and
// every external-memory transaction; tools/compare_rtl_model_aw49.py). NOT
// synthesis-closed, NOT timing-closed; no gf180mcu FPGA/ASIC claim. The
// schedule is a sequential operation stream (SXT-022/024 precedent).
//
// Long-buffer state is NEVER on-chip: 26 regions (126354 x 32b words per
// instance at instance-relative MEM_BASE) behind an explicit external-
// memory port (em_*). Per output frame (48 kHz, cycleEnd=1): 28 READs +
// 26 WRITEs = 54 words = 216 B (SXT-015/016 reconciliation).
//
// Control plane: coefficient words preloaded by the harness; per-sample
// vibrato read positions (baseL, fracqL, baseR, fracqR) stream in - vibM
// is a control-plane accumulator (DR-0006 tap; model README).
//
// Structure citations (read, not copied): airwindows GalacticProc.cpp
// processReplacing() + Galactic.h constructor state, via the pinned
// surge@58914e59 AirWindowsEffect adapter. Original to this repository
// (Apache-2.0).
`timescale 1ns/1ps

module galactic_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done,
    input  logic [31:0] mem_base,
    output logic [31:0] em_addr,
    output logic        em_req,
    output logic        em_we,
    output logic signed [31:0] em_wdata,
    input  logic signed [31:0] em_rdata
);

  localparam int BLOCK = 32;
  localparam int W_I = 6480, W_J = 3660, W_K = 1720, W_L = 680;
  localparam int W_A = 9700, W_B = 6000, W_C = 2320, W_D = 940;
  localparam int W_E = 15220, W_F = 8460, W_G = 4540, W_H = 3200;
  localparam int AM = 257;
  // layout mirrors the model: all 12 L lines, all 12 R lines, then the two
  // vibrato lines (aML, aMR) - instance-relative, model REGIONS table order
  localparam int unsigned R_I  = 0;
  localparam int unsigned R_J  = R_I + W_I;
  localparam int unsigned R_K  = R_J + W_J;
  localparam int unsigned R_L  = R_K + W_K;
  localparam int unsigned R_A  = R_L + W_L;
  localparam int unsigned R_B  = R_A + W_A;
  localparam int unsigned R_C  = R_B + W_B;
  localparam int unsigned R_D  = R_C + W_C;
  localparam int unsigned R_E  = R_D + W_D;
  localparam int unsigned R_F  = R_E + W_E;
  localparam int unsigned R_G  = R_F + W_F;
  localparam int unsigned R_H  = R_G + W_G;
  localparam int unsigned R_IR = R_H + W_H;
  localparam int unsigned R_JR = R_IR + W_I;
  localparam int unsigned R_KR = R_JR + W_J;
  localparam int unsigned R_LR = R_KR + W_K;
  localparam int unsigned R_AR = R_LR + W_L;
  localparam int unsigned R_BR = R_AR + W_A;
  localparam int unsigned R_CR = R_BR + W_B;
  localparam int unsigned R_DR = R_CR + W_C;
  localparam int unsigned R_ER = R_DR + W_D;
  localparam int unsigned R_FR = R_ER + W_E;
  localparam int unsigned R_GR = R_FR + W_F;
  localparam int unsigned R_HR = R_GR + W_G;
  localparam int unsigned R_ML = R_HR + W_H;
  localparam int unsigned R_MR = R_ML + AM;
  function automatic int unsigned DELAYS(input int n);
    case (n)
      0: return W_I; 1: return W_J; 2: return W_K; 3: return W_L;
      4: return W_A; 5: return W_B; 6: return W_C; 7: return W_D;
      8: return W_E; 9: return W_F; 10: return W_G; 11: return W_H;
    endcase
    return 0;
  endfunction

  // ------------------------------------------------------ coefficient plane
  logic signed [31:0] cfg_regen;        // c31
  logic signed [31:0] cfg_attenuate;    // c30
  logic signed [31:0] cfg_lowpass;      // c31
  logic signed [31:0] cfg_lowpass_m1;  // c31 (2^31 - lp)
  logic signed [31:0] cfg_wet;          // c31
  logic signed [31:0] cfg_wet_m1;       // c31
  logic               cfg_wet_active;
  logic signed [31:0] cfg_delay [12];

  // on-chip state (mirrors the model's checkpoint)
  logic signed [31:0] counts [12];
  logic signed [31:0] countM;
  logic signed [31:0] iir_a_l, iir_a_r, iir_b_l, iir_b_r;
  logic signed [31:0] fb_al, fb_bl, fb_cl, fb_dl;
  logic signed [31:0] fb_ar, fb_br, fb_cr, fb_dr;

  // block I/O + per-sample control stream (harness-loaded)
  logic signed [31:0] in_l [BLOCK];
  logic signed [31:0] in_r [BLOCK];
  logic signed [31:0] out_l [BLOCK];
  logic signed [31:0] out_r [BLOCK];
  logic signed [31:0] ctrl [4*BLOCK];   // baseL,fracqL,baseR,fracqR

  // FSM
  localparam logic [4:0] S_IDLE=0, S_VIBWR=1, S_VIBRD=2, S_IIRA=3,
                         S_S1WR=4, S_S1ADV=5, S_S1RD=6,
                         S_S2WR=7, S_S2ADV=8, S_S2RD=9,
                         S_S3WR=10, S_S3ADV=11, S_S3RD=12,
                         S_CORE=13, S_DONE=14;
  logic [4:0] st = S_IDLE;
  logic running = 1'b0;
  logic [4:0] k = 5'd0;
  logic [2:0] ln = 3'd0;        // line/cycle index inside a state

  // per-sample values
  logic signed [31:0] v_l, v_r;
  logic signed [31:0] vib_prev;
  // stage-1 read results
  logic signed [31:0] o_i_l, o_j_l, o_k_l, o_l_l;
  logic signed [31:0] o_i_r, o_j_r, o_k_r, o_l_r;
  // stage-2 read results
  logic signed [31:0] o_a_l, o_b_l, o_c_l, o_d_l;
  logic signed [31:0] o_a_r, o_b_r, o_c_r, o_d_r;
  // stage-3 read results
  logic signed [31:0] o_e_l, o_f_l, o_g_l, o_h_l;
  logic signed [31:0] o_e_r, o_f_r, o_g_r, o_h_r;
  // active shared read indices for a stage (after advance)
  logic [31:0] adv_idx [4];
  // S_CORE temporaries (blocking-assigned)
  logic signed [31:0] nel, nfl, ngl, nhl, ner, nfr, ngr, nhr;
  logic signed [31:0] core_l, core_r, ibl, ibr, mixl, mixr;

  function automatic logic signed [31:0] sat32(input logic signed [127:0] v);
    if      (v > 127'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -127'sd2147483648) sat32 = -32'sd2147483648;
    else                            sat32 = v[31:0];
  endfunction

  function automatic logic signed [31:0] rndsat32(input logic signed [127:0] x,
                                                  input int f);
    logic signed [127:0] r;
    r = (x + (128'sd1 <<< (f-1))) >>> f;
    rndsat32 = sat32(r);
  endfunction

  // vibrato read index: the model advances countM BEFORE the reads, so the
  // base pointer is the wrapped (countM + 1); reads are (cm + base [+1])
  // with the pinned conditional 257 wrap.
  function automatic logic [31:0] vib_idx(input int which);
    logic [31:0] base;
    logic [31:0] cm;
    cm = (countM + 1 > 32'd256) ? 32'd0 : countM + 1;
    if (which < 2) base = cm + 32'(ctrl[4*k]);
    else           base = cm + 32'(ctrl[4*k + 2]);
    if (which == 1 || which == 3) base = base + 1;
    if (base > 32'd256) base = base - 32'd257;
    return base;
  endfunction

  // stage-1 write value: L lines <- v_l + rnd(fb_R * regen); R <- v_r + rnd(fb_L * regen)
  function automatic logic signed [31:0] s1_wval(input logic [2:0] n);
    logic signed [31:0] x, fb;
    if (n < 4) begin x = v_l; end
    case (n)
      0: fb = fb_ar;
      1: fb = fb_br;
      2: fb = fb_cr;
      3: fb = fb_dr;
      4: begin x = v_r; fb = fb_al; end
      5: begin x = v_r; fb = fb_bl; end
      6: begin x = v_r; fb = fb_cl; end
      7: begin x = v_r; fb = fb_dl; end
    endcase
    // pinned: inputSample + feedback*regen -- the product rounds to Q6.25,
    // the sum only saturates (no second rounding)
    return sat32(128'(x) + ((128'(fb) * cfg_regen + (128'sd1 <<< 30)) >>> 31));
  endfunction

  function automatic int unsigned s1_region(input logic [2:0] n);
    case (n)
      0: return R_I; 1: return R_J; 2: return R_K; 3: return R_L;
      4: return R_IR; 5: return R_JR; 6: return R_KR; 7: return R_LR;
    endcase
    return 0;
  endfunction
  function automatic int unsigned s2_region(input logic [2:0] n);
    case (n)
      0: return R_A; 1: return R_B; 2: return R_C; 3: return R_D;
      4: return R_AR; 5: return R_BR; 6: return R_CR; 7: return R_DR;
    endcase
    return 0;
  endfunction
  function automatic int unsigned s3_region(input logic [2:0] n);
    case (n)
      0: return R_E; 1: return R_F; 2: return R_G; 3: return R_H;
      4: return R_ER; 5: return R_FR; 6: return R_GR; 7: return R_HR;
    endcase
    return 0;
  endfunction
  function automatic logic [31:0] stage_count(input logic [1:0] stage,
                                              input logic [1:0] line);
    return counts[{stage, line}];
  endfunction

  // stage-2 write values (exact Hadamard rows, saturated)
  function automatic logic signed [31:0] s2_wval(input logic [2:0] n);
    if (n < 4) begin
      case (n)
        0: return sat32(128'(o_i_l) - (o_j_l + o_k_l + o_l_l));
        1: return sat32(128'(o_j_l) - (o_i_l + o_k_l + o_l_l));
        2: return sat32(128'(o_k_l) - (o_i_l + o_j_l + o_l_l));
        3: return sat32(128'(o_l_l) - (o_i_l + o_j_l + o_k_l));
      endcase
    end else begin
      case (n[1:0])
        0: return sat32(128'(o_i_r) - (o_j_r + o_k_r + o_l_r));
        1: return sat32(128'(o_j_r) - (o_i_r + o_k_r + o_l_r));
        2: return sat32(128'(o_k_r) - (o_i_r + o_j_r + o_l_r));
        3: return sat32(128'(o_l_r) - (o_i_r + o_j_r + o_k_r));
      endcase
    end
    return 0;
  endfunction

  // stage-3 write values
  function automatic logic signed [31:0] s3_wval(input logic [2:0] n);
    if (n < 4) begin
      case (n)
        0: return sat32(128'(o_a_l) - (o_b_l + o_c_l + o_d_l));
        1: return sat32(128'(o_b_l) - (o_a_l + o_c_l + o_d_l));
        2: return sat32(128'(o_c_l) - (o_a_l + o_b_l + o_d_l));
        3: return sat32(128'(o_d_l) - (o_a_l + o_b_l + o_c_l));
      endcase
    end else begin
      case (n[1:0])
        0: return sat32(128'(o_a_r) - (o_b_r + o_c_r + o_d_r));
        1: return sat32(128'(o_b_r) - (o_a_r + o_c_r + o_d_r));
        2: return sat32(128'(o_c_r) - (o_a_r + o_b_r + o_d_r));
        3: return sat32(128'(o_d_r) - (o_a_r + o_b_r + o_c_r));
      endcase
    end
    return 0;
  endfunction

  // combinational external-memory request
  logic [31:0] wcount;
  always @* begin
    case (st)
      S_S1WR, S_S1RD: wcount = 32'(counts[{2'b00, ln[1:0]}]);
      S_S2WR, S_S2RD: wcount = 32'(counts[{2'b01, ln[1:0]}]);
      S_S3WR, S_S3RD: wcount = 32'(counts[{2'b10, ln[1:0]}]);
      default: wcount = 0;
    endcase
  end

  always @* begin
    em_req = 1'b0;
    em_we  = 1'b0;
    em_addr  = 32'b0;
    em_wdata = 32'sd0;
    if (running) begin
      case (st)
        S_VIBWR: begin
          em_req   = 1'b1;
          em_we    = 1'b1;
          em_addr  = (ln == 0) ? mem_base + R_ML + countM
                               : mem_base + R_MR + countM;
          em_wdata = (ln == 0)
            ? rndsat32(128'(cfg_attenuate) * in_l[k], 30)
            : rndsat32(128'(cfg_attenuate) * in_r[k], 30);
        end
        S_VIBRD: begin
          em_req = 1'b1;
          em_addr = (ln < 2) ? mem_base + R_ML + vib_idx(ln)
                             : mem_base + R_MR + vib_idx(ln);
        end
        S_S1WR: begin
          em_req   = 1'b1;
          em_we    = 1'b1;
          em_addr  = mem_base + s1_region(ln) + wcount;
          em_wdata = s1_wval(ln);
        end
        S_S1RD: begin
          em_req  = 1'b1;
          em_addr = mem_base + s1_region(ln) + adv_idx[ln[1:0]];
        end
        S_S2WR: begin
          em_req   = 1'b1;
          em_we    = 1'b1;
          em_addr  = mem_base + s2_region(ln) + wcount;
          em_wdata = s2_wval(ln);
        end
        S_S2RD: begin
          em_req  = 1'b1;
          em_addr = mem_base + s2_region(ln) + adv_idx[ln[1:0]];
        end
        S_S3WR: begin
          em_req   = 1'b1;
          em_we    = 1'b1;
          em_addr  = mem_base + s3_region(ln) + wcount;
          em_wdata = s3_wval(ln);
        end
        S_S3RD: begin
          em_req  = 1'b1;
          em_addr = mem_base + s3_region(ln) + adv_idx[ln[1:0]];
        end
        default: ;
      endcase
    end
  end

  // advance one counter with wrap (shared across the L/R pair)
  function automatic logic [31:0] advance(input logic [31:0] c,
                                          input logic [31:0] d);
    return (c + 1 > d) ? 0 : c + 1;
  endfunction

  always @(posedge clk) begin
    if (state_reset) begin
      clear_state();
    end else begin
      block_done <= 1'b0;
      case (st)
        S_IDLE: if (start_block) begin
          k <= 0; running <= 1'b1; st <= S_VIBWR; ln <= 0;
        end

        S_VIBWR: begin
          if (ln == 1) begin
            ln <= 0; st <= S_VIBRD;
          end else ln <= ln + 1;
        end

        S_VIBRD: begin
          // four reads: aML[i0], aML[i0+1] -> v_l; aMR[j0], aMR[j0+1] -> v_r
          // one-rounding interpolation: rnd25(a0*w1 + a1*fracq)
          if (ln == 1) begin
            // one-rounding interp: rnd25(a0*(2^31 - fracq) + a1*fracq);
            // the 2^31 complement is computed in the 128-bit domain (it
            // overflows signed-32 when fracq = 0)
            v_l <= rndsat32(128'(vib_prev) * ((128'sd1 <<< 31) - 128'(ctrl[4*k + 1]))
                            + 128'(em_rdata) * 128'(ctrl[4*k + 1]), 31);
          end
          if (ln == 3) begin
            v_r <= rndsat32(128'(vib_prev) * ((128'sd1 <<< 31) - 128'(ctrl[4*k + 3]))
                            + 128'(em_rdata) * 128'(ctrl[4*k + 3]), 31);
            ln <= 0; st <= S_IIRA;
          end else ln <= ln + 1;
          vib_prev <= em_rdata;
        end

        S_IIRA: begin
          // input one-pole (both channels); the filtered value REPLACES the
          // sample value (pinned: inputSample = iirAL after the filter)
          begin
            logic signed [31:0] tl, tr;
            tl = rndsat32(128'(iir_a_l) * cfg_lowpass_m1
                          + 128'(v_l) * cfg_lowpass, 31);
            tr = rndsat32(128'(iir_a_r) * cfg_lowpass_m1
                          + 128'(v_r) * cfg_lowpass, 31);
            iir_a_l <= tl; iir_a_r <= tr;
            v_l <= tl; v_r <= tr;
          end
          st <= S_S1WR; ln <= 0;
        end

        S_S1WR: begin
          if (ln == 7) begin ln <= 0; st <= S_S1ADV; end
          else ln <= ln + 1;
        end

        S_S1ADV: begin
          // counters advance one per cycle; the read index is captured in
          // the SAME cycle (post-advance value)
          counts[{2'b00, ln[1:0]}] <= advance(counts[{2'b00, ln[1:0]}],
                                              32'(cfg_delay[{2'b00, ln[1:0]}]));
          adv_idx[ln[1:0]] <= advance(counts[{2'b00, ln[1:0]}],
                                      32'(cfg_delay[{2'b00, ln[1:0]}]));
          if (ln == 3) begin
            ln <= 0; st <= S_S1RD;
          end else ln <= ln + 1;
        end

        S_S1RD: begin
          case (ln)
            0: o_i_l <= em_rdata;
            1: o_j_l <= em_rdata;
            2: o_k_l <= em_rdata;
            3: o_l_l <= em_rdata;
            4: o_i_r <= em_rdata;
            5: o_j_r <= em_rdata;
            6: o_k_r <= em_rdata;
            7: o_l_r <= em_rdata;
          endcase
          if (ln == 7) begin ln <= 0; st <= S_S2WR; end
          else ln <= ln + 1;
        end

        S_S2WR: begin
          if (ln == 7) begin ln <= 0; st <= S_S2ADV; end
          else ln <= ln + 1;
        end

        S_S2ADV: begin
          counts[{2'b01, ln[1:0]}] <= advance(counts[{2'b01, ln[1:0]}],
                                              32'(cfg_delay[{2'b01, ln[1:0]}]));
          adv_idx[ln[1:0]] <= advance(counts[{2'b01, ln[1:0]}],
                                      32'(cfg_delay[{2'b01, ln[1:0]}]));
          if (ln == 3) begin
            ln <= 0; st <= S_S2RD;
          end else ln <= ln + 1;
        end

        S_S2RD: begin
          case (ln)
            0: o_a_l <= em_rdata;
            1: o_b_l <= em_rdata;
            2: o_c_l <= em_rdata;
            3: o_d_l <= em_rdata;
            4: o_a_r <= em_rdata;
            5: o_b_r <= em_rdata;
            6: o_c_r <= em_rdata;
            7: o_d_r <= em_rdata;
          endcase
          if (ln == 7) begin ln <= 0; st <= S_S3WR; end
          else ln <= ln + 1;
        end

        S_S3WR: begin
          if (ln == 7) begin ln <= 0; st <= S_S3ADV; end
          else ln <= ln + 1;
        end

        S_S3ADV: begin
          counts[{2'b10, ln[1:0]}] <= advance(counts[{2'b10, ln[1:0]}],
                                              32'(cfg_delay[{2'b10, ln[1:0]}]));
          adv_idx[ln[1:0]] <= advance(counts[{2'b10, ln[1:0]}],
                                      32'(cfg_delay[{2'b10, ln[1:0]}]));
          if (ln == 3) begin
            ln <= 0; st <= S_S3RD;
          end else ln <= ln + 1;
        end

        S_S3RD: begin
          case (ln)
            0: o_e_l <= em_rdata;
            1: o_f_l <= em_rdata;
            2: o_g_l <= em_rdata;
            3: o_h_l <= em_rdata;
            4: o_e_r <= em_rdata;
            5: o_f_r <= em_rdata;
            6: o_g_r <= em_rdata;
            7: o_h_r <= em_rdata;
          endcase
          if (ln == 7) begin ln <= 0; st <= S_CORE; end
          else ln <= ln + 1;
        end

        S_CORE: begin
          // feedback registers + core + iirB + mix for sample k
          nel = sat32(128'(o_e_l) - (o_f_l + o_g_l + o_h_l));
          nfl = sat32(128'(o_f_l) - (o_e_l + o_g_l + o_h_l));
          ngl = sat32(128'(o_g_l) - (o_e_l + o_f_l + o_h_l));
          nhl = sat32(128'(o_h_l) - (o_e_l + o_f_l + o_g_l));
          ner = sat32(128'(o_e_r) - (o_f_r + o_g_r + o_h_r));
          nfr = sat32(128'(o_f_r) - (o_e_r + o_g_r + o_h_r));
          ngr = sat32(128'(o_g_r) - (o_e_r + o_f_r + o_h_r));
          nhr = sat32(128'(o_h_r) - (o_e_r + o_f_r + o_g_r));
          fb_al <= nel; fb_bl <= nfl; fb_cl <= ngl; fb_dl <= nhl;
          fb_ar <= ner; fb_br <= nfr; fb_cr <= ngr; fb_dr <= nhr;
          core_l = (o_e_l + o_f_l + o_g_l + o_h_l) >>> 3;
          core_r = (o_e_r + o_f_r + o_g_r + o_h_r) >>> 3;
          ibl = rndsat32(128'(iir_b_l) * cfg_lowpass_m1
                         + 128'(core_l) * cfg_lowpass, 31);
          ibr = rndsat32(128'(iir_b_r) * cfg_lowpass_m1
                         + 128'(core_r) * cfg_lowpass, 31);
          iir_b_l <= ibl;
          iir_b_r <= ibr;
          if (cfg_wet_active) begin
            mixl = rndsat32(128'(ibl) * cfg_wet + 128'(in_l[k]) * cfg_wet_m1, 31);
            mixr = rndsat32(128'(ibr) * cfg_wet + 128'(in_r[k]) * cfg_wet_m1, 31);
          end else begin
            mixl = ibl; mixr = ibr;
          end
          out_l[k] <= mixl;
          out_r[k] <= mixr;
          // vibrato counter advance (shared M, once per sample)
          countM <= (countM + 1 > 32'd256) ? 0 : countM + 1;
          if (k == BLOCK-1) begin k <= 0; st <= S_DONE; end
          else begin k <= k + 1; st <= S_VIBWR; ln <= 0; end
        end

        S_DONE: begin
          block_done <= 1'b1;
          running    <= 1'b0;
          st         <= S_IDLE;
        end
        default: st <= S_IDLE;
      endcase
    end
  end

  task automatic clear_state;
    integer i;
    begin
      st <= S_IDLE; running <= 1'b0; k <= 0; ln <= 0;
      countM <= 32'sd1;
      for (i = 0; i < 12; i++) counts[i] <= 32'sd1;
      iir_a_l <= 0; iir_a_r <= 0; iir_b_l <= 0; iir_b_r <= 0;
      fb_al <= 0; fb_bl <= 0; fb_cl <= 0; fb_dl <= 0;
      fb_ar <= 0; fb_br <= 0; fb_cr <= 0; fb_dr <= 0;
      v_l <= 0; v_r <= 0;
      block_done <= 1'b0;
      for (i = 0; i < BLOCK; i++) begin
        out_l[i] <= 0; out_r[i] <= 0;
      end
    end
  endtask
  initial clear_state();

endmodule
