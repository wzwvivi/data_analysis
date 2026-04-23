# -*- coding: utf-8 -*-
"""
飞管-飞控交互数据解析器（V1.5）

根据《飞管与飞控、自动飞行交互数据协议V1.5-nh20251028》实现。
飞管（FMS1/FMS2）通过 TSN 向飞控（FCC1-3）发送 11 种消息，
消息类型由端口号末两位决定。

TSN 包结构：协议填充(4B) + 功能状态集(4B) + 消息体
消息体全部小端序，无校验。
"""
import struct
from typing import Dict, List, Any, Optional

from .base import BaseParser, ParserRegistry, FieldLayout

TSN_HEADER_LEN = 8

_FMS_ROLE = {0: "无效", 1: "主FMS", 2: "备FMS"}
_FLIGHT_SCENE = {0: "正常", 1: "中断", 2: "复飞", 3: "紧急返航"}
_FLIGHT_PHASE = {
    0: "默认", 1: "上电", 2: "滑出", 3: "起飞-3", 4: "起飞-4",
    5: "起飞-5", 6: "起飞-6", 7: "起飞-7", 8: "爬升-8", 9: "爬升-9",
    10: "爬升-10", 11: "巡航", 12: "下降", 13: "进近-13", 14: "进近-14",
    15: "着陆-15", 16: "着陆-16", 17: "着陆-17", 18: "着陆-18",
    19: "滑入", 20: "下电", 21: "复飞",
}
_AIR_GROUND = {0: "地面", 1: "空中"}
_NAV_MODE = {
    0: "AUTOMATIC", 1: "HYBRID-1", 2: "HYBRID-2",
    3: "HYBRID-3", 4: "MULTISENSE-1", 5: "MULTISENSE-2",
}
_LEG_TYPE = {
    0: "进场滑行", 1: "起飞", 2: "爬升", 3: "航路",
    4: "下降", 5: "初始进近", 6: "着陆", 7: "离场滑行",
}

_MSG_TYPE_MAP = {
    1: "flight_status",
    2: "nav_calc",
    3: "time_calc",
    4: "flight_mission",
    5: "takeoff_runway",
    6: "landing_runway",
    7: "performance",
    8: "normal_leg_overview",
    9: "normal_leg_data",
    10: "emergency_leg_overview",
    11: "emergency_leg_data",
}
_MSG_TYPE_CN = {
    1: "飞行状态", 2: "导航计算", 3: "时间计算", 4: "飞行任务",
    5: "起飞跑道", 6: "降落跑道", 7: "性能计算",
    8: "正常航段总览", 9: "正常航段数据",
    10: "紧急航段总览", 11: "紧急航段数据",
}


def _port_to_msg_type(port: int) -> Optional[int]:
    """从端口号末两位推断消息类型编号 (1-11)，不匹配则返回 None。"""
    suffix = port % 100
    if 1 <= suffix <= 11:
        return suffix
    return None


def _port_to_fms_id(port: int) -> str:
    """推断发送方 FMS 编号。9901-9911/9508-9511/9708-9711 => FMS1, 其余 FMS2。"""
    prefix = port // 100
    if prefix in (99, 95, 97):
        return "FMS1"
    return "FMS2"


def _port_to_target_fcc(port: int, msg_num: int) -> Optional[str]:
    """
    推断目标飞控。

    - MSG01~MSG07: 协议定义为发往 FCC1/FCC2/FCC3（组播多目标）
    - MSG08~MSG11: 端口前缀对应单个 FCC
    """
    if 1 <= msg_num <= 7:
        return "FCC1/FCC2/FCC3"

    prefix = port // 100
    fcc_map = {99: "FCC1", 98: "FCC1", 97: "FCC2", 96: "FCC2", 95: "FCC3", 94: "FCC3"}
    return fcc_map.get(prefix)


_COMMON_COLS = ["timestamp", "source_port", "fms_id", "target_fcc",
                "msg_type", "msg_type_cn", "packet_size"]

