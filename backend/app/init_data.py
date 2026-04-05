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
    '["timestamp","adru_id","adru_id_cn","label_octal","label_name","ssm","ssm_cn",'
    '"label_count","labels_octal","labels_cn","ssm_values",'
    '"abs_alt_voted_ft","qnh_alt_voted_ft","qfe_alt_voted_ft","mach_voted","ias_voted_kn",'
    '"cas_voted_kn","tas_voted_kn","vspeed_voted_ftmin","tat_voted_c","sat_voted_c","aoa_voted_deg","aos_voted_deg",'
    '"left_sp_raw_hpa","right_sp_raw_hpa","total_p_raw_hpa","avg_sp_raw_hpa","avg_sp_corr_hpa",'
    '"abs_alt_src_ft","qnh_alt_src_ft","qfe_alt_src_ft","mach_src","ias_src_kn","cas_src_kn","tas_src_kn",'
    '"vspeed_src_ftmin","tat_src_c","sat_src_c","aoa_src_deg","aos_src_deg",'
    '"pbit_240","cbit_241","cbit_242","cbit_243","sw_version","qnh_report_hpa","qfe_report_hpa","flap_status_report",'
    '"inertial_vrate_report","maint_bit_cmd_report","heat_cmd_report","wow_report",'
    '"flap_takeoff_valid","flap_cruise_valid","flap_landing_valid",'
    '"maint_bit_cmd_active","maint_bit_cmd_cn","heat_cmd_mode","heat_cmd_mode_cn","wow_compressed","wow_compressed_cn"]'
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

    if not adc_exists:
        profiles_to_create.append(
            ParserProfile(
                name="大气数据系统",
                version="V2.2",
                device_model="ADC/ADRU",
                protocol_family="adc",
                parser_key="adc_v2.2",
                is_active=True,
                description="S/ADS-5大气数据系统通讯协议V2.2解析器。解码ARINC 429数据，包括表决后/源数据大气参数（气压高度、空速、马赫数、升降速度、温度、迎角、侧滑角等）、自检状态字、装订气压回报、软件版本。端口由TSN网络配置动态指定。",
                supported_ports="",
                output_fields=ADC_OUTPUT_FIELDS,
            )
        )
        print("[Init] 将创建 大气数据系统 解析器配置")
    else:
        if not adc_exists.protocol_family:
            adc_exists.protocol_family = "adc"
            print("[Init] 已更新 ADC protocol_family = adc")
        if adc_exists.output_fields != ADC_OUTPUT_FIELDS:
            adc_exists.output_fields = ADC_OUTPUT_FIELDS
            print("[Init] 已更新 ADC output_fields 到最新版本")
        print("[Init] 大气数据系统 解析版本已存在，跳过创建")

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
