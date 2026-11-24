read_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route.odb
define_corners tt_025C_3v30
read_liberty -corner tt_025C_3v30 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_3v30.lib
set_cmd_units -time ns -capacitance pF
create_clock -name clk -period 20.0 [get_ports clk]
set_wire_rc -layer Metal2
estimate_parasitics -global_routing
puts "===KLT_MAX_TRANSITION_LIBRARY_VIOLATIONS_BEGIN==="
report_check_types -max_slew -violators
puts "===KLT_MAX_TRANSITION_LIBRARY_VIOLATIONS_END==="
puts "===KLT_MAX_CAPACITANCE_LIBRARY_VIOLATIONS_BEGIN==="
report_check_types -max_capacitance -violators
puts "===KLT_MAX_CAPACITANCE_LIBRARY_VIOLATIONS_END==="
report_worst_slack_metric -setup
report_worst_slack_metric -hold
report_tns_metric -setup
report_tns_metric -hold
puts "===KLT_MAX_TRANSITION_VIOLATIONS_BEGIN==="
report_check_types -max_slew -violators
puts "===KLT_MAX_TRANSITION_VIOLATIONS_END==="
puts "===KLT_MAX_CAPACITANCE_VIOLATIONS_BEGIN==="
report_check_types -max_capacitance -violators
puts "===KLT_MAX_CAPACITANCE_VIOLATIONS_END==="
