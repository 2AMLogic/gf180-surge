// SXT-024 Reverb1 iverilog harness.
//
// Instantiates reverb1_core, provides the EXTERNAL writable memory behind the
// core's em_* port (composite taps + predelay line, 557056 x 32b words --
// the measured per-instance buffer requirement), logs every external-memory
// transaction in issue order, and dumps per-block checkpoints + s32i output
// blocks + the final external-memory image for EXACT comparison against the
// frozen model (tools/run_reverb_rtl.py).
//
// Stimulus (emitted by tools/run_reverb_rtl.py; control-plane boundary):
//   rtl/effects/reverb1/sim/cfg.hex    86 coefficient words (frozen formats)
//   rtl/effects/reverb1/sim/blocks.hex header word (nblocks) then per block:
//                                      header (bit15 = state reset before the
//                                      block; bits[14:0] = block index),
//                                      32 x in_l, 32 x in_r (s24 words)
//
// Outputs (compared by tools/run_reverb_rtl.py):
//   out/sxt-024/rtl/tb_trace.txt    T (checkpoint) + O (outputs) lines
//   out/sxt-024/rtl/txn_rtl.txt     R/W addr data per external access in
//                                   issue order, X RESET markers
//   out/sxt-024/rtl/mem_rtl.hex     final external-memory image (case A)
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module tb_reverb1;

  localparam int MEM_WORDS = 524288 + 32768;   // taps + predelay (32b words)
  localparam int BLOCK     = 32;

  logic clk = 1'b0;
  logic state_reset = 1'b0;
  logic start_block = 1'b0;
  logic block_done;

  logic [31:0]        em_addr;
  logic               em_req, em_we;
  logic signed [31:0] em_wdata;
  logic signed [31:0] em_rdata;

  // the external writable memory (flash is never a substitute: this is RAM)
  logic [31:0] ext_mem [0:MEM_WORDS-1];

  reverb1_core core (
    .clk(clk), .state_reset(state_reset), .start_block(start_block),
    .block_done(block_done),
    .em_addr(em_addr), .em_req(em_req), .em_we(em_we),
    .em_wdata(em_wdata), .em_rdata(em_rdata)
  );

  // combinational zero-wait-state external memory read
  assign em_rdata = $signed(ext_mem[em_addr]);

  // external memory write path (synchronous RAM write, visible next cycle)
  always @(posedge clk) begin
    if (em_req && em_we) ext_mem[em_addr] <= em_wdata;
  end

  // transaction + trace logs
  integer fd_t, fd_x, fd_m;
  integer b, i, nblocks, nb;
  logic [31:0] w;

  always @(negedge clk) begin
    if (em_req) begin
      if (em_we) $fwrite(fd_x, "W %0d %0d\n", em_addr, em_wdata);
      else       $fwrite(fd_x, "R %0d %0d\n", em_addr, em_rdata);
    end
  end

  always #1 clk = ~clk;

  // stimulus arrays
  logic [31:0] tb_cfg  [0:85];
  logic [31:0] sched   [0:400000];

  initial begin
    fd_t = $fopen("out/sxt-024/rtl/tb_trace.txt", "w");
    fd_x = $fopen("out/sxt-024/rtl/txn_rtl.txt", "w");
    if (fd_t == 0 || fd_x == 0) $fatal(1, "cannot open output logs");
    for (i = 0; i < MEM_WORDS; i++) ext_mem[i] = 32'b0;

    // coefficient preload (control-plane boundary; frozen quantized words)
    $readmemh("rtl/effects/reverb1/sim/cfg.hex", tb_cfg);
    core.cfg_pdtime  = $signed(tb_cfg[0]);
    core.cfg_damp    = $signed(tb_cfg[1]);
    core.cfg_damp_m1 = $signed(tb_cfg[2]);
    core.cfg_mix     = $signed(tb_cfg[3]);
    core.cfg_mix_m1  = $signed(tb_cfg[4]);
    core.cfg_width_s = $signed(tb_cfg[5]);
    core.cfg_locut_active = tb_cfg[6][0];
    core.cfg_hicut_active = tb_cfg[6][1];
    for (i = 0; i < 16; i++) begin
      core.cfg_dt[i]    = $signed(tb_cfg[7+i]);
      core.cfg_dfb[i]   = $signed(tb_cfg[23+i]);
      core.cfg_pan_l[i] = $signed(tb_cfg[39+i]);
      core.cfg_pan_r[i] = $signed(tb_cfg[55+i]);
    end
    for (i = 0; i < 5; i++) begin
      core.cfg_bi_locut[i] = $signed(tb_cfg[71+i]);
      core.cfg_bi_band1[i] = $signed(tb_cfg[76+i]);
      core.cfg_bi_hicut[i] = $signed(tb_cfg[81+i]);
    end

    // block schedule
    $readmemh("rtl/effects/reverb1/sim/blocks.hex", sched);
    nblocks = int'(sched[0]);
    for (b = 0; b < nblocks; b++) begin
      w = sched[1 + b*(2*BLOCK+1)];
      if (w[15]) begin
        // host bulk clear of the external long buffers (both sides log a
        // RESET marker; the clear itself is a memory action, not a datapath
        // transaction) + core state reset
        for (i = 0; i < MEM_WORDS; i++) ext_mem[i] = 32'b0;
        $fwrite(fd_x, "X RESET\n");
        @(negedge clk); state_reset = 1'b1;
        @(negedge clk); state_reset = 1'b0;
      end
      for (i = 0; i < BLOCK; i++) begin
        core.in_l[i] = $signed(sched[2 + b*(2*BLOCK+1) + i]);
        core.in_r[i] = $signed(sched[2 + b*(2*BLOCK+1) + BLOCK + i]);
      end
      @(negedge clk); start_block = 1'b1;
      @(negedge clk); start_block = 1'b0;
      while (!block_done) @(negedge clk);
      dump_checkpoint(b);
    end

    // final external-memory image for exact comparison (case A only; the
    // runner decides by writing a dump request flag -- we always dump; cheap
    // enough for the planned case sizes)
    fd_m = $fopen("out/sxt-024/rtl/mem_rtl.hex", "w");
    for (i = 0; i < MEM_WORDS; i++) $fwrite(fd_m, "%08h\n", ext_mem[i]);
    $fclose(fd_m);
    $fclose(fd_t);
    $fclose(fd_x);
    $display("DONE blocks=%0d", nblocks);
    $finish;
  end

  task automatic dump_checkpoint(input integer blk);
    $fwrite(fd_t, "T %0d %0d", blk, core.delay_pos);
    for (i = 0; i < 16; i++) $fwrite(fd_t, " %0d", core.out_tap[i]);
    for (i = 0; i < 12; i++) $fwrite(fd_t, " %0d", core.bregs[i]);
    $fwrite(fd_t, "\n");
    $fwrite(fd_t, "O %0d", blk);
    for (i = 0; i < BLOCK; i++) $fwrite(fd_t, " %0d", core.out_l[i]);
    for (i = 0; i < BLOCK; i++) $fwrite(fd_t, " %0d", core.out_r[i]);
    $fwrite(fd_t, "\n");
  endtask

endmodule
