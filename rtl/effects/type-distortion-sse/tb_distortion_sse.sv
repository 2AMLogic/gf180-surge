// SXT-028e-sse RTL behavioral schedule: Distortion, SSE quad-waveshaper
// branch (FX waveshaper Model indices 3..7).
//
// Reproduces the frozen fixed-point model
// (model/effects/type-distortion-sse/{sse_tables,quad_shapers,
// distortion_sse_model}.py) EXACTLY at declared checkpoints and on every
// per-instance output sample. All audio-rate arithmetic is computed here in
// the frozen conventions (exact products, round-half-up, saturating two's
// complement). Block-rate quantities (drive/outgain RAW lipol targets, the
// feedback coefficient, the four biquad coefficient target sets, and the
// activity/model flags) are CONTROL-PLANE: streamed from <case>_ctrl.hex.
//
// The shared Distortion chain -- pre/post peak EQ, the two instantized
// oversampled LP2B stages, the feedback recurrence, the drive/outgain lipol
// ramps, the two-stage halfband decimation, the ringout fade -- is REUSED
// UNCHANGED from SXT-028e's rtl/effects/type-distortion/tb_distortion.sv.
// Only the shaper step differs.
//
// WHAT THIS LEAF ADDS, AND COMPUTES HERE RATHER THAN STREAMING:
//   * the per-instance QuadWaveshaperState (n_waveshaper_registers = 4
//     registers x 2 modelled SIMD lanes, plus the per-lane `init` mask) --
//     checkpointed state, never pooled (the mutant-wsshared control pools it
//     and must FAIL);
//   * the `1/dNow` pre-scale, SKIPPED for wst_digital (`skipDriveNorm`);
//   * the per-oversample drive interpolation `dNow += dD` with
//     dD = (dE - dS) / (BLOCK_SIZE * dist_OS_bits) = /64 -- NOT /128; the
//     mutant-drivestep128 control "corrects" it and must FAIL;
//   * the zero-input DC-offset probe: the shaper evaluated on a THROW-AWAY
//     zeroed QuadWaveshaperState (instance slot 2 here) at drive dS, whose
//     lane-0 result is subtracted from every output sample of the block.
//     The mutant-dcprobe-live control runs it on the live state and must
//     FAIL; the mutant-nodcoffset control drops the subtraction entirely.
//
// Distortion owns NO delay-line-class buffer: there is no external memory in
// this slice at all.
//
// CONSTANTS. Per DR-0002 clause 1 (extended by DR-0012 and DR-0014) the RTL
// carries no independent copy of engine data: the twelve halfband allpass
// coefficients AND the eleven designed shaper scalars (the OJD breakpoints
// and its two denominators, the TANH rational's 9 and 27, the ADAA
// tolerance, the DC-blocker pole) are streamed through INITFILE. The two
// waveshaper ROM rows (wst_sine 1024 words, FuzzTable<1> 1025 words, Q2.29)
// are loaded from ws_sse_q29.hex, a build product of
// model/effects/type-distortion-sse/sse_tables.py. Only structural powers of
// two (1.0, 0.5, 512.0, 0.0625, N/2, N-1) are localparams here.
//
// Wiring (plusargs):
//   +NINST=1|2      instances driven per block (independent state)
//   +NBLOCKS=n      blocks
//   +RENDER0=b      first render block (outputs traced from here)
//   +RESETAT=b      optional: core reset before block b (fx-rebuild/panic)
//   +INFILE / +CTRLFILE / +INITFILE / +WSROM / +TRACE / +REV
//
// INITFILE layout: 12 x Q24.43 halfband coefficients (hr_a A[3], hr_a B[3],
//   hr_b A[3], hr_b B[3]); then per instance 2 x Q13.18 words (the plain
//   setvars(true) drive/outgain lipol targets); then 11 shaper scalars:
//   [16] OJD -1.7  [17] OJD 1.1  [18] OJD -0.3  [19] OJD 0.9
//   [20] OJD denLow  [21] OJD denHigh  [22] TANH 9 (Q24.43)
//   [23] TANH 27 (Q24.43)  [24] TANH 27 (Q40.23)  [25] ADAA tol
//   [26] dcBlock fac
`timescale 1ns/1ps

module tb_distortion_sse;
    integer NINST, N_BLOCKS, RENDER0, RESETAT, DEBUG;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, init_name, ws_name, rev_name;

    localparam integer BLOCKN  = 32;
    localparam integer OSN     = 128;        // BLOCK << dist_OS_bits
    localparam integer STAGES  = 3;          // HalfRateFilter M = 3
    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;   // 0.004  Q24.43
    localparam signed [63:0] DLPI_r = 64'sh000007F7CED91687;  // 0.996  Q24.43
    localparam integer ONE_A = 1 << 21;

    // structural (non-designed) fixed-point constants, Q24.43
    localparam signed [63:0] ONE_C   = 64'sd8796093022208;      // 1.0
    localparam signed [63:0] HALF_C  = 64'sd4398046511104;      // 0.5
    localparam signed [63:0] C512_C  = 64'sd4503599627370496;   // 512.0
    localparam signed [63:0] C16INV_C = 64'sd549755813888;      // 0.0625
    localparam signed [63:0] PM1_DX_C = 64'sd4503599627370496;  // N/2 = 512
    localparam signed [63:0] PM1_UB_C = 64'sd8998403161718784;  // N-1 = 1023

    // waveshaper ROM: [0..1023] wst_sine, [1024..2048] FuzzTable<1>
    localparam integer SINE_BASE = 0;
    localparam integer FUZZ_BASE = 1024;
    reg [31:0] wsrom [0:2048];

    // streamed init words (see INITFILE layout above)
    reg [63:0] initwords [0:31];

    // ---------------- per-instance state (shared #57 chain) ----------------
    reg signed [63:0] b1_lag [0:1][0:4]; reg signed [63:0] b1_tgt [0:1][0:4];
    reg signed [63:0] b2_lag [0:1][0:4]; reg signed [63:0] b2_tgt [0:1][0:4];
    reg signed [63:0] b1_r0 [0:1][0:1];  reg signed [63:0] b1_r1 [0:1][0:1];
    reg signed [63:0] b2_r0 [0:1][0:1];  reg signed [63:0] b2_r1 [0:1][0:1];
    integer b_first [0:1];
    reg signed [63:0] l1_c [0:1][0:4];   reg signed [63:0] l2_c [0:1][0:4];
    reg signed [63:0] l1_r0 [0:1][0:1];  reg signed [63:0] l1_r1 [0:1][0:1];
    reg signed [63:0] l2_r0 [0:1][0:1];  reg signed [63:0] l2_r1 [0:1][0:1];
    reg signed [63:0] hx [0:1][0:1][0:1][0:1][0:2][0:2];
    reg signed [63:0] hy [0:1][0:1][0:1][0:1][0:2][0:2];
    reg signed [31:0] dr_cur [0:1]; reg signed [31:0] dr_tgt [0:1];
    reg signed [31:0] dr_raw [0:1];                     // dE (this block)
    reg signed [31:0] og_cur [0:1]; reg signed [31:0] og_tgt [0:1];
    reg signed [31:0] fbl [0:1];    reg signed [31:0] fbr [0:1];
    reg signed [31:0] fbq [0:1];
    integer lp1on [0:1], lp2on [0:1], wsm [0:1];

    // ---------------- per-instance QuadWaveshaperState ---------------------
    // index 0/1 are the two live instances; index 2 is the THROW-AWAY probe
    // state of the DC-offset measurement (never the live one).
    reg signed [63:0] wsR [0:2][0:3][0:1];
    reg               wsI [0:2][0:1];

    // block-local SSE-branch quantities (recomputed per block per instance)
    reg signed [63:0] dnow, dd_step, dcoff;
    reg signed [63:0] dnow_end [0:1];
    reg signed [63:0] dcoff_blk [0:1];

    integer ilw [0:1][0:31];
    integer irw [0:1][0:31];
    integer out_l [0:31];
    integer out_r [0:31];
    integer wk_l [0:31];
    integer wk_r [0:31];
    integer bufl [0:127];
    integer bufr [0:127];

    integer tap_capture;
    integer xt [0:3][0:3][0:1];

    integer b, k, s_, j, ii, t_, chk, nn, ch, m_;
    reg signed [63:0] v64;
    reg signed [31:0] v32;

    // ---------------- fixed-point helpers ----------------
    function automatic signed [31:0] sat32(input signed [63:0] v);
        if (v > $signed(64'sd2147483647)) sat32 = 32'sd2147483647;
        else if (v < $signed(-64'sd2147483648)) sat32 = 32'sh80000000;
        else sat32 = v[31:0];
    endfunction

    localparam signed [127:0] S64MAX = (128'sd1 <<< 63) - 128'sd1;
    localparam signed [127:0] S64MIN = -(128'sd1 <<< 63);

    function automatic signed [63:0] sat64(input signed [127:0] v);
        if (v > S64MAX) sat64 = S64MAX[63:0];
        else if (v < S64MIN) sat64 = S64MIN[63:0];
        else sat64 = v[63:0];
    endfunction

    function automatic signed [127:0] ext128(input signed [63:0] a);
        ext128 = {{64{a[63]}}, a};
    endfunction

    function automatic signed [63:0] qadd64(input signed [63:0] a, input signed [63:0] b_);
        qadd64 = sat64(ext128(a) + ext128(b_));
    endfunction

    function automatic signed [63:0] qsub64(input signed [63:0] a, input signed [63:0] b_);
        qsub64 = sat64(ext128(a) - ext128(b_));
    endfunction

    // Q24.43 x Q24.43 -> Q24.43, round-half-up, saturating
    function automatic signed [63:0] qmul_cc(input signed [63:0] a, input signed [63:0] b_);
        reg signed [127:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_cc = sat64((p + $signed(128'sd4398046511104)) >>> 43);
        end
    endfunction

    // Q24.43 x Q24.43 -> Q40.23 (the TANH numerator/denominator widening)
    function automatic signed [63:0] qmul_cs(input signed [63:0] a, input signed [63:0] b_);
        reg signed [127:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_cs = sat64((p + (128'sd1 <<< 62)) >>> 63);
        end
    endfunction

    // Q40.23 x Q24.43 -> Q24.43
    function automatic signed [63:0] qmul_sc(input signed [63:0] a, input signed [63:0] b_);
        reg signed [127:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_sc = sat64((p + $signed(128'sd4194304)) >>> 23);
        end
    endfunction

    // 1 / b for a Q(fb) input, result Q(fq); SH = fb + fq. Round-half-up on
    // magnitude, saturating. (Model DD-2: the engine uses the SSE rcp_ps
    // ESTIMATE here; this is the exact reciprocal on both sides.)
    function automatic signed [63:0] frecip_g(input signed [63:0] b_, input integer SH);
        reg signed [127:0] num, nb, v;
        begin
            if (b_ == 0) frecip_g = 64'sh7FFFFFFFFFFFFFFF;
            else begin
                num = 128'sd1 <<< SH;
                if (b_ > 0) begin
                    nb = ext128(b_);
                    v = (2*num + nb) / (2*nb);
                end else begin
                    nb = -ext128(b_);
                    v = -((2*num + nb) / (2*nb));
                end
                frecip_g = sat64(v);
            end
        end
    endfunction

    // _mm_cvtps_epi32 on a Q24.43 word: round-half-to-EVEN, then the SSE
    // out-of-range rule (result is INT32_MIN, the "integer indefinite" value).
    function automatic integer cvt_i32_c(input signed [63:0] v);
        reg signed [63:0] n, r;
        begin
            n = v >>> 43;
            r = v - (n <<< 43);
            if (r > HALF_C) n = n + 64'sd1;
            else if (r == HALF_C && (n & 64'sd1)) n = n + 64'sd1;
            if (n > 64'sd2147483647 || n < -64'sd2147483648) cvt_i32_c = -2147483648;
            else cvt_i32_c = n[31:0];
        end
    endfunction

    // integer -> Q24.43, saturating (cvtepi32_ps into the shaper domain)
    function automatic signed [63:0] i2c(input integer v);
        i2c = sat64($signed({{96{v[31]}}, v}) <<< 43);
    endfunction

    // _mm_packs_epi32: saturating int32 -> int16
    function automatic integer packs16(input integer e);
        if (e > 32767) packs16 = 32767;
        else if (e < -32768) packs16 = -32768;
        else packs16 = e;
    endfunction

    // Q2.29 ROM word -> Q24.43
    function automatic signed [63:0] rom_c(input integer idx);
        reg signed [63:0] w;
        begin
            w = $signed({{32{wsrom[idx][31]}}, wsrom[idx]});
            rom_c = sat64(ext128(w) <<< 14);
        end
    endfunction

    function automatic signed [31:0] qadd32(input signed [31:0] a, input signed [31:0] b_);
        qadd32 = sat32($signed({{32{a[31]}}, a}) + $signed({{32{b_[31]}}, b_}));
    endfunction

    // Q13.18 x Q10.21 -> Q10.21
    function automatic signed [31:0] qmul_ga(input signed [31:0] a, input signed [31:0] b_);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_ga = sat32((p + $signed(64'sd131072)) >>> 18);
        end
    endfunction

    // Q13.18 x Q13.18 -> Q13.18
    function automatic signed [31:0] qmul_gg(input signed [31:0] a, input signed [31:0] b_);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_gg = sat32((p + $signed(64'sd131072)) >>> 18);
        end
    endfunction

    // Q10.21 x Q10.21 -> Q10.21
    function automatic signed [31:0] qmul_aa(input signed [31:0] a, input signed [31:0] b_);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_aa = sat32((p + $signed(64'sd1048576)) >>> 21);
        end
    endfunction

    // Q10.21 audio word -> Q24.43 shaper word
    function automatic signed [63:0] a2c(input signed [31:0] a);
        a2c = sat64(ext128($signed({{32{a[31]}}, a})) <<< 22);
    endfunction

    // Q24.43 shaper word -> Q10.21 audio word, round-half-up, saturating
    function automatic signed [31:0] c2a(input signed [63:0] v);
        c2a = sat32((ext128(v) + $signed(128'sd2097152)) >>> 22);
    endfunction

    function automatic signed [31:0] lip_val(input signed [31:0] cur,
                                             input signed [31:0] tgt,
                                             input integer kk);
        reg signed [63:0] d;
        begin
            d = $signed({{32{tgt[31]}}, tgt}) - $signed({{32{cur[31]}}, cur});
            if (d >= 0)
                lip_val = sat32($signed({{32{cur[31]}}, cur}) + ((d * (kk+1) + 16) >>> 5));
            else
                lip_val = sat32($signed({{32{cur[31]}}, cur}) - (((-d) * (kk+1) + 16) >>> 5));
        end
    endfunction

    task automatic lip_smooth(inout signed [31:0] cur, inout signed [31:0] tgt,
                              input signed [31:0] f);
        reg signed [31:0] old_t;
        begin
            old_t = tgt;
            cur = old_t;
            tgt = qadd32(qmul_gg(32'sd65536, f), qmul_gg(32'sd196608, old_t));
        end
    endtask

    task automatic rd64(input integer fh, output [63:0] v);
        integer c;
        begin
            c = $fscanf(fh, "%x\n", v);
            if (c <= 0) begin
                $display("STIMULUS UNDERRUN");
                $finish;
            end
        end
    endtask

    // ---------------- peak-EQ biquad sample (lagged TDF2) ----------------
    task bq_sample(input integer inst, input integer which,
                   input integer inl, input integer inr,
                   output integer ol, output integer orr);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, il, ir, op, op2;
        begin
            if (which == 0) begin
                for (t_ = 0; t_ < 5; t_ = t_ + 1)
                    b1_lag[inst][t_] = qadd64(qmul_cc(b1_lag[inst][t_], DLPI_r),
                                              qmul_cc(b1_tgt[inst][t_], DLP_r));
                a1_ = b1_lag[inst][0]; a2_ = b1_lag[inst][1];
                b0_ = b1_lag[inst][2]; b1_ = b1_lag[inst][3]; b2_ = b1_lag[inst][4];
                il = $signed(inl) <<< 22;
                op = qadd64(qmul_cc(il, b0_), b1_r0[inst][0]);
                b1_r0[inst][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)),
                                        b1_r1[inst][0]);
                b1_r1[inst][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
                ir = $signed(inr) <<< 22;
                op2 = qadd64(qmul_cc(ir, b0_), b1_r0[inst][1]);
                b1_r0[inst][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)),
                                        b1_r1[inst][1]);
                b1_r1[inst][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            end else begin
                for (t_ = 0; t_ < 5; t_ = t_ + 1)
                    b2_lag[inst][t_] = qadd64(qmul_cc(b2_lag[inst][t_], DLPI_r),
                                              qmul_cc(b2_tgt[inst][t_], DLP_r));
                a1_ = b2_lag[inst][0]; a2_ = b2_lag[inst][1];
                b0_ = b2_lag[inst][2]; b1_ = b2_lag[inst][3]; b2_ = b2_lag[inst][4];
                il = $signed(inl) <<< 22;
                op = qadd64(qmul_cc(il, b0_), b2_r0[inst][0]);
                b2_r0[inst][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)),
                                        b2_r1[inst][0]);
                b2_r1[inst][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
                ir = $signed(inr) <<< 22;
                op2 = qadd64(qmul_cc(ir, b0_), b2_r0[inst][1]);
                b2_r0[inst][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)),
                                        b2_r1[inst][1]);
                b2_r1[inst][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            end
            ol = sat32((op + $signed(64'sd2097152)) >>> 22);
            orr = sat32((op2 + $signed(64'sd2097152)) >>> 22);
        end
    endtask

    // ---------------- instantized LP biquad sample (no lag step) ---------
    task lp_sample(input integer inst, input integer which,
                   input integer inl, input integer inr,
                   output integer ol, output integer orr);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, il, ir, op, op2;
        begin
            if (which == 0) begin
                a1_ = l1_c[inst][0]; a2_ = l1_c[inst][1];
                b0_ = l1_c[inst][2]; b1_ = l1_c[inst][3]; b2_ = l1_c[inst][4];
                il = $signed(inl) <<< 22;
                op = qadd64(qmul_cc(il, b0_), l1_r0[inst][0]);
                l1_r0[inst][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)),
                                        l1_r1[inst][0]);
                l1_r1[inst][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
                ir = $signed(inr) <<< 22;
                op2 = qadd64(qmul_cc(ir, b0_), l1_r0[inst][1]);
                l1_r0[inst][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)),
                                        l1_r1[inst][1]);
                l1_r1[inst][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            end else begin
                a1_ = l2_c[inst][0]; a2_ = l2_c[inst][1];
                b0_ = l2_c[inst][2]; b1_ = l2_c[inst][3]; b2_ = l2_c[inst][4];
                il = $signed(inl) <<< 22;
                op = qadd64(qmul_cc(il, b0_), l2_r0[inst][0]);
                l2_r0[inst][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)),
                                        l2_r1[inst][0]);
                l2_r1[inst][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
                ir = $signed(inr) <<< 22;
                op2 = qadd64(qmul_cc(ir, b0_), l2_r0[inst][1]);
                l2_r0[inst][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)),
                                        l2_r1[inst][1]);
                l2_r1[inst][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            end
            ol = sat32((op + $signed(64'sd2097152)) >>> 22);
            orr = sat32((op2 + $signed(64'sd2097152)) >>> 22);
        end
    endtask

    // ======================= quad waveshapers =============================
    // Streamed designed constants (INITFILE indices 16..26).
    function automatic signed [63:0] KC(input integer idx);
        KC = $signed(initwords[idx]);
    endfunction

    // SINUS_SSE2<false> -- FX model 3, wst_sine
    function automatic signed [63:0] sh_sinus(input signed [63:0] x_c,
                                              input signed [63:0] drv);
        reg signed [63:0] x, a, t0, t1;
        integer e_raw, e;
        begin
            x = qmul_cc(x_c, drv);
            x = qadd64(sat64(ext128(x) <<< 8), C512_C);     // *256 + 512
            e_raw = cvt_i32_c(x);
            a = qsub64(x, i2c(e_raw));                      // signed remainder
            e = packs16(e_raw);
            if (e < 0) e = 0;
            else if (e > 1022) e = 1022;                    // DO_FOLD == false
            t0 = rom_c(SINE_BASE + (e & 1023));
            t1 = rom_c(SINE_BASE + ((e + 1) & 1023));
            sh_sinus = qadd64(qmul_cc(qsub64(ONE_C, a), t0), qmul_cc(a, t1));
        end
    endfunction

    // DIGI_SSE2 -- FX model 4, wst_digital
    function automatic signed [63:0] sh_digi(input signed [63:0] x_c,
                                             input signed [63:0] drv);
        reg signed [63:0] invdrive, u, w;
        integer a;
        begin
            invdrive = frecip_g(drv, 86);                   // rcp_ps -- DD-2
            u = sat64(ext128(x_c) <<< 4);                   // m16 * in
            u = qmul_cc(invdrive, u);
            u = qadd64(u, HALF_C);                          // + mofs
            a = cvt_i32_c(u);
            w = qsub64(i2c(a), HALF_C);
            w = qmul_cc(C16INV_C, w);
            sh_digi = qmul_cc(drv, w);
        end
    endfunction

    // OJD -- FX model 5, wst_ojd
    function automatic signed [63:0] sh_ojd(input signed [63:0] x_c,
                                            input signed [63:0] drv);
        reg signed [63:0] x, xlow, xhi, v;
        begin
            x = qmul_cc(x_c, drv);
            if (x <= KC(16))            sh_ojd = -ONE_C;             // <= -1.7
            else if (x >= KC(17))       sh_ojd = ONE_C;              // >= 1.1
            else if (x < KC(18)) begin                               // < -0.3
                xlow = qsub64(x, KC(18));
                v = qadd64(xlow, qmul_cc(KC(20), qmul_cc(xlow, xlow)));
                sh_ojd = qadd64(v, KC(18));
            end else if (x > KC(19)) begin                           // > 0.9
                xhi = qsub64(x, KC(19));
                v = qsub64(xhi, qmul_cc(KC(21), qmul_cc(xhi, xhi)));
                sh_ojd = qadd64(v, KC(19));
            end else sh_ojd = x;
        end
    endfunction

    // CLIP (Saturators.h)
    function automatic signed [63:0] sh_clip(input signed [63:0] x_c,
                                             input signed [63:0] drv);
        reg signed [63:0] x;
        begin
            x = qmul_cc(x_c, drv);
            if (x > ONE_C) sh_clip = ONE_C;
            else if (x < -ONE_C) sh_clip = -ONE_C;
            else sh_clip = x;
        end
    endfunction

    // TANH (Saturators.h): clip(x*(27 + x^2) / (27 + 9x^2))
    function automatic signed [63:0] sh_tanh(input signed [63:0] x_c,
                                             input signed [63:0] drv);
        reg signed [63:0] x, xx, num_s, den_s, inv, y;
        begin
            x = qmul_cc(x_c, drv);
            xx = qmul_cc(x, x);
            num_s = qmul_cs(x, qadd64(KC(23), xx));
            den_s = qadd64(KC(24), qmul_cs(KC(22), xx));
            inv = frecip_g(den_s, 66);                      // rcp_ps -- DD-2
            y = qmul_sc(num_s, inv);
            if (y > ONE_C) sh_tanh = ONE_C;
            else if (y < -ONE_C) sh_tanh = -ONE_C;
            else sh_tanh = y;
        end
    endfunction

    // ADAA<fwrect_kernel, 0, 1, true> -- FX model 6, wst_fwrectify
    function automatic signed [63:0] sh_fwrect(input integer inst, input integer lane,
                                               input signed [63:0] x_c,
                                               input signed [63:0] drv);
        reg signed [63:0] x, f_val, adf, dx, dad, den, dxdiv, from_ad;
        reg ltt;
        begin
            x = sh_clip(x_c, drv);
            f_val = (x < 0) ? -x : x;
            adf = qmul_cc(f_val, qmul_cc(x, HALF_C));
            dx = qsub64(x, wsR[inst][0][lane]);
            dad = qsub64(adf, wsR[inst][1][lane]);
            ltt = ((dx < KC(25)) && (dx > -KC(25))) || wsI[inst][lane];
            den = ltt ? KC(25) : dx;
            dxdiv = frecip_g(den, 86);                      // rcp_ps -- DD-2
            from_ad = qmul_cc(dad, dxdiv);
            wsR[inst][0][lane] = x;
            wsR[inst][1][lane] = adf;
            wsI[inst][lane] = 1'b0;                         // updateInit == true
            sh_fwrect = ltt ? f_val : from_ad;
        end
    endfunction

    // WS_PM1_LUT<1024> over the FuzzTable<1> row (WaveshaperLUT.h)
    function automatic signed [63:0] pm1_lut(input signed [63:0] c);
        reg signed [63:0] x, xc, frac, t0, t1;
        integer e;
        begin
            x = qadd64(qmul_cc(c, PM1_DX_C), PM1_DX_C);
            xc = x;
            if (xc > PM1_UB_C) xc = PM1_UB_C;
            if (xc < 0) xc = 0;
            e = cvt_i32_c(xc);
            frac = qsub64(x, i2c(e));                       // NOTE: unclamped x
            e = packs16(e);
            t0 = rom_c(FUZZ_BASE + e);
            t1 = rom_c(FUZZ_BASE + e + 1);
            pm1_lut = qadd64(qmul_cc(qsub64(ONE_C, frac), t0), qmul_cc(frac, t1));
        end
    endfunction

    // TableEval<FuzzTable<1>, 1024, TANH> -- FX model 7, wst_fuzzsoft
    function automatic signed [63:0] sh_fuzzsoft(input integer inst, input integer lane,
                                                 input signed [63:0] x_c,
                                                 input signed [63:0] drv);
        reg signed [63:0] c, v, dx, filtval;
        begin
            c = sh_tanh(x_c, drv);
            v = pm1_lut(c);
            dx = qsub64(v, wsR[inst][0][lane]);             // dcBlock<0,1>
            filtval = qadd64(dx, qmul_cc(KC(26), wsR[inst][1][lane]));
            wsR[inst][0][lane] = v;
            wsR[inst][1][lane] = filtval;
            wsI[inst][lane] = 1'b0;
            sh_fuzzsoft = filtval;
        end
    endfunction

    // GetQuadWaveshaper(FXWaveShapers[model])
    function automatic signed [63:0] ws_quad(input integer inst, input integer lane,
                                             input integer model,
                                             input signed [63:0] x_c,
                                             input signed [63:0] drv);
        begin
            case (model)
                3: ws_quad = sh_sinus(x_c, drv);
                4: ws_quad = sh_digi(x_c, drv);
                5: ws_quad = sh_ojd(x_c, drv);
                6: ws_quad = sh_fwrect(inst, lane, x_c, drv);
                7: ws_quad = sh_fuzzsoft(inst, lane, x_c, drv);
                default: begin
                    $display("FATAL: FX model %0d is not in the SSE branch", model);
                    $finish;
                end
            endcase
        end
    endfunction

    task ws_zero(input integer slot, input integer first_sample);
        integer r_, l_;
        begin
            for (r_ = 0; r_ < 4; r_ = r_ + 1)
                for (l_ = 0; l_ < 2; l_ = l_ + 1)
                    wsR[slot][r_][l_] = 64'sd0;
            for (l_ = 0; l_ < 2; l_ = l_ + 1)
                wsI[slot][l_] = (first_sample != 0);
        end
    endtask

    // ---------------- halfband D2 (one stage pair, one instance) ---------
    function automatic signed [63:0] hb_cascade(input integer inst, input integer hw,
                                                input integer chh, input integer br,
                                                input signed [63:0] xin);
        reg signed [63:0] v, y, x1, y1;
        integer jj, ci;
        begin
            v = xin;
            for (jj = 0; jj < STAGES; jj = jj + 1) begin
                ci = hw * 6 + br * 3 + jj;
                x1 = hx[inst][hw][chh][br][jj][1];
                y1 = hy[inst][hw][chh][br][jj][1];
                y = qadd64(x1, qmul_cc($signed(initwords[ci]), qsub64(v, y1)));
                hx[inst][hw][chh][br][jj][2] = hx[inst][hw][chh][br][jj][1];
                hx[inst][hw][chh][br][jj][1] = hx[inst][hw][chh][br][jj][0];
                hx[inst][hw][chh][br][jj][0] = v;
                hy[inst][hw][chh][br][jj][2] = hy[inst][hw][chh][br][jj][1];
                hy[inst][hw][chh][br][jj][1] = hy[inst][hw][chh][br][jj][0];
                hy[inst][hw][chh][br][jj][0] = y;
                v = y;
            end
            hb_cascade = v;
        end
    endfunction

    reg signed [63:0] hb_a_tmp [0:127];
    reg signed [63:0] hb_b_tmp [0:127];

    task hb_process(input integer inst, input integer hw, input integer nsamp);
        reg signed [63:0] xw, ss;
        integer i2, m2;
        begin
            for (ch = 0; ch < 2; ch = ch + 1) begin
                for (i2 = 0; i2 < nsamp; i2 = i2 + 1) begin
                    xw = $signed(ch == 0 ? bufl[i2] : bufr[i2]) <<< 22;
                    hb_a_tmp[i2] = hb_cascade(inst, hw, ch, 0, xw);
                    hb_b_tmp[i2] = hb_cascade(inst, hw, ch, 1, xw);
                end
                for (m2 = 0; m2 < nsamp / 2; m2 = m2 + 1) begin
                    ss = qadd64(hb_b_tmp[2*m2], hb_a_tmp[2*m2 + 1]);
                    if (ss >= 0) ss = ss >>> 1; else ss = -((-ss) >>> 1);
                    if (ch == 0) bufl[m2] = sat32((ss + $signed(64'sd2097152)) >>> 22);
                    else          bufr[m2] = sat32((ss + $signed(64'sd2097152)) >>> 22);
                end
            end
        end
    endtask

    // ---------------- distortion block datapath (one instance) -----------
    task dist_block(input integer inst);
        integer ol, orr, idx, skipnorm;
        reg signed [31:0] g;
        reg signed [63:0] ds_c, dinv, sbl, sbr, o_l, o_r;
        begin
            // 1. band1 (pre-EQ)
            for (k = 0; k < BLOCKN; k = k + 1) begin
                bq_sample(inst, 0, ilw[inst][k], irw[inst][k], ol, orr);
                wk_l[k] = ol; wk_r[k] = orr;
            end
            // 2. SSE-branch control quantities.
            //    dS = the PREVIOUS lipol target (dr_cur after lip_smooth),
            //    dE = the RAW streamed drive word. dD = (dE - dS)/64 -- the
            //    /64 is exact from Q13.18 to Q24.43 (a left shift of 19).
            ds_c = sat64(ext128($signed({{32{dr_cur[inst][31]}}, dr_cur[inst]})) <<< 25);
            dd_step = sat64(ext128($signed({{32{dr_raw[inst][31]}}, dr_raw[inst]})
                                   - $signed({{32{dr_cur[inst][31]}}, dr_cur[inst]})) <<< 19);
            dnow = ds_c;
            // 3. the zero-input DC-offset probe, on the THROW-AWAY state
            ws_zero(2, 0);                    // probeState.R = 0, .init = 0
            dcoff = ws_quad(2, 0, wsm[inst], 64'sd0, ds_c);
            dcoff_blk[inst] = dcoff;
            skipnorm = (wsm[inst] == 4);      // skipDriveNorm: DIGITAL only
            // 4. drive ramp (in place)
            for (k = 0; k < BLOCKN; k = k + 1) begin
                g = lip_val(dr_cur[inst], dr_tgt[inst], k);
                wk_l[k] = qmul_ga(g, wk_l[k]);
                wk_r[k] = qmul_ga(g, wk_r[k]);
            end
            // 5. 4x oversampled feedback + quad-shaper loop
            for (k = 0; k < BLOCKN; k = k + 1) begin
                for (s_ = 0; s_ < 4; s_ = s_ + 1) begin
                    fbl[inst] = qadd32(wk_l[k], qmul_aa(fbq[inst], fbl[inst]));
                    fbr[inst] = qadd32(wk_r[k], qmul_aa(fbq[inst], fbr[inst]));
                    if (lp1on[inst] != 0) begin
                        lp_sample(inst, 0, fbl[inst], fbr[inst], ol, orr);
                        fbl[inst] = ol; fbr[inst] = orr;
                    end
                    if (skipnorm != 0) begin
                        sbl = a2c(fbl[inst]);
                        sbr = a2c(fbr[inst]);
                    end else begin
                        dinv = frecip_g(dnow, 86);
                        sbl = qmul_cc(a2c(fbl[inst]), dinv);
                        sbr = qmul_cc(a2c(fbr[inst]), dinv);
                    end
                    o_l = ws_quad(inst, 0, wsm[inst], sbl, dnow);
                    o_r = ws_quad(inst, 1, wsm[inst], sbr, dnow);
                    fbl[inst] = c2a(qsub64(o_l, dcoff));
                    fbr[inst] = c2a(qsub64(o_r, dcoff));
                    dnow = qadd64(dnow, dd_step);
                    if (lp2on[inst] != 0) begin
                        lp_sample(inst, 1, fbl[inst], fbr[inst], ol, orr);
                        fbl[inst] = ol; fbr[inst] = orr;
                    end
                    idx = s_ + (k << 2);
                    bufl[idx] = fbl[inst];
                    bufr[idx] = fbr[inst];
                    if (tap_capture != 0 && k < 4) begin
                        xt[k][s_][0] = fbl[inst];
                        xt[k][s_][1] = fbr[inst];
                    end
                end
            end
            dnow_end[inst] = dnow;
            // 6. two-stage halfband decimation 128 -> 64 -> 32
            hb_process(inst, 0, 128);
            hb_process(inst, 1, 64);
            // 7. outgain ramp + band2 (post-EQ)
            for (k = 0; k < BLOCKN; k = k + 1) begin
                g = lip_val(og_cur[inst], og_tgt[inst], k);
                out_l[k] = qmul_ga(g, bufl[k]);
                out_r[k] = qmul_ga(g, bufr[k]);
            end
            for (k = 0; k < BLOCKN; k = k + 1) begin
                bq_sample(inst, 1, out_l[k], out_r[k], ol, orr);
                out_l[k] = ol; out_r[k] = orr;
            end
        end
    endtask

    // ---------------- control-plane stream --------------------------------
    task apply_ctrl(input integer inst, input integer fh);
        integer j_;
        begin
            rd64(fh, v64); v32 = v64[31:0];
            dr_raw[inst] = $signed(v32);           // dE, before smoothing
            lip_smooth(dr_cur[inst], dr_tgt[inst], $signed(v32));
            rd64(fh, v64); v32 = v64[31:0];
            lip_smooth(og_cur[inst], og_tgt[inst], $signed(v32));
            rd64(fh, v64); fbq[inst] = $signed(v64[31:0]);
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); b1_tgt[inst][j_] = $signed(v64);
            end
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); b2_tgt[inst][j_] = $signed(v64);
            end
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); l1_c[inst][j_] = $signed(v64);
            end
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); l2_c[inst][j_] = $signed(v64);
            end
            rd64(fh, v64);
            lp1on[inst] = v64[0];
            lp2on[inst] = v64[1];
            wsm[inst] = (v64 >> 2) & 7;            // FX model 3..7
            if (b_first[inst] != 0) begin
                for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                    b1_lag[inst][j_] = b1_tgt[inst][j_];
                    b2_lag[inst][j_] = b2_tgt[inst][j_];
                end
                b_first[inst] = 0;
            end
        end
    endtask

    // ---------------- reset (engine fx-rebuild / panic semantics) ---------
    task do_reset;
        integer i_, j_, h_, c_, r_, t2_;
        begin
            for (i_ = 0; i_ < NINST; i_ = i_ + 1) begin
                for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                    b1_lag[i_][j_] = 0; b1_tgt[i_][j_] = 0;
                    b2_lag[i_][j_] = 0; b2_tgt[i_][j_] = 0;
                    l1_c[i_][j_] = 0;   l2_c[i_][j_] = 0;
                end
                b1_r0[i_][0] = 0; b1_r1[i_][0] = 0; b1_r0[i_][1] = 0; b1_r1[i_][1] = 0;
                b2_r0[i_][0] = 0; b2_r1[i_][0] = 0; b2_r0[i_][1] = 0; b2_r1[i_][1] = 0;
                l1_r0[i_][0] = 0; l1_r1[i_][0] = 0; l1_r0[i_][1] = 0; l1_r1[i_][1] = 0;
                l2_r0[i_][0] = 0; l2_r1[i_][0] = 0; l2_r0[i_][1] = 0; l2_r1[i_][1] = 0;
                for (h_ = 0; h_ < 2; h_ = h_ + 1)
                    for (c_ = 0; c_ < 2; c_ = c_ + 1)
                        for (r_ = 0; r_ < 2; r_ = r_ + 1)
                            for (j_ = 0; j_ < STAGES; j_ = j_ + 1)
                                for (t2_ = 0; t2_ < 3; t2_ = t2_ + 1) begin
                                    hx[i_][h_][c_][r_][j_][t2_] = 0;
                                    hy[i_][h_][c_][r_][j_][t2_] = 0;
                                end
                fbl[i_] = 0; fbr[i_] = 0; fbq[i_] = 0;
                lp1on[i_] = 0; lp2on[i_] = 0; wsm[i_] = 3;
                dr_cur[i_] = 0; og_cur[i_] = 0; dr_raw[i_] = 0;
                dr_tgt[i_] = $signed(initwords[12 + i_*2 + 0][31:0]);
                og_tgt[i_] = $signed(initwords[12 + i_*2 + 1][31:0]);
                b_first[i_] = 1;
                // DistortionEffect::init(): wsState.R[i] = setzero_ps().
                // `wsState.init` is INDETERMINATE in the engine; the frozen
                // model pins it to "first sample" (quad_shapers.py DD-3).
                ws_zero(i_, 1);
                dnow_end[i_] = 0;
                dcoff_blk[i_] = 0;
            end
            ws_zero(2, 0);
        end
    endtask

    // ---------------- state trace -----------------------------------------
    task emit_state(input integer bb);
        integer i2_, j2_, h_, c_, r_, t2_, l2;
        begin
            for (i2_ = 0; i2_ < NINST; i2_ = i2_ + 1) begin
                $fwrite(fd, "T %0d %0d fbl %0d fbr %0d drv %0d og %0d ",
                        bb, i2_, $signed(fbl[i2_]), $signed(fbr[i2_]),
                        $signed(dr_tgt[i2_]), $signed(og_tgt[i2_]));
                for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1)
                    $fwrite(fd, "b1l%0d %0d ", j2_, $signed(b1_lag[i2_][j2_]));
                for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1)
                    $fwrite(fd, "b2l%0d %0d ", j2_, $signed(b2_lag[i2_][j2_]));
                $fwrite(fd, "b1r00 %0d b1r10 %0d b1r01 %0d b1r11 %0d ",
                        $signed(b1_r0[i2_][0]), $signed(b1_r1[i2_][0]),
                        $signed(b1_r0[i2_][1]), $signed(b1_r1[i2_][1]));
                $fwrite(fd, "b2r00 %0d b2r10 %0d b2r01 %0d b2r11 %0d ",
                        $signed(b2_r0[i2_][0]), $signed(b2_r1[i2_][0]),
                        $signed(b2_r0[i2_][1]), $signed(b2_r1[i2_][1]));
                $fwrite(fd, "l1r00 %0d l1r10 %0d l1r01 %0d l1r11 %0d ",
                        $signed(l1_r0[i2_][0]), $signed(l1_r1[i2_][0]),
                        $signed(l1_r0[i2_][1]), $signed(l1_r1[i2_][1]));
                $fwrite(fd, "l2r00 %0d l2r10 %0d l2r01 %0d l2r11 %0d ",
                        $signed(l2_r0[i2_][0]), $signed(l2_r1[i2_][0]),
                        $signed(l2_r0[i2_][1]), $signed(l2_r1[i2_][1]));
                for (h_ = 0; h_ < 2; h_ = h_ + 1)
                    for (c_ = 0; c_ < 2; c_ = c_ + 1)
                        for (r_ = 0; r_ < 2; r_ = r_ + 1)
                            for (j2_ = 0; j2_ < STAGES; j2_ = j2_ + 1)
                                for (t2_ = 0; t2_ < 3; t2_ = t2_ + 1)
                                    $fwrite(fd, "h%0d%0d%0d%0dx%0d %0d h%0d%0d%0d%0dy%0d %0d ",
                                            h_, c_, r_, j2_, t2_,
                                            $signed(hx[i2_][h_][c_][r_][j2_][t2_]),
                                            h_, c_, r_, j2_, t2_,
                                            $signed(hy[i2_][h_][c_][r_][j2_][t2_]));
                // the quad-waveshaper registers: this leaf's own state
                for (j2_ = 0; j2_ < 4; j2_ = j2_ + 1)
                    for (l2 = 0; l2 < 2; l2 = l2 + 1)
                        $fwrite(fd, "wsR%0d%0d %0d ", j2_, l2,
                                $signed(wsR[i2_][j2_][l2]));
                for (l2 = 0; l2 < 2; l2 = l2 + 1)
                    $fwrite(fd, "wsI%0d %0d ", l2, wsI[i2_][l2] ? 1 : 0);
                // the drive interpolation end point and the DC-offset probe
                $fwrite(fd, "dnowe %0d dcof %0d ",
                        $signed(dnow_end[i2_]), $signed(dcoff_blk[i2_]));
                $fwrite(fd, "er 0 ew 0\n");
            end
        end
    endtask

    // ---------------- main -------------------------------------------------
    initial begin
        if (!$value$plusargs("NINST=%d", NINST)) NINST = 1;
        if (!$value$plusargs("NBLOCKS=%d", N_BLOCKS)) N_BLOCKS = 1;
        if (!$value$plusargs("RENDER0=%d", RENDER0)) RENDER0 = 0;
        if (!$value$plusargs("RESETAT=%d", RESETAT)) RESETAT = -1;
        if (!$value$plusargs("DEBUG=%d", DEBUG)) DEBUG = 0;
        if (!$value$plusargs("TRACE=%s", trace_name)) trace_name = "tb_trace.txt";
        if (!$value$plusargs("INFILE=%s", fin_name)) fin_name = "in.hex";
        if (!$value$plusargs("CTRLFILE=%s", fct_name)) fct_name = "ctrl.hex";
        if (!$value$plusargs("INITFILE=%s", init_name)) init_name = "init.hex";
        if (!$value$plusargs("WSROM=%s", ws_name)) ws_name = "ws_sse_q29.hex";
        if (!$value$plusargs("REV=%s", rev_name)) rev_name = "00000000";

        $readmemh(ws_name, wsrom);
        $readmemh(init_name, initwords);

        fd = $fopen(trace_name, "w");
        fin = $fopen(fin_name, "r");
        fct = $fopen(fct_name, "r");
        if (fd == 0 || fin == 0 || fct == 0) begin
            $display("FILE OPEN FAILURE");
            $finish;
        end
        $fwrite(fd, "R %s\n", rev_name);

        do_reset;
        b_first[0] = 1; b_first[1] = 1;

        for (b = 0; b < N_BLOCKS; b = b + 1) begin
            if (b == RESETAT) begin
                do_reset;
            end
            chk = (b == 0) || (b == N_BLOCKS - 1) ||
                  ((b >= RENDER0) && (((b - RENDER0) % 16) == 0));
            tap_capture = (b == 0) || (b == N_BLOCKS - 1) ||
                          ((b >= RENDER0) && (((b - RENDER0) % 8) == 0));
            for (ii = 0; ii < NINST; ii = ii + 1)
                apply_ctrl(ii, fct);
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                for (k = 0; k < BLOCKN; k = k + 1) begin
                    rd64(fin, v64); ilw[ii][k] = $signed(v64[31:0]);
                end
                for (k = 0; k < BLOCKN; k = k + 1) begin
                    rd64(fin, v64); irw[ii][k] = $signed(v64[31:0]);
                end
            end
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                dist_block(ii);
                if (b >= RENDER0) begin
                    $fwrite(fd, "O %0d %0d", b, ii);
                    for (k = 0; k < BLOCKN; k = k + 1) $fwrite(fd, " %0d", out_l[k]);
                    for (k = 0; k < BLOCKN; k = k + 1) $fwrite(fd, " %0d", out_r[k]);
                    $fwrite(fd, "\n");
                end
                if (tap_capture != 0) begin
                    $fwrite(fd, "X %0d %0d", b, ii);
                    for (k = 0; k < 4; k = k + 1)
                        for (s_ = 0; s_ < 4; s_ = s_ + 1)
                            $fwrite(fd, " %0d %0d", xt[k][s_][0], xt[k][s_][1]);
                    $fwrite(fd, "\n");
                end
            end
            if (chk != 0) emit_state(b);
        end
        $fclose(fd);
        $display("TB DONE");
        $finish;
    end

endmodule
