// SXT-028d Global FX slot 2 (routing form) iverilog harness.
//
// Instantiates rf_global2_core, drives it from a per-block control-plane
// stream (rf_global2_core's config bus, poked hierarchically -- the
// reverb1_core.sv `cfg_*` preload convention, applied per block here since
// fx_bypass/fx_disable/occupied/coefficients are all exercised as per-block
// test stimulus by the negative controls, not just patch-level constants),
// and dumps per-block checkpoints + output blocks for EXACT comparison
// against the frozen model (tools/compare_rtl_model_rf_global2.py).
//
// Stimulus (emitted by tools/compare_rtl_model_rf_global2.py):
//   +CTRLFILE=<path>   15 words/block: fx_bypass, fx_disable,
//                      slot1_occupied, slot2_occupied, glob_in,
//                      slot1_c[0..4], slot2_c[0..4] (Q3.29)
//   +INFILE=<path>     64 words/block: 32 x in_l, 32 x in_r (Q10.21)
//   +NBLOCKS=n
//   +TRACE=<path>      output: per block "T <blk> <8 reg words> <glob_out>"
//                      then "O <blk> <32 out_l> <32 out_r>"
//   +RESETAT=<comma-separated block indices>  optional state_reset pulses
//     (issued BEFORE processing the named block; used by the tail /
//     shared-state negative controls)
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module tb_rf_global2;

  localparam int BLOCK = 32;
  localparam int CTRL_WORDS = 15;
  localparam int IN_WORDS   = 2 * BLOCK;

  logic clk = 1'b0;
  logic state_reset = 1'b0;
  logic start_block = 1'b0;
  logic block_done;

  rf_global2_core core (
    .clk(clk), .state_reset(state_reset),
    .start_block(start_block), .block_done(block_done)
  );

  always #1 clk = ~clk;

  integer fd_t;
  integer b, i, nblocks;
  string ctrl_name, in_name, trace_name, resetat_str;

  logic [31:0] ctrl_mem [0:1 << 20];   // flat: nblocks * CTRL_WORDS
  logic [31:0] in_mem   [0:1 << 22];   // flat: nblocks * IN_WORDS
  integer resetat;

  initial begin
    if (!$value$plusargs("CTRLFILE=%s", ctrl_name)) ctrl_name = "";
    if (!$value$plusargs("INFILE=%s", in_name)) in_name = "";
    if (!$value$plusargs("TRACE=%s", trace_name)) trace_name = "/tmp/rf_global2_trace.txt";
    if (!$value$plusargs("NBLOCKS=%d", nblocks)) nblocks = 0;
    // single optional reset-before-block index (-1 = no reset); the
    // planned negative controls need at most one reset event each.
    if (!$value$plusargs("RESETAT=%d", resetat)) resetat = -1;

    $readmemh(ctrl_name, ctrl_mem);
    $readmemh(in_name, in_mem);

    fd_t = $fopen(trace_name, "w");
    if (fd_t == 0) $fatal(1, "cannot open trace file %s", trace_name);

    // power-on reset
    state_reset = 1'b1;
    @(negedge clk); @(negedge clk);
    state_reset = 1'b0;

    for (b = 0; b < nblocks; b++) begin
      if (b == resetat) begin
        $fwrite(fd_t, "X RESET %0d\n", b);
        @(negedge clk); state_reset = 1'b1;
        @(negedge clk); state_reset = 1'b0;
      end

      // config-bus poke (hierarchical; matches reverb1_core.sv precedent)
      core.cfg_fx_bypass      = ctrl_mem[b*CTRL_WORDS + 0][1:0];
      core.cfg_fx_disable     = ctrl_mem[b*CTRL_WORDS + 1][15:0];
      core.cfg_slot1_occupied = ctrl_mem[b*CTRL_WORDS + 2][0];
      core.cfg_slot2_occupied = ctrl_mem[b*CTRL_WORDS + 3][0];
      for (i = 0; i < 5; i++) begin
        core.cfg_slot1_c[i] = $signed(ctrl_mem[b*CTRL_WORDS + 5 + i]);
        core.cfg_slot2_c[i] = $signed(ctrl_mem[b*CTRL_WORDS + 10 + i]);
      end
      core.glob_in = ctrl_mem[b*CTRL_WORDS + 4][0];

      for (i = 0; i < BLOCK; i++) begin
        core.in_l[i] = $signed(in_mem[b*IN_WORDS + i]);
        core.in_r[i] = $signed(in_mem[b*IN_WORDS + BLOCK + i]);
      end

      @(negedge clk); start_block = 1'b1;
      @(negedge clk); start_block = 1'b0;
      while (!block_done) @(negedge clk);
      dump_checkpoint(b);
    end

    $fclose(fd_t);
    $display("DONE blocks=%0d", nblocks);
    $finish;
  end

  task automatic dump_checkpoint(input integer blk);
    $fwrite(fd_t, "T %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n", blk,
            core.s1_reg0[0], core.s1_reg0[1], core.s1_reg1[0], core.s1_reg1[1],
            core.s2_reg0[0], core.s2_reg0[1], core.s2_reg1[0], core.s2_reg1[1],
            core.glob_out);
    $fwrite(fd_t, "O %0d", blk);
    for (i = 0; i < BLOCK; i++) $fwrite(fd_t, " %0d", core.out_l[i]);
    for (i = 0; i < BLOCK; i++) $fwrite(fd_t, " %0d", core.out_r[i]);
    $fwrite(fd_t, "\n");
  endtask

endmodule
