# -*- coding: utf-8 -*-
"""初始化数据 - 创建内置的设备协议解析器配置"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .models import ParserProfile, User
from .config import (
    INIT_ADMIN_USERNAME,
    INIT_ADMIN_PASSWORD,
    INIT_USER_USERNAME,
    INIT_USER_PASSWORD,
)
from .services.auth_password import hash_password

ADC_OUTPUT_FIELDS = (
    '["timestamp","adru_id","adru_id_cn",'
    '"label_102.voted_qfe_alt","label_102.sdi","label_102.ssm","label_102.ssm_enum","label_102.parity",'
    '"label_103.voted_qnh_alt","label_103.sdi","label_103.ssm","label_103.ssm_enum","label_103.parity",'
    '"label_137.flap_status","label_137.flap_status_enum","label_137.sdi","label_137.ssm","label_137.ssm_enum","label_137.parity",'
    '"label_176.src_left_sp","label_176.sdi","label_176.ssm","label_176.ssm_enum","label_176.parity",'
    '"label_177.src_right_sp","label_177.sdi","label_177.ssm","label_177.ssm_enum","label_177.parity",'
    '"label_203.voted_abs_alt","label_203.sdi","label_203.ssm","label_203.ssm_enum","label_203.parity",'
    '"label_205.voted_mach","label_205.sdi","label_205.ssm","label_205.ssm_enum","label_205.parity",'
    '"label_206.voted_ias","label_206.sdi","label_206.ssm","label_206.ssm_enum","label_206.parity",'
    '"label_207.voted_cas","label_207.sdi","label_207.ssm","label_207.ssm_enum","label_207.parity",'
    '"label_210.voted_tas","label_210.sdi","label_210.ssm","label_210.ssm_enum","label_210.parity",'
    '"label_211.voted_tat","label_211.sdi","label_211.ssm","label_211.ssm_enum","label_211.parity",'
    '"label_212.voted_vspeed","label_212.sdi","label_212.ssm","label_212.ssm_enum","label_212.parity",'
    '"label_213.voted_sat","label_213.sdi","label_213.ssm","label_213.ssm_enum","label_213.parity",'
    '"label_221.voted_aoa","label_221.sdi","label_221.ssm","label_221.ssm_enum","label_221.parity",'
    '"label_226.voted_aos","label_226.sdi","label_226.ssm","label_226.ssm_enum","label_226.parity",'
    '"label_233.qnh_report","label_233.qnh_report_enum","label_233.sdi","label_233.ssm","label_233.ssm_enum","label_233.parity",'
    '"label_234.qfe_report","label_234.qfe_report_enum","label_234.sdi","label_234.ssm","label_234.ssm_enum","label_234.parity",'
    '"label_235.wow","label_235.wow_enum","label_235.sdi","label_235.ssm","label_235.ssm_enum","label_235.parity",'
    '"label_236.maint_bit","label_236.maint_bit_enum","label_236.sdi","label_236.ssm","label_236.ssm_enum","label_236.parity",'
    '"label_237.heat_cmd","label_237.heat_cmd_enum","label_237.sdi","label_237.ssm","label_237.ssm_enum","label_237.parity",'
    '"label_240.pbit","label_240.pbit_enum","label_240.sdi","label_240.ssm","label_240.ssm_enum","label_240.parity",'
    '"label_241.cbit1","label_241.cbit1_enum","label_241.sdi","label_241.ssm","label_241.ssm_enum","label_241.parity",'
    '"label_242.cbit2","label_242.cbit2_enum","label_242.sdi","label_242.ssm","label_242.ssm_enum","label_242.parity",'
    '"label_243.cbit3","label_243.cbit3_enum","label_243.sdi","label_243.ssm","label_243.ssm_enum","label_243.parity",'
    '"label_244.src_total_p","label_244.sdi","label_244.ssm","label_244.ssm_enum","label_244.parity",'
    '"label_245.src_avg_sp","label_245.sdi","label_245.ssm","label_245.ssm_enum","label_245.parity",'
    '"label_246.src_avg_sp_corr","label_246.sdi","label_246.ssm","label_246.ssm_enum","label_246.parity",'
    '"label_303.src_abs_alt","label_303.sdi","label_303.ssm","label_303.ssm_enum","label_303.parity",'
    '"label_304.src_qnh_alt","label_304.sdi","label_304.ssm","label_304.ssm_enum","label_304.parity",'
    '"label_305.src_mach","label_305.sdi","label_305.ssm","label_305.ssm_enum","label_305.parity",'
    '"label_306.src_ias","label_306.sdi","label_306.ssm","label_306.ssm_enum","label_306.parity",'
    '"label_307.src_cas","label_307.sdi","label_307.ssm","label_307.ssm_enum","label_307.parity",'
    '"label_310.src_tas","label_310.sdi","label_310.ssm","label_310.ssm_enum","label_310.parity",'
    '"label_311.src_tat","label_311.sdi","label_311.ssm","label_311.ssm_enum","label_311.parity",'
    '"label_312.src_vspeed","label_312.sdi","label_312.ssm","label_312.ssm_enum","label_312.parity",'
    '"label_313.src_sat","label_313.sdi","label_313.ssm","label_313.ssm_enum","label_313.parity",'
    '"label_314.src_qfe_alt","label_314.sdi","label_314.ssm","label_314.ssm_enum","label_314.parity",'
    '"label_321.src_aoa","label_321.sdi","label_321.ssm","label_321.ssm_enum","label_321.parity",'
    '"label_326.src_aos","label_326.sdi","label_326.ssm","label_326.ssm_enum","label_326.parity",'
    '"label_350.sw_ver","label_350.sw_ver_enum","label_350.sdi","label_350.ssm","label_350.ssm_enum","label_350.parity",'
    '"label_364.inertial_vrate","label_364.sdi","label_364.ssm","label_364.ssm_enum","label_364.parity"]'
)

RA_OUTPUT_FIELDS = (
    '["timestamp","ra_id","ra_id_cn",'
    '"label_164.alt_bnr","label_164.inhibit_selftest","label_164.inhibit_selftest_enum","label_164.sdi","label_164.ssm","label_164.ssm_enum","label_164.parity",'
    '"label_165.alt_bcd","label_165.alt_bcd_sign","label_165.alt_bcd_sign_enum","label_165.sdi","label_165.ssm","label_165.ssm_enum","label_165.parity",'
    '"label_270.discrete","label_270.discrete_enum","label_270.inhibit_selftest","label_270.inhibit_selftest_enum","label_270.aid20","label_270.aid20_enum","label_270.aid40","label_270.aid40_enum","label_270.aid57","label_270.aid57_enum","label_270.aid_check","label_270.aid_check_enum","label_270.alt_valid","label_270.alt_valid_enum","label_270.selftest","label_270.selftest_enum","label_270.sdi","label_270.ssm","label_270.ssm_enum","label_270.parity",'
    '"label_350.bit_status","label_350.bit_status_enum","label_350.ra_status","label_350.ra_status_enum","label_350.source_signal","label_350.source_signal_enum","label_350.aid_detect","label_350.aid_detect_enum","label_350.fpga_monitor","label_350.fpga_monitor_enum","label_350.volt_5v","label_350.volt_5v_enum","label_350.volt_15v","label_350.volt_15v_enum","label_350.volt_28v","label_350.volt_28v_enum","label_350.tx_channel","label_350.tx_channel_enum","label_350.rx_channel_a","label_350.rx_channel_a_enum","label_350.rx_channel_b","label_350.rx_channel_b_enum","label_350.tx429_ch1","label_350.tx429_ch1_enum","label_350.tx429_ch2","label_350.tx429_ch2_enum","label_350.rx_antenna","label_350.rx_antenna_enum","label_350.tx_antenna","label_350.tx_antenna_enum","label_350.clock1","label_350.clock1_enum","label_350.clock2","label_350.clock2_enum","label_350.sdi","label_350.ssm","label_350.ssm_enum","label_350.parity"]'
)

BRAKE_OUTPUT_FIELDS = (
    '["timestamp","unit_id","unit_id_cn",'
    '"label_002.left_avg_wheel_speed","label_002.sdi","label_002.ssm","label_002.ssm_enum","label_002.parity",'
    '"label_003.right_avg_wheel_speed","label_003.sdi","label_003.ssm","label_003.ssm_enum","label_003.parity",'
    '"label_004.left_inside_wheel_speed","label_004.sdi","label_004.ssm","label_004.ssm_enum","label_004.parity",'
    '"label_005.left_outside_wheel_speed","label_005.sdi","label_005.ssm","label_005.ssm_enum","label_005.parity",'
    '"label_006.right_inside_wheel_speed","label_006.sdi","label_006.ssm","label_006.ssm_enum","label_006.parity",'
    '"label_007.right_outside_wheel_speed","label_007.sdi","label_007.ssm","label_007.ssm_enum","label_007.parity",'
    '"label_051.auto_brk_fail","label_051.auto_brk_lo","label_051.auto_brk_med","label_051.auto_brk_hi","label_051.auto_brk_rto","label_051.brk_plt_ped_fail","label_051.brk_coplt_ped_fail","label_051.brk_nml_no_dispatch","label_051.tire_pr_fail","label_051.left_inside_tire_pr_advy","label_051.left_outside_tire_pr_advy","label_051.right_inside_tire_pr_advy","label_051.right_outside_tire_pr_advy","label_051.ctr_status","label_051.sdi","label_051.ssm","label_051.ssm_enum","label_051.parity",'
    '"label_060.left_inside_tire_pressure","label_060.sdi","label_060.ssm","label_060.ssm_enum","label_060.parity",'
    '"label_061.right_inside_tire_pressure","label_061.sdi","label_061.ssm","label_061.ssm_enum","label_061.parity",'
    '"label_062.left_outside_tire_pressure","label_062.sdi","label_062.ssm","label_062.ssm_enum","label_062.parity",'
    '"label_063.right_outside_tire_pressure","label_063.sdi","label_063.ssm","label_063.ssm_enum","label_063.parity",'
    '"label_070.left_inside_brake_force","label_070.sdi","label_070.ssm","label_070.ssm_enum","label_070.parity",'
    '"label_071.right_inside_brake_force","label_071.sdi","label_071.ssm","label_071.ssm_enum","label_071.parity",'
    '"label_072.left_outside_brake_force","label_072.sdi","label_072.ssm","label_072.ssm_enum","label_072.parity",'
    '"label_073.right_outside_brake_force","label_073.sdi","label_073.ssm","label_073.ssm_enum","label_073.parity",'
    '"label_114.left_inside_brake_temp","label_114.sdi","label_114.ssm","label_114.ssm_enum","label_114.parity",'
    '"label_115.right_inside_brake_temp","label_115.sdi","label_115.ssm","label_115.ssm_enum","label_115.parity",'
    '"label_116.left_outside_brake_temp","label_116.sdi","label_116.ssm","label_116.ssm_enum","label_116.parity",'
    '"label_117.right_outside_brake_temp","label_117.sdi","label_117.ssm","label_117.ssm_enum","label_117.parity",'
    '"label_170.left_main_pedal_stroke","label_170.sdi","label_170.ssm","label_170.ssm_enum","label_170.parity",'
    '"label_171.right_main_pedal_stroke","label_171.sdi","label_171.ssm","label_171.ssm_enum","label_171.parity",'
    '"label_172.left_copilot_pedal_stroke","label_172.sdi","label_172.ssm","label_172.ssm_enum","label_172.parity",'
    '"label_173.right_copilot_pedal_stroke","label_173.sdi","label_173.ssm","label_173.ssm_enum","label_173.parity",'
    '"label_174.left_brake_feedback","label_174.sdi","label_174.ssm","label_174.ssm_enum","label_174.parity",'
    '"label_175.right_brake_feedback","label_175.sdi","label_175.ssm","label_175.ssm_enum","label_175.parity",'
    '"label_176.autoflight_left_brake_cmd","label_176.sdi","label_176.ssm","label_176.ssm_enum","label_176.parity",'
    '"label_177.autoflight_right_brake_cmd","label_177.sdi","label_177.ssm","label_177.ssm_enum","label_177.parity",'
    '"label_351.park_brk_fail","label_351.park_brk_on","label_351.park_brk_apply","label_351.brk_nml_fail","label_351.antiskid_off","label_351.brk_emer_fail","label_351.brk_total_loss","label_351.brk_degrd","label_351.brk_lh_fail","label_351.brk_rh_fail","label_351.antiskid_fail","label_351.left_inside_temp_overheat","label_351.left_outside_temp_overheat","label_351.right_inside_temp_overheat","label_351.right_outside_temp_overheat","label_351.brk_temp_fail","label_351.sdi","label_351.ssm","label_351.ssm_enum","label_351.parity",'
    '"label_352.left_inside_antiskid","label_352.left_outside_antiskid","label_352.right_inside_antiskid","label_352.right_outside_antiskid","label_352.left_inside_antiskid_fault","label_352.left_outside_antiskid_fault","label_352.right_inside_antiskid_fault","label_352.right_outside_antiskid_fault","label_352.auto_brk_on","label_352.brk_nml_on","label_352.brk_alt_on","label_352.brk_emer_on","label_352.sdi","label_352.ssm","label_352.ssm_enum","label_352.parity",'
    '"label_353.fcc_master","label_353.fcc_master_enum","label_353.autoflight_mode_on","label_353.autoflight_park_brake_on","label_353.autoflight_antiskid_on","label_353.autoflight_autobrake_off","label_353.autoflight_autobrake_lo","label_353.autoflight_autobrake_med","label_353.autoflight_autobrake_hi","label_353.autoflight_autobrake_rto","label_353.left_throttle_cmd","label_353.right_throttle_cmd","label_353.sdi","label_353.ssm","label_353.ssm_enum","label_353.parity"]'
)

LGCU_OUTPUT_FIELDS = (
    '["timestamp","unit_id","unit_id_cn",'
    '"label_103.rh_mlg_woffw_1","label_103.rh_mlg_woffw_1_op","label_103.spare_13","label_103.spare_14","label_103.rh_mlg_dnlk_1","label_103.rh_mlg_dnlk_1_op","label_103.sdi","label_103.ssm","label_103.ssm_enum","label_103.parity",'
    '"label_115.lh_mlg_woffw_2","label_115.lh_mlg_woffw_2_op","label_115.spare_13","label_115.spare_14","label_115.lh_mlg_dnlk_2","label_115.lh_mlg_dnlk_2_op","label_115.sdi","label_115.ssm","label_115.ssm_enum","label_115.parity",'
    '"label_271.mlg_rh_uplock","label_271.mlg_lh_uplock","label_271.nlg_lock","label_271.mlg_rh_dnlock","label_271.mlg_lh_dnlock","label_271.nlg_pos","label_271.mlg_rh_uplock_op","label_271.mlg_lh_uplock_op","label_271.nlg_lock_op","label_271.mlg_rh_dnlock_op","label_271.mlg_lh_dnlock_op","label_271.nlg_pos_op","label_271.lgcl_up","label_271.lgcl_down","label_271.lgcl_up_op","label_271.lgcl_down_op","label_271.lgcl_auto","label_271.lgcl_auto_op","label_271.sdi","label_271.ssm","label_271.ssm_enum","label_271.parity",'
    '"label_273.all_gear_dnlk","label_273.all_gear_uplk","label_273.nlg_uplk","label_273.nlg_dnlk","label_273.cmd_retract","label_273.cmd_extend","label_273.auto_retract_cmd","label_273.auto_extend_cmd","label_273.auto_flight_mode","label_273.spare_20","label_273.spare_21","label_273.spare_22","label_273.spare_23","label_273.lgcl_up_dn","label_273.spare_25","label_273.spare_26","label_273.cons_mlg_dnlk","label_273.cons_mlg_uplk","label_273.lgcl_dn_up","label_273.sdi","label_273.ssm","label_273.ssm_enum","label_273.parity",'
    '"label_274.rh_mlg_wow","label_274.lh_mlg_wow","label_274.nlg_wow","label_274.rh_mlg_wow_op","label_274.lh_mlg_wow_op","label_274.nlg_wow_op","label_274.sdi","label_274.ssm","label_274.ssm_enum","label_274.parity",'
    '"label_275.spare_11","label_275.all_gear_wow","label_275.mlg_wow","label_275.gr_woffw","label_275.nlg_wow","label_275.nlg_uplock_sw_off_mon","label_275.rh_mlg_uplock_sw_off_mon","label_275.lh_mlg_uplock_sw_off_mon","label_275.spare_19","label_275.spare_20","label_275.spare_21","label_275.spare_22","label_275.aes_gnd_disc","label_275.aes_28v_en","label_275.all_gear_wow_op","label_275.mlg_wow_op","label_275.sdi","label_275.ssm","label_275.ssm_enum","label_275.parity",'
    '"label_276.lg_sys_nd_fault","label_276.lgcu_internal_fault","label_276.lg_sys_degraded","label_276.wow_sys_fault","label_276.wow_sys_degraded","label_276.alt_ext_lg_down","label_276.alt_ext_lg_fault","label_276.ng_disagree","label_276.lg_disagree","label_276.rg_disagree","label_276.ng_uplocked","label_276.lg_uplocked","label_276.rg_uplocked","label_276.ng_in_transit","label_276.lg_in_transit","label_276.rg_in_transit","label_276.ng_downlocked","label_276.lg_downlocked","label_276.rg_downlocked","label_276.sdi","label_276.ssm","label_276.ssm_enum","label_276.parity",'
    '"label_350.lgcu_nd_fault","label_350.aes_relay3_nd_fault","label_350.aes_relay3_elec_fault","label_350.aes_relay2_nd_fault","label_350.aes_relay1_elec_fault","label_350.aes_relay2_elec_fault","label_350.aes_ng_uplk_elec_fault","label_350.aes_lg_uplk_elec_fault","label_350.aes_rg_uplk_elec_fault","label_350.spare_20","label_350.spare_21","label_350.ehm3_fault","label_350.lgcl_elec_fault","label_350.lgcl_nd_fault","label_350.aev_pos2_elec_fault","label_350.ehm1_fault","label_350.ehm2_fault","label_350.aev_pos1_elec_fault","label_350.aes_relay1_nd_fault","label_350.sdi","label_350.ssm","label_350.ssm_enum","label_350.parity",'
    '"label_351.lh_mlg_woffw_adj","label_351.rh_mlg_woffw_adj","label_351.nlg_woffw_adj","label_351.lh_mlg_dnlock_adj","label_351.rh_mlg_dnlock_adj","label_351.nlg_dnlock_adj","label_351.nlg_uplock_adj","label_351.rh_mlg_uplock_adj","label_351.lh_mlg_uplock_adj","label_351.sdi","label_351.ssm","label_351.ssm_enum","label_351.parity",'
    '"label_354.spare_11","label_354.spare_12","label_354.aes_relay4_nd_fault","label_354.aes_relay4_elec_fault","label_354.aes_relay5_nd_fault","label_354.aes_relay5_elec_fault","label_354.sdi","label_354.ssm","label_354.ssm_enum","label_354.parity",'
    '"label_355.invalid_time_date","label_355.spare_12","label_355.spare_13","label_355.spare_14","label_355.spare_15","label_355.spare_16","label_355.spare_17","label_355.spare_18","label_355.spare_19","label_355.spare_20","label_355.spare_21","label_355.spare_22","label_355.spare_23","label_355.spare_24","label_355.invalid_crosscom_cc","label_355.spare_26","label_355.spare_27","label_355.sdi","label_355.ssm","label_355.ssm_enum","label_355.parity",'
    '"label_360.lh_mlg_woffw_unreas","label_360.rh_mlg_woffw_unreas","label_360.nlg_woffw_unreas","label_360.lh_mlg_dnlock_unreas","label_360.rh_mlg_dnlock_unreas","label_360.nlg_dnlock_unreas","label_360.nlg_uplock_unreas","label_360.rh_mlg_uplock_unreas","label_360.lh_mlg_uplock_unreas","label_360.sdi","label_360.ssm","label_360.ssm_enum","label_360.parity",'
    '"label_361.lh_mlg_woffw_fault","label_361.rh_mlg_woffw_fault","label_361.nlg_woffw_fault","label_361.lh_mlg_dnlock_fault","label_361.rh_mlg_dnlock_fault","label_361.nlg_dnlock_fault","label_361.nlg_uplock_fault","label_361.rh_mlg_uplock_fault","label_361.lh_mlg_uplock_fault","label_361.spare_20","label_361.do_cons_mlg_wow_fault","label_361.do_mlg_lh_wow_fault","label_361.do_mlg_rh_wow_fault","label_361.do_cons_mlg_uplk_fault","label_361.do_cons_mlg_not_dnlk_fault","label_361.dc_bus_low","label_361.spare_27","label_361.ae_valve_mech_fault","label_361.dc_ess_bus_low","label_361.sdi","label_361.ssm","label_361.ssm_enum","label_361.parity",'
    '"label_364.mc_adc_bit_flt","label_364.cc_adc_bit_flt","label_364.dac_bit_flt","label_364.spare_14","label_364.spare_15","label_364.spare_16","label_364.aev_do_pos2_mon_flt","label_364.mc_sw_inop_mon_flt","label_364.cc_sw_inop_mon_flt","label_364.pow_int_eval_flt","label_364.aev_do_pos1_mon_flt","label_364.ext_do_mon_flt","label_364.cmd_asym_mon_flt","label_364.internal_bus_flt","label_364.eeprom_calib_flt","label_364.mc_timing_test_flt","label_364.dr_open_do_mon_flt","label_364.dr_cld_do_mon_flt","label_364.ret_do_mon_flt","label_364.sdi","label_364.ssm","label_364.ssm_enum","label_364.parity",'
    '"label_367.spare_11","label_367.spare_12","label_367.aev2_28v_pos1","label_367.aev2_28v_pos2","label_367.lgcl_aes_28v_en","label_367.spare_16","label_367.rh_mlg_uplock_gnd","label_367.lh_mlg_uplock_gnd","label_367.nlg_uplock_gnd","label_367.spare_20","label_367.spare_21","label_367.spare_22","label_367.spare_23","label_367.rh_mlg_uplock_28v","label_367.lh_mlg_uplock_28v","label_367.nlg_uplock_28v","label_367.sdi","label_367.ssm","label_367.ssm_enum","label_367.parity"]'
)

TURN_OUTPUT_FIELDS = (
    '["timestamp","scu_id","scu_id_cn",'
    '"label_111.nw_angle","label_111.sdi","label_111.ssm","label_111.ssm_enum","label_111.parity",'
    '"label_112.left_handwheel","label_112.sdi","label_112.ssm","label_112.ssm_enum","label_112.parity",'
    '"label_113.right_handwheel","label_113.sdi","label_113.ssm","label_113.ssm_enum","label_113.parity",'
    '"label_114.zero_offset","label_114.sdi","label_114.ssm","label_114.ssm_enum","label_114.parity",'
    '"label_154.control","label_154.control_enum","label_154.zero_cmd","label_154.zero_cmd_enum","label_154.steer_disc","label_154.steer_disc_enum","label_154.park_brk_on","label_154.park_brk_on_enum","label_154.sdi","label_154.ssm","label_154.ssm_enum","label_154.parity",'
    '"label_212.pedal_cmd_echo","label_212.sdi","label_212.ssm","label_212.ssm_enum","label_212.parity",'
    '"label_244.status","label_244.status_enum","label_244.pedal_release","label_244.pedal_release_enum","label_244.work_state","label_244.work_state_enum","label_244.tow_state","label_244.tow_state_enum","label_244.sw_major","label_244.sw_minor","label_244.sw_version","label_244.sw_version_enum","label_244.sdi","label_244.ssm","label_244.ssm_enum","label_244.parity",'
    '"label_314.fault_word","label_314.fault_word_enum","label_314.left_hw_fault","label_314.left_hw_fault_enum","label_314.right_hw_fault","label_314.right_hw_fault_enum","label_314.a429_comm_fault","label_314.a429_comm_fault_enum","label_314.nw_work_fault","label_314.nw_work_fault_enum","label_314.tow_overtravel","label_314.tow_overtravel_enum","label_314.sdi","label_314.ssm","label_314.ssm_enum","label_314.parity"]'
)


async def init_parser_profiles(db: AsyncSession):
    """初始化解析版本配置"""
    
    # 检查JZXPDR113B是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "jzxpdr113b_v20260113")
    )
    jzxpdr_exists = result.scalar_one_or_none()
    
    # 检查IRS是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "irs_v3")
    )
    irs_exists = result.scalar_one_or_none()
    
    # 检查RTK是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "rtk_v1.4")
    )
    rtk_exists = result.scalar_one_or_none()

    # 检查ATG(CPE)是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "atg_cpe_v20260402")
    )
    atg_exists = result.scalar_one_or_none()

    # 检查飞管给惯导转发是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "fms_irs_fwd_v0.4")
    )
    fms_irs_fwd_exists = result.scalar_one_or_none()

    # 检查FCC是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "fcc_v13")
    )
    fcc_exists = result.scalar_one_or_none()

    # 检查RA是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "ra_v1.0")
    )
    ra_exists = result.scalar_one_or_none()

    # 检查转弯系统是否已存在
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "turn_v2")
    )
    turn_exists = result.scalar_one_or_none()
    
    profiles_to_create = []
    
    # JZXPDR113B S模式应答机解析器
    if not jzxpdr_exists:
        profiles_to_create.append(
            ParserProfile(
                name="S模式应答机",
                version="",
                device_model="JZXPDR113B",
                protocol_family="xpdr",
                parser_key="jzxpdr113b_v20260113",
                is_active=True,
                description="根据JZXPDR113B S模式应答机接口控制文件20260113版本，解码ARINC 429标签，输出经纬度、地速、航向等飞行参数。端口由TSN网络配置动态指定。",
                supported_ports="",
                output_fields='["timestamp","beijing_time","latitude","longitude","ground_speed","true_heading","track_angle","vertical_velocity","north_velocity","east_velocity","geometric_height","nav_integrity_raw","ssm_status"]',
            )
        )
        print("[Init] 将创建 S模式应答机 解析器配置")
    else:
        if jzxpdr_exists.name != "S模式应答机":
            jzxpdr_exists.name = "S模式应答机"
            print("[Init] 已更新 JZXPDR113B 名称为 S模式应答机")
        if (jzxpdr_exists.version or "") != "":
            jzxpdr_exists.version = ""
            print("[Init] 已清空 JZXPDR113B 解析器 version 字段（界面仅显示 S模式应答机）")
        if not jzxpdr_exists.protocol_family:
            jzxpdr_exists.protocol_family = "xpdr"
            print("[Init] 已更新 JZXPDR113B protocol_family = xpdr")
        print("[Init] JZXPDR113B 解析版本已存在")
    
    # IRS 惯性基准系统解析器
    _IRS_OUTPUT_FIELDS = (
        '["timestamp","BeijingDateTime",'
        '"device_id","device_name_enum","frame_count",'
        '"heading","pitch","roll",'
        '"east_velocity","north_velocity","vertical_velocity",'
        '"latitude","longitude","altitude",'
        '"angular_rate_x","angular_rate_y","angular_rate_z",'
        '"accel_x","accel_y","accel_z",'
        '"work_mode","work_mode_enum","nav_mode","nav_mode_enum",'
        '"p_align_status","p_align_status_enum","sat_source","sat_source_enum",'
        '"align_status","align_status_enum","align_mode","align_mode_enum",'
        '"align_pos_source","align_pos_source_enum",'
        '"cycle_self_check_status","cycle_self_check_status_enum",'
        '"poweron_self_check_status","poweron_self_check_status_enum",'
        '"x_gyro_status","x_gyro_status_enum","y_gyro_status","y_gyro_status_enum",'
        '"z_gyro_status","z_gyro_status_enum",'
        '"x_accelerometer_status","x_accelerometer_status_enum",'
        '"y_accelerometer_status","y_accelerometer_status_enum",'
        '"z_accelerometer_status","z_accelerometer_status_enum",'
        '"attitude_status","attitude_status_enum",'
        '"heading_status","heading_status_enum",'
        '"position_status","position_status_enum",'
        '"altitude_status","altitude_status_enum",'
        '"velocity_ud_status","velocity_ud_status_enum",'
        '"velocity_ew_status","velocity_ew_status_enum",'
        '"velocity_ns_status","velocity_ns_status_enum",'
        '"x_axis_angular_velocity_status","x_axis_angular_velocity_status_enum",'
        '"y_axis_angular_velocity_status","y_axis_angular_velocity_status_enum",'
        '"z_axis_angular_velocity_status","z_axis_angular_velocity_status_enum",'
        '"x_axis_acceleration_status","x_axis_acceleration_status_enum",'
        '"y_axis_acceleration_status","y_axis_acceleration_status_enum",'
        '"z_axis_acceleration_status","z_axis_acceleration_status_enum",'
        '"rtk1_hpl","rtk2_hpl","rtk1_vpl","rtk2_vpl",'
        '"rtk1_sat_count","rtk2_sat_count",'
        '"rtk1_fix_type","rtk1_fix_type_enum",'
        '"rtk2_fix_type","rtk2_fix_type_enum",'
        '"rtk1_pos_valid","rtk1_pos_valid_enum","rtk1_dop_valid","rtk1_dop_valid_enum",'
        '"rtk2_pos_valid","rtk2_pos_valid_enum","rtk2_dop_valid","rtk2_dop_valid_enum",'
        '"sw_version","hw_version","crc_valid"]'
    )
    if not irs_exists:
        profiles_to_create.append(
            ParserProfile(
                name="IRS惯性基准系统",
                version="V3.0",
                device_model="IRS",
                protocol_family="irs",
                parser_key="irs_v3",
                is_active=True,
                description="惯导通讯协议V3.0解析器。解码姿态角（航向/俯仰/滚动）、速度（东/北/天向）、位置（经纬度/高度）、角速度、加速度等参数。端口由TSN网络配置动态指定，解析时通过包头(0xEB 0x90)自动识别数据格式。",
                supported_ports="",
                output_fields=_IRS_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 IRS惯性基准系统 解析器配置")
    else:
        if not irs_exists.protocol_family:
            irs_exists.protocol_family = "irs"
            print("[Init] 已更新 IRS protocol_family = irs")
        if irs_exists.output_fields != _IRS_OUTPUT_FIELDS:
            irs_exists.output_fields = _IRS_OUTPUT_FIELDS
            print("[Init] 已更新 IRS output_fields（新增枚举/有效性拆分列）")
        print("[Init] IRS惯性基准系统 解析版本已存在")
    
    # RTK 地基接收机解析器
    _RTK_OUTPUT_FIELDS = (
        '["timestamp","BeijingDateTime","frame_count",'
        '"equipment_location_number","equipment_location_number_enum",'
        '"locate_validity_flag","locate_validity_flag_enum",'
        '"satellite_system_flag","satellite_system_flag_enum",'
        '"DOP_validity_flag","DOP_validity_flag_enum",'
        '"GPS_validity_insufNumSats","GPS_validity_insufNumSats_enum",'
        '"GPS_validity_noSbas","GPS_validity_noSbas_enum",'
        '"GPS_validity_paModeEnabled","GPS_validity_paModeEnabled_enum",'
        '"GPS_validity_posPartCorrected","GPS_validity_posPartCorrected_enum",'
        '"GPS_validity_posFullCorrected","GPS_validity_posFullCorrected_enum",'
        '"GPS_validity_posFullMonitored","GPS_validity_posFullMonitored_enum",'
        '"GPS_validity_posPaQualified","GPS_validity_posPaQualified_enum",'
        '"receiver_positioning_status","receiver_positioning_status_enum",'
        '"num_sats_used","num_sats_visible",'
        '"hdop","vdop",'
        '"altitude_ft","altitude_m","ellipsoid_height_ft","ellipsoid_height_m",'
        '"track_angle_deg","ground_speed_kn","ground_speed_m_s",'
        '"latitude_deg","longitude_deg",'
        '"hpl_sbas_nm","hpl_sbas_km","SBAS_flag","SBAS_flag_enum",'
        '"hpl_fd_nm","hpl_fd_km","HPL_FD_flag","HPL_FD_flag_enum",'
        '"vpl_sbas_ft","vpl_sbas_m","vpl_fd_ft","vpl_fd_m",'
        '"vfom_ft","vfom_m","hfom_nm","hfom_km",'
        '"vertical_speed_ftmin","vertical_speed_m_s",'
        '"east_speed_kn","east_speed_m_s","north_speed_kn","north_speed_m_s",'
        '"receiver_FaultFlags","receiver_FaultFlags_enum",'
        '"vul_ft","vul_m","hul_nm","hul_km",'
        '"utc_date","utc_date_year","utc_date_mon","utc_date_day",'
        '"utc_time","utc_time_hour","utc_time_min","utc_time_sec",'
        '"utc_day_second","utc_millisecond",'
        '"sw_version","hw_version"]'
    )
    if not rtk_exists:
        profiles_to_create.append(
            ParserProfile(
                name="RTK地基接收机",
                version="V1.4",
                device_model="RTK",
                protocol_family="rtk",
                parser_key="rtk_v1.4",
                is_active=True,
                description="RTK设备通信协议V1.4解析器。解码GPS/北斗定位数据，包括经纬度、海拔/椭球高度、地速、航迹角、天向/东向/北向速度、HDOP/VDOP、保护级(HPL/VPL)、UTC时间等参数。帧头0x55AA55AA，24组32bit数据，大端序。端口由TSN网络配置动态指定。",
                supported_ports="",
                output_fields=_RTK_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 RTK地基接收机 解析器配置")
    else:
        if not rtk_exists.protocol_family:
            rtk_exists.protocol_family = "rtk"
            print("[Init] 已更新 RTK protocol_family = rtk")
        if rtk_exists.output_fields != _RTK_OUTPUT_FIELDS:
            rtk_exists.output_fields = _RTK_OUTPUT_FIELDS
            print("[Init] 已更新 RTK output_fields（新增枚举/GPS有效性/故障标识拆分列）")
        print("[Init] RTK地基接收机 解析版本已存在")

    # ATG(CPE) 解析器
    if not atg_exists:
        profiles_to_create.append(
            ParserProfile(
                name="ATG设备(CPE)",
                version="V20260402",
                device_model="ATG/CPE",
                protocol_family="atg",
                parser_key="atg_cpe_v20260402",
                is_active=True,
                description="基于《CPE通信协议_标红必须-Label修改》实现，覆盖标红必选Label(132/175/254/255/261/324/325/150/260)。端口由TSN网络配置动态指定。",
                supported_ports="",
                output_fields='["timestamp","true_track_angle_deg","ground_speed_kn","latitude_deg","longitude_deg","altitude_ft","pitch_angle_deg","roll_angle_deg","utc_time","date_text","utc_raw","date_raw","ssm_status"]',
            )
        )
        print("[Init] 将创建 ATG设备(CPE) 解析器配置")
    else:
        if not atg_exists.protocol_family:
            atg_exists.protocol_family = "atg"
            print("[Init] 已更新 ATG(CPE) protocol_family = atg")
        print("[Init] ATG设备(CPE) 解析版本已存在，跳过创建")

    # FMS-FCC 飞管-飞控交互数据解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "fms_fcc_v1.5")
    )
    fms_fcc_exists = result.scalar_one_or_none()

    if not fms_fcc_exists:
        profiles_to_create.append(
            ParserProfile(
                name="飞管-飞控交互数据",
                version="V1.5",
                device_model="FMS/FCC",
                protocol_family="fms",
                parser_key="fms_fcc_v1.5",
                is_active=True,
                description="飞管与飞控、自动飞行交互数据协议V1.5。覆盖飞行状态、导航计算、时间计算、飞行任务、起降跑道、性能计算、航段总览/数据共11种消息类型。端口由TSN网络配置动态指定。",
                supported_ports="",
                output_fields='["timestamp","source_port","fms_id","target_fcc","msg_type","msg_type_cn","fms_role","flight_scene","flight_phase","air_ground","sys_longitude_deg","sys_latitude_deg","sys_ground_speed_mps","sys_altitude_m","sys_heading_deg","sys_track_angle_deg","cruise_altitude_m","outside_temp_c","runway_validity","rwy_start_lon_deg","rwy_start_lat_deg","rwy_length_m","aircraft_weight_kg","leg_total_count","leg_index","leg_type","leg_type_cn","packet_size"]',
            )
        )
        print("[Init] 将创建 飞管-飞控交互数据 解析器配置")
    else:
        if not fms_fcc_exists.protocol_family:
            fms_fcc_exists.protocol_family = "fms"
            print("[Init] 已更新 FMS-FCC protocol_family = fms")
        print("[Init] 飞管-飞控交互数据 解析版本已存在，跳过创建")

    # ADC 大气数据系统解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "adc_v2.2")
    )
    adc_exists = result.scalar_one_or_none()

    _ADC_PORTS = "7001,7002,7003,7022,7023,7024,7025,7026,7027,8003,8004,8005,8006,8007,8008"
    if not adc_exists:
        profiles_to_create.append(
            ParserProfile(
                name="大气数据系统",
                version="V2.2",
                device_model="ADC/ADRU",
                protocol_family="adc",
                parser_key="adc_v2.2",
                is_active=True,
                description="S/ADS-5大气数据系统通讯协议V2.2解析器。解码ARINC 429数据，包括表决后/源数据大气参数（气压高度、空速、马赫数、升降速度、温度、迎角、侧滑角等）、自检状态字、装订气压回报、软件版本。端口7001-7003(全量)/7022-7027(子集)。",
                supported_ports=_ADC_PORTS,
                output_fields=ADC_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 大气数据系统 解析器配置")
    else:
        if not adc_exists.protocol_family:
            adc_exists.protocol_family = "adc"
            print("[Init] 已更新 ADC protocol_family = adc")
        if (adc_exists.supported_ports or "") != _ADC_PORTS:
            adc_exists.supported_ports = _ADC_PORTS
            print("[Init] 已更新 ADC supported_ports")
        if adc_exists.output_fields != ADC_OUTPUT_FIELDS:
            adc_exists.output_fields = ADC_OUTPUT_FIELDS
            print("[Init] 已更新 ADC output_fields 到最新版本")
        print("[Init] 大气数据系统 解析版本已存在，跳过创建")

    # RA 无线电高度表解析器
    if not ra_exists:
        profiles_to_create.append(
            ParserProfile(
                name="无线电高度表",
                version="V1.0",
                device_model="RA",
                protocol_family="ra",
                parser_key="ra_v1.0",
                is_active=True,
                description="无线电高度表429协议V1.0解析器。解码Label 164/165/270/350（BNR高度、BCD高度、离散状态、BIT状态），端口7007-7012（RA1/RA2）。",
                supported_ports="7007,7008,7009,7010,7011,7012",
                output_fields=RA_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 无线电高度表 解析器配置")
    else:
        if not ra_exists.protocol_family:
            ra_exists.protocol_family = "ra"
            print("[Init] 已更新 RA protocol_family = ra")
        if (ra_exists.supported_ports or "") != "7007,7008,7009,7010,7011,7012":
            ra_exists.supported_ports = "7007,7008,7009,7010,7011,7012"
            print("[Init] 已更新 RA supported_ports")
        if ra_exists.output_fields != RA_OUTPUT_FIELDS:
            ra_exists.output_fields = RA_OUTPUT_FIELDS
            print("[Init] 已更新 RA output_fields 到最新版本")
        print("[Init] 无线电高度表 解析版本已存在，跳过创建")

    # 转弯系统解析器
    _TURN_PORTS = "7019,7020"
    if not turn_exists:
        profiles_to_create.append(
            ParserProfile(
                name="前轮转弯系统",
                version="V2.0",
                device_model="LS1/SCU",
                protocol_family="turn",
                parser_key="turn_v2",
                is_active=True,
                description="转弯系统ARINC429通讯协议V2解析器。解码Label 111/112/113/114/154/212/244/314（前轮角度反馈、手轮指令、回绕、控制信号、状态上报、故障状态字），端口7019/7020。",
                supported_ports=_TURN_PORTS,
                output_fields=TURN_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 前轮转弯系统 解析器配置")
    else:
        if not turn_exists.protocol_family:
            turn_exists.protocol_family = "turn"
            print("[Init] 已更新 Turn protocol_family = turn")
        if (turn_exists.supported_ports or "") != _TURN_PORTS:
            turn_exists.supported_ports = _TURN_PORTS
            print("[Init] 已更新 Turn supported_ports")
        if (turn_exists.device_model or "") != "LS1/SCU":
            turn_exists.device_model = "LS1/SCU"
            print("[Init] 已更新 Turn device_model = LS1/SCU")
        if turn_exists.output_fields != TURN_OUTPUT_FIELDS:
            turn_exists.output_fields = TURN_OUTPUT_FIELDS
            print("[Init] 已更新 Turn output_fields 到最新版本")
        print("[Init] 前轮转弯系统 解析版本已存在，跳过创建")

    # 机轮刹车系统解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "brake_v7.3")
    )
    brake_exists = result.scalar_one_or_none()

    _BRAKE_PORTS = ""
    if not brake_exists:
        profiles_to_create.append(
            ParserProfile(
                name="机轮刹车系统",
                version="V7.3",
                device_model="BCMU/ABCU",
                protocol_family="brake",
                parser_key="brake_v7.3",
                is_active=True,
                description="机轮刹车系统EIOCD字节定义V7.3解析器。解码ARINC 429数据，包括CAS1/CAS2离散状态、4轮速/2平均轮速、4胎压、4刹车压力、4刹车温度、4脚蹬行程、刹车量反馈、防滑状态/刹车模式、自动飞行状态回绕等。SDI区分BCMU/ABCU。",
                supported_ports=_BRAKE_PORTS,
                output_fields=BRAKE_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 机轮刹车系统 解析器配置")
    else:
        if not brake_exists.protocol_family:
            brake_exists.protocol_family = "brake"
            print("[Init] 已更新 Brake protocol_family = brake")
        if brake_exists.output_fields != BRAKE_OUTPUT_FIELDS:
            brake_exists.output_fields = BRAKE_OUTPUT_FIELDS
            print("[Init] 已更新 Brake output_fields 到最新版本")
        print("[Init] 机轮刹车系统 解析版本已存在，跳过创建")

    # 电起落架收放控制单元解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "lgcu_v4.0")
    )
    lgcu_exists = result.scalar_one_or_none()

    if not lgcu_exists:
        profiles_to_create.append(
            ParserProfile(
                name="收放控制单元",
                version="V4.0",
                device_model="LGCU",
                protocol_family="lgcu",
                parser_key="lgcu_v4.0",
                is_active=True,
                description="电起落架收放控制单元EOICD V4.0解析器。解码ARINC 429离散数据，包括起落架位置传感器、综合起落架位置、WOFFW、WOW、位置指示状态、维护字1-13等。SDI区分LGCU1/LGCU2。",
                supported_ports="7077,7078,7079,7080",
                output_fields=LGCU_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 收放控制单元 解析器配置")
    else:
        if not lgcu_exists.protocol_family:
            lgcu_exists.protocol_family = "lgcu"
            print("[Init] 已更新 LGCU protocol_family = lgcu")
        if lgcu_exists.output_fields != LGCU_OUTPUT_FIELDS:
            lgcu_exists.output_fields = LGCU_OUTPUT_FIELDS
            print("[Init] 已更新 LGCU output_fields 到最新版本")
        print("[Init] 收放控制单元 解析版本已存在，跳过创建")

    # 800V BMS 动力电池解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "bms_800v_v2.5")
    )
    bms800v_exists = result.scalar_one_or_none()

    if not bms800v_exists:
        profiles_to_create.append(
            ParserProfile(
                name="800V动力电池BMS",
                version="V2.5.1",
                device_model="800V_BMS",
                protocol_family="bms800v",
                parser_key="bms_800v_v2.5",
                is_active=True,
                description="800V动力电池BMS CAN协议V2.5.1解析器。覆盖21个TSN端口（上行19+下行2），解码CAN扩展帧中电池包状态、测量数据、能量/充电信息、单电芯电压/温度极值、故障信息、序列号、监控状态及维护级单电芯数据。通用列名+pack_id区分电池包。",
                supported_ports="",
                output_fields='["timestamp","source_port","can_id_hex","msg_type","pack_id"]',
            )
        )
        print("[Init] 将创建 800V动力电池BMS 解析器配置")
    else:
        if not bms800v_exists.protocol_family:
            bms800v_exists.protocol_family = "bms800v"
            print("[Init] 已更新 BMS800V protocol_family = bms800v")
        print("[Init] 800V动力电池BMS 解析版本已存在，跳过创建")

    # 270V&28V BMS 动力电池解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "bms_270v_v2.5")
    )
    bms270v_exists = result.scalar_one_or_none()
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "mcu_v6.0")
    )
    mcu_exists = result.scalar_one_or_none()

    if not bms270v_exists:
        profiles_to_create.append(
            ParserProfile(
                name="270V&28V动力电池BMS",
                version="V2.5.2",
                device_model="270V_28V_BMS",
                protocol_family="bms270v",
                parser_key="bms_270v_v2.5",
                is_active=True,
                description="270V&28V动力电池BMS CAN协议V2.5.2解析器。覆盖12个TSN端口（上行10+下行2），解码CAN扩展帧中电池包P28(28V)/PE/PL/PR(270V)的状态、测量数据、充电信息、单电芯数据及故障信息。通用列名+pack_id区分电池包。",
                supported_ports="",
                output_fields='["timestamp","source_port","can_id_hex","msg_type","pack_id"]',
            )
        )
        print("[Init] 将创建 270V&28V动力电池BMS 解析器配置")
    else:
        if not bms270v_exists.protocol_family:
            bms270v_exists.protocol_family = "bms270v"
            print("[Init] 已更新 BMS270V protocol_family = bms270v")
        print("[Init] 270V&28V动力电池BMS 解析版本已存在，跳过创建")

    # BPCU/EMPC 配电系统 CAN 解析器
    result = await db.execute(
        select(ParserProfile).where(ParserProfile.parser_key == "bpcu_empc_v1")
    )
    bpcu_exists = result.scalar_one_or_none()

    _BPCU_PORTS = "7050,7051,7052,7053,7054,7055,8035,8042"
    if not bpcu_exists:
        profiles_to_create.append(
            ParserProfile(
                name="BPCU/EMPC配电系统",
                version="A.06",
                device_model="BPCU/EMPC",
                protocol_family="bpcu_empc",
                parser_key="bpcu_empc_v1",
                is_active=True,
                description="电源系统配电盘箱CAN总线ICD A.06解析器。覆盖LBPCU(7050/7051)、RBPCU(7052/7053)、EMPC(7054/7055)及下行灯控(8035/8042)端口，解码电源状态参数、SSPC负载状态、故障信息等。",
                supported_ports=_BPCU_PORTS,
                output_fields='["timestamp","source_port","can_id_hex","msg_name"]',
            )
        )
        print("[Init] 将创建 BPCU/EMPC配电系统 解析器配置")
    else:
        if not bpcu_exists.protocol_family:
            bpcu_exists.protocol_family = "bpcu_empc"
            print("[Init] 已更新 BPCU/EMPC protocol_family = bpcu_empc")
        if (bpcu_exists.supported_ports or "") != _BPCU_PORTS:
            bpcu_exists.supported_ports = _BPCU_PORTS
            print("[Init] 已更新 BPCU/EMPC supported_ports")
        print("[Init] BPCU/EMPC配电系统 解析版本已存在，跳过创建")

    # MCU 电推电驱 CAN 解析器
    if not mcu_exists:
        profiles_to_create.append(
            ParserProfile(
                name="MCU电推电驱",
                version="V6.0",
                device_model="MCU",
                protocol_family="mcu",
                parser_key="mcu_v6.0",
                is_active=True,
                description="电推-电驱CAN通信协议草案V6.0解析器。覆盖MCU相关8个TSN端口（7014/7016/7091-7096），支持指令帧与状态/信息/数据帧解析。",
                supported_ports="7014,7016,7091,7092,7093,7094,7095,7096",
                output_fields='["timestamp","source_port","can_id_hex","msg_name","msg_type"]',
            )
        )
        print("[Init] 将创建 MCU电推电驱 解析器配置")
    else:
        if not mcu_exists.protocol_family:
            mcu_exists.protocol_family = "mcu"
            print("[Init] 已更新 MCU protocol_family = mcu")
        print("[Init] MCU电推电驱 解析版本已存在，跳过创建")

    # 飞管给惯导转发数据解析器
    if not fms_irs_fwd_exists:
        profiles_to_create.append(
            ParserProfile(
                name="飞管给惯导转发数据",
                version="V0.4",
                device_model="FMS_IRS",
                protocol_family="fms_irs_fwd",
                parser_key="fms_irs_fwd_v0.4",
                is_active=True,
                description="飞管给惯导转发数据及初始化数据协议V0.4解析器。FMS1/FMS2向IRS1/2/3发送手动对准指令及大气数据转发，端口8025-8027/8039-8041。",
                supported_ports="8025,8026,8027,8039,8040,8041",
                output_fields='["timestamp","source_port","fms_id","target_irs","align_cmd","align_cmd_cn","manual_longitude_deg","manual_latitude_deg","manual_altitude_m","atm_baro_altitude_ft","atm_indicated_airspeed_kn","atm_true_airspeed_kn","atm_static_pressure_hpa","atm_dynamic_pressure_hpa","validity_raw"]',
            )
        )
        print("[Init] 将创建 飞管给惯导转发数据 解析器配置")
    else:
        print("[Init] 飞管给惯导转发数据 解析版本已存在，跳过创建")

    # FCC 飞控解析器
    if not fcc_exists:
        profiles_to_create.append(
            ParserProfile(
                name="FCC飞控数据",
                version="V13.4",
                device_model="FCC",
                protocol_family="fcc",
                parser_key="fcc_v13",
                is_active=True,
                description="飞控状态帧/飞控通道选择解析器。支持主飞控表决结果与IRS通道选择关键字段提取，端口由TSN网络配置动态指定。",
                supported_ports="",
                output_fields='["timestamp","source_port","source_fcc","frame_type","fcc_vote_raw","fcc_vote_bits","main_fcc","irs_channel_code","irs_channel_name","raw_data","packet_size"]',
            )
        )
        print("[Init] 将创建 FCC飞控数据 解析器配置")
    else:
        if not fcc_exists.protocol_family:
            fcc_exists.protocol_family = "fcc"
            print("[Init] 已更新 FCC protocol_family = fcc")
        print("[Init] FCC飞控数据 解析版本已存在，跳过创建")
    
    if profiles_to_create:
        for profile in profiles_to_create:
            db.add(profile)
    await db.commit()
    if profiles_to_create:
        print(f"[Init] 已创建 {len(profiles_to_create)} 个解析版本配置")
    else:
        print("[Init] 所有解析器配置已存在，无需创建")


async def init_users(db: AsyncSession):
    """为缺失的默认管理员/普通用户建号（密码见环境变量或 config 默认值）。

    旧逻辑仅在「用户表完全为空」时建号；若库里已有其他用户但从未建过 admin，
    会导致无法用 admin 登录。此处按用户名逐个补全，不覆盖已存在账号的密码。
    """
    specs = [
        (INIT_ADMIN_USERNAME, INIT_ADMIN_PASSWORD, "admin"),
        (INIT_USER_USERNAME, INIT_USER_PASSWORD, "user"),
    ]
    created: list[str] = []
    for username, raw_password, role in specs:
        r = await db.execute(select(User).where(User.username == username))
        if r.scalar_one_or_none() is not None:
            continue
        db.add(
            User(
                username=username,
                password_hash=hash_password(raw_password),
                role=role,
            )
        )
        created.append(f"{username}({role})")
    if created:
        await db.commit()
        print(
            f"[Init] 已创建账号: {', '.join(created)}；请尽快修改密码，"
            f"可通过 INIT_ADMIN_PASSWORD / INIT_USER_PASSWORD 指定初始密码"
        )
    else:
        print("[Init] 默认管理员与普通用户已存在，跳过账号创建")


async def init_all_data(db: AsyncSession):
    """初始化所有数据"""
    await init_users(db)
    await init_parser_profiles(db)
