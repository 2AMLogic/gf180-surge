// SXT-030 (#316) simulation bench for ext_mem_instr.
//
// Drives one take from a stimulus file and writes the raw witnesses that
// tools/sxt030_stall_bench.py grades against the §9.2 NC-1 validity gate.
// This bench makes no verdict of its own.
//
// External memory: a declared SIMULATION model, not a device — fixed
// MEM_LAT-cycle access latency (with the DUT's issue-on-ack handshake that
// is 4 core cycles per 32-bit word, the E2-class sustained assumption of the
// procedure doc §1.3). Read data are a fixed function of the address,
// mirrored by the Python predictor. It counts every completed access itself,
// so the DUT's EXT_WORDS_* counters can be cross-checked independently.
//
// Input cfg.hex ($readmemh, 64-bit words, 16 hex digits/line):
//   line 0: number of frames in the take
//   line 1: number of register writes N
//   lines 2..2+N-1: frame[63:40] addr[39:32] data[31:0]
//                   a write for frame f takes effect at frame f's start
//                   (f = 0: written before CTRL.RUN is set)
//
// Output bench_trace.txt lines:
//   D <phase> <addr> <value>      register dump (phase 0 before the take,
//                                 1 after it, 2 after a post-take reset)
//   F <frame> <l> <r>             one output frame (bench frame index,
//                                 counted from out_valid = the LRCLK timebase)
//   S <frame>                     stall_strobe seen with that frame's output
//   Q <cycle>                     stall_strobe seen with NO frame output
//   M <we> <tag> <count>          memory-model access count per (we, tag)
//   L <stall_led>                 latching LED at end of take
//   E <text>                      bench-level protocol error
//   Z <frames_seen> <frame_starts>

