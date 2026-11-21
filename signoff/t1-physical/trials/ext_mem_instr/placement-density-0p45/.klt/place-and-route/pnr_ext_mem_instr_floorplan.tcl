read_liberty /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lib/gf180mcu_fd_sc_mcu9t5v0__tt_025C_1v80.lib
read_lef /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/techlef/gf180mcu_fd_sc_mcu9t5v0__nom.tlef
read_lef /home/ubuntu/.ciel/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu9t5v0/lef/gf180mcu_fd_sc_mcu9t5v0.lef
read_verilog /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-item1/ext_mem_instr/ext_mem_instr_synth.v
link_design ext_mem_instr
set_cmd_units -time ns -capacitance pF
create_clock -name clk -period 20.0 [get_ports clk]
initialize_floorplan -die_area {0 0 1100 1100} -core_area {10 10 1090 1090} -site GF018hv5v_green_sc9
make_tracks
tapcell -distance 30 -tapcell_master gf180mcu_fd_sc_mcu9t5v0__filltie -endcap_master gf180mcu_fd_sc_mcu9t5v0__endcap
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDD$} -power
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDDPE$}
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDDCE$}
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDDP$}
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDDC$}
add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VNW$}
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VSS$} -ground
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VSSE$}
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VSSC$}
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VPW$}
global_connect
set_voltage_domain -name {CORE} -power {VDD} -ground {VSS}
define_pdn_grid -name {grid} -voltage_domains {CORE} -pins {Metal5}
add_pdn_stripe -grid {grid} -layer {Metal1} -width {0.9} -pitch {5.04} -offset {0.0} -followpins
add_pdn_stripe -grid {grid} -layer {Metal4} -width {4.48} -spacing {0.56} -pitch {44.8} -offset {22.4}
add_pdn_stripe -grid {grid} -layer {Metal5} -width {4.48} -pitch {89.6} -offset {44.8}
add_pdn_connect -grid {grid} -layers {Metal1 Metal4} -max_columns {5} -ongrid {Metal2 Metal3 Metal4}
add_pdn_connect -grid {grid} -layers {Metal4 Metal5}
pdngen
report_worst_slack_metric -setup
report_tns_metric -setup
report_worst_slack_metric -hold
report_design_area_metrics
write_db /home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-804/signoff/t1-physical/trials/ext_mem_instr/placement-density-0p45/.klt/place-and-route/ext_mem_instr_floorplan.odb
