// SXT-026 wavetable oscillator core — behavioral EXACT schedule of the
// frozen fixed-point model (model/oscillators/wavetable/wt_model.py).
// RTL-vs-model agreement must be EXACT (integer equality at every declared
// checkpoint; tools/compare_wt_rtl_model.py).
//
// Structure is cited from the pinned engine (read, never copied):
// surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71
//   src/common/dsp/oscillators/WavetableOscillator.cpp
//   src/common/dsp/Wavetable.cpp
//
// Q formats (model/oscillators/wavetable/README.md):
//   samples/coefs/table words Q10.21 signed 32-bit
//   pitchmult_inv Q13.18; pitchmult/a_cov/tableipol Q10.21
//   oscstate Q10.21 held in 64 bits; products widened to 128 bits
//   sinc lipol fraction 16-bit unsigned
//
// Wavetable words are EXTERNAL: every table read goes through the
// ext_addr/ext_req handshake; the testbench answers combinationally and
// models asset residency (frame cache, aligned burst fills) with miss
// latency counted as arithmetic stall cycles (declared). Sinc taps are
// on-chip ROM loaded from the run directory.
//
// Slice declarations (see README): drift = 0, formant = 0 (formant word
// == 1.0 exactly), FM path not in slice, mono (pan law cancels in (L+R)/2).

