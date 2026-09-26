// SXT-028k Airwindows "Logical" (streamed algorithm id 4) core.
//
// Implements the SAME integer schedule as the frozen fixed-point model
// (model/effects/aw-4/logical4_model.py): a48 audio words (48-bit, 35 frac),
// c96 control words (96-bit, 53 frac), t64 target words (64-bit, 43 frac),
// s96 sag accumulators (96-bit, 54 frac), k31 coefficient words, round-half-
// up `(x + 2^(f-1)) >>> f`, saturating stores.
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality of every output word and every per-block per-instance
// checkpoint; tools/compare_rtl_model_aw4.py). NOT synthesis-closed, NOT
// timing-closed; no gf180mcu / FPGA claim, no reference-fidelity claim, no
// musical-quality claim.
//
// TWO INSTANCES live in this module with COMPLETELY DISJOINT state records
// (`inst` indexes every state array). The shared-instance schedule
// time-multiplexes them; nothing is pooled. rtl/effects/aw-4/
// logical4_mutants.sv is the same module with -DNC_SHARED_STATE pooling
// them, which must FAIL the dual-instance equality.
//
// NO EXTERNAL MEMORY. The pinned 1000-double sag arrays are allocation, not
// reachable state: only taps of age 2 and 3 are ever read, so each line is a
// 4-word ring. There is no em_* port because there is no external traffic to
// issue (proved model-side; see the buffer report).
//
// Every numeric constant arrives from the frozen model through cfg.hex --
// the RTL holds STRUCTURE only, so a constant can never drift between the
// two sides. The only tables compiled in are the two ROM images emitted by
// model/effects/aw-4/tables.py (sin, 1-cos; derived, not quoted).
//
// COST NOTE (recorded, not a fit claim): the `S_DIVP`/`S_DIVN` states each
// perform one 128-bit-by-64-bit division. A real implementation needs a
// sequential divider (or a log-domain control path); this harness uses the
// language operator because its job is exactness against the frozen model,
// not a schedule. Counted and reported in reports/SXT-028k/EVIDENCE.md.
//
// Structure citations (read, never copied): airwindows Logical4Proc.cpp
// processReplacing() + Logical4.cpp constructor, via the pinned
// surge@58914e59 AirWindowsEffect adapter. Original to this repository
// (Apache-2.0).
`timescale 1ns/1ps

// ---------------------------------------------------------------------------
// Fault-injection macros. NONE of them is defined in a normal compile; the
// clean core is what `iverilog -g2012 tb_logical4.sv logical4_core.sv` builds
// and what the exactness claim is made about. logical4_mutants.sv includes
// THIS file with one NC_* selected, so every negative control is injected
// into the real core rather than into a copy that could drift away from it
// (tests/test_sxt028k.py asserts the clean build defines none of them).
// ---------------------------------------------------------------------------
`ifdef NC_SHARED_STATE
  // DEFECT: both instances read and write instance 0's state record --
  // "shared instead of per-instance state" (tb_fx_shared_line.sv defect).
  `define L4_INST 0
`else
  `define L4_INST inst
`endif

