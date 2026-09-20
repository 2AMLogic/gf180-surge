// SXT-021 control-plane testbench: drives the model's event stream into
// control_top and writes the RTL trace compared by tools/compare_control_rtl.py.
//
// Input  events.hex ($readmemh, 80-bit words, 20 hex digits/line):
//   line 0: event count N
//   line 1: total samples to render
//   lines 2..2+N-1: events, arrival order (nondecreasing t), word layout
//                   t[79:48] type[47:40] p1[39:24] p2[23:8]
//
// Protocol per sample s (mirrors the model's push-then-process block step):
//   push every event with t == s (single cycle each, DUT always accepts),
//   then tick_req until out_valid/tick_ack; block-start ticks stall in the
//   DUT while up to 8 queued events are dispatched.
//
// Output rtl_trace.txt lines:
//   T b qcount patch acount (a n q)x8      block-start snapshot
//   E b seq type p1 p2 slot steal status f  applied decision
//   X b t type p1 p2                        explicit queue-overflow drop
//   M b s l r                               stereo sample (the recording)
//   U b s                                   underrun (tick starved; a FAIL)

`timescale 1ns/1ps

module tb_control;

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

  control_top dut (
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

  always #5 clk = ~clk;

  reg [79:0] evmem [0:4097];
  integer nev, nsamples, evptr, s, i, guard, underruns;
  integer fh;

  // strobe sampler: preserves in-cycle order of E / X records per block
  always @(posedge clk) begin
    #1;
    if (!rst) begin
      if (ev_strobe)
        $fdisplay(fh, "E %0d %0d %0d %0d %0d %0d %0d %0d %0d",
                  ev_b, ev_seq, ev_type, ev_p1, ev_p2, ev_slot, ev_steal,
                  ev_status, ev_flush);
      if (drop_strobe)
        $fdisplay(fh, "X %0d %0d %0d %0d %0d",
                  drop_b, drop_word[79:48], drop_word[47:40],
                  drop_word[39:24], drop_word[23:8]);
    end
  end

  initial begin
    fh = $fopen("rtl_trace.txt", "w");
    $readmemh("events.hex", evmem);
    nev      = evmem[0][15:0];
    nsamples = evmem[1][31:0];
    underruns = 0;
    rst = 1'b1;
    @(posedge clk); #1;
    @(posedge clk); #1;
    rst = 1'b0; #1;
    evptr = 2;
    for (s = 0; s < nsamples; s = s + 1) begin
      // push phase: every event stamped with this sample's timestamp
      while (evptr < nev + 2 && evmem[evptr][79:48] == s) begin
        ev_word = evmem[evptr];
        ev_valid = 1'b1;
        @(posedge clk); #1;
        ev_valid = 1'b0;
        evptr = evptr + 1;
      end
      // sample tick: wait for the output word (block-start ticks stall)
      tick_req = 1'b1;
      guard = 0;
      begin: wait_out
        forever begin
          @(posedge clk); #1;
          if (out_valid) begin
            if (s % 32 == 0) begin
              $fwrite(fh, "T %0d %0d %0d %0d",
                      dbg_block, dbg_qcount, dbg_patch, dbg_acount);
              for (i = 0; i < 8; i = i + 1)
                $fwrite(fh, " %0d %0d %0d",
                        dbg_voices[25*i+24 -: 1],
                        dbg_voices[25*i+23 -: 8],
                        dbg_voices[25*i+15 -: 16]);
              $fwrite(fh, "\n");
            end
            $fdisplay(fh, "M %0d %0d %0d %0d", dbg_block, s % 32, out_l, out_r);
            disable wait_out;
          end
          guard = guard + 1;
          if (guard > 64) begin
            $fdisplay(fh, "U %0d %0d", s / 32, s);
            underruns = underruns + 1;
            disable wait_out;
          end
        end
      end
      tick_req = 1'b0;
    end
    $fdisplay(fh, "Z underruns %0d", underruns);
    $fclose(fh);
    $display("BLOCKS %0d UNDERRUNS %0d", nsamples / 32, underruns);
    $finish;
  end

endmodule