_MSG_COLUMNS: Dict[int, List[str]] = {
    1: ["fms_role", "fms_role_cn", "flight_scene", "flight_scene_cn",
        "flight_phase", "flight_phase_cn", "air_ground", "air_ground_cn"],
    2: ["nav_validity_basic", "nav_validity_pos", "nav_validity_alt", "nav_validity_wind",
        "sys_longitude_deg", "sys_latitude_deg", "sys_ground_speed_mps",
        "sys_east_velocity_mps", "sys_north_velocity_mps",
        "sys_altitude_m", "sys_vertical_velocity_mps",
        "sys_heading_deg", "sys_mag_heading_deg",
        "sys_track_angle_deg", "sys_mag_track_angle_deg",
        "sys_flight_path_angle_deg", "sys_drift_angle_deg",
        "sys_wind_dir_deg", "sys_wind_speed_mps",
        "sys_east_wind_mps", "sys_north_wind_mps",
        "nav_mode", "nav_mode_cn", "epu_nm", "sensor_combination"],
    3: ["utc_validity", "utc_year", "utc_month", "utc_day",
        "utc_hour", "utc_minute", "utc_second", "utc_millisecond"],
    4: ["cruise_altitude_m", "outside_temp_c", "mission_version"],
    5: ["runway_validity",
        "rwy_start_lon_deg", "rwy_start_lat_deg", "rwy_start_alt_m",
        "rwy_end_lon_deg", "rwy_end_lat_deg", "rwy_end_alt_m",
        "rwy_length_m", "runway_version"],
    6: ["runway_validity",
        "rwy_start_lon_deg", "rwy_start_lat_deg", "rwy_start_alt_m",
        "rwy_end_lon_deg", "rwy_end_lat_deg", "rwy_end_alt_m",
        "rwy_length_m", "runway_version"],
    7: ["perf_validity", "aircraft_weight_kg", "cg_pct",
        "v1_mps", "vr_mps", "v2_mps", "vref_mps", "perf_version"],
    8: ["leg_total_count", "leg_overview_version"],
    9: ["leg_index", "leg_type", "leg_type_cn", "is_arc",
        "leg_start_lon_deg", "leg_start_lat_deg", "leg_start_alt_m",
        "leg_end_lon_deg", "leg_end_lat_deg", "leg_end_alt_m",
        "leg_center_lon_deg", "leg_center_lat_deg", "leg_center_alt_m",
        "leg_turn_radius_m", "leg_speed_target_mps"],
    10: ["leg_total_count", "leg_overview_version"],
    11: ["leg_index", "leg_type", "leg_type_cn", "is_arc",
         "leg_start_lon_deg", "leg_start_lat_deg", "leg_start_alt_m",
         "leg_end_lon_deg", "leg_end_lat_deg", "leg_end_alt_m",
         "leg_center_lon_deg", "leg_center_lat_deg", "leg_center_alt_m",
         "leg_turn_radius_m", "leg_speed_target_mps"],
}

_ALL_COLUMNS: List[str] = list(dict.fromkeys(
    _COMMON_COLS
    + [c for cols in _MSG_COLUMNS.values() for c in cols]
))


