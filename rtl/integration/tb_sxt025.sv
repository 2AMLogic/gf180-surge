// SXT-025 integrated harness: control plane (SXT-021 control_top) + landed
// Reverb1 kernel (SXT-024 reverb1_core) in ONE iverilog simulation on a
// single clock, gated by the control block schedule.
//
// Declared RTL/host boundary (issue #18 task; full-RTL voice NOT required):
//   * IN-CHIP (this sim, two DUTs): the event scheduler/control plane, and
//     the Reverb1 effect kernel with its external writable memory behind the
//     em_* port (557,056 x 32b words; flash is never a substitute).
//   * HOST-SIDE (stimulus words, emitted by model/integration/run_model.py
//     from the frozen integration model): the voice stage (engine all-off
//     dry bus of the SAME preset+sequence -- declared adaptation, finding
//     F-1 in model/integration/README.md), the send/return/master gain
//     staging, and the send-block s24 quantization.
//
// The kernel block for index b starts only after the control plane has
// emitted its block-start snapshot for block b (start_block gate) -- the
// integrated schedule. The harness counts clk cycles per kernel block
// (stall-inclusive: the core issues real em_* transactions) and checks them
// against the declared per-block budget (A-CLK arithmetic, 192 MHz row).
//
// Inputs (same formats as the leaf harnesses):
//   sim/events.hex        SXT-021: N, nsamples, 80-bit event words
//   sim/cfg.hex           SXT-024: 86 coefficient words (frozen formats)
//   sim/blocks.hex        SXT-024: nblocks, then per block: header + 64 s24
//
// Outputs:
//   out/sxt025/rtl/ctl_trace.txt   T/E/X/M/Z lines (SXT-021 format)
//   out/sxt025/rtl/kernel_trace.txt  T/O lines (SXT-024 format)
//   out/sxt025/rtl/txn_rtl.txt     R/W external transactions + K cycle lines
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

