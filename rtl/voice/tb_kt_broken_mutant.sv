// SXT-042 RTL keytrack control-path slice: the per-voice ms_keytrack word
// ((state.pitch - keytrack_root)/12, Q10.21) and the md-ordered voice-route
// pass that consumes it (velocity + keytrack -> Filter 1 Cutoff / Resonance /
// FEG Mod Amount / VCA Gain; unit-2 destinations inert), implementing the
// SAME integer schedule as the frozen fixed-point model
// (model/voice/voice_model.py `VoiceV2._apply_voice_routes`, driven by
// model/voice/run_kt_model.py).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared block-boundary checkpoint; enforced by
// tools/compare_kt_rtl_model.py). NOT synthesis-closed, NOT timing-closed;
// no gf180mcu / FPGA claim of any kind.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/ModulationSource.h        modsources enum, ms_keytrack = 2
//   src/common/dsp/SurgeVoice.cpp        voice ctor (state.pitch, the
//       keytrack modsource value), applyModulationToLocalcopy
//       (localcopy[dst] += depth * source, md-array order), and the
//       modsource refresh at the END of the control pass (the declared
//       1-control-pass lag; pitch is constant per voice in this class, so
//       the refreshed word equals the ctor word -- the RTL therefore
//       derives the word once per block from the streamed key, which is the
//       same quantity, and the model asserts the equality)
//
// Integer-exact keytrack word.  The model quantizes (p-root)/12 to Q10.21
// round-half-up:  kt = floor((p-root)/12 * 2^21 + 1/2).  With n = p-root an
// integer that is exactly
//        kt = floor( (n*2^20 + 3) / 6 )        [floor, i.e. toward -inf]
// because (n*2^21)/12 = n*2^20/6 has fractional part 0, 1/3 or 2/3 and can
// never land on a rounding tie.  Verilog's `/` truncates toward zero, so the
// negative branch is written out explicitly.
//
// Stimulus (declared control-plane boundary; emitted by run_kt_model.py):
//   rtl/kt_init.hex    [total_blocks, keytrack_root, scene_octave,
//                       cutoff_q, reso_q, envmod_q, vca_q, n_routes]
//   rtl/kt_routes.hex  (src_code, dest_code, depth_q21) x n_routes, md order
//                      src_code  0 = velocity, 1 = keytrack
//                      dest_code 0 = fu1 cutoff, 1 = fu1 reso,
//                                2 = fu1 feg-mod, 3 = vca gain,
//                                4..6 = unit-2 (inert)
//   rtl/kt_ctrl.hex    per block: [b] + per slot [active, key, fvel_q21]
`timescale 1ns/1ps

module tb_kt;

  localparam int FQ        = 21;
  localparam int NSLOTS    = 8;
  localparam int STRIDE    = 1 + 3 * NSLOTS;
  localparam int MAX_WORDS = 2000000;      // fail-closed capacity (F-48c)
  localparam int MAX_ROUTES = 64;

  int unsigned qmul_count = 0;

  function automatic signed [31:0] sat32(input signed [63:0] r);
    if      (r >  64'sd2147483647) sat32 =  32'sd2147483647;
    else if (r < -64'sd2147483648) sat32 = -32'sd2147483648;
    else                           sat32 = r[31:0];
  endfunction

  // qmul(a, b) = sat((a*b + 2^(FQ-1)) >>> FQ)  (round-half-up, saturating)
  function automatic signed [31:0] qmul_q(input signed [31:0] a,
                                          input signed [31:0] b);
    logic signed [63:0] p;
    qmul_count++;
    p = a * b;
    qmul_q = sat32((p + (64'sd1 << (FQ-1))) >>> FQ);
  endfunction

  // kt = floor((n*2^20 + 3)/6), floor toward -inf
  function automatic signed [31:0] kt_word_of(input signed [31:0] n);
    logic signed [63:0] num;
    num = (64'sd1048576 * n) + 64'sd0;
    if (num >= 0) kt_word_of = sat32(num / 64'sd6);
    else          kt_word_of = sat32(-(((-num) + 64'sd5) / 64'sd6));
  endfunction

  // ------------------------------------------------------------------ state
  logic [31:0] kt_init  [0:7];
  logic [31:0] kt_route [0:3*MAX_ROUTES-1];
  logic [31:0] ctrl_mem [0:MAX_WORDS-1];

  integer fd;
  integer b, s, k, n_routes, total_blocks, ci;
  logic signed [31:0] root, oct, base_cut, base_reso, base_emod, base_vca;
  logic signed [31:0] key, fvel, kt, val, depth, cut, reso, emod, vca;
  logic signed [63:0] kt_cut_sum, kt_reso_sum, kt_emod_sum;
  logic signed [31:0] term;
  integer src, dest;

  initial begin
    $readmemh("rtl/kt_init.hex",   kt_init);
    $readmemh("rtl/kt_routes.hex", kt_route);
    $readmemh("rtl/kt_ctrl.hex",   ctrl_mem);
    fd = $fopen("tb_kt_trace.txt", "w");
    if (kt_init[7] === 32'hxxxxxxxx) $fatal(1, "kt_init.hex truncated");
    total_blocks = int'(kt_init[0]);
    root      = 32'(kt_init[1]);
    oct       = 32'(kt_init[2]);
    base_cut  = 32'(kt_init[3]);
    base_reso = 32'(kt_init[4]);
    base_emod = 32'(kt_init[5]);
    base_vca  = 32'(kt_init[6]);
    n_routes  = int'(kt_init[7]);
    if (n_routes > MAX_ROUTES)
      $fatal(1, "route table %0d exceeds MAX_ROUTES %0d", n_routes, MAX_ROUTES);
    if (total_blocks * STRIDE > MAX_WORDS)
      $fatal(1, "stimulus %0d words exceeds capacity %0d",
             total_blocks * STRIDE, MAX_WORDS);
    run();
    $fclose(fd);
    $display("DONE kt-qmuls=%0d", qmul_count);
    $finish;
  end

  task automatic run;
    ci = 0;
    for (b = 0; b < total_blocks; b++) begin
      if (ctrl_mem[ci] === 32'hxxxxxxxx)
        $fatal(1, "kt ctrl stream exhausted at block %0d", b);
      if (int'(ctrl_mem[ci]) != b)
        $fatal(1, "kt ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      for (s = 0; s < NSLOTS; s++) begin
        if (ctrl_mem[ci+1+3*s] === 32'hxxxxxxxx)
          $fatal(1, "kt ctrl X-read at block %0d slot %0d", b, s);
        if (ctrl_mem[ci+1+3*s] != 0) begin
          key  = 32'(ctrl_mem[ci+2+3*s]);
          fvel = 32'(ctrl_mem[ci+3+3*s]);
          // voice ctor: state.pitch = key + 12*scene_octave
          kt = kt_word_of(key + 12*oct - root);
          // applyModulationToLocalcopy, md-array order
          cut = base_cut; reso = base_reso; emod = base_emod; vca = base_vca;
          kt_cut_sum = 0; kt_reso_sum = 0; kt_emod_sum = 0;
          for (k = 0; k < n_routes; k++) begin
            src   = int'(kt_route[3*k]);
            dest  = int'(kt_route[3*k+1]);
            depth = 32'(kt_route[3*k+2]);
            val   = (src == 0) ? fvel : kt;
            term  = qmul_q(depth, val);
            case (dest)
              0: begin cut  = sat32(64'(cut)  + 64'(term));
                       if (src == 1) kt_cut_sum  = kt_cut_sum  + 64'(term);
                 end
              1: begin reso = sat32(64'(reso) + 64'(term));
                       if (src == 1) kt_reso_sum = kt_reso_sum + 64'(term);
                 end
              2: begin emod = sat32(64'(emod) + 64'(term));
                       if (src == 1) kt_emod_sum = kt_emod_sum + 64'(term);
                 end
              3: vca = sat32(64'(vca) + 64'(term));
              4, 5, 6: ;                       // unit 2 Off: inert
              default: $fatal(1, "route dest code %0d outside declared class",
                              dest);
            endcase
          end
          $fwrite(fd, "V %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
                  b, s, kt, kt_cut_sum, kt_reso_sum, kt_emod_sum,
                  cut, reso, emod, vca);
        end
      end
      ci += STRIDE;
    end
  endtask

endmodule