@ParserRegistry.register
class FMSFCCParser(BaseParser):
    parser_key = "fms_fcc_v1.5"
    name = "飞管-飞控交互数据"
    display_name = "飞管-飞控交互数据"
    parser_version = "V1.5"
    protocol_family = "fms_fcc"
    supported_ports: List[int] = []

    OUTPUT_COLUMNS = _ALL_COLUMNS

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not payload or len(payload) <= TSN_HEADER_LEN:
            return None

        msg_num = _port_to_msg_type(port)
        if msg_num is None:
            return None

        cols = _COMMON_COLS + _MSG_COLUMNS.get(msg_num, [])
        data = payload[TSN_HEADER_LEN:]
        out: Dict[str, Any] = {c: None for c in cols}
        out["timestamp"] = timestamp
        out["source_port"] = port
        out["fms_id"] = _port_to_fms_id(port)
        out["target_fcc"] = _port_to_target_fcc(port, msg_num)
        out["msg_type"] = _MSG_TYPE_MAP.get(msg_num, f"unknown_{msg_num}")
        out["msg_type_cn"] = _MSG_TYPE_CN.get(msg_num, f"未知_{msg_num}")
        out["packet_size"] = len(payload)

        try:
            if msg_num == 1:
                self._decode_flight_status(data, out)
            elif msg_num == 2:
                self._decode_nav_calc(data, out)
            elif msg_num == 3:
                self._decode_time_calc(data, out)
            elif msg_num == 4:
                self._decode_flight_mission(data, out)
            elif msg_num in (5, 6):
                self._decode_runway(data, out)
            elif msg_num == 7:
                self._decode_performance(data, out)
            elif msg_num in (8, 10):
                self._decode_leg_overview(data, out)
            elif msg_num in (9, 11):
                self._decode_leg_data(data, out)
        except Exception:
            pass

        return out

    # ------------------------------------------------------------------
    # MSG01 飞行状态 (4B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_flight_status(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 4:
            return
        b = struct.unpack_from('<4B', data)
        out["fms_role"] = b[0]
        out["fms_role_cn"] = _FMS_ROLE.get(b[0], f"未知({b[0]})")
        out["flight_scene"] = b[1]
        out["flight_scene_cn"] = _FLIGHT_SCENE.get(b[1], f"未知({b[1]})")
        out["flight_phase"] = b[2]
        out["flight_phase_cn"] = _FLIGHT_PHASE.get(b[2], f"阶段{b[2]}")
        out["air_ground"] = b[3]
        out["air_ground_cn"] = _AIR_GROUND.get(b[3], f"未知({b[3]})")

    # ------------------------------------------------------------------
    # MSG02 导航计算 (61B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_nav_calc(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 61:
            return
        out["nav_validity_basic"] = data[0]
        out["nav_validity_pos"] = data[1]
        out["nav_validity_alt"] = data[2]
        out["nav_validity_wind"] = data[3]

        out["sys_longitude_deg"] = struct.unpack_from('<i', data, 4)[0] * 1e-07
        out["sys_latitude_deg"] = struct.unpack_from('<i', data, 8)[0] * 1e-07
        out["sys_ground_speed_mps"] = struct.unpack_from('<i', data, 12)[0] * 0.01
        out["sys_east_velocity_mps"] = struct.unpack_from('<i', data, 16)[0] * 0.01
        out["sys_north_velocity_mps"] = struct.unpack_from('<i', data, 20)[0] * 0.01
        out["sys_altitude_m"] = struct.unpack_from('<i', data, 24)[0] * 0.01
        out["sys_vertical_velocity_mps"] = struct.unpack_from('<i', data, 28)[0] * 0.01

        out["sys_heading_deg"] = struct.unpack_from('<H', data, 32)[0] * 0.01
        out["sys_mag_heading_deg"] = struct.unpack_from('<H', data, 34)[0] * 0.01
        out["sys_track_angle_deg"] = struct.unpack_from('<H', data, 36)[0] * 0.01
        out["sys_mag_track_angle_deg"] = struct.unpack_from('<H', data, 38)[0] * 0.01
        out["sys_flight_path_angle_deg"] = struct.unpack_from('<H', data, 40)[0] * 0.01
        out["sys_drift_angle_deg"] = struct.unpack_from('<h', data, 42)[0] * 0.01

        out["sys_wind_dir_deg"] = struct.unpack_from('<H', data, 44)[0] * 0.01
        out["sys_wind_speed_mps"] = struct.unpack_from('<i', data, 46)[0] * 0.01
        out["sys_east_wind_mps"] = struct.unpack_from('<i', data, 50)[0] * 0.01
        out["sys_north_wind_mps"] = struct.unpack_from('<i', data, 54)[0] * 0.01

        nav = data[58]
        out["nav_mode"] = nav
        out["nav_mode_cn"] = _NAV_MODE.get(nav, f"未知({nav})")
        out["epu_nm"] = data[59] * 0.01
        out["sensor_combination"] = f"{data[60]:08b}"

    # ------------------------------------------------------------------
    # MSG03 时间计算 (12B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_time_calc(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 12:
            return
        out["utc_validity"] = data[0]
        out["utc_year"] = struct.unpack_from('<H', data, 1)[0]
        out["utc_month"] = data[3]
        out["utc_day"] = data[4]
        out["utc_hour"] = data[5]
        out["utc_minute"] = data[6]
        out["utc_second"] = data[7]
        out["utc_millisecond"] = struct.unpack_from('<I', data, 8)[0]

    # ------------------------------------------------------------------
    # MSG04 飞行任务 (6B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_flight_mission(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 6:
            return
        out["cruise_altitude_m"] = struct.unpack_from('<I', data, 0)[0] * 0.01
        out["outside_temp_c"] = struct.unpack_from('<b', data, 4)[0]
        out["mission_version"] = data[5]

    # ------------------------------------------------------------------
    # MSG05/06 起飞/降落跑道 (30B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_runway(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 30:
            return
        out["runway_validity"] = data[0] & 0x01
        out["rwy_start_lon_deg"] = struct.unpack_from('<i', data, 1)[0] * 1e-07
        out["rwy_start_lat_deg"] = struct.unpack_from('<i', data, 5)[0] * 1e-07
        out["rwy_start_alt_m"] = struct.unpack_from('<i', data, 9)[0] * 0.01
        out["rwy_end_lon_deg"] = struct.unpack_from('<i', data, 13)[0] * 1e-07
        out["rwy_end_lat_deg"] = struct.unpack_from('<i', data, 17)[0] * 1e-07
        out["rwy_end_alt_m"] = struct.unpack_from('<i', data, 21)[0] * 0.01
        out["rwy_length_m"] = struct.unpack_from('<I', data, 25)[0] * 0.01
        out["runway_version"] = data[29]

    # ------------------------------------------------------------------
    # MSG07 性能计算 (9B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_performance(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 9:
            return
        out["perf_validity"] = data[0]
        out["aircraft_weight_kg"] = struct.unpack_from('<H', data, 1)[0] * 0.01
        out["cg_pct"] = data[3] * 0.01
        out["v1_mps"] = data[4] * 0.01
        out["vr_mps"] = data[5] * 0.01
        out["v2_mps"] = data[6] * 0.01
        out["vref_mps"] = data[7] * 0.01
        out["perf_version"] = data[8]

    # ------------------------------------------------------------------
    # MSG08/10 航段总览 (2B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_leg_overview(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 2:
            return
        out["leg_total_count"] = data[0]
        out["leg_overview_version"] = data[1]

    # ------------------------------------------------------------------
    # MSG09/11 航段数据 (43B)
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_leg_data(data: bytes, out: Dict[str, Any]) -> None:
        if len(data) < 43:
            return
        out["leg_index"] = data[0]
        lt = data[1]
        out["leg_type"] = lt
        out["leg_type_cn"] = _LEG_TYPE.get(lt, f"未知({lt})")
        out["is_arc"] = data[2]
        out["leg_start_lon_deg"] = struct.unpack_from('<i', data, 3)[0] * 1e-07
        out["leg_start_lat_deg"] = struct.unpack_from('<i', data, 7)[0] * 1e-07
        out["leg_start_alt_m"] = struct.unpack_from('<i', data, 11)[0] * 0.01
        out["leg_end_lon_deg"] = struct.unpack_from('<i', data, 15)[0] * 1e-07
        out["leg_end_lat_deg"] = struct.unpack_from('<i', data, 19)[0] * 1e-07
        out["leg_end_alt_m"] = struct.unpack_from('<i', data, 23)[0] * 0.01
        out["leg_center_lon_deg"] = struct.unpack_from('<i', data, 27)[0] * 1e-07
        out["leg_center_lat_deg"] = struct.unpack_from('<i', data, 31)[0] * 1e-07
        out["leg_center_alt_m"] = struct.unpack_from('<i', data, 35)[0] * 0.01
        out["leg_turn_radius_m"] = struct.unpack_from('<h', data, 39)[0]
        out["leg_speed_target_mps"] = struct.unpack_from('<H', data, 41)[0] * 0.1

    def get_output_columns(self, port: int) -> List[str]:
        msg_num = _port_to_msg_type(port)
        if msg_num is not None:
            return _COMMON_COLS + _MSG_COLUMNS.get(msg_num, [])
        return self.OUTPUT_COLUMNS