module tb_sxt025;

  localparam int MEM_WORDS = 524288 + 32768;
  localparam int BLOCK     = 32;
  localparam int MAX_SCHED = 200000;
  // declared per-block kernel budget at the 192 MHz candidate clock:
  // (192e6/48e3) * 0.8 reserve * 32 samples = 102400 cycles (A-CLK)
  localparam int KERNEL_BLOCK_BUDGET = 102400;

  // ------------------------------------------------------------- control
  reg clk = 1'b0, rst = 1'b1;
  reg ev_valid = 1'b0;
  reg [79:0] ev_word = 80'd0;
  wire ev_ready;
  reg tick_req = 1'b0;
  wire tick_ack, out_valid;
  wire [15:0] out_l, out_r;
  wire ev_strobe, drop_strobe;
  wire [31:0] ev_b, ev_seq, ev_type, ev_p1, ev_p2, ev_slot, ev_steal,
              ev_status, ev_flush, drop_b;
  wire [79:0] drop_word;
  wire [31:0] dbg_block, dbg_qcount, dbg_patch, dbg_acount;
  wire [199:0] dbg_voices;

  control_top u_ctl (
    .clk(clk), .rst(rst),
    .ev_valid(ev_valid), .ev_word(ev_word), .ev_ready(ev_ready),
    .tick_req(tick_req), .tick_ack(tick_ack),
    .out_valid(out_valid), .out_l(out_l), .out_r(out_r),
    .ev_strobe(ev_strobe), .ev_b(ev_b), .ev_seq(ev_seq), .ev_type(ev_type),
    .ev_p1(ev_p1), .ev_p2(ev_p2), .ev_slot(ev_slot), .ev_steal(ev_steal),
    .ev_status(ev_status), .ev_flush(ev_flush),
    .drop_strobe(drop_strobe), .drop_word(drop_word), .drop_b(drop_b),
    .dbg_block(dbg_block), .dbg_qcount(dbg_qcount), .dbg_patch(dbg_patch),
    .dbg_acount(dbg_acount), .dbg_voices(dbg_voices)
  );

  // ------------------------------------------------------------- kernel
  logic state_reset = 1'b0;
  logic start_block = 1'b0;
  logic block_done;
  logic [31:0]        em_addr;
  logic               em_req, em_we;
  logic signed [31:0] em_wdata;
  logic signed [31:0] em_rdata;
  logic [31:0] ext_mem [0:MEM_WORDS-1];

  reverb1_core u_fx (
    .clk(clk), .state_reset(state_reset), .start_block(start_block),
    .block_done(block_done),
    .em_addr(em_addr), .em_req(em_req), .em_we(em_we),
    .em_wdata(em_wdata), .em_rdata(em_rdata)
  );

  assign em_rdata = $signed(ext_mem[em_addr]);
  always @(posedge clk) begin
    if (em_req && em_we) ext_mem[em_addr] <= em_wdata;
  end

  always #5 clk = ~clk;   // tb_control timing discipline (race-free pushes)

  integer fd_c, fd_k, fd_x;
  integer nev, nsamples, evptr, s, i, g, guard, underruns;
  integer nblocks, cycles, worst_cycles, total_cycles;
  logic [79:0] evmem [0:4097];
  logic [31:0] tb_cfg [0:85];
  logic [31:0] sched [0:MAX_SCHED];
  logic [31:0] w;

  // transaction log (kernel) -- on negedge like the SXT-024 harness
  always @(negedge clk) begin
    if (em_req) begin
      if (em_we) $fwrite(fd_x, "W %0d %0d\n", em_addr, em_wdata);
      else       $fwrite(fd_x, "R %0d %0d\n", em_addr, em_rdata);
    end
  end

  // control strobe capture (E/X records, in-cycle order)
  always @(posedge clk) begin
    #1;
    if (!rst) begin
      if (ev_strobe)
        $fdisplay(fd_c, "E %0d %0d %0d %0d %0d %0d %0d %0d %0d",
                  ev_b, ev_seq, ev_type, ev_p1, ev_p2, ev_slot, ev_steal,
                  ev_status, ev_flush);
      if (drop_strobe)
        $fdisplay(fd_c, "X %0d %0d %0d %0d %0d",
                  drop_b, drop_word[79:48], drop_word[47:40],
                  drop_word[39:24], drop_word[23:8]);
    end
  end

  initial begin
    fd_c = $fopen("out/sxt025/rtl/ctl_trace.txt", "w");
    fd_k = $fopen("out/sxt025/rtl/kernel_trace.txt", "w");
    fd_x = $fopen("out/sxt025/rtl/txn_rtl.txt", "w");
    if (fd_c == 0 || fd_k == 0 || fd_x == 0) $fatal(1, "cannot open logs");
    for (i = 0; i < MEM_WORDS; i++) ext_mem[i] = 32'b0;

    // kernel coefficient preload (control-plane boundary, frozen words)
    $readmemh("rtl/integration/sim/cfg.hex", tb_cfg);
    u_fx.cfg_pdtime  = $signed(tb_cfg[0]);
    u_fx.cfg_damp    = $signed(tb_cfg[1]);
    u_fx.cfg_damp_m1 = $signed(tb_cfg[2]);
    u_fx.cfg_mix     = $signed(tb_cfg[3]);
    u_fx.cfg_mix_m1  = $signed(tb_cfg[4]);
    u_fx.cfg_width_s = $signed(tb_cfg[5]);
    u_fx.cfg_locut_active = tb_cfg[6][0];
    u_fx.cfg_hicut_active = tb_cfg[6][1];
    for (i = 0; i < 16; i++) begin
      u_fx.cfg_dt[i]    = $signed(tb_cfg[7+i]);
      u_fx.cfg_dfb[i]   = $signed(tb_cfg[23+i]);
      u_fx.cfg_pan_l[i] = $signed(tb_cfg[39+i]);
      u_fx.cfg_pan_r[i] = $signed(tb_cfg[55+i]);
    end
    for (i = 0; i < 5; i++) begin
      u_fx.cfg_bi_locut[i] = $signed(tb_cfg[71+i]);
      u_fx.cfg_bi_band1[i] = $signed(tb_cfg[76+i]);
      u_fx.cfg_bi_hicut[i] = $signed(tb_cfg[81+i]);
    end

    $readmemh("rtl/integration/sim/events.hex", evmem);
    $readmemh("rtl/integration/sim/blocks.hex", sched);
    nev      = evmem[0][15:0];
    nsamples = evmem[1][31:0];
    nblocks  = int'(sched[0]);
    underruns = 0; worst_cycles = 0; total_cycles = 0;

    rst = 1'b1;
    @(posedge clk); #1;
    @(posedge clk); #1;
    rst = 1'b0; #1;
    evptr = 2;

    for (s = 0; s < nsamples; s = s + 1) begin
      // ---- control plane: push events stamped with this sample
      while (evptr < nev + 2 && evmem[evptr][79:48] == s) begin
        ev_word = evmem[evptr];
        ev_valid = 1'b1;
        @(posedge clk); #1;
        ev_valid = 1'b0;
        evptr = evptr + 1;
      end
      tick_req = 1'b1;
      guard = 0;
      begin: wait_out
        forever begin
          @(posedge clk); #1;
          if (out_valid) begin
            if (s % 32 == 0) begin
              $fwrite(fd_c, "T %0d %0d %0d %0d",
                      dbg_block, dbg_qcount, dbg_patch, dbg_acount);
              for (i = 0; i < 8; i = i + 1)
                $fwrite(fd_c, " %0d %0d %0d",
                        dbg_voices[25*i+24 -: 1],
                        dbg_voices[25*i+23 -: 8],
                        dbg_voices[25*i+15 -: 16]);
              $fwrite(fd_c, "\n");
            end
            $fdisplay(fd_c, "M %0d %0d %0d %0d", dbg_block, s % 32,
                      out_l, out_r);
            disable wait_out;
          end
          guard = guard + 1;
          if (guard > 64) begin
            $fdisplay(fd_c, "U %0d %0d", s / 32, s);
            underruns = underruns + 1;
            disable wait_out;
          end
        end
      end
      tick_req = 1'b0;

      // ---- integrated schedule: at the block boundary run the kernel
      if (s % 32 == 31) begin
        i = s / 32;   // block index just completed at the control plane
        if (i < nblocks) begin
          w = sched[1 + i*(2*BLOCK+1)];
          for (g = 0; g < BLOCK; g = g + 1) begin
            u_fx.in_l[g] = $signed(sched[2 + i*(2*BLOCK+1) + g]);
            u_fx.in_r[g] = $signed(sched[2 + i*(2*BLOCK+1) + BLOCK + g]);
          end
          @(negedge clk); start_block = 1'b1;
          @(negedge clk); start_block = 1'b0;
          cycles = 0;
          while (!block_done) begin
            @(negedge clk);
            cycles = cycles + 1;
          end
          @(negedge clk);
          $fwrite(fd_x, "K %0d %0d\n", i, cycles);
          total_cycles = total_cycles + cycles;
          if (cycles > worst_cycles) worst_cycles = cycles;
          // checkpoint + outputs (SXT-024 T/O format)
          $fwrite(fd_k, "T %0d %0d", i, u_fx.delay_pos);
          for (g = 0; g < 16; g = g + 1)
            $fwrite(fd_k, " %0d", u_fx.out_tap[g]);
          for (g = 0; g < 12; g = g + 1) $fwrite(fd_k, " %0d", u_fx.bregs[g]);
          $fwrite(fd_k, "\n");
          $fwrite(fd_k, "O %0d", i);
          for (g = 0; g < BLOCK; g = g + 1) $fwrite(fd_k, " %0d", u_fx.out_l[g]);
          for (g = 0; g < BLOCK; g = g + 1) $fwrite(fd_k, " %0d", u_fx.out_r[g]);
          $fwrite(fd_k, "\n");
          if (cycles > KERNEL_BLOCK_BUDGET) begin
            $fdisplay(fd_c, "Z kernel_block_budget_exceeded %0d %0d",
                      i, cycles);
          end
        end
      end
    end

    $fdisplay(fd_c, "Z underruns %0d", underruns);
    $fdisplay(fd_x, "Z kernel_blocks %0d worst_cycles %0d total %0d budget %0d",
              nblocks, worst_cycles, total_cycles, KERNEL_BLOCK_BUDGET);
    $display("DONE blocks=%0d underruns=%0d kernel_worst=%0d",
             nblocks, underruns, worst_cycles);
    $fclose(fd_c); $fclose(fd_k); $fclose(fd_x);
    $finish;
  end

endmodule
