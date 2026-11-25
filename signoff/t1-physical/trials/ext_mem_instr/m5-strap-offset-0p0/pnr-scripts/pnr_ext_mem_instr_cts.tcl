read_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_place.odb
read_liberty /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_1v80.lib
set_cmd_units -time ns -capacitance pF
create_clock -name clk -period 20.0 [get_ports clk]
set_wire_rc -layer Metal2
estimate_parasitics -placement
set _klt_cts_seq_sinks [llength [all_registers -clock [get_clocks {clk}]]]
if {$_klt_cts_seq_sinks > 0} {
clock_tree_synthesis -root_buf gf180mcu_fd_sc_mcu9t5v0__buf_4 -buf_list gf180mcu_fd_sc_mcu9t5v0__buf_4 -sink_clustering_enable -obstruction_aware
estimate_parasitics -placement
repair_timing -hold
} else {
puts "klt place-and-route: clock clk has no sequential (registered) fanout -- skipping clock_tree_synthesis (see issue #1506)"
}
detailed_placement
write_def /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr.cts.def
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
write_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_cts.odb
