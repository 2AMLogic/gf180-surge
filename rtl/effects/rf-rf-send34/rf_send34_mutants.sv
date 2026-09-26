// SXT-028l NEGATIVE-CONTROL RTL ONLY -- deliberately defective variants of
// rf_send34_core, compiled INSTEAD of rtl/effects/rf-rf-send34/
// rf_send34_core.sv by tools/rf_send34_negative_controls.py and required to
// FAIL the exact-equality check against the frozen model
// (model/effects/rf-rf-send34/rf_send34_model.py). A control that PASSES is a
// broken control (a finding), not a success.
//
// This file declares the SAME module name (`rf_send34_core`) on purpose so
// that the production testbench (tb_rf_send34.sv) and the production
// comparator drive it through exactly the same stimulus path as the real
// core -- the defect is the only difference. It is never compiled together
// with the real core, and nothing in the production flow references it.
//
// Select one defect at compile time:
//   iverilog -g2012 -DNC_SHARED_STATE ...   both send buses POOL one register
//       set (the tb_fx_shared_line.sv "shared instead of per-instance state"
//       defect) -- must fail the dual-instance checkpoint/output equality.
//   iverilog -g2012 -DNC_SWAP_ORDER ...     the two buses' OCCUPANTS are
//       permuted (send3's bus is processed by send4's instance and vice
//       versa) while each bus keeps its own gain plane -- the reorderFx /
//       tools/ablate_fx.py permute defect for a PARALLEL routing form. Must
//       fail the order-sensitive equality.
//   iverilog -g2012 -DNC_TAIL_KILL ...      both buses are skipped whenever
//       the incoming SCENE buses are entirely silent, dropping the
//       occupants' arithmetic tails -- must fail the declared tail case (and
//       is NOT caught by the non-silent baseline case, which is exactly what
//       makes the tail case load-bearing).
//   iverilog -g2012 -DNC_GAIN_SWAP ...      send-form-specific: the per-bus
//       GAIN PLACEMENT is swapped -- the return gain is applied when FORMING
//       the bus and the scene-A send gain when RETURNING it. The same three
//       numbers are used, in the wrong places; must fail exact equality.
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module rf_send34_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done
);

  localparam int BLOCK  = 32;
  localparam int C_FRAC = 29;
  localparam int G_FRAC = 30;
  localparam logic signed [143:0] REG_LIM = 144'sd1 <<< 79;

  localparam logic [1:0] FXB_ALL_FX = 2'd0;
  localparam int FXSLOT_SEND3 = 12, FXSLOT_SEND4 = 13;

  logic [1:0]  cfg_fx_bypass;
  logic [15:0] cfg_fx_disable;
  logic        cfg_scene_b_active;
  logic        cfg_slot3_occupied, cfg_slot4_occupied;
  logic        cfg_slot3_reload,   cfg_slot4_reload;
  logic signed [31:0] cfg_slot3_c [5];
  logic signed [31:0] cfg_slot4_c [5];
  logic signed [31:0] cfg_bus3_g  [3];
  logic signed [31:0] cfg_bus4_g  [3];

  logic signed [79:0] s3_reg0 [2];
  logic signed [79:0] s3_reg1 [2];
  logic signed [79:0] s4_reg0 [2];
  logic signed [79:0] s4_reg1 [2];
  logic prev_occ3 = 1'b0;
  logic prev_occ4 = 1'b0;

  logic signed [31:0] sa_l   [BLOCK];
  logic signed [31:0] sa_r   [BLOCK];
  logic signed [31:0] sb_l   [BLOCK];
  logic signed [31:0] sb_r   [BLOCK];
  logic signed [31:0] main_l [BLOCK];
  logic signed [31:0] main_r [BLOCK];
  logic signed [31:0] out_l  [BLOCK];
  logic signed [31:0] out_r  [BLOCK];
  logic signed [31:0] wet3_l [BLOCK];
  logic signed [31:0] wet3_r [BLOCK];
  logic signed [31:0] wet4_l [BLOCK];
  logic signed [31:0] wet4_r [BLOCK];
  logic               send_in3, send_in4;
  logic               ring3, ring4;

  localparam logic [2:0] S_IDLE=0, S_CTRL=1, S_GATE=2, S_B3=3, S_B4=4,
                         S_SUM=5, S_DONE=6;
  logic [2:0] st = S_IDLE;
  logic       running = 1'b0;
  logic [5:0] k = 6'd0;
  logic       run_b3, run_b4;
