// SXT-035 RTL scene-modwheel control-path slice: the landed FAST_LINE
// smoother (controller CC1 -> target -> per-block FAST_LINE step) plus the
// generalized scene route table (Filter 1 Cutoff 308 / Filter 1 Resonance
// 309 / VCA Gain 298), implementing the SAME integer schedule as the frozen
// fixed-point model extension (model/voice/run_mw_model.py).
//
// Claim scope: simulated with iverilog; must match the frozen model EXACTLY
// (integer equality at every declared block-boundary checkpoint; enforced by
// tools/compare_mw_rtl_model.py). NOT synthesis-closed, NOT timing-closed;
// no gf180mcu FPGA/ASIC claim of any kind.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/ModulationSource.h ControllerModulationSourceVector (NDX=1)
//       set_target (target/startingpoint), processSmoothing FAST_LINE branch
//       (da = (target-startingpoint)/(50*samplerate/44100); snap when
//       |target-value| < |da|; else value += da), bipolar=false
//   src/common/SurgeStorage.h:2063 (smoothingMode default = FAST_LINE)
//   src/common/SurgeSynthesizer.cpp channelController case 1
//       (set_target(value * 1/127) per scene) and the per-block
//       modsource_doprocess[ms_modwheel] gate on process_block()
//   src/common/SurgeVoice.cpp applyModulationToLocalcopy
//       (localcopy[dst] += depth * source per routed destination)
//
// Schedule (declared, identical to the model): per block, controller events
// dispatch first (set_target), the per-voice control passes read the CURRENT
// value (route sums below are computed pre-step), then the smoother steps.
//
// Stimulus (declared control-plane boundary; emitted by run_mw_model.py):
//   rtl/mw_init.hex    [total_blocks, inv_q21]
//   rtl/mw_ctrl.hex    per block: [b, set_flag, cc_value] + 8 slot-run words
//   rtl/mw_routes.hex  n_routes, then (dest_code, depth_q21) per route
//                      (dest_code 0=cutoff, 1=reso, 2=vca)
`timescale 1ns/1ps

module tb_mw;

  localparam int FQ     = 21;
  localparam int NSLOTS = 8;
  localparam int STRIDE = 3 + NSLOTS;

  // ControllerModulationSourceVector::inv = 1/(50 * samplerate/44100),
  // quantized round-half-up to Q10.21 (word emitted by the model runner)
  logic signed [31:0] INV;

  int unsigned qmul_count = 0;

  function automatic signed [31:0] qmul_sh(input signed [31:0] a,
                                           input signed [31:0] b,
                                           input integer sh);
    logic signed [63:0] p, r;
    qmul_count++;
    p = a * b;
    r = (p + (64'sd1 << (sh-1))) >>> sh;
    if      (r > 64'sd2147483647)  qmul_sh = 32'sd2147483647;
    else if (r < -64'sd2147483648) qmul_sh = -32'sd2147483648;
    else                           qmul_sh = r[31:0];
  endfunction

  // quantization-time only (matches model qint): Q10.21 round-half-up
  function automatic signed [31:0] qint_r(input real v);
    integer q;
    q = $rtoi(v * 2097152.0 + 0.5);
    if      (q > 32'sd2147483647)  qint_r = 32'sd2147483647;
    else if (q < -32'sd2147483648) qint_r = -32'sd2147483648;
    else                           qint_r = q;
  endfunction

  // ------------------------------------------------------------------ state
  logic [31:0] mw_init  [0:1];
  logic [31:0] mw_route [0:63];
  logic [31:0] ctrl_mem [0:1200000];

  // ControllerModulationSourceVector state (single scene => one instance)
  logic signed [31:0] target, value, startingpoint;

  integer fd;
  integer b, s, k, n_routes;
  logic signed [31:0] tp_sp, da, bv, cut_sum, reso_sum, vca_sum, depth;
  logic signed [31:0] abs_bv, abs_da;
  logic [31:0] set_flag, dest;
  integer ci;

  initial begin
    $readmemh("rtl/mw_init.hex",   mw_init);
    $readmemh("rtl/mw_routes.hex", mw_route);
    $readmemh("rtl/mw_ctrl.hex",   ctrl_mem);
    fd = $fopen("tb_mw_trace.txt", "w");
    if (mw_init[1] === 32'hxxxxxxxx) $fatal(1, "mw_init.hex truncated");
    INV = 32'(mw_init[1]);
    n_routes = int'(mw_route[0]);
    target = 0; value = 0; startingpoint = 0;
    run();
    $fclose(fd);
    $display("DONE mw-qmuls=%0d", qmul_count);
    $finish;
  end

  task automatic run;
    int total_blocks;
    logic [31:0] ccw;
    total_blocks = int'(mw_init[0]);
    ci = 0;
    for (b = 0; b < total_blocks; b++) begin
      if (ctrl_mem[ci] === 32'hxxxxxxxx)
        $fatal(1, "mw ctrl stream exhausted at block %0d", b);
      if (int'(ctrl_mem[ci]) != b)
        $fatal(1, "mw ctrl desync at block %0d (got %0d)", b, ctrl_mem[ci]);
      set_flag = ctrl_mem[ci+1];
      ccw      = ctrl_mem[ci+2];
      // channelController case 1: set_target(value * 1/127) (Q10.21 quantize)
      if (set_flag[0]) begin
        target       = qint_r(ccw / 127.0);
        startingpoint = value;
      end
      // per-voice control passes read the CURRENT (pre-step) value
      for (s = 0; s < NSLOTS; s++) begin
        if (ctrl_mem[ci+3+s] != 0) begin
          cut_sum = 0; reso_sum = 0; vca_sum = 0;
          for (k = 0; k < n_routes; k++) begin
            dest  = mw_route[1 + k*2];
            depth = 32'(mw_route[2 + k*2]);
            bv = qmul_sh(depth, value, FQ);
            if      (dest == 0) cut_sum = cut_sum + bv;
            else if (dest == 1) reso_sum = reso_sum + bv;
            else                vca_sum = vca_sum + bv;
          end
          $fwrite(fd, "S %0d %0d %0d %0d %0d\n",
                  b, s, cut_sum, reso_sum, vca_sum);
        end
      end
      // processSmoothing(FAST_LINE): da = (target-startingpoint)*inv;
      // |target-value| < |da| -> snap, else value += da
      tp_sp = target - startingpoint;
      da    = qmul_sh(tp_sp, INV, FQ);
      bv    = target - value;
      if ($signed(bv) < 0) abs_bv = -bv; else abs_bv = bv;
      if ($signed(da) < 0) abs_da = -da; else abs_da = da;
      if ($signed(abs_bv) < $signed(abs_da)) value = target;
      else                                   value = value + da;
      $fwrite(fd, "M %0d %0d\n", b, value);
      ci += STRIDE;
    end
  endtask

endmodule
