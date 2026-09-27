// SXT-028h NEGATIVE-CONTROL RTL ONLY -- deliberately defective variants of
// rf_bins12_core, compiled INSTEAD of rtl/effects/rf-rf-bins12/
// rf_bins12_core.sv by tools/rf_bins12_negative_controls.py and required to
// FAIL the exact-equality check against the frozen model
// (model/effects/rf-rf-bins12/rf_bins12_model.py). A control that PASSES is
// a broken control (a finding), not a success.
//
// This file declares the SAME module name (`rf_bins12_core`) on purpose so
// that the production testbench (tb_rf_bins12.sv) and the production
// comparator drive it through exactly the same stimulus path as the real
// core -- the defect is the only difference. It is never compiled together
// with the real core, and nothing in the production flow references it.
//
// Select one defect at compile time:
//   iverilog -g2012 -DNC_SHARED_STATE ...   both insert slots POOL one
//       register set (the tb_fx_shared_line.sv "shared instead of
//       per-instance state" defect) -- must fail the dual-instance
//       checkpoint/output equality.
//   iverilog -g2012 -DNC_SWAP_ORDER ...     the bins1 -> bins2 series chain
//       is evaluated in the WRONG order (bins2 first; the reorderFx /
//       tools/ablate_fx.py permute defect) -- must fail the order-sensitive
//       equality.
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module rf_bins12_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done
);

  localparam int BLOCK  = 32;
  localparam int C_FRAC = 29;
  localparam logic signed [143:0] REG_LIM = 144'sd1 <<< 79;

  localparam logic [1:0] FXB_NO_FX = 2'd3;
  localparam int FXSLOT_BINS1 = 2, FXSLOT_BINS2 = 3;

  logic [1:0]  cfg_fx_bypass;
  logic [15:0] cfg_fx_disable;
  logic        cfg_slot1_occupied, cfg_slot2_occupied;
  logic        cfg_slot1_reload,   cfg_slot2_reload;
  logic signed [31:0] cfg_slot1_c [5];
  logic signed [31:0] cfg_slot2_c [5];

  logic signed [79:0] s1_reg0 [2];
  logic signed [79:0] s1_reg1 [2];
  logic signed [79:0] s2_reg0 [2];
  logic signed [79:0] s2_reg1 [2];
  logic prev_occ1 = 1'b0;
  logic prev_occ2 = 1'b0;

  logic signed [31:0] in_l  [BLOCK];
  logic signed [31:0] in_r  [BLOCK];
  logic signed [31:0] out_l [BLOCK];
  logic signed [31:0] out_r [BLOCK];
  logic                sc_in;
  logic                sc_out;

  localparam logic [2:0] S_IDLE=0, S_CTRL=1, S_GATE=2, S_S1=3, S_S2=4, S_DONE=5;
  logic [2:0] st = S_IDLE;
  logic       running = 1'b0;
  logic [5:0] k = 6'd0;
  logic       run_s1, run_s2;
  logic       sc_cur;

  function automatic logic signed [31:0] sat32(input logic signed [143:0] v);
    if      (v > 144'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -144'sd2147483648) sat32 = -32'sd2147483648;
    else                            sat32 = v[31:0];
  endfunction

  function automatic logic signed [79:0] sat80(input logic signed [143:0] v);
    if      (v > (REG_LIM - 1))   sat80 = REG_LIM - 1;
    else if (v < -REG_LIM)        sat80 = -REG_LIM;
    else                          sat80 = v[79:0];
  endfunction

  function automatic logic signed [31:0] rndsat32(input logic signed [143:0] x,
                                                   input int f);
    logic signed [143:0] r;
    r = (x + (144'sd1 <<< (f-1))) >>> f;
    rndsat32 = sat32(r);
  endfunction

  function automatic logic signed [143:0] rndshift(input logic signed [143:0] x,
                                                     input int f);
    rndshift = (x + (144'sd1 <<< (f-1))) >>> f;
  endfunction

  always @(posedge clk) begin
    if (state_reset) begin
      panic_clear();
    end else begin
      block_done <= 1'b0;
      case (st)
        S_IDLE: begin
          if (start_block) begin
            running <= 1'b1;
            st      <= S_CTRL;
          end
        end

        S_CTRL: begin
          if (!cfg_slot1_occupied || !prev_occ1 || cfg_slot1_reload)
            clear_slot1();
          if (!cfg_slot2_occupied || !prev_occ2 || cfg_slot2_reload)
            clear_slot2();
          prev_occ1 <= cfg_slot1_occupied;
          prev_occ2 <= cfg_slot2_occupied;
          st <= S_GATE;
        end

        S_GATE: begin
          for (int i = 0; i < BLOCK; i++) begin
            out_l[i] <= in_l[i];
            out_r[i] <= in_r[i];
          end
          if (cfg_fx_bypass == FXB_NO_FX) begin
            sc_out <= sc_in;
            st     <= S_DONE;
          end else begin
            run_s1 <= cfg_slot1_occupied && !cfg_fx_disable[FXSLOT_BINS1];
            run_s2 <= cfg_slot2_occupied && !cfg_fx_disable[FXSLOT_BINS2];
            sc_cur <= sc_in;
            k      <= 6'd0;
            st     <= S_S1;
          end
        end

`ifdef NC_SWAP_ORDER
        // DEFECT (NC_SWAP_ORDER): the series chain is evaluated bins2 FIRST,
        // then bins1 -- the slot-content permutation the wrong-order control
        // targets. Everything else is identical to the real core.
        S_S1: begin
          if (run_s2 && sc_cur) biquad_step(1, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_S2;
          end else k <= k + 1'b1;
        end
        S_S2: begin
          if (run_s1 && sc_cur) biquad_step(0, k);
          if (k == BLOCK-1) begin
            sc_out <= sc_cur;
            st     <= S_DONE;
          end else k <= k + 1'b1;
        end
`else
        S_S1: begin
          if (run_s1 && sc_cur) biquad_step(0, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_S2;
          end else k <= k + 1'b1;
        end
        S_S2: begin
          if (run_s2 && sc_cur) biquad_step(1, k);
          if (k == BLOCK-1) begin
            sc_out <= sc_cur;
            st     <= S_DONE;
          end else k <= k + 1'b1;
        end
`endif

        S_DONE: begin
          block_done <= 1'b1;
          running    <= 1'b0;
          st         <= S_IDLE;
        end
        default: st <= S_IDLE;
      endcase
    end
  end

  task automatic biquad_step(input int slot, input logic [5:0] kk);
    logic signed [143:0] op0, nr00, nr10, op1, nr01, nr11;
    logic signed [31:0]  c0, c1, c2, c3, c4;
    if (slot == 0) begin
      c0 = cfg_slot1_c[0]; c1 = cfg_slot1_c[1]; c2 = cfg_slot1_c[2];
      c3 = cfg_slot1_c[3]; c4 = cfg_slot1_c[4];
    end else begin
      c0 = cfg_slot2_c[0]; c1 = cfg_slot2_c[1]; c2 = cfg_slot2_c[2];
      c3 = cfg_slot2_c[3]; c4 = cfg_slot2_c[4];
    end
`ifdef NC_SHARED_STATE
    // DEFECT (NC_SHARED_STATE): BOTH slots read and write ONE pooled
    // register set (s1_reg*), i.e. shared instead of per-instance state --
    // the tb_fx_shared_line.sv defect. s2_reg* is left permanently zero, so
    // the dual-instance checkpoint cannot match either.
    op0  = (144'(out_l[kk]) * c0) + s1_reg0[0];
    nr00 = (144'(out_l[kk]) * c1) + s1_reg1[0]
           - rndshift(144'(c3) * op0, C_FRAC);
    nr10 = (144'(out_l[kk]) * c2) - rndshift(144'(c4) * op0, C_FRAC);
    if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
      $fatal(1, "mutant biquad reg overflow (L) slot=%0d k=%0d", slot, kk);
    s1_reg0[0] = sat80(nr00); s1_reg1[0] = sat80(nr10);
    out_l[kk] = rndsat32(op0, C_FRAC);
    op1  = (144'(out_r[kk]) * c0) + s1_reg0[1];
    nr01 = (144'(out_r[kk]) * c1) + s1_reg1[1]
           - rndshift(144'(c3) * op1, C_FRAC);
    nr11 = (144'(out_r[kk]) * c2) - rndshift(144'(c4) * op1, C_FRAC);
    if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
      $fatal(1, "mutant biquad reg overflow (R) slot=%0d k=%0d", slot, kk);
    s1_reg0[1] = sat80(nr01); s1_reg1[1] = sat80(nr11);
    out_r[kk] = rndsat32(op1, C_FRAC);
`else
    op0  = (144'(out_l[kk]) * c0)
           + (slot == 0 ? s1_reg0[0] : s2_reg0[0]);
    nr00 = (144'(out_l[kk]) * c1) + (slot == 0 ? s1_reg1[0] : s2_reg1[0])
           - rndshift(144'(c3) * op0, C_FRAC);
    nr10 = (144'(out_l[kk]) * c2) - rndshift(144'(c4) * op0, C_FRAC);
    if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
      $fatal(1, "mutant biquad reg overflow (L) slot=%0d k=%0d", slot, kk);
    if (slot == 0) begin s1_reg0[0] = sat80(nr00); s1_reg1[0] = sat80(nr10); end
    else           begin s2_reg0[0] = sat80(nr00); s2_reg1[0] = sat80(nr10); end
    out_l[kk] = rndsat32(op0, C_FRAC);
    op1  = (144'(out_r[kk]) * c0)
           + (slot == 0 ? s1_reg0[1] : s2_reg0[1]);
    nr01 = (144'(out_r[kk]) * c1) + (slot == 0 ? s1_reg1[1] : s2_reg1[1])
           - rndshift(144'(c3) * op1, C_FRAC);
    nr11 = (144'(out_r[kk]) * c2) - rndshift(144'(c4) * op1, C_FRAC);
    if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
      $fatal(1, "mutant biquad reg overflow (R) slot=%0d k=%0d", slot, kk);
    if (slot == 0) begin s1_reg0[1] = sat80(nr01); s1_reg1[1] = sat80(nr11); end
    else           begin s2_reg0[1] = sat80(nr01); s2_reg1[1] = sat80(nr11); end
    out_r[kk] = rndsat32(op1, C_FRAC);
`endif
  endtask

  task automatic clear_slot1;
    integer ri;
    begin
      for (ri = 0; ri < 2; ri++) begin
        s1_reg0[ri] <= 80'sd0;
        s1_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  task automatic clear_slot2;
    integer ri;
    begin
      for (ri = 0; ri < 2; ri++) begin
        s2_reg0[ri] <= 80'sd0;
        s2_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  task automatic panic_clear;
    integer ri;
    begin
      st      <= S_IDLE;
      running <= 1'b0;
      k       <= 6'd0;
      run_s1  <= 1'b0;
      run_s2  <= 1'b0;
      sc_cur     <= 1'b0;
      sc_out     <= 1'b0;
      block_done <= 1'b0;
      for (ri = 0; ri < 2; ri++) begin
        s1_reg0[ri] <= 80'sd0;
        s1_reg1[ri] <= 80'sd0;
        s2_reg0[ri] <= 80'sd0;
        s2_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  initial panic_clear();

  // A mutant compiled with NO defect selected would behave exactly like the
  // real core and report a spurious CONTROL-OK. Refuse to simulate instead.
`ifndef NC_SHARED_STATE
`ifndef NC_SWAP_ORDER
  initial $fatal(1, "rf_bins12_mutants.sv compiled with no defect selected: use -DNC_SHARED_STATE or -DNC_SWAP_ORDER");
`endif
`endif

endmodule