`ifdef NC_TAIL_KILL
  // DEFECT (NC_TAIL_KILL) support: "are the incoming scene buses entirely
  // silent?"
  logic       blk_silent;
`endif

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
          if (!cfg_slot3_occupied || !prev_occ3 || cfg_slot3_reload)
            clear_slot3();
          if (!cfg_slot4_occupied || !prev_occ4 || cfg_slot4_reload)
            clear_slot4();
          prev_occ3 <= cfg_slot3_occupied;
          prev_occ4 <= cfg_slot4_occupied;
          st <= S_GATE;
        end

        S_GATE: begin
          for (int i = 0; i < BLOCK; i++) begin
            wet3_l[i] <= 32'sd0; wet3_r[i] <= 32'sd0;
            wet4_l[i] <= 32'sd0; wet4_r[i] <= 32'sd0;
          end
`ifdef NC_TAIL_KILL
          blk_silent <= 1'b1;
          for (int i = 0; i < BLOCK; i++)
            if (sa_l[i] != 32'sd0 || sa_r[i] != 32'sd0 ||
                sb_l[i] != 32'sd0 || sb_r[i] != 32'sd0) blk_silent <= 1'b0;
`endif
          if (cfg_fx_bypass != FXB_ALL_FX) begin
            for (int i = 0; i < BLOCK; i++) begin
              out_l[i] <= main_l[i];
              out_r[i] <= main_r[i];
            end
            ring3  <= 1'b0;
            ring4  <= 1'b0;
            run_b3 <= 1'b0;
            run_b4 <= 1'b0;
            st     <= S_DONE;
          end else begin
            run_b3 <= cfg_slot3_occupied && !cfg_fx_disable[FXSLOT_SEND3];
            run_b4 <= cfg_slot4_occupied && !cfg_fx_disable[FXSLOT_SEND4];
            ring3  <= (cfg_slot3_occupied &&
                       !cfg_fx_disable[FXSLOT_SEND3]) && send_in3;
            ring4  <= (cfg_slot4_occupied &&
                       !cfg_fx_disable[FXSLOT_SEND4]) && send_in4;
            k      <= 6'd0;
            st     <= S_B3;
          end
        end

