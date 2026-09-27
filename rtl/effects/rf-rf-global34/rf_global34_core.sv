// SXT-028j routing-form core: Global FX slots 3-4 (global3 -> global4, the
// EXTENDED RACK HALF of the master global-FX chain), reproducing the SAME
// integer schedule as the frozen fixed-point model
// (model/effects/rf-rf-global34/rf_global34_model.py) exactly on every
// output sample and every per-instance checkpoint.
//
// Claim scope: this RTL is simulated with iverilog and must match the frozen
// model EXACTLY (integer equality of every output word and every
// per-instance biquad register; enforced by
// tools/compare_rtl_model_rf_global34.py). It is NOT synthesis-closed, NOT
// timing-closed, and makes no gf180mcu FPGA/ASIC claim of any kind. It also
// makes NO claim about any specific Surge FX algorithm's fidelity --
// "algorithm behavior stays with the per-algorithm leaves" (issue #62 scope
// note); the per-slot occupant modeled here is the synthetic TDF2 biquad
// documented in the frozen model's docstring.
//
// Structure citation (cited, not copied): src/common/SurgeSynthesizer.cpp
// process() "apply global effects" block (the master bus processed in place
// through {global1, global2, global3, global4} in slot order, the ring flag
// threaded through each slot's process_ringout return value, fx_bypass /
// fx_disable gating, loadFx()/enqueueFXOff() instance lifecycle);
// src/common/SurgeStorage.h fxslot_positions (global3 = 14, global4 = 15) /
// fxb_* enum. The upstream global1 -> global2 segment is the landed sibling
// leaf rtl/effects/rf-rf-global2/ and is NOT re-implemented here: its bus
// output and ring flag arrive as this core's in_l/in_r/glob_in.
//
// Per-instance state: TWO independent register sets (s3_reg0/s3_reg1,
// s4_reg0/s4_reg1) for slot3 (global3) and slot4 (global4) -- never pooled,
// even though both run through the SAME biquad_step task (shared arithmetic,
// independent state; AGENTS.md; issue #62 "Per-instance state"). This holds
// even when both slots host the same FX class, which the corpus really does
// exercise (John Valentine/Strings/String Contrabass.fxp: Airwindows in BOTH
// global3 and global4).
//
// Control-plane boundary: cfg_fx_bypass, cfg_fx_disable,
// cfg_slot{3,4}_occupied, cfg_slot{3,4}_reload, cfg_slot{3,4}_c[5] (Q3.29
// biquad coefficients) are configuration-bus pokes (the reverb1_core.sv
// `cfg_*` preload convention, applied per block because the lifecycle and
// gating controls are exercised as per-block stimulus); the per-block
// glob_in bit and in_l/in_r[32] (Q10.21) are block I/O. `state_reset` is the
// panic/all-notes-off path (both instances cleared, ring memory dropped).
//
// Original to this repository (Apache-2.0). No Surge source, tables, or
// assets are copied.
`timescale 1ns/1ps

module rf_global34_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done
);

  localparam int BLOCK  = 32;
  localparam int C_FRAC = 29;                    // Q3.29 coefficients
  // NOTE: 2^79 does not fit in an 80-bit signed container (max positive value
  // there is 2^79-1); REG_LIM is only ever used as a wide (144-bit)
  // comparison bound against products, never stored in an 80-bit reg, so it
  // is declared wide here to avoid a shift-overflow wraparound to -2^79.
  localparam logic signed [143:0] REG_LIM = 144'sd1 <<< 79;

  localparam logic [1:0] FXB_ALL_FX = 2'd0, FXB_NO_SENDS = 2'd1;
  // FXB_SCENE_FX_ONLY = 2'd2 and FXB_NO_FX = 2'd3 both SKIP the global stage
  // -- see the frozen model's "BYPASS-MODE PARTITION" note.
  localparam int FXSLOT_GLOBAL3 = 14, FXSLOT_GLOBAL4 = 15;

  // ------------------------------------------------- control-plane config
  logic [1:0]  cfg_fx_bypass;
  logic [15:0] cfg_fx_disable;
  logic        cfg_slot3_occupied, cfg_slot4_occupied;
  logic        cfg_slot3_reload,   cfg_slot4_reload;
  logic signed [31:0] cfg_slot3_c [5];  // b0 b1 b2 a1 a2 (Q3.29)
  logic signed [31:0] cfg_slot4_c [5];

  // --------------------------------------------------------- on-chip state
  logic signed [79:0] s3_reg0 [2];   // L, R (accumulator scale 21+29)
  logic signed [79:0] s3_reg1 [2];
  logic signed [79:0] s4_reg0 [2];
  logic signed [79:0] s4_reg1 [2];
  // occupancy history: `loadFx()` on a rising occupancy or on an explicit
  // reload pulse installs a FRESH instance (that slot's registers cleared).
  // Deliberately NOT cleared by state_reset: the panic path clears histories
  // and the ring flag, it does not unload the patch (mirrors the frozen
  // model's `panic_reset()`, which leaves `occupied` alone).
  logic prev_occ3 = 1'b0;
  logic prev_occ4 = 1'b0;

  // --------------------------------------------------------- block I/O
  logic signed [31:0] in_l  [BLOCK];
  logic signed [31:0] in_r  [BLOCK];
  logic signed [31:0] out_l [BLOCK];    // reused in place as the running bus
  logic signed [31:0] out_r [BLOCK];
  logic                glob_in;   // ring flag as the global1->global2 segment left it
  logic                glob_out;  // ... as threaded out of global4

  // ------------------------------------------------------------ FSM state
  localparam logic [2:0] S_IDLE=0, S_CTRL=1, S_GATE=2, S_S3=3, S_S4=4, S_DONE=5;
  logic [2:0] st = S_IDLE;
  logic       running = 1'b0;
  logic [5:0] k = 6'd0;
  logic       run_s3, run_s4;
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
  // (out_l/out_r) -- never for the TDF2 feedback term itself, which must stay
  // at full accumulator width (see rndshift below; the same distinction the
  // sibling routing leaf rf_global2_core.sv documents, where conflating the
  // two silently truncated the accumulator).
  function automatic logic signed [31:0] rndsat32(input logic signed [143:0] x,
                                                   input int f);
    logic signed [143:0] r;
    r = (x + (144'sd1 <<< (f-1))) >>> f;
    rndsat32 = sat32(r);
  endfunction

  // (x + 2^(f-1)) >>> f, FULL WIDTH, no saturation -- round-half-up at
  // accumulator scale (the TDF2 feedback term a1*op / a2*op reduction).
  // Mirrors model/effects/rf-rf-global34/rf_global34_model.py's rnd_shift()
  // exactly; REG_LIM overflow is checked separately by the caller.
  function automatic logic signed [143:0] rndshift(input logic signed [143:0] x,
                                                     input int f);
    rndshift = (x + (144'sd1 <<< (f-1))) >>> f;
  endfunction

  // ------------------------------------------------------------- datapath
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

        // control-rate lifecycle pass (runs regardless of fx_bypass, as the
        // engine's loadFx()/enqueueFXOff() path does):
        //   !occupied                       -> instance released, regs clear
        //   occupied rising, or reload pulse-> FRESH instance, regs clear
        //   occupied steady, no reload      -> coefficients adopted, regs kept
        // Only the affected slot is ever cleared; the sibling slot's history
        // and the ring flag are untouched.
        S_CTRL: begin
          if (!cfg_slot3_occupied || !prev_occ3 || cfg_slot3_reload)
            clear_slot3();
          if (!cfg_slot4_occupied || !prev_occ4 || cfg_slot4_reload)
            clear_slot4();
          prev_occ3 <= cfg_slot3_occupied;
          prev_occ4 <= cfg_slot4_occupied;
          st <= S_GATE;
        end

        // gate: the GLOBAL stage runs ONLY in ALL_FX and NO_SENDS
        // (SCENE_FX_ONLY and NO_FX skip it). When it is skipped the bus
        // passes through and the ring flag passes through untouched
        // (matches process(): the global block is simply not entered).
        S_GATE: begin
          for (int i = 0; i < BLOCK; i++) begin
            out_l[i] <= in_l[i];
            out_r[i] <= in_r[i];
          end
          if (cfg_fx_bypass != FXB_ALL_FX && cfg_fx_bypass != FXB_NO_SENDS) begin
            glob_out <= glob_in;
            st       <= S_DONE;
          end else begin
            run_s3   <= cfg_slot3_occupied && !cfg_fx_disable[FXSLOT_GLOBAL3];
            run_s4   <= cfg_slot4_occupied && !cfg_fx_disable[FXSLOT_GLOBAL4];
            glob_cur <= glob_in;
            k        <= 6'd0;
            st       <= S_S3;
          end
        end

        // slot3 (global3) in place on out_l/out_r. Per the frozen model's
        // process_ringout: while run_s3 (occupied and not disabled) and
        // glob_cur (indata) is true, process every sample and keep reporting
        // ringing==true (this occupant declares no ring-out policy of its
        // own, so its own ring decision reduces to indata exactly); if
        // glob_cur is false the stage no-ops (pass-through, ring stays
        // false); if run_s3 is false the stage no-ops and glob_cur is NOT
        // touched (carries forward unchanged into slot4, matching
        // process()'s "glob = ..." assignment only firing when the slot
        // actually runs).
        S_S3: begin
          if (run_s3 && glob_cur) biquad_step(0, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_S4;
          end else k <= k + 1'b1;
        end

        // slot4 (global4) in place on out_l/out_r, chained after slot3 (same
        // rule as S_S3, applied to whatever glob_cur slot3 left).
        S_S4: begin
          if (run_s4 && glob_cur) biquad_step(1, k);
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
  // selected by `slot` (0 = slot3/global3, 1 = slot4/global4); updates
  // out_l[kk]/out_r[kk] in place. `slot` selects module-level per-instance
  // state directly (iverilog does not support unpacked-array subroutine
  // ports); it is never used to pool the two instances' registers -- each
  // branch reads and writes only its own s{3,4}_reg{0,1} pair.
  task automatic biquad_step(input int slot, input logic [5:0] kk);
    logic signed [143:0] op0, nr00, nr10, op1, nr01, nr11;
    logic signed [31:0]  c0, c1, c2, c3, c4;
    if (slot == 0) begin
      c0 = cfg_slot3_c[0]; c1 = cfg_slot3_c[1]; c2 = cfg_slot3_c[2];
      c3 = cfg_slot3_c[3]; c4 = cfg_slot3_c[4];
    end else begin
      c0 = cfg_slot4_c[0]; c1 = cfg_slot4_c[1]; c2 = cfg_slot4_c[2];
      c3 = cfg_slot4_c[3]; c4 = cfg_slot4_c[4];
    end
    // channel 0 = L
    op0  = (144'(out_l[kk]) * c0)
           + (slot == 0 ? s3_reg0[0] : s4_reg0[0]);
    nr00 = (144'(out_l[kk]) * c1) + (slot == 0 ? s3_reg1[0] : s4_reg1[0])
           - rndshift(144'(c3) * op0, C_FRAC);
    nr10 = (144'(out_l[kk]) * c2) - rndshift(144'(c4) * op0, C_FRAC);
    if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
      $fatal(1, "slot biquad reg overflow (L) slot=%0d k=%0d", slot, kk);
    if (slot == 0) begin s3_reg0[0] = sat80(nr00); s3_reg1[0] = sat80(nr10); end
    else           begin s4_reg0[0] = sat80(nr00); s4_reg1[0] = sat80(nr10); end
    out_l[kk] = rndsat32(op0, C_FRAC);
    // channel 1 = R
    op1  = (144'(out_r[kk]) * c0)
           + (slot == 0 ? s3_reg0[1] : s4_reg0[1]);
    nr01 = (144'(out_r[kk]) * c1) + (slot == 0 ? s3_reg1[1] : s4_reg1[1])
           - rndshift(144'(c3) * op1, C_FRAC);
    nr11 = (144'(out_r[kk]) * c2) - rndshift(144'(c4) * op1, C_FRAC);
    if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
      $fatal(1, "slot biquad reg overflow (R) slot=%0d k=%0d", slot, kk);
    if (slot == 0) begin s3_reg0[1] = sat80(nr01); s3_reg1[1] = sat80(nr11); end
    else           begin s4_reg0[1] = sat80(nr01); s4_reg1[1] = sat80(nr11); end
    out_r[kk] = rndsat32(op1, C_FRAC);
  endtask

  // per-slot instance clear (loadFx() / enqueueFXOff()): ONLY this slot.
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

  // panic / all-notes-off (and power-on): BOTH instances' histories and the
  // ring flag are dropped. Occupancy history (prev_occ*) is deliberately
  // left alone -- a panic does not unload the patch.
  task automatic panic_clear;
    integer ri;
    begin
      st      <= S_IDLE;
      running <= 1'b0;
      k       <= 6'd0;
      run_s3  <= 1'b0;
      run_s4  <= 1'b0;
      glob_cur   <= 1'b0;
      glob_out   <= 1'b0;
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

endmodule
