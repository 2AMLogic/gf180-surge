// SXT-028k Airwindows "Logical" (id 4) iverilog harness.
//
// Drives logical4_core (or logical4_mutants.sv's same-named defective core)
// from a control-plane stream emitted by tools/compare_rtl_model_aw4.py and
// dumps, per block, the FULL per-instance state checkpoint for BOTH
// instances plus the active instance's output block, for EXACT integer
// comparison against the frozen model.
//
// This single harness carries both required benches:
//   * the DUAL-INSTANCE bench — every checkpoint line dumps instance 0 and
//     instance 1 separately, so a pooled-history implementation cannot pass
//     (the tb_fx_shared_line.sv "shared instead of per-instance state"
//     defect is exactly logical4_mutants.sv -DNC_SHARED_STATE);
//   * the NEGATIVE-CONTROL bench — the comparator drives the stage-order
//     permutation, the dropped-tail truncation, the quirk-"fix" mutants and
//     a stale frozen-revision pin through this same stimulus path.
//
// Stale-stub control: the first word of cfg.hex is the frozen model's
// revision word. The harness echoes it on the `R` line and the comparator
// REFUSES to report PASS when the echoed word does not match the model it
// just ran (a stale harness therefore cannot report a pass).
//
// Plusargs:
//   +CFG=<path>      cfg.hex     96-bit words: [0] revision word, [1..31]
//                    instance-0 coefficient plane, [32..62] instance-1 plane
//   +BLOCKS=<path>   blocks.hex  96-bit words: [0] nblocks, then per block a
//                    header (bit95 = state_reset before this block,
//                    bit94 = instance select, bits[15:0] = block index)
//                    followed by 32 x in_l then 32 x in_r (a48 words)
//   +TRACE=<path>    output trace
//   +SINROM/+OMCROM  ROM image paths (forwarded to the core)
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module tb_logical4;

  localparam int BLOCK = 32;
  localparam int NSTAGE = 3;
  localparam int NCH = 2;
  localparam int RING = 4;
  localparam int PLANE_WORDS = 31;
  localparam int MAXW = 4 * 1024 * 1024;

  logic clk = 1'b0;
  logic state_reset = 1'b0;
  logic start_block = 1'b0;
  logic block_done;

  logical4_core core (
    .clk(clk), .state_reset(state_reset),
    .start_block(start_block), .block_done(block_done)
  );

  always #1 clk = ~clk;

  logic [95:0] cfgmem [0:127];
  logic [95:0] sched  [0:MAXW-1];

  string cfg_path = "sim/cfg.hex";
  string blk_path = "sim/blocks.hex";
  string trc_path = "sim/tb_trace.txt";

  integer fd, b, i, j, nblocks;
  logic [95:0] hdr;

  task automatic dump_inst(input integer ii);
    integer s, c, r;
    begin
      $fwrite(fd, " %0d %0d", $signed(core.gcount[ii]), core.fp_flip[ii]);
      for (s = 0; s < NSTAGE; s++)
        for (c = 0; c < NCH; c++)
          $fwrite(fd, " %0d %0d %0d %0d",
                  $signed(core.c_apos[ii][s][c]),
                  $signed(core.c_aneg[ii][s][c]),
                  $signed(core.c_bpos[ii][s][c]),
                  $signed(core.c_bneg[ii][s][c]));
      for (s = 0; s < NSTAGE; s++)
        for (c = 0; c < NCH; c++)
          $fwrite(fd, " %0d %0d",
                  $signed(core.t_pos[ii][s][c]), $signed(core.t_neg[ii][s][c]));
      for (s = 0; s < NSTAGE; s++)
        for (c = 0; c < NCH; c++)
          $fwrite(fd, " %0d %0d",
                  $signed(core.avgr[ii][s][c]), $signed(core.nvgr[ii][s][c]));
      for (s = 0; s < NSTAGE; s++)
        for (c = 0; c < NCH; c++)
          $fwrite(fd, " %0d", $signed(core.sag_ctrl[ii][s][c]));
      for (s = 0; s < NSTAGE; s++)
        for (c = 0; c < NCH; c++)
          for (r = 0; r < RING; r++)
            $fwrite(fd, " %0d", $signed(core.sag_line[ii][s][c][r]));
    end
  endtask

  initial begin
    if ($value$plusargs("CFG=%s", cfg_path)) ;
    if ($value$plusargs("BLOCKS=%s", blk_path)) ;
    if ($value$plusargs("TRACE=%s", trc_path)) ;

    fd = $fopen(trc_path, "w");
    if (fd == 0) $fatal(1, "cannot open trace %s", trc_path);

    $readmemh(cfg_path, cfgmem);
    for (i = 0; i < PLANE_WORDS; i++) begin
      core.cfg[0][i] = $signed(cfgmem[1 + i]);
      core.cfg[1][i] = $signed(cfgmem[1 + PLANE_WORDS + i]);
    end
    $fwrite(fd, "R %0d\n", cfgmem[0][31:0]);

    // constructor state for both instances before any block
    @(negedge clk); state_reset = 1'b1;
    @(negedge clk); state_reset = 1'b0;

    $readmemh(blk_path, sched);
    nblocks = int'(sched[0][31:0]);
    j = 1;
    for (b = 0; b < nblocks; b++) begin
      hdr = sched[j]; j = j + 1;
      if (hdr[95]) begin
        @(negedge clk); state_reset = 1'b1;
        @(negedge clk); state_reset = 1'b0;
      end
      core.inst = hdr[94];
      for (i = 0; i < BLOCK; i++) begin
        core.in_l[i] = $signed(sched[j + i]);
        core.in_r[i] = $signed(sched[j + BLOCK + i]);
      end
      j = j + 2 * BLOCK;
      @(negedge clk); start_block = 1'b1;
      @(negedge clk); start_block = 1'b0;
      while (!block_done) @(negedge clk);
      @(negedge clk);

      $fwrite(fd, "T %0d %0d", b, core.inst);
      dump_inst(0);
      dump_inst(1);
      $fwrite(fd, "\n");
      $fwrite(fd, "O %0d", b);
      for (i = 0; i < BLOCK; i++) $fwrite(fd, " %0d", $signed(core.out_l[i]));
      for (i = 0; i < BLOCK; i++) $fwrite(fd, " %0d", $signed(core.out_r[i]));
      $fwrite(fd, "\n");
    end
    $fwrite(fd, "C %0d %0d %0d\n", core.n_div, core.n_clip, core.n_tap3);
    $fclose(fd);
    $display("DONE blocks=%0d divisions=%0d clips=%0d tap3=%0d",
             nblocks, core.n_div, core.n_clip, core.n_tap3);
    $finish;
  end

endmodule
