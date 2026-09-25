// SXT-028g RTL behavioral schedule: Phaser (sst-effects Phaser) slice.
//
// Reproduces the frozen fixed-point model (model/effects/type-phaser/
// phaser_model.py) EXACTLY on every per-instance output sample and at every
// declared checkpoint. All audio-rate arithmetic is computed here in the
// frozen conventions (exact products, round-half-up, saturating two's
// complement). Block-rate quantities (the APF / tone-filter coefficient
// targets, the feedback + tone lipol targets, the widthS/mix raw targets and
// the flags word) are CONTROL-PLANE: streamed from <slug>_ctrl.hex. The LFO
// phase accumulator, the FXModControl shapes and the tone->cutoff map live in
// the control plane (declared boundary, same class as the SXT-023 delay and
// SXT-028c chorus slices).
//
// The Phaser owns NO delay line: every state word below is small on-chip
// state and the audio-rate external-memory traffic is ZERO words/sample.
// The er/ew counters are therefore expected to stay 0 and are traced so a
// silent introduction of external traffic is caught at a checkpoint.
//
// Wiring (plusargs):
//   +NINST=1|2        instances driven per block (disjoint state)
//   +NBLOCKS=n        blocks
//   +RENDER0=b        first render block (outputs traced from here)
//   +RESETAT=b        optional: core reset before block b (panic / fx rebuild)
//   +INFILE / +CTRLFILE / +TRACE / +REV
//
// Control record per instance per block (every word one 16-hex-digit line;
// 32-bit quantities occupy the low half):
//   0        flags: bit0 setvars(bi==0), bit1 tone_on, bits[9:4] n_stages
//   1        mix raw target      (Q13.18, applied EVERY block)
//   2        widthS raw target   (Q13.18, applied on setvars)
//   3        feedback newValue   (Q24.43)
//   4        tone newValue       (Q24.43)
//   5..9     tone lp coefficient targets a1 a2 b0 b1 b2 (Q24.43)
//   10..14   tone hp coefficient targets a1 a2 b0 b1 b2 (Q24.43)
//   15..     5 coefficient targets per configured APF biquad unit, unit
//            major; NU = (n_stages < 2) ? 4 : 2*n_stages units (the legacy
//            branch of Phaser.h configures 4 units and runs 2 of them).
`timescale 1ns/1ps

module tb_phaser;
    integer NINST, N_BLOCKS, RENDER0, RESETAT;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, rev_name;

    localparam integer MAXU = 32;                 // 2 * Phaser.h max_stages
    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;  // 0.004  Q24.43
    localparam signed [63:0] DLPI_r = 64'sh07F7CED91687;     // 1-0.004 Q24.43
    localparam integer ONE_G  = 1 << 18;
    localparam integer CLAMP_A = 32 * (1 << 21);  // Phaser.h clamp(dL,-32,32)

    // ---------------- per-instance state ----------------
    reg signed [63:0] apf_lag [0:1][0:MAXU-1][0:4];
    reg signed [63:0] apf_tgt [0:1][0:MAXU-1][0:4];
    reg signed [63:0] apf_r0  [0:1][0:MAXU-1];
    reg signed [63:0] apf_r1  [0:1][0:MAXU-1];
    integer           apf_fst [0:1][0:MAXU-1];

    reg signed [63:0] lp_lag [0:1][0:4];
    reg signed [63:0] lp_tgt [0:1][0:4];
    reg signed [63:0] hp_lag [0:1][0:4];
    reg signed [63:0] hp_tgt [0:1][0:4];
    reg signed [63:0] lp_r0 [0:1][0:1]; reg signed [63:0] lp_r1 [0:1][0:1];
    reg signed [63:0] hp_r0 [0:1][0:1]; reg signed [63:0] hp_r1 [0:1][0:1];
    integer           lp_fst [0:1]; integer hp_fst [0:1];

    reg signed [63:0] fb_v [0:1]; reg signed [63:0] fb_new [0:1];
    reg signed [63:0] fb_dv [0:1]; integer fb_fst [0:1];
    reg signed [63:0] tn_v [0:1]; reg signed [63:0] tn_new [0:1];
    reg signed [63:0] tn_dv [0:1]; integer tn_fst [0:1];

    reg signed [31:0] mx_cur [0:1]; reg signed [31:0] mx_tgt [0:1];
    reg signed [31:0] ws_cur [0:1]; reg signed [31:0] ws_tgt [0:1];

    reg signed [31:0] dl_s [0:1]; reg signed [31:0] dr_s [0:1];
    integer nstg [0:1];
    integer tone_on [0:1];
    longint unsigned er [0:1];
    longint unsigned ew [0:1];

    integer ilw [0:1][0:31];
    integer irw [0:1][0:31];
    integer wl [0:31];
    integer wr [0:31];
    integer out_l [0:31];
    integer out_r [0:31];

    // cascade checkpoint capture (observation only): per sample k<4, per
    // stage, the post-stage (dL, dR) pair — pins the cascade ORDER
    integer xs [0:3][0:15][0:1];
    integer stage_capture;

    integer b, k, s, u, t_, ii, j_;
    integer setv, nu;
    reg signed [31:0] dlv, drv;
    integer tmp, tmp2, ss;
    reg [63:0] hsh;

    // ---------------- fixed-point helpers ----------------
    function automatic signed [31:0] sat32(input signed [63:0] v);
        if (v > $signed(64'd2147483647)) sat32 = 32'sd2147483647;
        else if (v < -$signed(64'd2147483647)) sat32 = -32'sd2147483647;
        else sat32 = v[31:0];
    endfunction

    function automatic signed [31:0] sat32w(input signed [95:0] v);
        if (v > $signed(96'd2147483647)) sat32w = 32'sd2147483647;
        else if (v < -$signed(96'd2147483647)) sat32w = -32'sd2147483647;
        else sat32w = v[31:0];
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

    function automatic signed [31:0] qadd32(input signed [31:0] a, input signed [31:0] b);
        qadd32 = sat32($signed({{33{a[31]}}, a}) + $signed({{33{b[31]}}, b}));
    endfunction

    function automatic signed [31:0] qsub32(input signed [31:0] a, input signed [31:0] b);
        qsub32 = qadd32(a, ~b + 32'sd1);
    endfunction

    // Q24.43 x Q24.43 -> Q24.43, exact product, round-half-up, saturating
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

    // Q10.21 x Q24.43 -> Q10.21 (the feedback multiply)
    function automatic signed [31:0] qmul_ac(input signed [31:0] a, input signed [63:0] b);
        reg signed [95:0] p;
        begin
            p = $signed({{64{a[31]}}, a}) * $signed({{32{b[63]}}, b});
            qmul_ac = sat32w((p + $signed(96'd4398046511104)) >>> 43);
        end
    endfunction

    // Q13.18 x Q10.21 -> Q10.21 (gain ramps)
    function automatic signed [31:0] qmul_ga(input signed [31:0] a, input signed [31:0] b);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b);
            qmul_ga = sat32((p + $signed(64'd131072)) >>> 18);
        end
    endfunction

    function automatic integer clipi(input integer v, input integer lo, input integer hi);
        if (v < lo) clipi = lo;
        else if (v > hi) clipi = hi;
        else clipi = v;
    endfunction

    // lipol_sse line value: current + round((target-current)*(k+1)/32)
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

    // lipol_sse::set_target_smoothed: current = target; target = 0.25f + 0.75*target
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

    // ---------------- MONO APF biquad sample (TDF2 + per-sample lag) -------
    task apf_sample(input integer inst, input integer unit,
                    input signed [31:0] xin, output signed [31:0] yout);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, xi, op;
        begin
            for (t_ = 0; t_ < 5; t_ = t_ + 1)
                apf_lag[inst][unit][t_] =
                    qadd64(qmul_cc(apf_lag[inst][unit][t_], DLPI_r),
                           qmul_cc(apf_tgt[inst][unit][t_], DLP_r));
            a1_ = apf_lag[inst][unit][0]; a2_ = apf_lag[inst][unit][1];
            b0_ = apf_lag[inst][unit][2]; b1_ = apf_lag[inst][unit][3];
            b2_ = apf_lag[inst][unit][4];
            xi = $signed({{32{xin[31]}}, xin}) <<< 22;
            op = qadd64(qmul_cc(xi, b0_), apf_r0[inst][unit]);
            apf_r0[inst][unit] = qadd64(qsub64(qmul_cc(xi, b1_), qmul_cc(a1_, op)),
                                        apf_r1[inst][unit]);
            apf_r1[inst][unit] = qsub64(qmul_cc(xi, b2_), qmul_cc(a2_, op));
            yout = sat32((op + $signed(64'sd2097152)) >>> 22);
        end
    endtask

    // ---------------- STEREO tone biquad sample ---------------------------
    task bq_sample(input integer inst, input integer is_hp,
                   input integer inl, input integer inr,
                   output integer ol, output integer orr);
        reg signed [63:0] a1_, a2_, b0_, b1_, b2_, il, ir, op, op2;
        begin
            if (is_hp == 0) begin
                for (t_ = 0; t_ < 5; t_ = t_ + 1)
                    lp_lag[inst][t_] = qadd64(qmul_cc(lp_lag[inst][t_], DLPI_r),
                                              qmul_cc(lp_tgt[inst][t_], DLP_r));
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
                                              qmul_cc(hp_tgt[inst][t_], DLP_r));
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

    // ---------------- phaser block datapath (one instance) ----------------
    task phaser_block(input integer inst);
        begin
            for (k = 0; k < 32; k = k + 1) begin
                // lipol<float,BS,true>::process(): v += dv
                fb_v[inst] = qadd64(fb_v[inst], fb_dv[inst]);
                tn_v[inst] = qadd64(tn_v[inst], tn_dv[inst]);
                dlv = qadd32(ilw[inst][k], qmul_ac(dl_s[inst], fb_v[inst]));
                drv = qadd32(irw[inst][k], qmul_ac(dr_s[inst], fb_v[inst]));
                dlv = clipi(dlv, -CLAMP_A, CLAMP_A);
                drv = clipi(drv, -CLAMP_A, CLAMP_A);
                for (s = 0; s < nstg[inst]; s = s + 1) begin
                    apf_sample(inst, 2*s,     dlv, dlv);
                    apf_sample(inst, 2*s + 1, drv, drv);
                    if (stage_capture != 0 && k < 4) begin
                        xs[k][s][0] = dlv; xs[k][s][1] = drv;
                    end
                end
                dl_s[inst] = dlv; dr_s[inst] = drv;
                wl[k] = dlv; wr[k] = drv;
            end
            if (tone_on[inst] != 0) begin
                for (k = 0; k < 32; k = k + 1)
                    bq_sample(inst, 0, wl[k], wr[k], wl[k], wr[k]);
                for (k = 0; k < 32; k = k + 1)
                    bq_sample(inst, 1, wl[k], wr[k], wl[k], wr[k]);
            end
            // applyWidth: encodeMS, widthS.multiply_block(S), decodeMS
            for (k = 0; k < 32; k = k + 1) begin
                tmp  = $signed(wl[k]) + $signed(wr[k]);
                tmp2 = $signed(wl[k]) - $signed(wr[k]);
                tmp  = (tmp  >= 0) ? sat32(tmp  >>> 1) : sat32(-((-tmp)  >>> 1));
                tmp2 = (tmp2 >= 0) ? sat32(tmp2 >>> 1) : sat32(-((-tmp2) >>> 1));
                ss = qmul_ga(lip_val(ws_cur[inst], ws_tgt[inst], k), tmp2);
                wl[k] = qadd32(tmp, ss);
                wr[k] = qsub32(tmp, ss);
            end
            // mix crossfade: dry*(1-t) + wet*t
            for (k = 0; k < 32; k = k + 1) begin
                out_l[k] = qadd32(qmul_ga(qsub32(ONE_G, lip_val(mx_cur[inst], mx_tgt[inst], k)),
                                          ilw[inst][k]),
                                  qmul_ga(lip_val(mx_cur[inst], mx_tgt[inst], k), wl[k]));
                out_r[k] = qadd32(qmul_ga(qsub32(ONE_G, lip_val(mx_cur[inst], mx_tgt[inst], k)),
                                          irw[inst][k]),
                                  qmul_ga(lip_val(mx_cur[inst], mx_tgt[inst], k), wr[k]));
            end
        end
    endtask

    // ---------------- control application ---------------------------------
    reg [63:0] v64;
    reg [63:0] cw [0:14];
    reg [63:0] aw [0:MAXU*5-1];
    task apply_ctrl(input integer inst, input integer fh);
        integer i_, uu, nn;
        begin
            for (i_ = 0; i_ < 15; i_ = i_ + 1) begin
                rd64(fh, v64); cw[i_] = v64;
            end
            setv = cw[0][0];
            tone_on[inst] = cw[0][1];
            nn = cw[0][9:4];
            nstg[inst] = nn;
            nu = (nn < 2) ? 4 : 2*nn;
            for (i_ = 0; i_ < nu*5; i_ = i_ + 1) begin
                rd64(fh, v64); aw[i_] = v64;
            end
            if (setv != 0) begin
                for (uu = 0; uu < nu; uu = uu + 1) begin
                    for (i_ = 0; i_ < 5; i_ = i_ + 1)
                        apf_tgt[inst][uu][i_] = $signed(aw[uu*5 + i_]);
                    if (apf_fst[inst][uu] != 0) begin
                        for (i_ = 0; i_ < 5; i_ = i_ + 1)
                            apf_lag[inst][uu][i_] = $signed(aw[uu*5 + i_]);
                        apf_fst[inst][uu] = 0;
                    end
                end
                for (i_ = 0; i_ < 5; i_ = i_ + 1) lp_tgt[inst][i_] = $signed(cw[5 + i_]);
                if (lp_fst[inst] != 0) begin
                    for (i_ = 0; i_ < 5; i_ = i_ + 1) lp_lag[inst][i_] = $signed(cw[5 + i_]);
                    lp_fst[inst] = 0;
                end
                for (i_ = 0; i_ < 5; i_ = i_ + 1) hp_tgt[inst][i_] = $signed(cw[10 + i_]);
                if (hp_fst[inst] != 0) begin
                    for (i_ = 0; i_ < 5; i_ = i_ + 1) hp_lag[inst][i_] = $signed(cw[10 + i_]);
                    hp_fst[inst] = 0;
                end
                // lipol<float,BS,true>::newValue
                fb_v[inst] = fb_new[inst];
                fb_new[inst] = $signed(cw[3]);
                if (fb_fst[inst] != 0) begin
                    fb_v[inst] = $signed(cw[3]); fb_fst[inst] = 0;
                end
                // dv = (new_v - v) * bs_inv; bs_inv = 1/256 (Q24.43 = 2^35)
                fb_dv[inst] = qmul_cc(qsub64(fb_new[inst], fb_v[inst]),
                                      64'sh0000000800000000);
                tn_v[inst] = tn_new[inst];
                tn_new[inst] = $signed(cw[4]);
                if (tn_fst[inst] != 0) begin
                    tn_v[inst] = $signed(cw[4]); tn_fst[inst] = 0;
                end
                // bs_inv = 1/32 (Q24.43 = 2^38)
                tn_dv[inst] = qmul_cc(qsub64(tn_new[inst], tn_v[inst]),
                                      64'sh0000004000000000);
                lip_smooth(ws_cur[inst], ws_tgt[inst], $signed(cw[2][31:0]));
            end
            // mix target is refreshed EVERY block (Phaser::processBlock)
            lip_smooth(mx_cur[inst], mx_tgt[inst], $signed(cw[1][31:0]));
        end
    endtask

    // ---------------- reset (initialize() / suspendProcessing()) ----------
    task clear_inst(input integer i_);
        integer uu, j2;
        begin
            dl_s[i_] = 0; dr_s[i_] = 0;
            for (uu = 0; uu < MAXU; uu = uu + 1) begin
                for (j2 = 0; j2 < 5; j2 = j2 + 1) begin
                    apf_lag[i_][uu][j2] = 0; apf_tgt[i_][uu][j2] = 0;
                end
                apf_r0[i_][uu] = 0; apf_r1[i_][uu] = 0; apf_fst[i_][uu] = 1;
            end
            for (j2 = 0; j2 < 5; j2 = j2 + 1) begin
                lp_lag[i_][j2] = 0; lp_tgt[i_][j2] = 0;
                hp_lag[i_][j2] = 0; hp_tgt[i_][j2] = 0;
            end
            lp_r0[i_][0] = 0; lp_r1[i_][0] = 0; lp_r0[i_][1] = 0; lp_r1[i_][1] = 0;
            hp_r0[i_][0] = 0; hp_r1[i_][0] = 0; hp_r0[i_][1] = 0; hp_r1[i_][1] = 0;
            lp_fst[i_] = 1; hp_fst[i_] = 1;
            fb_v[i_] = 0; fb_new[i_] = 0; fb_dv[i_] = 0; fb_fst[i_] = 1;
            tn_v[i_] = 0; tn_new[i_] = 0; tn_dv[i_] = 0; tn_fst[i_] = 1;
            ws_cur[i_] = 0; ws_tgt[i_] = 0;
            // initialize(): mix.set_target(1.f) then mix.instantize()
            mx_cur[i_] = ONE_G; mx_tgt[i_] = ONE_G;
            tone_on[i_] = 0; nstg[i_] = 4;
            er[i_] = 0; ew[i_] = 0;
        end
    endtask

    // ---------------- state trace -----------------------------------------
    task emit_state(input integer bb);
        integer i2, uu, j2;
        begin
            for (i2 = 0; i2 < NINST; i2 = i2 + 1) begin
                hsh = 64'd0;
                for (uu = 0; uu < 2*nstg[i2]; uu = uu + 1) begin
                    for (j2 = 0; j2 < 5; j2 = j2 + 1)
                        hsh = hsh * 64'd1000003 + apf_lag[i2][uu][j2];
                    for (j2 = 0; j2 < 5; j2 = j2 + 1)
                        hsh = hsh * 64'd1000003 + apf_tgt[i2][uu][j2];
                    hsh = hsh * 64'd1000003 + apf_r0[i2][uu];
                    hsh = hsh * 64'd1000003 + apf_r1[i2][uu];
                end
                $fwrite(fd, "T %0d %0d dl %0d dr %0d fbv %0d fbdv %0d fbnew %0d ",
                        bb, i2, dl_s[i2], dr_s[i2], $signed(fb_v[i2]),
                        $signed(fb_dv[i2]), $signed(fb_new[i2]));
                $fwrite(fd, "tonev %0d tonedv %0d tonenew %0d ",
                        $signed(tn_v[i2]), $signed(tn_dv[i2]), $signed(tn_new[i2]));
                $fwrite(fd, "mixc %0d mixt %0d wsc %0d wst %0d ",
                        $signed(mx_cur[i2]), $signed(mx_tgt[i2]),
                        $signed(ws_cur[i2]), $signed(ws_tgt[i2]));
                for (j2 = 0; j2 < 5; j2 = j2 + 1)
                    $fwrite(fd, "lp%0d %0d ", j2, $signed(lp_lag[i2][j2]));
                for (j2 = 0; j2 < 5; j2 = j2 + 1)
                    $fwrite(fd, "hp%0d %0d ", j2, $signed(hp_lag[i2][j2]));
                $fwrite(fd, "lpr0 %0d lpr1 %0d lpr0b %0d lpr1b %0d ",
                        $signed(lp_r0[i2][0]), $signed(lp_r1[i2][0]),
                        $signed(lp_r0[i2][1]), $signed(lp_r1[i2][1]));
                $fwrite(fd, "hpr0 %0d hpr1 %0d hpr0b %0d hpr1b %0d ",
                        $signed(hp_r0[i2][0]), $signed(hp_r1[i2][0]),
                        $signed(hp_r0[i2][1]), $signed(hp_r1[i2][1]));
                $fwrite(fd, "apfhash %0d er %0d ew %0d\n", hsh, er[i2], ew[i2]);
            end
        end
    endtask

    // ---------------- main -------------------------------------------------
    initial begin
        if (!$value$plusargs("NINST=%d", NINST)) NINST = 1;
        if (!$value$plusargs("NBLOCKS=%d", N_BLOCKS)) N_BLOCKS = 1;
        if (!$value$plusargs("RENDER0=%d", RENDER0)) RENDER0 = 0;
        if (!$value$plusargs("RESETAT=%d", RESETAT)) RESETAT = -1;
        if (!$value$plusargs("TRACE=%s", trace_name)) trace_name = "tb_trace.txt";
        if (!$value$plusargs("INFILE=%s", fin_name)) fin_name = "in.hex";
        if (!$value$plusargs("CTRLFILE=%s", fct_name)) fct_name = "ctrl.hex";
        if (!$value$plusargs("REV=%s", rev_name)) rev_name = "00000000";

        fd = $fopen(trace_name, "w");
        fin = $fopen(fin_name, "r");
        fct = $fopen(fct_name, "r");
        if (fd == 0 || fin == 0 || fct == 0) begin
            $display("FILE OPEN FAILURE");
            $finish;
        end
        $fwrite(fd, "R %s\n", rev_name);

        for (ii = 0; ii < 2; ii = ii + 1) clear_inst(ii);

        for (b = 0; b < N_BLOCKS; b = b + 1) begin
            if (b == RESETAT)
                for (ii = 0; ii < NINST; ii = ii + 1) clear_inst(ii);
            stage_capture = (b == RENDER0) || (b == N_BLOCKS - 1) ||
                            ((b >= RENDER0) && (((b - RENDER0) % 16) == 0));
            for (ii = 0; ii < NINST; ii = ii + 1)
                apply_ctrl(ii, fct);
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); ilw[ii][k] = $signed(v64[31:0]);
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); irw[ii][k] = $signed(v64[31:0]);
                end
            end
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                phaser_block(ii);
                if (b >= RENDER0) begin
                    $fwrite(fd, "O %0d %0d", b, ii);
                    for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_l[k]);
                    for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_r[k]);
                    $fwrite(fd, "\n");
                end
                if (stage_capture != 0) begin
                    $fwrite(fd, "X %0d %0d", b, ii);
                    for (k = 0; k < 4; k = k + 1)
                        for (s = 0; s < nstg[ii]; s = s + 1)
                            $fwrite(fd, " %0d %0d", xs[k][s][0], xs[k][s][1]);
                    $fwrite(fd, "\n");
                end
            end
            if ((b == RENDER0) || (b == N_BLOCKS - 1) ||
                ((b >= RENDER0) && (((b - RENDER0) % 16) == 0)))
                emit_state(b);
        end
        $fwrite(fd, "ER %0d %0d %0d %0d\n", er[0], ew[0], er[1], ew[1]);
        $fclose(fd);
        $display("TB DONE");
        $finish;
    end

endmodule
