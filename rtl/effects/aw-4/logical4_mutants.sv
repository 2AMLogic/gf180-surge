// SXT-028k live RTL negative controls for the Airwindows "Logical" (id 4)
// leaf.
//
// This file does NOT re-implement the core. It includes the real
// `logical4_core.sv` with exactly one fault-injection macro selected, so a
// control can never drift away from the RTL it is a control for (the failure
// mode a hand-copied mutant file has). Compiling this file WITHOUT selecting
// a defect is refused.
//
//   iverilog -g2012 -DNC_SHARED_STATE ...
//       Both instances read and write instance 0's state record — "shared
//       instead of per-instance state" (the tb_fx_shared_line.sv defect).
//       Must FAIL the dual-instance checkpoint/output equality.
//
//   iverilog -g2012 -DNC_SWAP_STAGES ...
//       The A -> B -> C stage cascade is evaluated in the WRONG order
//       (same-class slot permutation; tools/ablate_fx.py permute pattern).
//       Must FAIL the order-sensitive equality. Note it is a NO-OP when
//       ratioselector == 0 (one active stage): the comparator therefore
//       runs it on a multi-stage case and records the single-stage case as
//       the control's own blind spot rather than hiding it.
//
//   iverilog -g2012 -DNC_TAIL_KILL ...
//       The plausible "nothing to do on silence" optimisation: an all-zero
//       input block is emitted as silence with the whole state record
//       frozen, which DROPS the gain-recovery tail. Must FAIL the tail case
//       while remaining UNDETECTED on a non-silent baseline case — which is
//       precisely what makes the declared tail span load-bearing rather
//       than decorative.
//
//   iverilog -g2012 -DNC_FIX_Q1 ...
//       "Fixes" pinned quirk Q1 (the +499 sag mirror against a 500-sample
//       gcount period) to a constant 2-sample tap. Must FAIL — a model that
//       tidies the reference is not the reference. Blind spot: a run
//       shorter than one gcount period never reaches gcount 498/499, so the
//       comparator runs it on a >= 500-sample case.
//
//   iverilog -g2012 -DNC_FIX_Q2 ...
//       "Fixes" pinned quirk Q2 (stage C's right channel updating the LEFT
//       positive target). Must FAIL on a ratioselector-2 case. Blind spot:
//       stage C must be active, so a sel<2 case cannot detect it.
//
// Original to this repository (Apache-2.0).
`timescale 1ns/1ps

`ifndef NC_SHARED_STATE
`ifndef NC_SWAP_STAGES
`ifndef NC_TAIL_KILL
`ifndef NC_FIX_Q1
`ifndef NC_FIX_Q2
module logical4_mutant_misuse;
  initial begin
    $display("REFUSED: logical4_mutants.sv compiled with no NC_* defect "
             "selected. A mutant build that is identical to the clean core "
             "is not a negative control.");
    $fatal(1, "no negative-control defect selected");
  end
endmodule
`endif
`endif
`endif
`endif
`endif

`include "logical4_core.sv"
