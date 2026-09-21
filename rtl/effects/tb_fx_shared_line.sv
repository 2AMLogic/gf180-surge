// SXT-023 RTL behavioral schedule: Delay + EQ slice.
//
// Reproduces the frozen fixed-point models (model/effects/{delay,eq})
// exactly at declared checkpoints and on every output sample. All
// audio-rate arithmetic is computed here in the frozen conventions
// (exact products, round-half-up, saturating two's-complement).
// Block-rate quantities (lipol targets, biquad coefficient targets,
// delay-time lag targets including the LFO contribution, send/return
// gains) are CONTROL-PLANE: streamed one word per line from
// <slug>_ctrl.hex and echoed in the trace.
//
// Delay channel lines (2^18+12 x Q10.21) live in external-memory
// modules (fx_line_ext) with transaction counters and an additive hash.
//
// Wiring (plusarg PCONFIG):
//   1 = metallic : ains=[delay] sends=[delay]
//   2 = fm_bass  : ains=[eq]
//   3 = dexie    : ains=[delay]
`timescale 1ns/1ps

module tb_fx;
    integer PCONFIG;
    integer N_BLOCKS;
    integer RENDER0;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, sinc_name;

    // ---------------- constants (exact, from the frozen model) ----------
    localparam signed [63:0] LPT_r  = 64'sh000000346DC5C0;    // f32(0.0001) Q24.43
    // engine lag pair is float32: lpinv = (float)(1.0f - 0.0001f) =
    // 0.9998999834060669f -> Q24.43 = 0x7FFCB900000 (NOT the double 1-lp,
    // 0x7FFCB923A40, which made the pair sum to exactly 2^43 and killed the
    // engine's -64-ulp lag drift: dexie tlv/trv drift, +-5 LSB class)
    localparam signed [63:0] LPIT_r = 64'sh0007FFCB900000;    // f32(1 - f32(0.0001)) Q24.43
    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;    // 0.004 Q24.43
    localparam signed [63:0] DLPI_r = 64'sh07F7CED91687;       // (1 - 0.004) Q24.43
    localparam signed [31:0] SOFT_A = -32'sd310689;            // -4/27 Q10.21
    localparam integer ONE_G   = 1 << 18;
    localparam integer CLIP_HI = 3 << 19;
    localparam integer HARD8   = 8 << 21;
    localparam signed [63:0] ONE43 = 64'sh0000080000000000;
    integer a_q;

    // ---------------- external delay lines ----------------

    // behavioral external-memory lines: 4 arrays (2 instances x 2 channels),
    // interface semantics per rtl/effects/delay/ext_mem_if.md
    reg [31:0] line_mem0 [0:(1<<18)+12-1];
    reg [31:0] line_mem1 [0:(1<<18)+12-1];
    reg [31:0] line_mem2 [0:(1<<18)+12-1];
    reg [31:0] line_mem3 [0:(1<<18)+12-1];
    longint unsigned rd0, wr0, h0, rd1, wr1, h1, rd2, wr2, h2, rd3, wr3, h3;
    reg [8*256:1] zeros_name;
    integer zinit;
    integer last_read;

    task line_access(input integer d, input integer c, input integer we,
                     input integer a, input integer wd);
        integer sel;
        reg signed [63:0] w64, o64;
        begin
            // sign-extend BOTH delta operands to 64 bits BEFORE the unsigned
            // accumulate: mixing 32-bit signed words with a longint unsigned
            // accumulator zero-extends them (LRM unsigned context) and
            // inflates every negative write delta by 2^32
            w64 = $signed({{32{wd[31]}}, wd});
            sel = 0; // MUTANT: shared line across instances (acceptance a)
            // sel = d*2 + c;
            case (sel)
                0: begin
                    if (we) begin
                        o64 = $signed({{32{line_mem0[a][31]}}, line_mem0[a]});
                        h0 = h0 + w64 - o64; line_mem0[a] = wd[31:0]; wr0 = wr0 + 1;
                    end
                    else begin rd0 = rd0 + 1; last_read = $signed(line_mem0[a]); end
                end
                1: begin
                    if (we) begin
                        o64 = $signed({{32{line_mem1[a][31]}}, line_mem1[a]});
                        h1 = h1 + w64 - o64; line_mem1[a] = wd[31:0]; wr1 = wr1 + 1;
                    end
                    else begin rd1 = rd1 + 1; last_read = $signed(line_mem1[a]); end
                end
                2: begin
                    if (we) begin
                        o64 = $signed({{32{line_mem2[a][31]}}, line_mem2[a]});
                        h2 = h2 + w64 - o64; line_mem2[a] = wd[31:0]; wr2 = wr2 + 1;
                    end
                    else begin rd2 = rd2 + 1; last_read = $signed(line_mem2[a]); end
                end
                default: begin
                    if (we) begin
                        o64 = $signed({{32{line_mem3[a][31]}}, line_mem3[a]});
                        h3 = h3 + w64 - o64; line_mem3[a] = wd[31:0]; wr3 = wr3 + 1;
                    end
                    else begin rd3 = rd3 + 1; last_read = $signed(line_mem3[a]); end
                end
            endcase
        end
    endtask

    // ---------------- delay instance state (2 max) ----------------
    reg signed [63:0] d_tlv [0:1];
    reg signed [63:0] d_tlt [0:1];
    reg signed [63:0] d_trv [0:1];
    reg signed [63:0] d_trt [0:1];
    reg               d_fbsign [0:1];
    reg signed [63:0] d_lag [0:1][0:1][0:4];  // [lp/hp][inst][a1 a2 b0 b1 b2]
    reg signed [63:0] d_r0 [0:1][0:1];        // [lp/hp][inst] L
    reg signed [63:0] d_r1 [0:1][0:1];
    reg signed [63:0] d_r0b [0:1][0:1];
    reg signed [63:0] d_r1b [0:1][0:1];
    reg signed [31:0] d_cur [0:1][0:4];
    reg signed [31:0] d_tgt [0:1][0:4];
    integer           d_wpos [0:1];
    integer           d_clip [0:1];
    integer           d_lpon [0:1];
    integer           d_hpon [0:1];
    integer           d_first [0:1];
    longint unsigned  d_er [0:1];
    longint unsigned  d_ew [0:1];
    reg signed [31:0] d_sg [0:1];
    reg signed [31:0] d_rl [0:1];

    // ---------------- EQ state ----------------
    reg signed [63:0] e_lag [0:2][0:4];
    reg signed [63:0] e_r0 [0:2][0:1];
    reg signed [63:0] e_r1 [0:2][0:1];
    reg signed [31:0] e_gcur, e_gtgt, e_mcur, e_mtgt;
    integer           e_bi;

    // ---------------- buffers ----------------
    integer ilw [0:31];
    integer irw [0:31];
    integer tb_l [0:1][0:31];
    integer tb_r [0:1][0:31];
    integer slw [0:31];
    integer srw [0:31];
    integer wb_l [0:31];
    integer wb_r [0:31];
    integer olw [0:31];
    integer orw [0:31];

    reg [31:0] sinc [0:3083];

    integer b, k, t_, tmp_i, tmp_j, w0, chk, i_;
    integer i_dt, i_dtr, ph, phr, base_l, base_r;
    integer acc_l, acc_r;
    integer cur_inst;
    integer first_step;

    reg signed [63:0] d_lagt [0:1][0:1][0:4];
    reg signed [63:0] e_lagt [0:2][0:4];

    // ---------------- fixed-point helpers ----------------
    function automatic signed [31:0] sat32(input signed [63:0] v);
        if (v > $signed(64'd2147483647)) sat32 = 32'sd2147483647;
        else if (v < -$signed(64'd2147483647)) sat32 = -32'sd2147483647;
        else sat32 = v[31:0];
    endfunction

    function automatic signed [63:0] sat64(input signed [127:0] v);
        if (v > $signed(128'd9223372036854775807)) sat64 = 64'sd9223372036854775807;
        else if (v < -$signed(128'd9223372036854775807)) sat64 = -64'sd9223372036854775807;
        else sat64 = v[63:0];
    endfunction

    function automatic signed [63:0] qadd64(input signed [63:0] a, input signed [63:0] b);
        qadd64 = sat64($signed({{64{a[63]}}, a}) + $signed({{64{b[63]}}, b}));
    endfunction

    function automatic signed [63:0] qsub64(input signed [63:0] a, input signed [63:0] b);
        qsub64 = qadd64(a, ~b + 64'sd1);
    endfunction

    // 64x64 signed multiply -> 128-bit, via 32-bit partial products
    // (iverilog elaborates a direct 128x128 '*' for minutes)
    function automatic signed [63:0] zext32(input [31:0] x);
        zext32 = $signed({32'h0, x});
    endfunction
    function automatic signed [63:0] qmul_cc(input signed [63:0] a, input signed [63:0] b);
        // 64x64 signed multiply -> 128-bit via 32-bit partial products
        // (iverilog elaborates a direct 128x128 '*' for minutes)
        reg signed [31:0] ah, bh;
        reg [31:0] al, bl;
        reg signed [63:0] t_hh;
        reg signed [95:0] t_hl, t_lh, tsum;
        reg signed [127:0] p;
        begin
            ah = a[63:32]; al = a[31:0];
            bh = b[63:32]; bl = b[31:0];
            t_hh = $signed(ah) * $signed(bh);                    // << 64
            t_hl = $signed(ah) * $signed({32'h0, bl});           // << 32 (u32 low)
            t_lh = $signed({32'h0, al}) * $signed(bh);           // << 32 (u32 low)
            tsum = t_hl + t_lh;
            p = ($signed({{64{t_hh[63]}}, t_hh}) <<< 64)
              + ($signed({{32{tsum[95]}}, tsum}) <<< 32)
              + $signed({64'h0, al} * {64'h0, bl});
            qmul_cc = sat64((p + $signed(128'd4398046511104)) >>> 43);
        end
    endfunction

    function automatic signed [31:0] qadd32(input signed [31:0] a, input signed [31:0] b);
        qadd32 = sat32($signed({{33{a[31]}}, a}) + $signed({{33{b[31]}}, b}));
    endfunction

    function automatic signed [31:0] qsub32(input signed [31:0] a, input signed [31:0] b);
        qsub32 = qadd32(a, ~b + 32'sd1);
    endfunction

    function automatic signed [31:0] qmul_ga(input signed [31:0] a, input signed [31:0] b);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b);
            qmul_ga = sat32((p + $signed(64'd131072)) >>> 18);
        end
    endfunction

    function automatic signed [31:0] qmul_aa(input signed [31:0] a, input signed [31:0] b);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b);
            qmul_aa = sat32((p + $signed(64'd1048576)) >>> 21);
        end
    endfunction

    function automatic integer clipi(input integer v, input integer lo, input integer hi);
        if (v < lo) clipi = lo;
        else if (v > hi) clipi = hi;
        else clipi = v;
    endfunction

    function automatic integer int_part(input signed [63:0] v);
        if (v >= 0) int_part = v >>> 43;
        else int_part = -((-v) >>> 43);
    endfunction

    function automatic integer sinc_phase(input integer i_dt, input signed [63:0] v);
        reg signed [63:0] diff, scaled;
        begin
            diff = qsub64(((i_dt + 1) * ONE43), v);
            if (diff >= 0) scaled = (diff * 256) >>> 43;
            else scaled = -(((-diff) * 256) >>> 43);
            sinc_phase = clipi(scaled, 0, 255);
        end
    endfunction

    function automatic signed [31:0] softclip32(input signed [31:0] x);
        reg signed [31:0] xx, t2;
        begin
            if (x > CLIP_HI) softclip32 = CLIP_HI;
            else if (x < -CLIP_HI) softclip32 = -CLIP_HI;
            else begin
                xx = qmul_aa(x, x);
                t2 = qmul_aa(qmul_aa(x, SOFT_A), xx);
                softclip32 = qadd32(x, t2);
            end
        end
    endfunction

    // lipol ramp line value: cur + round(d*(k+1)/32)
    function automatic signed [31:0] lip_val(input signed [31:0] cur, input signed [31:0] tgt,
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
            tgt = qadd32(qmul_ga(32'sd65536, f), qmul_ga(32'sd196608, old_t));
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

    // control application: one delay instance
    reg [63:0] v64;
    reg [31:0] v32;
    integer j_;
    task apply_delay_ctrl(input integer inst, input integer fh, input integer first);
        begin
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); v32 = v64[31:0];
                lip_smooth(d_cur[inst][j_], d_tgt[inst][j_], $signed(v32));
            end
            rd64(fh, v64); d_tlt[inst] = $signed(v64);
            rd64(fh, v64); d_trt[inst] = $signed(v64);
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); d_lagt[0][inst][j_] = $signed(v64);
            end
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); d_lagt[1][inst][j_] = $signed(v64);
            end
            rd64(fh, v64);
            d_lpon[inst] = v64[0];
            d_hpon[inst] = v64[1];
            d_fbsign[inst] = v64[2];
            d_clip[inst] = v64[5:3];
            if (first != 0) begin
                d_tlv[inst] = d_tlt[inst];
                d_trv[inst] = d_trt[inst];
                for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                    d_cur[inst][j_] = d_tgt[inst][j_];
                    d_lag[0][inst][j_] = d_lagt[0][inst][j_];
                    d_lag[1][inst][j_] = d_lagt[1][inst][j_];
                end
            end
        end
    endtask
    // EQ control application
    task apply_eq_ctrl(input integer fh, input integer first);
        integer w_, j2_;
        reg [63:0] v2;
        reg [31:0] v32b;
        begin
            for (w_ = 0; w_ < 3; w_ = w_ + 1)
                for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1) begin
                    rd64(fh, v2); e_lagt[w_][j2_] = $signed(v2);
                end
            rd64(fh, v2); v32b = v2[31:0]; lip_smooth(e_gcur, e_gtgt, $signed(v32b));
            rd64(fh, v2); v32b = v2[31:0]; lip_smooth(e_mcur, e_mtgt, $signed(v32b));
            if (first != 0)
                for (w_ = 0; w_ < 3; w_ = w_ + 1)
                    for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1)
                        e_lag[w_][j2_] = e_lagt[w_][j2_];
        end
    endtask
    // ---------------- biquad / eq band samples ----------------
    task bq_sample(input integer wh, input integer inst,
                   input integer inl, input integer inr,
                   output integer ol, output integer orr);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, il, ir, op, op2;
        begin
            for (t_ = 0; t_ < 5; t_ = t_ + 1)
                d_lag[wh][inst][t_] = qadd64(qmul_cc(d_lag[wh][inst][t_], DLPI_r),
                                             qmul_cc(d_lagt[wh][inst][t_], DLP_r));
            a1_ = d_lag[wh][inst][0];
            a2_ = d_lag[wh][inst][1];
            b0_ = d_lag[wh][inst][2];
            b1_ = d_lag[wh][inst][3];
            b2_ = d_lag[wh][inst][4];
            il = $signed(inl) <<< 22;
            op = qadd64(qmul_cc(il, b0_), d_r0[wh][inst]);
            d_r0[wh][inst] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)), d_r1[wh][inst]);
            d_r1[wh][inst] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
            orr = 0;
            ir = $signed(inr) <<< 22;
            op2 = qadd64(qmul_cc(ir, b0_), d_r0b[wh][inst]);
            d_r0b[wh][inst] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)), d_r1b[wh][inst]);
            d_r1b[wh][inst] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            ol = sat32((op + $signed(64'sd2097152)) >>> 22);
            orr = sat32((op2 + $signed(64'sd2097152)) >>> 22);
        end
    endtask
    task eq_band_sample(input integer w_, input integer inl, input integer inr,
                        output integer ol, output integer orr);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, il, ir, op, op2;
        begin
            for (t_ = 0; t_ < 5; t_ = t_ + 1)
                e_lag[w_][t_] = qadd64(qmul_cc(e_lag[w_][t_], DLPI_r),
                                       qmul_cc(e_lagt[w_][t_], DLP_r));
            a1_ = e_lag[w_][0];
            a2_ = e_lag[w_][1];
            b0_ = e_lag[w_][2];
            b1_ = e_lag[w_][3];
            b2_ = e_lag[w_][4];
            il = $signed(inl) <<< 22;
            ir = $signed(inr) <<< 22;
            op = qadd64(qmul_cc(il, b0_), e_r0[w_][0]);
            e_r0[w_][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)), e_r1[w_][0]);
            e_r1[w_][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
            op2 = qadd64(qmul_cc(ir, b0_), e_r0[w_][1]);
            e_r0[w_][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)), e_r1[w_][1]);
            e_r1[w_][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            ol = sat32((op + $signed(64'sd2097152)) >>> 22);
            orr = sat32((op2 + $signed(64'sd2097152)) >>> 22);
        end
    endtask

    function automatic [31:0] eq_lip_val(input integer which, input integer kk);
        reg signed [31:0] cur, tgt;
        begin
            cur = which ? e_mcur : e_gcur;
            tgt = which ? e_mtgt : e_gtgt;
            eq_lip_val = lip_val(cur, tgt, kk);
        end
    endfunction

    function automatic [31:0] trix_l(input signed [31:0] pv, input integer l, input integer r);
        reg signed [31:0] a, bb;
        begin
            a = (pv > 0) ? pv : 32'sd0;
            bb = (pv < 0) ? pv : 32'sd0;
            trix_l = qsub32(qmul_ga(qsub32(ONE_G, a), l), qmul_ga(bb, r));
        end
    endfunction
    function automatic [31:0] trix_r(input signed [31:0] pv, input integer l, input integer r);
        reg signed [31:0] a, bb;
        begin
            a = (pv > 0) ? pv : 32'sd0;
            bb = (pv < 0) ? pv : 32'sd0;
            trix_r = qadd32(qmul_ga(a, l), qmul_ga(qadd32(ONE_G, bb), r));
        end
    endfunction

    // ---------------- delay block datapath ----------------
    integer oins_l [0:31];
    integer oins_r [0:31];
    task delay_block(input integer inst);
        integer kk, i_dt, i_dtr, ph, phr, base_l, base_r, w0, rd, tmp, tmp2;
        longint signed acc_l, acc_r;
        begin
            for (kk = 0; kk < 32; kk = kk + 1) begin
                d_tlv[inst] = qadd64(qmul_cc(d_tlv[inst], LPIT_r), qmul_cc(d_tlt[inst], LPT_r));
                d_trv[inst] = qadd64(qmul_cc(d_trv[inst], LPIT_r), qmul_cc(d_trt[inst], LPT_r));
                i_dt  = clipi(int_part(d_tlv[inst]), 32, (1 << 18) - 13);
                i_dtr = clipi(int_part(d_trv[inst]), 32, (1 << 18) - 13);
                base_l = ((d_wpos[inst] - i_dt + kk) - 12) & ((1 << 18) - 1);
                base_r = ((d_wpos[inst] - i_dtr + kk) - 12) & ((1 << 18) - 1);
                ph  = sinc_phase(i_dt,  d_tlv[inst]);
                phr = sinc_phase(i_dtr, d_trv[inst]);
                acc_l = 0; acc_r = 0;
                for (t_ = 0; t_ < 12; t_ = t_ + 1) begin
                    line_access(inst, 0, 0, (base_l + t_) & ((1 << 18) - 1), 0);
                    rd = last_read;
                    acc_l = acc_l + $signed(sinc[ph*12 + t_]) * $signed(rd);
                    line_access(inst, 1, 0, (base_r + t_) & ((1 << 18) - 1), 0);
                    rd = last_read;
                    acc_r = acc_r + $signed(sinc[phr*12 + t_]) * $signed(rd);
                end
                // Q(21+29) accumulator -> Q10.21, round-half-up (half 2^28,
                // shift 29 — was 2^20/22, a 128x tap-scale error)
                tb_l[inst][kk] = sat32((acc_l + $signed(64'sd268435456)) >>> 29);
                tb_r[inst][kk] = sat32((acc_r + $signed(64'sd268435456)) >>> 29);
            end
            if (d_fbsign[inst]) begin
                for (kk = 0; kk < 32; kk = kk + 1) begin
                    tb_l[inst][kk] = -tb_l[inst][kk];
                    tb_r[inst][kk] = -tb_r[inst][kk];
                end
            end
            if (d_clip[inst] == 1) begin
                for (kk = 0; kk < 32; kk = kk + 1) begin
                    tb_l[inst][kk] = softclip32(tb_l[inst][kk]);
                    tb_r[inst][kk] = softclip32(tb_r[inst][kk]);
                end
            end
            if (d_lpon[inst] != 0)
                for (kk = 0; kk < 32; kk = kk + 1)
                    bq_sample(0, inst, tb_l[inst][kk], tb_r[inst][kk], tb_l[inst][kk], tb_r[inst][kk]);
            if (d_hpon[inst] != 0)
                for (kk = 0; kk < 32; kk = kk + 1)
                    bq_sample(1, inst, tb_l[inst][kk], tb_r[inst][kk], tb_l[inst][kk], tb_r[inst][kk]);
            for (kk = 0; kk < 32; kk = kk + 1) begin
                wb_l[kk] = trix_l(lip_val(d_cur[inst][3], d_tgt[inst][3], kk), ilw[kk], irw[kk]);
                wb_r[kk] = trix_r(lip_val(d_cur[inst][3], d_tgt[inst][3], kk), ilw[kk], irw[kk]);
            end
            for (kk = 0; kk < 32; kk = kk + 1) begin
                wb_l[kk] = qadd32(wb_l[kk], qmul_ga(lip_val(d_cur[inst][0], d_tgt[inst][0], kk), tb_l[inst][kk]));
                wb_r[kk] = qadd32(wb_r[kk], qmul_ga(lip_val(d_cur[inst][0], d_tgt[inst][0], kk), tb_r[inst][kk]));
                wb_r[kk] = qadd32(wb_r[kk], qmul_ga(lip_val(d_cur[inst][1], d_tgt[inst][1], kk), tb_l[inst][kk]));
                wb_l[kk] = qadd32(wb_l[kk], qmul_ga(lip_val(d_cur[inst][1], d_tgt[inst][1], kk), tb_r[inst][kk]));
            end
            for (kk = 0; kk < 32; kk = kk + 1) begin
                w0 = (d_wpos[inst] + kk) & ((1 << 18) - 1);
                line_access(inst, 0, 1, w0, wb_l[kk]);
                line_access(inst, 1, 1, w0, wb_r[kk]);
            end
            d_ew[inst] = d_ew[inst] + 64;
            for (kk = 0; kk < 32; kk = kk + 1) begin
                // mid/side halving is round-half-up (truncate toward zero):
                // -(|d| >> 1), NOT arithmetic >>> 1 (floor) on negative sums —
                // the floor form injected a -1 LSB bias on odd negative sums
                tmp = $signed(tb_l[inst][kk]) + $signed(tb_r[inst][kk]);
                tmp2 = $signed(tb_l[inst][kk]) - $signed(tb_r[inst][kk]);
                tmp = (tmp >= 0) ? sat32(tmp >>> 1) : sat32(-((-tmp) >>> 1));
                tmp2 = (tmp2 >= 0) ? sat32(tmp2 >>> 1) : sat32(-((-tmp2) >>> 1));
                tmp2 = qmul_ga(lip_val(d_cur[inst][4], d_tgt[inst][4], kk), tmp2);
                tb_l[inst][kk] = qadd32(tmp, tmp2);
                tb_r[inst][kk] = qsub32(tmp, tmp2);
            end
            for (kk = 0; kk < 32; kk = kk + 1) begin
                olw[kk] = qadd32(qmul_ga(qsub32(ONE_G, lip_val(d_cur[inst][2], d_tgt[inst][2], kk)), ilw[kk]),
                                 qmul_ga(lip_val(d_cur[inst][2], d_tgt[inst][2], kk), tb_l[inst][kk]));
                orw[kk] = qadd32(qmul_ga(qsub32(ONE_G, lip_val(d_cur[inst][2], d_tgt[inst][2], kk)), irw[kk]),
                                 qmul_ga(lip_val(d_cur[inst][2], d_tgt[inst][2], kk), tb_r[inst][kk]));
            end
            d_wpos[inst] = (d_wpos[inst] + 32) & ((1 << 18) - 1);
        end
    endtask

    // ---------------- EQ block ----------------
    task eq_block;
        integer kk, w_;
        integer wl [0:31];
        integer wr [0:31];
        integer nl [0:31];
        integer nr [0:31];
        integer g_, mv;
        begin
            for (kk = 0; kk < 32; kk = kk + 1) begin
                wl[kk] = ilw[kk];
                wr[kk] = irw[kk];
            end
            for (w_ = 0; w_ < 3; w_ = w_ + 1) begin
                for (kk = 0; kk < 32; kk = kk + 1)
                    eq_band_sample(w_, wl[kk], wr[kk], nl[kk], nr[kk]);
                for (kk = 0; kk < 32; kk = kk + 1) begin
                    wl[kk] = nl[kk];
                    wr[kk] = nr[kk];
                end
            end
            for (kk = 0; kk < 32; kk = kk + 1) begin
                g_ = eq_lip_val(0, kk);
                mv = eq_lip_val(1, kk);
                olw[kk] = qadd32(qmul_ga(qsub32(ONE_G, mv), ilw[kk]),
                                 qmul_ga(mv, qmul_ga(g_, wl[kk])));
                orw[kk] = qadd32(qmul_ga(qsub32(ONE_G, mv), irw[kk]),
                                 qmul_ga(mv, qmul_ga(g_, wr[kk])));
            end
        end
    endtask

    // ---------------- state trace ----------------
    task emit_state(input integer bb);
        integer j2_, w2_;
        begin
            if (PCONFIG == 2) begin
                $fwrite(fd, "T %0d eq0 bi %0d ", bb, e_bi);
                for (w2_ = 0; w2_ < 3; w2_ = w2_ + 1)
                    for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1)
                        $fwrite(fd, "lag%0d_%0d %0d ", w2_, j2_, $signed(e_lag[w2_][j2_]));
                $fwrite(fd, "r0 %0d r1 %0d r2 %0d r3 %0d r4 %0d r5 %0d r6 %0d r7 %0d r8 %0d r9 %0d r10 %0d r11 %0d ",
                        $signed(e_r0[0][0]), $signed(e_r0[0][1]),
                        $signed(e_r1[0][0]), $signed(e_r1[0][1]),
                        $signed(e_r0[1][0]), $signed(e_r0[1][1]),
                        $signed(e_r1[1][0]), $signed(e_r1[1][1]),
                        $signed(e_r0[2][0]), $signed(e_r0[2][1]),
                        $signed(e_r1[2][0]), $signed(e_r1[2][1]));
                $fwrite(fd, "gtgt %0d mtgt %0d\n", $signed(e_gtgt), $signed(e_mtgt));
            end else begin
                emit_delay_state(bb, 0);
                if (PCONFIG == 1) emit_delay_state(bb, 1);
            end
        end
    endtask

    task emit_delay_state(input integer bb, input integer inst);
        integer j3_;
        begin
            $fwrite(fd, "T %0d d%0d wpos %0d fbsign %0d ", bb, inst, d_wpos[inst], d_fbsign[inst]);
            $fwrite(fd, "tlv %0d tlt %0d trv %0d trt %0d ",
                    $signed(d_tlv[inst]), $signed(d_tlt[inst]),
                    $signed(d_trv[inst]), $signed(d_trt[inst]));
            for (j3_ = 0; j3_ < 5; j3_ = j3_ + 1)
                $fwrite(fd, "lp%0d %0d ", j3_, $signed(d_lag[0][inst][j3_]));
            for (j3_ = 0; j3_ < 5; j3_ = j3_ + 1)
                $fwrite(fd, "hp%0d %0d ", j3_, $signed(d_lag[1][inst][j3_]));
            $fwrite(fd, "lpr0 %0d lpr1 %0d lpr0b %0d lpr1b %0d ",
                    $signed(d_r0[0][inst]), $signed(d_r1[0][inst]),
                    $signed(d_r0b[0][inst]), $signed(d_r1b[0][inst]));
            $fwrite(fd, "hpr0 %0d hpr1 %0d hpr0b %0d hpr1b %0d ",
                    $signed(d_r0[1][inst]), $signed(d_r1[1][inst]),
                    $signed(d_r0b[1][inst]), $signed(d_r1b[1][inst]));
            $fwrite(fd, "fb %0d cf %0d mix %0d pan %0d ws %0d ",
                    $signed(d_tgt[inst][0]), $signed(d_tgt[inst][1]),
                    $signed(d_tgt[inst][2]), $signed(d_tgt[inst][3]),
                    $signed(d_tgt[inst][4]));
            if (inst == 0)
                $fwrite(fd, "hash %0d er %0d ew %0d\n", h0 + h1, rd0 + rd1, wr0 + wr1);
            else
                $fwrite(fd, "hash %0d er %0d ew %0d\n", h2 + h3, rd2 + rd3, wr2 + wr3);
        end
    endtask

    // ---------------- state initialization (engine load/reset) ----------
    initial begin
        for (i_ = 0; i_ < 2; i_ = i_ + 1) begin
            d_tlv[i_] = 0; d_tlt[i_] = 0; d_trv[i_] = 0; d_trt[i_] = 0;
            d_fbsign[i_] = 0; d_wpos[i_] = 0; d_clip[i_] = 0;
            d_lpon[i_] = 0; d_hpon[i_] = 0; d_first[i_] = 0;
            d_sg[i_] = 0; d_rl[i_] = 0;
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                d_cur[i_][j_] = 0; d_tgt[i_][j_] = 0;
                d_lag[0][i_][j_] = 0; d_lag[1][i_][j_] = 0;
                d_lagt[0][i_][j_] = 0; d_lagt[1][i_][j_] = 0;
            end
            d_r0[0][i_] = 0; d_r1[0][i_] = 0;
            d_r0b[0][i_] = 0; d_r1b[0][i_] = 0;
            d_r0[1][i_] = 0; d_r1[1][i_] = 0;
            d_r0b[1][i_] = 0; d_r1b[1][i_] = 0;
        end
        for (j_ = 0; j_ < 3; j_ = j_ + 1) begin
            for (k = 0; k < 5; k = k + 1) begin
                e_lag[j_][k] = 0; e_lagt[j_][k] = 0;
                e_r0[j_][0] = 0; e_r0[j_][1] = 0;
                e_r1[j_][0] = 0; e_r1[j_][1] = 0;
            end
        end
        e_gcur = ONE_G; e_gtgt = ONE_G; e_mcur = ONE_G; e_mtgt = ONE_G;
        e_bi = 0;
        if (!$value$plusargs("ZEROS=%s", zeros_name)) zeros_name = "line_zeros.hex";
        $readmemh(zeros_name, line_mem0);
        $readmemh(zeros_name, line_mem1);
        $readmemh(zeros_name, line_mem2);
        $readmemh(zeros_name, line_mem3);
    end

    // ---------------- main ----------------
    initial begin
        if (!$value$plusargs("PCONFIG=%d", PCONFIG)) PCONFIG = 1;
        if (!$value$plusargs("NBLOCKS=%d", N_BLOCKS)) N_BLOCKS = 1;
        if (!$value$plusargs("RENDER0=%d", RENDER0)) RENDER0 = 240;
        if (!$value$plusargs("TRACE=%s", trace_name)) trace_name = "tb_trace.txt";
        if (!$value$plusargs("INFILE=%s", fin_name)) fin_name = "in.hex";
        if (!$value$plusargs("CTRLFILE=%s", fct_name)) fct_name = "ctrl.hex";
        if (!$value$plusargs("SINC=%s", sinc_name)) sinc_name = "sinc_q29.hex";

        $readmemh(sinc_name, sinc);


        fd = $fopen(trace_name, "w");
        fin = $fopen(fin_name, "r");
        fct = $fopen(fct_name, "r");
        if (fd == 0 || fin == 0 || fct == 0) begin
            $display("FILE OPEN FAILURE");
            $finish;
        end

        first_step = 1;
        e_gcur = ONE_G; e_gtgt = ONE_G; e_mcur = ONE_G; e_mtgt = ONE_G;
        e_bi = 0;

        for (b = 0; b < N_BLOCKS; b = b + 1) begin
            chk = (b == 239) || (b == 240) || (b == 241) || (b == N_BLOCKS - 1) ||
                  ((b >= RENDER0) && (((b - RENDER0) % 64) == 0));

            rd64(fct, v64); a_q = $signed(v64[31:0]);   // master amplitude (control)
            if (PCONFIG == 1) begin
                apply_delay_ctrl(0, fct, first_step);
                apply_delay_ctrl(1, fct, first_step);
                rd64(fct, v64); d_sg[0] = $signed(v64[31:0]);
                rd64(fct, v64); d_rl[0] = $signed(v64[31:0]);
            end else if (PCONFIG == 2) begin
                apply_eq_ctrl(fct, first_step);
                e_bi = (e_bi + 1) & 7;
            end else begin
                apply_delay_ctrl(0, fct, first_step);
            end
            first_step = 0;

            if (PCONFIG == 2) begin
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); ilw[k] = $signed(v64[31:0]);
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); irw[k] = $signed(v64[31:0]);
                end
            end else begin
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); ilw[k] = $signed(v64[31:0]);
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); irw[k] = $signed(v64[31:0]);
                end
            end
            if (PCONFIG == 2) begin
                eq_block;
            end else begin
                cur_inst = 0;
                delay_block(0);
                if (PCONFIG == 1) begin
                    // save the insert output: the send block below overwrites
                    // olw/orw, and the return adds rl * send-FX-output (was:
                    // rl * send input -- a model-vs-tb wiring defect)
                    for (k = 0; k < 32; k = k + 1) begin
                        oins_l[k] = olw[k];
                        oins_r[k] = orw[k];
                        slw[k] = qmul_ga(d_sg[0], olw[k]);
                        srw[k] = qmul_ga(d_sg[0], orw[k]);
                    end
                    for (k = 0; k < 32; k = k + 1) begin
                        ilw[k] = slw[k];
                        irw[k] = srw[k];
                    end
                    cur_inst = 1;
                    delay_block(1);
                    for (k = 0; k < 32; k = k + 1) begin
                        olw[k] = qadd32(oins_l[k], qmul_ga(d_rl[0], olw[k]));
                        orw[k] = qadd32(oins_r[k], qmul_ga(d_rl[0], orw[k]));
                    end
                end
            end

            for (k = 0; k < 32; k = k + 1) begin
                olw[k] = clipi(qmul_ga(a_q, olw[k]), -HARD8, HARD8);
                orw[k] = clipi(qmul_ga(a_q, orw[k]), -HARD8, HARD8);
            end

            if (b >= RENDER0) begin
                $fwrite(fd, "O %0d", b);
                for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", olw[k]);
                for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", orw[k]);
                $fwrite(fd, "\n");
            end
            if (chk != 0) emit_state(b);
        end
        $fclose(fd);
        $display("TB DONE");
        $finish;
    end

endmodule
