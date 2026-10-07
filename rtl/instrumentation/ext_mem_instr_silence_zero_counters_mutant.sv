// SXT-030 (#316) COMMITTED NEGATIVE CONTROL (do not fix in place).
//
// Deliberately mutated copy of rtl/instrumentation/ext_mem_instr.sv:
//   `{out_l, out_r} <= miss ? {out_l, out_r} : {smp_l, smp_r};`
//     -> `{out_l, out_r} <= miss ? 32'd0 : {smp_l, smp_r};`
//   `wire stall_count = miss;`
//     -> `wire stall_count = 1'b0;`
// Effect: silence on a miss AND the stall instrumentation stubbed to zero (silence-with-zero-counters).
// Under tools/sxt030_stall_bench.py this build MUST be REFUSED by the NC-1 gate as NO_VERDICT; silence with zero counters is never reportable as a pass or a stall.
// If it ever grades PASS, the bench/gate is broken and must be
// repaired before any SXT-030 instrumentation claim stands.
//
// Regenerate with: python3 tools/make_sxt030_mutants.py

`timescale 1ns/1ps
// SXT-030 (#316) external-memory service/stall instrumentation.
//
// Implements the register/signal set of
// docs/fpga-capture-calibration-procedure.md §9.1 and the two NC-1
// over-subscription mechanisms of §9.2 (M1 load generator, M2 service-window
// throttle) around a declared STUB fixture. SIMULATION ONLY: nothing here is
// an FPGA, synthesis, timing, power or playback claim, and the stub fixture
// is a traffic shape, not DSP.
//
// Frame model (one 48 kHz output frame = CYCLES_PER_FRAME core cycles):
//   cyc 0              frame start: latch SVC_WINDOW_LIMIT and
//                      LOADGEN_WORDS_PER_FRAME, clear per-frame counts.
//                      A frame starts only while CTRL.RUN = 1.
//   cyc 1 .. F-2       external service. A new access may be issued only
//                      while cyc < window (the M2 grant). Load-generator
//                      accesses (tag 2) are queued AHEAD of the fixture's own
//                      six accesses, so added load delays the fixture's data.
//   cyc F-1            commit. The frame's external service MISSED ITS
//                      DEADLINE iff not every access of the frame completed.
//                      Normal path: emit the fixture sample. Miss: HOLD the
//                      previous frame's sample (never silence, never a quiet
//                      or faded substitute), set OUTPUT_FAULT, count the
//                      stall, pulse stall_strobe, latch stall_led.
//   window <= F - SVC_RESERVE (clamped on write), and SVC_RESERVE exceeds one
//   access's latency, so every access issued inside the window completes
//   before commit: a miss always leaves un-issued work, and therefore always
//   records STALL_CYCLES > 0.
//
// Stub fixture traffic per frame (6 words; >= the #19 measured-shape anchor
// of ~1,070,000 B/s = ~5.6 words per 48 kHz frame):
//   tag 0 (instance 0): read j0, read j1, ... write (its output sample)
//   tag 1 (instance 1): read j0, read j1, ... write (its output sample)
// out_l = ((d0[15:0] ^ d1[31:16]) + frame[15:0]) | 1 from instance 0's reads,
// out_r likewise from instance 1's — a normal-path sample is never zero.
//
// Holding when no previous frame exists (a stall in frame 0): the output
// register resets to HOLD_RESET, a declared non-zero constant, so even that
// case is not silence.
//
// Original to this repository (Apache-2.0). No Surge-derived material.


module ext_mem_instr #(
  parameter integer CYCLES_PER_FRAME   = 1000,
  parameter integer SVC_RESERVE        = 8,
  parameter integer SVC_WINDOW_NOMINAL = 960,
  parameter integer STALL_W            = 32,
  parameter [31:0]  BUILD_ID           = 32'h0000_0000,
  parameter [15:0]  HOLD_RESET         = 16'h4000
) (
  input  wire        clk,
  input  wire        rst,
  // control link (register map: see reports/SXT-030/EVIDENCE.md)
  input  wire [7:0]  reg_addr,
  input  wire        reg_we,
  input  wire [31:0] reg_wdata,
  output reg  [31:0] reg_rdata,
  // external-memory port (req held until ack; one access in flight)
  output reg         mem_req,
  output reg         mem_we,
  output reg  [23:0] mem_addr,
  output reg  [31:0] mem_wdata,
  output reg  [1:0]  mem_tag,
  input  wire        mem_ack,
  input  wire [31:0] mem_rdata,
  // audio frame timebase (LRCLK-equivalent) and output
  output reg         frame_start,
  output reg         out_valid,
  output reg  [15:0] out_l,
  output reg  [15:0] out_r,
  // hardware witness
  output reg         stall_strobe,
  output reg         stall_led
);

  localparam integer FIX_WORDS = 6;
  localparam integer MAX_WINDOW = CYCLES_PER_FRAME - SVC_RESERVE;
  localparam [STALL_W-1:0] STALL_SAT = {STALL_W{1'b1}};

  // register addresses
  localparam [7:0] A_BUILD_ID    = 8'h00, A_CTRL        = 8'h01,
                   A_STATUS      = 8'h02, A_FRAME_COUNT = 8'h03,
                   A_EXT_RD      = 8'h04, A_EXT_WR      = 8'h05,
                   A_OCC_MAX     = 8'h06, A_STALL_FR    = 8'h07,
                   A_STALL_CYMAX = 8'h08, A_FIRST_STALL = 8'h09,
                   A_LOADGEN     = 8'h0A, A_SVC_WINDOW  = 8'h0B,
                   A_RD_TAG0     = 8'h10, A_RD_TAG1     = 8'h11,
                   A_RD_TAG2     = 8'h12, A_WR_TAG0     = 8'h14,
                   A_WR_TAG1     = 8'h15, A_WR_TAG2     = 8'h16;

  // ------------------------------------------------------------ registers
  reg         run;
  reg [31:0]  loadgen_words;
  reg [31:0]  svc_window;
  reg [31:0]  frame_count, ext_rd, ext_wr, occ_max, stall_cycles_max;
  reg [31:0]  first_stall_frame;
  reg         first_stall_valid, output_fault;
  reg [STALL_W-1:0] stall_frames;
  reg [31:0]  rd_tag [0:2];
  reg [31:0]  wr_tag [0:2];

  // ------------------------------------------------------------ frame state
  reg [31:0]  cyc;
  reg [31:0]  frame_idx;          // index of the frame in progress
  reg [31:0]  win_l;              // latched grant window
  reg [31:0]  total, issued, done_cnt, occ, blk;
  reg [31:0]  lg_l;
  reg [31:0]  d00, d01, d10, d11;

  wire [15:0] smp_l = ((d00[15:0] ^ d01[31:16]) + frame_idx[15:0]) | 16'h0001;
  wire [15:0] smp_r = ((d10[15:0] ^ d11[31:16]) + frame_idx[15:0]) | 16'h0001;

  // deadline: every access of the frame completed by the commit cycle
  wire miss = (done_cnt != total);
  // the instrumentation sees exactly the misses the output policy acts on
  wire stall_count = 1'b0;

  function [31:0] sat_inc;
    input [31:0] v;
    begin
      sat_inc = (v == 32'hFFFF_FFFF) ? v : v + 32'd1;
    end
  endfunction

  function [31:0] max32;
    input [31:0] a, b;
    begin
      max32 = (a > b) ? a : b;
    end
  endfunction

  // scattered address: mix of (tag, frame, index); mirrored exactly by
  // tools/sxt030_stall_bench.py
  function [23:0] scatter;
    input [1:0]  tag;
    input [31:0] n;
    input [31:0] j;
    reg   [31:0] h;
    begin
      h = ({tag, 30'd0} ^ (n << 12) ^ j) * 32'h9E37_79B1;
      h = h ^ (h >> 15);
      scatter = h[23:0];
    end
  endfunction

  // the k-th access of the frame: loadgen first, then the fixture's six
  task issue_access;
    input [31:0] k;
    reg   [31:0] f;
    begin
      mem_req <= 1'b1;
      if (k < lg_l) begin
        mem_we    <= 1'b0;
        mem_tag   <= 2'd2;
        mem_addr  <= scatter(2'd2, frame_idx, k);
        mem_wdata <= 32'd0;
      end else begin
        f = k - lg_l;
        case (f)
          32'd0: begin mem_we <= 1'b0; mem_tag <= 2'd0;
                       mem_addr <= scatter(2'd0, frame_idx, 32'd0);
                       mem_wdata <= 32'd0; end
          32'd1: begin mem_we <= 1'b0; mem_tag <= 2'd0;
                       mem_addr <= scatter(2'd0, frame_idx, 32'd1);
                       mem_wdata <= 32'd0; end
          32'd2: begin mem_we <= 1'b0; mem_tag <= 2'd1;
                       mem_addr <= scatter(2'd1, frame_idx, 32'd0);
                       mem_wdata <= 32'd0; end
          32'd3: begin mem_we <= 1'b0; mem_tag <= 2'd1;
                       mem_addr <= scatter(2'd1, frame_idx, 32'd1);
                       mem_wdata <= 32'd0; end
          32'd4: begin mem_we <= 1'b1; mem_tag <= 2'd0;
                       mem_addr <= scatter(2'd0, frame_idx, 32'd4);
                       mem_wdata <= {16'd0, smp_l}; end
          default: begin mem_we <= 1'b1; mem_tag <= 2'd1;
                       mem_addr <= scatter(2'd1, frame_idx, 32'd5);
                       mem_wdata <= {16'd0, smp_r}; end
        endcase
      end
    end
  endtask

  // ------------------------------------------------------------ read port
  always @(*) begin
    case (reg_addr)
      A_BUILD_ID:    reg_rdata = BUILD_ID;
      A_CTRL:        reg_rdata = {31'd0, run};
      A_STATUS:      reg_rdata = {28'd0, (stall_frames == STALL_SAT),
                                  stall_led, first_stall_valid,
                                  output_fault};
      A_FRAME_COUNT: reg_rdata = frame_count;
      A_EXT_RD:      reg_rdata = ext_rd;
      A_EXT_WR:      reg_rdata = ext_wr;
      A_OCC_MAX:     reg_rdata = occ_max;
      A_STALL_FR:    reg_rdata = stall_frames;
      A_STALL_CYMAX: reg_rdata = stall_cycles_max;
      A_FIRST_STALL: reg_rdata = first_stall_frame;
      A_LOADGEN:     reg_rdata = loadgen_words;
      A_SVC_WINDOW:  reg_rdata = svc_window;
      A_RD_TAG0:     reg_rdata = rd_tag[0];
      A_RD_TAG1:     reg_rdata = rd_tag[1];
      A_RD_TAG2:     reg_rdata = rd_tag[2];
      A_WR_TAG0:     reg_rdata = wr_tag[0];
      A_WR_TAG1:     reg_rdata = wr_tag[1];
      A_WR_TAG2:     reg_rdata = wr_tag[2];
      default:       reg_rdata = 32'hDEAD_0000 | {24'd0, reg_addr};
    endcase
  end

  // ------------------------------------------------------------ main
  integer t;
  always @(posedge clk) begin
    if (rst) begin
      run <= 1'b0;
      loadgen_words <= 32'd0;
      svc_window <= (SVC_WINDOW_NOMINAL > MAX_WINDOW) ? MAX_WINDOW
                                                      : SVC_WINDOW_NOMINAL;
      frame_count <= 32'd0; ext_rd <= 32'd0; ext_wr <= 32'd0;
      occ_max <= 32'd0; stall_cycles_max <= 32'd0;
      first_stall_frame <= 32'd0; first_stall_valid <= 1'b0;
      output_fault <= 1'b0; stall_frames <= {STALL_W{1'b0}};
      for (t = 0; t < 3; t = t + 1) begin
        rd_tag[t] <= 32'd0; wr_tag[t] <= 32'd0;
      end
      cyc <= 32'd0; frame_idx <= 32'd0; win_l <= 32'd0; lg_l <= 32'd0;
      total <= 32'd0; issued <= 32'd0; done_cnt <= 32'd0;
      occ <= 32'd0; blk <= 32'd0;
      d00 <= 32'd0; d01 <= 32'd0; d10 <= 32'd0; d11 <= 32'd0;
      mem_req <= 1'b0; mem_we <= 1'b0; mem_addr <= 24'd0;
      mem_wdata <= 32'd0; mem_tag <= 2'd0;
      frame_start <= 1'b0; out_valid <= 1'b0;
      out_l <= HOLD_RESET; out_r <= HOLD_RESET;
      stall_strobe <= 1'b0; stall_led <= 1'b0;
    end else begin
      frame_start <= 1'b0;
      out_valid <= 1'b0;
      stall_strobe <= 1'b0;

      // control-link writes
      if (reg_we) begin
        case (reg_addr)
          A_CTRL:       run <= reg_wdata[0];
          A_LOADGEN:    loadgen_words <= reg_wdata;
          A_SVC_WINDOW: svc_window <= (reg_wdata > MAX_WINDOW) ? MAX_WINDOW
                                                               : reg_wdata;
          default: ;
        endcase
      end

      // access completion and word counters (any cycle)
      if (mem_ack && mem_req) begin
        mem_req <= 1'b0;
        done_cnt <= done_cnt + 32'd1;
        if (mem_we) begin
          ext_wr <= sat_inc(ext_wr);
          wr_tag[mem_tag] <= sat_inc(wr_tag[mem_tag]);
        end else begin
          ext_rd <= sat_inc(ext_rd);
          rd_tag[mem_tag] <= sat_inc(rd_tag[mem_tag]);
          if (done_cnt == lg_l + 32'd0) d00 <= mem_rdata;
          if (done_cnt == lg_l + 32'd1) d01 <= mem_rdata;
          if (done_cnt == lg_l + 32'd2) d10 <= mem_rdata;
          if (done_cnt == lg_l + 32'd3) d11 <= mem_rdata;
        end
      end

      if (cyc == 32'd0) begin
        if (run) begin
          win_l <= svc_window;
          lg_l <= loadgen_words;
          total <= loadgen_words + FIX_WORDS;
          issued <= 32'd0; done_cnt <= 32'd0; occ <= 32'd0; blk <= 32'd0;
          frame_start <= 1'b1;
          cyc <= 32'd1;
        end
      end else if (cyc == CYCLES_PER_FRAME - 1) begin
        // commit: the held-sample deadline-miss policy
        out_valid <= 1'b1;
        {out_l, out_r} <= miss ? 32'd0 : {smp_l, smp_r};
        frame_count <= sat_inc(frame_count);
        occ_max <= max32(occ_max, occ);
        if (stall_count) begin
          if (stall_frames != STALL_SAT)
            stall_frames <= stall_frames + 1'b1;
          if (!first_stall_valid) begin
            first_stall_frame <= frame_idx;
            first_stall_valid <= 1'b1;
          end
          stall_cycles_max <= max32(stall_cycles_max, blk);
          output_fault <= 1'b1;
          stall_strobe <= 1'b1;
          stall_led <= 1'b1;
        end
        frame_idx <= frame_idx + 32'd1;
        cyc <= 32'd0;
      end else begin
        // service cycle: occupancy, blocked cycles, issue under the grant
        if (mem_req) occ <= occ + 32'd1;
        if (issued < total && cyc >= win_l) blk <= blk + 32'd1;
        if (issued < total && cyc < win_l && (!mem_req || mem_ack)) begin
          issue_access(issued);
          issued <= issued + 32'd1;
        end
        cyc <= cyc + 32'd1;
      end
    end
  end

endmodule