`timescale 1ns/1ps

module wavetable_core (
    input wire clk,
    input wire rst,

    // external asset memory (single-word handshake; the testbench answers
    // combinationally and does the traffic accounting)
    output reg  [31:0] ext_addr,
    output reg         ext_req,
    input  wire [31:0] ext_rd_data,
    input  wire        ext_rd_valid,

    // per-block control record (from ctrl.hex)
    input  wire signed [31:0] c_pmi,         // Q13.18
    input  wire signed [31:0] c_a_cov,       // Q10.21
    input  wire signed [31:0] c_hpf_start,   // Q10.21
    input  wire signed [31:0] c_hpf_d,       // Q10.21
    input  wire signed [31:0] c_t_shape,     // morph target Q10.21
    input  wire signed [31:0] c_t_vskew,
    input  wire signed [31:0] c_t_hskew,
    input  wire signed [31:0] c_t_clip,
    input  wire               c_checkpoint,  // emit trace lines this block
    input  wire [31:0]        c_trace_wr,    // trace file descriptor
    input  wire [31:0]        c_block,       // block index (trace)
    input  wire [31:0]        c_slot,        // slot index (trace)

    // one-time init words (init.hex; see run_model.py word order)
    input wire signed [31:0] i_out_attenuation,
    input wire signed [31:0] i_t_shape,
    input wire signed [31:0] i_t_vskew,
    input wire signed [31:0] i_t_hskew,
    input wire signed [31:0] i_t_clip,
    input wire signed [31:0] i_formant_t,
    input wire signed [31:0] i_lag_rate,
    input wire signed [31:0] i_morph_scale,  // qint((n-1+nointerp)*0.99999)
    input wire signed [31:0] i_taylor,       // qint(sqrt(27/4))
    input wire signed [31:0] i_dt,           // qint(1/WAVE_SIZE)
    input wire signed [31:0] i_tableipol0,
    input wire signed [31:0] i_tableid0,
    input wire signed [31:0] i_last_tableipol0,
    input wire signed [31:0] i_last_tableid0,
    input wire signed [31:0] i_hpf0,
    input wire signed [31:0] i_tempt_0,
    input wire signed [31:0] i_tempt_1,
    input wire signed [31:0] i_tempt_2,
    input wire signed [31:0] i_tempt_3,
    input wire signed [31:0] i_tempt_4,
    input wire signed [31:0] i_tempt_5,
    input wire signed [31:0] i_tempt_6,
    input wire signed [31:0] i_tempt_7,
    input wire signed [31:0] i_tempt_8,
    input wire signed [31:0] i_tempt_9,
    input wire signed [31:0] i_tempt_10,
    input wire signed [31:0] i_tempt_11,
    input wire signed [31:0] i_tempt_12,
    input wire signed [31:0] i_tempt_13,
    input wire signed [31:0] i_tempt_14,
    input wire signed [31:0] i_tempt_15
);

    integer N_UNISON     = 1;
    integer WAVE_SIZE    = 1024;
    integer N_TABLES     = 16;
    integer NOINTERP     = 0;
    integer DEFORM_LEGACY = 0;  // 0 = xt14_continuous, 1 = legacy

    reg signed [31:0] o_oscout [0:63];   // last 64-sample oscillator block

    // ---------------------------------------------------------- constants
    localparam integer FQ = 21;
    localparam integer PMI_F = 18;
    localparam integer FIRIPOL_N = 12;
    localparam integer OB_END = 140;            // OB_LENGTH + FIRIPOL_N
    localparam signed [31:0] ONE = 32'sd2097152;
    localparam signed [31:0] FOUR = 32'sd8388608;
    localparam signed [31:0] HALF = 32'sd1048576;

    // ------------------------------------------------------------- state
    reg signed [63:0] oscstate   [0:15];
    reg [31:0]        wstate     [0:15];
    reg signed [31:0] last_level [0:15];
    reg [31:0]        mipmap     [0:15];
    reg [31:0]        mipmap_ofs [0:15];

    reg signed [31:0] l_shape, l_vskew, l_hskew, l_clip;
    reg signed [31:0] tableipol, last_tableipol;
    reg signed [31:0] tableid, last_tableid;
    reg signed [31:0] formant_t, formant_last;
    reg signed [31:0] hpf_prev;
    reg signed [31:0] formant_word;             // ntp_tuningctr(0) == ONE

    reg signed [31:0] osc [0:OB_END-1];
    reg signed [31:0] osc_out;
    reg [31:0]        bufpos;
    reg [63:0]        block_impulses;

    reg signed [31:0] tempt   [0:15];
    reg signed [31:0] out_att, lag_rate, morph_scale_w, taylor_w, dt_q;

    // sinc ROM (on-chip; loaded by the testbench)
    reg signed [31:0] sinc_main  [0:6143];
    reg signed [31:0] sinc_deriv [0:6143];

    // traffic counters (read by the testbench; SXT-016 reconciliation)
    integer reads_words = 0;
    integer fill_words = 0;
    integer bursts = 0;
    integer stall_cycles = 0;
    reg     frame_touched [0:6*16-1];

    integer dbg = 0;

    // ---------------------------------------------------------- Q helpers
    function signed [31:0] sat32(input signed [127:0] x);
        sat32 = (x > 127'sd2147483647) ? 32'sd2147483647 :
                ((x < -127'sd2147483648) ? -32'sd2147483648 : x[31:0]);
    endfunction

    function signed [31:0] qmul_sh(input signed [127:0] a,
                                   input signed [127:0] b,
                                   input integer s);
        reg signed [127:0] p;
        begin
            p = (a * b) + (128'sd1 <<< (s - 1));
            qmul_sh = sat32(p >>> s);
        end
    endfunction

    function signed [31:0] qmul_wt(input signed [127:0] a,
                                   input signed [31:0] b,
                                   input integer fb);
        qmul_wt = qmul_sh(a, b, fb);
    endfunction

    function signed [31:0] q21(input signed [127:0] a,
                               input signed [127:0] b);
        q21 = qmul_sh(a, b, FQ);
    endfunction

    function signed [31:0] limit_q(input signed [31:0] x,
                                   input signed [31:0] lo,
                                   input signed [31:0] hi);
        limit_q = (x < lo) ? lo : ((x > hi) ? hi : x);
    endfunction

    // pinned float32 mip thresholds in Q10.21 (WavetableOscillator.cpp).
    // The WAVETABLE_MUTANT_MIP define is the committed RTL negative control
    // (NC-B, RTL): the mip-2 threshold is mutated (0.44999998807907104 ->
    // 0.2861), which shifts the selected mip for a band of pitches and must
    // break RTL-vs-model exactness (NC-B RTL transcript).
    function signed [31:0] mip_thr(input integer k);
        begin
`ifdef WAVETABLE_MUTANT_MIP
            // NC-B RTL mutant: every mip threshold halved -> the core
            // selects the WRONG (deeper) mip level for a wide pitch band;
            // the comparison against the model must FAIL.
            case (k)
                6: mip_thr = 32'sd29465;
                5: mip_thr = 32'sd58930;
                4: mip_thr = 32'sd117861;
                3: mip_thr = 32'sd235722;
                2: mip_thr = 32'sd471444;
                1: mip_thr = 32'sd942889;
                default: mip_thr = ONE;
            endcase
