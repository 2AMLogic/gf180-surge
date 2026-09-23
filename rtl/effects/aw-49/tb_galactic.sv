// SXT-028a Galactic iverilog harness.
//
// Instantiates galactic_core, provides the EXTERNAL writable memory behind
// the em_* port (2 x 126354 x 32b words: two independent instance regions
// for the dual-instance schedule), logs every external-memory transaction
// in issue order, and dumps the per-block checkpoints + s32i output blocks
// + the final external-memory image for EXACT comparison against the frozen
// model (tools/compare_rtl_model_aw49.py).
//
// Stimulus (emitted by the runner; control-plane boundary):
//   sim/cfg.hex    fixed layout: [0] frozen-model revision word (echoed in
//                  the trace header - a stale harness refuses to report
//                  PASS), [1] regen c31, [2] attenuate c30, [3] lowpass c31,
//                  [4] lowpass_m1 c31, [5] wet c31, [6] wet_m1 c31,
//                  [7] flags (bit0 = wet_active), [8..19] delay lengths,
//                  [20] EXT_WORDS
//   sim/blocks.hex header word (nblocks) then per block:
//                  header (bit31 = state reset before the block;
//                  bit30 = instance select (0/1); bits[15:0] block index),
//                  32 x {inL, inR, baseL, fracL, baseR, fracR}
//
// Outputs: tb_trace.txt (R header + T/O lines), txn_rtl.txt, mem_rtl.hex.
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module tb_galactic;

  localparam int MEM_WORDS = 2 * 126354;  // two instance regions
  localparam int BLOCK = 32;

  logic clk = 1'b0;
  logic state_reset = 1'b0;
  logic start_block = 1'b0;
  logic block_done;

  logic [31:0] mem_base = 0;   // selected instance's region base
  logic [31:0] em_addr;
  logic em_req, em_we;
  logic signed [31:0] em_wdata;
  logic signed [31:0] em_rdata;

  // the external writable memory (RAM, never flash): TWO disjoint instance
  // regions - per-instance state is never shared
  logic [31:0] ext_mem [0:MEM_WORDS-1];

  // two cores, one per instance region: independent on-chip state
  // (counters, filters, feedback registers); the shared-instance schedule
  // time-multiplexes them, never pooling state
  logic        start0, start1, done0, done1;
  logic [31:0] addr0, addr1;
  logic        req0, we0, req1, we1;
  logic signed [31:0] wd0, wd1;

  galactic_core core0 (
    .clk(clk), .state_reset(state_reset), .start_block(start0),
    .block_done(done0), .mem_base(32'd0),
    .em_addr(addr0), .em_req(req0), .em_we(we0),
    .em_wdata(wd0), .em_rdata(em_rdata)
  );

  galactic_core core1 (
    .clk(clk), .state_reset(state_reset), .start_block(start1),
    .block_done(done1), .mem_base(32'd126354),
    .em_addr(addr1), .em_req(req1), .em_we(we1),
    .em_wdata(wd1), .em_rdata(em_rdata)
  );

  // instance select: mux the active core onto the port (harness-set)
  logic        inst_sel = 1'b0;
  always @* begin
    start0     = start_block & ~inst_sel;
    start1     = start_block & inst_sel;
    block_done = inst_sel ? done1 : done0;
    em_addr    = inst_sel ? addr1 : addr0;
    em_req     = inst_sel ? req1 : req0;
    em_we      = inst_sel ? we1 : we0;
    em_wdata   = inst_sel ? wd1 : wd0;
  end

  assign em_rdata = $signed(ext_mem[em_addr]);

  always @(posedge clk) begin
    if (em_req && em_we) ext_mem[em_addr] <= em_wdata;
  end

  // transaction + trace logs
  integer fd_t, fd_x, fd_m;
  integer b, i, j, nblocks, nb;
  logic [31:0] w, hdr;
  logic [31:0] revword;

  always @(negedge clk) begin
    if (em_req) begin
      if (em_we) $fwrite(fd_x, "W %0d %0d\n", em_addr, em_wdata);
      else       $fwrite(fd_x, "R %0d %0d\n", em_addr, em_rdata);
    end
  end

  always #1 clk = ~clk;

  logic [31:0] cfg [0:63];
  logic [31:0] sched [0:8000000];

  initial begin
    fd_t = $fopen("out/aw-49/rtl/tb_trace.txt", "w");
    fd_x = $fopen("out/aw-49/rtl/txn_rtl.txt", "w");
    if (fd_t == 0 || fd_x == 0) $fatal(1, "cannot open output logs");
    for (i = 0; i < MEM_WORDS; i++) ext_mem[i] = 32'b0;

    $readmemh("rtl/effects/aw-49/sim/cfg.hex", cfg);
    revword = cfg[0];
    $fwrite(fd_t, "R %0d\n", revword);
    core0.cfg_regen = $signed(cfg[1]);
    core0.cfg_attenuate = $signed(cfg[2]);
    core0.cfg_lowpass = $signed(cfg[3]);
    core0.cfg_lowpass_m1 = $signed(cfg[4]);
    core0.cfg_wet = $signed(cfg[5]);
    core0.cfg_wet_m1 = $signed(cfg[6]);
    core0.cfg_wet_active = cfg[7][0];
    for (i = 0; i < 12; i++) core0.cfg_delay[i] = $signed(cfg[8 + i]);
    // an optional second coefficient plane (dual-instance cases) lives in
    // words 21..41; its presence is detected via word 41 being defined
    if (cfg[20] * 2 != MEM_WORDS)
      $display("WARN: cfg EXT_WORDS %0d x2 != MEM_WORDS %0d", cfg[20], MEM_WORDS);
    // second coefficient plane (dual-instance cases): the runner appends
    // coefficient_words(ctrl1)[1:] = 20 words at indices 21..40; presence
    // detected via word 40 ($readmemh leaves unread entries x)
    if (cfg[40] !== 32'hx) begin
      core1.cfg_regen = $signed(cfg[21]);
      core1.cfg_attenuate = $signed(cfg[22]);
      core1.cfg_lowpass = $signed(cfg[23]);
      core1.cfg_lowpass_m1 = $signed(cfg[24]);
      core1.cfg_wet = $signed(cfg[25]);
      core1.cfg_wet_m1 = $signed(cfg[26]);
      core1.cfg_wet_active = cfg[27][0];
      for (i = 0; i < 12; i++) core1.cfg_delay[i] = $signed(cfg[28 + i]);
    end else begin
      core1.cfg_regen = core0.cfg_regen;
      core1.cfg_attenuate = core0.cfg_attenuate;
      core1.cfg_lowpass = core0.cfg_lowpass;
      core1.cfg_lowpass_m1 = core0.cfg_lowpass_m1;
      core1.cfg_wet = core0.cfg_wet;
      core1.cfg_wet_m1 = core0.cfg_wet_m1;
      core1.cfg_wet_active = core0.cfg_wet_active;
      for (i = 0; i < 12; i++) core1.cfg_delay[i] = core0.cfg_delay[i];
    end

    $readmemh("rtl/effects/aw-49/sim/blocks.hex", sched);
    nblocks = int'(sched[0]);
    j = 1;
    for (b = 0; b < nblocks; b++) begin
      hdr = sched[j]; j = j + 1;
      if (hdr[31]) begin
        // host bulk clear of BOTH instance regions + core state reset
        for (i = 0; i < MEM_WORDS; i++) ext_mem[i] = 32'b0;
        $fwrite(fd_x, "X RESET\n");
        @(negedge clk); state_reset = 1'b1;
        @(negedge clk); state_reset = 1'b0;
      end
      inst_sel = hdr[30];
      mem_base = hdr[30] ? 32'd126354 : 32'd0;
      for (i = 0; i < BLOCK; i++) begin
        core0.in_l[i] = $signed(sched[j + 6*i + 0]);
        core0.in_r[i] = $signed(sched[j + 6*i + 1]);
        core0.ctrl[4*i + 0] = $signed(sched[j + 6*i + 2]);
        core0.ctrl[4*i + 1] = $signed(sched[j + 6*i + 3]);
        core0.ctrl[4*i + 2] = $signed(sched[j + 6*i + 4]);
        core0.ctrl[4*i + 3] = $signed(sched[j + 6*i + 5]);
        core1.in_l[i] = core0.in_l[i];
        core1.in_r[i] = core0.in_r[i];
        core1.ctrl[4*i + 0] = core0.ctrl[4*i + 0];
        core1.ctrl[4*i + 1] = core0.ctrl[4*i + 1];
        core1.ctrl[4*i + 2] = core0.ctrl[4*i + 2];
        core1.ctrl[4*i + 3] = core0.ctrl[4*i + 3];
      end
      j = j + 6*BLOCK;
      @(negedge clk); start_block = 1'b1;
      @(negedge clk); start_block = 1'b0;
      while (!block_done) @(negedge clk);
      dump_checkpoint(b);
    end

    fd_m = $fopen("out/aw-49/rtl/mem_rtl.hex", "w");
    for (i = 0; i < MEM_WORDS; i++) $fwrite(fd_m, "%08h\n", ext_mem[i]);
    $fclose(fd_m);
    $fclose(fd_t);
    $fclose(fd_x);
    $display("DONE blocks=%0d", nblocks);
    $finish;
  end

  task automatic dump_checkpoint(input integer blk);
    integer n;
    // dump from the ACTIVE core (per-instance state)
    $fwrite(fd_t, "T %0d %0d", blk, inst_sel ? core1.countM : core0.countM);
    for (n = 0; n < 12; n++)
      $fwrite(fd_t, " %0d", inst_sel ? core1.counts[n] : core0.counts[n]);
    if (inst_sel) begin
      $fwrite(fd_t, " %0d %0d %0d %0d", core1.iir_a_l, core1.iir_a_r,
              core1.iir_b_l, core1.iir_b_r);
      $fwrite(fd_t, " %0d %0d %0d %0d", core1.fb_al, core1.fb_bl,
              core1.fb_cl, core1.fb_dl);
      $fwrite(fd_t, " %0d %0d %0d %0d", core1.fb_ar, core1.fb_br,
              core1.fb_cr, core1.fb_dr);
      $fwrite(fd_t, "\n");
      $fwrite(fd_t, "O %0d", blk);
      for (n = 0; n < BLOCK; n++) $fwrite(fd_t, " %0d", core1.out_l[n]);
      for (n = 0; n < BLOCK; n++) $fwrite(fd_t, " %0d", core1.out_r[n]);
    end else begin
      $fwrite(fd_t, " %0d %0d %0d %0d", core0.iir_a_l, core0.iir_a_r,
              core0.iir_b_l, core0.iir_b_r);
      $fwrite(fd_t, " %0d %0d %0d %0d", core0.fb_al, core0.fb_bl,
              core0.fb_cl, core0.fb_dl);
      $fwrite(fd_t, " %0d %0d %0d %0d", core0.fb_ar, core0.fb_br,
              core0.fb_cr, core0.fb_dr);
      $fwrite(fd_t, "\n");
      $fwrite(fd_t, "O %0d", blk);
      for (n = 0; n < BLOCK; n++) $fwrite(fd_t, " %0d", core0.out_l[n]);
      for (n = 0; n < BLOCK; n++) $fwrite(fd_t, " %0d", core0.out_r[n]);
    end
    $fwrite(fd_t, "\n");
  endtask

endmodule
