// SXT-024 Reverb1 core: sequential audio-rate datapath implementing the SAME
// integer schedule as the frozen fixed-point model
// (model/effects/reverb1/reverb1_fixed.py, frozen Q4.28/32-bit-word format).
//
// Claim scope: this RTL is simulated with iverilog and must match the frozen
// model EXACTLY (integer equality of every output word, every per-block
// checkpoint, and every external-memory transaction; enforced by
// tools/run_reverb_rtl.py). It is NOT synthesis-closed, NOT timing-closed,
// and makes no gf180mcu FPGA/ASIC claim of any kind. The schedule is a
// sequential operation stream (SXT-022 precedent); op counts are reported in
// reports/sxt-024/EVIDENCE.md.
//
// Long-buffer state is NEVER on-chip: the composite tap array (524288 x 32b)
// and the predelay line (32768 x 32b) live behind an explicit external-memory
// request port (em_*). Every access is visible on that port and logged by the
// harness: per output frame 16 tap READs (one contiguous 16-word row burst),
// 1 predelay READ, 1 predelay WRITE, 16 tap WRITEs (one contiguous 16-word
// row burst) = 34 words / 136 B per frame, reconciled with SXT-015/016.
// State reset is a harness pulse on state_reset; the long-buffer bulk clear
// is a host-side memory action outside this port (logged as a marker by both
// the model and the harness transaction logs).
//
// Frozen arithmetic (mirrors reverb1_fixed.py bit-exactly):
//   rnd_f(x) = (x + (1 <<< (f-1))) >>> f   (round-half-up, arithmetic shift)
//   sat32(x) = clamp(x, -2^31, 2^31-1)
//   s32i = Q4.28 in 32-bit containers (sign + 3 headroom int bits; +/-8)
//   c31 = Q1.31, c30 = Q2.30, c29 = Q3.29, biquad state = 80-bit signed
//   I/O: s24 in: << 5 (exact); FX-block outputs stay s32i (unclamped) -- the
//   s24 device clamp belongs to the final output stage (to_s24), not here.
//
// Control-plane boundary: coefficient words (quantized by the coefficient
// plane, model/effects/reverb1/coefficient_plane.py) are preloaded by the
// harness (equivalent to a configuration bus). Coefficients are control-rate
// inputs and outside the RTL-vs-model exactness claim, which covers the
// audio-rate datapath and its state.
//
// Structure citations (read, not copied): sst-effects
// include/sst/effects/Reverb1.h processBlock()/loadpreset()/update_rtime()
// via surge@58914e59 src/common/dsp/effects/Reverb1Effect.cpp (wrapper).
//
// Original to this repository (Apache-2.0). No Surge source, tables, or
// assets are copied.
`timescale 1ns/1ps

module reverb1_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done,
    // external memory port (single-cycle, zero-wait-state)
    output logic [31:0] em_addr,
    output logic        em_req,
    output logic        em_we,
    output logic signed [31:0] em_wdata,
    input  logic signed [31:0] em_rdata
);

  localparam int REV_BITS    = 15;
  localparam int MAX_REV_DLY = 1 << REV_BITS;          // 32768
  localparam int TAPS        = 16;
  localparam int TAP_WORDS   = TAPS * MAX_REV_DLY;     // 524288
  localparam int PD_BASE     = TAP_WORDS;              // predelay line base
  localparam int BLOCK       = 32;

  localparam logic signed [127:0] REG_LIM = 128'sd1 <<< 79; // biquad |reg| < 2^79

  // ------------------------------------------------------ coefficient plane
  logic signed [31:0] cfg_dt       [TAPS];  // delay_time, 256ths of a sample
  logic signed [31:0] cfg_dfb      [TAPS];  // delay_fb, c31
  logic signed [31:0] cfg_pan_l    [TAPS];  // c31
  logic signed [31:0] cfg_pan_r    [TAPS];  // c31
  logic signed [31:0] cfg_damp;             // c31
  logic signed [31:0] cfg_damp_m1;          // c31
  logic signed [31:0] cfg_mix;              // c30
  logic signed [31:0] cfg_mix_m1;           // c30
  logic signed [31:0] cfg_width_s;          // c30
  logic signed [31:0] cfg_bi_locut [5];     // c29: b0,b1,b2,a1,a2
  logic signed [31:0] cfg_bi_band1 [5];     // c29
  logic signed [31:0] cfg_bi_hicut [5];     // c29
  logic               cfg_locut_active;
  logic               cfg_hicut_active;
  logic signed [31:0] cfg_pdtime;           // predelay read distance (samples)

  // --------------------------------------------------------- on-chip state
  logic [REV_BITS-1:0] delay_pos;
  logic signed [31:0]  out_tap [TAPS];
  // flat biquad TDF2 state: [0..5] = reg0 for (filter, ch) = fi*2+ch,
  // [6..11] = reg1 in the same order (single-index: hierarchical multi-dim
  // selects are unreliable across simulators)
  logic signed [79:0]  bregs [12];

  // --------------------------------------------------------- block I/O bufs
  // (harness-loaded per block: s24 input words; s32i output words)
  logic signed [31:0] in_l [BLOCK];
  logic signed [31:0] in_r [BLOCK];
  logic signed [31:0] out_l [BLOCK];
  logic signed [31:0] out_r [BLOCK];

  // ------------------------------------------------------------ FSM state
  localparam logic [3:0] S_IDLE=0, S_TAP_RD=1, S_FB=2, S_PD_WR=3, S_TAP_WR=4,
                         S_BIQ=5, S_WIDTH=6, S_MIX=7, S_DONE=8;
  logic [3:0]         st = S_IDLE;
  logic               running = 1'b0;
  logic [4:0]         k = 5'd0;       // sample index 0..31
  logic [4:0]         t = 5'd0;       // tap index 0..15
  logic [2:0]         bi = 3'd0;      // biquad filter index 0..2
  logic               ch = 1'b0;      // biquad channel 0=L, 1=R
  logic signed [36:0] fbsum = 37'sd0;  // exact sum of the 16 updated out_taps
  logic signed [36:0] fbw;     // -(fbsum>>>3) + predelay read
  logic signed [31:0] wet_l [BLOCK];
  logic signed [31:0] wet_r [BLOCK];

  // ------------------------------------------------------------ functions
  function automatic logic signed [31:0] sat32(input logic signed [127:0] v);
    if      (v > 127'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -127'sd2147483648) sat32 = -32'sd2147483648;
    else                            sat32 = v[31:0];
  endfunction

  // (x + 2^(f-1)) >>> f then saturate to s32 -- mirrors rnd()/sat32() exactly
  function automatic logic signed [31:0] rndsat32(input logic signed [127:0] x,
                                                  input int f);
    logic signed [127:0] r;
    r = (x + (128'sd1 <<< (f-1))) >>> f;
    rndsat32 = sat32(r);
  endfunction

  // combinational external-memory request (zero-wait-state single cycle)
  integer dp_tmp;
  always @* begin
    em_req = 1'b0;
    em_we  = 1'b0;
    em_addr  = 32'b0;
    em_wdata = 32'sd0;
    if (running) begin
      case (st)
        S_TAP_RD: begin
          em_req  = 1'b1;
          dp_tmp  = $signed({1'b0, delay_pos}) - (cfg_dt[t] >>> 8);
          em_addr = 32'(((dp_tmp & (MAX_REV_DLY-1)) << 4) + t);
        end
        S_FB: begin
          em_req  = 1'b1;
          dp_tmp  = $signed({1'b0, delay_pos}) - cfg_pdtime;
          em_addr = 32'(PD_BASE + (dp_tmp & (MAX_REV_DLY-1)));
        end
        S_PD_WR: begin
          em_req   = 1'b1;
          em_we    = 1'b1;
          em_addr  = 32'(PD_BASE + ((delay_pos + 1'b1) & (MAX_REV_DLY-1)));
          em_wdata = sat32((128'((in_l[k] <<< 5) + (in_r[k] <<< 5))) >>> 1);
        end
        S_TAP_WR: begin
          em_req   = 1'b1;
          em_we    = 1'b1;
          em_addr  = 32'(((delay_pos & (MAX_REV_DLY-1)) << 4) + t);
          em_wdata = rndsat32(128'(cfg_dfb[t]) * (fbw + out_tap[t]), 31);
        end
        default: ;
      endcase
    end
  end

  // ------------------------------------------------------------- datapath
  always @(posedge clk) begin
    if (state_reset) begin
      clear_state();
    end else begin
      block_done <= 1'b0;
      case (st)
        S_IDLE: begin
          if (start_block) begin
            k       <= 0;
            running <= 1'b1;
            st      <= S_TAP_RD;
          end
        end

        // 1. damped tap outputs: 16 external READs (one 16-word row burst)
        //    out_tap[t] = sat32(rnd31(damp*out_tap[t] + (1-damp)*new))
        S_TAP_RD: begin
          if (t == 0) fbsum <= rndsat32(cfg_damp * out_tap[0]
                                        + cfg_damp_m1 * em_rdata, 31);
          else fbsum <= fbsum + rndsat32(cfg_damp * out_tap[t]
                                         + cfg_damp_m1 * em_rdata, 31);
          out_tap[t] <= rndsat32(cfg_damp * out_tap[t]
                                 + cfg_damp_m1 * em_rdata, 31);
          if (t == TAPS-1) begin st <= S_FB; t <= 0; end
          else             t <= t + 1;
        end

        // 2. fbw = -(fbsum>>>3) + predelay[(delay_pos - pdtime) & mask]
        S_FB: begin
          fbw <= (-(fbsum >>> 3)) + em_rdata;
          st  <= S_PD_WR;
        end

        // 3. advance delay_pos; predelay[delay_pos] = 0.5*(L+R) (exact >>1)
        S_PD_WR: begin
          delay_pos <= delay_pos + 1'b1;
          st        <= S_TAP_WR;
        end

        // 4. 16 external WRITEs (one 16-word row burst) + pan sums
        S_TAP_WR: begin
          if (t == 0) begin
            wet_l[k] <= rndsat32(128'(cfg_pan_l[0]) * out_tap[0], 31);
            wet_r[k] <= rndsat32(128'(cfg_pan_r[0]) * out_tap[0], 31);
          end else begin
            wet_l[k] <= wet_l[k] + rndsat32(128'(cfg_pan_l[t]) * out_tap[t], 31);
            wet_r[k] <= wet_r[k] + rndsat32(128'(cfg_pan_r[t]) * out_tap[t], 31);
          end
          if (t == TAPS-1) begin
            t <= 0;
            if (k == BLOCK-1) begin
              k  <= 0;
              bi <= cfg_locut_active ? 3'd0 : 3'd1;
              ch <= 1'b0;
              st <= S_BIQ;
            end else begin
              k  <= k + 1;
              st <= S_TAP_RD;
            end
          end else t <= t + 1;
        end

        // 5. biquads in pinned order: (locut L,R) -> band1 L,R -> (hicut L,R)
        S_BIQ: begin
          biq_stage();
          if (k == BLOCK-1) begin
            k <= 0;
            if (ch == 0) ch <= 1'b1;
            else begin
              ch <= 1'b0;
              if (bi == 3'd2 || (bi == 3'd1 && !cfg_hicut_active)) st <= S_WIDTH;
              else bi <= bi + 1'b1;
            end
          end else k <= k + 1;
        end

        // 6. width (dB mode, side only)
        S_WIDTH: begin
          width_stage();
          if (k == BLOCK-1) begin k <= 0; st <= S_MIX; end
          else k <= k + 1;
        end

        // 7. mix: out = rnd30((1-mix)*dry + mix*wet), dry widened << 5
        S_MIX: begin
          out_l[k] <= rndsat32(128'(cfg_mix_m1) * (in_l[k] <<< 5)
                               + 128'(cfg_mix) * wet_l[k], 30);
          out_r[k] <= rndsat32(128'(cfg_mix_m1) * (in_r[k] <<< 5)
                               + 128'(cfg_mix) * wet_r[k], 30);
          if (k == BLOCK-1) st <= S_DONE;
          else k <= k + 1;
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

  // state clear: mirrors the frozen model's reset() (constructor state too --
  // power-on calls this once so inactive-filter biquad regs are defined)
  task automatic clear_state;
    integer ri;
    begin
      st        <= S_IDLE;
      running   <= 1'b0;
      delay_pos <= '0;
      for (ri = 0; ri < TAPS; ri++) out_tap[ri] <= 32'sd0;
      for (ri = 0; ri < 12; ri++) bregs[ri] <= '0;
      block_done <= 1'b0;
      k  <= 5'd0;
      t  <= 5'd0;
      bi <= 3'd0;
      ch <= 1'b0;
      fbsum <= 37'sd0;
      for (ri = 0; ri < BLOCK; ri++) begin
        wet_l[ri] <= 32'sd0;
        wet_r[ri] <= 32'sd0;
      end
    end
  endtask

  initial clear_state();

  // TDF2 stage for one (filter bi, channel ch, sample k): the frozen model's
  // _biquad with c29 coefficients and 2^-57-scale accumulators (f = 29).
  task automatic biq_stage;
    logic signed [127:0] op, nr0, nr1, y;
    logic signed [31:0]  x, b0, b1, b2, a1, a2;
    x  = ch ? wet_r[k] : wet_l[k];
    b0 = (bi == 0) ? cfg_bi_locut[0] : (bi == 1) ? cfg_bi_band1[0]
                                                 : cfg_bi_hicut[0];
    b1 = (bi == 0) ? cfg_bi_locut[1] : (bi == 1) ? cfg_bi_band1[1]
                                                 : cfg_bi_hicut[1];
    b2 = (bi == 0) ? cfg_bi_locut[2] : (bi == 1) ? cfg_bi_band1[2]
                                                 : cfg_bi_hicut[2];
    a1 = (bi == 0) ? cfg_bi_locut[3] : (bi == 1) ? cfg_bi_band1[3]
                                                 : cfg_bi_hicut[3];
    a2 = (bi == 0) ? cfg_bi_locut[4] : (bi == 1) ? cfg_bi_band1[4]
                                                 : cfg_bi_hicut[4];
    op   = 128'(x) * b0 + bregs[bi*2 + ch];
    nr0  = 128'(x) * b1 + bregs[6 + bi*2 + ch]
           - ((128'(a1) * op + (128'sd1 <<< 28)) >>> 29);
    nr1  = 128'(x) * b2 - ((128'(a2) * op + (128'sd1 <<< 28)) >>> 29);
    if (nr0 >= REG_LIM - 1 || nr0 <= -(REG_LIM))
      $fatal(1, "biquad reg0 overflow bi=%0d ch=%0d", bi, ch);
    if (nr1 >= REG_LIM - 1 || nr1 <= -(REG_LIM))
      $fatal(1, "biquad reg1 overflow bi=%0d ch=%0d", bi, ch);
    bregs[bi*2 + ch]     = nr0;
    bregs[6 + bi*2 + ch] = nr1;
    y = rndsat32(op, 29);
    if (ch) wet_r[k] = y; else wet_l[k] = y;
  endtask

  // width stage for sample k (blocking: feeds the mix stage next cycles)
  task automatic width_stage;
    logic signed [33:0] mid, sd;
    logic signed [127:0] p;
    mid = (wet_l[k] + wet_r[k]) >>> 1;
    p   = 128'((wet_l[k] - wet_r[k]) >>> 1) * cfg_width_s;
    sd  = 34'(rndsat32(p, 30));
    wet_l[k] = sat32(128'(mid) + sd);
    wet_r[k] = sat32(128'(mid) - sd);
  endtask

endmodule
