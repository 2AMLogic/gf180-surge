// SXT-028l routing-form core: Send buses 3-4 (send3 / send4, the EXTENDED
// RACK HALF of the engine's four send buses), reproducing the SAME integer
// schedule as the frozen fixed-point model
// (model/effects/rf-rf-send34/rf_send34_model.py) exactly on every output
// sample and every per-instance checkpoint.
//
// Claim scope: this RTL is simulated with iverilog and must match the frozen
// model EXACTLY (integer equality of every main-bus output word, every
// per-bus wet word and every per-instance biquad register; enforced by
// tools/compare_rtl_model_rf_send34.py). It is NOT synthesis-closed, NOT
// timing-closed, and makes no gf180mcu FPGA/ASIC claim of any kind. It also
// makes NO claim about any specific Surge FX algorithm's fidelity --
// "algorithm behavior stays with the per-algorithm leaves" (issue #64 scope
// note); the per-slot occupant modeled here is the synthetic TDF2 biquad
// documented in the frozen model's docstring.
//
// PARALLEL, NOT SERIES. Unlike the four landed routing cores (rf_global2,
// rf_bins12, rf_ains34, rf_global34), which thread ONE bus through two slots
// in series, this core FORMS two independent buses from the two scene buses
// (per-scene send gains), processes each with its own instance, and MIXES
// both back into the main bus (per-slot return gains). A bus that does not
// run contributes NOTHING to the main bus -- it is not a pass-through.
//
// Structure citation (cited, not copied): src/common/SurgeSynthesizer.cpp
// process() send-FX block (fxsendout[s] accumulated from the scene buses
// through per-scene send_level, processed in place through the send slot's
// process_ringout(L, R, sendused[s]), mixed into the main output through the
// slot's return_level, under fx_bypass / fx_disable gating;
// loadFx()/enqueueFXOff()/reorderFx() instance lifecycle);
// src/common/SurgeStorage.h fxslot_positions (send3 = 12, send4 = 13),
// n_send_slots = 4, fxb_* enum. The send stage runs in fxb_all_fx ONLY
// (corpus/normalized/README.md, the committed SXT-011 mapping note written
// against the pin -- see reports/SXT-028l/EVIDENCE.md section 0b).
//
// Per-instance state: TWO independent register sets (s3_reg0/s3_reg1,
// s4_reg0/s4_reg1) for send3 and send4 -- never pooled, even though both run
// through the SAME biquad_step task (shared arithmetic, independent state;
// AGENTS.md; issue #64 "Per-instance state"). This holds even when both
// buses host the same FX class, which the corpus really does exercise
// (Exquis MPE/Strings/Strynth.fxp: Nimbus in BOTH send3 and send4).
//
// Control-plane boundary: cfg_fx_bypass, cfg_fx_disable, cfg_scene_b_active,
// cfg_slot{3,4}_occupied, cfg_slot{3,4}_reload, cfg_slot{3,4}_c[5] (Q3.29
// biquad coefficients) and cfg_bus{3,4}_g[3] (Q1.30 send-A / send-B / return
// gains) are configuration-bus pokes (the reverb1_core.sv `cfg_*` preload
// convention, applied per block because the lifecycle, gating and level
// controls are exercised as per-block stimulus); the per-block send_in{3,4}
// bits and sa_*/sb_*/main_*[32] (Q10.21) are block I/O. `state_reset` is the
// panic/all-notes-off path (both instances cleared, ring memory dropped).
//
// Original to this repository (Apache-2.0). No Surge source, tables, or
// assets are copied.
`timescale 1ns/1ps

module rf_send34_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done
);

  localparam int BLOCK  = 32;
  localparam int C_FRAC = 29;                    // Q3.29 coefficients
  localparam int G_FRAC = 30;                    // Q1.30 send/return gains
  // NOTE: 2^79 does not fit in an 80-bit signed container (max positive value
  // there is 2^79-1); REG_LIM is only ever used as a wide (144-bit)
  // comparison bound against products, never stored in an 80-bit reg, so it
  // is declared wide here to avoid a shift-overflow wraparound to -2^79.
  localparam logic signed [143:0] REG_LIM = 144'sd1 <<< 79;

  localparam logic [1:0] FXB_ALL_FX = 2'd0;
  // FXB_NO_SENDS (1), FXB_SCENE_FX_ONLY (2) and FXB_NO_FX (3) ALL skip the
  // send stage -- the strictest of the engine's three routing-stage
  // partitions. See the frozen model's SEND_ACTIVE_MODES note.
  localparam int FXSLOT_SEND3 = 12, FXSLOT_SEND4 = 13;

  // ------------------------------------------------- control-plane config
  logic [1:0]  cfg_fx_bypass;
  logic [15:0] cfg_fx_disable;
  logic        cfg_scene_b_active;
  logic        cfg_slot3_occupied, cfg_slot4_occupied;
  logic        cfg_slot3_reload,   cfg_slot4_reload;
  logic signed [31:0] cfg_slot3_c [5];  // b0 b1 b2 a1 a2 (Q3.29)
  logic signed [31:0] cfg_slot4_c [5];
  logic signed [31:0] cfg_bus3_g  [3];  // send_gain_a, send_gain_b, return (Q1.30)
  logic signed [31:0] cfg_bus4_g  [3];

  // --------------------------------------------------------- on-chip state
  logic signed [79:0] s3_reg0 [2];   // L, R (accumulator scale 21+29)
  logic signed [79:0] s3_reg1 [2];
  logic signed [79:0] s4_reg0 [2];
  logic signed [79:0] s4_reg1 [2];
  // occupancy history: `loadFx()` on a rising occupancy or on an explicit
  // reload pulse installs a FRESH instance (that slot's registers cleared).
  // Deliberately NOT cleared by state_reset: the panic path clears histories
  // and the ring flags, it does not unload the patch (mirrors the frozen
  // model's `panic_reset()`, which leaves `occupied` and the gain plane
  // alone).
  logic prev_occ3 = 1'b0;
  logic prev_occ4 = 1'b0;

  // --------------------------------------------------------- block I/O
  logic signed [31:0] sa_l   [BLOCK];   // scene A post-insert bus
  logic signed [31:0] sa_r   [BLOCK];
  logic signed [31:0] sb_l   [BLOCK];   // scene B post-insert bus
  logic signed [31:0] sb_r   [BLOCK];
  logic signed [31:0] main_l [BLOCK];   // main bus in (scene sum + send1/2)
  logic signed [31:0] main_r [BLOCK];
  logic signed [31:0] out_l  [BLOCK];   // main bus out
  logic signed [31:0] out_r  [BLOCK];
  logic signed [31:0] wet3_l [BLOCK];   // per-bus wet taps (post-occupant,
  logic signed [31:0] wet3_r [BLOCK];   // PRE return gain) -- internal
  logic signed [31:0] wet4_l [BLOCK];   // observability, matching the
  logic signed [31:0] wet4_r [BLOCK];   // model's fxsendout scratch
  logic               send_in3, send_in4;   // per-bus `sendused[k]`
  logic               ring3, ring4;         // per-bus ringing report

  // ------------------------------------------------------------ FSM state
  localparam logic [2:0] S_IDLE=0, S_CTRL=1, S_GATE=2, S_B3=3, S_B4=4,
                         S_SUM=5, S_DONE=6;
  logic [2:0] st = S_IDLE;
  logic       running = 1'b0;
  logic [5:0] k = 6'd0;
  logic       run_b3, run_b4;

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
  // reducing an accumulator-scale value down to a final s32 AUDIO word (the
  // formed bus sample, the occupant output, the mixed main bus) -- never for
  // the TDF2 feedback term itself, which must stay at full accumulator width
  // (see rndshift below; the same distinction the sibling routing cores
  // document, where conflating the two silently truncated the accumulator).
  function automatic logic signed [31:0] rndsat32(input logic signed [143:0] x,
                                                   input int f);
    logic signed [143:0] r;
    r = (x + (144'sd1 <<< (f-1))) >>> f;
    rndsat32 = sat32(r);
  endfunction

  // (x + 2^(f-1)) >>> f, FULL WIDTH, no saturation -- round-half-up at
  // accumulator scale (the TDF2 feedback term a1*op / a2*op reduction).
  // Mirrors model/effects/rf-rf-send34/rf_send34_model.py's rnd_shift()
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
        // Only the affected slot is ever cleared; the sibling slot's history,
        // the bus gain plane and the other bus's ring flag are untouched.
        S_CTRL: begin
          if (!cfg_slot3_occupied || !prev_occ3 || cfg_slot3_reload)
            clear_slot3();
          if (!cfg_slot4_occupied || !prev_occ4 || cfg_slot4_reload)
            clear_slot4();
          prev_occ3 <= cfg_slot3_occupied;
          prev_occ4 <= cfg_slot4_occupied;
          st <= S_GATE;
        end

        // gate: the SEND stage runs ONLY in ALL_FX. When it is skipped the
        // main bus passes through untouched, no bus is formed, no instance
        // state advances and neither bus reports ringing (matches process():
        // the send block is simply not entered).
        S_GATE: begin
          for (int i = 0; i < BLOCK; i++) begin
            wet3_l[i] <= 32'sd0; wet3_r[i] <= 32'sd0;
            wet4_l[i] <= 32'sd0; wet4_r[i] <= 32'sd0;
          end
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
            // this occupant declares no ring-out policy of its own, so its
            // ring decision reduces to `sendused` exactly (algorithm-leaf
            // scope -- see the frozen model's process_ringout docstring)
            ring3  <= (cfg_slot3_occupied &&
                       !cfg_fx_disable[FXSLOT_SEND3]) && send_in3;
            ring4  <= (cfg_slot4_occupied &&
                       !cfg_fx_disable[FXSLOT_SEND4]) && send_in4;
            k      <= 6'd0;
            st     <= S_B3;
          end
        end

        // bus 3 (send3): form the bus from the two scene buses through this
        // bus's own send gains, then run the occupant in place on it while
        // `send_in3` is true (otherwise the formed bus passes through
        // untouched and no state advances).
        S_B3: begin
          if (run_b3) bus_step(0, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_B4;
          end else k <= k + 1'b1;
        end

        // bus 4 (send4): the SAME arithmetic on an INDEPENDENT instance and
        // an INDEPENDENT gain plane -- the two buses are parallel, so bus 4
        // reads the scene buses, never bus 3's output.
        S_B4: begin
          if (run_b4) bus_step(1, k);
          if (k == BLOCK-1) begin
            k  <= 6'd0;
            st <= S_SUM;
          end else k <= k + 1'b1;
        end

        // return mix: main_out = sat32(rnd((main_in << G) + sum of running
        // buses' wet*return_gain)). ONE rounding and ONE saturation for the
        // whole mix, so the summation order is irrelevant by construction
        // (the frozen model does the same); with both buses off this is an
        // exact pass-through of main_in.
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

  // one send-bus sample pair (L,R) at index kk on the bus selected by `bus`
  // (0 = send3, 1 = send4): form the bus word from the two scene buses, then
  // either run this bus's own TDF2 instance on it or pass it through.
  // `bus` selects module-level per-instance state directly (iverilog does not
  // support unpacked-array subroutine ports); it is never used to pool the
  // two instances' registers -- each branch reads and writes only its own
  // s{3,4}_reg{0,1} pair and its own cfg_bus{3,4}_g gain plane.
  task automatic bus_step(input int bus, input logic [5:0] kk);
    logic signed [143:0] accl, accr, op0, nr00, nr10, op1, nr01, nr11;
    logic signed [31:0]  xl, xr, c0, c1, c2, c3, c4, ga, gb;
    logic                live;
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

    // --- bus formation: one rounding, one saturation for the scene sum ---
    accl = 144'(sa_l[kk]) * ga;
    accr = 144'(sa_r[kk]) * ga;
    if (cfg_scene_b_active) begin
      accl = accl + 144'(sb_l[kk]) * gb;
      accr = accr + 144'(sb_r[kk]) * gb;
    end
    xl = rndsat32(accl, G_FRAC);
    xr = rndsat32(accr, G_FRAC);

    if (!live) begin
      // `sendused` false: the occupant passes the formed bus through and
      // reports not-ringing; no register advances.
      if (bus == 0) begin wet3_l[kk] = xl; wet3_r[kk] = xr; end
      else          begin wet4_l[kk] = xl; wet4_r[kk] = xr; end
    end else begin
      // channel 0 = L
      op0  = (144'(xl) * c0) + (bus == 0 ? s3_reg0[0] : s4_reg0[0]);
      nr00 = (144'(xl) * c1) + (bus == 0 ? s3_reg1[0] : s4_reg1[0])
             - rndshift(144'(c3) * op0, C_FRAC);
      nr10 = (144'(xl) * c2) - rndshift(144'(c4) * op0, C_FRAC);
      if (nr00 >= REG_LIM || nr00 < -REG_LIM || nr10 >= REG_LIM || nr10 < -REG_LIM)
        $fatal(1, "send bus biquad reg overflow (L) bus=%0d k=%0d", bus, kk);
      if (bus == 0) begin s3_reg0[0] = sat80(nr00); s3_reg1[0] = sat80(nr10); end
      else          begin s4_reg0[0] = sat80(nr00); s4_reg1[0] = sat80(nr10); end
      // channel 1 = R
      op1  = (144'(xr) * c0) + (bus == 0 ? s3_reg0[1] : s4_reg0[1]);
      nr01 = (144'(xr) * c1) + (bus == 0 ? s3_reg1[1] : s4_reg1[1])
             - rndshift(144'(c3) * op1, C_FRAC);
      nr11 = (144'(xr) * c2) - rndshift(144'(c4) * op1, C_FRAC);
      if (nr01 >= REG_LIM || nr01 < -REG_LIM || nr11 >= REG_LIM || nr11 < -REG_LIM)
        $fatal(1, "send bus biquad reg overflow (R) bus=%0d k=%0d", bus, kk);
      if (bus == 0) begin s3_reg0[1] = sat80(nr01); s3_reg1[1] = sat80(nr11); end
      else          begin s4_reg0[1] = sat80(nr01); s4_reg1[1] = sat80(nr11); end

      if (bus == 0) begin
        wet3_l[kk] = rndsat32(op0, C_FRAC);
        wet3_r[kk] = rndsat32(op1, C_FRAC);
      end else begin
        wet4_l[kk] = rndsat32(op0, C_FRAC);
        wet4_r[kk] = rndsat32(op1, C_FRAC);
      end
    end
  endtask

  // one return-mix sample pair at index kk.
  task automatic sum_step(input logic [5:0] kk);
    logic signed [143:0] wl, wr;
    wl = 144'(main_l[kk]) <<< G_FRAC;
    wr = 144'(main_r[kk]) <<< G_FRAC;
    if (run_b3) begin
      wl = wl + 144'(wet3_l[kk]) * cfg_bus3_g[2];
      wr = wr + 144'(wet3_r[kk]) * cfg_bus3_g[2];
    end
    if (run_b4) begin
      wl = wl + 144'(wet4_l[kk]) * cfg_bus4_g[2];
      wr = wr + 144'(wet4_r[kk]) * cfg_bus4_g[2];
    end
    out_l[kk] = rndsat32(wl, G_FRAC);
    out_r[kk] = rndsat32(wr, G_FRAC);
  endtask

  // per-slot instance clear (loadFx() / enqueueFXOff()): ONLY this slot.
  // The bus gain plane (cfg_bus*_g) is untouched -- it is routing state, not
  // occupant state.
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

  // panic / all-notes-off (and power-on): BOTH instances' histories and both
  // buses' ring flags are dropped. Occupancy history (prev_occ*) and the gain
  // plane are deliberately left alone -- a panic does not unload the patch.
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

endmodule