`ifdef NC_SWAP_STAGES
  // DEFECT: the A -> B -> C stage cascade is evaluated in the WRONG order
  // (same-class slot permutation, tools/ablate_fx.py permute pattern).
  `define L4_STAGE (sel - int'(stage))
`else
  `define L4_STAGE int'(stage)
`endif

module logical4_core (
    input  logic        clk,
    input  logic        state_reset,
    input  logic        start_block,
    output logic        block_done
);

  localparam int BLOCK   = 32;
  localparam int NSTAGE  = 3;
  localparam int NCH     = 2;
  localparam int RING    = 4;
  localparam int GCMAX   = 499;

  localparam int F_A = 35;
  localparam int F_C = 53;
  localparam int F_T = 43;
  localparam int F_S = 54;
  localparam int F_K = 31;
  localparam int CALC_SHIFT = 2 * F_T - F_C;   // 33
  localparam int TBL_FRAC   = F_A - 9;         // 26
  localparam int TBL_WORDS  = 806;

  // ---- config plane word indices (frozen interface; see the comparator)
  localparam int P_SEL = 0,  P_FLAGS = 1, P_IGAIN = 2,  P_INVCOG = 3,
                 P_OGAIN = 4, P_RATIO = 5, P_IRATIO = 6, P_WET = 7,
                 P_DRY = 8,  P_REM0 = 9,  P_DIV0 = 12,  P_INTEN = 15,
                 P_PSAG = 16, P_FPOLD = 17, P_FPNEW = 18, P_PFLOOR = 19,
                 P_LEAK = 20, P_HALFS = 21, P_ONES = 22, P_ONEC = 23,
                 P_ONET = 24, P_BRMAX = 25, P_CLIP = 26, P_SOFF = 27,
                 P_A48MAX = 28, P_RECIP = 29;
  localparam int PLANE_WORDS = 31;

  logic signed [95:0] cfg [2][0:PLANE_WORDS-1];

  // ---- frozen ROM tables (shared by both instances; read-only)
  logic signed [39:0] sin_rom [0:TBL_WORDS-1];
  logic signed [39:0] omc_rom [0:TBL_WORDS-1];
  string sin_path = "rtl/effects/aw-4/sin_q31.hex";
  string omc_path = "rtl/effects/aw-4/omc_q31.hex";
  initial begin
    if ($value$plusargs("SINROM=%s", sin_path)) ;
    if ($value$plusargs("OMCROM=%s", omc_path)) ;
    $readmemh(sin_path, sin_rom);
    $readmemh(omc_path, omc_rom);
  end

  // ------------------------------------------------- per-instance state
  logic signed [15:0] gcount   [2];
  logic               fp_flip  [2];
  logic signed [95:0] c_apos   [2][NSTAGE][NCH];
  logic signed [95:0] c_aneg   [2][NSTAGE][NCH];
  logic signed [95:0] c_bpos   [2][NSTAGE][NCH];
  logic signed [95:0] c_bneg   [2][NSTAGE][NCH];
  logic signed [63:0] t_pos    [2][NSTAGE][NCH];
  logic signed [63:0] t_neg    [2][NSTAGE][NCH];
  logic signed [47:0] avgr     [2][NSTAGE][NCH];
  logic signed [47:0] nvgr     [2][NSTAGE][NCH];
  logic signed [95:0] sag_ctrl [2][NSTAGE][NCH];
  logic signed [95:0] sag_line [2][NSTAGE][NCH][RING];

  // ---- block I/O (harness-loaded)
  logic signed [47:0] in_l  [BLOCK];
  logic signed [47:0] in_r  [BLOCK];
  logic signed [47:0] out_l [BLOCK];
  logic signed [47:0] out_r [BLOCK];
  logic               inst = 1'b0;          // active instance for this block

  // ---- instrumentation (compared as a checkpoint field, not a claim)
  logic [31:0] n_div;
  logic [31:0] n_clip;
  logic [31:0] n_tap3;

  // ------------------------------------------------------------- helpers
  function automatic signed [191:0] rndsh(input signed [191:0] x,
                                          input integer f);
    if (f <= 0) rndsh = x;
    else        rndsh = (x + (192'sd1 <<< (f - 1))) >>> f;
  endfunction

  function automatic signed [191:0] mulr(input signed [191:0] a,
                                         input signed [191:0] b,
                                         input integer f);
    mulr = rndsh(a * b, f);
  endfunction

  function automatic signed [63:0] tbl(input integer which,
                                       input signed [63:0] u);
    integer i;
    logic signed [63:0] fr, t0, t1;
    begin
      i  = int'(u >>> TBL_FRAC);
      fr = u & ((64'sd1 <<< TBL_FRAC) - 1);
      t0 = which ? omc_rom[i] : sin_rom[i];
      t1 = which ? omc_rom[i + 1] : sin_rom[i + 1];
      tbl = t0 + (((t1 - t0) * fr + (64'sd1 <<< (TBL_FRAC - 1)))
                  >>> TBL_FRAC);
    end
  endfunction

  // --------------------------------------------------------------- FSM
  localparam logic [3:0] S_IDLE = 0, S_BEGIN = 1, S_SAG = 2, S_CPRE = 3,
                         S_DIVP = 4, S_NPRE = 5, S_DIVN = 6, S_CFIN = 7,
                         S_NEXT = 8, S_MIX = 9, S_DONE = 10;
  logic [3:0] st = S_IDLE;
  logic [5:0] k;                     // sample index in block
  logic [1:0] stage;
  logic       chan;
  integer     sel;

  logic signed [47:0] xl, xr, dryl, dryr;
  logic signed [47:0] oa [NCH];
  logic signed [47:0] ob [NCH];
  logic signed [47:0] oc [NCH];
  logic signed [47:0] xcur;
  logic signed [63:0] divop, calc_in;
  logic signed [95:0] calc_pos, calc_neg;
  logic signed [63:0] opos, oneg;

  // scratch (blocking, single-cycle)
  logic signed [191:0] w0, w1, w2;
  logic signed [95:0]  ssum, kk, dword, dold, ctl, clampv, thick, outw;
  logic signed [63:0]  ipos, sq, dr, dd, brv, bq, invq;
  logic signed [47:0]  bra, blended, shaped;
  logic signed [95:0]  tot, bnk_o;
  integer ridx, rold, age, tgt, other, si, ci, ii;

  task automatic do_reset();
    integer a, b, c, d;
    begin
      for (a = 0; a < 2; a++) begin
        gcount[a]  = 0;
        fp_flip[a] = 1'b1;
        for (b = 0; b < NSTAGE; b++)
          for (c = 0; c < NCH; c++) begin
            c_apos[a][b][c]   = cfg[a][P_ONEC];
            c_aneg[a][b][c]   = cfg[a][P_ONEC];
            c_bpos[a][b][c]   = cfg[a][P_ONEC];
            c_bneg[a][b][c]   = cfg[a][P_ONEC];
            t_pos[a][b][c]    = cfg[a][P_ONET][63:0];
            t_neg[a][b][c]    = cfg[a][P_ONET][63:0];
            avgr[a][b][c]     = 48'sd0;
            nvgr[a][b][c]     = 48'sd0;
            sag_ctrl[a][b][c] = 96'sd0;
            for (d = 0; d < RING; d++) sag_line[a][b][c][d] = 96'sd0;
          end
      end
      n_div = 0; n_clip = 0; n_tap3 = 0;
    end
  endtask

  initial begin
    block_done = 1'b0;
    n_div = 0; n_clip = 0; n_tap3 = 0;
  end

  always_ff @(posedge clk) begin
    if (state_reset) begin
      do_reset();
      st         = S_IDLE;
      block_done = 1'b0;
    end else begin
      case (st)
        // -------------------------------------------------------- idle
        S_IDLE: begin
          block_done = 1'b0;
          if (start_block) begin
            k   = 0;
            sel = int'(cfg[inst][P_SEL]);
            st  = S_BEGIN;
`ifdef NC_TAIL_KILL
            // DEFECT: the plausible "nothing to do on silence" optimisation.
            // An all-zero input block is emitted as silence and the whole
            // state record is frozen -- which DROPS the gain-recovery tail
            // this effect's tail claim rests on.
            begin : nc_tail_kill_blk
              logic silent;
              integer q;
              silent = 1'b1;
              for (q = 0; q < BLOCK; q++)
                if (in_l[q] != 0 || in_r[q] != 0) silent = 1'b0;
              if (silent) begin
                for (q = 0; q < BLOCK; q++) begin
                  out_l[q] = 48'sd0; out_r[q] = 48'sd0;
                end
                st = S_DONE;
              end
            end
`endif
          end
        end

        // ------------------------------------------- per-sample prologue
        S_BEGIN: begin
          ii   = int'(`L4_INST);
          dryl = in_l[k];
          dryr = in_r[k];
          xl   = in_l[k];
          xr   = in_r[k];
          for (si = 0; si < NCH; si++) begin
            oa[si] = 48'sd0; ob[si] = 48'sd0; oc[si] = 48'sd0;
          end
          gcount[ii] = gcount[ii] - 16'sd1;
          if (gcount[ii] < 0 || gcount[ii] > GCMAX) gcount[ii] = GCMAX;
          stage = 2'd0;
          chan  = 1'b0;
          st    = S_SAG;
        end

        // --------------------------------------------- Desk "Power Sag"
        S_SAG: begin
          ii   = int'(`L4_INST);
          si   = `L4_STAGE;
          ci   = chan ? 1 : 0;
          xcur = ci ? xr : xl;

          ssum = c_apos[ii][si][ci] + c_bpos[ii][si][ci]
               + c_aneg[ii][si][ci] + c_bneg[ii][si][ci];
          kk = cfg[ii][P_INTEN] - mulr(ssum, cfg[ii][P_PSAG], F_K);
          w0 = (xcur >= 0) ? 192'(xcur) : -192'(xcur);      // |x| as a48
          dword = mulr(w0, kk, F_A);

          ridx = (-int'(gcount[ii])) & (RING - 1);
`ifdef NC_FIX_Q1
          // DEFECT: "fixes" pinned quirk Q1 -- a constant 2-sample tap,
          // dropping the two 3-sample taps per 500-sample gcount period.
          age  = int'(cfg[ii][P_SOFF]);
