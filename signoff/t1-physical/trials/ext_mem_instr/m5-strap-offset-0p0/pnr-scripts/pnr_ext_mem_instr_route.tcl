read_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_cts.odb
read_liberty /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_1v80.lib
set_cmd_units -time ns -capacitance pF
create_clock -name clk -period 20.0 [get_ports clk]
set_routing_layers -signal Metal2-Metal5
global_route -verbose
file delete -force /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_pass_0_drc.rpt /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_pass_0_maze.log
utl::push_metrics_stage "route_pass:0__{}"
detailed_route -output_drc /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_pass_0_drc.rpt -output_maze /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_pass_0_maze.log -or_seed 1
utl::pop_metrics_stage
repair_antennas gf180mcu_fd_sc_mcu9t5v0__antenna
file delete -force /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_drc.rpt /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_maze.log
detailed_route -output_drc /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_drc.rpt -output_maze /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route_maze.log -or_seed 1
puts "===KLT_ANTENNA_VIOLATIONS_BEGIN==="
check_antennas
puts "===KLT_ANTENNA_VIOLATIONS_END==="
puts "===KLT_ROUTING_COMPLETENESS_BEGIN==="
set klt_block [ord::get_db_block]
set klt_total 0
set klt_unrouted 0
foreach klt_net [$klt_block getNets] {
  if {[$klt_net getSigType] ne "SIGNAL"} continue
  set klt_pins [expr {[llength [$klt_net getITerms]] + [llength [$klt_net getBTerms]]}]
  if {$klt_pins < 2} continue
  incr klt_total
  if {[$klt_net getWire] eq "NULL"} { incr klt_unrouted }
}
puts "KLT_ROUTING_COMPLETENESS signal_nets=$klt_total unrouted=$klt_unrouted"
puts "===KLT_ROUTING_COMPLETENESS_END==="
filler_placement {gf180mcu_fd_sc_mcu9t5v0__fill_64 gf180mcu_fd_sc_mcu9t5v0__fill_32 gf180mcu_fd_sc_mcu9t5v0__fill_16 gf180mcu_fd_sc_mcu9t5v0__fill_8 gf180mcu_fd_sc_mcu9t5v0__fill_4 gf180mcu_fd_sc_mcu9t5v0__fill_2 gf180mcu_fd_sc_mcu9t5v0__fill_1}
global_connect
estimate_parasitics -global_routing
report_worst_slack_metric -setup
report_tns_metric -setup
report_worst_slack_metric -hold
report_design_area_metrics
report_fmax_metric
report_power_metric
report_clock_skew_metric -setup
puts "===KLT_SETUP_VIOLATIONS_BEGIN==="
report_check_types -max_delay -recovery -clock_gating_setup -violators -format end
puts "===KLT_SETUP_VIOLATIONS_END==="
puts "===KLT_HOLD_VIOLATIONS_BEGIN==="
report_check_types -min_delay -removal -clock_gating_hold -violators -format end
puts "===KLT_HOLD_VIOLATIONS_END==="
write_def /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr.def
write_verilog /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr.v -remove_cells {gf180mcu_fd_sc_mcu9t5v0__filltie gf180mcu_fd_sc_mcu9t5v0__endcap gf180mcu_fd_sc_mcu9t5v0__fill_64 gf180mcu_fd_sc_mcu9t5v0__fill_32 gf180mcu_fd_sc_mcu9t5v0__fill_16 gf180mcu_fd_sc_mcu9t5v0__fill_8 gf180mcu_fd_sc_mcu9t5v0__fill_4 gf180mcu_fd_sc_mcu9t5v0__fill_2 gf180mcu_fd_sc_mcu9t5v0__fill_1}
write_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route.odb
