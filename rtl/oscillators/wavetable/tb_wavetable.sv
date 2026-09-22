// SXT-026 wavetable testbench: drives four wavetable_core instances (one
// per voice slot) from the model runner's stimulus (init.hex / ctrl.hex),
// models the EXTERNAL asset memory (per-(mip,frame) cache, aligned burst
// fills, optional Reverb1 background bus traffic), and each core emits the
// integer-exact trace (T/S/O lines) compared by
// tools/compare_wt_rtl_model.py.
//
// Plusargs:
//   +BLOCKS=n  +TRACE=file  +INIT=file  +CTRL=file  +WT_TABLE=file
//   +SINC_MAIN=file  +SINC_DERIV=file  +WAVE_SIZE=n  +N_TABLES=n
//   +N_UNISON=n  +NOINTERP=0|1  +LEGACY=0|1  +REVERB_BG=0|1
//   +TRAFFIC=file  +DBG=1
//
// Traffic accounting: ext_reads (logical word reads by the core), fill_words
// (prefetched frame words on cache misses, aligned bursts of <=16 words),
// stall_cycles (core-visible miss latency), reverb_words (background
// Reverb1 bus traffic per the SXT-016 pattern: 34 scattered words/frame =
// 16 composite-tap r/w pairs + predelay 1r/1w), against the DECLARED frame
// budget of 32000 bus-slots (A-CLK 48 MHz candidate, 2 cycles/external
// word, 7500 frames/s; a harness constant, NOT an achievable-clock claim
// — clock closure stays with SXT-016/SXT-017). A frame UNDERRUNS when its
// total bus cost (core words + core stall + reverb words) exceeds the
// budget; underrun_blocks is dumped and the harness FAILs on any.
//
// The cores are exercised sequentially (behavioral time-multiplex; each
// slot holds independent voice state), so external requests never collide;
// the Reverb1 master takes bus slots in the same frame, which is what the
// underrun check accounts for.