`else
            case (k)
                6: mip_thr = 32'sd58930;
                5: mip_thr = 32'sd117861;
                4: mip_thr = 32'sd235722;
                3: mip_thr = 32'sd471444;
                2: mip_thr = 32'sd942889;
                1: mip_thr = 32'sd1885777;
                default: mip_thr = ONE;
            endcase
`endif
        end
    endfunction

    // ------------------------------------------------------ table access
    // combinational zero-latency response; miss latency counted as
    // arithmetic stall cycles (declared traffic model)
    task do_ext_read(input integer mip, input integer tbl,
                     input integer idx);
        integer frame_words, addr, tidx;
        begin
            addr = level_offset(mip) + tbl * (WAVE_SIZE >> mip) + idx;
            frame_words = (WAVE_SIZE >> mip);
            tidx = mip*16 + tbl;
            ext_addr = addr;
            ext_req = 1'b1;
            #1;
            ext_req = 1'b0;
            reads_words = reads_words + 1;
            if (!frame_touched[tidx]) begin
                frame_touched[tidx] = 1'b1;
                fill_words = fill_words + frame_words;
                bursts = bursts + (frame_words + 15) / 16;
                stall_cycles = stall_cycles +
                               ((frame_words < 64) ? frame_words : 64);
            end else begin
                stall_cycles = stall_cycles + 1;
            end
        end
    endtask

    function integer level_offset(input integer mip);
        integer k, acc_l;
        begin
            acc_l = 0;
            for (k = 0; k < mip; k = k + 1)
                acc_l = acc_l + N_TABLES * (WAVE_SIZE >> k);
            level_offset = acc_l;
        end
    endfunction

    // -------------------------------------------------------- convolute
    task do_convolute(input integer v);
        reg signed [31:0] block_pos, a_sel, dt2, xt, xt_w, ft, d, t;
        reg signed [31:0] level, w0, w1, proc, tblip, newlevel, x1, x3, g;
        reg signed [31:0] a_skew, bp;
        reg [31:0] ipos, delay, wtsize, wt_inc, m, m12, base;
        reg signed [31:0] term, main_tap, deriv_tap, lipol_q;
        reg signed [63:0] nxt;
        reg signed [127:0] half_q, prod;
        integer tid_i, target_i, kk;
        reg [31:0] w0a, w1a;
        begin
            block_impulses = block_impulses + 64'd1;

            // block_pos = qmul(oscstate >>> 6, pmi, fb=18)
            block_pos = qmul_wt(oscstate[v] >>> 6, c_pmi, PMI_F);

            // ipos = (unsigned)(oscstate * pmi) >>> 15, low 32 bits
            prod = oscstate[v] * c_pmi;
            ipos = prod >>> (FQ + PMI_F - 24);

            if (wstate[v] == 0) begin
                formant_last = formant_t;
                a_sel = qmul_wt(dt_q, c_pmi, PMI_F);
                mipmap[v] = 0;
                $display("DBG SEL a=%0d mip=%0d", a_sel, mipmap[v]);
                if ((a_sel < mip_thr(6)) && (WAVE_SIZE >= 128))
                    mipmap[v] = 6;
                else if ((a_sel < mip_thr(5)) && (WAVE_SIZE >= 64))
                    mipmap[v] = 5;
                else if ((a_sel < mip_thr(4)) && (WAVE_SIZE >= 32))
                    mipmap[v] = 4;
                else if ((a_sel < mip_thr(3)) && (WAVE_SIZE >= 16))
                    mipmap[v] = 3;
                else if ((a_sel < mip_thr(2)) && (WAVE_SIZE >= 8))
                    mipmap[v] = 2;
                else if ((a_sel < mip_thr(1)) && (WAVE_SIZE >= 4))
                    mipmap[v] = 1;
                if (dbg) $display("DBG mipsel a_sel=%0d thr2=%0d mip=%0d", a_sel, mip_thr(2), mipmap[v]);
                mipmap_ofs[v] = 0;
                for (kk = 0; kk < mipmap[v]; kk = kk + 1)
                    mipmap_ofs[v] = mipmap_ofs[v] + (WAVE_SIZE >> kk);
            end

            delay = (ipos >> 24) & 32'h3F;
            m     = ((ipos >> 16) & 32'hFF) * (FIRIPOL_N << 1);
            m12   = m >> 1;

            wt_inc = (32'h1 << mipmap[v]);
            dt2 = q21(dt_q, wt_inc <<< FQ);   // qmul(dt, qint(wt_inc))

            // xt = qmul(qint(state + 0.5), dt2)
            half_q = wstate[v] * 2 * HALF + HALF;
            xt = qmul_sh(half_q, dt2, FQ);

            // hskew taylor warp
            xt_w = ONE + q21(l_hskew,
                             q21(FOUR,
                                 q21(xt, q21(xt - ONE,
                                             q21(2 * xt - ONE,
                                                 taylor_w)))));

            ft = q21(block_pos, formant_t)
               + q21(ONE - block_pos, formant_last);
            d   = q21(formant_word, xt_w);
            dt2 = q21(dt2, d);

            wtsize = WAVE_SIZE >> mipmap[v];
            if (wstate[v] >= (wtsize - 1))
                dt2 = sat32(dt2 + (ONE - formant_word));
            t = q21(dt2, tempt[v]);
            wstate[v] = wstate[v] & (wtsize - 1);

            // morph frame interpolation
            if (DEFORM_LEGACY == 0) begin
                bp = (NOINTERP != 0) ? ONE : block_pos;
                tblip = q21(ONE - bp, last_tableipol)
                      + q21(bp, tableipol);
                tid_i = tblip >>> FQ;
                target_i = (tid_i + 1 > N_TABLES - 1) ? (N_TABLES - 1)
                                                      : (tid_i + 1);
                proc = q21(tblip - (tid_i <<< FQ), ONE - NOINTERP * ONE);
            end else begin
                tblip = q21(ONE - block_pos, last_tableipol)
                      + q21(block_pos, tableipol);
                proc = q21(ONE - NOINTERP * ONE, tblip);
                tid_i = tableid;
                target_i = tableid + 1 - NOINTERP;
            end

            do_ext_read(mipmap[v], tid_i, wstate[v]);
            w0 = ext_rd_data;
            do_ext_read(mipmap[v], target_i, wstate[v]);
            w1 = ext_rd_data;

            level = q21(w0, ONE - proc) + q21(w1, proc);

            // distort_level
            a_skew = l_vskew >>> 1;
            x1 = sat32(level - q21(q21(a_skew, level), level) + a_skew);
            x3 = q21(q21(q21(l_clip, x1), x1), x1);
            newlevel = limit_q(sat32(q21(x1, ONE - l_clip) + x3),
                               -ONE, ONE);

            g = sat32(newlevel - last_level[v]);
            last_level[v] = newlevel;
            g = q21(g, out_att);

            base = bufpos + delay;
            for (kk = 0; kk < FIRIPOL_N; kk = kk + 1) begin
                main_tap  = sinc_main[m12 + kk];
                deriv_tap = sinc_deriv[m12 + kk];
                lipol_q   = ipos[15:0];
                term = sat32(main_tap + qmul_sh(lipol_q, deriv_tap, 16));
                osc[base + kk] = sat32(osc[base + kk] + q21(term, g));
            end

            nxt = oscstate[v] + t;
            oscstate[v] = (nxt < 0) ? 64'sd0 : nxt;
            wstate[v] = (wstate[v] + 1) & (wtsize - 1);
        end
    endtask

    // ------------------------------------------------------- block proc
    task do_block;
        integer v2, k2;
        reg signed [31:0] shape, shape_scaled, hpf, hpf_start, hpf_step;
        reg signed [31:0] max_tid;
        begin
            // lag steps (vskew/hskew/clip BEFORE the morph update, as in
            // model process_block; the shape lag happens inside the morph
            // update, after the last_* copy)
            l_vskew = sat32(l_vskew + q21(lag_rate, c_t_vskew - l_vskew));
            l_hskew = sat32(l_hskew + q21(lag_rate, c_t_hskew - l_hskew));
            l_clip  = sat32(l_clip  + q21(lag_rate, c_t_clip  - l_clip));

            hpf_start = hpf_prev;
            max_tid = (N_TABLES - 2 + NOINTERP > 0)
                    ? (N_TABLES - 2 + NOINTERP) : 0;

            if (N_TABLES > 1) begin
                last_tableipol = tableipol;
                last_tableid = tableid;
                l_shape = sat32(l_shape + q21(lag_rate,
                                              c_t_shape - l_shape));
                shape = limit_q(l_shape, 32'sd0, ONE);
                shape_scaled = q21(shape, morph_scale_w);
                if (DEFORM_LEGACY == 0) begin
                    tableipol = shape_scaled;
                    tableid = limit_q(shape_scaled >>> FQ, 32'sd0, max_tid);
                end else begin
                    tableipol = shape_scaled & 32'sd2097151;
                    tableid = limit_q(shape_scaled >>> FQ, 32'sd0, max_tid);
                    if (tableid > last_tableid) begin
                        if (last_tableipol != ONE) begin
                            tableid = last_tableid;
                            tableipol = ONE;
                        end else last_tableipol = 32'sd0;
                    end else if (tableid < last_tableid) begin
                        if (last_tableipol != 32'sd0) begin
                            tableid = last_tableid;
                            tableipol = 32'sd0;
                        end else last_tableipol = ONE;
                    end
                end
            end else begin
                tableipol = 32'sd0; tableid = 32'sd0;
                last_tableipol = 32'sd0; last_tableid = 32'sd0;
            end

            for (v2 = 0; v2 < N_UNISON; v2 = v2 + 1) begin
                while (oscstate[v2] < c_a_cov)
                    do_convolute(v2);
                oscstate[v2] = oscstate[v2] - c_a_cov;
                if (oscstate[v2] < 0) oscstate[v2] = 64'sd0;
            end

            for (k2 = 0; k2 < 64; k2 = k2 + 1) begin
                hpf_step = sat32((c_hpf_d * (k2 + 1) + 32'sd32) >>> 6);
                hpf = sat32(c_hpf_start + hpf_step);
                osc_out = sat32(q21(osc_out, hpf) + osc[bufpos + k2]);
                o_oscout[k2] = osc_out;
                osc[bufpos + k2] = 32'sd0;
            end
            hpf_prev = sat32(c_hpf_start + c_hpf_d);

            bufpos = (bufpos + 64) & (128 - 1);
            if (bufpos == 0) begin
                for (k2 = 0; k2 < FIRIPOL_N; k2 = k2 + 1) begin
                    osc[k2] = osc[128 + k2];
                    osc[128 + k2] = 32'sd0;
                end
            end
        end
    endtask

    // trace output (integer-exact checkpoints + full oscillator block)
    integer fd_trace = 0;

    task emit_trace;
        integer v;
        begin
            if (fd_trace == 0)
                fd_trace = c_trace_wr;   // fd streamed by the testbench
            for (v = 0; v < N_UNISON; v = v + 1)
                $fdisplay(fd_trace, "T %0d %0d %0d %0d %0d %0d %0d",
                          c_block, c_slot, v,
                          oscstate[v], wstate[v], last_level[v], mipmap[v]);
            $fdisplay(fd_trace, "S %0d %0d %0d %0d %0d %0d %0d %0d",
                      c_block, c_slot,
                      tableid, tableipol, last_tableipol, l_shape,
                      osc_out, bufpos, hpf_prev);
            for (v = 0; v < 64; v = v + 4)
                $fdisplay(fd_trace, "O %0d %0d %0d %0d %0d %0d",
                          c_block, c_slot, o_oscout[v], o_oscout[v+1],
                          o_oscout[v+2], o_oscout[v+3]);
        end
    endtask

    // -------------------------------------------------------------- init
    // init words are latched on the first clocked cycle: the testbench
    // loads them at time 0 (declared control-plane boundary)
    reg init_latched = 0;
    always @(posedge clk) begin
        if (!init_latched) begin
            out_att = i_out_attenuation;
            l_shape = i_t_shape;
            l_vskew = i_t_vskew;
            l_hskew = i_t_hskew;
            l_clip = i_t_clip;
            lag_rate = i_lag_rate;
            morph_scale_w = i_morph_scale;
            taylor_w = i_taylor;
            dt_q = i_dt;
            formant_t = i_formant_t;
            formant_last = i_formant_t;
            tableipol = i_tableipol0;
            tableid = i_tableid0;
            last_tableipol = i_last_tableipol0;
            last_tableid = i_last_tableid0;
            hpf_prev = i_hpf0;
            tempt[0] = i_tempt_0;  tempt[1] = i_tempt_1;
            tempt[2] = i_tempt_2;  tempt[3] = i_tempt_3;
            tempt[4] = i_tempt_4;  tempt[5] = i_tempt_5;
            tempt[6] = i_tempt_6;  tempt[7] = i_tempt_7;
            tempt[8] = i_tempt_8;  tempt[9] = i_tempt_9;
            tempt[10] = i_tempt_10; tempt[11] = i_tempt_11;
            tempt[12] = i_tempt_12; tempt[13] = i_tempt_13;
            tempt[14] = i_tempt_14; tempt[15] = i_tempt_15;
            init_latched = 1'b1;
        end
    end

    integer init_i;
    initial begin
        osc_out = 0;
        bufpos = 0;
        for (init_i = 0; init_i < OB_END; init_i = init_i + 1)
            osc[init_i] = 32'sd0;
        for (init_i = 0; init_i < 16; init_i = init_i + 1) begin
            oscstate[init_i] = 64'sd0;
            wstate[init_i] = 0;
            last_level[init_i] = 32'sd0;
            mipmap[init_i] = 0;
            mipmap_ofs[init_i] = 0;
        end
        for (init_i = 0; init_i < 6*16; init_i = init_i + 1)
            frame_touched[init_i] = 1'b0;
        formant_word = ONE;      // ntp_tuningctr(0) == 1.0 exactly
    end

endmodule
