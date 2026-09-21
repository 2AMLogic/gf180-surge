// SXT-023 behavioral external-memory delay line (one channel).
// Models the writable external buffer holding one delay channel of
// max_delay_length + FIRipol_N words (Q10.21). Transaction-accurate: counts
// reads and writes; read latency is zero in this behavioral model (the
// tolerance analysis lives in rtl/effects/delay/ext_mem_if.md).
`timescale 1ns/1ps

module fx_line_ext (
    input  logic        cs,
    input  logic        we,
    input  logic [17:0] addr,
    input  logic [31:0] wdata,
    output logic [31:0] rdata,
    output longint unsigned rd_count,
    output longint unsigned wr_count,
    output longint unsigned hash
);
    reg [31:0] mem [0:(1<<18)+12-1];
    longint unsigned rd_q, wr_q, h_q;

    reg [8*256:1] zeros_name;
    initial begin
        if (!$value$plusargs("ZEROS=%s", zeros_name)) zeros_name = "line_zeros.hex";
        $readmemh(zeros_name, mem);
        rd_q = 0; wr_q = 0; h_q = 0;
    end

    always @(cs or we or addr or wdata) begin
        rdata = 32'h0;
        if (cs) begin
            rdata = mem[addr];
            if (we) begin
                h_q = h_q + $signed(wdata) - $signed(mem[addr]);
                mem[addr] = wdata;
                wr_q = wr_q + 1;
            end else begin
                rd_q = rd_q + 1;
            end
        end
    end

    assign rd_count = rd_q;
    assign wr_count = wr_q;
    assign hash     = h_q;
endmodule