`timescale 1ns/1ps

module tb_ext_mem_instr;

  parameter integer STALL_W  = 32;
  parameter [31:0]  BUILD_ID = 32'h0000_0000;
  parameter integer MEM_LAT  = 3;

  reg clk = 1'b0, rst = 1'b1;
  reg  [7:0]  reg_addr = 8'd0;
  reg         reg_we = 1'b0;
  reg  [31:0] reg_wdata = 32'd0;
  wire [31:0] reg_rdata;
  wire        mem_req, mem_we;
  wire [23:0] mem_addr;
  wire [31:0] mem_wdata;
  wire [1:0]  mem_tag;
  reg         mem_ack = 1'b0;
  reg  [31:0] mem_rdata = 32'd0;
  wire        frame_start, out_valid, stall_strobe, stall_led;
  wire [15:0] out_l, out_r;

  ext_mem_instr #(.STALL_W(STALL_W), .BUILD_ID(BUILD_ID)) dut (
    .clk(clk), .rst(rst),
    .reg_addr(reg_addr), .reg_we(reg_we), .reg_wdata(reg_wdata),
    .reg_rdata(reg_rdata),
    .mem_req(mem_req), .mem_we(mem_we), .mem_addr(mem_addr),
    .mem_wdata(mem_wdata), .mem_tag(mem_tag),
    .mem_ack(mem_ack), .mem_rdata(mem_rdata),
    .frame_start(frame_start), .out_valid(out_valid),
    .out_l(out_l), .out_r(out_r),
    .stall_strobe(stall_strobe), .stall_led(stall_led)
  );

  always #5 clk = ~clk;

  // ------------------------------------------------- external-memory model
  integer lat_cnt = 0;
  integer mcount [0:7];      // index {we, tag}
  integer k;
  function [31:0] mem_data;
    input [23:0] a;
    reg   [31:0] h;
    begin
      h = {8'd0, a} * 32'h2545_F491;
      mem_data = h ^ (h >> 13);
    end
  endfunction

  always @(posedge clk) begin
    if (rst) begin
      mem_ack <= 1'b0;
      lat_cnt <= 0;
    end else begin
      mem_ack <= 1'b0;
      if (mem_req && !mem_ack) begin
        if (lat_cnt == MEM_LAT - 1) begin
          mem_ack <= 1'b1;
          mem_rdata <= mem_we ? 32'd0 : mem_data(mem_addr);
          mcount[{mem_we, mem_tag}] = mcount[{mem_we, mem_tag}] + 1;
          lat_cnt <= 0;
        end else begin
          lat_cnt <= lat_cnt + 1;
        end
      end
    end
  end

  // ------------------------------------------------- witnesses
  reg [63:0] cfg [0:1025];
  integer nframes, nwrites, wptr, fh, i;
  integer frames_seen = 0, starts_seen = 0, cyc_count = 0;

  always @(posedge clk) begin
    #1;
    cyc_count = cyc_count + 1;
    if (!rst) begin
      if (frame_start) starts_seen = starts_seen + 1;
      if (out_valid) begin
        if (mem_req)
          $fdisplay(fh, "E access_in_flight_at_commit %0d", frames_seen);
        $fdisplay(fh, "F %0d %0d %0d", frames_seen, out_l, out_r);
        if (stall_strobe) $fdisplay(fh, "S %0d", frames_seen);
        frames_seen = frames_seen + 1;
      end else if (stall_strobe) begin
        $fdisplay(fh, "Q %0d", cyc_count);
      end
    end
  end

  task reg_write;
    input [7:0]  a;
    input [31:0] v;
    begin
      reg_addr = a; reg_wdata = v; reg_we = 1'b1;
      @(posedge clk); #1;
      reg_we = 1'b0;
    end
  endtask

  task dump;
    input integer phase;
    reg [7:0] addrs [0:17];
    integer j;
    begin
      addrs[0] = 8'h00; addrs[1] = 8'h01; addrs[2] = 8'h02;
      addrs[3] = 8'h03; addrs[4] = 8'h04; addrs[5] = 8'h05;
      addrs[6] = 8'h06; addrs[7] = 8'h07; addrs[8] = 8'h08;
      addrs[9] = 8'h09; addrs[10] = 8'h0A; addrs[11] = 8'h0B;
      addrs[12] = 8'h10; addrs[13] = 8'h11; addrs[14] = 8'h12;
      addrs[15] = 8'h14; addrs[16] = 8'h15; addrs[17] = 8'h16;
      for (j = 0; j < 18; j = j + 1) begin
        reg_addr = addrs[j];
        #1;
        $fdisplay(fh, "D %0d %0d %0d", phase, addrs[j], reg_rdata);
      end
    end
  endtask

  // apply every write stamped for frame f
  task apply_writes;
    input integer f;
    begin
      while (wptr < nwrites + 2 && cfg[wptr][63:40] == f) begin
        reg_write(cfg[wptr][39:32], cfg[wptr][31:0]);
        wptr = wptr + 1;
      end
    end
  endtask

  initial begin
    for (k = 0; k < 8; k = k + 1) mcount[k] = 0;
    fh = $fopen("bench_trace.txt", "w");
    $readmemh("cfg.hex", cfg);
    nframes = cfg[0][31:0];
    nwrites = cfg[1][31:0];
    wptr = 2;
    rst = 1'b1;
    repeat (3) @(posedge clk);
    #1 rst = 1'b0;
    @(posedge clk); #1;
    dump(0);
    apply_writes(0);
    reg_write(8'h01, 32'd1);                 // CTRL.RUN
    for (i = 0; i < nframes; i = i + 1) begin
      // wait for frame i to start, then stage frame i+1's writes
      begin: wait_start
        forever begin
          @(posedge clk); #1;
          if (frame_start === 1'b1) disable wait_start;
        end
      end
      #1;
      apply_writes(i + 1);
      if (i == nframes - 1) reg_write(8'h01, 32'd0);  // stop after frame i
    end
    // wait for the last frame's output
    while (frames_seen < nframes) @(posedge clk);
    repeat (4) @(posedge clk);
    #2;
    dump(1);
    for (k = 0; k < 8; k = k + 1)
      $fdisplay(fh, "M %0d %0d %0d", k >> 2, k & 3, mcount[k]);
    $fdisplay(fh, "L %0d", stall_led);
    // counter reset behaviour: a reset after the take clears everything
    rst = 1'b1;
    repeat (2) @(posedge clk);
    #1 rst = 1'b0;
    @(posedge clk); #1;
    dump(2);
    $fdisplay(fh, "Z %0d %0d", frames_seen, starts_seen);
    $fclose(fh);
    $display("SXT030_BENCH_DONE frames=%0d", frames_seen);
    $finish;
  end

endmodule