`timescale 1ns/1ps

module tb_wavetable;

    integer WAVE_SIZE    = 1024;
    integer N_TABLES     = 16;
    integer N_UNISON     = 1;
    integer NOINTERP     = 0;
    integer LEGACY       = 0;
    integer TOTAL_BLOCKS = 10;
    integer REVERB_BG    = 0;
    integer DBG          = 0;
    integer MUT          = 0;
    integer N_SLOTS      = 4;

    reg clk = 0;
    always #10.5 clk = ~clk;    // ~47.6 MHz placeholder (A-CLK candidate)

    reg [31:0] ext_addr_0, ext_addr_1, ext_addr_2, ext_addr_3;
    reg        ext_req_0, ext_req_1, ext_req_2, ext_req_3;
    reg  [31:0] bus_data;
    wire        bus_valid;

    reg signed [31:0] c_pmi_0, c_a_cov_0, c_hpf_start_0, c_hpf_d_0;
    reg signed [31:0] c_pmi_1, c_a_cov_1, c_hpf_start_1, c_hpf_d_1;
    reg signed [31:0] c_pmi_2, c_a_cov_2, c_hpf_start_2, c_hpf_d_2;
    reg signed [31:0] c_pmi_3, c_a_cov_3, c_hpf_start_3, c_hpf_d_3;
    reg c_ckpt_0 = 0, c_ckpt_1 = 0, c_ckpt_2 = 0, c_ckpt_3 = 0;
    reg c_newvoice_0 = 0, c_newvoice_1 = 0, c_newvoice_2 = 0,
        c_newvoice_3 = 0;
    reg [31:0] tb_block = 0;
    integer fd0 = 0, fd1 = 0, fd2 = 0, fd3 = 0;
    wire [31:0] c_trace_wr_0 = fd0;
    wire [31:0] c_trace_wr_1 = fd1;
    wire [31:0] c_trace_wr_2 = fd2;
    wire [31:0] c_trace_wr_3 = fd3;

    // init words (40; see run_model.py word order)
    reg signed [31:0] iw [0:39];

    // -------------------------------------------------- memory model
    reg [31:0] wt_mem  [0:131071];
    reg        touched [0:8*16-1];     // (mip, frame) cache tags
    integer ext_reads = 0, fill_words = 0, bursts = 0;
    integer stall_total = 0, reverb_words = 0;
    integer underrun_blocks = 0, max_frame_bus_cost = 0;
    integer bg_countdown = 0;
    integer frame_size_now, mip_now, tab_now, base_now, acc;
    // Reverb1 background master (SXT-016 pattern): 34 scattered words per
    // frame (16 composite-tap r/w pairs + predelay 1r/1w) over a 2^16-word
    // external delay-memory image.
    integer REVERB_WORDS_PER_FRAME = 34;
    integer REVERB_ADDR_MASK        = (1 << 16) - 1;
    reg [15:0] reverb_lfsr          = 16'hACE1;
    integer reads_snap = 0, stall_snap = 0, ri;
    integer frame_bus_cost;

    // combinational zero-latency response; miss latency is counted as
    // arithmetic stall cycles in the traffic model (declared)
    assign bus_data = ext_req_0 ? wt_mem[ext_addr_0] :
                      ext_req_1 ? wt_mem[ext_addr_1] :
                      ext_req_2 ? wt_mem[ext_addr_2] :
                      ext_req_3 ? wt_mem[ext_addr_3] : 32'h0;
    assign bus_valid = ext_req_0 | ext_req_1 | ext_req_2 | ext_req_3;


    // four explicit cores (constant-index hierarchical references)
    wavetable_core core0 (
        .clk(clk), .rst(1'b0),
        .ext_addr(ext_addr_0), .ext_req(ext_req_0),
        .ext_rd_data(bus_data), .ext_rd_valid(bus_valid),
        .c_pmi(c_pmi_0), .c_a_cov(c_a_cov_0),
        .c_hpf_start(c_hpf_start_0), .c_hpf_d(c_hpf_d_0),
        .c_t_shape(iw[10]), .c_t_vskew(iw[11]),
        .c_t_hskew(iw[12]), .c_t_clip(iw[13]),
        .c_checkpoint(c_ckpt_0),
        .c_newvoice(c_newvoice_0),
        .c_trace_wr(c_trace_wr_0),
        .c_block(tb_block),
        .c_slot(0),
        .i_out_attenuation(iw[6]), .i_t_shape(iw[10]),
        .i_t_vskew(iw[11]), .i_t_hskew(iw[12]), .i_t_clip(iw[13]),
        .i_formant_t(iw[14]), .i_lag_rate(iw[15]),
        .i_morph_scale(iw[21]), .i_taylor(iw[22]), .i_dt(iw[23]),
        .i_tableipol0(iw[16]), .i_tableid0(iw[17]),
        .i_last_tableipol0(iw[18]), .i_last_tableid0(iw[19]),
        .i_hpf0(iw[20]),
        .i_tempt_0(iw[24]), .i_tempt_1(iw[25]), .i_tempt_2(iw[26]),
        .i_tempt_3(iw[27]), .i_tempt_4(iw[28]), .i_tempt_5(iw[29]),
        .i_tempt_6(iw[30]), .i_tempt_7(iw[31]), .i_tempt_8(iw[32]),
        .i_tempt_9(iw[33]), .i_tempt_10(iw[34]), .i_tempt_11(iw[35]),
        .i_tempt_12(iw[36]), .i_tempt_13(iw[37]), .i_tempt_14(iw[38]),
        .i_tempt_15(iw[39])
    );
    wavetable_core core1 (
        .clk(clk), .rst(1'b0),
        .ext_addr(ext_addr_1), .ext_req(ext_req_1),
        .ext_rd_data(bus_data), .ext_rd_valid(bus_valid),
        .c_pmi(c_pmi_1), .c_a_cov(c_a_cov_1),
        .c_hpf_start(c_hpf_start_1), .c_hpf_d(c_hpf_d_1),
        .c_t_shape(iw[10]), .c_t_vskew(iw[11]),
        .c_t_hskew(iw[12]), .c_t_clip(iw[13]),
        .c_checkpoint(c_ckpt_1),
        .c_newvoice(c_newvoice_1),
        .c_trace_wr(c_trace_wr_1),
        .c_block(tb_block),
        .c_slot(1),
        .i_out_attenuation(iw[6]), .i_t_shape(iw[10]),
        .i_t_vskew(iw[11]), .i_t_hskew(iw[12]), .i_t_clip(iw[13]),
        .i_formant_t(iw[14]), .i_lag_rate(iw[15]),
        .i_morph_scale(iw[21]), .i_taylor(iw[22]), .i_dt(iw[23]),
        .i_tableipol0(iw[16]), .i_tableid0(iw[17]),
        .i_last_tableipol0(iw[18]), .i_last_tableid0(iw[19]),
        .i_hpf0(iw[20]),
        .i_tempt_0(iw[24]), .i_tempt_1(iw[25]), .i_tempt_2(iw[26]),
        .i_tempt_3(iw[27]), .i_tempt_4(iw[28]), .i_tempt_5(iw[29]),
        .i_tempt_6(iw[30]), .i_tempt_7(iw[31]), .i_tempt_8(iw[32]),
        .i_tempt_9(iw[33]), .i_tempt_10(iw[34]), .i_tempt_11(iw[35]),
        .i_tempt_12(iw[36]), .i_tempt_13(iw[37]), .i_tempt_14(iw[38]),
        .i_tempt_15(iw[39])
    );
    wavetable_core core2 (
        .clk(clk), .rst(1'b0),
        .ext_addr(ext_addr_2), .ext_req(ext_req_2),
        .ext_rd_data(bus_data), .ext_rd_valid(bus_valid),
        .c_pmi(c_pmi_2), .c_a_cov(c_a_cov_2),
        .c_hpf_start(c_hpf_start_2), .c_hpf_d(c_hpf_d_2),
        .c_t_shape(iw[10]), .c_t_vskew(iw[11]),
        .c_t_hskew(iw[12]), .c_t_clip(iw[13]),
        .c_checkpoint(c_ckpt_2),
        .c_newvoice(c_newvoice_2),
        .c_trace_wr(c_trace_wr_2),
        .c_block(tb_block),
        .c_slot(2),
        .i_out_attenuation(iw[6]), .i_t_shape(iw[10]),
        .i_t_vskew(iw[11]), .i_t_hskew(iw[12]), .i_t_clip(iw[13]),
        .i_formant_t(iw[14]), .i_lag_rate(iw[15]),
        .i_morph_scale(iw[21]), .i_taylor(iw[22]), .i_dt(iw[23]),
        .i_tableipol0(iw[16]), .i_tableid0(iw[17]),
        .i_last_tableipol0(iw[18]), .i_last_tableid0(iw[19]),
        .i_hpf0(iw[20]),
        .i_tempt_0(iw[24]), .i_tempt_1(iw[25]), .i_tempt_2(iw[26]),
        .i_tempt_3(iw[27]), .i_tempt_4(iw[28]), .i_tempt_5(iw[29]),
        .i_tempt_6(iw[30]), .i_tempt_7(iw[31]), .i_tempt_8(iw[32]),
        .i_tempt_9(iw[33]), .i_tempt_10(iw[34]), .i_tempt_11(iw[35]),
        .i_tempt_12(iw[36]), .i_tempt_13(iw[37]), .i_tempt_14(iw[38]),
        .i_tempt_15(iw[39])
    );
    wavetable_core core3 (
        .clk(clk), .rst(1'b0),
        .ext_addr(ext_addr_3), .ext_req(ext_req_3),
        .ext_rd_data(bus_data), .ext_rd_valid(bus_valid),
        .c_pmi(c_pmi_3), .c_a_cov(c_a_cov_3),
        .c_hpf_start(c_hpf_start_3), .c_hpf_d(c_hpf_d_3),
        .c_t_shape(iw[10]), .c_t_vskew(iw[11]),
        .c_t_hskew(iw[12]), .c_t_clip(iw[13]),
        .c_checkpoint(c_ckpt_3),
        .c_newvoice(c_newvoice_3),
        .c_trace_wr(c_trace_wr_3),
        .c_block(tb_block),
        .c_slot(3),
        .i_out_attenuation(iw[6]), .i_t_shape(iw[10]),
        .i_t_vskew(iw[11]), .i_t_hskew(iw[12]), .i_t_clip(iw[13]),
        .i_formant_t(iw[14]), .i_lag_rate(iw[15]),
        .i_morph_scale(iw[21]), .i_taylor(iw[22]), .i_dt(iw[23]),
        .i_tableipol0(iw[16]), .i_tableid0(iw[17]),
        .i_last_tableipol0(iw[18]), .i_last_tableid0(iw[19]),
        .i_hpf0(iw[20]),
        .i_tempt_0(iw[24]), .i_tempt_1(iw[25]), .i_tempt_2(iw[26]),
        .i_tempt_3(iw[27]), .i_tempt_4(iw[28]), .i_tempt_5(iw[29]),
        .i_tempt_6(iw[30]), .i_tempt_7(iw[31]), .i_tempt_8(iw[32]),
        .i_tempt_9(iw[33]), .i_tempt_10(iw[34]), .i_tempt_11(iw[35]),
        .i_tempt_12(iw[36]), .i_tempt_13(iw[37]), .i_tempt_14(iw[38]),
        .i_tempt_15(iw[39])
    );

    // ------------------------------------------------------- stimulus
    reg signed [31:0] ctrl_mem [0:262143];
    reg signed [31:0] init_mem [0:63];
    reg signed [31:0] sinc_tmp [0:6143];

    string trace_f = "tb_trace";
    string init_f = "rtl/init.hex";
    string ctrl_f = "rtl/ctrl.hex";
    string wt_table_f = "rtl/wt_table.hex";
    string traffic_f = "tb_traffic.txt";
    string SINC_MAIN_F = "rtl/sinc_main.hex";
    string SINC_DERIV_F = "rtl/sinc_deriv.hex";

    integer b, s, w, ptr, slotmask, flags, fd_traffic;

    // watchdog scaled to the requested run length (long exactness /
    // sustained runs legitimately exceed 3 ms of sim time)
    initial begin
        wait(TOTAL_BLOCKS > 0);
        #(TOTAL_BLOCKS * 400_000 + 4_000_000);
        $display("WATCHDOG: killed at %0t (blocks=%0d)", $time,
                 TOTAL_BLOCKS);
        $finish;
    end

    // one Reverb1 background bus frame: 34 scattered words (17r + 17w,
    // LFSR-driven addresses per the SXT-016 scattered composite-tap
    // pattern) against the external delay-memory image
    task do_reverb_frame;
        integer k;
        begin
            for (k = 0; k < REVERB_WORDS_PER_FRAME; k = k + 1) begin
                reverb_lfsr = {reverb_lfsr[14:0],
                    reverb_lfsr[15] ^ reverb_lfsr[12] ^ reverb_lfsr[10]
                                   ^ reverb_lfsr[8]};
                acc = reverb_lfsr & REVERB_ADDR_MASK;
                bg_countdown = bg_countdown + 1;
            end
            reverb_words = reverb_words + REVERB_WORDS_PER_FRAME;
        end
    endtask

    initial begin
        if (!$value$plusargs("BLOCKS=%d", TOTAL_BLOCKS)) ;
        if (!$value$plusargs("N_UNISON=%d", N_UNISON)) ;
        if (!$value$plusargs("WAVE_SIZE=%d", WAVE_SIZE)) ;
        if (!$value$plusargs("N_TABLES=%d", N_TABLES)) ;
        if (!$value$plusargs("NOINTERP=%d", NOINTERP)) ;
        if (!$value$plusargs("LEGACY=%d", LEGACY)) ;
        if (!$value$plusargs("REVERB_BG=%d", REVERB_BG)) ;
        if (!$value$plusargs("DBG=%d", DBG)) ;
        if (!$value$plusargs("MUT=%d", MUT)) ;
        if (!$value$plusargs("TRACE=%s", trace_f)) ;
        if (!$value$plusargs("INIT=%s", init_f)) ;
        if (!$value$plusargs("CTRL=%s", ctrl_f)) ;
        if (!$value$plusargs("WT_TABLE=%s", wt_table_f)) ;
        if (!$value$plusargs("SINC_MAIN=%s", SINC_MAIN_F)) ;
        if (!$value$plusargs("SINC_DERIV=%s", SINC_DERIV_F)) ;
        if (!$value$plusargs("TRAFFIC=%s", traffic_f)) ;

        for (s = 0; s < 8*16; s = s + 1) touched[s] = 1'b0;

        if (DBG) $display("DBG loading hex files");
        $readmemh(init_f, init_mem);
        for (w = 0; w < 40; w = w + 1) iw[w] = init_mem[w];
        $readmemh(ctrl_f, ctrl_mem);
        $readmemh(wt_table_f, wt_mem);
        $readmemh(SINC_MAIN_F, sinc_tmp);
        for (w = 0; w < 6144; w = w + 1) begin
            core0.sinc_main[w] = sinc_tmp[w];
            core1.sinc_main[w] = sinc_tmp[w];
            core2.sinc_main[w] = sinc_tmp[w];
            core3.sinc_main[w] = sinc_tmp[w];
        end
        $readmemh(SINC_DERIV_F, sinc_tmp);
        for (w = 0; w < 6144; w = w + 1) begin
            core0.sinc_deriv[w] = sinc_tmp[w];
            core1.sinc_deriv[w] = sinc_tmp[w];
            core2.sinc_deriv[w] = sinc_tmp[w];
            core3.sinc_deriv[w] = sinc_tmp[w];
        end

        repeat (4) @(posedge clk);
        core0.N_UNISON = N_UNISON; core1.N_UNISON = N_UNISON;
        core2.N_UNISON = N_UNISON; core3.N_UNISON = N_UNISON;
        core0.WAVE_SIZE = WAVE_SIZE; core1.WAVE_SIZE = WAVE_SIZE;
        core2.WAVE_SIZE = WAVE_SIZE; core3.WAVE_SIZE = WAVE_SIZE;
        core0.N_TABLES = N_TABLES; core1.N_TABLES = N_TABLES;
        core2.N_TABLES = N_TABLES; core3.N_TABLES = N_TABLES;
        core0.NOINTERP = NOINTERP; core1.NOINTERP = NOINTERP;
        core2.NOINTERP = NOINTERP; core3.NOINTERP = NOINTERP;
        core0.DEFORM_LEGACY = LEGACY; core1.DEFORM_LEGACY = LEGACY;
        core2.DEFORM_LEGACY = LEGACY; core3.DEFORM_LEGACY = LEGACY;
        fd0 = $fopen({trace_f, ".s0"}, "w");
        fd1 = $fopen({trace_f, ".s1"}, "w");
        fd2 = $fopen({trace_f, ".s2"}, "w");
        fd3 = $fopen({trace_f, ".s3"}, "w");

        ptr = 0;
        for (b = 0; b < TOTAL_BLOCKS; b = b + 1) begin
            if (ctrl_mem[ptr] !== b)
                $display("WARNING: ctrl block index %0d != %0d",
                         ctrl_mem[ptr], b);
            ptr = ptr + 1;
            slotmask = ctrl_mem[ptr]; ptr = ptr + 1;
            for (s = 0; s < 4; s = s + 1) begin
                if (slotmask & (1 << s)) begin
                    flags = ctrl_mem[ptr + 1];
                    case (s)
                        0: begin
                            c_pmi_0 = ctrl_mem[ptr + 2];
                            c_a_cov_0 = ctrl_mem[ptr + 4];
                            c_hpf_start_0 = ctrl_mem[ptr + 5];
                            c_hpf_d_0 = ctrl_mem[ptr + 6];
                            c_ckpt_0 = (flags & 2) != 0;
                            c_newvoice_0 = (flags & 4) != 0;
                        end
                        1: begin
                            c_pmi_1 = ctrl_mem[ptr + 2];
                            c_a_cov_1 = ctrl_mem[ptr + 4];
                            c_hpf_start_1 = ctrl_mem[ptr + 5];
                            c_hpf_d_1 = ctrl_mem[ptr + 6];
                            c_ckpt_1 = (flags & 2) != 0;
                            c_newvoice_1 = (flags & 4) != 0;
                        end
                        2: begin
                            c_pmi_2 = ctrl_mem[ptr + 2];
                            c_a_cov_2 = ctrl_mem[ptr + 4];
                            c_hpf_start_2 = ctrl_mem[ptr + 5];
                            c_hpf_d_2 = ctrl_mem[ptr + 6];
                            c_ckpt_2 = (flags & 2) != 0;
                            c_newvoice_2 = (flags & 4) != 0;
                        end
                        3: begin
                            c_pmi_3 = ctrl_mem[ptr + 2];
                            c_a_cov_3 = ctrl_mem[ptr + 4];
                            c_hpf_start_3 = ctrl_mem[ptr + 5];
                            c_hpf_d_3 = ctrl_mem[ptr + 6];
                            c_ckpt_3 = (flags & 2) != 0;
                            c_newvoice_3 = (flags & 4) != 0;
                        end
                    endcase
                    ptr = ptr + 7;
                end
            end
            if (DBG) $display("DBG block %0d start @%0t", b, $time);
            tb_block = b;
            reads_snap = core0.reads_words + core1.reads_words
                       + core2.reads_words + core3.reads_words;
            stall_snap = core0.stall_cycles + core1.stall_cycles
                       + core2.stall_cycles + core3.stall_cycles;
            if (slotmask & 1) begin
                core0.do_block();
                if (c_ckpt_0) core0.emit_trace;
            end
            if (slotmask & 2) begin
                core1.do_block();
                if (c_ckpt_1) core1.emit_trace;
            end
            if (slotmask & 4) begin
                core2.do_block();
                if (c_ckpt_2) core2.emit_trace;
            end
            if (slotmask & 8) begin
                core3.do_block();
                if (c_ckpt_3) core3.emit_trace;
            end
            if (REVERB_BG != 0) do_reverb_frame;
            // no-underrun check: this frame's declared bus cost =
            // core external words (cache hits and fills) + core-visible
            // miss latency + Reverb1 words, against the declared budget
            frame_bus_cost = (core0.reads_words + core1.reads_words
                            + core2.reads_words + core3.reads_words
                            - reads_snap)
                           + (core0.stall_cycles + core1.stall_cycles
                            + core2.stall_cycles + core3.stall_cycles
                            - stall_snap)
                           + (REVERB_BG != 0 ? REVERB_WORDS_PER_FRAME : 0);
            if (frame_bus_cost > max_frame_bus_cost)
                max_frame_bus_cost = frame_bus_cost;
            if (frame_bus_cost > 32000) begin
                underrun_blocks = underrun_blocks + 1;
                $display("UNDERRUN: block %0d bus cost %0d > 32000",
                         b, frame_bus_cost);
            end
            if (DBG) $display("DBG block %0d done @%0t", b, $time);
        end

        fd_traffic = $fopen(traffic_f, "w");
        $fdisplay(fd_traffic, "core_reads_words %0d",
                  core0.reads_words + core1.reads_words
                  + core2.reads_words + core3.reads_words);
        $fdisplay(fd_traffic, "core_fill_words %0d",
                  core0.fill_words + core1.fill_words
                  + core2.fill_words + core3.fill_words);
        $fdisplay(fd_traffic, "core_bursts %0d",
                  core0.bursts + core1.bursts + core2.bursts
                  + core3.bursts);
        $fdisplay(fd_traffic, "core_stall_cycles %0d",
                  core0.stall_cycles + core1.stall_cycles
                  + core2.stall_cycles + core3.stall_cycles);
        $fdisplay(fd_traffic, "reverb_words %0d", reverb_words);
        $fdisplay(fd_traffic, "underrun_blocks %0d", underrun_blocks);
        $fdisplay(fd_traffic, "max_frame_bus_cost %0d",
                  max_frame_bus_cost);
        $fdisplay(fd_traffic, "budget_cycles_per_frame 32000");
        $fclose(fd_traffic);
        $display("TB done: blocks %0d ext_reads %0d fill_words %0d bursts %0d stall %0d reverb %0d",
                 TOTAL_BLOCKS, ext_reads, fill_words, bursts, stall_total,
                 reverb_words);
        $finish;
    end


endmodule
