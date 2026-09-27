// SXT-028e RTL behavioral schedule: Distortion (multiband + waveshaper
// drive) slice.
//
// Reproduces the frozen fixed-point model
// (model/effects/type-distortion/distortion_model.py) EXACTLY at declared
// checkpoints and on every per-instance output sample. All audio-rate
// arithmetic is computed here in the frozen conventions (exact products,
// round-half-up, saturating two's-complement). Block-rate quantities
// (drive/outgain RAW lipol targets, the feedback coefficient, the four
// biquad coefficient target sets, and the activity/model flags) are
// CONTROL-PLANE: streamed from <case>_ctrl.hex.
//
// Distortion owns NO delay-line-class buffer: there is no external memory
// in this slice at all. Per-instance state is the two peak-EQ biquads,
// the two instantized oversampled LP biquads, the two halfband decimators,
// the two feedback registers, the two lipol ramps and the slow-rate
// counter -- all replicated per instance and never pooled (the
// mutant-shared negative control pools them and must FAIL).
//
// The twelve halfband allpass coefficients are NOT duplicated here: they
// are streamed through INITFILE (decision-records/0002 clause 1, extended
// by 0012). The waveshaper ROM (three frozen rows x 1024 Q2.29 words) is
// loaded from ws_q29.hex, generated from the pinned construction formulas
// by model/effects/type-distortion/ws_tables.py.
//
// Wiring (plusargs):
//   +NINST=1|2      instances driven per block (independent state)
//   +NBLOCKS=n      blocks
//   +RENDER0=b      first render block (outputs traced from here)
//   +RESETAT=b      optional: core reset before block b (fx-rebuild/panic)
//   +INFILE / +CTRLFILE / +INITFILE / +WSROM / +TRACE / +REV
//
// INITFILE layout: 12 x Q24.43 halfband coefficients
//   (hr_a A[3], hr_a B[3], hr_b A[3], hr_b B[3]) followed by, per instance,
//   2 x Q13.18 words (the plain setvars(true) drive/outgain lipol targets).
`timescale 1ns/1ps

module tb_distortion;
    integer NINST, N_BLOCKS, RENDER0, RESETAT, DEBUG;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, init_name, ws_name, rev_name;

    localparam integer BLOCKN  = 32;
    localparam integer OSN     = 128;        // BLOCK << dist_OS_bits
    localparam integer STAGES  = 3;          // HalfRateFilter M = 3
    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;   // 0.004  Q24.43
    localparam signed [63:0] DLPI_r = 64'sh000007F7CED91687;  // 0.996  Q24.43
    localparam integer ONE_A = 1 << 21;

    // ---------------- waveshaper ROM (3 frozen rows x 1024 words) --------
    reg [31:0] wsrom [0:3071];

    // ---------------- halfband coefficients (streamed, not duplicated) ---
    // INITFILE words are 16 hex digits each (sign-extended); the first 12
    // are the Q24.43 halfband allpass coefficients, then 2 x Q13.18 per
    // instance (the plain setvars(true) drive/outgain lipol targets).
    reg [63:0] initwords [0:15];

    // ---------------- per-instance state ----------------
    // peak-EQ biquads (lagged TDF2)
    reg signed [63:0] b1_lag [0:1][0:4]; reg signed [63:0] b1_tgt [0:1][0:4];
    reg signed [63:0] b2_lag [0:1][0:4]; reg signed [63:0] b2_tgt [0:1][0:4];
    reg signed [63:0] b1_r0 [0:1][0:1];  reg signed [63:0] b1_r1 [0:1][0:1];
    reg signed [63:0] b2_r0 [0:1][0:1];  reg signed [63:0] b2_r1 [0:1][0:1];
    integer b_first [0:1];
    // oversampled LP biquads (instantized coefficients, no lag step)
    reg signed [63:0] l1_c [0:1][0:4];   reg signed [63:0] l2_c [0:1][0:4];
    reg signed [63:0] l1_r0 [0:1][0:1];  reg signed [63:0] l1_r1 [0:1][0:1];
    reg signed [63:0] l2_r0 [0:1][0:1];  reg signed [63:0] l2_r1 [0:1][0:1];
    // halfband state: [inst][which hr][channel][branch][stage][tap]
    reg signed [63:0] hx [0:1][0:1][0:1][0:1][0:2][0:2];
    reg signed [63:0] hy [0:1][0:1][0:1][0:1][0:2][0:2];
    // gain ramps + feedback registers + slow-rate counter
    reg signed [31:0] dr_cur [0:1]; reg signed [31:0] dr_tgt [0:1];
    reg signed [31:0] og_cur [0:1]; reg signed [31:0] og_tgt [0:1];
    reg signed [31:0] fbl [0:1];    reg signed [31:0] fbr [0:1];
    reg signed [31:0] fbq [0:1];
    integer lp1on [0:1], lp2on [0:1], wsm [0:1];

    integer ilw [0:1][0:31];
    integer irw [0:1][0:31];
    integer out_l [0:31];
    integer out_r [0:31];
    integer wk_l [0:31];
    integer wk_r [0:31];
    integer bufl [0:127];
    integer bufr [0:127];

    // tap checkpoints (observation only): the first 4 base samples x 4 OS
    // steps of the shaper loop per instance
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

    function automatic signed [63:0] qadd64(input signed [63:0] a, input signed [63:0] b_);
        qadd64 = sat64($signed({{64{a[63]}}, a}) + $signed({{64{b_[63]}}, b_}));
    endfunction

    function automatic signed [63:0] qsub64(input signed [63:0] a, input signed [63:0] b_);
        qsub64 = sat64($signed({{64{a[63]}}, a}) - $signed({{64{b_[63]}}, b_}));
    endfunction

    // Q24.43 x Q24.43 -> Q24.43, round-half-up, saturating
    function automatic signed [63:0] qmul_cc(input signed [63:0] a, input signed [63:0] b_);
        reg signed [127:0] p;
        begin
            p = $signed(a) * $signed(b_);
            qmul_cc = sat64((p + $signed(128'sd4398046511104)) >>> 43);
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

    // lipol ramp line value: cur + round(d*(k+1)/32)
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

    // ---------------- waveshaper (lookup_waveshape, Q2.29 ROM) -----------
    function automatic signed [31:0] ws_lookup(input integer inst,
                                               input signed [31:0] x);
        reg signed [63:0] xs;
        integer e, base;
        reg signed [63:0] frc, t0, t1, d, r29;
        begin
            xs = ($signed({{32{x[31]}}, x}) <<< 5) + $signed(64'sd1073741824);
            e = xs >>> 21;
            if (e > 1021) ws_lookup = ONE_A;
            else if (e < 1) ws_lookup = -ONE_A;
            else begin
                frc = xs - ($signed(e) <<< 21);
                base = wsm[inst] * 1024;
                t0 = $signed({{32{wsrom[base + (e & 1023)][31]}}, wsrom[base + (e & 1023)]});
                t1 = $signed({{32{wsrom[base + ((e + 1) & 1023)][31]}},
                              wsrom[base + ((e + 1) & 1023)]});
                d = t1 - t0;
                // frc (Q10.21) * d (Q2.29) -> Q2.29, round-half-up, saturating
                r29 = $signed({{32{1'b0}}, sat32((frc * d + $signed(64'sd1048576)) >>> 21)});
                r29 = $signed({{32{r29[31]}}, r29[31:0]});
                r29 = $signed({{32{1'b0}}, sat32(t0 + r29)});
                r29 = $signed({{32{r29[31]}}, r29[31:0]});
                ws_lookup = sat32((r29 + $signed(64'sd128)) >>> 8);
            end
        end
    endfunction

    // ---------------- halfband D2 (one stage pair, one instance) ---------
    // hw: 0 = hr_a (coefficients hbc[0..5]), 1 = hr_b (hbc[6..11])
    function automatic signed [63:0] hb_cascade(input integer inst, input integer hw,
                                                input integer chh, input integer br,
                                                input signed [63:0] xin);
        reg signed [63:0] v, y, x1, y1;
        integer jj, ci;
        begin
            v = xin;
            for (jj = 0; jj < STAGES; jj = jj + 1) begin
                ci = hw * 6 + br * 3 + jj;   // 12 streamed Q24.43 coefficients
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
        integer ol, orr, idx;
        reg signed [31:0] g;
        begin
            // 1. band1 (pre-EQ)
            for (k = 0; k < BLOCKN; k = k + 1) begin
                bq_sample(inst, 0, ilw[inst][k], irw[inst][k], ol, orr);
                wk_l[k] = ol; wk_r[k] = orr;
            end
            // 2. drive ramp (in place)
            for (k = 0; k < BLOCKN; k = k + 1) begin
                g = lip_val(dr_cur[inst], dr_tgt[inst], k);
                wk_l[k] = qmul_ga(g, wk_l[k]);
                wk_r[k] = qmul_ga(g, wk_r[k]);
            end
            // 3. 4x oversampled feedback + shaper loop
            for (k = 0; k < BLOCKN; k = k + 1) begin
                for (s_ = 0; s_ < 4; s_ = s_ + 1) begin
                    fbl[inst] = qadd32(wk_l[k], qmul_aa(fbq[inst], fbl[inst]));
                    fbr[inst] = qadd32(wk_r[k], qmul_aa(fbq[inst], fbr[inst]));
                    if (lp1on[inst] != 0) begin
                        lp_sample(inst, 0, fbl[inst], fbr[inst], ol, orr);
                        fbl[inst] = ol; fbr[inst] = orr;
                    end
                    fbl[inst] = ws_lookup(inst, fbl[inst]);
                    fbr[inst] = ws_lookup(inst, fbr[inst]);
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
            // 4. two-stage halfband decimation 128 -> 64 -> 32
            hb_process(inst, 0, 128);
            hb_process(inst, 1, 64);
            // 5. outgain ramp + band2 (post-EQ)
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
            wsm[inst] = (v64 >> 2) & 3;
            if (b_first[inst] != 0) begin
                // first coefficient set start-values the band lags
                // (BiquadFilter::set_coef first_run path after suspend())
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
                lp1on[i_] = 0; lp2on[i_] = 0; wsm[i_] = 0;
                dr_cur[i_] = 0; og_cur[i_] = 0;
                dr_tgt[i_] = $signed(initwords[12 + i_*2 + 0][31:0]);
                og_tgt[i_] = $signed(initwords[12 + i_*2 + 1][31:0]);
                b_first[i_] = 1;
            end
        end
    endtask

    // ---------------- state trace -----------------------------------------
    task emit_state(input integer bb);
        integer i2_, j2_, h_, c_, r_, t2_;
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
        if (!$value$plusargs("WSROM=%s", ws_name)) ws_name = "ws_q29.hex";
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
