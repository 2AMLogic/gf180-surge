read_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/m5-strap-offset-0p0/.klt/place-and-route/ext_mem_instr_route.odb
define_corners ff_125C_1v98 ff_125C_3v60 ff_125C_5v50 ff_n40C_1v98 ff_n40C_3v60 ff_n40C_5v50 ss_125C_1v62 ss_125C_3v00 ss_125C_4v50 ss_n40C_1v62 ss_n40C_3v00 ss_n40C_4v50 tt_025C_1v80 tt_025C_3v30 tt_025C_5v00
read_liberty -corner ff_125C_1v98 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ff_125C_1v98.lib
read_liberty -corner ff_125C_3v60 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ff_125C_3v60.lib
read_liberty -corner ff_125C_5v50 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ff_125C_5v50.lib
read_liberty -corner ff_n40C_1v98 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ff_n40C_1v98.lib
read_liberty -corner ff_n40C_3v60 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ff_n40C_3v60.lib
read_liberty -corner ff_n40C_5v50 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ff_n40C_5v50.lib
read_liberty -corner ss_125C_1v62 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ss_125C_1v62.lib
read_liberty -corner ss_125C_3v00 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ss_125C_3v00.lib
read_liberty -corner ss_125C_4v50 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ss_125C_4v50.lib
read_liberty -corner ss_n40C_1v62 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ss_n40C_1v62.lib
read_liberty -corner ss_n40C_3v00 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ss_n40C_3v00.lib
read_liberty -corner ss_n40C_4v50 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__ss_n40C_4v50.lib
read_liberty -corner tt_025C_1v80 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_1v80.lib
read_liberty -corner tt_025C_3v30 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_3v30.lib
read_liberty -corner tt_025C_5v00 /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib
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
