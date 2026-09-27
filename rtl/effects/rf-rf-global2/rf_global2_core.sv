// SXT-028d routing-form core: Global FX slots 1+2 series bus (the second
// concurrent global-FX instance), reproducing the SAME integer schedule as
// the frozen fixed-point model (model/effects/rf-rf-global2/
// rf_global2_model.py) exactly on every output sample and every per-
// instance checkpoint.
//
// Claim scope: this RTL is simulated with iverilog and must match the
// frozen model EXACTLY (integer equality of every output word and every
// per-instance biquad register; enforced by
// tools/compare_rtl_model_rf_global2.py). It is NOT synthesis-closed, NOT
// timing-closed, and makes no gf180mcu FPGA/ASIC claim of any kind. It also
// makes NO claim about any specific Surge FX algorithm's fidelity --
// "algorithm behavior stays with the per-algorithm leaves" (issue #56 scope
// note); the per-slot occupant modeled here is the synthetic TDF2 biquad
// documented in the frozen model's docstring.
//
// Structure citation (read, not copied): src/common/SurgeSynthesizer.cpp
// process() "apply global effects" block (fxslot_global1/global2 series
// chaining, fx_bypass/fx_disable gating, process_ringout threading);
// src/common/SurgeStorage.h fxslot_positions / fxb_* enum.
//
// Per-instance state: TWO independent register sets (s1_reg0/s1_reg1,
// s2_reg0/s2_reg1) for slot1 (global1) and slot2 (global2) -- never pooled,
// even though both run through the SAME biquad_step task (shared
// arithmetic, independent state; AGENTS.md; issue #56 "Per-instance state").
//
// Control-plane boundary: cfg_fx_bypass, cfg_fx_disable, cfg_slot{1,2}_c[5]
// (Q3.29 biquad coefficients), cfg_slot{1,2}_occupied are configuration-bus
// pokes (equivalent to the reverb1_core.sv `cfg_*` preload convention); the
// per-block glob_in bit and in_l/in_r[32] (Q10.21) are block I/O.
//
// Original to this repository (Apache-2.0). No Surge source, tables, or
// assets are copied.
`timescale 1ns/1ps

module rf_global2_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done
);

  localparam int BLOCK  = 32;
  localparam int C_FRAC = 29;                    // Q3.29 coefficients
  // NOTE: 2^79 does not fit in an 80-bit signed container (max positive
  // value there is 2^79-1); REG_LIM is only ever used as a wide (144-bit)
  // comparison bound against products, never stored in an 80-bit reg, so it
  // is declared wide here to avoid a shift-overflow wraparound to -2^79.
  localparam logic signed [143:0] REG_LIM = 144'sd1 <<< 79;

  localparam logic [1:0] FXB_ALL_FX = 2'd0, FXB_NO_SENDS = 2'd1;
  // FXB_SCENE_FX_ONLY = 2'd2, FXB_NO_FX = 2'd3 (both skip this block)
  localparam int FXSLOT_GLOBAL1 = 6, FXSLOT_GLOBAL2 = 7;

  // ------------------------------------------------- control-plane config
  logic [1:0]  cfg_fx_bypass;
  logic [15:0] cfg_fx_disable;
  logic        cfg_slot1_occupied, cfg_slot2_occupied;
  logic signed [31:0] cfg_slot1_c [5];  // b0 b1 b2 a1 a2 (Q3.29)
  logic signed [31:0] cfg_slot2_c [5];

  // --------------------------------------------------------- on-chip state
  logic signed [79:0] s1_reg0 [2];   // L, R (accumulator scale 21+29)
  logic signed [79:0] s1_reg1 [2];
  logic signed [79:0] s2_reg0 [2];
  logic signed [79:0] s2_reg1 [2];

  // --------------------------------------------------------- block I/O
  logic signed [31:0] in_l  [BLOCK];
  logic signed [31:0] in_r  [BLOCK];
  logic signed [31:0] out_l [BLOCK];    // reused in place as the running bus
  logic signed [31:0] out_r [BLOCK];
  logic                glob_in;
  logic                glob_out;

  // ------------------------------------------------------------ FSM state
  localparam logic [2:0] S_IDLE=0, S_GATE=1, S_S1=2, S_S2=3, S_DONE=4;
  logic [2:0] st = S_IDLE;
  logic       running = 1'b0;
  logic [5:0] k = 6'd0;
  logic       run_s1, run_s2;
  logic       glob_cur;

  // ------------------------------------------------------------ functions
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

  // (x + 2^(f-1)) >>> f then saturate to s32 -- round-half-up. ONLY for
  // reducing an accumulator-scale value down to the final s32 AUDIO output
  // (out_l/out_r) -- never for the TDF2 feedback term itself, which must
  // stay at full accumulator width (see rndshift below; Reverb1 precedent:
  // reverb1_core.sv's own bregs recurrence uses the equivalent wide,
  // non-saturating shift inline, reserving its rndsat32 for wet_l/wet_r/
  // mix-stage outputs only).
  function automatic logic signed [31:0] rndsat32(input logic signed [143:0] x,
                                                   input int f);
    logic signed [143:0] r;
    r = (x + (144'sd1 <<< (f-1))) >>> f;
    rndsat32 = sat32(r);
  endfunction

  // (x + 2^(f-1)) >>> f, FULL WIDTH, no saturation -- round-half-up at
  // accumulator scale (the TDF2 feedback term a1*op / a2*op reduction).
  // Mirrors model/effects/rf-rf-global2/rf_global2_model.py's rnd_shift()
  // exactly; REG_LIM overflow is checked separately by the caller.
  function automatic logic signed [143:0] rndshift(input logic signed [143:0] x,
                                                     input int f);
    rndshift = (x + (144'sd1 <<< (f-1))) >>> f;
  endfunction

  // ------------------------------------------------------------- datapath
  always @(posedge clk) begin
    if (state_reset) begin
      clear_state();
    end else begin
      block_done <= 1'b0;
      case (st)
        S_IDLE: begin
          if (start_block) begin
            running <= 1'b1;
            st      <= S_GATE;
          end
        end

        // gate: outside {ALL_FX, NO_SENDS} the whole block is skipped
        // (matches process(): the `glob` local is never computed).
        S_GATE: begin
          if (cfg_fx_bypass != FXB_ALL_FX && cfg_fx_bypass != FXB_NO_SENDS) begin
            for (int i = 0; i < BLOCK; i++) begin
              out_l[i] <= in_l[i];
              out_r[i] <= in_r[i];
            end
            glob_out <= glob_in;
            st <= S_DONE;
          end else begin
            for (int i = 0; i < BLOCK; i++) begin
              out_l[i] <= in_l[i];
              out_r[i] <= in_r[i];
            end
            run_s1   <= cfg_slot1_occupied && !cfg_fx_disable[FXSLOT_GLOBAL1];
            run_s2   <= cfg_slot2_occupied && !cfg_fx_disable[FXSLOT_GLOBAL2];
            glob_cur <= glob_in;
            k        <= 6'd0;
            st       <= S_S1;
          end
        end

        // slot1 (global1) in place on out_l/out_r. Per the frozen model's
        // process_ringout: while run_s1 (occupied and not disabled) and
        // glob_cur (indata) is true, process every sample and keep
        // reporting ringing==true (this occupant declares no extended
        // tail, so its own ring decision reduces to indata exactly); if
        // glob_cur is false the stage no-ops (pass-through, ring stays
        // false); if run_s1 is false the stage no-ops and glob_cur is
        // NOT touched (carries forward unchanged into slot2, matching
        // process()'s "glob = ..." assignment only firing when the slot
        // actually runs).
        S_S1: begin
          if (run_s1 && glob_cur) biquad_step(0, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_S2;
          end else k <= k + 1'b1;
        end

        // slot2 (global2) in place on out_l/out_r, chained after slot1
        // (same rule as S_S1, applied to whatever glob_cur slot1 left).
        S_S2: begin
          if (run_s2 && glob_cur) biquad_step(1, k);
          if (k == BLOCK-1) begin
            glob_out <= glob_cur;
            st       <= S_DONE;
          end else k <= k + 1'b1;
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

  // one TDF2 sample for channel-pair (L,R) at index kk, on the instance
  // selected by `slot` (0 = slot1/global1, 1 = slot2/global2); updates
  // out_l[kk]/out_r[kk] in place. `slot` selects module-level per-instance
  // state directly (iverilog does not support unpacked-array subroutine
  // ports); it is never used to pool the two instances' registers -- each
  // branch reads and writes only its own s{1,2}_reg{0,1} pair.
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
    // channel 0 = L
    op0  = (144'(out_l[kk]) * c0)
           + (slot == 0 ? s1_reg0[0] : s2_reg0[0]);
    nr00 = (144'(out_l[kk]) * c1) + (slot == 0 ? s1_reg1[0] : s2_reg1[0])
           - rndshift(144'(c3) * op0, C_FRAC);
    nr10 = (144'(out_l[kk]) * c2) - rndshift(144'(c4) * op0, C_FRAC);
    if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
      $fatal(1, "slot biquad reg overflow (L) slot=%0d k=%0d", slot, kk);
    if (slot == 0) begin s1_reg0[0] = sat80(nr00); s1_reg1[0] = sat80(nr10); end
    else           begin s2_reg0[0] = sat80(nr00); s2_reg1[0] = sat80(nr10); end
    out_l[kk] = rndsat32(op0, C_FRAC);
    // channel 1 = R
    op1  = (144'(out_r[kk]) * c0)
           + (slot == 0 ? s1_reg0[1] : s2_reg0[1]);
    nr01 = (144'(out_r[kk]) * c1) + (slot == 0 ? s1_reg1[1] : s2_reg1[1])
           - rndshift(144'(c3) * op1, C_FRAC);
    nr11 = (144'(out_r[kk]) * c2) - rndshift(144'(c4) * op1, C_FRAC);
    if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
      $fatal(1, "slot biquad reg overflow (R) slot=%0d k=%0d", slot, kk);
    if (slot == 0) begin s1_reg0[1] = sat80(nr01); s1_reg1[1] = sat80(nr11); end
    else           begin s2_reg0[1] = sat80(nr01); s2_reg1[1] = sat80(nr11); end
    out_r[kk] = rndsat32(op1, C_FRAC);
  endtask

  task automatic clear_state;
    integer ri;
    begin
      st      <= S_IDLE;
      running <= 1'b0;
      k       <= 6'd0;
      run_s1  <= 1'b0;
      run_s2  <= 1'b0;
      glob_cur   <= 1'b0;
      glob_out   <= 1'b0;
      block_done <= 1'b0;
      for (ri = 0; ri < 2; ri++) begin
        s1_reg0[ri] <= 80'sd0;
        s1_reg1[ri] <= 80'sd0;
        s2_reg0[ri] <= 80'sd0;
        s2_reg1[ri] <= 80'sd0;
      end
    end
  endtask

  initial clear_state();

endmodule
