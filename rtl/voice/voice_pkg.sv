// SXT-022 RTL voice slice: audio-rate datapath + envelope state machines for
// factory preset `Basses/Attacky.fxp`, implementing the SAME integer schedule
// as the frozen fixed-point model (model/voice/voice_model.py).
//
// Claim scope: this file is iverilog-simulated RTL that must match the model
// EXACTLY (integer equality at every declared checkpoint). It is NOT
// synthesis-closed, NOT timing-closed, and makes no gf180mcu claim.
//
// Structure citations (read, not copied): surge@58914e59
//   src/common/dsp/oscillators/ClassicOscillator.cpp (convolute/process_block)
//   src/common/dsp/QuadFilterChain.cpp ProcessFBQuad fc_serial1
//   libs/sst/sst-filters QuadFilterUnit_Impl.h IIR12CFCquad
//   src/common/dsp/modulators/ADSRModulationSource.h (digital mode)
//   libs/sst/sst-filters HalfRateFilter.h (M=6, steep) process_block_D2
//   sst-basic-blocks OscillatorDriftUnisonCharacter.h CharacterFilter (Warm)
//
// Arithmetic (frozen in model/voice/README.md):
//   Q10.21 words, 32-bit; products exact then rounded round-half-up:
//     qmul(a,b) = (a*b + (1<<20)) >>> 21   (a*b computed at 64-bit)
//   sinc sub-sample position truncates toward zero (>>> with $unsigned).

`timescale 1ns/1ps

package voice_pkg;
  localparam int FQ        = 21;    // Q10.21
  localparam int F_PHASE   = 29;    // Q2.29 envelope phase
  localparam int PMI_F     = 18;    // pitchmult_inv Q13.18
  localparam int BLOCK     = 32;    // samples @ 48 kHz per engine block
  localparam int BLOCK_OS  = 64;    // samples @ 96 kHz per engine block
  localparam int OB_LEN    = 128;   // impulse ring length
  localparam int FIRN      = 12;    // sinc taps
  localparam int FIROFF    = 6;     // FIRoffset
  localparam int NSLOTS    = 8;     // voice slots

  // Q10.21 x Q10.21 -> Q10.21, round-half-up, saturating
  function automatic signed [31:0] qmul(input signed [31:0] a, input signed [31:0] b);
    reg signed [63:0] p;
    reg signed [63:0] r;
    p = a * b;
    r = (p + (64'sd1 << 20)) >>> 21;               // round-half-up
    if (r > 63'sd2147483647)       qmul = 32'sd2147483647;
    else if (r < -63'sd2147483648) qmul = -32'sd2147483648;
    else                           qmul = r[31:0];
  endfunction

  // Saturating add
  function automatic signed [31:0] qadd(input signed [31:0] a, input signed [31:0] b);
    reg signed [33:0] r;
    r = a + b;
    if (r > 34'sd2147483647)       qadd = 32'sd2147483647;
    else if (r < -34'sd2147483648) qadd = -32'sd2147483648;
    else                           qadd = r[31:0];
  endfunction
endpackage
