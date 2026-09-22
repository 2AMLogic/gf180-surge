// SXT-037 RTL filter leaf: LP 12 dB unit — all three engine subtypes,
// implementing the SAME frozen integer schedule as the fixed-point model
// (model/voice/filter_lp12/filter_lp12_model.py).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared checkpoint; enforced by
// tools/compare_rtl_model_lp12.py). NOT synthesis-closed, NOT timing-closed;
// no gf180mcu FPGA/ASIC claim of any kind.
//
// Structure citations (read, not copied): surge@58914e59
//   sst-filters QuadFilterUnit_Impl.h  SVFLP12Aquad / IIR12CFCquad / IIR12Bquad
//     (per-sample C[i] += dC[i] reload paths; clipgain register position)
//   sst-filters QuadFilterUnit.h       LP12 subtype -> kernel table
//   SurgeVoice.cpp                     per-voice FBP zero-init (R[2]=0) and
//                                      the type/subtype-change reset path
//
// Stimulus (declared control-plane boundary; emitted by
// model/voice/filter_lp12/run_filter_leg.py from the frozen model):
//   init.hex  [n_blocks]
//   ctrl.hex  per block, 18 words: flags(b0 active, b1 reset), subtype,
//             C[8] block-start, dC[8]
//   in.hex    64 input words per block
//
// Trace (tb_trace.txt): one "Y" line per output sample, one "T" line per
// block checkpoint (end-of-block registers + coefficients).
`timescale 1ns/1ps

module tb_lp12;

  localparam int FQ = 21;

  localparam logic signed [31:0] ONE = 32'sd2097152;   // 1.0 Q10.21

  int unsigned qmul_count = 0;

  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << 19)) >>> 21;
    if      (r > 64'sd2147483647)  qmul = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  function automatic signed [31:0] sat32(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = v[31:0];
  endfunction

  function automatic signed [31:0] maxs(input signed [31:0] a, input signed [31:0] b);
    maxs = ($signed(a) > $signed(b)) ? a : b;
  endfunction

  logic [31:0] cfg  [0:0];
  logic [31:0] ctrl_mem [0:8000000];
  logic [31:0] in_mem   [0:8000000];

  // per-instance filter state (engine FBP semantics: registers start at 0)
  logic signed [31:0] r0, r1, r_clip;
  integer fd;
  integer ci, ii, b, k, i, n_blocks;
  logic [31:0] flags, subtype;
  logic signed [31:0] c [8];
  logic signed [31:0] dc [8];
  logic signed [31:0] x, y, low, high, band, low2, high2, band2, f1v, f2v, g1v, g2v, s1v, s2v;

  initial begin
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ctrl.hex", ctrl_mem);
    $readmemh("rtl/in.hex",   in_mem);
    fd = $fopen("tb_trace.txt", "w");
    n_blocks = int'(cfg[0]);
    ci = 0; ii = 0;
    r0 = 0; r1 = 0; r_clip = 0;          // FBP zero-init (R[2] starts at 0)
    for (b = 0; b < n_blocks; b++) begin
      flags   = ctrl_mem[ci + 0];
      subtype = ctrl_mem[ci + 1];
      for (i = 0; i < 8; i++) c[i]  = 32'(ctrl_mem[ci + 2 + i]);
      for (i = 0; i < 8; i++) dc[i] = 32'(ctrl_mem[ci + 10 + i]);
      ci = ci + 18;
      if (!flags[0]) $fatal(1, "inactive block record");
      if (flags[1]) begin
        r0 = 0; r1 = 0; r_clip = 0;      // type/subtype-change reset path
      end
      for (k = 0; k < 64; k++) begin
        x = 32'(in_mem[ii]); ii = ii + 1;
        case (subtype)
          32'd1: begin
            // IIR12CFCquad: reload {0,1,2,4,5,6} before the sample,
            // C[7] (clipgain) after the state update
            for (i = 0; i < 8; i++)
              if (i != 3 && i != 7) c[i] = sat32(c[i] + dc[i]);
            y  = qmul(c[4], r0) + qmul(c[6], x) + qmul(c[5], r1);
            s1v = qmul(x, c[2]) + qmul(c[0], r0) - qmul(c[1], r1);
            s2v = qmul(c[1], r0) + qmul(c[0], r1);
            r0 = qmul(s1v, r_clip);
            r1 = qmul(s2v, r_clip);
            c[7] = sat32(c[7] + dc[7]);
            r_clip = maxs(32'sd209715, ONE - qmul(c[7], qmul(y, y)));
          end
          32'd2: begin
            // IIR12Bquad: interleaved coefficient reloads (K/Q/V order)
            f2v = qmul(c[3], x) - qmul(c[1], r1);
            c[1] = sat32(c[1] + dc[1]);
            c[3] = sat32(c[3] + dc[3]);
            g2v = qmul(c[1], x) + qmul(c[3], r1);
            f1v = qmul(c[2], f2v) - qmul(c[0], r0);
            c[0] = sat32(c[0] + dc[0]);
            c[2] = sat32(c[2] + dc[2]);
            g1v = qmul(c[0], f2v) + qmul(c[2], r0);
            c[4] = sat32(c[4] + dc[4]);
            c[5] = sat32(c[5] + dc[5]);
            c[6] = sat32(c[6] + dc[6]);
            y = qmul(c[6], g2v) + qmul(c[5], g1v) + qmul(c[4], f1v);
            r0 = qmul(f1v, r_clip);
            r1 = qmul(g1v, r_clip);
            c[7] = sat32(c[7] + dc[7]);
            r_clip = maxs(32'sd209715, ONE - qmul(c[7], qmul(y, y)));
          end
          default: begin
            // 32'd0: SVFLP12Aquad
            c[0] = sat32(c[0] + dc[0]);
            c[1] = sat32(c[1] + dc[1]);
            low  = r1 + qmul(c[0], r0);
            high = x - low - qmul(c[1], r0);
            band = r0 + qmul(c[0], high);
            low2  = low + qmul(c[0], band);
            high2 = x - low2 - qmul(c[1], band);
            band2 = band + qmul(c[0], high2);
            r0 = qmul(band2, r_clip);
            r1 = qmul(low2, r_clip);
            c[2] = sat32(c[2] + dc[2]);
            r_clip = maxs(32'sd209715, ONE - qmul(c[2], qmul(band, band)));
            c[3] = sat32(c[3] + dc[3]);
            y = qmul(low2, c[3]);
          end
        endcase
        $fwrite(fd, "Y %0d %0d %0d\n", b, k, y);
      end
      $fwrite(fd, "T %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
              b, subtype, r0, r1, r_clip,
              c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]);
    end
    $fclose(fd);
    $display("DONE qmuls=%0d blocks=%0d inputs=%0d", qmul_count, n_blocks, ii);
    $finish;
  end

endmodule
