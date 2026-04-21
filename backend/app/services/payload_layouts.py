# -*- coding: utf-8 -*-
"""
设备协议 payload 内部字节布局常量表（**非 ICD 数据，不入 bundle**）。

设计目的（Phase 3）：
- ICD 提供的「端口号 / 周期 / 消息名 / 源目的设备」已经通过 Bundle 下发；
- 但 payload 内部各字段的 **byte offset / 类型** 属于"设备协议规范"（比如
  《飞管与飞控、自动飞行交互数据协议 V1.5》、FCC 状态帧协议），ICD 表里没有；
- 所以继续把这些偏移写死在代码里，但集中放在这个模块，方便审阅、review 和
  下个版本替换。

规则：只放"不来自 ICD、写成代码才合理"的常量。ICD 有的字段一律走 bundle。

每组常量的注释必须写明：
- 来自哪份设备协议 / 版本 / 页码
- 字节序 / 包体是否跳过 TSN header（8B）
"""
from __future__ import annotations

from typing import Dict


# ── TSN 外层包头 ──────────────────────────────────────────────────────
# 所有与设备之间跑的 TSN 帧前 8 字节是 TSN 层头部（协议填充 4B + 功能状态集 4B），
# 下面所有偏移都是相对跳过 TSN header 之后的 payload 首字节（index=0）。
TSN_HEADER_LEN = 8


# ══════════════════════════════════════════════════════════════════════
# 飞控状态/选择/故障 — 9001~9023
# 来源：飞控状态帧设备协议（内部文档，版本不可检索到 ICD）
# ══════════════════════════════════════════════════════════════════════

# 每个 FCC 在 payload 第一个字节放表决结果（位图 bit0=FCC1 主；bit1=FCC2 主；bit2=FCC3 主）
FCC_STATUS_VOTE_OFFSET = 0

# payload[0] = IRS 选择值（0/1/2 对应 IRS1/2/3）；payload[1] = RA 选择值（0/1）
FCC_CHANNEL_IRS_SEL_OFFSET = 0
FCC_CHANNEL_RA_SEL_OFFSET = 1

# payload[0] = IRS 故障位图（bit0~bit2 = IRS1~IRS3）；payload[1] = RA 故障位图（bit0/bit1 = RA1/RA2）
FCC_FAULT_IRS_BITMAP_OFFSET = 0
FCC_FAULT_RA_BITMAP_OFFSET = 1


# ══════════════════════════════════════════════════════════════════════
# 自动飞行数据（端口 9031~9034）
# 来源：《飞控发出数据-TSN版-V13.4》
# 注意：协议文档里字段编号是 1-based，这里转成 0-based offset 落地。
# 数据类型：`u8` = 1 字节无符号；`f32` = IEEE-754 小端 4 字节浮点
# ══════════════════════════════════════════════════════════════════════

#: 自动飞行结构体在 payload 里固定占 124 字节
AUTO_FLIGHT_FRAME_SIZE = 124

#: field_name → (0-based offset, type)
AUTO_FLIGHT_LAYOUT: Dict[str, tuple[int, str]] = {
    # 1..13：u8 状态字段
    "ap_engaged":                (0,  "u8"),
    "at_engaged":                (1,  "u8"),
    "air_ground":                (2,  "u8"),
    "flight_phase":              (3,  "u8"),
    "auto_mode":                 (4,  "u8"),
    "current_leg":               (5,  "u8"),
    "lat_mode_armed":            (6,  "u8"),
    "lat_mode_active":           (7,  "u8"),
    "lon_mode_armed":            (8,  "u8"),
    "lon_mode_active":           (9,  "u8"),
    "thr_mode_armed":            (10, "u8"),
    "thr_mode_active":           (11, "u8"),
    "af_warning":                (12, "u8"),
    # 14..52：f32 控制/参考
    "lat_track_error_m":                    (13, "f32"),
    "vert_track_error_m":                   (17, "f32"),
    "speed_cmd_mps":                        (21, "f32"),
    "altitude_cmd_m":                       (25, "f32"),
    "vs_cmd_mps":                           (29, "f32"),
    "roll_cmd_deg":                         (33, "f32"),
    "pitch_cmd_deg":                        (37, "f32"),
    "target_heading_deg":                   (41, "f32"),
    "target_thrust_n":                      (45, "f32"),
    "target_rotor_rpm":                     (49, "f32"),
    # 55..79：f32 当前态
    "current_altitude_m":                   (55, "f32"),
    "current_airspeed_mps":                 (59, "f32"),
    "current_airspeed_acc_mps2":            (63, "f32"),
    "current_groundspeed_mps":              (67, "f32"),
    "current_calibrated_airspeed_mps":      (71, "f32"),
    "current_calibrated_airspeed_acc_mps2": (75, "f32"),
    # 106..116：u8 来源/激活位
    "height_source":             (105, "u8"),
    "airspeed_source":           (106, "u8"),
    "ap_active":                 (107, "u8"),
    "at_active":                 (108, "u8"),
    "alt_active":                (112, "u8"),
    "vs_active":                 (113, "u8"),
    "mission_active":            (114, "u8"),
    "land_active":               (115, "u8"),
}


__all__ = [
    "TSN_HEADER_LEN",
    "FCC_STATUS_VOTE_OFFSET",
    "FCC_CHANNEL_IRS_SEL_OFFSET",
    "FCC_CHANNEL_RA_SEL_OFFSET",
    "FCC_FAULT_IRS_BITMAP_OFFSET",
    "FCC_FAULT_RA_BITMAP_OFFSET",
    "AUTO_FLIGHT_FRAME_SIZE",
    "AUTO_FLIGHT_LAYOUT",
]
