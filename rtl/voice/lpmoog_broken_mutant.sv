// SXT-039 NEGATIVE CONTROL (committed, must FAIL).
//
// This file is rtl/voice/tb_lpmoog.sv with EXACTLY ONE constant mutated: the
// round-half-up bias of the coefficient product (1 << (CFQ-1) -> 1 << (CFQ-2)),
// i.e. rounding at 1/4 LSB instead of 1/2 LSB.  It must FAIL the
// RTL-vs-model exactness comparison (tools/compare_rtl_model_lpmoog.py) while
// the clean testbench passes on the same stimulus.  A control that stops
// failing is a broken control, not a success.
// SXT-039 RTL filter leaf: LP Legacy Ladder unit — all four engine-declared
// subtypes, implementing the SAME frozen integer schedule as the fixed-point
// model (model/voice/filter_lpmoog/filter_lpmoog_model.py).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared checkpoint; enforced by
// tools/compare_rtl_model_lpmoog.py). NOT synthesis-closed, NOT timing-closed;
// no gf180mcu/FPGA synthesis, area, timing or hardware-playback claim of any
// kind.
//
// Structure citations (read, not copied): surge@58914e59
//   sst-filters QuadFilterUnit_Impl.h  LPMOOGquad<subtype> (per-sample
//     C[0..2] += dC[0..2] reload, the softclipped first stage, the three
//     trailing one-pole stages, the R[3]/R[4] feedback pair, and the
//     subtype output tap R[subtype])
//   sst-filters QuadFilterUnit.h       fut_lpmoog subtype -> kernel table
//   sst-basic-blocks Clippers.h        softclip8_ps (+/-12 clamp, cubic term)
//   SurgeVoice.cpp                     per-voice FBP zero-init (all five
//                                      registers start at 0) and the
//                                      type/subtype-change reset path
//
// Frozen words: samples and registers Q10.21; coefficient plane (C, dC)
// Q2.29; softclip8 cubic coefficient Q0.40 with a Q1.31 first product.
//
// Stimulus (declared control-plane boundary; emitted by
// model/voice/filter_lpmoog/run_filter_leg.py from the frozen model):
//   init.hex  [n_blocks]
//   ctrl.hex  per block, 18 words: flags(b0 active, b1 reset), subtype,
//             C[8] block-start (Q2.29), dC[8] (Q2.29)
//   in.hex    64 input words per block (Q10.21)
//
// Trace (tb_trace.txt): one "Y" line per output sample, one "T" line per
// block checkpoint (end-of-block registers R[0..4] + coefficients C[0..7]).
`timescale 1ns/1ps

module tb_lpmoog;   // MUTANT BUILD (see header)

  localparam int FQ = 21;            // sample / register word
  localparam int CFQ = 29;           // coefficient word
  localparam int SC_A_FRAC = 40;     // softclip8 cubic coefficient word
  localparam int SC_T_FRAC = 31;     // softclip8 first-product word

  localparam logic signed [31:0] SC_LIMIT = 32'sd25165824;    // 12.0 Q10.21
  localparam logic signed [31:0] SC_A     = -32'sd318145726;  // -4/27/8^3 Q0.40

  int unsigned qmul_count = 0;

  // Q10.21 x Q2.29 -> Q10.21 (coefficient product), round-half-up, saturated
  function automatic signed [31:0] qmulc(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << (CFQ - 2))) >>> CFQ;   // MUTATION: round bias 1/2 -> 1/4 LSB
    if      (r > 64'sd2147483647)  qmulc = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmulc = -32'sd2147483648;
    else                           qmulc = r[31:0];
  endfunction

  // Q10.21 x Q10.21 -> Q10.21, round-half-up, saturated
  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << (FQ - 1))) >>> FQ;
    if      (r > 64'sd2147483647)  qmul = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  function automatic signed [31:0] sat32(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = v[31:0];
  endfunction

  // pinned softclip8_ps in the frozen words: clamp +/-12, then
  // y = x + ((x * a) * x^2) with the a-product held at Q1.31
  function automatic signed [31:0] softclip8(input signed [31:0] v);
    logic signed [31:0] x, xx;
    logic signed [63:0] p, t1, t2;
    if      (v >  SC_LIMIT) x =  SC_LIMIT;
    else if (v < -SC_LIMIT) x = -SC_LIMIT;
    else                    x = v;
    xx = qmul(x, x);
    qmul_count = qmul_count + 2;                  // the two scaling products
    p  = x * SC_A;
    t1 = (p + (64'sd1 << (FQ + SC_A_FRAC - SC_T_FRAC - 1)))
         >>> (FQ + SC_A_FRAC - SC_T_FRAC);
    p  = t1 * xx;
    t2 = (p + (64'sd1 << (SC_T_FRAC - 1))) >>> SC_T_FRAC;
    softclip8 = sat32(t2 + x);
  endfunction

  logic [31:0] cfg  [0:0];
  logic [31:0] ctrl_mem [0:8000000];
  logic [31:0] in_mem   [0:8000000];

  // per-instance ladder state (engine FBP semantics: all registers start 0)
  logic signed [31:0] r [5];
  integer fd;
  integer ci, ii, b, k, i, n_blocks;
  logic [31:0] flags, subtype;
  logic signed [31:0] c [8];
  logic signed [31:0] dc [8];
  logic signed [31:0] x, y, fb, drive;

  initial begin
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ctrl.hex", ctrl_mem);
    $readmemh("rtl/in.hex",   in_mem);
    fd = $fopen("tb_trace.txt", "w");
    n_blocks = int'(cfg[0]);
    ci = 0; ii = 0;
    for (i = 0; i < 5; i++) r[i] = 0;         // FBP zero-init
    for (b = 0; b < n_blocks; b++) begin
      flags   = ctrl_mem[ci + 0];
      subtype = ctrl_mem[ci + 1];
      for (i = 0; i < 8; i++) c[i]  = 32'(ctrl_mem[ci + 2 + i]);
      for (i = 0; i < 8; i++) dc[i] = 32'(ctrl_mem[ci + 10 + i]);
      ci = ci + 18;
      if (!flags[0]) $fatal(1, "inactive block record");
      if (flags[1]) begin
        for (i = 0; i < 5; i++) r[i] = 0;     // voice creation / subtype change
      end
      if (subtype > 32'd3) $fatal(1, "subtype %0d outside the declared set", subtype);
      for (k = 0; k < 64; k++) begin
        x = 32'(in_mem[ii]); ii = ii + 1;
        c[0] = sat32(c[0] + dc[0]);
        c[1] = sat32(c[1] + dc[1]);
        c[2] = sat32(c[2] + dc[2]);
        fb    = sat32(r[3] + r[4]);
        drive = sat32(sat32(qmulc(x, c[0]) - qmulc(fb, c[2])) - r[0]);
        r[0]  = softclip8(sat32(r[0] + qmulc(drive, c[1])));
        r[1]  = sat32(r[1] + qmulc(sat32(r[0] - r[1]), c[1]));
        r[2]  = sat32(r[2] + qmulc(sat32(r[1] - r[2]), c[1]));
        r[4]  = r[3];
        r[3]  = sat32(r[3] + qmulc(sat32(r[2] - r[3]), c[1]));
        y = r[subtype];
        $fwrite(fd, "Y %0d %0d %0d\n", b, k, y);
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
