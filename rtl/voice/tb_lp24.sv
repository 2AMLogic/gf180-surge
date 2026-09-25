// SXT-038 RTL filter leaf: LP 24 dB unit — all three engine subtypes,
// implementing the SAME frozen integer schedule as the fixed-point model
// (model/voice/filter_lp24/filter_lp24_model.py).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared checkpoint; enforced by
// tools/compare_rtl_model_lp24.py).  NOT synthesis-closed, NOT timing-closed;
// no gf180mcu / FPGA area, timing, power or hardware-playback claim.
//
// Structure citations (read, never copied): surge@58914e59, submodule
// sst-filters@e92d93a9
//   QuadFilterUnit_Impl.h  SVFLP24Aquad / IIR24CFCquad / IIR24Bquad — the two
//     cascaded sections, the per-sample C[i] += dC[i] reload order, the
//     register indices, and which R slot each subtype uses for clipgain
//     (R[2] for the SVF and coupled-form kernels, R[4] for the lattice)
//   QuadFilterUnit.h       GetQFPtrFilterUnit: fut_lp24 subtype -> kernel
//   SurgeVoice.cpp         per-voice FBP zero-init and the type/subtype-change
//                          reset path; per-block C copy-back (GetQFB)
//
// Stimulus (declared control-plane boundary; emitted by
// model/voice/filter_lp24/run_filter_leg.py from the frozen model):
//   init.hex  [n_blocks]
//   ctrl.hex  per block, 18 words: flags(b0 active, b1 reset), subtype,
//             C[8] block-start, dC[8]
//   in.hex    64 input words per block
//
// Trace (tb_trace.txt): one "Y" line per output sample, one "T" line per
// block checkpoint (end-of-block registers R[0..4] + coefficients C[0..7]).
`timescale 1ns/1ps

module tb_lp24;

  localparam int FQ = 21;
  localparam logic signed [31:0] ONE  = 32'sd2097152;   // 1.0 in Q10.21
  localparam logic signed [31:0] CLIP = 32'sd209715;    // 0.1 in Q10.21 (pinned floor)

  int unsigned qmul_count = 0;

  // Round-half-up Q10.21 multiply, saturating to signed 32 bits.
  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << 20)) >>> 21;
    if      (r > 64'sd2147483647)  qmul = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  // Saturating signed-32 sum (the model's `sadd`): every audio-path sum has
  // defined overflow behaviour so model and RTL agree bit for bit.
  function automatic signed [31:0] sat32(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = v[31:0];
  endfunction

  function automatic signed [31:0] maxs(input signed [31:0] a, input signed [31:0] b);
    maxs = ($signed(a) > $signed(b)) ? a : b;
  endfunction

  logic [31:0] cfg      [0:0];
  logic [31:0] ctrl_mem [0:8000000];
  logic [31:0] in_mem   [0:8000000];

  // per-instance filter state (engine FBP semantics: all registers start at 0)
  logic signed [31:0] r [0:4];
  integer fd;
  integer ci, ii, b, k, i, n_blocks;
  logic [31:0] flags, subtype;
  logic signed [31:0] c  [0:7];
  logic signed [31:0] dc [0:7];
  logic signed [31:0] x, yout, y1, y2, low, high, band, xin, f1v, f2v, g1v, g2v;
  logic signed [31:0] s1v, s2v, s3v, s4v;

  initial begin
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ctrl.hex", ctrl_mem);
    $readmemh("rtl/in.hex",   in_mem);
    fd = $fopen("tb_trace.txt", "w");
    n_blocks = int'(cfg[0]);
    ci = 0; ii = 0;
    for (i = 0; i < 5; i++) r[i] = 0;        // FBP zero-init
    for (b = 0; b < n_blocks; b++) begin
      flags   = ctrl_mem[ci + 0];
      subtype = ctrl_mem[ci + 1];
      for (i = 0; i < 8; i++) c[i]  = 32'(ctrl_mem[ci + 2 + i]);
      for (i = 0; i < 8; i++) dc[i] = 32'(ctrl_mem[ci + 10 + i]);
      ci = ci + 18;
      if (!flags[0]) $fatal(1, "inactive block record");
      if (flags[1]) begin
        for (i = 0; i < 5; i++) r[i] = 0;    // voice creation / subtype change
      end
      for (k = 0; k < 64; k++) begin
        x = 32'(in_mem[ii]); ii = ii + 1;
        case (subtype)
          32'd1: begin
            // IIR24CFCquad: two cascaded coupled-form sections, one clipgain
            // register R[2] whose PREVIOUS value scales both state updates.
            for (i = 0; i < 8; i++)
              if (i != 3 && i != 7) c[i] = sat32(c[i] + dc[i]);
            y1  = sat32(64'(qmul(c[4], r[0])) + 64'(qmul(c[6], x)) + 64'(qmul(c[5], r[1])));
            s1v = sat32(64'(qmul(x, c[2])) + 64'(qmul(c[0], r[0])) - 64'(qmul(c[1], r[1])));
            s2v = sat32(64'(qmul(c[1], r[0])) + 64'(qmul(c[0], r[1])));
            r[0] = qmul(s1v, r[2]);
            r[1] = qmul(s2v, r[2]);
            y2  = sat32(64'(qmul(c[4], r[3])) + 64'(qmul(c[6], y1)) + 64'(qmul(c[5], r[4])));
            s3v = sat32(64'(qmul(y1, c[2])) + 64'(qmul(c[0], r[3])) - 64'(qmul(c[1], r[4])));
            s4v = sat32(64'(qmul(c[1], r[3])) + 64'(qmul(c[0], r[4])));
            r[3] = qmul(s3v, r[2]);
            r[4] = qmul(s4v, r[2]);
            c[7] = sat32(c[7] + dc[7]);
            r[2] = maxs(CLIP, sat32(64'(ONE) - 64'(qmul(c[7], qmul(y2, y2)))));
            yout = y2;
          end
          32'd2: begin
            // IIR24Bquad: two cascaded normalized-lattice sections; the
            // clipgain register is R[4]; all coefficient reloads precede the
            // sample (pinned order K2, Q2, K1, Q1, V1, V2, V3).
            c[1] = sat32(c[1] + dc[1]);
            c[3] = sat32(c[3] + dc[3]);
            c[0] = sat32(c[0] + dc[0]);
            c[2] = sat32(c[2] + dc[2]);
            c[4] = sat32(c[4] + dc[4]);
            c[5] = sat32(c[5] + dc[5]);
            c[6] = sat32(c[6] + dc[6]);
            f2v = sat32(64'(qmul(c[3], x)) - 64'(qmul(c[1], r[1])));
            g2v = sat32(64'(qmul(c[1], x)) + 64'(qmul(c[3], r[1])));
            f1v = sat32(64'(qmul(c[2], f2v)) - 64'(qmul(c[0], r[0])));
            g1v = sat32(64'(qmul(c[0], f2v)) + 64'(qmul(c[2], r[0])));
            r[0] = qmul(f1v, r[4]);
            r[1] = qmul(g1v, r[4]);
            y1 = sat32(64'(qmul(c[6], g2v)) + 64'(qmul(c[5], g1v)) + 64'(qmul(c[4], f1v)));
            f2v = sat32(64'(qmul(c[3], y1)) - 64'(qmul(c[1], r[3])));
            g2v = sat32(64'(qmul(c[1], y1)) + 64'(qmul(c[3], r[3])));
            f1v = sat32(64'(qmul(c[2], f2v)) - 64'(qmul(c[0], r[2])));
            g1v = sat32(64'(qmul(c[0], f2v)) + 64'(qmul(c[2], r[2])));
            r[2] = qmul(f1v, r[4]);
            r[3] = qmul(g1v, r[4]);
            y2 = sat32(64'(qmul(c[6], g2v)) + 64'(qmul(c[5], g1v)) + 64'(qmul(c[4], f1v)));
            c[7] = sat32(c[7] + dc[7]);
            r[4] = maxs(CLIP, sat32(64'(ONE) - 64'(qmul(c[7], qmul(y2, y2)))));
            yout = y2;
          end
          default: begin
            // 32'd0: SVFLP24Aquad — two cascaded zero-delay-feedback SVF
            // sections; clipgain R[2] is updated from the SECOND section's
            // band signal, and the output is the SECOND section's low.
            c[0] = sat32(c[0] + dc[0]);
            c[1] = sat32(c[1] + dc[1]);
            low  = sat32(64'(r[1]) + 64'(qmul(c[0], r[0])));
            high = sat32(64'(x) - 64'(low) - 64'(qmul(c[1], r[0])));
            band = sat32(64'(r[0]) + 64'(qmul(c[0], high)));
            low  = sat32(64'(low) + 64'(qmul(c[0], band)));
            high = sat32(64'(x) - 64'(low) - 64'(qmul(c[1], band)));
            band = sat32(64'(band) + 64'(qmul(c[0], high)));
            r[0] = qmul(band, r[2]);
            r[1] = qmul(low, r[2]);
            xin  = low;
            low  = sat32(64'(r[4]) + 64'(qmul(c[0], r[3])));
            high = sat32(64'(xin) - 64'(low) - 64'(qmul(c[1], r[3])));
            band = sat32(64'(r[3]) + 64'(qmul(c[0], high)));
            low  = sat32(64'(low) + 64'(qmul(c[0], band)));
            high = sat32(64'(xin) - 64'(low) - 64'(qmul(c[1], band)));
            band = sat32(64'(band) + 64'(qmul(c[0], high)));
            r[3] = qmul(band, r[2]);
            r[4] = qmul(low, r[2]);
            c[2] = sat32(c[2] + dc[2]);
            r[2] = maxs(CLIP, sat32(64'(ONE) - 64'(qmul(c[2], qmul(band, band)))));
            c[3] = sat32(c[3] + dc[3]);
            yout = qmul(low, c[3]);
          end
        endcase
        $fwrite(fd, "Y %0d %0d %0d\n", b, k, yout);
      end
      $fwrite(fd, "T %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
              b, subtype, r[0], r[1], r[2], r[3], r[4],
              c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]);
    end
    $fclose(fd);
    $display("DONE qmuls=%0d blocks=%0d inputs=%0d", qmul_count, n_blocks, ii);
    $finish;
  end

endmodule
