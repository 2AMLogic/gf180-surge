// SXT-040 RTL Sine oscillator family: audio-rate schedule for the declared
// parameter classes (all 32 shape modes, legacy + modern behavior, unison
// stacking, per-instance state), implementing the SAME integer schedule as
// the frozen fixed-point model (model/oscillators/sine/sine_model.py).
//
// Claim scope: this RTL is simulated with iverilog and must match the frozen
// model EXACTLY (integer equality at every declared checkpoint; enforced by
// tools/compare_sine_rtl_model.py). It is NOT synthesis-closed, NOT
// timing-closed, and makes no gf180mcu FPGA/ASIC claim of any kind. The
// schedule is a sequential operation stream (the landed SXT-022/SXT-033
// harness style); cost accounting is reported separately in
// reports/SXT-040/EVIDENCE.md under the declared 1-MAC cost model.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/dsp/oscillators/SineOscillator.cpp/.h (process_block
//     fmlegacy dispatch, process_block_legacy FM/non-FM branches,
//     process_block_internal omega ramp / feedback lags / playramp,
//     valueFromSinAndCosForMode<0..31>, applyFilter,
//     handleStreamingMismatches shape wave_remap)
//   OscillatorBase.h pitch_to_omega
//   sst-basic-blocks QuadratureOscillators.h SurgeQuadrOsc (legacy branch)
//   sst-basic-blocks FastMath.h fastsin/fastcos/clampToPiRange (modern
//     branch; the FM legacy branch shares the fastsin machine - declared
//     inert under the fixture fm_switch=0 override)
//   sst-basic-blocks dsp/Lag.h SurgeLag (FMdepth/FB)
//   sst-basic-blocks OscillatorDriftUnisonCharacter.h UnisonSetup (linear
//     pan law is mono-inert: (panL+panR)/2 = 1), CharacterFilter
//   sst-filters BiquadFilter coeff_HP/coeff_LP2B TDF2 (applyFilter)
//
// Stimulus (declared control-plane boundary; emitted by
// model/oscillators/sine/run_model.py):
//   init.hex   one-time constants: mode/behavior, unison, lag words,
//              filter + character coefficients, AEG rates, halfband
//   ctrl.hex   per-block control words: header [b, slotmask, master, 0..]
//              + one 7-word record per processed slot (+16 creation words:
//              per-voice omega_u latched on voice creation)
`timescale 1ns/1ps

module tb_sine;

  localparam int FQ       = 21;
  localparam int F_PHASE  = 29;
  localparam int FQ28     = 28;
  localparam int BLOCK    = 32;
  localparam int BLOCK_OS = 64;
  localparam int NSLOTS   = 8;
  localparam int MAXUNI   = 16;
  localparam int REC      = 7;
  localparam int REC_NEW  = REC + 16;

  localparam logic signed [31:0] ONE      = 32'sd2097152;    // 1.0 Q10.21
  localparam logic signed [31:0] PH_ONE   = 32'sd536870912;  // 1.0 Q2.29
  localparam logic signed [31:0] PI_Q28   = 32'sd843314856;
  localparam logic signed [31:0] TWO_PI_Q28 = 32'sd1686629713;
  localparam logic [31:0] S_ATTACK = 0, S_DECAY = 1, S_RELEASE = 3, S_IDLE = 6;

  int unsigned qmul_count = 0;

  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << 20)) >>> 21;
    if      (r > 64'sd2147483647)  qmul = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  function automatic signed [31:0] sat32(input signed [63:0] v);
    if      (v > 64'sd2147483647)  sat32 = 32'sd2147483647;
    else if (v < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = v[31:0];
  endfunction

  function automatic signed [31:0] shl1(input signed [31:0] v); // engine *2
    shl1 = sat32(64'(v) <<< 1);
  endfunction

  function automatic signed [31:0] half_rhu(input signed [31:0] v);
    // engine mul_ps(0.5, x) is exact; the Q word rounds half-up (model _half)
    if (v >= 0) half_rhu = 32'((64'(v) + 64'sd1) >>> 1);
    else        half_rhu = -32'((-64'(v) + 64'sd1) >>> 1);
  endfunction

  function automatic signed [31:0] qdiv_rhu(input signed [31:0] a, input signed [31:0] b);
    // exact division with round-half-up (b > 0); modes 25/27 quadrant divide
    logic signed [63:0] av, bv;
    av = a; bv = b;
    if (av >= 0) qdiv_rhu = 32'((av + (bv >>> 1)) / bv);
    else         qdiv_rhu = -32'((-av + (bv >>> 1)) / bv);
  endfunction

  function automatic signed [31:0] clamp8(input signed [31:0] v); // +-8.0
    if      ($signed(v) >  32'sd16777216) clamp8 =  32'sd16777216;
    else if ($signed(v) < -32'sd16777216) clamp8 = -32'sd16777216;
    else clamp8 = v;
  endfunction

  function automatic signed [31:0] clamp1(input signed [31:0] v);
    if      ($signed(v) >  ONE) clamp1 = ONE;
    else if ($signed(v) < -ONE) clamp1 = -ONE;
    else clamp1 = v;
  endfunction

  // init word map (INIT order in run_model.py):
  //   0 mode  1 legacy  2 n_unison  3 out_attenuation  4 dplaying
  //   5 fb_target  6 lag_lp  7 lag_lpinv  8 do_filter
  //   9..24 omega_u[16] (probe defaults)
  //   25 char_a1  26 char_b0  27 char_b1
  //   28..37 hp b0 b1 b2 a1 a2   38..47 lp b0 b1 b2 a1 a2
  //   48..55 aeg a/d/r rate words, sustain(Q2.29), r_s, inst_att, d_s, d
  //   56..61 halfband B0..B5  62..67 halfband A0..A5  68 total_blocks
  logic [31:0] cfg [0:68];
  logic [31:0] ctrl_mem [0:4200000];

  // --------------------------------------------------------- per-slot state
  // per unison voice (legacy quadrature)
  logic signed [31:0] sq_r [NSLOTS][MAXUNI], sq_i [NSLOTS][MAXUNI];
  logic signed [31:0] sq_dr [NSLOTS][MAXUNI], sq_di [NSLOTS][MAXUNI];
  logic signed [31:0] pramp [NSLOTS][MAXUNI];
  // per unison voice (modern phase machine)
  logic signed [31:0] phase [NSLOTS][MAXUNI];
  logic signed [31:0] lv0 [NSLOTS][MAXUNI], lv1 [NSLOTS][MAXUNI];
  logic signed [31:0] om_prior [NSLOTS][MAXUNI];
  logic signed [31:0] om_step [NSLOTS][MAXUNI], om_curr [NSLOTS][MAXUNI];
  // per-voice constants (latched at creation)
  logic signed [31:0] omega_u [NSLOTS][MAXUNI];
  // shared per-slot state
  logic signed [31:0] fb_v [NSLOTS], fm_v [NSLOTS];
  logic firstblock [NSLOTS], prior_valid [NSLOTS];
  logic signed [31:0] hp_r0 [NSLOTS], hp_r1 [NSLOTS];
  logic signed [31:0] lp_r0 [NSLOTS], lp_r1 [NSLOTS];
  logic signed [31:0] char_py [NSLOTS], char_px [NSLOTS];
  logic char_started [NSLOTS];
  logic signed [31:0] osout [NSLOTS][BLOCK_OS];
  // slice (envelope + gain) state
  logic signed [31:0] aeg_phase [NSLOTS], aeg_out_r [NSLOTS], aeg_scale [NSLOTS];
  logic [31:0]  aeg_state [NSLOTS], aeg_idle [NSLOTS];
  logic signed [31:0] prev_gain [NSLOTS];
  logic [31:0] slot_ckpt [NSLOTS], slot_key [NSLOTS];

  // scene + decimator state
  logic signed [31:0] scene_l [BLOCK_OS];
  logic signed [31:0] hbx1_b [6], hbx2_b [6], hby1_b [6], hby2_b [6];
  logic signed [31:0] hbx1_a [6], hbx2_a [6], hby1_a [6], hby2_a [6];
  logic signed [31:0] sblk [BLOCK_OS];

  // control words for the slot being processed
  // 0 key  1 flags(b0 gate,b1 ckpt,b2 created,b3 released)
  // 2 lvl  3 pfg  4 gain_start  5 d_gain  6 outl
  logic signed [31:0] cw [REC];
  logic signed [31:0] nw [16];

  integer fd;
  integer b, s, u, k, i, w;
  logic signed [31:0] g, acc, t_v, fbv, fba, xv, sval, cval, ramp, lv, dp;
  logic fbneg;

  initial begin
    $readmemh("rtl/init.hex", cfg);
    $readmemh("rtl/ctrl.hex", ctrl_mem);
    fd = $fopen("tb_trace.txt", "w");
    for (i = 0; i < 6; i++) begin
      hbx1_b[i]=0; hbx2_b[i]=0; hby1_b[i]=0; hby2_b[i]=0;
      hbx1_a[i]=0; hbx2_a[i]=0; hby1_a[i]=0; hby2_a[i]=0;
    end
    run();
    $fclose(fd);
    $display("DONE qmuls=%0d blocks=%0d", qmul_count, int'(cfg[68]));
    $finish;
  end

  task automatic run;
    int total_blocks, ci;
    logic [31:0] master_amp, slotmask;
    total_blocks = int'(cfg[68]);
    ci = 0;
    for (b = 0; b < total_blocks; b++) begin
      if (ctrl_mem[ci] !== 32'hxxxxxxxx && int'(ctrl_mem[ci]) != b)
        $fatal(1, "ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      slotmask   = ctrl_mem[ci+1];
      master_amp = ctrl_mem[ci+2];
      ci += 10;
      for (k = 0; k < BLOCK_OS; k++) scene_l[k] = 0;
      for (s = 0; s < NSLOTS; s++) begin
        if (slotmask[s]) begin
          for (i = 0; i < REC; i++) cw[i] = ctrl_mem[ci + i];
          slot_ckpt[s] = cw[1][1];
          slot_key[s]  = cw[0];
          if (cw[1][2]) begin
            for (i = 0; i < 16; i++) nw[i] = ctrl_mem[ci + REC + i];
            for (u = 0; u < MAXUNI; u++) omega_u[s][u] = nw[u];
            init_voice();
            ci += REC_NEW;
          end else begin
            ci += REC;
          end
          process_slot();
        end
      end
      decimate_and_output(master_amp);
    end
  endtask

  // --------------------------------------------------------------- envelope
  task automatic adsr_tick;
    logic signed [31:0] ph, rate_a, rate_d, rate_r, sus, l_lo, l_hi, ov, scl;
    logic [31:0] st, r_s;
    rate_a=cfg[48]; rate_d=cfg[49]; rate_r=cfg[50]; sus=cfg[51];
    r_s=cfg[52];
    st=aeg_state[s]; ph=aeg_phase[s]; ov=aeg_out_r[s]; scl=aeg_scale[s];
    if (st == S_ATTACK) begin
      ph = ph + rate_a;
      if ($signed(ph) >= $signed(PH_ONE)) begin ph = PH_ONE; st = S_DECAY; end
      ov = ph >>> (F_PHASE - FQ);
    end else if (st == S_DECAY) begin
      if (cfg[54] == 0) begin
        l_lo = ph - rate_d; l_hi = ph + rate_d;
      end else begin
        // d_s == 1 (sqrt-domain decay), frozen SXT-026 form
        logic signed [63:0] prod64d;
        logic signed [31:0] sx, two_sx_rate, rr, rate_w;
        real phr;
        rate_w = rate_d;
        phr = $itor(ph) / 536870912.0;
        sx = $rtoi($sqrt(phr) * 536870912.0 + 0.5);
        prod64d = $signed(sx) * $signed(rate_w);
        two_sx_rate = 32'((prod64d + (64'sd1 << 28)) >>> 29) << 1;
        prod64d = $signed(rate_w) * $signed(rate_w);
        rr = 32'((prod64d + (64'sd1 << 28)) >>> 29);
        l_lo = ph - two_sx_rate + rr;
        l_hi = ph + two_sx_rate + rr;
        if (($signed(sus) < 32'sd2097 && $signed(ph) < 32'sd210) ||
            ($signed(sus) == 0 && $signed(32'(cfg[55])) < -32'sd14680064))
          l_lo = 0;
        if ($signed(rate_w) > $signed(PH_ONE) && $signed(l_lo) > $signed(sus))
          l_lo = sus;
      end
      if      ($signed(sus) < $signed(l_lo)) ph = l_lo;
      else if ($signed(sus) > $signed(l_hi)) ph = l_hi;
      else                                   ph = sus;
      ov = ph >>> (F_PHASE - FQ);
    end else if (st == S_RELEASE) begin
      ph = ph - rate_r;
      ov = ph >>> (F_PHASE - FQ);
      for (i = 0; i < int'(r_s); i++) ov = qmul(ov, ph >>> (F_PHASE - FQ));
      ov = qmul(ov, scl);
      if ($signed(ph) < 0) begin st = S_IDLE; ov = 0; end
    end else if (st == S_IDLE) begin
      aeg_idle[s] = aeg_idle[s] + 1;
    end
    if ($signed(ov) < 0) ov = 0;
    if ($signed(ov) > $signed(ONE)) ov = ONE;
    aeg_state[s]=st; aeg_phase[s]=ph; aeg_out_r[s]=ov;
  endtask

  // ------------------------------------------------------------------ voice
  task automatic init_voice;
    begin
      if (cfg[1] != 0) begin
        // legacy: SurgeQuadrOsc ctor (r=0, i=-1) + prepare_unison playingramp
        for (u = 0; u < int'(cfg[2]); u++) begin
          sq_r[s][u]=0; sq_i[s][u]=-ONE; sq_dr[s][u]=0; sq_di[s][u]=0;
          pramp[s][u] = (u == 0) ? ONE : 0;
        end
      end else begin
        // modern: retrigger phase 0; omega ramp anchors on the first block
        for (u = 0; u < int'(cfg[2]); u++) begin
          phase[s][u]=0; lv0[s][u]=0; lv1[s][u]=0; om_prior[s][u]=0;
        end
        prior_valid[s] = 0;
      end
      fb_v[s] = 32'(cfg[5]); fm_v[s] = 0;      // lag first-run snap
      firstblock[s] = 1;
      hp_r0[s]=0; hp_r1[s]=0; lp_r0[s]=0; lp_r1[s]=0;
      char_py[s]=0; char_px[s]=0; char_started[s]=0;
      aeg_phase[s]=0; aeg_out_r[s]=0; aeg_idle[s]=0; aeg_scale[s]=ONE;
      aeg_state[s]=S_ATTACK;
      if (cfg[53] != 0) begin aeg_state[s]=S_DECAY; aeg_out_r[s]=ONE; aeg_phase[s]=PH_ONE; end
      // (the frozen model's constructor does NOT step the envelope)
      prev_gain[s] = 32'(cw[4]);               // constructor gain (block-0 gain_start)
    end
  endtask

  task automatic process_slot;
    begin
      if (cw[1][3]) begin  // note_off: release (carried in the record flags)
        aeg_scale[s] = aeg_out_r[s]; aeg_phase[s] = PH_ONE;
        aeg_state[s] = S_RELEASE;
      end
      adsr_tick();
      osc_block();
      output_stage();
      if (slot_ckpt[s]) dump_slot();
    end
  endtask

  // --------------------------------------------------- shape mode functions
  // valueFromSinAndCosForMode<mode>(s, c) on Q10.21 words (pinned op order;
  // model sine_model.shape_out). w = mode (cfg[0]); operates on sval/cval.
  function automatic signed [31:0] shape_out(input signed [31:0] sv,
                                             input signed [31:0] cv);
    logic signed [31:0] s2x, c2x, s4x, uh, lh, v1, qv, sw, mv, sig, fh, cx;
    logic signed [63:0] prod;
    integer mode, quad;
    mode = int'(cfg[0]);
    case (mode)
      0: shape_out = sv;
      1: begin
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        uh = half_rhu(sat32(64'(ONE) - 64'(c2x)));
        lh = half_rhu(sat32(64'(c2x) - 64'(ONE)));
        shape_out = ($signed(sv) >= 0) ? uh : lh;
      end
      2: shape_out = ($signed(sv) >= 0) ? sv : 0;
      3: begin
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        uh = half_rhu(sat32(64'(ONE) - 64'(c2x)));
        shape_out = ($signed(sv) >= 0) ? uh : 0;
      end
      4: begin
        s2x = shl1(qmul(sv, cv));
        shape_out = ($signed(sv) >= 0) ? s2x : 0;
      end
      5, 7: begin
        s2x = shl1(qmul(sv, cv));
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        uh = half_rhu(sat32(64'(ONE) - 64'(c2x)));
        lh = half_rhu(sat32(64'(c2x) - 64'(ONE)));
        v1 = ($signed(s2x) >= 0) ? uh : lh;
        shape_out = ($signed(sv) >= 0) ? v1 : 0;
        if (mode == 7) shape_out = (shape_out < 0) ? -shape_out : shape_out;
      end
      6: begin
        s2x = shl1(qmul(sv, cv));
        v1 = ($signed(sv) >= 0) ? s2x : 0;
        shape_out = (v1 < 0) ? -v1 : v1;
      end
      8: shape_out = sat32(64'(shl1(($signed(sv) >= 0) ? sv : 0)) - 64'(ONE));
      9: begin
        prod = qmul(sv, cv);
        shape_out = (prod <= 0) ? sv : 0;
      end
      10: begin
        prod = qmul(sv, cv);
        shape_out = (prod >= 0) ? sv : 0;
      end
      11: begin
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        uh = half_rhu(sat32(64'(ONE) - 64'(c2x)));
        qv = ($signed(sv) >= 0) ? uh : 0;
        shape_out = sat32(64'(shl1(qv)) - 64'(ONE));
      end
      12: begin
        s2x = shl1(qmul(sv, cv));
        shape_out = ($signed(cv) >= 0) ? s2x : -s2x;
      end
      13: begin
        s2x = shl1(qmul(sv, cv));
        v1 = ($signed(sv) <= 0) ? -s2x : s2x;
        shape_out = ($signed(s2x) >= 0) ? v1 : 0;
      end
      14: begin
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        v1 = (c2x < 0) ? -c2x : c2x;
        shape_out = ($signed(sv) >= 0) ? v1 : 0;
      end
      15: begin
        sig = ($signed(sv) >= 0) ? sat32(64'(ONE) - 64'(sv))
                                 : sat32(-64'(ONE) - 64'(sv));
        shape_out = ($signed(cv) >= 0) ? sig : 0;
      end
      16: begin
        sig = ($signed(sv) >= 0) ? sat32(64'(ONE) - 64'(sv))
                                 : sat32(64'(cv) - 64'(ONE));
        shape_out = ($signed(cv) >= 0) ? sig : 0;
      end
      17: begin
        sw = ($signed(sv) >= 0) ? ONE : -ONE;
        shape_out = sat32(64'(sw) - 64'(sv));
      end
      18: begin
        s2x = shl1(qmul(sv, cv));
        if ($signed(cv) <= 0) shape_out = cv;
        else shape_out = ($signed(sv) >= 0) ? s2x : -s2x;
      end
      19: begin
        s2x = shl1(qmul(sv, cv));
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        s4x = shl1(qmul(s2x, c2x));
        fh = ($signed(cv) >= 0) ? s2x : sat32(-64'(s4x));
        shape_out = ($signed(sv) >= 0) ? fh : sv;
      end
      20, 21: begin
        prod = qmul(sv, cv);
        mv = ($signed(sv) >= 0) ? ONE : -ONE;
        if (mode == 20) shape_out = (prod >= 0) ? sv : mv;
        else            shape_out = (prod >= 0) ? mv : sv;
      end
      22: shape_out = ($signed(cv) >= 0) ? sv : 0;
      23: shape_out = ($signed(cv) <= 0) ? sv : 0;
      24: shape_out = ($signed(sv) >= 0) ? sat32(64'(ONE) - 64'(sv)) : sv;
      25, 27: begin
        s2x = shl1(qmul(sv, cv));
        quad = 3 * ((sv <= 0) ? 1 : 0) + ((cv <= 0) ? 1 : 0)
             - 2 * (((sv <= 0) ? 1 : 0) * ((cv <= 0) ? 1 : 0)) + 1;
        v1 = qdiv_rhu(s2x, 32'(quad));
        shape_out = (mode == 25) ? (($signed(sv) >= 0) ? v1 : 0) : v1;
      end
      26: shape_out = ((sv <= 0) && (cv <= 0)) ? 0 : sv;
      28: begin
        sw = ($signed(sv) >= 0) ? ONE : -ONE;
        prod = qmul(sv, cv);
        v1 = (prod < 0) ? cv : -cv;
        shape_out = sat32(64'(sw) + 64'(v1));
      end
      29: begin
        fh = ($signed(sv) >= 0) ? ONE : 0;
        cx = 0;
        if ($signed(sv) >= 0) begin
          cx = (($signed(sv) >= 0) && ($signed(cv) <= 0)) ? cv : -cv;
        end
        shape_out = sat32(64'(fh) + 64'(cx));
      end
      30, 31: begin
        s2x = shl1(qmul(sv, cv));
        c2x = sat32(64'(ONE) - 64'(shl1(qmul(sv, sv))));
        sw = ($signed(s2x) >= 0) ? ONE : -ONE;
        prod = qmul(s2x, c2x);
        v1 = (prod < 0) ? c2x : -c2x;
        v1 = sat32(64'(sw) + 64'(v1));
        v1 = ($signed(sv) >= 0) ? v1 : 0;      // mode-30 gate (before abs!)
        shape_out = (mode == 31) ? ((v1 < 0) ? -v1 : v1) : v1;
      end
      default: shape_out = 0;
    endcase
  endfunction

  // -------------------------------------------- fastsin/fastcos (modern path)
  // floor semantics for the rational evaluation (Python //): trunc + fixup
  function automatic signed [335:0] fdiv_floor(input signed [335:0] n,
                                               input signed [335:0] d);
    logic signed [335:0] q;
    q = n / d;
    if ((n < 0) && ((n % d) != 0)) q = q - 1;
    fdiv_floor = q;
  endfunction

  function automatic signed [31:0] sat_wide(input signed [335:0] v);
    if      (v > 335'sd2147483647)  sat_wide = 32'sd2147483647;
    else if (v < -335'sd2147483648) sat_wide = -32'sd2147483648;
    else                            sat_wide = v[31:0];
  endfunction

  function automatic signed [31:0] fastsin_wide(input signed [31:0] x);
    logic signed [63:0] x2l;
    logic signed [335:0] gg, hh, nn, sn2;
    x2l = x * x;
    gg = 336'sd479249 * x2l;
    gg = gg - (336'sd52785432 << 56);
    gg = x2l * gg + (336'sd1640635920 << 112);
    gg = x2l * gg - (336'sd11511339840 << 168);
    nn = -x * gg;
    hh = 336'sd18361 * x2l;
    hh = hh + (336'sd3177720 << 56);
    hh = x2l * hh + (336'sd277920720 << 112);
    hh = x2l * hh + (336'sd11511339840 << 168);
    sn2 = (nn >>> 7) + (hh >>> 1);                // round-half-up num/den
    fastsin_wide = sat_wide(fdiv_floor(sn2, hh));
  endfunction

  function automatic signed [31:0] fastcos_wide(input signed [31:0] x);
    logic signed [63:0] x2l;
    logic signed [335:0] gg, hh, nn, sn2;
    x2l = x * x;
    gg = 336'sd14615 * x2l;
    gg = gg - (336'sd1075032 << 56);
    gg = x2l * gg + (336'sd18471600 << 112);
    gg = x2l * gg - (336'sd39251520 << 168);
    nn = -gg;
    hh = 336'sd127 * x2l;
    hh = hh + (336'sd16632 << 56);
    hh = x2l * hh + (336'sd1154160 << 112);
    hh = x2l * hh + (336'sd39251520 << 168);
    sn2 = (nn << 21) + (hh >>> 1);                // round-half-up num/den
    fastcos_wide = sat_wide(fdiv_floor(sn2, hh));
  endfunction

  function automatic signed [31:0] wrap_pi(input signed [31:0] p);
    // modern phase update: phase -= (phase > M_PI) * 2*pi (single wrap)
    if ($signed(p) > $signed(PI_Q28)) wrap_pi = p - TWO_PI_Q28;
    else wrap_pi = p;
  endfunction

  function automatic signed [31:0] clamp_pi(input signed [31:0] p);
    // sst FastMath clampToPiRange on the Q3.28 word (integer-exact; the
    // (int) cast is floor for every sign - see model vm.clamp_to_pi)
    logic signed [65:0] yy, kk, rr;
    yy = 66'(p) + 66'(PI_Q28);
    kk = yy / 66'(TWO_PI_Q28);
    if ((yy < 0) && ((yy % 66'(TWO_PI_Q28)) != 0)) kk = kk - 1;  // floor
    rr = yy - 66'(TWO_PI_Q28) * kk - 66'(PI_Q28);
    clamp_pi = 32'(rr);
  endfunction

  // SurgeQuadrOsc set_rate: dr/di from real math, then normalize (r, i)
  task automatic sine_set_rate(input integer u, input signed [31:0] omega);
    real w, rd, idd, nval;
    begin
      w = $itor(omega) / 268435456.0;            // 2^28
      sq_dr[s][u] = qint_r($cos(w));
      sq_di[s][u] = qint_r($sin(w));
      rd = $itor(sq_r[s][u]) / 2097152.0;
      idd = $itor(sq_i[s][u]) / 2097152.0;
      nval = 1.0 / $sqrt(rd*rd + idd*idd);
      sq_r[s][u] = qint_r(rd * nval);
      sq_i[s][u] = qint_r(idd * nval);
    end
  endtask

  function automatic signed [31:0] qint_r(input real x);
    if (x >= 0) qint_r = 32'($rtoi(x * 2097152.0 + 0.5));
    else        qint_r = -32'($rtoi(-x * 2097152.0 + 0.5));
  endfunction

  // TDF2 biquad over sblk (which_hp: lowcut/highcut)
  task automatic biquad_process(input logic which_hp);
    logic signed [31:0] b0, b1, b2, a1, a2, r0, r1, xx, op;
    integer base_idx;
    begin
      base_idx = which_hp ? 28 : 38;
      b0 = 32'(cfg[base_idx]); b1 = 32'(cfg[base_idx+1]);
      b2 = 32'(cfg[base_idx+2]); a1 = 32'(cfg[base_idx+3]);
      a2 = 32'(cfg[base_idx+4]);
      r0 = which_hp ? hp_r0[s] : lp_r0[s];
      r1 = which_hp ? hp_r1[s] : lp_r1[s];
      for (k = 0; k < BLOCK_OS; k++) begin
        xx = sblk[k];
        op = sat32(qmul(b0, xx) + r0);
        r0 = sat32(qmul(b1, xx) - qmul(a1, op) + r1);
        r1 = sat32(qmul(b2, xx) - qmul(a2, op));
        sblk[k] = op;
      end
      if (which_hp) begin hp_r0[s] = r0; hp_r1[s] = r1; end
      else          begin lp_r0[s] = r0; lp_r1[s] = r1; end
    end
  endtask

  // CharacterFilter over sblk (with the `starting` warm start)
  task automatic char_filter;
    begin
      if (cfg[8] == 0) return;                   // doFilter false
      if (!char_started[s]) begin
        char_py[s] = sblk[0]; char_px[s] = sblk[0]; char_started[s] = 1;
      end
      for (k = 0; k < BLOCK_OS; k++) begin
        g = sat32(qmul(32'(cfg[25]), char_py[s])
                  + qmul(32'(cfg[26]), sblk[k])
                  + qmul(32'(cfg[27]), char_px[s]));
        char_py[s] = g; char_px[s] = sblk[k];
        sblk[k] = g;
      end
    end
  endtask

  // ------------------------------------------------------- sine osc (1 slot)
  task automatic osc_block;
    logic signed [31:0] lag_lp, lag_lpinv, atten;
    begin
      atten = 32'(cfg[3]);
      dp = 32'(cfg[4]);
      if (cfg[1] != 0) begin
        // ---------------- legacy: set_rate per voice, then the sample loop
        for (u = 0; u < int'(cfg[2]); u++) sine_set_rate(u, omega_u[s][u]);
        for (k = 0; k < BLOCK_OS; k++) begin
          acc = 0;
          for (u = 0; u < int'(cfg[2]); u++) begin
            // SurgeQuadrOsc process(): r' = dr*r - di*i; i' = dr*i + di*r
            g = sat32(qmul(sq_dr[s][u], sq_r[s][u]) - qmul(sq_di[s][u], sq_i[s][u]));
            sq_i[s][u] = sat32(qmul(sq_dr[s][u], sq_i[s][u]) + qmul(sq_di[s][u], sq_r[s][u]));
            sq_r[s][u] = g;
            sval = shape_out(sq_r[s][u], sq_i[s][u]);
            t_v = qmul(qmul(sval, atten), pramp[s][u]);
            acc = sat32(64'(acc) + 64'(t_v));
            if ($signed(pramp[s][u]) < $signed(ONE)) begin
              if ($signed(pramp[s][u]) + $signed(dp) > $signed(ONE))
                pramp[s][u] = ONE;
              else
                pramp[s][u] = pramp[s][u] + dp;
            end
          end
          osout[s][k] = acc;
        end
      end else begin
        // ---------------- modern: omega ramp, feedback lag, phase machine
        if (!prior_valid[s]) begin
          for (u = 0; u < int'(cfg[2]); u++) om_prior[s][u] = omega_u[s][u];
          prior_valid[s] = 1;
        end
        for (u = 0; u < int'(cfg[2]); u++) begin
          // omegaStep = (omega - prior)/64 half-up; omegaCurr = omega - 31.5*step
          if (omega_u[s][u] >= om_prior[s][u])
            om_step[s][u] = 32'((64'(omega_u[s][u] - om_prior[s][u]) + 64'sd32) >>> 6);
          else
            om_step[s][u] = -32'((64'(om_prior[s][u] - omega_u[s][u]) + 64'sd32) >>> 6);
          if (om_step[s][u] >= 0)
            om_curr[s][u] = omega_u[s][u]
                - 32'((64'(om_step[s][u]) * 64'sd63 + 64'sd1) >>> 1);
          else
            om_curr[s][u] = omega_u[s][u]
                + 32'((-64'(om_step[s][u]) * 64'sd63 + 64'sd1) >>> 1);
          om_prior[s][u] = omega_u[s][u];
        end
        lag_lp = 32'(cfg[6]); lag_lpinv = 32'(cfg[7]);
        for (k = 0; k < BLOCK_OS; k++) begin
          fbv = ($signed(fb_v[s]) < 0) ? -fb_v[s] : fb_v[s];
          fbneg = $signed(fb_v[s]) < 0;
          acc = 0;
          for (u = 0; u < int'(cfg[2]); u++) begin
            lv = lv1[s][u];                       // fb_mode 0 (type_1)
            if (fbneg) fba = qmul(qmul(lv, lv), fbv);
            else       fba = qmul(lv, fbv);
            xv = clamp_pi(phase[s][u] + fba);
            sval = fastsin_wide(xv);
            cval = fastcos_wide(xv);
            g = shape_out(sval, cval);
            ramp = (u == 0 || !firstblock[s]) ? ONE : 32'(k * 32768);
            t_v = qmul(qmul(g, ramp), atten);
            acc = sat32(64'(acc) + 64'(t_v));
            lv0[s][u] = lv1[s][u];
            lv1[s][u] = g;
            phase[s][u] = wrap_pi(phase[s][u] + om_curr[s][u]);
            om_curr[s][u] = om_curr[s][u] + om_step[s][u];
          end
          fm_v[s] = sat32(qmul(fm_v[s], lag_lpinv) + qmul(0, lag_lp));
          fb_v[s] = sat32(qmul(fb_v[s], lag_lpinv) + qmul(32'(cfg[5]), lag_lp));
          osout[s][k] = acc;
        end
        firstblock[s] = 0;
      end
      for (k = 0; k < BLOCK_OS; k++) sblk[k] = osout[s][k];
      biquad_process(1'b1);                      // applyFilter: lowcut,
      biquad_process(1'b0);                      // then highcut
      char_filter();                             // CharacterFilter
      for (k = 0; k < BLOCK_OS; k++) osout[s][k] = sblk[k];
    end
  endtask

  // ------------------------------------- output stage (serial-1, filters off)
  // x = (osc * lvl) * pfg ; scene += x * gain_ramp * outl
  task automatic output_stage;
    logic signed [31:0] x, gainv;
    begin
      for (k = 0; k < BLOCK_OS; k++) begin
        x = qmul(qmul(osout[s][k], 32'(cw[2])), 32'(cw[3]));
        gainv = 32'(cw[4]) + ((32'(cw[5]) * (k+1) + 32'sd32) >>> 6);
        scene_l[k] = scene_l[k] + qmul(qmul(x, gainv), 32'(cw[6]));
      end
      prev_gain[s] = 32'(cw[4]) + 32'(cw[5]);
    end
  endtask

  // ------------------------------------------- halfband D2 + master output
  task automatic decimate_and_output(input logic [31:0] master_amp);
    logic signed [31:0] xb, xa, yb, ya;
    logic signed [31:0] chainb [BLOCK_OS];
    logic signed [31:0] chaina [BLOCK_OS];
    logic signed [31:0] bl, mm;
    for (k = 0; k < BLOCK_OS; k++) begin
      xb = scene_l[k]; xa = scene_l[k];   // mono bus: the R lane is identical
      for (i = 0; i < 6; i++) begin
        yb = hbx2_b[i] + qmul(32'(cfg[56+i]), xb - hby2_b[i]);
        hbx2_b[i] = hbx1_b[i]; hbx1_b[i] = xb;
        hby2_b[i] = hby1_b[i]; hby1_b[i] = yb;
        xb = yb;
        ya = hbx2_a[i] + qmul(32'(cfg[62+i]), xa - hby2_a[i]);
        hbx2_a[i] = hbx1_a[i]; hbx1_a[i] = xa;
        hby2_a[i] = hby1_a[i]; hby1_a[i] = ya;
        xa = ya;
      end
      chainb[k] = xb; chaina[k] = xa;
    end
    for (k = 0; k < BLOCK; k++) begin
      bl = clamp8((chaina[2*k] + chainb[2*k+1] + 32'sd1) >>> 1);
      mm = clamp8(qmul(bl, 32'(master_amp)));   // L == R on the mono bus
      mm = clamp1(mm);
      $fwrite(fd, "M %0d %0d\n", b, mm);
    end
  endtask

  // checkpoint dump (mirrors the model trace "after" fields)
  task automatic dump_slot;
    integer nuni, legacy;
    begin
      nuni = int'(cfg[2]); legacy = int'(cfg[1]);
      $fwrite(fd, "T %0d %0d %0d %0d %0d %0d %0d %0d", b, s, slot_key[s],
              legacy, nuni, aeg_state[s], aeg_phase[s], aeg_out_r[s]);
      if (legacy != 0) begin
        for (u = 0; u < MAXUNI; u++) begin
          if (u < nuni)
            $fwrite(fd, " %0d %0d %0d %0d %0d", sq_r[s][u], sq_i[s][u],
                    sq_dr[s][u], sq_di[s][u], pramp[s][u]);
          else
            $fwrite(fd, " 0 0 0 0 0");
        end
        $fwrite(fd, "\n");
      end else begin
        for (u = 0; u < MAXUNI; u++) begin
          if (u < nuni)
            $fwrite(fd, " %0d %0d %0d %0d", phase[s][u], lv0[s][u],
                    lv1[s][u], om_prior[s][u]);
          else
            $fwrite(fd, " 0 0 0 0");
        end
        $fwrite(fd, " %0d\n", prior_valid[s] ? 1 : 0);
      end
      $fwrite(fd, "S %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
              b, s, fb_v[s], fm_v[s], firstblock[s] ? 1 : 0,
              hp_r0[s], hp_r1[s], lp_r0[s], lp_r1[s],
              char_py[s], char_px[s]);
      $fwrite(fd, "G %0d %0d %0d\n", b, s, prev_gain[s]);
      $fwrite(fd, "O %0d %0d", b, s);
      for (k = 0; k < BLOCK_OS; k++) $fwrite(fd, " %0d", osout[s][k]);
      $fwrite(fd, "\n");
    end
  endtask

endmodule
