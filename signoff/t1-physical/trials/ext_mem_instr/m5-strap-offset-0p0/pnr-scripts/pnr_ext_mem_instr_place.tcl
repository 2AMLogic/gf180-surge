read_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_floorplan.odb
read_liberty /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_1v80.lib
set_cmd_units -time ns -capacitance pF
create_clock -name clk -period 20.0 [get_ports clk]
place_pins -hor_layers Metal3 -ver_layers Metal2
set_wire_rc -layer Metal2
global_placement -density 0.6 -routability_driven -timing_driven -random_seed 1
estimate_parasitics -placement
repair_design
repair_timing
detailed_placement
report_worst_slack_metric -setup
report_tns_metric -setup
report_worst_slack_metric -hold
report_design_area_metrics
report_fmax_metric
report_power_metric
puts "===KLT_SETUP_VIOLATIONS_BEGIN==="
report_check_types -max_delay -recovery -clock_gating_setup -violators -format end
puts "===KLT_SETUP_VIOLATIONS_END==="
puts "===KLT_HOLD_VIOLATIONS_BEGIN==="
report_check_types -min_delay -removal -clock_gating_hold -violators -format end
puts "===KLT_HOLD_VIOLATIONS_END==="
write_def /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr.place.def
write_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_place.odb
