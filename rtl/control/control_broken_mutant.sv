// SXT-021 COMMITTED NEGATIVE CONTROL (do not fix in place).
//
// Deliberately mutated copy of rtl/control/control_top.sv: the event-queue
// depth constant is changed from 16 to 15 (one constant). The comparator
// (tools/compare_control_rtl.py --dut <this file>) MUST FAIL against the
// SXT-021 model: queue-overflow drop records and queue-count checkpoints
// diverge (e.g. the 30-event burst fixture drops 14 words in the mutant vs
// the model's 16-deep queue). If this file ever PASSES the comparator, the
// comparator's divergence detection is broken and must be repaired before
// any RTL-vs-model equality claim stands.
//
// Regenerate with: python3 tools/make_control_mutant.py

`timescale 1ns/1ps
// SXT-021 RTL control plane: event scheduler + frame counter + queue.
//
// Claim scope: iverilog-simulated RTL that must match the SXT-021 model
// (model/control/control_model.py) EXACTLY — integer equality on schedule
// decisions, queue/voice-table snapshots, drop records, and the stereo
// output stream (comparator: tools/compare_control_rtl.py). This file is
// NOT synthesis-closed, NOT timing-closed, and makes no gf180mcu claim.
//
// Declared conventions mirrored from model/control/README.md (normative):
//   * 32-sample blocks @ 48 kHz; one control pass per block (frame counter);
//   * events quantize UP to the block, never down (target = ceil(t/32));
//   * FIFO queue (QUEUE_DEPTH=16, event_queue_depth); a push onto a full
//     queue produces an EXPLICIT drop record (never silent corruption);
//   * declared per-block event reserve of 8 dispatched events (SXT-016
//     scheduler row); surplus stays queued and spills to later blocks;
//   * voice pool 8; steal = oldest active (smallest alloc seq), tie -> low
//     slot; note_off releases the oldest matching voice;
//   * patch change = HARD SWITCH at the block boundary (voices cleared,
//     queue flushed with an explicit count; v1 declared semantics);
//   * the engine slot is the STUB counter (module audio_stub_slot, named
//     per the repo *_stub* convention): L = {vcount[3:0], (g+1)&0xFFF},
//     R = L + 1 (mod 2^16), g = global sample index.
//
// Interface notes:
//   * one event per accepted cycle on ev_word; the DUT ALWAYS accepts the
//     cycle (ev_ready tied high) — a full queue turns the write into a drop
//     record so overload is visible inside the DUT, not hidden in the TB;
//   * pushes are only sampled in S_IDLE (the TB protocol guarantees this:
//     push, then tick, then wait for the ack);
//   * sample ticks are one tick per 48 kHz sample period; a block-start
//     tick stalls (no ack) while the drain FSM dispatches up to 8 events;
//     this models "control takes what it needs inside the sample period",
//     which is how the schedule accounting charges it.
//
// Timestamp/target field limits (declared, model-gated): t < 2^21 samples,
// target block fits 16 bits; the model fail-closes inputs beyond this.


module control_top #(
  parameter int QUEUE_DEPTH = 15,
  parameter int N_VOICES    = 8,
  parameter int EV_RESERVE  = 8
) (
  input  wire        clk,
  input  wire        rst,          // synchronous, active high (power-on)

  // event push stream (arrival order == FIFO order)
  input  wire        ev_valid,
  input  wire [79:0] ev_word,      // t[79:48] type[47:40] p1[39:24] p2[23:8]
  output wire        ev_ready,

  // sample-tick service (one per sample; ack after the sample is emitted)
  input  wire        tick_req,
  output wire        tick_ack,
  output wire        out_valid,
  output wire [15:0] out_l,
  output wire [15:0] out_r,

  // decision trace (1-cycle strobes)
  output reg         ev_strobe,
  output reg  [31:0] ev_b, ev_seq, ev_type, ev_p1, ev_p2,
  output reg  [31:0] ev_slot, ev_steal, ev_status, ev_flush,
  output reg         drop_strobe,
  output reg  [79:0] drop_word,
  output reg  [31:0] drop_b,

  // block-start snapshot (valid in the first out_valid cycle of a block)
  output reg  [31:0] dbg_block, dbg_qcount, dbg_patch, dbg_acount,
  output reg  [199:0] dbg_voices  // 8 x {active, note[7:0], seq[15:0]}
);

  localparam [15:0] QD     = QUEUE_DEPTH;
  localparam [15:0] QD_M1  = QUEUE_DEPTH - 1;

  // event types (shared encoding with the model)
  localparam [7:0] T_NOTE_ON  = 8'd0, T_NOTE_OFF = 8'd1, T_CC     = 8'd2,
                   T_PITCHB   = 8'd3, T_PRESS    = 8'd4, T_PATCH  = 8'd5,
                   T_TEMPO    = 8'd6;
  // decision statuses (shared encoding with the model)
  localparam [7:0] S_ALLOC = 8'd0, S_STEAL = 8'd1, S_REL = 8'd2, S_NOV = 8'd3,
                   S_CC = 8'd4, S_PB = 8'd5, S_PR = 8'd6, S_Tempo = 8'd7,
                   S_PATCH = 8'd8;

  localparam int S_IDLE = 0, S_DRAIN = 1, S_RUN = 2;

  // ------------------------------------------------------------- state
  reg [71:0] q_mem [0:QUEUE_DEPTH-1];  // {seq[15:0] target[15:0] type p1 p2}
  reg [15:0] wr_ptr, rd_ptr, qcount, seq_ctr;
  reg [15:0] alloc_ctr;
  reg        v_active [0:N_VOICES-1];
  reg [7:0]  v_note   [0:N_VOICES-1];
  reg [15:0] v_seq    [0:N_VOICES-1];
  reg [31:0] vcount;
  reg [31:0] patch, block, s_local, sample_ctr, drain_ctr;
  reg [1:0]  state;

  // ------------------------------------------------- push decode (wires)
  wire [31:0] p_t    = ev_word[79:48];
  wire [4:0]  p_off  = ev_word[52:48];
  wire [19:0] p_hi   = ev_word[72:53];   // t[20:5]
  wire [15:0] p_tgt  = (p_off != 5'd0) ? (p_hi + 20'd1) : p_hi; // ceil UP
  wire [7:0]  p_type = ev_word[47:40];
  wire [15:0] p_p1   = ev_word[39:24];
  wire [15:0] p_p2   = ev_word[23:8];

  assign ev_ready = 1'b1;

  // ------------------------------------------------ head + decision comb
  wire [15:0] h_seq  = q_mem[rd_ptr][71:56];
  wire [15:0] h_tgt  = q_mem[rd_ptr][55:40];
  wire [7:0]  h_type = q_mem[rd_ptr][39:32];
  wire [15:0] h_p1   = q_mem[rd_ptr][31:16];
  wire [15:0] h_p2   = q_mem[rd_ptr][15:0];

  integer i;
  reg        free_found; reg [4:0] free_i;
  reg        vict_found; reg [15:0] vict_seq; reg [4:0] vict_i;
  reg        rel_found;  reg [15:0] rel_seq;  reg [4:0] rel_i;
  reg        pop_en;
  reg [7:0]  d_status; reg [4:0] d_slot; reg d_steal; reg [15:0] d_flush;

  always @* begin
    pop_en = (state == S_DRAIN) && (drain_ctr < EV_RESERVE)
             && (qcount != 16'd0) && (h_tgt <= block[15:0]);
    free_found = 1'b0; free_i  = 5'd0;
    vict_found = 1'b0; vict_seq = 16'hFFFF; vict_i = 5'd0;
    rel_found  = 1'b0; rel_seq  = 16'hFFFF; rel_i  = 5'd0;
    d_status = 8'hFF; d_slot = 5'h1F; d_steal = 1'b0; d_flush = 16'd0;
    if (pop_en) begin
      case (h_type)
        T_NOTE_ON: begin
          for (i = 0; i < N_VOICES; i = i + 1)
            if (!v_active[i] && !free_found) begin
              free_found = 1'b1; free_i = i[4:0];
            end
          for (i = 0; i < N_VOICES; i = i + 1)
            if (v_active[i] && (!vict_found || v_seq[i] < vict_seq)) begin
              vict_found = 1'b1; vict_seq = v_seq[i]; vict_i = i[4:0];
            end
          if (free_found) begin d_status = S_ALLOC; d_slot = free_i; end
          else begin d_status = S_STEAL; d_slot = vict_i; d_steal = 1'b1; end
        end
        T_NOTE_OFF: begin
          for (i = 0; i < N_VOICES; i = i + 1)
            if (v_active[i] && (v_note[i] == h_p1[7:0])
                && (!rel_found || v_seq[i] < rel_seq)) begin
              rel_found = 1'b1; rel_seq = v_seq[i]; rel_i = i[4:0];
            end
          if (rel_found) begin d_status = S_REL; d_slot = rel_i; end
          else begin d_status = S_NOV; end
        end
        T_CC:     d_status = S_CC;
        T_PITCHB: d_status = S_PB;
        T_PRESS:  d_status = S_PR;
        T_TEMPO:  d_status = S_Tempo;
        T_PATCH:  begin
                    d_status = S_PATCH;
                    d_flush = qcount - 16'd1;  // exclude the patch event itself
                  end
        default:  d_status = 8'hFF;
      endcase
    end
  end

  // snapshot pack (combinational; registered on the DRAIN->RUN edge)
  // voice i occupies bits [25*i +: 25] as {active, note[7:0], seq[15:0]}
  reg [199:0] snap_voices;
  always @* begin
    for (i = 0; i < N_VOICES; i = i + 1)
      snap_voices[25*i +: 25] = {v_active[i], v_note[i], v_seq[i]};
  end

  // sample output valid/ack: high during the S_RUN cycle (pre-increment)
  assign out_valid = (state == S_RUN);
  assign tick_ack  = (state == S_RUN);

  // ------------------------------------------------------------ stub slot
  // audio_stub_slot: 16-bit counter + active-voice nibble (see header).
  wire [36:0] g1     = {block[31:0], s_local[4:0]} + 37'd1;  // g + 1
  wire [15:0] stub_l = {vcount[3:0], g1[11:0]};
  wire [15:0] stub_r = stub_l + 16'd1;
  assign out_l = stub_l;
  assign out_r = stub_r;

  // -------------------------------------------------------------- main FS
  always @(posedge clk) begin
    if (rst) begin
      state <= S_IDLE; wr_ptr <= 16'd0; rd_ptr <= 16'd0; qcount <= 16'd0;
      seq_ctr <= 16'd0; alloc_ctr <= 16'd0; vcount <= 32'd0;
      patch <= 32'd0; block <= 32'd0; s_local <= 32'd0; sample_ctr <= 32'd0;
      drain_ctr <= 32'd0;
      ev_strobe <= 1'b0; drop_strobe <= 1'b0;
      for (i = 0; i < N_VOICES; i = i + 1) begin
        v_active[i] <= 1'b0; v_note[i] <= 8'd0; v_seq[i] <= 16'd0;
      end
    end else begin
      ev_strobe <= 1'b0; drop_strobe <= 1'b0;
      // push: accepted in IDLE or RUN (never in DRAIN, where pops would
      // race the queue update). The TB catches out_valid at the RUN-entry
      // edge, so mid-block pushes land on the RUN cycle; block-start
      // pushes (t on the boundary) land in IDLE, before the drain.
      if (ev_valid && state != S_DRAIN) begin
        seq_ctr <= seq_ctr + 16'd1;
        if (qcount == QD) begin
          drop_strobe <= 1'b1; drop_word <= ev_word; drop_b <= block;
        end else begin
          q_mem[wr_ptr] <= {seq_ctr, p_tgt, p_type, p_p1, p_p2};
          wr_ptr <= (wr_ptr == QD_M1) ? 16'd0 : wr_ptr + 16'd1;
          qcount <= qcount + 16'd1;
        end
      end
      case (state)
        S_IDLE: if (tick_req) begin
          drain_ctr <= 32'd0;   // per-block dispatch reserve budget
          state <= (s_local == 32'd0) ? S_DRAIN : S_RUN;
        end
        S_DRAIN: begin
          if (pop_en) begin
            if (h_type == T_NOTE_ON) begin
              if (free_found) begin
                v_active[free_i] <= 1'b1; v_note[free_i] <= h_p1[7:0];
                v_seq[free_i] <= alloc_ctr; alloc_ctr <= alloc_ctr + 16'd1;
                vcount <= vcount + 32'd1;
              end else begin
                v_note[vict_i] <= h_p1[7:0]; v_seq[vict_i] <= alloc_ctr;
                alloc_ctr <= alloc_ctr + 16'd1;
              end
            end else if (h_type == T_NOTE_OFF) begin
              if (rel_found) begin
                v_active[rel_i] <= 1'b0; v_note[rel_i] <= 8'd0;
                v_seq[rel_i] <= 16'd0; vcount <= vcount - 32'd1;
              end
            end else if (h_type == T_PATCH) begin
              for (i = 0; i < N_VOICES; i = i + 1) begin
                v_active[i] <= 1'b0; v_note[i] <= 8'd0; v_seq[i] <= 16'd0;
              end
              vcount <= 32'd0; patch <= {16'd0, h_p1};
              qcount <= 16'd0; wr_ptr <= 16'd0; rd_ptr <= 16'd0;
            end else begin
              // cc / pitch bend / pressure / tempo: recorded only
            end
            if (h_type != T_PATCH) begin
              rd_ptr <= (rd_ptr == QD_M1) ? 16'd0 : rd_ptr + 16'd1;
              qcount <= qcount - 16'd1;
            end
            ev_strobe <= 1'b1;
            ev_b <= block; ev_seq <= {16'd0, h_seq}; ev_type <= {24'd0, h_type};
            ev_p1 <= {16'd0, h_p1}; ev_p2 <= {16'd0, h_p2};
            ev_slot <= {27'd0, d_slot}; ev_steal <= {31'd0, d_steal};
            ev_status <= {24'd0, d_status}; ev_flush <= {16'd0, d_flush};
            drain_ctr <= drain_ctr + 32'd1;
          end else begin
            // end of drain: snapshot, then emit sample 0 of the block
            dbg_block <= block; dbg_qcount <= {16'd0, qcount};
            dbg_patch <= patch; dbg_acount <= vcount;
            dbg_voices <= snap_voices;
            state <= S_RUN;
          end
        end
        S_RUN: begin
          sample_ctr <= sample_ctr + 32'd1;
          if (s_local == 32'd31) begin
            s_local <= 32'd0; block <= block + 32'd1;
          end else begin
            s_local <= s_local + 32'd1;
          end
          state <= S_IDLE;
        end
        default: state <= S_IDLE;
      endcase
    end
  end

endmodule