`ifdef NC_TAIL_KILL
        // DEFECT (NC_TAIL_KILL): both buses are skipped when the incoming
        // scene buses are silent, so the occupants' arithmetic tails are
        // dropped and their registers freeze instead of decaying.
        S_B3: begin
          if (run_b3 && !blk_silent) bus_step(0, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_B4;
          end else k <= k + 1'b1;
        end
        S_B4: begin
          if (run_b4 && !blk_silent) bus_step(1, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_SUM;
          end else k <= k + 1'b1;
        end
`else
        S_B3: begin
          if (run_b3) bus_step(0, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_B4;
          end else k <= k + 1'b1;
        end
        S_B4: begin
          if (run_b4) bus_step(1, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_SUM;
          end else k <= k + 1'b1;
        end
`endif

        S_SUM: begin
          sum_step(k);
          if (k == BLOCK-1) st <= S_DONE;
          else              k  <= k + 1'b1;
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

  task automatic bus_step(input int bus, input logic [5:0] kk);
    logic signed [143:0] accl, accr, op0, nr00, nr10, op1, nr01, nr11;
    logic signed [31:0]  xl, xr, c0, c1, c2, c3, c4, ga, gb;
    logic                live;
`ifdef NC_SWAP_ORDER
    // DEFECT (NC_SWAP_ORDER): the two buses' OCCUPANTS are permuted -- bus 3
    // is processed by send4's coefficients + registers and bus 4 by send3's,
    // while each bus keeps its own gain plane. This is the parallel-form
    // equivalent of the series leaves' evaluate-in-the-wrong-order defect
    // (reorderFx / tools/ablate_fx.py permute).
    logic                swapped;
    swapped = (bus == 0) ? 1'b1 : 1'b0;   // 1 => use slot4 state on bus3
`endif
    if (bus == 0) begin
      c0 = cfg_slot3_c[0]; c1 = cfg_slot3_c[1]; c2 = cfg_slot3_c[2];
      c3 = cfg_slot3_c[3]; c4 = cfg_slot3_c[4];
      ga = cfg_bus3_g[0];  gb = cfg_bus3_g[1];
      live = send_in3;
    end else begin
      c0 = cfg_slot4_c[0]; c1 = cfg_slot4_c[1]; c2 = cfg_slot4_c[2];
      c3 = cfg_slot4_c[3]; c4 = cfg_slot4_c[4];
      ga = cfg_bus4_g[0];  gb = cfg_bus4_g[1];
      live = send_in4;
    end
`ifdef NC_SWAP_ORDER
    if (bus == 0) begin
      c0 = cfg_slot4_c[0]; c1 = cfg_slot4_c[1]; c2 = cfg_slot4_c[2];
      c3 = cfg_slot4_c[3]; c4 = cfg_slot4_c[4];
    end else begin
      c0 = cfg_slot3_c[0]; c1 = cfg_slot3_c[1]; c2 = cfg_slot3_c[2];
      c3 = cfg_slot3_c[3]; c4 = cfg_slot3_c[4];
    end
`endif
`ifdef NC_GAIN_SWAP
    // DEFECT (NC_GAIN_SWAP): the gain PLACEMENT is swapped -- the return gain
    // is applied when forming the bus (here) and the scene-A send gain when
    // returning it (see sum_step). The same three numbers, in the wrong
    // places.
    ga = (bus == 0) ? cfg_bus3_g[2] : cfg_bus4_g[2];
`endif

    accl = 144'(sa_l[kk]) * ga;
    accr = 144'(sa_r[kk]) * ga;
    if (cfg_scene_b_active) begin
      accl = accl + 144'(sb_l[kk]) * gb;
      accr = accr + 144'(sb_r[kk]) * gb;
    end
    xl = rndsat32(accl, G_FRAC);
    xr = rndsat32(accr, G_FRAC);

    if (!live) begin
      if (bus == 0) begin wet3_l[kk] = xl; wet3_r[kk] = xr; end
      else          begin wet4_l[kk] = xl; wet4_r[kk] = xr; end
    end else begin
`ifdef NC_SHARED_STATE
      // DEFECT (NC_SHARED_STATE): BOTH buses read and write ONE pooled
      // register set (s3_reg*), i.e. shared instead of per-instance state --
      // the tb_fx_shared_line.sv defect. s4_reg* is left permanently zero, so
      // the dual-instance checkpoint cannot match either.
      op0  = (144'(xl) * c0) + s3_reg0[0];
      nr00 = (144'(xl) * c1) + s3_reg1[0] - rndshift(144'(c3) * op0, C_FRAC);
      nr10 = (144'(xl) * c2) - rndshift(144'(c4) * op0, C_FRAC);
      if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
        $fatal(1, "mutant biquad reg overflow (L) bus=%0d k=%0d", bus, kk);
      s3_reg0[0] = sat80(nr00); s3_reg1[0] = sat80(nr10);
      op1  = (144'(xr) * c0) + s3_reg0[1];
      nr01 = (144'(xr) * c1) + s3_reg1[1] - rndshift(144'(c3) * op1, C_FRAC);
      nr11 = (144'(xr) * c2) - rndshift(144'(c4) * op1, C_FRAC);
      if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
        $fatal(1, "mutant biquad reg overflow (R) bus=%0d k=%0d", bus, kk);
      s3_reg0[1] = sat80(nr01); s3_reg1[1] = sat80(nr11);
`elsif NC_SWAP_ORDER
      // permuted occupants: bus 3 uses slot4's registers, bus 4 slot3's
      op0  = (144'(xl) * c0) + (swapped ? s4_reg0[0] : s3_reg0[0]);
      nr00 = (144'(xl) * c1) + (swapped ? s4_reg1[0] : s3_reg1[0])
             - rndshift(144'(c3) * op0, C_FRAC);
      nr10 = (144'(xl) * c2) - rndshift(144'(c4) * op0, C_FRAC);
      if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
        $fatal(1, "mutant biquad reg overflow (L) bus=%0d k=%0d", bus, kk);
      if (swapped) begin s4_reg0[0] = sat80(nr00); s4_reg1[0] = sat80(nr10); end
      else         begin s3_reg0[0] = sat80(nr00); s3_reg1[0] = sat80(nr10); end
      op1  = (144'(xr) * c0) + (swapped ? s4_reg0[1] : s3_reg0[1]);
      nr01 = (144'(xr) * c1) + (swapped ? s4_reg1[1] : s3_reg1[1])
             - rndshift(144'(c3) * op1, C_FRAC);
      nr11 = (144'(xr) * c2) - rndshift(144'(c4) * op1, C_FRAC);
      if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
        $fatal(1, "mutant biquad reg overflow (R) bus=%0d k=%0d", bus, kk);
      if (swapped) begin s4_reg0[1] = sat80(nr01); s4_reg1[1] = sat80(nr11); end
      else         begin s3_reg0[1] = sat80(nr01); s3_reg1[1] = sat80(nr11); end
`else
      op0  = (144'(xl) * c0) + (bus == 0 ? s3_reg0[0] : s4_reg0[0]);
      nr00 = (144'(xl) * c1) + (bus == 0 ? s3_reg1[0] : s4_reg1[0])
             - rndshift(144'(c3) * op0, C_FRAC);
      nr10 = (144'(xl) * c2) - rndshift(144'(c4) * op0, C_FRAC);
      if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
        $fatal(1, "mutant biquad reg overflow (L) bus=%0d k=%0d", bus, kk);
      if (bus == 0) begin s3_reg0[0] = sat80(nr00); s3_reg1[0] = sat80(nr10); end
      else          begin s4_reg0[0] = sat80(nr00); s4_reg1[0] = sat80(nr10); end
      op1  = (144'(xr) * c0) + (bus == 0 ? s3_reg0[1] : s4_reg0[1]);
      nr01 = (144'(xr) * c1) + (bus == 0 ? s3_reg1[1] : s4_reg1[1])
             - rndshift(144'(c3) * op1, C_FRAC);
      nr11 = (144'(xr) * c2) - rndshift(144'(c4) * op1, C_FRAC);
      if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
        $fatal(1, "mutant biquad reg overflow (R) bus=%0d k=%0d", bus, kk);
      if (bus == 0) begin s3_reg0[1] = sat80(nr01); s3_reg1[1] = sat80(nr11); end
      else          begin s4_reg0[1] = sat80(nr01); s4_reg1[1] = sat80(nr11); end
`endif

      if (bus == 0) begin
        wet3_l[kk] = rndsat32(op0, C_FRAC);
        wet3_r[kk] = rndsat32(op1, C_FRAC);
      end else begin
        wet4_l[kk] = rndsat32(op0, C_FRAC);
        wet4_r[kk] = rndsat32(op1, C_FRAC);
      end
    end
  endtask

  task automatic sum_step(input logic [5:0] kk);
    logic signed [143:0] wl, wr;
    logic signed [31:0]  rg3, rg4;
`ifdef NC_GAIN_SWAP
    rg3 = cfg_bus3_g[0];   // DEFECT: send gain used as the return gain
    rg4 = cfg_bus4_g[0];
`else
    rg3 = cfg_bus3_g[2];
    rg4 = cfg_bus4_g[2];
`endif
    wl = 144'(main_l[kk]) <<< G_FRAC;
    wr = 144'(main_r[kk]) <<< G_FRAC;
    if (run_b3) begin
      wl = wl + 144'(wet3_l[kk]) * rg3;
      wr = wr + 144'(wet3_r[kk]) * rg3;
    end
    if (run_b4) begin
      wl = wl + 144'(wet4_l[kk]) * rg4;
      wr = wr + 144'(wet4_r[kk]) * rg4;
    end
    out_l[kk] = rndsat32(wl, G_FRAC);
    out_r[kk] = rndsat32(wr, G_FRAC);
  endtask

  task automatic clear_slot3;
    integer ri;
    begin
      for (ri = 0; ri < 2; ri++) begin
        s3_reg0[ri] <= 80'sd0;
        s3_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  task automatic clear_slot4;
    integer ri;
    begin
      for (ri = 0; ri < 2; ri++) begin
        s4_reg0[ri] <= 80'sd0;
        s4_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  task automatic panic_clear;
    integer ri;
    begin
      st      <= S_IDLE;
      running <= 1'b0;
      k       <= 6'd0;
      run_b3  <= 1'b0;
      run_b4  <= 1'b0;
      ring3   <= 1'b0;
      ring4   <= 1'b0;
      block_done <= 1'b0;
      for (ri = 0; ri < 2; ri++) begin
        s3_reg0[ri] <= 80'sd0;
        s3_reg1[ri] <= 80'sd0;
        s4_reg0[ri] <= 80'sd0;
        s4_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  initial panic_clear();

  // A mutant compiled with NO defect selected would behave exactly like the
  // real core and report a spurious CONTROL-OK. Refuse to simulate instead.
`ifndef NC_SHARED_STATE
`ifndef NC_SWAP_ORDER
`ifndef NC_TAIL_KILL
`ifndef NC_GAIN_SWAP
  initial $fatal(1, "rf_send34_mutants.sv compiled with no defect selected: use -DNC_SHARED_STATE, -DNC_SWAP_ORDER, -DNC_TAIL_KILL or -DNC_GAIN_SWAP");
`endif
`endif
`endif
`endif

endmodule
