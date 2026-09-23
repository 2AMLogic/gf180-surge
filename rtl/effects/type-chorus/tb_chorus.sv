// SXT-028c RTL behavioral schedule: Chorus (ChorusEffect<4>) slice.
//
// Reproduces the frozen fixed-point model (model/effects/type-chorus/
// chorus_model.py) exactly at declared checkpoints and on every per-instance
// output sample. All audio-rate arithmetic is computed here in the frozen
// conventions (exact products, round-half-up, saturating two's-complement).
// Block-rate quantities (lipol RAW targets, per-voice time-lag targets
// including the LFO term, biquad coefficient targets, flags) are
// CONTROL-PLANE: streamed from <slug>_ctrl.hex; the lfophase accumulators
// and LFO depth/rate live in the control plane (declared boundary, same
// class as the SXT-023 delay slice).
//
// The MONO delay line (2^18+12 x Q10.21) lives in external-memory arrays
// with transaction counters and an additive hash. The padding words
// line[2^18..2^18+11] are written only when wpos == 0 (engine semantics:
// the wrap reads into possibly-stale padding are reproduced exactly,
// never masked away).
//
// Wiring (plusargs):
//   +NINST=1|2        instances driven per block (disjoint memories)
//   +NBLOCKS=n        blocks
//   +RENDER0=b        first render block (outputs traced from here)
//   +RESETAT=b        optional: bulk clear + core reset before block b
//   +INFILE / +CTRLFILE / +INITFILE / +SINC / +ZEROS / +TRACE / +REV
//
// INITFILE: 3 x Q13.18 words per instance (the plain setvars(true)
// init-time lipol targets: fb, mix, width) — consumed at block 0 and at
// +RESETAT (engine fx-rebuild semantics: constructor state + plain
// targets; the time lags re-arm their first-run snap).
`timescale 1ns/1ps

module tb_chorus;
    integer NINST, N_BLOCKS, RENDER0, RESETAT, DEBUG;
    integer DBG0, DBG1;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, init_name, sinc_name, rev_name;

    localparam integer LINE_LEN = (1 << 18) + 12;
    localparam integer LINE_MASK = (1 << 18) - 1;

    // engine lag pair is float32 (ChorusEffect init: time[i].setRate(0.001))
    localparam signed [63:0] LPT_r  = 64'sh00000020C49BC00;   // f32(0.001) Q24.43
    localparam signed [63:0] LPIT_r = 64'sh0007FDF3B80000;    // f32(1-f32(0.001))
    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;   // 0.004 Q24.43
    localparam signed [63:0] DLPI_r = 64'sh07F7CED91687;      // (1-0.004) Q24.43
    localparam integer ONE_G   = 1 << 18;
    localparam integer HARD1   = 1 << 21;
    localparam signed [63:0] ONE43 = 64'sh0000080000000000;

    // frozen voicepan constants (init sqrt law, gainscale 1/sqrt(4), Q13.18)
    function automatic signed [31:0] pan_l(input integer j);
        case (j)
            0: pan_l = 32'sd131072;
            1: pan_l = 32'sd107020;
            2: pan_l = 32'sd75674;
            default: pan_l = 32'sd0;
        endcase
    endfunction
    function automatic signed [31:0] pan_r(input integer j);
        case (j)
            0: pan_r = 32'sd0;
            1: pan_r = 32'sd75674;
            2: pan_r = 32'sd107020;
            default: pan_r = 32'sd131072;
        endcase
    endfunction

    // ---------------- external mono lines (2 instances) ----------------
    reg [31:0] line_mem0 [0:LINE_LEN-1];
    reg [31:0] line_mem1 [0:LINE_LEN-1];
    longint unsigned rd0, wr0, h0, rd1, wr1, h1;
    reg [8*256:1] zeros_name;
    integer last_read;

    task line_access(input integer inst, input integer we,
                     input integer a, input integer wd);
        reg signed [63:0] w64, o64;
        begin
            w64 = $signed({{32{wd[31]}}, wd});
            if (inst == 0) begin
                if (we) begin
                    o64 = $signed({{32{line_mem0[a][31]}}, line_mem0[a]});
                    h0 = h0 + w64 - o64; line_mem0[a] = wd[31:0]; wr0 = wr0 + 1;
                end else begin
                    rd0 = rd0 + 1; last_read = $signed(line_mem0[a]);
                end
            end else begin
                if (we) begin
                    o64 = $signed({{32{line_mem1[a][31]}}, line_mem1[a]});
                    h1 = h1 + w64 - o64; line_mem1[a] = wd[31:0]; wr1 = wr1 + 1;
                end else begin
                    rd1 = rd1 + 1; last_read = $signed(line_mem1[a]);
                end
            end
        end
    endtask

    // ---------------- per-instance state ----------------
    reg signed [63:0] tlv   [0:1][0:3];
    reg signed [63:0] tlt   [0:1][0:3];
    reg signed [31:0] fb_cur [0:1]; reg signed [31:0] fb_tgt [0:1];
    reg signed [31:0] mx_cur [0:1]; reg signed [31:0] mx_tgt [0:1];
    reg signed [31:0] ws_cur [0:1]; reg signed [31:0] ws_tgt [0:1];
    reg signed [63:0] lp_lag [0:1][0:4];
    reg signed [63:0] hp_lag [0:1][0:4];
    reg signed [63:0] lp_r0 [0:1][0:1]; reg signed [63:0] lp_r1 [0:1][0:1];
    reg signed [63:0] hp_r0 [0:1][0:1]; reg signed [63:0] hp_r1 [0:1][0:1];
    reg signed [63:0] lp_lagt [0:1][0:4];
    reg signed [63:0] hp_lagt [0:1][0:4];
    integer           wpos [0:1];
    integer           lpon [0:1];
    integer           hpon [0:1];
    integer           first [0:1];
    integer           inst_init [0:1];
    longint unsigned  er [0:1];
    longint unsigned  ew [0:1];

    integer ilw [0:1][0:31];
    integer irw [0:1][0:31];
    integer tb_l [0:31];
    integer tb_r [0:31];

    // tap-checkpoint capture (observation only)
    integer tap_capture;
    integer xt [0:3][0:3][0:2];   // [sample k][voice][i_dt, ph, rp]

    reg [31:0] sinc [0:3083];
    reg [31:0] initwords [0:5];

    integer b, k, j, j2, ii, t_, chk;
    integer i_dt, ph, rp, base, w0, rd, fbk;
    integer tmp, tmp2, ss;
    longint signed vo, acc_l, acc_r;   // Q68 tap MAC: 32-bit wraps

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

    function automatic signed [63:0] zext32(input [31:0] x);
        zext32 = $signed({32'h0, x});
    endfunction

    function automatic signed [63:0] qmul_cc(input signed [63:0] a, input signed [63:0] b);
        reg signed [31:0] ah, bh;
        reg [31:0] al, bl;
        reg signed [63:0] t_hh;
        reg signed [95:0] t_hl, t_lh, tsum;
        reg signed [127:0] p;
        begin
            ah = a[63:32]; al = a[31:0];
            bh = b[63:32]; bl = b[31:0];
            t_hh = $signed(ah) * $signed(bh);
            t_hl = $signed(ah) * $signed({32'h0, bl});
            t_lh = $signed({32'h0, al}) * $signed(bh);
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

    function automatic integer sinc_phase(input integer i_d, input signed [63:0] v);
        reg signed [63:0] diff, scaled;
        begin
            diff = qsub64(((i_d + 1) * ONE43), v);
            if (diff >= 0) scaled = (diff * 256) >>> 43;
            else scaled = -(((-diff) * 256) >>> 43);
            sinc_phase = clipi(scaled, 0, 255);
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

    // ---------------- biquad sample (TDF2, per-sample coefficient lag) ----
    task bq_sample(input integer inst, input integer is_hp,
                   input integer inl, input integer inr,
                   output integer ol, output integer orr);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, il, ir, op, op2;
        begin
            if (is_hp == 0) begin
                for (t_ = 0; t_ < 5; t_ = t_ + 1)
                    lp_lag[inst][t_] = qadd64(qmul_cc(lp_lag[inst][t_], DLPI_r),
                                              qmul_cc(lp_lagt[inst][t_], DLP_r));
                a1_ = lp_lag[inst][0]; a2_ = lp_lag[inst][1];
                b0_ = lp_lag[inst][2]; b1_ = lp_lag[inst][3]; b2_ = lp_lag[inst][4];
                il = $signed(inl) <<< 22;
                op = qadd64(qmul_cc(il, b0_), lp_r0[inst][0]);
                lp_r0[inst][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)), lp_r1[inst][0]);
                lp_r1[inst][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
                ir = $signed(inr) <<< 22;
                op2 = qadd64(qmul_cc(ir, b0_), lp_r0[inst][1]);
                lp_r0[inst][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)), lp_r1[inst][1]);
                lp_r1[inst][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            end else begin
                for (t_ = 0; t_ < 5; t_ = t_ + 1)
                    hp_lag[inst][t_] = qadd64(qmul_cc(hp_lag[inst][t_], DLPI_r),
                                              qmul_cc(hp_lagt[inst][t_], DLP_r));
                a1_ = hp_lag[inst][0]; a2_ = hp_lag[inst][1];
                b0_ = hp_lag[inst][2]; b1_ = hp_lag[inst][3]; b2_ = hp_lag[inst][4];
                il = $signed(inl) <<< 22;
                op = qadd64(qmul_cc(il, b0_), hp_r0[inst][0]);
                hp_r0[inst][0] = qadd64(qsub64(qmul_cc(il, b1_), qmul_cc(a1_, op)), hp_r1[inst][0]);
                hp_r1[inst][0] = qsub64(qmul_cc(il, b2_), qmul_cc(a2_, op));
                ir = $signed(inr) <<< 22;
                op2 = qadd64(qmul_cc(ir, b0_), hp_r0[inst][1]);
                hp_r0[inst][1] = qadd64(qsub64(qmul_cc(ir, b1_), qmul_cc(a1_, op2)), hp_r1[inst][1]);
                hp_r1[inst][1] = qsub64(qmul_cc(ir, b2_), qmul_cc(a2_, op2));
            end
            ol = sat32((op + $signed(64'sd2097152)) >>> 22);
            orr = sat32((op2 + $signed(64'sd2097152)) >>> 22);
        end
    endtask

    // ---------------- chorus block datapath (one instance) ----------------
    integer out_l [0:31];
    integer out_r [0:31];
    integer fbb  [0:31];
    task chorus_block(input integer inst);
        begin
            for (k = 0; k < 32; k = k + 1) begin
                acc_l = 0; acc_r = 0;
                if (DEBUG != 0 && inst == 0 && b >= DBG0 && b <= DBG1)
                    $display("DBG tap b=%0d k=%0d", b, k);
                for (j = 0; j < 4; j = j + 1) begin
                    tlv[inst][j] = qadd64(qmul_cc(tlv[inst][j], LPIT_r),
                                          qmul_cc(tlt[inst][j], LPT_r));
                    i_dt = clipi(int_part(tlv[inst][j]), 32, (1 << 18) - 13);
                    rp = ((wpos[inst] - i_dt + k) - 12) & LINE_MASK;
                    ph = sinc_phase(i_dt, tlv[inst][j]);
                    if (tap_capture != 0 && k < 4) begin
                        xt[k][j][0] = i_dt; xt[k][j][1] = ph; xt[k][j][2] = rp;
                    end
                    if (DEBUG != 0 && inst == 0 && b >= DBG0 && b <= DBG1)
                        $display("DBG vt b=%0d k=%0d j=%0d i_dt %0d ph %0d rp %0d tlv %0d",
                                 b, k, j, i_dt, ph, rp, tlv[inst][j]);
                    base = ph * 12;
                    vo = 0;
                    for (t_ = 0; t_ < 12; t_ = t_ + 1) begin
                        line_access(inst, 0, rp + t_, 0);   // UNMASKED (padding!)
                        rd = last_read;
                        vo = vo + $signed(sinc[base + t_]) * $signed(rd);
                    end
                    acc_l = acc_l + pan_l(j) * vo;
                    acc_r = acc_r + pan_r(j) * vo;
                end
                // Q68 accumulator -> Q10.21: shift 47, round-half-up
                tb_l[k] = sat32((acc_l + $signed(64'sd70368744177664)) >>> 47);
                tb_r[k] = sat32((acc_r + $signed(64'sd70368744177664)) >>> 47);
            end
            if (lpon[inst] != 0)
                for (k = 0; k < 32; k = k + 1)
                    bq_sample(inst, 0, tb_l[k], tb_r[k], tb_l[k], tb_r[k]);
            if (hpon[inst] != 0)
                for (k = 0; k < 32; k = k + 1)
                    bq_sample(inst, 1, tb_l[k], tb_r[k], tb_l[k], tb_r[k]);
            // mono fbblock: (wetL + wetR) -> feedback ramp -> hardclip -> += in
            for (k = 0; k < 32; k = k + 1) begin
                fbk = qadd32(tb_l[k], tb_r[k]);
                if (DEBUG != 0 && inst == 0 && b >= DBG0 && b <= DBG1)
                    $display("DBG tb b=%0d k=%0d tb %0d fbg %0d",
                             b, k, tb_l[k], lip_val(fb_cur[inst], fb_tgt[inst], k));
                fbk = clipi(qmul_ga(lip_val(fb_cur[inst], fb_tgt[inst], k), fbk),
                            -HARD1, HARD1);
                fbb[k] = qadd32(qadd32(fbk, ilw[inst][k]), irw[inst][k]);
                if (DEBUG != 0 && inst == 0 && b >= DBG0 && b <= DBG1)
                    $display("DBG fbb b=%0d k=%0d fbb %0d", b, k, fbb[k]);
            end
            for (k = 0; k < 32; k = k + 1) begin
                w0 = (wpos[inst] + k) & LINE_MASK;
                line_access(inst, 1, w0, fbb[k]);
            end
            ew[inst] = ew[inst] + 32;
            if (wpos[inst] == 0) begin
                // padding words = buffer[0..11] just written this block
                // (model copies st.line[t]; no external read is issued)
                for (t_ = 0; t_ < 12; t_ = t_ + 1) begin
                    line_access(inst, 1, (1 << 18) + t_, fbb[t_]);
                end
                ew[inst] = ew[inst] + 12;
            end
            // width (mid/side halving exact: truncate toward zero)
            for (k = 0; k < 32; k = k + 1) begin
                tmp = $signed(tb_l[k]) + $signed(tb_r[k]);
                tmp2 = $signed(tb_l[k]) - $signed(tb_r[k]);
                tmp = (tmp >= 0) ? sat32(tmp >>> 1) : sat32(-((-tmp) >>> 1));
                tmp2 = (tmp2 >= 0) ? sat32(tmp2 >>> 1) : sat32(-((-tmp2) >>> 1));
                ss = qmul_ga(lip_val(ws_cur[inst], ws_tgt[inst], k), tmp2);
                tb_l[k] = qadd32(tmp, ss);
                tb_r[k] = qsub32(tmp, ss);
            end
            // mix crossfade: dry*(1-t) + wet*t
            for (k = 0; k < 32; k = k + 1) begin
                out_l[k] = qadd32(qmul_ga(qsub32(ONE_G, lip_val(mx_cur[inst], mx_tgt[inst], k)), ilw[inst][k]),
                                  qmul_ga(lip_val(mx_cur[inst], mx_tgt[inst], k), tb_l[k]));
                out_r[k] = qadd32(qmul_ga(qsub32(ONE_G, lip_val(mx_cur[inst], mx_tgt[inst], k)), irw[inst][k]),
                                  qmul_ga(lip_val(mx_cur[inst], mx_tgt[inst], k), tb_r[k]));
            end
            wpos[inst] = (wpos[inst] + 32) & LINE_MASK;
        end
    endtask

    // ---------------- control application ---------------------------------
    reg [63:0] v64;
    reg [31:0] v32;
    task apply_ctrl(input integer inst, input integer fh);
        integer j_;
        begin
            rd64(fh, v64); v32 = v64[31:0];
            lip_smooth(fb_cur[inst], fb_tgt[inst], $signed(v32));
            rd64(fh, v64); v32 = v64[31:0];
            lip_smooth(mx_cur[inst], mx_tgt[inst], $signed(v32));
            rd64(fh, v64); v32 = v64[31:0];
            lip_smooth(ws_cur[inst], ws_tgt[inst], $signed(v32));
            for (j_ = 0; j_ < 4; j_ = j_ + 1) begin
                rd64(fh, v64); tlt[inst][j_] = $signed(v64);
            end
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); lp_lagt[inst][j_] = $signed(v64);
            end
            for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                rd64(fh, v64); hp_lagt[inst][j_] = $signed(v64);
            end
            rd64(fh, v64);
            lpon[inst] = v64[0];
            hpon[inst] = v64[1];
            if (first[inst] != 0) begin
                // block 0: the model's first set_target snaps the time lags
                // (first-run) and the biquad coefficient lags instantize;
                // lipol state: cur=0, tgt=init words (preloaded)
                for (j_ = 0; j_ < 4; j_ = j_ + 1)
                    tlv[inst][j_] = tlt[inst][j_];
                for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                    lp_lag[inst][j_] = lp_lagt[inst][j_];
                    hp_lag[inst][j_] = hp_lagt[inst][j_];
                end
                first[inst] = 0;
            end
        end
    endtask

    // ---------------- reset (engine fx-rebuild semantics) -----------------
    task do_reset;
        integer i_, j_;
        begin
            for (i_ = 0; i_ < NINST; i_ = i_ + 1) begin
                for (w0 = 0; w0 < LINE_LEN; w0 = w0 + 1) begin
                    if (i_ == 0) line_mem0[w0] = 32'sd0;
                    else line_mem1[w0] = 32'sd0;
                end
                if (i_ == 0) begin
                    h0 = 0; rd0 = 0; wr0 = 0;
                end else begin
                    h1 = 0; rd1 = 0; wr1 = 0;
                end
                ew[i_] = 0;
                wpos[i_] = 0;
                lpon[i_] = 0; hpon[i_] = 0;
                fb_cur[i_] = 0; mx_cur[i_] = 0; ws_cur[i_] = 0;
                fb_tgt[i_] = $signed(initwords[i_*3 + 0]);
                mx_tgt[i_] = $signed(initwords[i_*3 + 1]);
                ws_tgt[i_] = $signed(initwords[i_*3 + 2]);
                for (j_ = 0; j_ < 4; j_ = j_ + 1) begin
                    tlv[i_][j_] = 0; tlt[i_][j_] = 0;
                end
                for (j_ = 0; j_ < 5; j_ = j_ + 1) begin
                    lp_lag[i_][j_] = 0; hp_lag[i_][j_] = 0;
                    lp_lagt[i_][j_] = 0; hp_lagt[i_][j_] = 0;
                end
                lp_r0[i_][0] = 0; lp_r1[i_][0] = 0; lp_r0[i_][1] = 0; lp_r1[i_][1] = 0;
                hp_r0[i_][0] = 0; hp_r1[i_][0] = 0; hp_r0[i_][1] = 0; hp_r1[i_][1] = 0;
                first[i_] = 1;
            end
        end
    endtask

    // ---------------- state trace -----------------------------------------
    task emit_state(input integer bb);
        integer i2_, j2_;
        begin
            for (i2_ = 0; i2_ < NINST; i2_ = i2_ + 1) begin
                $fwrite(fd, "T %0d %0d wpos %0d ", bb, i2_, wpos[i2_]);
                for (j2_ = 0; j2_ < 4; j2_ = j2_ + 1)
                    $fwrite(fd, "tlv%0d %0d ", j2_, $signed(tlv[i2_][j2_]));
                for (j2_ = 0; j2_ < 4; j2_ = j2_ + 1)
                    $fwrite(fd, "tlt%0d %0d ", j2_, $signed(tlt[i2_][j2_]));
                $fwrite(fd, "fb %0d mix %0d ws %0d ",
                        $signed(fb_tgt[i2_]), $signed(mx_tgt[i2_]), $signed(ws_tgt[i2_]));
                for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1)
                    $fwrite(fd, "lp%0d %0d ", j2_, $signed(lp_lag[i2_][j2_]));
                for (j2_ = 0; j2_ < 5; j2_ = j2_ + 1)
                    $fwrite(fd, "hp%0d %0d ", j2_, $signed(hp_lag[i2_][j2_]));
                $fwrite(fd, "lpr0 %0d lpr1 %0d lpr0b %0d lpr1b %0d ",
                        $signed(lp_r0[i2_][0]), $signed(lp_r1[i2_][0]),
                        $signed(lp_r0[i2_][1]), $signed(lp_r1[i2_][1]));
                $fwrite(fd, "hpr0 %0d hpr1 %0d hpr0b %0d hpr1b %0d ",
                        $signed(hp_r0[i2_][0]), $signed(hp_r1[i2_][0]),
                        $signed(hp_r0[i2_][1]), $signed(hp_r1[i2_][1]));
                if (i2_ == 0)
                    $fwrite(fd, "hash %0d er %0d ew %0d\n", h0, rd0, wr0);
                else
                    $fwrite(fd, "hash %0d er %0d ew %0d\n", h1, rd1, wr1);
            end
        end
    endtask

    // ---------------- main -------------------------------------------------
    initial begin
        if (!$value$plusargs("NINST=%d", NINST)) NINST = 1;
        if (!$value$plusargs("NBLOCKS=%d", N_BLOCKS)) N_BLOCKS = 1;
        if (!$value$plusargs("RENDER0=%d", RENDER0)) RENDER0 = 240;
        if (!$value$plusargs("RESETAT=%d", RESETAT)) RESETAT = -1;
        if (!$value$plusargs("DEBUG=%d", DEBUG)) DEBUG = 0;
        if (!$value$plusargs("DBG0=%d", DBG0)) DBG0 = 0;
        if (!$value$plusargs("DBG1=%d", DBG1)) DBG1 = -1;
        if (!$value$plusargs("TRACE=%s", trace_name)) trace_name = "tb_trace.txt";
        if (!$value$plusargs("INFILE=%s", fin_name)) fin_name = "in.hex";
        if (!$value$plusargs("CTRLFILE=%s", fct_name)) fct_name = "ctrl.hex";
        if (!$value$plusargs("INITFILE=%s", init_name)) init_name = "init.hex";
        if (!$value$plusargs("SINC=%s", sinc_name)) sinc_name = "sinc_q29.hex";
        if (!$value$plusargs("ZEROS=%s", zeros_name)) zeros_name = "line_zeros.hex";
        if (!$value$plusargs("REV=%s", rev_name)) rev_name = "00000000";

        $readmemh(sinc_name, sinc);
        $readmemh(zeros_name, line_mem0);
        $readmemh(zeros_name, line_mem1);
        $readmemh(init_name, initwords);

        fd = $fopen(trace_name, "w");
        fin = $fopen(fin_name, "r");
        fct = $fopen(fct_name, "r");
        if (fd == 0 || fin == 0 || fct == 0) begin
            $display("FILE OPEN FAILURE");
            $finish;
        end

        $fwrite(fd, "R %s\n", rev_name);

        h0 = 0; rd0 = 0; wr0 = 0; h1 = 0; rd1 = 0; wr1 = 0;
        for (b = 0; b < 2; b = b + 1) begin
            wpos[b] = 0; lpon[b] = 0; hpon[b] = 0;
            fb_cur[b] = 0; mx_cur[b] = 0; ws_cur[b] = 0;
            // constructor state + setvars(true): cur=0, tgt=init words
            fb_tgt[b] = $signed(initwords[b*3 + 0]);
            mx_tgt[b] = $signed(initwords[b*3 + 1]);
            ws_tgt[b] = $signed(initwords[b*3 + 2]);
            first[b] = 1;
            er[b] = 0; ew[b] = 0;
            for (j = 0; j < 4; j = j + 1) begin
                tlv[b][j] = 0; tlt[b][j] = 0;
            end
            for (j = 0; j < 5; j = j + 1) begin
                lp_lag[b][j] = 0; hp_lag[b][j] = 0;
                lp_lagt[b][j] = 0; hp_lagt[b][j] = 0;
            end
            lp_r0[b][0] = 0; lp_r1[b][0] = 0; lp_r0[b][1] = 0; lp_r1[b][1] = 0;
            hp_r0[b][0] = 0; hp_r1[b][0] = 0; hp_r0[b][1] = 0; hp_r1[b][1] = 0;
        end

        for (b = 0; b < N_BLOCKS; b = b + 1) begin
            if (b == RESETAT) do_reset;
            chk = (b == RENDER0 - 1) || (b == RENDER0) || (b == RENDER0 + 1) ||
                  (b == N_BLOCKS - 1) ||
                  ((b >= RENDER0) && (((b - RENDER0) % 64) == 0));
            tap_capture = (b == RENDER0 - 1) || (b == RENDER0) || (b == RENDER0 + 1) ||
                          (b == N_BLOCKS - 1) ||
                          ((b >= RENDER0) && (((b - RENDER0) % 16) == 0));
            // control words: NINST per block
            for (ii = 0; ii < NINST; ii = ii + 1)
                apply_ctrl(ii, fct);
            // input words: NINST x (32 L then 32 R) per block
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); ilw[ii][k] = $signed(v64[31:0]);
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); irw[ii][k] = $signed(v64[31:0]);
                end
            end
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                chorus_block(ii);
                if (b >= RENDER0) begin
                    $fwrite(fd, "O %0d %0d", b, ii);
                    for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_l[k]);
                    for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_r[k]);
                    $fwrite(fd, "\n");
                end
                if (tap_capture != 0) begin
                    $fwrite(fd, "X %0d %0d", b, ii);
                    for (k = 0; k < 4; k = k + 1)
                        for (j2 = 0; j2 < 4; j2 = j2 + 1)
                            $fwrite(fd, " %0d %0d %0d", xt[k][j2][0], xt[k][j2][1], xt[k][j2][2]);
                    $fwrite(fd, "\n");
                end
            end
            if (chk != 0) emit_state(b);
        end
        $fwrite(fd, "ER %0d %0d %0d %0d %0d %0d\n", rd0, wr0, rd1, wr1, h0, h1);
        $fclose(fd);
        $display("TB DONE");
        $finish;
    end

endmodule