`else
          age  = (int'(gcount[ii]) + int'(cfg[ii][P_SOFF]) <= GCMAX)
                 ? int'(cfg[ii][P_SOFF]) : int'(cfg[ii][P_SOFF]) + 1;
`endif
          if (age != int'(cfg[ii][P_SOFF])) n_tap3 = n_tap3 + 1;
          sag_line[ii][si][ci][ridx] = dword;
          rold = (ridx - age) & (RING - 1);
          dold = sag_line[ii][si][ci][rold];

          ctl    = sag_ctrl[ii][si][ci] + dword - dold - cfg[ii][P_LEAK];
          clampv = cfg[ii][P_ONES];
          if (ctl < 0) ctl = 96'sd0;
          if (ctl > cfg[ii][P_ONES]) begin
            clampv = clampv - (ctl - cfg[ii][P_ONES]);
            ctl    = cfg[ii][P_ONES];
          end
          if (clampv < cfg[ii][P_HALFS]) clampv = cfg[ii][P_HALFS];
          sag_ctrl[ii][si][ci] = ctl;

          thick = cfg[ii][P_ONES] - (ctl <<< 1);
          outw  = (thick >= 0) ? thick : -thick;

          brv = (w0 <= 192'(cfg[ii][P_BRMAX])) ? 64'(w0)
                                               : 64'(cfg[ii][P_BRMAX]);
          bq  = (thick > 0) ? tbl(0, brv) : tbl(1, brv);
          bra = 48'(bq <<< (F_A - F_K));

          blended = 48'(mulr(192'(xcur), 192'(cfg[ii][P_ONES] - outw), F_S));
          shaped  = 48'(mulr(192'(bra), 192'(outw), F_S));
          xcur    = (xcur > 0) ? (blended + shaped) : (blended - shaped);
          if (clampv != cfg[ii][P_ONES])
            xcur = 48'(mulr(192'(xcur), 192'(clampv), F_S));

          if (ci == 0) begin xl = xcur; chan = 1'b1; end
          else         begin xr = xcur; chan = 1'b0; st = S_CPRE; end
        end

        // ---------------------------------- ButterComp: positive polarity
        S_CPRE: begin
          ii   = int'(`L4_INST);
          si   = `L4_STAGE;
          ci   = chan ? 1 : 0;
          xcur = ci ? xr : xl;
          if (si == 0 && cfg[ii][P_FLAGS][0] == 1'b0)
            xcur = 48'(mulr(192'(xcur), 192'(cfg[ii][P_IGAIN]), F_K));

          ipos = 64'(mulr(192'(xcur), 192'(cfg[ii][P_FPOLD]), F_A + F_K - F_T)
                     + mulr(192'(avgr[ii][si][ci]), 192'(cfg[ii][P_FPNEW]),
                            F_A + F_K - F_T)
                     + 192'(cfg[ii][P_ONET]));
          avgr[ii][si][ci] = xcur;
          if (ipos < cfg[ii][P_PFLOOR]) ipos = 64'(cfg[ii][P_PFLOOR]);
          opos = 64'(rndsh(192'(ipos), 1));
          if (opos > cfg[ii][P_ONET]) opos = 64'(cfg[ii][P_ONET]);
          sq = 64'(rndsh(192'(ipos) * 192'(ipos), F_T));
          dr = 64'(rndsh(192'(cfg[ii][P_REM0 + si])
                         * (192'(sq) + 192'(cfg[ii][P_ONET])), F_T));
          if (dr > cfg[ii][P_ONET]) dr = 64'(cfg[ii][P_ONET]);
          dd = 64'(cfg[ii][P_ONET]) - dr;
          // quirk Q2: stage C's RIGHT channel updates the LEFT pos target
`ifdef NC_FIX_Q2
          // DEFECT: "fixes" pinned quirk Q2 -- stage C's right channel
          // updates its OWN positive target instead of the left one.
          tgt = ci;
`else
          tgt = (si == 2 && ci == 1) ? 0 : ci;
`endif
          t_pos[ii][si][tgt] = 64'(rndsh(192'(t_pos[ii][si][tgt]) * 192'(dd),
                                         F_T)
                                   + rndsh(192'(sq) * 192'(dr), F_T));
          divop = t_pos[ii][si][ci];
          if (ci == 0) xl = xcur; else xr = xcur;
          st = S_DIVP;
        end

        S_DIVP: begin
          ii = int'(`L4_INST);
          if (divop <= 0) $fatal(1, "target word non-positive (%0d)", divop);
          w0 = 192'(cfg[ii][P_RECIP]);
          invq = 64'((w0 + 192'(divop >>> 1)) / 192'(divop));
          n_div = n_div + 1;
          calc_pos = 96'(rndsh(192'(invq) * 192'(invq), CALC_SHIFT));
          st = S_NPRE;
        end

        // ---------------------------------- ButterComp: negative polarity
        S_NPRE: begin
          ii   = int'(`L4_INST);
          si   = `L4_STAGE;
          ci   = chan ? 1 : 0;
          xcur = ci ? xr : xl;
          ipos = 64'(mulr(192'(-xcur), 192'(cfg[ii][P_FPOLD]),
                          F_A + F_K - F_T)
                     + mulr(192'(nvgr[ii][si][ci]), 192'(cfg[ii][P_FPNEW]),
                            F_A + F_K - F_T)
                     + 192'(cfg[ii][P_ONET]));
          nvgr[ii][si][ci] = -xcur;
          if (ipos < cfg[ii][P_PFLOOR]) ipos = 64'(cfg[ii][P_PFLOOR]);
          oneg = 64'(rndsh(192'(ipos), 1));
          if (oneg > cfg[ii][P_ONET]) oneg = 64'(cfg[ii][P_ONET]);
          sq = 64'(rndsh(192'(ipos) * 192'(ipos), F_T));
          dr = 64'(rndsh(192'(cfg[ii][P_REM0 + si])
                         * (192'(sq) + 192'(cfg[ii][P_ONET])), F_T));
          if (dr > cfg[ii][P_ONET]) dr = 64'(cfg[ii][P_ONET]);
          dd = 64'(cfg[ii][P_ONET]) - dr;
          t_neg[ii][si][ci] = 64'(rndsh(192'(t_neg[ii][si][ci]) * 192'(dd),
                                        F_T)
                                  + rndsh(192'(sq) * 192'(dr), F_T));
          divop = t_neg[ii][si][ci];
          st = S_DIVN;
        end

        S_DIVN: begin
          ii = int'(`L4_INST);
          if (divop <= 0) $fatal(1, "target word non-positive (%0d)", divop);
          w0 = 192'(cfg[ii][P_RECIP]);
          invq = 64'((w0 + 192'(divop >>> 1)) / 192'(divop));
          n_div = n_div + 1;
          calc_neg = 96'(rndsh(192'(invq) * 192'(invq), CALC_SHIFT));
          st = S_CFIN;
        end

        // ------------------------ bank update, stereo link, gain, clip
        S_CFIN: begin
          ii    = int'(`L4_INST);
          si    = `L4_STAGE;
          ci    = chan ? 1 : 0;
          other = 1 - ci;
          xcur  = ci ? xr : xl;

          if (xcur > 0) begin
            if (fp_flip[ii]) begin
              c_apos[ii][si][ci] =
                96'(rndsh(192'(c_apos[ii][si][ci])
                          * 192'(cfg[ii][P_DIV0 + si]), F_T)
                    + rndsh(192'(calc_pos) * 192'(cfg[ii][P_REM0 + si]), F_T));
              if (c_apos[ii][si][other] > c_apos[ii][si][ci])
                c_apos[ii][si][other] =
                  96'(rndsh(192'(c_apos[ii][si][other])
                            + 192'(c_apos[ii][si][ci]), 1));
            end else begin
              c_bpos[ii][si][ci] =
                96'(rndsh(192'(c_bpos[ii][si][ci])
                          * 192'(cfg[ii][P_DIV0 + si]), F_T)
                    + rndsh(192'(calc_pos) * 192'(cfg[ii][P_REM0 + si]), F_T));
              if (c_bpos[ii][si][other] > c_bpos[ii][si][ci])
                c_bpos[ii][si][other] =
                  96'(rndsh(192'(c_bpos[ii][si][other])
                            + 192'(c_bpos[ii][si][ci]), 1));
            end
          end else begin
            if (fp_flip[ii]) begin
              c_aneg[ii][si][ci] =
                96'(rndsh(192'(c_aneg[ii][si][ci])
                          * 192'(cfg[ii][P_DIV0 + si]), F_T)
                    + rndsh(192'(calc_neg) * 192'(cfg[ii][P_REM0 + si]), F_T));
              if (c_aneg[ii][si][other] > c_aneg[ii][si][ci])
                c_aneg[ii][si][other] =
                  96'(rndsh(192'(c_aneg[ii][si][other])
                            + 192'(c_aneg[ii][si][ci]), 1));
            end else begin
              c_bneg[ii][si][ci] =
                96'(rndsh(192'(c_bneg[ii][si][ci])
                          * 192'(cfg[ii][P_DIV0 + si]), F_T)
                    + rndsh(192'(calc_neg) * 192'(cfg[ii][P_REM0 + si]), F_T));
              if (c_bneg[ii][si][other] > c_bneg[ii][si][ci])
                c_bneg[ii][si][other] =
                  96'(rndsh(192'(c_bneg[ii][si][other])
                            + 192'(c_bneg[ii][si][ci]), 1));
            end
          end

          if (fp_flip[ii])
            tot = 96'(mulr(192'(c_apos[ii][si][ci]), 192'(opos),
                           F_C + F_T - F_C)
                      + mulr(192'(c_aneg[ii][si][ci]), 192'(oneg),
                             F_C + F_T - F_C));
          else
            tot = 96'(mulr(192'(c_bpos[ii][si][ci]), 192'(opos),
                           F_C + F_T - F_C)
                      + mulr(192'(c_bneg[ii][si][ci]), 192'(oneg),
                             F_C + F_T - F_C));

          if (tot != cfg[ii][P_ONEC])
            xcur = 48'(mulr(192'(xcur), 192'(tot), F_C));
          if (192'(xcur) > 192'(cfg[ii][P_CLIP])) begin
            xcur = 48'(cfg[ii][P_CLIP]); n_clip = n_clip + 1;
          end else if (192'(xcur) < -192'(cfg[ii][P_CLIP])) begin
            xcur = -48'(cfg[ii][P_CLIP]); n_clip = n_clip + 1;
          end
          if (ci == 0) xl = xcur; else xr = xcur;

          bnk_o = 96'(mulr(192'(xcur), 192'(cfg[ii][P_INVCOG]), F_K));
          if (si == 0)      oa[ci] = 48'(bnk_o);
          else if (si == 1) ob[ci] = 48'(bnk_o);
          else              oc[ci] = 48'(bnk_o);

          if (ci == 0) begin chan = 1'b1; st = S_CPRE; end
          else         begin chan = 1'b0; st = S_NEXT; end
        end

        S_NEXT: begin
          if (int'(stage) < sel) begin
            stage = stage + 2'd1;
            st    = S_SAG;
          end else begin
            st = S_MIX;
          end
        end

        // -------------------------- ratio crossfade, makeup gain, wet/dry
        S_MIX: begin
          ii = int'(`L4_INST);
          for (ci = 0; ci < NCH; ci++) begin
            if (sel == 0) begin
              w0 = 192'(ci ? dryr : dryl); w1 = 192'(oa[ci]);
            end else if (sel == 1) begin
              w0 = 192'(oa[ci]);           w1 = 192'(ob[ci]);
            end else begin
              w0 = 192'(ob[ci]);           w1 = 192'(oc[ci]);
            end
            w2 = mulr(w0, 192'(cfg[ii][P_IRATIO]), F_K)
                 + mulr(w1, 192'(cfg[ii][P_RATIO]), F_K);
            if (cfg[ii][P_FLAGS][1] == 1'b0)
              w2 = mulr(w2, 192'(cfg[ii][P_OGAIN]), F_K);
            if (cfg[ii][P_FLAGS][2] == 1'b0)
              w2 = mulr(w2, 192'(cfg[ii][P_WET]), F_K)
                   + mulr(192'(ci ? dryr : dryl), 192'(cfg[ii][P_DRY]), F_K);
            if (w2 > 192'(cfg[ii][P_A48MAX]))       w2 = 192'(cfg[ii][P_A48MAX]);
            else if (w2 < -192'(cfg[ii][P_A48MAX]) - 192'sd1)
              w2 = -192'(cfg[ii][P_A48MAX]) - 192'sd1;
            if (ci == 0) out_l[k] = 48'(w2); else out_r[k] = 48'(w2);
          end
          fp_flip[ii] = ~fp_flip[ii];
          if (k == BLOCK - 1) st = S_DONE;
          else begin k = k + 6'd1; st = S_BEGIN; end
        end

        S_DONE: begin
          block_done = 1'b1;
          st         = S_IDLE;
        end

        default: st = S_IDLE;
      endcase
    end
  end

endmodule
