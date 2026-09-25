// GENERATED negative-control mutant of tb_conditioner.sv by
// tools/compare_rtl_model_conditioner.py -- must FAIL exactness.
// SXT-028b RTL behavioral schedule: Conditioner (ConditionerEffect) slice.
//
// Reproduces the frozen fixed-point model
// (model/effects/type-conditioner/conditioner_model.py) EXACTLY: every
// per-instance output sample and every declared per-block checkpoint
// (tools/compare_rtl_model_conditioner.py compares with integer equality).
// This is claim (1) only (RTL == frozen model); it says nothing about
// agreement with the pinned Surge engine (claim 2, BLOCKED on this host).
//
// Frozen arithmetic (model/effects/qmath.py): exact products, round-half-up
// (add 2^(s-1), arithmetic shift), saturation to [-2^(w-1), 2^(w-1)-1].
// Audio Q10.21 s32, lipol ramps Q13.18 s32, biquad/envelope/gain Q24.43 s64.
//
// Control plane (streamed per block per instance, CTRL_WORDS = 22 x 64-bit
// hex words): attack, release (Q24.43); ampL, ampR, width, postamp RAW
// lipol targets (Q13.18); 15 biquad coefficient targets (band1, band2, hp:
// a1 a2 b0 b1 b2, Q24.43); flags word:
//   bit0 bass on, bit1 treble on, bit2 side-HP on,
//   bit3 CONTROL_ONLY (Effect::process_ringout chose process_only_control),
//   bit4 SUSPEND before this block (engine suspend() == init()),
//   bit5 FRESH before this block (patch load: object re-spawned + init()).
// The ringout counter and lifecycle decisions are scheduler/control-plane
// (Effect base class); the RTL executes what the flags say.
//
// Per-instance state is on-chip register arrays indexed by instance; no
// array is shared between instances (the mutant benches break exactly that).
//
// Plusargs: +NINST=1|2 +NBLOCKS=n +TRACE= +INFILE= +CTRLFILE= +REV=<8 hex>
// NOTE (iverilog): array elements are never passed to task inout/output
// ports -- iverilog 13 mis-writes such ports back (found in the first draft
// of this bench); all tasks operate on module-level scratch registers.
`timescale 1ns/1ps

module tb_conditioner;
    integer NINST, N_BLOCKS;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, rev_name;

    localparam integer LOOKAHEAD_MASK = 127;
    localparam integer LA_READ_INDEX = 126;
    localparam signed [63:0] ONE_C = 64'sh0000080000000000;   // 1.0 Q24.43
    // BiquadFilter d_lp = 0.004 and 1 - d_lp, Q24.43 (delay_model.D_LP/D_LPINV)
    localparam signed [63:0] DLP_C  = 64'sh000000083126e979;
    localparam signed [63:0] DLPI_C = 64'sh000007f7ced91687;
    localparam signed [31:0] Q25_G = 32'sd65536;      // 0.25 Q13.18
    localparam signed [31:0] Q75_G = 32'sd196608;     // 0.75 Q13.18

    // ---------------- per-instance state ------------------------------
    reg signed [63:0] bq_lag  [0:1][0:2][0:4];
    reg signed [63:0] bq_tgt  [0:1][0:2][0:4];
    reg signed [63:0] bq_r0   [0:1][0:2][0:1];
    reg signed [63:0] bq_r1   [0:1][0:2][0:1];
    integer           bq_first [0:1][0:2];
    reg signed [31:0] lp_cur [0:1][0:3];   // 0 ampL, 1 ampR, 2 width, 3 postamp
    reg signed [31:0] lp_tgt [0:1][0:3];
    reg signed [31:0] dly_l  [0:1][0:127];
    reg signed [31:0] dly_r  [0:1][0:127];
    reg signed [63:0] lamax  [0:1][0:127];
    integer           bufpos [0:1];
    reg signed [63:0] flam   [0:1];
    reg signed [63:0] flam2  [0:1];
    reg signed [63:0] gain_r [0:1];
    reg [63:0]        rhash  [0:1];

    // ---------------- per-block control (per instance) ----------------
    reg signed [63:0] cw [0:1][0:21];

    // ---------------- scratch ----------------------------------------
    reg signed [31:0] in_l [0:1][0:31];
    reg signed [31:0] in_r [0:1][0:31];
    reg signed [31:0] dl [0:31];
    reg signed [31:0] dr [0:31];
    reg signed [31:0] ms_m [0:31];
    reg signed [31:0] ms_s [0:31];
    reg signed [31:0] out_l [0:31];
    reg signed [31:0] out_r [0:31];
    reg signed [31:0] bq_xl, bq_xr, bq_yl, bq_yr;
    reg [63:0] v64;
    integer b, k, ii;

    // ---------------- frozen fixed-point helpers ----------------------
    function automatic signed [31:0] sat32(input signed [127:0] v);
        if (v > 128'sd2147483647) sat32 = 32'sh7fffffff;
        else if (v < -128'sd2147483648) sat32 = 32'sh80000000;
        else sat32 = v[31:0];
    endfunction

    function automatic signed [63:0] sat64(input signed [127:0] v);
        if (v > 128'sd9223372036854775807) sat64 = 64'sh7fffffffffffffff;
        else if (v < -128'sd9223372036854775808) sat64 = 64'sh8000000000000000;
        else sat64 = v[63:0];
    endfunction

    function automatic signed [127:0] x64(input signed [63:0] a);
        x64 = {{64{a[63]}}, a};
    endfunction

    function automatic signed [127:0] x32(input signed [31:0] a);
        x32 = {{96{a[31]}}, a};
    endfunction

    function automatic signed [63:0] add_c(input signed [63:0] a, input signed [63:0] c);
        add_c = sat64(x64(a) + x64(c));
    endfunction
    function automatic signed [63:0] sub_c(input signed [63:0] a, input signed [63:0] c);
        sub_c = sat64(x64(a) - x64(c));
    endfunction
    function automatic signed [31:0] add_a(input signed [31:0] a, input signed [31:0] c);
        add_a = sat32(x32(a) + x32(c));
    endfunction
    function automatic signed [31:0] sub_a(input signed [31:0] a, input signed [31:0] c);
        sub_a = sat32(x32(a) - x32(c));
    endfunction

    // Q24.43 x Q24.43 -> Q24.43 (s = 43)
    function automatic signed [63:0] mul_cc(input signed [63:0] a, input signed [63:0] c);
        reg signed [127:0] p;
        begin
            p = x64(a) * x64(c);
            mul_cc = sat64((p + (128'sd1 <<< 42)) >>> 43);
        end
    endfunction

    // Q13.18 x (Q13.18 | Q10.21) -> same as 2nd operand (s = 18)
    function automatic signed [31:0] mul_g(input signed [31:0] g, input signed [31:0] x);
        reg signed [127:0] p;
        begin
            p = x32(g) * x32(x);
            mul_g = sat32((p + (128'sd1 <<< 17)) >>> 18);
        end
    endfunction

    // Q24.43 x Q10.21 -> Q10.21 (s = 43)
    function automatic signed [31:0] mul_ca(input signed [63:0] c, input signed [31:0] x);
        reg signed [127:0] p;
        begin
            p = x64(c) * x32(x);
            mul_ca = sat32((p + (128'sd1 <<< 42)) >>> 43);
        end
    endfunction

    // Q10.21 magnitude squared -> Q24.43 (s = -1: exact promote, << 1)
    function automatic signed [63:0] sq_ac(input signed [63:0] m);
        sq_ac = sat64((x64(m) * x64(m)) <<< 1);
    endfunction

    // floor(sqrt(num)), digit-by-digit (standard; not derived from Surge)
    function automatic [63:0] isqrt128(input [127:0] num);
        reg [127:0] rem, root, trial;
        integer i;
        begin
            rem = 0; root = 0;
            for (i = 63; i >= 0; i = i - 1) begin
                rem = (rem << 2) | ((num >> (2 * i)) & 128'd3);
                trial = (root << 2) | 128'd1;
                root = root << 1;
                if (rem >= trial) begin
                    rem = rem - trial;
                    root = root | 128'd1;
                end
            end
            isqrt128 = root[63:0];
        end
    endfunction

    function automatic signed [63:0] sqrt_c(input signed [63:0] x);
        reg [127:0] sh;
        begin
            if (x <= 0) sqrt_c = 64'sd0;
            else begin
                sh = {64'd0, x} << 43;
                sqrt_c = sat64({64'd0, isqrt128(sh)});
            end
        end
    endfunction

    // ONE_C / d, Q24.43, round-half-up (qmath.qdiv, d > 0 here: d >= ~1.0)
    function automatic signed [63:0] recip_c(input signed [63:0] d);
        reg [127:0] q;
        begin
            q = ((128'd1 << 86) + ({64'd0, d} >> 1)) / {64'd0, d};
            recip_c = sat64(q);
        end
    endfunction

    // lipol line value: cur + round((tgt-cur)*(i+1)/32), sign-symmetric
    function automatic signed [31:0] lip_val(input signed [31:0] cur,
                                             input signed [31:0] tgt, input integer i);
        reg signed [127:0] d, r;
        begin
            d = x32(tgt) - x32(cur);
            if (d >= 0) r = x32(cur) + ((d * (i + 1) + 16) >>> 5);
            else r = x32(cur) - (((-d) * (i + 1) + 16) >>> 5);
            lip_val = r[31:0];
        end
    endfunction

    function automatic signed [31:0] half_tz(input signed [127:0] v);
        reg signed [127:0] r;
        begin
            if (v >= 0) r = v >>> 1; else r = -((-v) >>> 1);
            half_tz = r[31:0];
        end
    endfunction

    function automatic signed [63:0] abs64(input signed [31:0] v);
        abs64 = (v < 0) ? -x64({{32{v[31]}}, v}) : {{32{v[31]}}, v};
    endfunction

    task automatic rd64(input integer fh);
        integer c;
        begin
            c = $fscanf(fh, "%x\n", v64);
            if (c <= 0) begin
                $display("STIMULUS UNDERRUN");
                $finish;
            end
        end
    endtask

    // ---------------- biquad: one stereo sample (TDF2, per-sample lag) --
    // inputs bq_xl/bq_xr, outputs bq_yl/bq_yr (module scratch)
    task automatic bq_step(input integer inst, input integer band);
        reg signed [63:0] a1, a2, b0, b1, b2, il, ir, op, op2;
        integer t;
        begin
            for (t = 0; t < 5; t = t + 1)
                bq_lag[inst][band][t] = add_c(mul_cc(bq_lag[inst][band][t], DLPI_C),
                                              mul_cc(bq_tgt[inst][band][t], DLP_C));
            a1 = bq_lag[inst][band][0]; a2 = bq_lag[inst][band][1];
            b0 = bq_lag[inst][band][2]; b1 = bq_lag[inst][band][3];
            b2 = bq_lag[inst][band][4];
            il = x64({{32{bq_xl[31]}}, bq_xl}) <<< 22;
            op = add_c(mul_cc(il, b0), bq_r0[inst][band][0]);
            bq_r0[inst][band][0] = add_c(sub_c(mul_cc(il, b1), mul_cc(a1, op)),
                                         bq_r1[inst][band][0]);
            bq_r1[inst][band][0] = sub_c(mul_cc(il, b2), mul_cc(a2, op));
            ir = x64({{32{bq_xr[31]}}, bq_xr}) <<< 22;
            op2 = add_c(mul_cc(ir, b0), bq_r0[inst][band][1]);
            bq_r0[inst][band][1] = add_c(sub_c(mul_cc(ir, b1), mul_cc(a1, op2)),
                                         bq_r1[inst][band][1]);
            bq_r1[inst][band][1] = sub_c(mul_cc(ir, b2), mul_cc(a2, op2));
            bq_yl = sat32((x64(op) + (128'sd1 <<< 21)) >>> 22);
            bq_yr = sat32((x64(op2) + (128'sd1 <<< 21)) >>> 22);
        end
    endtask

    // ---------------- envelope step (shared by process / control-only) --
    task automatic env_step(input integer inst, input signed [63:0] la);
        begin
            flam[0] = add_c(mul_cc(sub_c(ONE_C, cw[inst][0]), flam[0]),
                               mul_cc(cw[inst][0], la));
            flam2[0] = add_c(mul_cc(sub_c(ONE_C, cw[inst][1]), flam2[0]),
                                mul_cc(cw[inst][1], flam[0]));
            if (flam[0] > flam2[0]) flam2[0] = flam[0];
            gain_r[0] = recip_c(flam2[0]);
        end
    endtask

    // ---------------- lifecycle ---------------------------------------
    task automatic clear_limiter(input integer inst);
        integer t;
        begin
            for (t = 0; t < 128; t = t + 1) begin
                dly_l[0][t] = 0; dly_r[0][t] = 0; lamax[0][t] = 0;
            end
            bufpos[0] = 0;
            flam[0] = ONE_C; flam2[0] = ONE_C; gain_r[0] = ONE_C;
            rhash[inst] = 0;
        end
    endtask

    task automatic fresh_state(input integer inst);
        integer band, j;
        begin
            clear_limiter(inst);
            for (j = 0; j < 4; j = j + 1) begin
                lp_cur[inst][j] = 0; lp_tgt[inst][j] = 0;
            end
            for (band = 0; band < 3; band = band + 1) begin
                bq_first[inst][band] = 1;
                for (j = 0; j < 5; j = j + 1) begin
                    bq_lag[inst][band][j] = 0; bq_tgt[inst][band][j] = 0;
                end
                for (j = 0; j < 2; j = j + 1) begin
                    bq_r0[inst][band][j] = 0; bq_r1[inst][band][j] = 0;
                end
            end
        end
    endtask

    task automatic apply_ctrl(input integer inst);
        integer band, j;
        reg [63:0] fl;
        begin
            fl = cw[inst][21];
            if (fl[5]) fresh_state(inst);
            if (fl[4]) clear_limiter(inst);
            if (fl[5] || fl[4] || !fl[3]) begin
                // setvars: BiquadFilter::set_coef (first_run -> startValue)
                for (band = 0; band < 3; band = band + 1) begin
                    for (j = 0; j < 5; j = j + 1) begin
                        bq_tgt[inst][band][j] = cw[inst][6 + 5 * band + j];
                        if (bq_first[inst][band] != 0)
                            bq_lag[inst][band][j] = cw[inst][6 + 5 * band + j];
                    end
                    bq_first[inst][band] = 0;
                end
            end
            if (!fl[3]) begin
                // lipol_sse::set_target_smoothed on ampL, ampR, width, postamp
                for (j = 0; j < 4; j = j + 1) begin
                    lp_cur[inst][j] = lp_tgt[inst][j];
                    lp_tgt[inst][j] = add_a(mul_g(Q25_G, cw[inst][2 + j][31:0]),
                                            mul_g(Q75_G, lp_tgt[inst][j]));
                end
            end
        end
    endtask

    // ---------------- ConditionerEffect::process (one block) ------------
    task automatic process_block(input integer inst);
        reg [63:0] fl;
        reg signed [63:0] la, lsq, al, ar;
        reg signed [31:0] d_l, d_r;
        integer bp;
        begin
            fl = cw[inst][21];
            for (k = 0; k < 32; k = k + 1) begin
                dl[k] = in_l[inst][k]; dr[k] = in_r[inst][k];
            end
            if (fl[0])
                for (k = 0; k < 32; k = k + 1) begin
                    bq_xl = dl[k]; bq_xr = dr[k]; bq_step(inst, 0);
                    dl[k] = bq_yl; dr[k] = bq_yr;
                end
            if (fl[1])
                for (k = 0; k < 32; k = k + 1) begin
                    bq_xl = dl[k]; bq_xr = dr[k]; bq_step(inst, 1);
                    dl[k] = bq_yl; dr[k] = bq_yr;
                end
            for (k = 0; k < 32; k = k + 1) begin
                ms_m[k] = half_tz(x32(dl[k]) + x32(dr[k]));
                ms_s[k] = half_tz(x32(dl[k]) - x32(dr[k]));
            end
            if (fl[2])
                for (k = 0; k < 32; k = k + 1) begin
                    bq_xl = ms_s[k]; bq_xr = 0; bq_step(inst, 2);
                    ms_s[k] = bq_yl;
                end
            for (k = 0; k < 32; k = k + 1)
                ms_s[k] = mul_g(lip_val(lp_cur[inst][2], lp_tgt[inst][2], k), ms_s[k]);
            for (k = 0; k < 32; k = k + 1) begin
                dl[k] = add_a(ms_m[k], ms_s[k]);
                dr[k] = sub_a(ms_m[k], ms_s[k]);
            end
            for (k = 0; k < 32; k = k + 1) begin
                dl[k] = mul_g(lip_val(lp_cur[inst][0], lp_tgt[inst][0], k), dl[k]);
                dr[k] = mul_g(lip_val(lp_cur[inst][1], lp_tgt[inst][1], k), dr[k]);
            end

            for (k = 0; k < 32; k = k + 1) begin
                bp = bufpos[0];
                d_l = dly_l[0][bp];
                d_r = dly_r[0][bp];
                la = lamax[0][LA_READ_INDEX];
                la = sqrt_c(add_c(la, la));
                if (la < ONE_C) la = ONE_C;
                env_step(inst, la);

                rhash[inst] = rhash[inst]
                    + (x64({{32{dl[k][31]}}, dl[k]}) - x64({{32{d_l[31]}}, d_l})) * (bp + 1)
                    + (x64({{32{dr[k][31]}}, dr[k]}) - x64({{32{d_r[31]}}, d_r})) * (bp + 129);
                dly_l[0][bp] = dl[k];
                dly_r[0][bp] = dr[k];
                al = abs64(dl[k]);
                ar = abs64(dr[k]);
                lsq = sq_ac((al >= ar) ? al : ar);
                rhash[inst] = rhash[inst] + (x64(lsq) - x64(lamax[0][bp])) * (bp + 257);
                lamax[0][bp] = lsq;

                out_l[k] = mul_ca(gain_r[0], d_l);
                out_r[k] = mul_ca(gain_r[0], d_r);
                bufpos[0] = (bp + 1) & LOOKAHEAD_MASK;
            end
            for (k = 0; k < 32; k = k + 1) begin
                out_l[k] = mul_g(lip_val(lp_cur[inst][3], lp_tgt[inst][3], k), out_l[k]);
                out_r[k] = mul_g(lip_val(lp_cur[inst][3], lp_tgt[inst][3], k), out_r[k]);
            end
        end
    endtask

    // ---------------- ConditionerEffect::process_only_control ------------
    task automatic control_only_block(input integer inst);
        begin
            for (k = 0; k < 32; k = k + 1) env_step(inst, ONE_C);
            for (k = 0; k < 32; k = k + 1) begin
                out_l[k] = in_l[inst][k]; out_r[k] = in_r[inst][k];
            end
        end
    endtask

    // ---------------- checkpoint trace ---------------------------------
    task automatic emit_state(input integer bb, input integer inst);
        integer band, j;
        begin
            $fwrite(fd, "T %0d %0d bufpos %0d flamax %0d flamax2 %0d gain %0d",
                    bb, inst, bufpos[0], flam[0], flam2[0], gain_r[0]);
            $fwrite(fd, " ampL %0d ampLb %0d ampR %0d ampRb %0d wid %0d widb %0d pa %0d pab %0d",
                    lp_cur[inst][0], lp_tgt[inst][0], lp_cur[inst][1], lp_tgt[inst][1],
                    lp_cur[inst][2], lp_tgt[inst][2], lp_cur[inst][3], lp_tgt[inst][3]);
            for (band = 0; band < 3; band = band + 1) begin
                for (j = 0; j < 5; j = j + 1)
                    $fwrite(fd, " bq%0d_%0d %0d", band, j, bq_lag[inst][band][j]);
                $fwrite(fd, " bq%0d_r0 %0d bq%0d_r1 %0d", band, bq_r0[inst][band][0],
                        band, bq_r1[inst][band][0]);
            end
            $fwrite(fd, " hash %0d\n", rhash[inst]);
        end
    endtask

    // ---------------- main --------------------------------------------
    integer jj;
    initial begin
        if (!$value$plusargs("NINST=%d", NINST)) NINST = 1;
        if (!$value$plusargs("NBLOCKS=%d", N_BLOCKS)) N_BLOCKS = 1;
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
        for (ii = 0; ii < 2; ii = ii + 1) fresh_state(ii);

        for (b = 0; b < N_BLOCKS; b = b + 1) begin
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                for (jj = 0; jj < 22; jj = jj + 1) begin
                    rd64(fct); cw[ii][jj] = v64;
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin); in_l[ii][k] = v64[31:0];
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin); in_r[ii][k] = v64[31:0];
                end
            end
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                apply_ctrl(ii);
                if (cw[ii][21][3]) control_only_block(ii);
                else process_block(ii);
                $fwrite(fd, "O %0d %0d", b, ii);
                for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_l[k]);
                for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_r[k]);
                $fwrite(fd, "\n");
                emit_state(b, ii);
            end
        end
        $fclose(fd);
        $display("TB DONE");
        $finish;
    end
endmodule
