// SXT-028f RTL behavioral schedule: Reverb 2 (sst-effects tank reverb) slice.
//
// Reproduces the frozen fixed-point model
// (model/effects/type-reverb 2/reverb2_model.py) EXACTLY at declared
// checkpoints and on every per-instance output sample. All audio-rate
// arithmetic is computed here in the frozen conventions (exact products,
// round-half-up, saturating two's complement). Block-rate quantities are
// CONTROL-PLANE and streamed from <case>_ctrl.hex: the six lipol<float>
// coefficient targets (decay / diffusion / buildup / hf-damp / lf-damp /
// modulation), the LFO's (dr, di) pair and its control-rate renormalisation
// constant, the widthS / mix RAW lipol_sse targets, the eight tap times, the
// twelve allpass lengths, the four delay lengths and the predelay tap.
//
// The RTL owns, audio-rate: the six lipol recurrences (and the pinned
// engine's quirk that the LF-damping ramp is NEVER stepped), the LFO
// recurrence, the predelay ring, all twelve allpass rings, all four delay
// rings with their sub-sample modulated read, the eight one-pole filters,
// the modulation truncation, the four tap MACs, the decay multiply, the
// mid/side width matrix and the mix crossfade.
//
// External memory: one flat region per instance, HARNESS allocation profile
// (declared in model/effects/type-reverb 2/README.md):
//     predelay  16384 words   @ 0
//     allpass   12 x 4096     @ 16384
//     delay      4 x 16384    @ 65536      (mask 16383)
//   = 131072 x 32-bit words per instance.
// The bench profile is legal only while no ring wraps into a live tap; the
// frozen model REFUSES a configuration that would alias (ProfileRefusal) and
// tests/test_sxt028f.py demonstrates profile equivalence against the engine
// allocation. Two instances hold two disjoint regions - state is never
// shared (AGENTS.md per-instance rule).
//
// Wiring (plusargs):
//   +NINST=1|2     instances driven per block (disjoint memories)
//   +NBLOCKS=n     blocks
//   +RENDER0=b     first traced block
//   +RESETAT=b     optional bulk clear + constructor reset before block b
//   +INFILE / +CTRLFILE / +TRACE / +REV
`timescale 1ns/1ps

module tb_reverb2;
    integer NINST, N_BLOCKS, RENDER0, RESETAT;
    integer fd, fin, fct;
    string trace_name, fin_name, fct_name, rev_name;

    // ---- engine constants (Reverb2.h:63-74), read + cited, not copied
    localparam integer NUM_BLOCKS = 4;
    localparam integer NUM_AP     = 12;   // 4 input + 4 blocks x 2
    localparam integer SUBS_BITS  = 8;
    localparam integer SUBS_RANGE = 256;

    // ---- declared HARNESS allocation profile
    localparam integer PD_LEN   = 16384;
    localparam integer AP_ALLOC = 4096;
    localparam integer DL_ALLOC = 16384;
    localparam integer DL_MASK  = DL_ALLOC - 1;
    localparam integer PD_OFF   = 0;
    localparam integer AP_BASE  = PD_LEN;                    // 16384
    localparam integer DL_BASE  = PD_LEN + NUM_AP*AP_ALLOC;  // 65536
    localparam integer REGION_W = DL_BASE + NUM_BLOCKS*DL_ALLOC; // 131072

    localparam signed [63:0] ONE43 = 64'sh0000_0800_0000_0000;  // 1.0 Q24.43
    localparam signed [63:0] C001  = 64'sh0000_0014_7AE1_47AE;  // 0.01 Q24.43
    localparam signed [63:0] C099  = 64'sh0000_07EB_851E_B852;  // 0.99 Q24.43
    localparam integer ONE_G = 1 << 18;

    // ---- frozen tap gains (Reverb2.h:387-394 literals / 4.f), Q13.18
    function automatic signed [31:0] tap_gain(input integer b);
        case (b)
            0: tap_gain = 32'sd98304;    // 1.5f/4
            1: tap_gain = 32'sd78643;    // 1.2f/4
            2: tap_gain = 32'sd65536;    // 1.0f/4
            default: tap_gain = 32'sd52429; // 0.8f/4
        endcase
    endfunction

    // ---------------- external regions (2 instances, disjoint) ------------
    reg [31:0] mem0 [0:REGION_W-1];
    reg [31:0] mem1 [0:REGION_W-1];
    longint unsigned pdh [0:1];
    longint unsigned aph [0:1];
    longint unsigned dlh [0:1];
    longint unsigned er  [0:1];
    longint unsigned ew  [0:1];
    integer last_read;

    // region: 0 = predelay, 1 = allpass, 2 = delay
    task mem_access(input integer inst, input integer region,
                    input integer we, input integer a, input integer wd);
        reg signed [63:0] w64, o64;
        begin
            w64 = $signed({{32{wd[31]}}, wd});
            if (inst == 0) o64 = $signed({{32{mem0[a][31]}}, mem0[a]});
            else           o64 = $signed({{32{mem1[a][31]}}, mem1[a]});
            if (we) begin
                if (region == 0) pdh[inst] = pdh[inst] + w64 - o64;
                else if (region == 1) aph[inst] = aph[inst] + w64 - o64;
                else dlh[inst] = dlh[inst] + w64 - o64;
                if (inst == 0) mem0[a] = wd[31:0];
                else           mem1[a] = wd[31:0];
                ew[inst] = ew[inst] + 1;
            end else begin
                er[inst] = er[inst] + 1;
                last_read = o64[31:0];
            end
        end
    endtask

    // ---------------- per-instance state ----------------------------------
    integer pd_k   [0:1];
    integer ap_k   [0:1][0:11];
    integer ap_len [0:1][0:11];
    integer dl_k   [0:1][0:3];
    integer dl_len [0:1][0:3];
    integer tap_l  [0:1][0:3];
    integer tap_r  [0:1][0:3];
    integer pdt    [0:1];
    reg signed [63:0] hf_a0 [0:1][0:3];
    reg signed [63:0] lf_a0 [0:1][0:3];
    integer           tank  [0:1];

    // six lipol<float,32,true> ramps: v / new_v / dv / first_run
    reg signed [63:0] rv [0:1][0:5];
    reg signed [63:0] rt [0:1][0:5];
    reg signed [63:0] rd [0:1][0:5];
    integer           rfirst [0:1];
    // ramp index map: 0 decay, 1 diffusion, 2 buildup, 3 hf, 4 lf, 5 modulation

    reg signed [63:0] lfo_r [0:1];
    reg signed [63:0] lfo_i [0:1];
    reg signed [63:0] lfo_dr [0:1];
    reg signed [63:0] lfo_di [0:1];

    reg signed [31:0] ws_cur [0:1]; reg signed [31:0] ws_tgt [0:1];
    reg signed [31:0] mx_cur [0:1]; reg signed [31:0] mx_tgt [0:1];

    integer ilw [0:1][0:31];
    integer irw [0:1][0:31];
    integer wet_l [0:31];
    integer wet_r [0:31];
    integer out_l [0:31];
    integer out_r [0:31];

    // per-sample checkpoint capture (observation only): k < 4
    integer xs [0:3][0:13];

    integer b, k, ii, j_, t_, chk, xcap;
    reg [63:0] v64;

    // ---------------- fixed-point helpers ---------------------------------
    function automatic signed [31:0] sat32(input signed [63:0] v);
        if (v > $signed(64'sd2147483647)) sat32 = 32'sd2147483647;
        else if (v < -$signed(64'sd2147483648)) sat32 = -32'sd2147483648;
        else sat32 = v[31:0];
    endfunction

    function automatic signed [63:0] sat64(input signed [127:0] v);
        if (v > $signed(128'sd9223372036854775807))
            sat64 = 64'sd9223372036854775807;
        else if (v < -$signed(128'sd9223372036854775808))
            sat64 = -64'sd9223372036854775808;
        else sat64 = v[63:0];
    endfunction

    function automatic signed [31:0] qadd32(input signed [31:0] a,
                                            input signed [31:0] b);
        qadd32 = sat32($signed({{32{a[31]}}, a}) + $signed({{32{b[31]}}, b}));
    endfunction

    function automatic signed [31:0] qsub32(input signed [31:0] a,
                                            input signed [31:0] b);
        qsub32 = sat32($signed({{32{a[31]}}, a}) - $signed({{32{b[31]}}, b}));
    endfunction

    function automatic signed [63:0] qadd64(input signed [63:0] a,
                                            input signed [63:0] b);
        qadd64 = sat64($signed({{64{a[63]}}, a}) + $signed({{64{b[63]}}, b}));
    endfunction

    function automatic signed [63:0] qsub64(input signed [63:0] a,
                                            input signed [63:0] b);
        qsub64 = sat64($signed({{64{a[63]}}, a}) - $signed({{64{b[63]}}, b}));
    endfunction

    // exact 64x64 -> 128 signed product (limb decomposition)
    function automatic signed [127:0] mul64(input signed [63:0] a,
                                            input signed [63:0] b);
        reg signed [31:0] ah, bh;
        reg [31:0] al, bl;
        reg signed [63:0] t_hh;
        reg signed [95:0] t_hl, t_lh, tsum;
        begin
            ah = a[63:32]; al = a[31:0];
            bh = b[63:32]; bl = b[31:0];
            t_hh = $signed(ah) * $signed(bh);
            t_hl = $signed(ah) * $signed({32'h0, bl});
            t_lh = $signed({32'h0, al}) * $signed(bh);
            tsum = t_hl + t_lh;
            mul64 = ($signed({{64{t_hh[63]}}, t_hh}) <<< 64)
                  + ($signed({{32{tsum[95]}}, tsum}) <<< 32)
                  + $signed({64'h0, al} * {64'h0, bl});
        end
    endfunction

    // Q24.43 x Q24.43 -> Q24.43 (round-half-up, saturating)
    function automatic signed [63:0] qmul_cc(input signed [63:0] a,
                                             input signed [63:0] b);
        qmul_cc = sat64((mul64(a, b) + $signed(128'sd4398046511104)) >>> 43);
    endfunction

    // Q24.43 x Q10.21 -> Q10.21 (round-half-up, saturating)
    function automatic signed [31:0] qmul_ca(input signed [63:0] a,
                                             input signed [31:0] b);
        reg signed [127:0] p;
        begin
            p = mul64(a, $signed({{32{b[31]}}, b}));
            qmul_ca = sat32((p + $signed(128'sd4398046511104)) >>> 43);
        end
    endfunction

    // Q13.18 x (Q13.18|Q10.21) -> same (shift 18, round-half-up)
    function automatic signed [31:0] qmul_g(input signed [31:0] a,
                                            input signed [31:0] b);
        reg signed [63:0] p;
        begin
            p = $signed(a) * $signed(b);
            qmul_g = sat32((p + $signed(64'sd131072)) >>> 18);
        end
    endfunction

    function automatic signed [63:0] rsh64(input signed [63:0] v,
                                           input integer s);
        rsh64 = (v + ($signed(64'sd1) <<< (s - 1))) >>> s;
    endfunction

    function automatic integer clipi(input integer v, input integer lo,
                                     input integer hi);
        if (v < lo) clipi = lo;
        else if (v > hi) clipi = hi;
        else clipi = v;
    endfunction

    function automatic signed [63:0] clip64(input signed [63:0] v,
                                            input signed [63:0] lo,
                                            input signed [63:0] hi);
        if (v < lo) clip64 = lo;
        else if (v > hi) clip64 = hi;
        else clip64 = v;
    endfunction

    // (int) cast of a Q86 product scaled by 256: truncate toward zero
    function automatic integer mod_trunc(input signed [63:0] mv,
                                         input signed [63:0] lv);
        reg signed [127:0] p;
        begin
            p = mul64(mv, lv);
            if (p >= 0) mod_trunc = p >>> 78;
            else mod_trunc = -((-p) >>> 78);
        end
    endfunction

    // lipol_sse line value: cur + round((tgt-cur)*(k+1)/32)
    function automatic signed [31:0] lip_val(input signed [31:0] cur,
                                             input signed [31:0] tgt,
                                             input integer kk);
        reg signed [63:0] d;
        begin
            d = $signed({{32{tgt[31]}}, tgt}) - $signed({{32{cur[31]}}, cur});
            if (d >= 0)
                lip_val = sat32($signed({{32{cur[31]}}, cur})
                                + ((d * (kk+1) + 16) >>> 5));
            else
                lip_val = sat32($signed({{32{cur[31]}}, cur})
                                - (((-d) * (kk+1) + 16) >>> 5));
        end
    endfunction

    task automatic lip_smooth(inout signed [31:0] cur, inout signed [31:0] tgt,
                              input signed [31:0] f);
        reg signed [31:0] old_t;
        begin
            old_t = tgt;
            cur = old_t;
            tgt = qadd32(qmul_g(32'sd65536, f), qmul_g(32'sd196608, old_t));
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

    // ---------------- kernels ---------------------------------------------
    integer ap_res;
    task allpass_step(input integer inst, input integer idx,
                      input integer x, input signed [63:0] coeff);
        integer addr, d, din;
        begin
            ap_k[inst][idx] = ap_k[inst][idx] + 1;
            if (ap_k[inst][idx] >= ap_len[inst][idx]) ap_k[inst][idx] = 0;
            addr = AP_BASE + idx*AP_ALLOC + ap_k[inst][idx];
            mem_access(inst, 1, 0, addr, 0);
            d = last_read;
            din = qsub32(x, qmul_ca(coeff, d));
            ap_res = qadd32(d, qmul_ca(coeff, din));
            mem_access(inst, 1, 1, addr, din);
        end
    endtask

    integer dl_res, dl_t1, dl_t2;
    task delay_step(input integer inst, input integer bb, input integer x,
                    input integer modulation);
        integer off, kk, mi, f1, f2, a1, a2, d1, d2;
        reg signed [63:0] acc;
        begin
            off = DL_BASE + bb*DL_ALLOC;
            dl_k[inst][bb] = (dl_k[inst][bb] + 1) & DL_MASK;
            kk = dl_k[inst][bb];
            mem_access(inst, 2, 0, off + ((kk - tap_l[inst][bb]) & DL_MASK), 0);
            dl_t1 = last_read;
            mem_access(inst, 2, 0, off + ((kk - tap_r[inst][bb]) & DL_MASK), 0);
            dl_t2 = last_read;
            mi = modulation >>> SUBS_BITS;          // arithmetic (floor) shift
            f1 = modulation & (SUBS_RANGE - 1);
            f2 = SUBS_RANGE - f1;
            a1 = (kk - dl_len[inst][bb] + mi + 1) & DL_MASK;
            a2 = (kk - dl_len[inst][bb] + mi) & DL_MASK;
            mem_access(inst, 2, 0, off + a1, 0); d1 = last_read;
            mem_access(inst, 2, 0, off + a2, 0); d2 = last_read;
            acc = $signed({{32{d1[31]}}, d1}) * f1
                + $signed({{32{d2[31]}}, d2}) * f2;
            dl_res = sat32((acc + $signed(64'sd128)) >>> SUBS_BITS);
            mem_access(inst, 2, 1, off + kk, x);
        end
    endtask

    // ---------------- one block for one instance --------------------------
    task reverb2_block(input integer inst);
        integer s, x_in, x, ol, orr, p_rd, addr, i_, bb;
        reg signed [63:0] hdc, ldc, hdc1, ldc1, xc, a0, lr, li;
        reg signed [63:0] lfos;
        integer modulation, tmpm, tmps;
        begin
            for (k = 0; k < 32; k = k + 1) begin
                s = qadd32(ilw[inst][k], irw[inst][k]);
                x_in = (s >= 0) ? (s >>> 1) : -((-s) >>> 1);

                // predelay ring (read old, then write)
                pd_k[inst] = pd_k[inst] + 1;
                if (pd_k[inst] == PD_LEN) pd_k[inst] = 0;
                p_rd = pd_k[inst] - pdt[inst];
                while (p_rd < 0) p_rd = p_rd + PD_LEN;
                mem_access(inst, 0, 0, PD_OFF + p_rd, 0);
                addr = last_read;
                mem_access(inst, 0, 1, PD_OFF + pd_k[inst], x_in);
                x_in = addr;

                for (i_ = 0; i_ < 4; i_ = i_ + 1) begin
                    allpass_step(inst, i_, x_in, rv[inst][1]);
                    x_in = ap_res;
                end

                x = tank[inst];
                ol = 0; orr = 0;
                hdc = clip64(rv[inst][3], C001, C099);
                ldc = clip64(rv[inst][4], C001, C099);
                hdc1 = qsub64(ONE43, hdc);
                ldc1 = qsub64(ONE43, ldc);
                if (xcap != 0 && k < 4) xs[k][0] = x_in;

                for (bb = 0; bb < NUM_BLOCKS; bb = bb + 1) begin
                    x = qadd32(x, x_in);
                    allpass_step(inst, 4 + bb*2, x, rv[inst][2]); x = ap_res;
                    allpass_step(inst, 5 + bb*2, x, rv[inst][2]); x = ap_res;

                    // one-pole lowpass: a0 = a0*c0 + x*(1-c0); y = a0
                    xc = $signed({{32{x[31]}}, x}) <<< 22;
                    a0 = qadd64(qmul_cc(hf_a0[inst][bb], hdc),
                                qmul_cc(xc, hdc1));
                    hf_a0[inst][bb] = a0;
                    x = sat32(rsh64(a0, 22));

                    // one-pole highpass: a0 = a0*(1-c0) + x*c0; y = x - a0
                    xc = $signed({{32{x[31]}}, x}) <<< 22;
                    a0 = qadd64(qmul_cc(lf_a0[inst][bb], ldc1),
                                qmul_cc(xc, ldc));
                    lf_a0[inst][bb] = a0;
                    x = qsub32(x, sat32(rsh64(a0, 22)));

                    case (bb)
                        0: lfos = lfo_r[inst];
                        1: lfos = lfo_i[inst];
                        2: lfos = -lfo_r[inst];
                        default: lfos = -lfo_i[inst];
                    endcase
                    modulation = mod_trunc(rv[inst][5], lfos);
                    delay_step(inst, bb, x, modulation);
                    x = dl_res;
                    ol = qadd32(ol, qmul_g(tap_gain(bb), dl_t1));
                    orr = qadd32(orr, qmul_g(tap_gain(bb), dl_t2));
                    if (xcap != 0 && k < 4) begin
                        xs[k][1 + bb*3] = modulation;
                        xs[k][2 + bb*3] = dl_t1;
                        xs[k][3 + bb*3] = dl_t2;
                    end
                    x = qmul_ca(rv[inst][0], x);
                end

                wet_l[k] = ol;
                wet_r[k] = orr;
                tank[inst] = x;
                if (xcap != 0 && k < 4) xs[k][13] = x;

                // ramp steps: decay, diffusion, buildup, hf, LFO, modulation
                // (the pinned engine NEVER steps the LF-damping ramp)
                rv[inst][0] = qadd64(rv[inst][0], rd[inst][0]);
                rv[inst][1] = qadd64(rv[inst][1], rd[inst][1]);
                rv[inst][2] = qadd64(rv[inst][2], rd[inst][2]);
                rv[inst][3] = qadd64(rv[inst][3], rd[inst][3]);
                lr = lfo_r[inst]; li = lfo_i[inst];
                lfo_r[inst] = qsub64(qmul_cc(lfo_dr[inst], lr),
                                     qmul_cc(lfo_di[inst], li));
                lfo_i[inst] = qadd64(qmul_cc(lfo_dr[inst], li),
                                     qmul_cc(lfo_di[inst], lr));
                rv[inst][5] = qadd64(rv[inst][5], rd[inst][5]);
            end

            // applyWidth (mid/side; halving truncates toward zero)
            for (k = 0; k < 32; k = k + 1) begin
                tmpm = $signed(wet_l[k]) + $signed(wet_r[k]);
                tmps = $signed(wet_l[k]) - $signed(wet_r[k]);
                tmpm = (tmpm >= 0) ? sat32(tmpm >>> 1) : sat32(-((-tmpm) >>> 1));
                tmps = (tmps >= 0) ? sat32(tmps >>> 1) : sat32(-((-tmps) >>> 1));
                tmps = qmul_g(lip_val(ws_cur[inst], ws_tgt[inst], k), tmps);
                wet_l[k] = qadd32(tmpm, tmps);
                wet_r[k] = qsub32(tmpm, tmps);
            end
            // mix crossfade: dry*(1-t) + wet*t
            for (k = 0; k < 32; k = k + 1) begin
                tmpm = lip_val(mx_cur[inst], mx_tgt[inst], k);
                out_l[k] = qadd32(qmul_g(qsub32(ONE_G, tmpm), ilw[inst][k]),
                                  qmul_g(tmpm, wet_l[k]));
                out_r[k] = qadd32(qmul_g(qsub32(ONE_G, tmpm), irw[inst][k]),
                                  qmul_g(tmpm, wet_r[k]));
            end
        end
    endtask

    // ---------------- control application ---------------------------------
    task apply_ctrl(input integer inst, input integer fh);
        integer q;
        reg signed [63:0] tgt, nrm;
        begin
            for (q = 0; q < 6; q = q + 1) begin
                rd64(fh, v64); tgt = $signed(v64);
                rv[inst][q] = rt[inst][q];
                rt[inst][q] = tgt;
                if (rfirst[inst] != 0) rv[inst][q] = tgt;
                rd[inst][q] = rsh64(qsub64(rt[inst][q], rv[inst][q]), 5);
            end
            rfirst[inst] = 0;
            rd64(fh, v64); lfo_dr[inst] = $signed(v64);
            rd64(fh, v64); lfo_di[inst] = $signed(v64);
            rd64(fh, v64); nrm = $signed(v64);
            lfo_r[inst] = qmul_cc(lfo_r[inst], nrm);
            lfo_i[inst] = qmul_cc(lfo_i[inst], nrm);
            rd64(fh, v64); lip_smooth(ws_cur[inst], ws_tgt[inst],
                                      $signed(v64[31:0]));
            rd64(fh, v64); lip_smooth(mx_cur[inst], mx_tgt[inst],
                                      $signed(v64[31:0]));
            for (q = 0; q < 4; q = q + 1) begin
                rd64(fh, v64); tap_l[inst][q] = $signed(v64);
            end
            for (q = 0; q < 4; q = q + 1) begin
                rd64(fh, v64); tap_r[inst][q] = $signed(v64);
            end
            for (q = 0; q < NUM_AP; q = q + 1) begin
                rd64(fh, v64); ap_len[inst][q] = $signed(v64);
            end
            for (q = 0; q < NUM_BLOCKS; q = q + 1) begin
                rd64(fh, v64); dl_len[inst][q] = $signed(v64);
            end
            rd64(fh, v64); pdt[inst] = $signed(v64);
        end
    endtask

    // ---------------- reset (engine fx-rebuild: ctor + init) ---------------
    task init_inst(input integer i_, input integer clear_mem);
        integer q, w;
        begin
            if (clear_mem != 0) begin
                for (w = 0; w < REGION_W; w = w + 1) begin
                    if (i_ == 0) mem0[w] = 32'sd0;
                    else         mem1[w] = 32'sd0;
                end
            end
            pdh[i_] = 0; aph[i_] = 0; dlh[i_] = 0;
            er[i_] = 0; ew[i_] = 0;
            pd_k[i_] = 0; tank[i_] = 0; pdt[i_] = 1;
            for (q = 0; q < NUM_AP; q = q + 1) begin
                ap_k[i_][q] = 0; ap_len[i_][q] = 1;
            end
            for (q = 0; q < NUM_BLOCKS; q = q + 1) begin
                dl_k[i_][q] = 0; dl_len[i_][q] = 1;
                tap_l[i_][q] = 0; tap_r[i_][q] = 0;
                hf_a0[i_][q] = 0; lf_a0[i_][q] = 0;
            end
            for (q = 0; q < 6; q = q + 1) begin
                rv[i_][q] = 0; rt[i_][q] = 0; rd[i_][q] = 0;
            end
            rfirst[i_] = 1;
            lfo_r[i_] = 0; lfo_i[i_] = -ONE43;
            lfo_dr[i_] = 0; lfo_di[i_] = 0;
            ws_cur[i_] = 0; ws_tgt[i_] = 0;
            mx_cur[i_] = 0; mx_tgt[i_] = 0;
        end
    endtask

    // ---------------- state trace -----------------------------------------
    task emit_state(input integer bb);
        integer i2, q;
        begin
            for (i2 = 0; i2 < NINST; i2 = i2 + 1) begin
                $fwrite(fd, "T %0d %0d pd_k %0d tank %0d pdt %0d ",
                        bb, i2, pd_k[i2], tank[i2], pdt[i2]);
                for (q = 0; q < NUM_AP; q = q + 1)
                    $fwrite(fd, "apk%0d %0d ", q, ap_k[i2][q]);
                for (q = 0; q < NUM_AP; q = q + 1)
                    $fwrite(fd, "apl%0d %0d ", q, ap_len[i2][q]);
                for (q = 0; q < NUM_BLOCKS; q = q + 1)
                    $fwrite(fd, "dlk%0d %0d ", q, dl_k[i2][q]);
                for (q = 0; q < NUM_BLOCKS; q = q + 1)
                    $fwrite(fd, "dll%0d %0d ", q, dl_len[i2][q]);
                for (q = 0; q < NUM_BLOCKS; q = q + 1)
                    $fwrite(fd, "tpl%0d %0d ", q, tap_l[i2][q]);
                for (q = 0; q < NUM_BLOCKS; q = q + 1)
                    $fwrite(fd, "tpr%0d %0d ", q, tap_r[i2][q]);
                for (q = 0; q < NUM_BLOCKS; q = q + 1)
                    $fwrite(fd, "hf%0d %0d ", q, $signed(hf_a0[i2][q]));
                for (q = 0; q < NUM_BLOCKS; q = q + 1)
                    $fwrite(fd, "lf%0d %0d ", q, $signed(lf_a0[i2][q]));
                for (q = 0; q < 6; q = q + 1)
                    $fwrite(fd, "rv%0d %0d rt%0d %0d ",
                            q, $signed(rv[i2][q]), q, $signed(rt[i2][q]));
                $fwrite(fd, "lfor %0d lfoi %0d ",
                        $signed(lfo_r[i2]), $signed(lfo_i[i2]));
                $fwrite(fd, "ws %0d mix %0d ",
                        $signed(ws_tgt[i2]), $signed(mx_tgt[i2]));
                $fwrite(fd, "pdh %0d aph %0d dlh %0d erd %0d ewr %0d\n",
                        pdh[i2], aph[i2], dlh[i2], er[i2], ew[i2]);
            end
        end
    endtask

    // ---------------- main --------------------------------------------------
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

        for (ii = 0; ii < 2; ii = ii + 1) init_inst(ii, 1);

        for (b = 0; b < N_BLOCKS; b = b + 1) begin
            if (b == RESETAT)
                for (ii = 0; ii < NINST; ii = ii + 1) init_inst(ii, 1);
            chk = (b == RENDER0 - 1) || (b == RENDER0) || (b == RENDER0 + 1)
                  || (b == N_BLOCKS - 1)
                  || ((b >= RENDER0) && (((b - RENDER0) % 16) == 0));
            xcap = (b == RENDER0) || (b == N_BLOCKS - 1)
                   || ((b >= RENDER0) && (((b - RENDER0) % 8) == 0));
            for (ii = 0; ii < NINST; ii = ii + 1) apply_ctrl(ii, fct);
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); ilw[ii][k] = $signed(v64[31:0]);
                end
                for (k = 0; k < 32; k = k + 1) begin
                    rd64(fin, v64); irw[ii][k] = $signed(v64[31:0]);
                end
            end
            for (ii = 0; ii < NINST; ii = ii + 1) begin
                reverb2_block(ii);
                if (b >= RENDER0) begin
                    $fwrite(fd, "O %0d %0d", b, ii);
                    for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_l[k]);
                    for (k = 0; k < 32; k = k + 1) $fwrite(fd, " %0d", out_r[k]);
                    $fwrite(fd, "\n");
                end
                if (xcap != 0) begin
                    $fwrite(fd, "X %0d %0d", b, ii);
                    for (k = 0; k < 4; k = k + 1)
                        for (j_ = 0; j_ < 14; j_ = j_ + 1)
                            $fwrite(fd, " %0d", xs[k][j_]);
                    $fwrite(fd, "\n");
                end
            end
            if (chk != 0) emit_state(b);
        end
        $fwrite(fd, "ER %0d %0d %0d %0d\n", er[0], ew[0], er[1], ew[1]);
        $fclose(fd);
        $display("TB DONE");
        $finish;
    end

endmodule
